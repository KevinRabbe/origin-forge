from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

import origin_forge.production_dispatch_invocation as invocation_module
from origin_forge.ids import IdKind, validate_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
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
from origin_forge.simulation_service import SimulationService, SimulationServiceResult
from origin_forge.state import RunStatus, TaskStatus


class Phase47ESimulationInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase47e-simulation-invocation")
        goal_id = self.runtime.create_goal("invoke deterministic simulation")
        flow_id = self.runtime.create_flow(goal_id)
        self.task_id = self.runtime.create_task(
            flow_id,
            "run deterministic simulation",
            acceptance_criteria=("produce deterministic simulation evidence",),
            constraints=("no external inputs",),
            required_capabilities=("simulation.run",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

        full_catalog = build_builtin_capability_catalog()
        self.capability_catalog = CapabilityCatalog.create(
            (full_catalog.capability("simulation.run"),),
            (full_catalog.adapter("originforge.simulation.deterministic"),),
        )
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.capability_catalog,
            ordered_adapter_ids=("originforge.simulation.deterministic",),
            allowed_capability_ids=("simulation.run",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.capability_catalog)
        self.capability_store.publish_policy(
            self.routing_policy,
            self.capability_catalog,
        )
        route = self.capability_store.resolve_and_publish(
            self.task_id,
            self.capability_catalog.catalog_id,
            self.routing_policy.routing_policy_id,
        )

        self.validator_registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.capability_catalog)
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validator_registry,
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)
        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
        dispatch_store = ProductionDispatchStore(
            self.work_order_store,
            resolver_registry,
            binder_registry,
        )

        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            route.route_decision_id,
            payload=self._payload(),
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
            resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            self.work_order_store,
            resolver_registry,
            binder_registry,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            self.work_order_store,
            resolver_registry,
            binder_registry,
            bundle,
            binding,
        )
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.claim = acquire_dispatch_claim(
            self.runtime,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _payload() -> dict[str, object]:
        return {
            "seed": 47,
            "replicates": 2,
            "max_steps": 4,
            "stall_steps": 2,
            "initial_state_json": '{"ore":0}',
            "rules_json": '[{"consume":{},"priority":0,"probability_ppm":1000000,"produce":{"ore":1},"requires":{},"rule_id":"mine"}]',
            "invariants_json": "[]",
        }

    def _execution_row(self) -> dict:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT * FROM dispatch_executions WHERE claim_id = ?",
                (self.claim.claim_id,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        return dict(rows[0])

    def test_exact_simulation_owner_allocates_after_started_calls_service_once_and_returns(self) -> None:
        original_execute = SimulationService.execute
        observed_specs = []

        def observed_execute(service, task_id, spec):
            row = self._execution_row()
            self.assertEqual(row["status"], DispatchExecutionStatus.STARTED.value)
            self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)
            self.assertEqual(task_id, self.task_id)
            self.assertTrue(validate_id(spec.spec_id, IdKind.SIMULATION_SPEC))
            self.assertTrue(validate_id(spec.session_id, IdKind.SIMULATION_SESSION))
            self.assertTrue(validate_id(spec.workspace_id, IdKind.SIMULATION_WORKSPACE))
            observed_specs.append(spec)
            return original_execute(service, task_id, spec)

        with patch.object(
            SimulationService,
            "execute",
            autospec=True,
            side_effect=observed_execute,
        ) as execute:
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

        self.assertEqual(execute.call_count, 1)
        self.assertEqual(len(observed_specs), 1)
        self.assertIsNone(completed.policy_result)
        self.assertIsInstance(completed.simulation_result, SimulationServiceResult)
        self.assertEqual(completed.execution.status, DispatchExecutionStatus.RETURNED)
        self.assertEqual(completed.execution.execution_owner_id, "originforge.execution.simulation.deterministic@1")
        consumed = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(consumed.revision, 1)
        task = self.runtime.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task["revision"]), 2)
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["role"], SimulationService.RUN_ROLE)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task_id), [])

    def test_forged_typed_service_return_requires_recovery_without_false_returned(self) -> None:
        original_execute = SimulationService.execute

        def forged_execute(service, task_id, spec):
            result = original_execute(service, task_id, spec)
            return replace(result, result_hash="sha256:" + "0" * 64)

        with patch.object(
            SimulationService,
            "execute",
            autospec=True,
            side_effect=forged_execute,
        ) as execute:
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

        self.assertEqual(execute.call_count, 1)
        self.assertEqual(caught.exception.reason_code, "OWNER_RETURN_CONTRACT_MISMATCH")
        execution = self._execution_row()
        self.assertEqual(execution["status"], DispatchExecutionStatus.STARTED.value)
        active = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(active.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(active.revision, 0)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)

    def test_ordinary_simulation_owner_exception_records_raised_and_keeps_task_running(self) -> None:
        class SimulationFailure(RuntimeError):
            pass

        with patch.object(
            SimulationService,
            "execute",
            autospec=True,
            side_effect=SimulationFailure("sensitive backend text"),
        ) as execute:
            with self.assertRaises(ProductionDispatchInvocationError) as caught:
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

        self.assertEqual(execute.call_count, 1)
        self.assertNotIsInstance(caught.exception, ProductionDispatchInvocationRecoveryRequired)
        self.assertNotIn("sensitive backend text", str(caught.exception))
        self.assertIn("SimulationFailure", str(caught.exception))
        execution = self._execution_row()
        self.assertEqual(execution["status"], DispatchExecutionStatus.RAISED.value)
        consumed = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)

    def test_base_exception_leaves_started_active_running_and_never_replays(self) -> None:
        with patch.object(
            SimulationService,
            "execute",
            autospec=True,
            side_effect=KeyboardInterrupt(),
        ) as execute:
            with self.assertRaises(KeyboardInterrupt):
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

        self.assertEqual(execute.call_count, 1)
        execution = self._execution_row()
        self.assertEqual(execution["status"], DispatchExecutionStatus.STARTED.value)
        active = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(active.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(active.revision, 0)
        task = self.runtime.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task["revision"]), 2)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_coordinator_source_is_closed_to_one_code_and_one_simulation_call_site(self) -> None:
        source = inspect.getsource(invocation_module.dispatch_claim_once)
        tree = ast.parse(source)
        drive_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "drive"
        ]
        execute_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ]
        self.assertEqual(len(drive_calls), 1)
        self.assertEqual(len(execute_calls), 1)
        self.assertFalse(
            any(isinstance(node, (ast.For, ast.AsyncFor, ast.While)) for node in ast.walk(tree))
        )
        self.assertNotIn("importlib", source)
        self.assertNotIn("getattr(", source)
        self.assertNotIn("callable(", source)


if __name__ == "__main__":
    unittest.main()
