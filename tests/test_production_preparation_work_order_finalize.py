from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_work_order_finalize as finalize_module
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
from origin_forge.production_preparation_tick import (
    PreparationTickStatus,
    prepare_materialization_tick,
)
from origin_forge.production_preparation_work_order_finalize import (
    PreparationWorkOrderFinalizeStatus,
    finalize_preparation_work_order_audit,
)
from origin_forge.production_work_order_audit import (
    WorkOrderAuditStatus,
    WorkOrderCurrentnessStatus,
    audit_work_order_frozen,
    inspect_work_order_currentness,
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


class PreparationWorkOrderFinalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase39e-work-order-finalize")
        goal = self.runtime.create_goal("publish exact recovered WorkOrder")
        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.routing_policy, self.catalog)
        planning_input = freeze_governed_planning_input(
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
            planning_input=planning_input,
            summary="Publish one governed WorkOrder.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement the bounded change.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        plan_audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(self.runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(plan_audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=plan_audit.audit_id,
        )
        self.task_id = materialization.task_bindings[0].task_id
        self.validators = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        self.store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validators,
        )
        self.store.publish_dispatch_catalog(self.dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
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

    def _planner_returned(self):
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            return_value=self._response(),
        ):
            result = prepare_materialization_tick(
                self.runtime,
                self.policy.preparation_policy_id,
            )
        self.assertEqual(result.status, PreparationTickStatus.PLANNER_RETURNED)
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        return result.receipt

    def _audit_files(self) -> tuple[Path, ...]:
        directory = self.store.root / "audits"
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("WORKAUD-*.json")))

    def _work_order_files(self) -> tuple[Path, ...]:
        directory = self.store.root / "work-orders"
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("WORKORD-*.json")))

    def test_finalizer_publishes_exact_work_order_and_pass_audit_then_stops(self) -> None:
        returned = self._planner_returned()
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("39E2 must not call model"),
        ):
            result = finalize_preparation_work_order_audit(
                self.runtime,
                returned.preparation_id,
            )
        self.assertEqual(
            result.status,
            PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        )
        self.assertEqual(result.receipt.stage, PreparationStage.WORK_ORDER_AUDITED)
        self.assertEqual(result.receipt.status, PreparationStatus.ACTIVE)
        self.assertEqual(result.receipt.work_order_id, returned.work_order_id)
        self.assertEqual(result.receipt.work_order_hash, returned.work_order_hash)
        self.assertIsNotNone(result.receipt.work_order_audit_id)
        self.assertIsNotNone(result.receipt.work_order_audit_hash)
        self.assertIsNone(result.receipt.input_resolution_id)
        self.assertIsNone(result.receipt.dispatch_binding_id)
        self.assertIsNone(result.receipt.binding_audit_id)
        self.assertEqual(len(self._work_order_files()), 1)
        self.assertEqual(len(self._audit_files()), 1)
        assert result.work_order_audit is not None
        self.assertEqual(result.work_order_audit.status, WorkOrderAuditStatus.PASS)
        work_order = self.store.load_work_order(result.receipt.work_order_id)
        audit = self.store.load_audit(result.receipt.work_order_audit_id)
        currentness = inspect_work_order_currentness(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validators,
            work_order,
            audit,
        )
        self.assertEqual(currentness.status, WorkOrderCurrentnessStatus.CURRENT_READY)
        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0], 0)

        second = finalize_preparation_work_order_audit(
            self.runtime,
            returned.preparation_id,
        )
        self.assertEqual(
            second.status,
            PreparationWorkOrderFinalizeStatus.ALREADY_AUDITED,
        )
        self.assertEqual(len(self._work_order_files()), 1)
        self.assertEqual(len(self._audit_files()), 1)

    def test_crash_after_immutable_publish_reuses_same_artifacts_on_retry(self) -> None:
        returned = self._planner_returned()
        with patch.object(
            finalize_module,
            "_checkpoint_work_order_audited",
            side_effect=RuntimeError("simulated lost PREP audit checkpoint"),
        ):
            first = finalize_preparation_work_order_audit(
                self.runtime,
                returned.preparation_id,
            )
        self.assertEqual(
            first.status,
            PreparationWorkOrderFinalizeStatus.RECOVERY_REQUIRED,
        )
        self.assertEqual(first.receipt.stage, PreparationStage.PLANNER_RETURNED)
        self.assertEqual(len(self._work_order_files()), 1)
        self.assertEqual(len(self._audit_files()), 1)
        work_order_path = self._work_order_files()[0]
        audit_path = self._audit_files()[0]

        second = finalize_preparation_work_order_audit(
            self.runtime,
            returned.preparation_id,
        )
        self.assertEqual(
            second.status,
            PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        )
        self.assertTrue(second.reused_work_order)
        self.assertTrue(second.reused_audit)
        self.assertEqual(self._work_order_files(), (work_order_path,))
        self.assertEqual(self._audit_files(), (audit_path,))

    def test_semantically_identical_duplicate_pass_audits_collapse_deterministically(self) -> None:
        returned = self._planner_returned()
        with patch.object(
            finalize_module,
            "_checkpoint_work_order_audited",
            side_effect=RuntimeError("leave published audit without PREP checkpoint"),
        ):
            first = finalize_preparation_work_order_audit(
                self.runtime,
                returned.preparation_id,
            )
        self.assertEqual(first.status, PreparationWorkOrderFinalizeStatus.RECOVERY_REQUIRED)
        work_order = self.store.load_work_order(returned.work_order_id)
        duplicate = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validators,
            work_order,
        )
        self.store.publish_audit(duplicate)
        audit_ids = sorted(path.stem for path in self._audit_files())
        self.assertEqual(len(audit_ids), 2)

        recovered = finalize_preparation_work_order_audit(
            self.runtime,
            returned.preparation_id,
        )
        self.assertEqual(
            recovered.status,
            PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        )
        self.assertTrue(recovered.reused_audit)
        self.assertEqual(recovered.receipt.work_order_audit_id, audit_ids[0])
        self.assertEqual(len(self._audit_files()), 2)

    def test_task_revision_drift_prevents_any_phase33_publication(self) -> None:
        returned = self._planner_returned()
        current = self.runtime.get_task(self.task_id)
        self.runtime.transition_task(
            self.task_id,
            TaskStatus.BLOCKED,
            expected_revision=int(current["revision"]),
        )
        result = finalize_preparation_work_order_audit(
            self.runtime,
            returned.preparation_id,
        )
        self.assertEqual(
            result.status,
            PreparationWorkOrderFinalizeStatus.PLANNER_UNRESOLVED,
        )
        self.assertEqual(result.receipt.stage, PreparationStage.PLANNER_RETURNED)
        self.assertEqual(self._work_order_files(), ())
        self.assertEqual(self._audit_files(), ())

    def test_e2_source_has_no_model_phase34_or_dispatch_execution_authority(self) -> None:
        source = Path(finalize_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ScheduledModelAdapter", source)
        self.assertNotIn("BoundedProductionWorkOrderPlanner", source)
        self.assertNotIn("production_dispatch_binding", source)
        self.assertNotIn("production_dispatch_store", source)
        self.assertNotIn("dispatch_claim", source)
        self.assertNotIn("dispatch_execution", source)
        self.assertNotIn(".generate(", source)
        self.assertNotIn(".propose(", source)


if __name__ == "__main__":
    unittest.main()
