from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import origin_forge.production_manager_dispatch_admission as admission_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmissionDetail,
    ManagerDispatchAdmissionStatus,
    inspect_manager_dispatch_admission_readonly,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


def _state_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    if not root.exists():
        return ()
    rows: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows.append((relative, b"<symlink>"))
        elif path.is_file():
            rows.append((relative, path.read_bytes()))
    return tuple(rows)


class ProductionManagerDispatchAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("manager-dispatch-admission")
        self.goal_id = self.runtime.create_goal("dispatch bounded ready tasks")
        self.flow_id = self.runtime.create_flow(self.goal_id)

        self.capability_catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.capability_catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.capability_catalog)
        self.capability_store.publish_policy(
            self.routing_policy,
            self.capability_catalog,
        )

        self.validator_registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.capability_catalog)
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validator_registry,
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)
        self.resolver_registry = build_dispatch_input_resolver_registry()
        self.binder_registry = build_builtin_dispatch_binder_registry()
        self.dispatch_store = ProductionDispatchStore(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _create_ready_task(self, objective: str, *, priority: int = 0) -> str:
        task_id = self.runtime.create_task(
            self.flow_id,
            objective,
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
            priority=priority,
        )
        activation = activate_dependency_ready_task(self.runtime, task_id, 0)
        self.assertEqual(activation.new_revision, 1)
        return task_id

    def _publish_chain(
        self,
        task_id: str,
        *,
        seed_path: str = "src/example.py",
    ):
        route = self.capability_store.resolve_and_publish(
            task_id,
            self.capability_catalog.catalog_id,
            self.routing_policy.routing_policy_id,
        )
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": [seed_path],
                "structural_context": True,
            },
        )
        work_order_audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            work_order,
        )
        self.work_order_store.publish_work_order(work_order)
        self.work_order_store.publish_audit(work_order_audit)
        return self._publish_binding_chain(work_order, work_order_audit)

    def _publish_binding_chain(self, work_order, work_order_audit):
        bundle = create_input_resolution_bundle(
            self.work_order_store,
            self.resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            binding,
        )
        self.dispatch_store.publish_input_resolution(bundle)
        self.dispatch_store.publish_binding(binding)
        self.dispatch_store.publish_audit(binding_audit)
        return work_order, work_order_audit, bundle, binding, binding_audit

    def test_queued_task_is_not_activated_or_admitted(self) -> None:
        task_id = self.runtime.create_task(
            self.flow_id,
            "remain queued",
            required_capabilities=("code.change",),
        )
        before = _state_snapshot(self.runtime.state_dir)

        admission = inspect_manager_dispatch_admission_readonly(self.runtime)

        self.assertEqual(admission.status, ManagerDispatchAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidates, ())
        task = self.runtime.get_task(task_id)
        self.assertEqual(task["status"], TaskStatus.QUEUED.value)
        self.assertEqual(task["revision"], 0)
        self.assertEqual(before, _state_snapshot(self.runtime.state_dir))

    def test_current_ready_chain_is_admitted_without_state_mutation(self) -> None:
        task_id = self._create_ready_task("dispatch me")
        _, _, bundle, binding, binding_audit = self._publish_chain(task_id)
        before = _state_snapshot(self.runtime.state_dir)

        admission = inspect_manager_dispatch_admission_readonly(self.runtime)

        self.assertEqual(admission.status, ManagerDispatchAdmissionStatus.COMPLETE)
        self.assertEqual(admission.scanned_audit_count, 1)
        self.assertEqual(admission.current_chain_count, 1)
        self.assertEqual(admission.candidate_count, 1)
        candidate = admission.candidates[0]
        self.assertEqual(candidate.task_id, task_id)
        self.assertEqual(candidate.task_revision, 1)
        self.assertEqual(candidate.input_resolution_id, bundle.input_resolution_id)
        self.assertEqual(candidate.dispatch_binding_id, binding.dispatch_binding_id)
        self.assertEqual(candidate.binding_audit_id, binding_audit.binding_audit_id)
        self.assertEqual(before, _state_snapshot(self.runtime.state_dir))

    def test_active_claim_excludes_otherwise_current_task(self) -> None:
        task_id = self._create_ready_task("claimed task")
        _, _, _, binding, binding_audit = self._publish_chain(task_id)
        claim = acquire_dispatch_claim(
            self.runtime,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            1,
        )
        self.assertEqual(claim.task_id, task_id)
        before = _state_snapshot(self.runtime.state_dir)

        admission = inspect_manager_dispatch_admission_readonly(self.runtime)

        self.assertEqual(admission.status, ManagerDispatchAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 0)
        self.assertEqual(admission.active_claim_exclusion_count, 1)
        self.assertEqual(before, _state_snapshot(self.runtime.state_dir))

    def test_candidates_sort_by_created_at_then_task_id_not_priority(self) -> None:
        first_task = self._create_ready_task("first", priority=-1000)
        second_task = self._create_ready_task("second", priority=1000)
        self._publish_chain(second_task, seed_path="src/second.py")
        self._publish_chain(first_task, seed_path="src/first.py")

        admission = inspect_manager_dispatch_admission_readonly(self.runtime)

        self.assertEqual(admission.status, ManagerDispatchAdmissionStatus.COMPLETE)
        self.assertEqual(
            [candidate.task_id for candidate in admission.candidates],
            [first_task, second_task],
        )

    def test_equivalent_duplicate_current_chains_collapse_by_lexical_evidence_ids(self) -> None:
        task_id = self._create_ready_task("duplicate authority")
        work_order, work_order_audit, bundle1, binding1, audit1 = self._publish_chain(
            task_id
        )
        _, _, bundle2, binding2, audit2 = self._publish_binding_chain(
            work_order,
            work_order_audit,
        )

        admission = inspect_manager_dispatch_admission_readonly(self.runtime)

        self.assertEqual(admission.status, ManagerDispatchAdmissionStatus.COMPLETE)
        self.assertEqual(admission.current_chain_count, 2)
        self.assertEqual(admission.candidate_count, 1)
        expected = min(
            (
                audit1.binding_audit_id,
                binding1.dispatch_binding_id,
                bundle1.input_resolution_id,
            ),
            (
                audit2.binding_audit_id,
                binding2.dispatch_binding_id,
                bundle2.input_resolution_id,
            ),
        )
        candidate = admission.candidates[0]
        self.assertEqual(candidate.representative_key(), expected)

    def test_conflicting_current_authority_is_ambiguous_and_selects_no_candidate_for_task(self) -> None:
        task_id = self._create_ready_task("ambiguous authority")
        self._publish_chain(task_id, seed_path="src/one.py")
        self._publish_chain(task_id, seed_path="src/two.py")

        admission = inspect_manager_dispatch_admission_readonly(self.runtime)

        self.assertEqual(
            admission.status,
            ManagerDispatchAdmissionStatus.AMBIGUOUS_AUTHORITY,
        )
        self.assertEqual(admission.current_chain_count, 2)
        self.assertEqual(admission.candidate_count, 0)
        self.assertEqual(admission.ambiguous_task_ids, (task_id,))

    def test_scan_and_candidate_limits_fail_closed_without_truncation(self) -> None:
        task_id = self._create_ready_task("bounded scan")
        self._publish_chain(task_id)

        with mock.patch.object(admission_module, "_MAX_MANAGER_AUDIT_CHAINS", 0):
            scan_limited = inspect_manager_dispatch_admission_readonly(self.runtime)
        self.assertEqual(
            scan_limited.status,
            ManagerDispatchAdmissionStatus.LIMIT_EXCEEDED,
        )
        self.assertEqual(scan_limited.candidate_count, 0)
        self.assertEqual(
            scan_limited.detail,
            ManagerDispatchAdmissionDetail.PHASE34_SCAN_LIMIT_EXCEEDED,
        )

        with mock.patch.object(admission_module, "_MAX_MANAGER_CANDIDATES", 0):
            candidate_limited = inspect_manager_dispatch_admission_readonly(self.runtime)
        self.assertEqual(
            candidate_limited.status,
            ManagerDispatchAdmissionStatus.LIMIT_EXCEEDED,
        )
        self.assertEqual(candidate_limited.candidate_count, 0)
        self.assertEqual(
            candidate_limited.detail,
            ManagerDispatchAdmissionDetail.CANDIDATE_LIMIT_EXCEEDED,
        )

    def test_undeclared_binding_audit_entry_invalidates_complete_admission(self) -> None:
        task_id = self._create_ready_task("valid before corruption")
        self._publish_chain(task_id)
        category = (
            self.runtime.state_dir
            / "production-dispatch-bindings"
            / "binding-audits"
        )
        (category / "undeclared.txt").write_text("invalid", encoding="utf-8")
        before = _state_snapshot(self.runtime.state_dir)

        admission = inspect_manager_dispatch_admission_readonly(self.runtime)

        self.assertEqual(admission.status, ManagerDispatchAdmissionStatus.INVALID_STATE)
        self.assertEqual(admission.candidate_count, 0)
        self.assertEqual(
            admission.detail,
            ManagerDispatchAdmissionDetail.INVALID_PHASE34_EVIDENCE,
        )
        self.assertEqual(before, _state_snapshot(self.runtime.state_dir))


if __name__ == "__main__":
    unittest.main()
