from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_phase34_finalize as phase34_module
from origin_forge.model import ModelResponse
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_phase34_finalize import (
    PreparationPhase34FinalizeStatus,
    finalize_preparation_phase34,
)
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


class PreparationPhase34FinalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase39e-phase34-finalize")
        goal = self.runtime.create_goal("bind one exact prepared WorkOrder")
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
            summary="Bind one governed code WorkOrder.",
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
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validators,
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=self.catalog.catalog_id,
            capability_routing_policy_id=self.routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=self.dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(self.runtime, self.policy)
        self._write_model_config()
        self.resolvers = build_dispatch_input_resolver_registry()
        self.binders = build_builtin_dispatch_binder_registry()
        self.dispatch_store = ProductionDispatchStore(
            self.work_order_store,
            self.resolvers,
            self.binders,
        )

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

    def _work_order_audited(self):
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            return_value=self._response(),
        ):
            tick = prepare_materialization_tick(
                self.runtime,
                self.policy.preparation_policy_id,
            )
        self.assertEqual(tick.status, PreparationTickStatus.PLANNER_RETURNED)
        assert tick.receipt is not None
        finalized = finalize_preparation_work_order_audit(
            self.runtime,
            tick.receipt.preparation_id,
        )
        self.assertEqual(
            finalized.status,
            PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        )
        return finalized.receipt

    def _category_files(self, category: str, prefix: str) -> tuple[Path, ...]:
        directory = self.dispatch_store.root / category
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob(f"{prefix}-*.json")))

    def _counts(self):
        return (
            len(self._category_files("input-resolutions", "INRES")),
            len(self._category_files("dispatch-bindings", "DISPBIND")),
            len(self._category_files("binding-audits", "BINDAUD")),
        )

    def _publish_bundle(self, receipt):
        bundle = create_input_resolution_bundle(
            self.work_order_store,
            self.resolvers,
            receipt.work_order_id,
            receipt.work_order_audit_id,
        )
        self.dispatch_store.publish_input_resolution(bundle)
        return bundle

    def _publish_binding(self, bundle):
        binding = create_dispatch_binding(
            self.work_order_store,
            self.resolvers,
            self.binders,
            bundle,
        )
        self.dispatch_store.publish_binding(binding)
        return binding

    def _publish_audit(self, bundle, binding):
        audit = audit_dispatch_binding_frozen(
            self.work_order_store,
            self.resolvers,
            self.binders,
            bundle,
            binding,
        )
        self.dispatch_store.publish_audit(audit)
        return audit

    def test_phase34_finalizer_marks_ready_and_stops_before_dispatch(self) -> None:
        receipt = self._work_order_audited()
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("39E3 must not call model"),
        ):
            result = finalize_preparation_phase34(
                self.runtime,
                receipt.preparation_id,
            )
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertEqual(result.receipt.stage, PreparationStage.BOUND)
        self.assertEqual(result.receipt.status, PreparationStatus.READY)
        self.assertIsNotNone(result.input_resolution)
        self.assertIsNotNone(result.dispatch_binding)
        self.assertIsNotNone(result.binding_audit)
        assert result.input_resolution is not None
        assert result.dispatch_binding is not None
        assert result.binding_audit is not None
        self.assertEqual(result.receipt.input_resolution_id, result.input_resolution.input_resolution_id)
        self.assertEqual(result.receipt.input_resolution_hash, result.input_resolution.content_hash)
        self.assertEqual(result.receipt.dispatch_binding_id, result.dispatch_binding.dispatch_binding_id)
        self.assertEqual(result.receipt.dispatch_binding_hash, result.dispatch_binding.content_hash)
        self.assertEqual(result.receipt.binding_audit_id, result.binding_audit.binding_audit_id)
        self.assertEqual(result.receipt.binding_audit_hash, result.binding_audit.content_hash)
        self.assertEqual(self._counts(), (1, 1, 1))
        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0], 0)

        second = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(second.status, PreparationPhase34FinalizeStatus.ALREADY_READY)
        self.assertEqual(second.receipt.revision, result.receipt.revision)
        self.assertEqual(self._counts(), (1, 1, 1))

    def test_crash_after_all_phase34_artifacts_reuses_exact_chain_on_retry(self) -> None:
        receipt = self._work_order_audited()
        with patch.object(
            phase34_module,
            "_checkpoint_preparation_bound",
            side_effect=RuntimeError("simulated lost PREP BOUND checkpoint"),
        ):
            first = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(first.status, PreparationPhase34FinalizeStatus.RECOVERY_REQUIRED)
        self.assertEqual(first.receipt.stage, PreparationStage.WORK_ORDER_AUDITED)
        self.assertEqual(first.receipt.status, PreparationStatus.ACTIVE)
        self.assertEqual(self._counts(), (1, 1, 1))
        ids = (
            first.input_resolution.input_resolution_id,
            first.dispatch_binding.dispatch_binding_id,
            first.binding_audit.binding_audit_id,
        )

        second = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(second.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertTrue(second.reused_input_resolution)
        self.assertTrue(second.reused_dispatch_binding)
        self.assertTrue(second.reused_binding_audit)
        self.assertEqual(
            (
                second.receipt.input_resolution_id,
                second.receipt.dispatch_binding_id,
                second.receipt.binding_audit_id,
            ),
            ids,
        )
        self.assertEqual(self._counts(), (1, 1, 1))

    def test_orphan_input_resolution_is_reused_before_binding(self) -> None:
        receipt = self._work_order_audited()
        bundle = self._publish_bundle(receipt)
        result = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertTrue(result.reused_input_resolution)
        self.assertFalse(result.reused_dispatch_binding)
        self.assertFalse(result.reused_binding_audit)
        self.assertEqual(result.receipt.input_resolution_id, bundle.input_resolution_id)
        self.assertEqual(self._counts(), (1, 1, 1))

    def test_orphan_binding_is_reused_before_audit(self) -> None:
        receipt = self._work_order_audited()
        bundle = self._publish_bundle(receipt)
        binding = self._publish_binding(bundle)
        result = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertTrue(result.reused_input_resolution)
        self.assertTrue(result.reused_dispatch_binding)
        self.assertFalse(result.reused_binding_audit)
        self.assertEqual(result.receipt.dispatch_binding_id, binding.dispatch_binding_id)
        self.assertEqual(self._counts(), (1, 1, 1))

    def test_semantically_identical_duplicate_bundles_collapse_before_binding(self) -> None:
        receipt = self._work_order_audited()
        first = self._publish_bundle(receipt)
        second = self._publish_bundle(receipt)
        chosen_id = min(first.input_resolution_id, second.input_resolution_id)
        result = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertTrue(result.reused_input_resolution)
        self.assertEqual(result.receipt.input_resolution_id, chosen_id)
        self.assertEqual(self._counts(), (2, 1, 1))

    def test_semantically_identical_duplicate_bindings_collapse_before_audit(self) -> None:
        receipt = self._work_order_audited()
        bundle = self._publish_bundle(receipt)
        first = self._publish_binding(bundle)
        second = self._publish_binding(bundle)
        chosen_id = min(first.dispatch_binding_id, second.dispatch_binding_id)
        result = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertTrue(result.reused_dispatch_binding)
        self.assertEqual(result.receipt.dispatch_binding_id, chosen_id)
        self.assertEqual(self._counts(), (1, 2, 1))

    def test_semantically_identical_duplicate_pass_audits_collapse_deterministically(self) -> None:
        receipt = self._work_order_audited()
        bundle = self._publish_bundle(receipt)
        binding = self._publish_binding(bundle)
        first = self._publish_audit(bundle, binding)
        second = self._publish_audit(bundle, binding)
        chosen_id = min(first.binding_audit_id, second.binding_audit_id)
        result = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertTrue(result.reused_binding_audit)
        self.assertEqual(result.receipt.binding_audit_id, chosen_id)
        self.assertEqual(self._counts(), (1, 1, 2))

    def test_task_drift_after_work_order_audit_prevents_phase34_publication(self) -> None:
        receipt = self._work_order_audited()
        current = self.runtime.get_task(self.task_id)
        self.runtime.transition_task(
            self.task_id,
            TaskStatus.BLOCKED,
            expected_revision=int(current["revision"]),
        )
        result = finalize_preparation_phase34(self.runtime, receipt.preparation_id)
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.receipt.stage, PreparationStage.WORK_ORDER_AUDITED)
        self.assertEqual(result.receipt.status, PreparationStatus.ACTIVE)
        self.assertEqual(self._counts(), (0, 0, 0))

    def test_e3_source_has_no_model_claim_execution_or_manager_authority(self) -> None:
        source = Path(phase34_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ScheduledModelAdapter", source)
        self.assertNotIn("BoundedProductionWorkOrderPlanner", source)
        self.assertNotIn("production_dispatch_claim", source)
        self.assertNotIn("production_dispatch_execution", source)
        self.assertNotIn("production_manager", source)
        self.assertNotIn(".generate(", source)
        self.assertNotIn(".propose(", source)
        self.assertNotIn("acquire_dispatch_claim", source)
        self.assertNotIn("dispatch_claim_once", source)


if __name__ == "__main__":
    unittest.main()
