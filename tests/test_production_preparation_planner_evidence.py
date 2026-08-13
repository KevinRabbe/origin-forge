from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_planner_resume as planner_resume_module
from origin_forge.model import ModelResponse
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_assembly import assemble_preparation_planner_dependencies
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_planner_evidence import (
    PlannerEvidenceRecoveryStatus,
    recover_planner_evidence,
)
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_receipts import PreparationReceiptError
from origin_forge.production_preparation_tick import (
    PreparationTickStatus,
    prepare_materialization_tick,
)
from origin_forge.production_preparation_provenance import resolve_preparation_policy_provenance
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_validator_registry,
    build_builtin_dispatch_catalog,
)
from origin_forge.production_work_order_planner import (
    BoundedProductionWorkOrderPlanner,
    DeterministicWorkOrderPlannerAdapter,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationPlannerEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase39e-planner-evidence")
        goal = self.runtime.create_goal("recover exact planner evidence")
        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.routing_policy, self.catalog)
        self.planning_input = freeze_governed_planning_input(
            self.runtime,
            goal,
            capability_store=self.capability_store,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=self.planning_input,
            summary="Recover one bounded code WorkOrder.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement the bounded change.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        audit = audit_plan(self.planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(self.runtime)
        planning.publish_input(self.planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(audit)
        self.materialization = planning.materialize(
            planning_input_id=self.planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        self.task_id = self.materialization.task_bindings[0].task_id
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=self.materialization.materialization_id,
            capability_catalog_id=self.catalog.catalog_id,
            capability_routing_policy_id=self.routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=self.dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(self.runtime, self.policy)
        self._write_model_config()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_model_config(self) -> None:
        self.runtime.state_dir.joinpath("config.toml").write_text(
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

    @staticmethod
    def _response() -> ModelResponse:
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

    def _complete_tick(self):
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            return_value=self._response(),
        ):
            return prepare_materialization_tick(
                self.runtime,
                self.policy.preparation_policy_id,
            )

    def _successful_but_uncheckpointed(self):
        with (
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=self._response(),
            ),
            patch.object(
                planner_resume_module,
                "checkpoint_preparation_planner_returned",
                side_effect=PreparationReceiptError("simulated lost PREP return checkpoint"),
            ),
        ):
            result = prepare_materialization_tick(
                self.runtime,
                self.policy.preparation_policy_id,
            )
        self.assertEqual(result.status, PreparationTickStatus.PLANNER_RECOVERY_REQUIRED)
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual(result.receipt.stage, PreparationStage.PLANNER_STARTED)
        self.assertEqual(result.receipt.status, PreparationStatus.ACTIVE)
        return result.receipt

    def test_exact_planner_return_rehydrates_same_work_order_without_model_call(self) -> None:
        tick = self._complete_tick()
        self.assertEqual(tick.status, PreparationTickStatus.PLANNER_RETURNED)
        assert tick.receipt is not None and tick.planner_result is not None
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("planner replay"),
        ):
            recovered = recover_planner_evidence(
                self.runtime,
                tick.receipt.preparation_id,
            )
        self.assertEqual(recovered.status, PlannerEvidenceRecoveryStatus.EXACT_RETURN)
        self.assertIsNotNone(recovered.planner_result)
        assert recovered.planner_result is not None
        self.assertEqual(
            recovered.planner_result.work_order.to_dict(),
            tick.planner_result.work_order.to_dict(),
        )
        self.assertEqual(
            recovered.planner_result.work_order.content_hash,
            tick.receipt.work_order_hash,
        )
        self.assertEqual(recovered.receipt.revision, tick.receipt.revision)

    def test_successful_planner_verification_recovers_lost_return_checkpoint_once(self) -> None:
        started = self._successful_but_uncheckpointed()
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("planner replay"),
        ):
            recovered = recover_planner_evidence(
                self.runtime,
                started.preparation_id,
            )
        self.assertEqual(
            recovered.status,
            PlannerEvidenceRecoveryStatus.RECOVERED_PLANNER_RETURNED,
        )
        self.assertEqual(recovered.receipt.stage, PreparationStage.PLANNER_RETURNED)
        self.assertEqual(recovered.receipt.status, PreparationStatus.ACTIVE)
        self.assertIsNotNone(recovered.receipt.planner_run_id)
        self.assertIsNotNone(recovered.receipt.work_order_id)
        self.assertIsNotNone(recovered.planner_result)
        again = recover_planner_evidence(self.runtime, started.preparation_id)
        self.assertEqual(again.status, PlannerEvidenceRecoveryStatus.EXACT_RETURN)
        self.assertEqual(again.receipt.revision, recovered.receipt.revision)

    def test_no_successful_planner_evidence_remains_unresolved_without_mutation(self) -> None:
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=RuntimeError("simulated model uncertainty"),
        ):
            tick = prepare_materialization_tick(
                self.runtime,
                self.policy.preparation_policy_id,
            )
        self.assertEqual(tick.status, PreparationTickStatus.PLANNER_RECOVERY_REQUIRED)
        assert tick.receipt is not None
        before = tick.receipt.to_dict()
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("planner replay"),
        ):
            recovered = recover_planner_evidence(
                self.runtime,
                tick.receipt.preparation_id,
            )
        self.assertEqual(recovered.status, PlannerEvidenceRecoveryStatus.UNRESOLVED)
        self.assertEqual(recovered.receipt.to_dict(), before)

    def test_multiple_exact_successful_planner_results_are_ambiguous_not_replayed(self) -> None:
        started = self._successful_but_uncheckpointed()
        provenance = resolve_preparation_policy_provenance(self.runtime, self.policy)
        adapter = DeterministicWorkOrderPlannerAdapter(
            response_text=self._response().text,
            fixture_model_id="test-model",
            input_tokens=10,
            output_tokens=5,
        )
        planner = BoundedProductionWorkOrderPlanner(
            self.runtime,
            self.capability_store,
            provenance.dispatch_contract_catalog,
            build_builtin_dispatch_validator_registry(),
            adapter,
        )
        planner.propose(started.route_decision_id, allowed_input_refs=())
        self.assertEqual(adapter.call_count, 1)

        recovered = recover_planner_evidence(self.runtime, started.preparation_id)
        self.assertEqual(recovered.status, PlannerEvidenceRecoveryStatus.AMBIGUOUS)
        self.assertEqual(recovered.receipt.stage, PreparationStage.PLANNER_STARTED)
        self.assertIsNone(recovered.receipt.planner_run_id)
        self.assertIsNone(recovered.receipt.work_order_id)

    def test_tampered_exact_planner_verification_fails_closed(self) -> None:
        tick = self._complete_tick()
        assert tick.receipt is not None
        run_id = tick.receipt.planner_run_id
        assert run_id is not None
        with self.runtime.store.session() as conn:
            row = conn.execute(
                """SELECT * FROM verifications
                   WHERE target_type = 'RUN' AND target_id = ?
                     AND verification_type = 'work-order-planner-generation'
                     AND status = 'PASS'""",
                (run_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            evidence = json.loads(row["evidence_json"])
            evidence["work_order_hash"] = "0" * 64
            conn.execute(
                "UPDATE verifications SET evidence_json = ? WHERE id = ?",
                (
                    json.dumps(evidence, separators=(",", ":"), sort_keys=True),
                    row["id"],
                ),
            )
        recovered = recover_planner_evidence(
            self.runtime,
            tick.receipt.preparation_id,
        )
        self.assertEqual(recovered.status, PlannerEvidenceRecoveryStatus.UNRESOLVED)
        self.assertEqual(recovered.receipt.stage, PreparationStage.PLANNER_RETURNED)
        self.assertEqual(recovered.receipt.work_order_id, tick.receipt.work_order_id)


if __name__ == "__main__":
    unittest.main()
