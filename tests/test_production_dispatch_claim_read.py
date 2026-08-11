from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_dispatch_claim_read as claim_read_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_binding_models import (
    DispatchBindingCurrentnessStatus,
)
from origin_forge.production_dispatch_claim_lifecycle import (
    interrupt_dispatch_claim,
    release_dispatch_claim,
)
from origin_forge.production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    ProductionDispatchClaimReadError,
    inspect_dispatch_claim_currentness_readonly,
    inspect_task_activation_eligibility_readonly,
    read_dispatch_claim,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
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


class ProductionDispatchClaimReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dispatch-claim-read")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _chain(self, *, activate: bool) -> SimpleNamespace:
        goal_id = self.runtime.create_goal("inspect exact dispatch claim")
        flow_id = self.runtime.create_flow(goal_id)
        task_id = self.runtime.create_task(
            flow_id,
            "change code through bounded retry",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        if activate:
            activation = activate_dependency_ready_task(self.runtime, task_id, 0)
            task_revision = activation.new_revision
        else:
            activation = None
            task_revision = 0

        phase32 = build_builtin_capability_catalog()
        policy = CapabilityRoutingPolicy.create(
            phase32,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(phase32)
        capability_store.publish_policy(policy, phase32)
        route = capability_store.resolve_and_publish(
            task_id,
            phase32.catalog_id,
            policy.routing_policy_id,
        )

        validator_registry = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(phase32)
        work_order_store = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            validator_registry,
        )
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        work_order = create_current_work_order(
            self.runtime,
            capability_store,
            dispatch_catalog,
            validator_registry,
            route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
            },
        )
        work_order_audit = audit_work_order_frozen(
            capability_store,
            dispatch_catalog,
            validator_registry,
            work_order,
        )
        work_order_store.publish_work_order(work_order)
        work_order_store.publish_audit(work_order_audit)

        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
        bundle = create_input_resolution_bundle(
            work_order_store,
            resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            work_order_store,
            resolver_registry,
            binder_registry,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            work_order_store,
            resolver_registry,
            binder_registry,
            bundle,
            binding,
        )
        dispatch_store = ProductionDispatchStore(
            work_order_store,
            resolver_registry,
            binder_registry,
        )
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        return SimpleNamespace(
            task_id=task_id,
            task_revision=task_revision,
            activation=activation,
            bundle=bundle,
            binding=binding,
            binding_audit=binding_audit,
        )

    def _claim(self, *, activate: bool = True):
        chain = self._chain(activate=activate)
        if activate:
            claim = acquire_dispatch_claim(
                self.runtime,
                chain.binding.dispatch_binding_id,
                chain.binding_audit.binding_audit_id,
                chain.task_revision,
            )
        else:
            claim = DispatchClaim(
                claim_id=new_id(IdKind.DISPATCH_CLAIM),
                project_id=self.runtime.project_id(),
                task_id=chain.task_id,
                task_revision=chain.binding.task_revision,
                task_content_hash=chain.binding.task_content_hash,
                work_order_id=chain.binding.work_order_id,
                work_order_hash=chain.binding.work_order_hash,
                work_order_audit_id=chain.binding.work_order_audit_id,
                work_order_audit_hash=chain.binding.work_order_audit_hash,
                input_resolution_id=chain.bundle.input_resolution_id,
                input_resolution_hash=chain.bundle.content_hash,
                dispatch_binding_id=chain.binding.dispatch_binding_id,
                dispatch_binding_hash=chain.binding.content_hash,
                binding_audit_id=chain.binding_audit.binding_audit_id,
                binding_audit_hash=chain.binding_audit.content_hash,
                selected_adapter_id=chain.binding.selected_adapter_id,
                selected_adapter_fingerprint=chain.binding.selected_adapter_fingerprint,
                dispatch_contract_id=chain.binding.dispatch_contract_id,
                dispatch_contract_hash=chain.binding.dispatch_contract_hash,
                binder_id=chain.binding.binder_id,
                binder_fingerprint=chain.binding.binder_fingerprint,
                status=DispatchClaimStatus.ACTIVE,
                revision=0,
                created_at="2026-08-11T18:00:00Z",
                updated_at="2026-08-11T18:00:00Z",
                terminal_reason=None,
            )
            values = claim.to_dict()
            with self.runtime.store.session() as conn:
                conn.execute(
                    """INSERT INTO dispatch_claims(
                        claim_id, project_id, task_id, task_revision, task_content_hash,
                        work_order_id, work_order_hash,
                        work_order_audit_id, work_order_audit_hash,
                        input_resolution_id, input_resolution_hash,
                        dispatch_binding_id, dispatch_binding_hash,
                        binding_audit_id, binding_audit_hash,
                        selected_adapter_id, selected_adapter_fingerprint,
                        dispatch_contract_id, dispatch_contract_hash,
                        binder_id, binder_fingerprint,
                        status, revision, created_at, updated_at, terminal_reason
                    ) VALUES (
                        :claim_id, :project_id, :task_id, :task_revision, :task_content_hash,
                        :work_order_id, :work_order_hash,
                        :work_order_audit_id, :work_order_audit_hash,
                        :input_resolution_id, :input_resolution_hash,
                        :dispatch_binding_id, :dispatch_binding_hash,
                        :binding_audit_id, :binding_audit_hash,
                        :selected_adapter_id, :selected_adapter_fingerprint,
                        :dispatch_contract_id, :dispatch_contract_hash,
                        :binder_id, :binder_fingerprint,
                        :status, :revision, :created_at, :updated_at, :terminal_reason
                    )""",
                    values,
                )
        return chain, claim

    def test_exact_active_claim_reads_and_reports_current_without_mutation(self) -> None:
        chain, claim = self._claim()
        task_before = self.runtime.get_task(chain.task_id)
        read = read_dispatch_claim(self.runtime, claim.claim_id)
        currentness = inspect_dispatch_claim_currentness_readonly(
            self.runtime,
            claim.claim_id,
        )
        self.assertEqual(read.to_dict(), claim.to_dict())
        self.assertEqual(currentness.status, DispatchClaimCurrentnessStatus.CURRENT_ACTIVE)
        self.assertIsNone(currentness.detail)
        self.assertEqual(self.runtime.get_task(chain.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(chain.task_id), [])

    def test_activation_eligibility_is_read_only_and_exact(self) -> None:
        chain = self._chain(activate=False)
        before = self.runtime.get_task(chain.task_id)
        eligibility = inspect_task_activation_eligibility_readonly(
            self.runtime,
            chain.task_id,
        )
        self.assertTrue(eligibility.eligible)
        self.assertEqual(eligibility.task_status, TaskStatus.QUEUED)
        self.assertEqual(eligibility.task_revision, 0)
        self.assertIsNone(eligibility.detail)
        self.assertEqual(self.runtime.get_task(chain.task_id), before)

        activate_dependency_ready_task(self.runtime, chain.task_id, 0)
        after = inspect_task_activation_eligibility_readonly(
            self.runtime,
            chain.task_id,
        )
        self.assertFalse(after.eligible)
        self.assertEqual(after.task_status, TaskStatus.READY)
        self.assertIn("not QUEUED", after.detail or "")

    def test_queued_self_consistent_claim_is_not_ready(self) -> None:
        _, claim = self._claim(activate=False)
        currentness = inspect_dispatch_claim_currentness_readonly(
            self.runtime,
            claim.claim_id,
        )
        self.assertEqual(currentness.status, DispatchClaimCurrentnessStatus.NOT_READY)

    def test_task_revision_drift_is_stale_task(self) -> None:
        chain, claim = self._claim()
        self.runtime.transition_task(
            chain.task_id,
            TaskStatus.RUNNING,
            expected_revision=chain.task_revision,
        )
        currentness = inspect_dispatch_claim_currentness_readonly(
            self.runtime,
            claim.claim_id,
        )
        self.assertEqual(currentness.status, DispatchClaimCurrentnessStatus.STALE_TASK)

    def test_terminal_claims_remain_historical_and_not_current(self) -> None:
        _, released_claim = self._claim()
        released = release_dispatch_claim(self.runtime, released_claim.claim_id, 0)
        released_state = inspect_dispatch_claim_currentness_readonly(
            self.runtime,
            released.claim_id,
        )
        self.assertEqual(released_state.status, DispatchClaimCurrentnessStatus.RELEASED)
        self.assertEqual(released_state.detail, released.terminal_reason)

        _, interrupted_claim = self._claim()
        interrupted = interrupt_dispatch_claim(
            self.runtime,
            interrupted_claim.claim_id,
            0,
            "explicit reader recovery test",
        )
        interrupted_state = inspect_dispatch_claim_currentness_readonly(
            self.runtime,
            interrupted.claim_id,
        )
        self.assertEqual(
            interrupted_state.status,
            DispatchClaimCurrentnessStatus.INTERRUPTED,
        )
        self.assertEqual(interrupted_state.detail, interrupted.terminal_reason)

    def test_frozen_claim_phase34_relation_tamper_is_invalid(self) -> None:
        _, claim = self._claim()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE dispatch_claims SET dispatch_binding_hash = ? WHERE claim_id = ?",
                ("9" * 64, claim.claim_id),
            )
        currentness = inspect_dispatch_claim_currentness_readonly(
            self.runtime,
            claim.claim_id,
        )
        self.assertEqual(currentness.status, DispatchClaimCurrentnessStatus.INVALID)
        self.assertIn("frozen authority", currentness.detail or "")

    def test_phase34_noncurrent_result_maps_to_stale_binding(self) -> None:
        _, claim = self._claim()
        fake = SimpleNamespace(status=DispatchBindingCurrentnessStatus.BINDER_DRIFT)
        with patch.object(
            claim_read_module,
            "inspect_dispatch_binding_currentness_readonly",
            return_value=fake,
        ):
            currentness = inspect_dispatch_claim_currentness_readonly(
                self.runtime,
                claim.claim_id,
            )
        self.assertEqual(
            currentness.status,
            DispatchClaimCurrentnessStatus.STALE_BINDING,
        )
        self.assertIn("BINDER_DRIFT", currentness.detail or "")

    def test_immutable_reads_create_no_sqlite_sidecars_or_file_changes(self) -> None:
        chain, claim = self._claim()
        state = self.runtime.state_dir
        database = self.runtime.store.db_path
        config = state / "config.toml"
        before_names = {path.name for path in state.iterdir()}
        before_db = database.stat()
        before_config = config.read_bytes()

        read_dispatch_claim(self.runtime, claim.claim_id)
        inspect_dispatch_claim_currentness_readonly(self.runtime, claim.claim_id)
        inspect_task_activation_eligibility_readonly(self.runtime, chain.task_id)

        after_db = database.stat()
        self.assertEqual({path.name for path in state.iterdir()}, before_names)
        self.assertEqual(config.read_bytes(), before_config)
        self.assertEqual(
            (after_db.st_dev, after_db.st_ino, after_db.st_size, after_db.st_mtime_ns),
            (before_db.st_dev, before_db.st_ino, before_db.st_size, before_db.st_mtime_ns),
        )
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(str(database) + suffix).exists())

    def test_uninitialized_reads_fail_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            state = root / ".origin-forge"
            self.assertFalse(state.exists())
            with self.assertRaises(ProductionDispatchClaimReadError):
                read_dispatch_claim(runtime, new_id(IdKind.DISPATCH_CLAIM))
            with self.assertRaises(ProductionDispatchClaimReadError):
                inspect_task_activation_eligibility_readonly(
                    runtime,
                    new_id(IdKind.TASK),
                )
            self.assertFalse(state.exists())

    def test_reader_source_has_no_writer_or_execution_surface(self) -> None:
        source = inspect.getsource(claim_read_module)
        for forbidden_text in (
            ".store",
            "BEGIN IMMEDIATE",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "subprocess",
            "importlib",
            "production_dispatch_claims",
            "production_dispatch_claim_lifecycle",
        ):
            self.assertNotIn(forbidden_text, source)
        tree = ast.parse(source)
        forbidden_calls = {
            "drive",
            "generate",
            "dispatch",
            "start_run",
            "create_run",
            "finish_run",
            "record_verification",
            "transition_task",
            "transition_flow",
            "transition_goal",
            "acquire_dispatch_claim",
            "release_dispatch_claim",
            "interrupt_dispatch_claim",
            "create_workspace",
            "lease",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))
        execute_receivers = [
            node.func.value.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and isinstance(node.func.value, ast.Name)
        ]
        self.assertTrue(execute_receivers)
        self.assertEqual(set(execute_receivers), {"conn"})


if __name__ == "__main__":
    unittest.main()
