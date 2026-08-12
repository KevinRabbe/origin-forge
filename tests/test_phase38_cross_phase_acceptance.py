from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
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
from origin_forge.production_dispatch_invocation import CompletedDispatchInvocation
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_manager_dispatch_admission import (
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
NOW = "2026-08-12T18:30:00Z"


class Phase38CrossPhaseAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase38-cross-phase")
        self.goal_id = self.runtime.create_goal("dispatch one admitted task")
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

    def _ready_chain(self, objective: str, *, priority: int = 0):
        task_id = self.runtime.create_task(
            self.flow_id,
            objective,
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
            priority=priority,
        )
        activate_dependency_ready_task(self.runtime, task_id, 0)
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
                "context_seed_paths": [f"src/{task_id[-6:]}.py"],
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
        return task_id, binding, binding_audit

    def _completed_for_claim(
        self,
        claim_id: str,
        outcome: PolicyOutcome = PolicyOutcome.BLOCKED,
    ) -> CompletedDispatchInvocation:
        claim = read_dispatch_claim(self.runtime, claim_id)
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
        return CompletedDispatchInvocation(
            execution,
            PolicyResult(
                task_id=claim.task_id,
                outcome=outcome,
                action=PolicyAction.STOP,
                reason="mocked exact Phase-37 boundary",
                executor_attempts=0,
                attempts_started=0,
            ),
        )

    def test_real_admission_and_claim_call_exact_phase37_once_without_outcome_reinterpretation(self) -> None:
        first_task, first_binding, _ = self._ready_chain("first", priority=-1000)
        self._ready_chain("second", priority=1000)
        calls: list[str] = []

        def phase37_boundary(runtime, claim_id, expected_revision):
            self.assertIs(runtime, self.runtime)
            self.assertEqual(expected_revision, 0)
            calls.append(claim_id)
            return self._completed_for_claim(claim_id, PolicyOutcome.QUARANTINED)

        with patch.object(
            tick_module,
            "dispatch_claim_once",
            side_effect=phase37_boundary,
        ):
            result = dispatch_manager_tick(self.runtime)

        self.assertEqual(result.status, ManagerDispatchTickStatus.DISPATCH_RETURNED)
        self.assertEqual(result.task_id, first_task)
        self.assertEqual(result.dispatch_binding_id, first_binding.dispatch_binding_id)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.runtime.get_task(first_task)["status"], TaskStatus.READY.value)
        claim = read_dispatch_claim(self.runtime, result.claim_id)
        self.assertEqual(claim.task_id, first_task)
        self.assertEqual(claim.revision, 0)

    def test_two_concurrent_ticks_for_one_task_produce_at_most_one_phase37_call(self) -> None:
        task_id, _, _ = self._ready_chain("one concurrent task")
        lock = threading.Lock()
        calls: list[str] = []

        def phase37_boundary(runtime, claim_id, expected_revision):
            with lock:
                calls.append(claim_id)
            return self._completed_for_claim(claim_id, PolicyOutcome.SUCCEEDED)

        with patch.object(
            tick_module,
            "dispatch_claim_once",
            side_effect=phase37_boundary,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = tuple(pool.map(lambda _: dispatch_manager_tick(self.runtime), range(2)))

        self.assertLessEqual(len(calls), 1)
        self.assertEqual(len(set(calls)), len(calls))
        self.assertTrue(
            all(
                result.status
                in {
                    ManagerDispatchTickStatus.DISPATCH_RETURNED,
                    ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED,
                    ManagerDispatchTickStatus.NO_ELIGIBLE_TASK,
                }
                for result in results
            )
        )
        with self.runtime.store.session() as conn:
            active = conn.execute(
                "SELECT COUNT(*) AS n FROM dispatch_claims WHERE task_id = ? AND status = 'ACTIVE'",
                (task_id,),
            ).fetchone()["n"]
        self.assertLessEqual(int(active), 1)

    def test_stale_selected_task_at_claim_boundary_does_not_fall_through_to_second_task(self) -> None:
        first_task, first_binding, _ = self._ready_chain("first stale")
        second_task, _, _ = self._ready_chain("second must not be attempted")
        admission = inspect_manager_dispatch_admission_readonly(self.runtime)
        self.assertEqual(admission.candidates[0].task_id, first_task)
        self.assertEqual(admission.candidates[1].task_id, second_task)
        real_acquire = acquire_dispatch_claim
        acquire_calls: list[str] = []

        def stale_then_acquire(runtime, binding_id, audit_id, revision):
            acquire_calls.append(binding_id)
            task = runtime.get_task(first_task)
            runtime.transition_task(
                first_task,
                TaskStatus.RUNNING,
                expected_revision=int(task["revision"]),
            )
            return real_acquire(runtime, binding_id, audit_id, revision)

        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=admission,
            ),
            patch.object(
                tick_module,
                "acquire_dispatch_claim",
                side_effect=stale_then_acquire,
            ),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=AssertionError("Phase 37 must not be invoked"),
            ),
        ):
            result = dispatch_manager_tick(self.runtime)

        self.assertEqual(result.status, ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED)
        self.assertEqual(acquire_calls, [first_binding.dispatch_binding_id])
        with self.runtime.store.session() as conn:
            second_claims = conn.execute(
                "SELECT COUNT(*) AS n FROM dispatch_claims WHERE task_id = ?",
                (second_task,),
            ).fetchone()["n"]
        self.assertEqual(int(second_claims), 0)


if __name__ == "__main__":
    unittest.main()
