from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_manager_dispatch_tick as tick_module
from origin_forge.ids import IdKind, new_id
from origin_forge.orchestration_policy import PolicyAction, PolicyOutcome, PolicyResult
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution_models import (
    DispatchExecution,
    DispatchExecutionStatus,
)
from origin_forge.production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationRecoveryRequired,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmissionStatus,
    inspect_manager_dispatch_admission_readonly,
)
from origin_forge.production_manager_dispatch_tick import (
    ManagerDispatchTickStatus,
    dispatch_manager_tick,
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


H = "a" * 64
NOW = "2026-08-12T18:00:00Z"


class Phase38ManagerDispatchAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase38-cross-phase-acceptance")
        self.goal_id = self.runtime.create_goal("govern one Manager dispatch tick")
        self.flow_id = self.runtime.create_flow(self.goal_id)

        self.catalog = build_builtin_capability_catalog()
        self.policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.policy, self.catalog)
        self.validator_registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
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

    def _publish_chain(self, task_id: str, seed_path: str):
        route = self.capability_store.resolve_and_publish(
            task_id,
            self.catalog.catalog_id,
            self.policy.routing_policy_id,
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
        return binding, binding_audit

    @staticmethod
    def _completed_for_claim(runtime: OriginForgeRuntime, claim_id: str):
        claim = read_dispatch_claim(runtime, claim_id)
        execution = DispatchExecution(
            execution_id=new_id(IdKind.DISPATCH_EXECUTION),
            project_id=claim.project_id,
            claim_id=claim.claim_id,
            claim_revision_at_start=claim.revision,
            task_id=claim.task_id,
            task_revision=claim.task_revision,
            task_content_hash=claim.task_content_hash,
            work_order_id=claim.work_order_id,
            work_order_hash=claim.work_order_hash,
            input_resolution_id=claim.input_resolution_id,
            input_resolution_hash=claim.input_resolution_hash,
            dispatch_binding_id=claim.dispatch_binding_id,
            dispatch_binding_hash=claim.dispatch_binding_hash,
            binding_audit_id=claim.binding_audit_id,
            binding_audit_hash=claim.binding_audit_hash,
            selected_adapter_id=claim.selected_adapter_id,
            selected_adapter_fingerprint=claim.selected_adapter_fingerprint,
            dispatch_contract_id=claim.dispatch_contract_id,
            dispatch_contract_hash=claim.dispatch_contract_hash,
            binder_id=claim.binder_id,
            binder_fingerprint=claim.binder_fingerprint,
            execution_owner_id="originforge.execution.bounded-retry@1",
            execution_owner_fingerprint=H,
            runtime_dependency_plan_hash=H,
            status=DispatchExecutionStatus.RETURNED,
            revision=1,
            created_at=NOW,
            updated_at=NOW,
            terminal_detail_hash=H,
        )
        policy = PolicyResult(
            task_id=claim.task_id,
            outcome=PolicyOutcome.BLOCKED,
            action=PolicyAction.STOP,
            reason="Manager must not reinterpret policy outcome",
            executor_attempts=0,
            attempts_started=0,
        )
        return CompletedDispatchInvocation(execution, policy)

    def test_ready_task_without_phase34_authority_is_not_admitted_or_claimed(self) -> None:
        task_id = self._create_ready_task("ready but no dispatch authority")
        admission = inspect_manager_dispatch_admission_readonly(self.runtime)
        self.assertEqual(admission.status, ManagerDispatchAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 0)

        with patch.object(
            tick_module,
            "acquire_dispatch_claim",
            side_effect=AssertionError("claim attempted without Phase-34 authority"),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.NO_ELIGIBLE_TASK)
        task = self.runtime.get_task(task_id)
        self.assertEqual(task["status"], TaskStatus.READY.value)
        self.assertEqual(task["revision"], 1)
        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)

    def test_concurrent_manager_ticks_create_one_claim_and_one_phase37_call(self) -> None:
        task_id = self._create_ready_task("one concurrent Manager winner")
        self._publish_chain(task_id, "src/concurrent.py")
        real_acquire = acquire_dispatch_claim
        claim_barrier = threading.Barrier(2)
        results = []
        failures: list[BaseException] = []
        lock = threading.Lock()

        def racing_acquire(runtime, binding_id, audit_id, revision):
            claim_barrier.wait(timeout=15)
            return real_acquire(runtime, binding_id, audit_id, revision)

        def fake_dispatch(runtime, claim_id, expected_revision):
            self.assertEqual(expected_revision, 0)
            return self._completed_for_claim(runtime, claim_id)

        def worker() -> None:
            runtime = OriginForgeRuntime(self.root)
            try:
                value = dispatch_manager_tick(runtime)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(tick_module, "acquire_dispatch_claim", side_effect=racing_acquire),
            patch.object(tick_module, "dispatch_claim_once", side_effect=fake_dispatch) as dispatch,
        ):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(
            sum(result.status is ManagerDispatchTickStatus.DISPATCH_RETURNED for result in results),
            1,
        )
        self.assertEqual(
            sum(result.status is ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED for result in results),
            1,
        )
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT claim_id, status FROM dispatch_claims WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ACTIVE")

    def test_stale_selected_authority_at_claim_does_not_fall_through_to_second_task(self) -> None:
        first_task = self._create_ready_task("candidate one")
        second_task = self._create_ready_task("candidate two")
        chains = {
            first_task: self._publish_chain(first_task, "src/first.py"),
            second_task: self._publish_chain(second_task, "src/second.py"),
        }
        admission = inspect_manager_dispatch_admission_readonly(self.runtime)
        self.assertEqual(admission.candidate_count, 2)
        selected = admission.candidates[0]
        other = admission.candidates[1]
        self.assertNotEqual(selected.task_id, other.task_id)
        real_acquire = acquire_dispatch_claim
        acquire_calls = []

        def stale_before_acquire(runtime, binding_id, audit_id, revision):
            acquire_calls.append((binding_id, audit_id, revision))
            self.runtime.transition_task(
                selected.task_id,
                TaskStatus.RUNNING,
                expected_revision=revision,
            )
            return real_acquire(runtime, binding_id, audit_id, revision)

        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=admission,
            ),
            patch.object(tick_module, "acquire_dispatch_claim", side_effect=stale_before_acquire),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=AssertionError("dispatch reached after stale claim"),
            ),
        ):
            result = dispatch_manager_tick(self.runtime)

        self.assertEqual(result.status, ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED)
        self.assertEqual(
            acquire_calls,
            [
                (
                    selected.dispatch_binding_id,
                    selected.binding_audit_id,
                    selected.task_revision,
                )
            ],
        )
        with self.runtime.store.session() as conn:
            selected_claims = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (selected.task_id,),
            ).fetchone()[0]
            other_claims = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (other.task_id,),
            ).fetchone()[0]
        self.assertEqual(selected_claims, 0)
        self.assertEqual(other_claims, 0)
        self.assertIn(selected.task_id, chains)
        self.assertIn(other.task_id, chains)

    def test_recovery_required_after_real_claim_is_surfaced_once_without_replay(self) -> None:
        task_id = self._create_ready_task("recovery stops the Manager tick")
        self._publish_chain(task_id, "src/recovery.py")
        execution_id = new_id(IdKind.DISPATCH_EXECUTION)
        recovery = ProductionDispatchInvocationRecoveryRequired(
            execution_id,
            "RETURNED_TERMINALIZATION_FAILED",
        )
        with patch.object(
            tick_module,
            "dispatch_claim_once",
            side_effect=recovery,
        ) as dispatch:
            result = dispatch_manager_tick(self.runtime)

        self.assertEqual(result.status, ManagerDispatchTickStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.execution_id, execution_id)
        self.assertEqual(dispatch.call_count, 1)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT claim_id, status FROM dispatch_claims WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
