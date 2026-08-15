from __future__ import annotations

import ast
import inspect
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_dispatch_invocation as invocation_module
import origin_forge.production_manager_advance_once as advance_once_module
from origin_forge.lineage import OriginForgeLineage
from origin_forge.model import ModelResponse
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_goal_bootstrap_authority import build_builtin_goal_bootstrap_owner
from origin_forge.production_manager_advance_bounded import (
    BoundedManagerAdvanceStopReason,
    advance_production_manager_bounded,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.simulation_service import SimulationService
from origin_forge.state import RunStatus, TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class Phase47FSimulationCrossPhaseAcceptanceTests(unittest.TestCase):
    @staticmethod
    def _planner_response() -> ModelResponse:
        return ModelResponse(
            text=json.dumps(
                {
                    "contract_id": "simulation.deterministic@1",
                    "input_refs": [],
                    "payload": {
                        "seed": 47,
                        "replicates": 2,
                        "max_steps": 5,
                        "stall_steps": 3,
                        "initial_state_json": '{"ore":0}',
                        "rules_json": '[{"consume":{},"priority":0,"probability_ppm":1000000,"produce":{"ore":1},"requires":{},"rule_id":"mine"}]',
                        "invariants_json": "[]",
                    },
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            model_id="test-model",
            model_hash=_HASH_A,
            input_tokens=10,
            output_tokens=5,
        )

    @staticmethod
    def _write_model_config(runtime: OriginForgeRuntime) -> None:
        runtime.state_dir.joinpath("config.toml").write_text(
            '''version = 6
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "unconfigured"
image = ""
network = false
memory = "2g"
cpus = 2.0
pids_limit = 256

[commands]
build = []
test = []

[code_intelligence]
lsp_servers = []

[resources]
enabled = true
cpu_slots = 8
ram_mib = 16384
max_active_leases = 8
gpus = []

[models]
profiles = [
  { profile_id = "strong", role = "coder_strong", model_id = "test-model", model_hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", runtime_id = "llamacpp-cpu", resources = { cpu_slots = 2, ram_mib = 4096 } }
]
policies = [
  { role = "coder_strong", primary_profile_id = "strong", fallback_profile_ids = [] }
]

[model_runtimes]
providers = [
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18082, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]
''',
            encoding="utf-8",
        )

    def _scenario(self, *, steps: int = 1):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        runtime = OriginForgeRuntime(root)
        runtime.initialize(f"phase47f-simulation-{steps}")
        goal_id = runtime.create_goal("prove governed simulation production dispatch")

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("simulation.run"),),
            (full.adapter("originforge.simulation.deterministic"),),
        )
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.simulation.deterministic",),
            allowed_capability_ids=("simulation.run",),
        )
        capability_store = ProductionCapabilityStore(runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(routing_policy, catalog)
        planning_input = freeze_governed_planning_input(
            runtime,
            goal_id,
            capability_store=capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Prepare deterministic simulation Tasks through the bounded Manager.",
            steps=tuple(
                PlanStep(
                    step_key=f"simulation{index}",
                    objective=f"Run deterministic simulation {index}.",
                    acceptance_criteria=("Produce deterministic simulation evidence.",),
                    constraints=("No external inputs.",),
                    required_capabilities=("simulation.run",),
                )
                for index in range(steps)
            ),
        )
        plan_audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(plan_audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=plan_audit.audit_id,
        )

        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_order_store = ProductionWorkOrderStore(
            runtime,
            capability_store,
            validators,
        )
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        preparation_policy = create_preparation_policy_binding(
            runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=catalog.catalog_id,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(runtime, preparation_policy)
        self._write_model_config(runtime)
        return SimpleNamespace(
            root=root,
            runtime=runtime,
            catalog=catalog,
            routing_policy=routing_policy,
            capability_store=capability_store,
            validators=validators,
            dispatch_catalog=dispatch_catalog,
            work_order_store=work_order_store,
            preparation_policy=preparation_policy,
            materialization=materialization,
            task_ids=tuple(binding.task_id for binding in materialization.task_bindings),
        )

    @staticmethod
    def _dispatch_rows(runtime: OriginForgeRuntime, task_id: str) -> tuple[list[dict], list[dict]]:
        with runtime.store.session() as conn:
            claims = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM dispatch_claims WHERE task_id = ? ORDER BY created_at, rowid",
                    (task_id,),
                )
            ]
            executions = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM dispatch_executions WHERE task_id = ? ORDER BY created_at, rowid",
                    (task_id,),
                )
            ]
        return claims, executions

    def _advance_to_dispatch_ready(self, scenario) -> str:
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            return_value=self._planner_response(),
        ) as generate:
            first = advance_production_manager_once(scenario.runtime)
            second = advance_production_manager_once(scenario.runtime)
            third = advance_production_manager_once(scenario.runtime)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(
            (first.status, second.status, third.status),
            (
                ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
                ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
                ManagerAdvanceOnceStatus.PHASE34_READY,
            ),
        )
        self.assertEqual(first.task_id, second.task_id)
        self.assertEqual(second.task_id, third.task_id)
        self.assertIsNotNone(third.task_id)
        return third.task_id

    def test_full_manager_path_executes_one_simulation_and_stops_with_task_running(self) -> None:
        scenario = self._scenario(steps=2)
        original_execute = SimulationService.execute
        observed = []

        def execute_once(service, task_id, spec):
            claims, executions = self._dispatch_rows(scenario.runtime, task_id)
            self.assertEqual(len(claims), 1)
            self.assertEqual(claims[0]["status"], DispatchClaimStatus.ACTIVE.value)
            self.assertEqual(len(executions), 1)
            self.assertEqual(executions[0]["status"], DispatchExecutionStatus.STARTED.value)
            self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.RUNNING.value)
            observed.append((spec.spec_id, spec.session_id, spec.workspace_id))
            return original_execute(service, task_id, spec)

        with (
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=self._planner_response(),
            ) as generate,
            patch.object(
                SimulationService,
                "execute",
                autospec=True,
                side_effect=execute_once,
            ) as execute,
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(generate.call_count, 1)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(len(observed), 1)
        self.assertEqual(
            tuple(step.status for step in result.steps),
            (
                ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
                ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
                ManagerAdvanceOnceStatus.PHASE34_READY,
                ManagerAdvanceOnceStatus.DISPATCH_RETURNED,
            ),
        )
        self.assertEqual(result.step_count, 4)
        self.assertEqual(
            result.stop_reason,
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
        )
        selected_task_id = result.final_result.task_id
        self.assertIsNotNone(selected_task_id)
        self.assertTrue(all(step.task_id == selected_task_id for step in result.steps))
        selected = scenario.runtime.get_task(selected_task_id)
        self.assertEqual(selected["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(selected["revision"]), 2)
        self.assertEqual(scenario.runtime.list_verifications("TASK", selected_task_id), [])

        claims, executions = self._dispatch_rows(scenario.runtime, selected_task_id)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], DispatchClaimStatus.CONSUMED.value)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["status"], DispatchExecutionStatus.RETURNED.value)
        runs = scenario.runtime.list_runs(selected_task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["role"], SimulationService.RUN_ROLE)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)
        artifacts = [
            artifact
            for artifact in OriginForgeLineage(scenario.runtime).list_artifacts()
            if artifact["created_by_run_id"] == runs[0]["id"]
        ]
        self.assertEqual(
            tuple(sorted(artifact["type"] for artifact in artifacts)),
            ("SIMULATION_RESULT", "SIMULATION_SPEC", "SIMULATION_SUMMARY"),
        )

        newer_task_id = next(
            task_id for task_id in scenario.task_ids if task_id != selected_task_id
        )
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(int(newer["revision"]), 0)
        newer_claims, newer_executions = self._dispatch_rows(scenario.runtime, newer_task_id)
        self.assertEqual(newer_claims, [])
        self.assertEqual(newer_executions, [])

    def test_ordinary_simulation_exception_is_raised_consumed_and_never_falls_through(self) -> None:
        scenario = self._scenario(steps=2)
        with (
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=self._planner_response(),
            ),
            patch.object(
                SimulationService,
                "execute",
                autospec=True,
                side_effect=RuntimeError("forced simulation failure"),
            ) as execute,
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(execute.call_count, 1)
        selected_task_id = result.final_result.task_id
        self.assertIsNotNone(selected_task_id)
        self.assertEqual(
            result.final_result.status,
            ManagerAdvanceOnceStatus.DISPATCH_RAISED,
        )
        self.assertEqual(scenario.runtime.get_task(selected_task_id)["status"], TaskStatus.RUNNING.value)
        claims, executions = self._dispatch_rows(scenario.runtime, selected_task_id)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], DispatchClaimStatus.CONSUMED.value)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["status"], DispatchExecutionStatus.RAISED.value)
        self.assertEqual(scenario.runtime.list_runs(selected_task_id), [])

        newer_task_id = next(
            task_id for task_id in scenario.task_ids if task_id != selected_task_id
        )
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        newer_claims, newer_executions = self._dispatch_rows(scenario.runtime, newer_task_id)
        self.assertEqual(newer_claims, [])
        self.assertEqual(newer_executions, [])

    def test_base_exception_leaves_started_active_running_and_next_manager_never_replays(self) -> None:
        scenario = self._scenario(steps=1)
        with (
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=self._planner_response(),
            ),
            patch.object(
                SimulationService,
                "execute",
                autospec=True,
                side_effect=KeyboardInterrupt(),
            ) as execute,
        ):
            with self.assertRaises(KeyboardInterrupt):
                advance_production_manager_bounded(scenario.runtime)
        self.assertEqual(execute.call_count, 1)

        task_id = scenario.task_ids[0]
        self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.RUNNING.value)
        claims, executions = self._dispatch_rows(scenario.runtime, task_id)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], DispatchClaimStatus.ACTIVE.value)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["status"], DispatchExecutionStatus.STARTED.value)
        self.assertEqual(scenario.runtime.list_runs(task_id), [])

        restarted = OriginForgeRuntime(scenario.root)
        with patch.object(
            SimulationService,
            "execute",
            autospec=True,
            side_effect=AssertionError("uncertain STARTED simulation was replayed"),
        ) as replay:
            result = advance_production_manager_once(restarted)
        replay.assert_not_called()
        self.assertIn(
            result.status,
            {
                ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
                ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK,
                ManagerAdvanceOnceStatus.INVALID_STATE,
            },
        )
        claims_after, executions_after = self._dispatch_rows(restarted, task_id)
        self.assertEqual(len(claims_after), 1)
        self.assertEqual(len(executions_after), 1)
        self.assertEqual(executions_after[0]["execution_id"], executions[0]["execution_id"])
        self.assertEqual(restarted.list_runs(task_id), [])

    def test_durable_simulation_evidence_before_terminalization_failure_is_never_replayed(self) -> None:
        scenario = self._scenario(steps=1)
        original_execute = SimulationService.execute
        with (
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=self._planner_response(),
            ),
            patch.object(
                SimulationService,
                "execute",
                autospec=True,
                side_effect=lambda service, task_id, spec: original_execute(service, task_id, spec),
            ) as execute,
            patch.object(
                invocation_module,
                "mark_dispatch_execution_returned",
                side_effect=RuntimeError("forced terminalization failure"),
            ),
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(execute.call_count, 1)
        self.assertEqual(
            result.final_result.status,
            ManagerAdvanceOnceStatus.DISPATCH_RECOVERY_REQUIRED,
        )
        task_id = scenario.task_ids[0]
        self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.RUNNING.value)
        claims, executions = self._dispatch_rows(scenario.runtime, task_id)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], DispatchClaimStatus.ACTIVE.value)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["status"], DispatchExecutionStatus.STARTED.value)
        runs = scenario.runtime.list_runs(task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)

        restarted = OriginForgeRuntime(scenario.root)
        with patch.object(
            SimulationService,
            "execute",
            autospec=True,
            side_effect=AssertionError("durable simulation evidence was replayed"),
        ) as replay:
            second = advance_production_manager_once(restarted)
        replay.assert_not_called()
        self.assertIn(
            second.status,
            {
                ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
                ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK,
                ManagerAdvanceOnceStatus.INVALID_STATE,
            },
        )
        self.assertEqual(len(restarted.list_runs(task_id)), 1)
        _, executions_after = self._dispatch_rows(restarted, task_id)
        self.assertEqual(len(executions_after), 1)
        self.assertEqual(executions_after[0]["execution_id"], executions[0]["execution_id"])

    def test_concurrent_manager_dispatch_has_at_most_one_simulation_and_never_newer_task(self) -> None:
        scenario = self._scenario(steps=2)
        selected_task_id = self._advance_to_dispatch_ready(scenario)
        newer_task_id = next(
            task_id for task_id in scenario.task_ids if task_id != selected_task_id
        )
        real_dispatch = advance_once_module._dispatch_selected_candidate_once
        dispatch_barrier = threading.Barrier(2)
        lock = threading.Lock()
        execute_calls = 0
        failures: list[BaseException] = []
        results = []
        original_execute = SimulationService.execute

        def racing_dispatch(runtime, candidate):
            self.assertEqual(candidate.task_id, selected_task_id)
            dispatch_barrier.wait(timeout=30)
            return real_dispatch(runtime, candidate)

        def execute_once(service, task_id, spec):
            nonlocal execute_calls
            with lock:
                execute_calls += 1
            self.assertEqual(task_id, selected_task_id)
            return original_execute(service, task_id, spec)

        def worker() -> None:
            runtime = OriginForgeRuntime(scenario.root)
            try:
                value = advance_production_manager_once(runtime)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(
                advance_once_module,
                "_dispatch_selected_candidate_once",
                side_effect=racing_dispatch,
            ),
            patch.object(
                SimulationService,
                "execute",
                autospec=True,
                side_effect=execute_once,
            ),
        ):
            threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(execute_calls, 1)
        self.assertTrue(all(result.task_id == selected_task_id for result in results))
        self.assertEqual(
            sum(result.status is ManagerAdvanceOnceStatus.DISPATCH_RETURNED for result in results),
            1,
        )
        self.assertEqual(
            sum(
                result.status is ManagerAdvanceOnceStatus.DISPATCH_CLAIM_NOT_ACQUIRED
                for result in results
            ),
            1,
        )
        self.assertTrue(
            all(
                result.status
                in {
                    ManagerAdvanceOnceStatus.DISPATCH_RETURNED,
                    ManagerAdvanceOnceStatus.DISPATCH_CLAIM_NOT_ACQUIRED,
                }
                for result in results
            )
        )
        selected_claims, selected_executions = self._dispatch_rows(
            scenario.runtime,
            selected_task_id,
        )
        self.assertEqual(len(selected_claims), 1)
        self.assertEqual(len(selected_executions), 1)
        self.assertEqual(len(scenario.runtime.list_runs(selected_task_id)), 1)
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        newer_claims, newer_executions = self._dispatch_rows(scenario.runtime, newer_task_id)
        self.assertEqual(newer_claims, [])
        self.assertEqual(newer_executions, [])

    def test_cross_phase_isolation_preserves_code_bootstrap_and_closed_owner_call_sites(self) -> None:
        owner = build_builtin_goal_bootstrap_owner()
        self.assertEqual(owner.supported_capability_id, "code.change")
        self.assertEqual(owner.supported_adapter_id, "originforge.code.bounded-retry")
        self.assertEqual(owner.supported_dispatch_contract_id, "code.bounded-retry@1")
        self.assertEqual(
            owner.preparation_owner_id,
            "originforge.preparation.work-order-planner@1",
        )

        tree = ast.parse(inspect.getsource(invocation_module.dispatch_claim_once))
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


if __name__ == "__main__":
    unittest.main()
