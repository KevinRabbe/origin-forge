from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_tick as tick_module
from origin_forge.model import ModelResponse
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_receipts import PreparationReceiptError
from origin_forge.production_preparation_tick import (
    PreparationTickStatus,
    prepare_materialization_tick,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationTickTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_model_config(self, runtime: OriginForgeRuntime) -> None:
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
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18081, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]
''',
            encoding="utf-8",
        )

    def _fixture(
        self,
        *,
        capability_id: str = "code.change",
        ordered_adapter_ids: tuple[str, ...] = ("originforge.code.bounded-retry",),
        step_count: int = 1,
    ):
        runtime = OriginForgeRuntime(self.root)
        runtime.initialize("phase39d-tick")
        goal = runtime.create_goal("prepare exact materialized work")
        catalog = build_builtin_capability_catalog()
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=ordered_adapter_ids,
            allowed_capability_ids=(capability_id,),
        )
        capability_store = ProductionCapabilityStore(runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(routing_policy, catalog)
        planning_input = freeze_governed_planning_input(
            runtime,
            goal,
            capability_store=capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        steps = tuple(
            PlanStep(
                step_key=f"step-{index}",
                objective=f"Implement governed step {index}.",
                acceptance_criteria=("The step is verified.",),
                required_capabilities=(capability_id,),
            )
            for index in range(step_count)
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Prepare governed work.",
            steps=steps,
        )
        audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_orders = ProductionWorkOrderStore(
            runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(dispatch_catalog)
        policy = create_preparation_policy_binding(
            runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=catalog.catalog_id,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(runtime, policy)
        self._write_model_config(runtime)
        task_ids = tuple(binding.task_id for binding in materialization.task_bindings)
        return runtime, policy, materialization, task_ids

    @staticmethod
    def _successful_model_response() -> ModelResponse:
        return ModelResponse(
            text=json.dumps(
                {
                    "contract_id": "code.bounded-retry@1",
                    "input_refs": [],
                    "payload": {"context_mode": "auto"},
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            model_id="test-model",
            model_hash="a" * 64,
            input_tokens=10,
            output_tokens=5,
        )

    def _preparation_rows(self, runtime: OriginForgeRuntime):
        with runtime.store.session() as conn:
            return conn.execute(
                "SELECT * FROM task_preparations ORDER BY created_at, preparation_id"
            ).fetchall()

    def test_success_crosses_one_model_boundary_and_stops_at_planner_returned(self) -> None:
        runtime, policy, _, task_ids = self._fixture()
        calls = []

        def generate(_model, request):
            calls.append(request.run_id)
            return self._successful_model_response()

        with patch.object(ScheduledModelAdapter, "generate", new=generate):
            result = prepare_materialization_tick(runtime, policy.preparation_policy_id)

        self.assertEqual(result.status, PreparationTickStatus.PLANNER_RETURNED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.task_id, task_ids[0])
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual(result.receipt.stage, PreparationStage.PLANNER_RETURNED)
        self.assertEqual(result.receipt.status, PreparationStatus.ACTIVE)
        self.assertIsNotNone(result.receipt.planner_dependency_plan_hash)
        self.assertIsNotNone(result.receipt.planner_run_id)
        self.assertIsNotNone(result.receipt.work_order_id)
        self.assertIsNone(result.receipt.work_order_audit_id)
        self.assertIsNone(result.receipt.input_resolution_id)
        self.assertIsNone(result.receipt.dispatch_binding_id)
        self.assertIsNone(result.receipt.binding_audit_id)

        task = runtime.get_task(task_ids[0])
        self.assertEqual(task["status"], TaskStatus.READY.value)
        self.assertEqual(task["revision"], 1)
        self.assertEqual(result.receipt.ready_task_revision, 1)
        self.assertNotEqual(
            result.receipt.queued_task_hash,
            result.receipt.ready_task_hash,
        )
        self.assertIsNotNone(result.receipt.route_decision_id)
        route = ProductionCapabilityStore(runtime).require_current_route(
            result.receipt.route_decision_id
        )
        self.assertEqual(route.resolution.route_input.task_revision, 1)
        self.assertEqual(
            route.resolution.route_input.task_content_hash,
            result.receipt.ready_task_hash,
        )

        with runtime.store.session() as conn:
            claim_count = conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0]
            execution_count = conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0]
            run = conn.execute(
                "SELECT * FROM runs WHERE id = ?",
                (result.receipt.planner_run_id,),
            ).fetchone()
        self.assertEqual(claim_count, 0)
        self.assertEqual(execution_count, 0)
        self.assertIsNotNone(run)
        self.assertIsNone(run["task_id"])
        self.assertEqual(run["role"], "WORK_ORDER_PLANNER")
        self.assertEqual(run["status"], "SUCCEEDED")

        # A later call cannot replay the already-prepared READY Task.
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("planner replay"),
        ):
            second = prepare_materialization_tick(runtime, policy.preparation_policy_id)
        self.assertEqual(second.status, PreparationTickStatus.NO_ELIGIBLE_TASK)
        self.assertEqual(len(calls), 1)

    def test_unsupported_routed_adapter_fails_before_planner_started(self) -> None:
        runtime, policy, _, task_ids = self._fixture(
            capability_id="image.generate",
            ordered_adapter_ids=("originforge.image.generate",),
        )
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("unsupported adapter reached model"),
        ):
            result = prepare_materialization_tick(runtime, policy.preparation_policy_id)
        self.assertEqual(result.status, PreparationTickStatus.FAILED_PRE_PLANNER)
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual(result.receipt.stage, PreparationStage.ROUTED)
        self.assertEqual(result.receipt.status, PreparationStatus.FAILED_PRE_PLANNER)
        self.assertIsNone(result.receipt.planner_dependency_plan_hash)
        self.assertEqual(runtime.get_task(task_ids[0])["status"], TaskStatus.READY.value)
        with runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)

    def test_uncertain_baseexception_after_planner_started_is_durable_and_never_replayed(self) -> None:
        runtime, policy, _, task_ids = self._fixture()
        calls = []

        def crash(_model, request):
            calls.append(request.run_id)
            raise KeyboardInterrupt("simulated host interruption")

        with patch.object(ScheduledModelAdapter, "generate", new=crash):
            with self.assertRaises(KeyboardInterrupt):
                prepare_materialization_tick(runtime, policy.preparation_policy_id)
        self.assertEqual(len(calls), 1)
        rows = self._preparation_rows(runtime)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["task_id"], task_ids[0])
        self.assertEqual(row["stage"], PreparationStage.PLANNER_STARTED.value)
        self.assertEqual(row["status"], PreparationStatus.ACTIVE.value)
        self.assertIsNotNone(row["planner_dependency_plan_hash"])
        self.assertIsNone(row["planner_run_id"])
        self.assertEqual(runtime.get_task(task_ids[0])["status"], TaskStatus.READY.value)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("uncertain planner replay"),
        ):
            second = prepare_materialization_tick(runtime, policy.preparation_policy_id)
        self.assertEqual(second.status, PreparationTickStatus.NO_ELIGIBLE_TASK)
        self.assertEqual(len(calls), 1)
        rows_after = self._preparation_rows(runtime)
        self.assertEqual(len(rows_after), 1)
        self.assertEqual(rows_after[0]["stage"], PreparationStage.PLANNER_STARTED.value)
        self.assertEqual(rows_after[0]["status"], PreparationStatus.ACTIVE.value)

    def test_acquisition_failure_never_falls_through_to_second_candidate(self) -> None:
        runtime, policy, _, task_ids = self._fixture(step_count=2)
        with patch.object(
            tick_module,
            "acquire_preparation_receipt",
            side_effect=PreparationReceiptError("simulated acquisition race"),
        ) as acquire:
            result = prepare_materialization_tick(runtime, policy.preparation_policy_id)
        self.assertEqual(result.status, PreparationTickStatus.PREPARATION_NOT_ACQUIRED)
        self.assertEqual(acquire.call_count, 1)
        selected_task = acquire.call_args.args[2].task_id
        self.assertEqual(result.task_id, selected_task)
        self.assertIn(selected_task, task_ids)
        self.assertTrue(
            all(runtime.get_task(task_id)["status"] == TaskStatus.QUEUED.value for task_id in task_ids)
        )
        self.assertEqual(self._preparation_rows(runtime), [])

    def test_ordinary_model_exception_after_planner_started_requires_recovery_not_failure(self) -> None:
        runtime, policy, _, _ = self._fixture()
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=RuntimeError("model transport uncertainty"),
        ):
            result = prepare_materialization_tick(runtime, policy.preparation_policy_id)
        self.assertEqual(result.status, PreparationTickStatus.PLANNER_RECOVERY_REQUIRED)
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual(result.receipt.stage, PreparationStage.PLANNER_STARTED)
        self.assertEqual(result.receipt.status, PreparationStatus.ACTIVE)
        self.assertIsNone(result.receipt.planner_run_id)
        self.assertIsNone(result.receipt.terminal_reason)


if __name__ == "__main__":
    unittest.main()
