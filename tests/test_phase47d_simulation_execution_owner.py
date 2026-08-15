from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from unittest.mock import patch

import origin_forge.production_dispatch_execution as execution_module
import origin_forge.production_execution_assembly as assembly_module
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
from origin_forge.production_dispatch_execution import begin_dispatch_execution
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_assembly import (
    DeterministicSimulationExecutionPayload,
    ProductionExecutionAssemblyError,
    assemble_production_execution_dependencies,
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
from origin_forge.simulation_service import SimulationService
from origin_forge.state import TaskStatus


class Phase47DSimulationExecutionOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase47d-simulation-execution")
        goal_id = self.runtime.create_goal("execute deterministic simulation")
        flow_id = self.runtime.create_flow(goal_id)
        self.task_id = self.runtime.create_task(
            flow_id,
            "run deterministic simulation",
            acceptance_criteria=("produce deterministic simulation evidence",),
            constraints=("no external inputs",),
            required_capabilities=("simulation.run",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.READY.value,
        )

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

        validator_registry = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(self.capability_catalog)
        work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            validator_registry,
        )
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
        dispatch_store = ProductionDispatchStore(
            work_order_store,
            resolver_registry,
            binder_registry,
        )

        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            dispatch_catalog,
            validator_registry,
            route.route_decision_id,
            payload=self._payload(),
        )
        work_order_audit = audit_work_order_frozen(
            self.capability_store,
            dispatch_catalog,
            validator_registry,
            work_order,
        )
        work_order_store.publish_work_order(work_order)
        work_order_store.publish_audit(work_order_audit)
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
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.binding = binding
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
            "seed": 7,
            "replicates": 2,
            "max_steps": 10,
            "stall_steps": 3,
            "initial_state_json": '{"ore":0}',
            "rules_json": '[{"consume":{},"priority":0,"probability_ppm":1000000,"produce":{"ore":1},"requires":{},"rule_id":"mine"}]',
            "invariants_json": "[]",
        }

    def _execution_rows(self) -> list[dict]:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT * FROM dispatch_executions
                   WHERE task_id = ? ORDER BY created_at, execution_id""",
                (self.task_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _event_rows(self, aggregate_type: str, aggregate_id: str) -> list[dict]:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = ? AND aggregate_id = ?
                   ORDER BY created_at, rowid""",
                (aggregate_type, aggregate_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def _workspace_count(self) -> int:
        with self.runtime.store.session() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                    (self.task_id,),
                ).fetchone()[0]
            )

    def test_simulation_dependencies_use_no_model_runtime_sandbox_or_workspace_stack(self) -> None:
        task_before = dict(self.runtime.get_task(self.task_id))
        runs_before = self.runtime.list_runs(self.task_id)
        with (
            patch.object(
                assembly_module,
                "load_config",
                side_effect=AssertionError("config load"),
            ),
            patch.object(
                assembly_module,
                "create_model_scheduling",
                side_effect=AssertionError("model scheduling"),
            ),
            patch.object(
                assembly_module,
                "ManagedLlamaCppCpuLoader",
                side_effect=AssertionError("managed loader"),
            ),
            patch.object(
                assembly_module,
                "create_sandbox_backend",
                side_effect=AssertionError("sandbox create"),
            ),
            patch.object(
                assembly_module,
                "GitWorkspaceManager",
                side_effect=AssertionError("workspace manager"),
            ),
            patch.object(
                assembly_module,
                "BoundedRetryPolicy",
                side_effect=AssertionError("bounded retry policy"),
            ),
        ):
            first = assemble_production_execution_dependencies(
                self.runtime,
                self.claim.claim_id,
            )
            second = assemble_production_execution_dependencies(
                self.runtime,
                self.claim.claim_id,
            )

        self.assertIsInstance(first.payload, DeterministicSimulationExecutionPayload)
        self.assertEqual(first.payload.dependency_mode, "deterministic-simulation-no-runtime@1")
        self.assertEqual(
            first.plan.owner_id,
            "originforge.execution.simulation.deterministic@1",
        )
        self.assertEqual(first.plan.claim_id, self.claim.claim_id)
        self.assertEqual(first.plan.claim_revision, 0)
        self.assertEqual(first.plan.task_id, self.task_id)
        self.assertEqual(first.plan.task_revision, 1)
        self.assertEqual(first.plan.task_content_hash, self.claim.task_content_hash)
        self.assertEqual(
            first.plan.request_type_id,
            "SimulationService.execute@production-v1",
        )
        self.assertEqual(first.plan.config_version, 0)
        self.assertEqual(first.plan.model_strategy_roles, ())
        self.assertEqual(first.plan.model_profile_ids, ())
        self.assertEqual(first.plan.runtime_ids, ())
        self.assertEqual(first.plan.runtime_provider_fingerprints, ())
        self.assertEqual(first.plan.sandbox_backend, "not-required")
        self.assertRegex(first.plan.resource_model_config_hash, r"^[0-9a-f]{64}$")
        self.assertRegex(first.plan.model_runtime_config_fingerprint, r"^[0-9a-f]{64}$")
        self.assertRegex(first.plan.sandbox_config_hash, r"^[0-9a-f]{64}$")
        self.assertRegex(first.plan.plan_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(second.plan.to_dict(), first.plan.to_dict())
        self.assertEqual(second.plan.plan_hash, first.plan.plan_hash)
        with self.assertRaises(ProductionExecutionAssemblyError):
            _ = first.bounded_retry_policy
        self.assertEqual(dict(self.runtime.get_task(self.task_id)), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)
        self.assertEqual(self._workspace_count(), 0)

    def test_simulation_begin_atomically_records_started_and_transitions_ready_to_running(self) -> None:
        task_before = dict(self.runtime.get_task(self.task_id))
        claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        with patch.object(
            SimulationService,
            "execute",
            side_effect=AssertionError("47E simulation execution"),
        ):
            started = begin_dispatch_execution(
                self.runtime,
                self.claim.claim_id,
                0,
            )

        execution = started.execution
        self.assertEqual(execution.status, DispatchExecutionStatus.STARTED)
        self.assertEqual(execution.revision, 0)
        self.assertEqual(execution.task_id, self.task_id)
        self.assertEqual(execution.task_revision, 1)
        self.assertEqual(execution.task_content_hash, task_before["routing_hash"] if "routing_hash" in task_before else self.claim.task_content_hash)
        self.assertEqual(
            execution.execution_owner_id,
            "originforge.execution.simulation.deterministic@1",
        )
        self.assertEqual(
            execution.runtime_dependency_plan_hash,
            started.dependencies.plan.plan_hash,
        )

        task_after = self.runtime.get_task(self.task_id)
        self.assertEqual(task_after["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task_after["revision"]), 2)
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id), claim_before)
        self.assertEqual(claim_before.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(claim_before.revision, 0)
        self.assertEqual(len(self._execution_rows()), 1)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])
        self.assertEqual(self._workspace_count(), 0)

        execution_events = self._event_rows("DISPATCH_EXECUTION", execution.execution_id)
        self.assertEqual(len(execution_events), 1)
        self.assertEqual(
            execution_events[0]["event_type"],
            "DISPATCH_EXECUTION_STARTED",
        )
        task_events = self._event_rows("TASK", self.task_id)
        self.assertEqual(task_events[-1]["event_type"], "TASK_STATUS_CHANGED")
        self.assertEqual(task_events[-1]["old_state"], TaskStatus.READY.value)
        self.assertEqual(task_events[-1]["new_state"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task_events[-1]["revision"]), 2)
        self.assertIn(
            "SIMULATION_DISPATCH_EXECUTION_STARTED",
            task_events[-1]["metadata_json"],
        )

    def test_simulation_task_event_failure_rolls_back_receipt_and_running_state(self) -> None:
        task_before = dict(self.runtime.get_task(self.task_id))
        claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        task_events_before = self._event_rows("TASK", self.task_id)
        original_append = self.runtime.store._append_event
        call_count = 0

        def injected(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("injected simulation task-event failure")
            return original_append(*args, **kwargs)

        with patch.object(self.runtime.store, "_append_event", side_effect=injected):
            with self.assertRaisesRegex(RuntimeError, "task-event failure"):
                begin_dispatch_execution(
                    self.runtime,
                    self.claim.claim_id,
                    0,
                )

        self.assertEqual(dict(self.runtime.get_task(self.task_id)), task_before)
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id), claim_before)
        self.assertEqual(self._execution_rows(), [])
        self.assertEqual(self._event_rows("TASK", self.task_id), task_events_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])
        self.assertEqual(self._workspace_count(), 0)

    def test_phase47d_source_does_not_call_simulation_backend(self) -> None:
        source = inspect.getsource(execution_module)
        tree = ast.parse(source)
        self.assertNotIn("SimulationService", source)
        self.assertNotIn("simulation_service", source)
        execute_receivers = {
            node.func.value.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and isinstance(node.func.value, ast.Name)
        }
        self.assertEqual(execute_receivers, {"conn"})


if __name__ == "__main__":
    unittest.main()
