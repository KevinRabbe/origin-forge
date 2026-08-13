from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_status as status_module
from origin_forge.model import ModelResponse
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmissionStatus,
    inspect_manager_dispatch_admission_readonly,
)
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_phase34_finalize import (
    PreparationPhase34FinalizeStatus,
    finalize_preparation_phase34,
)
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_status import (
    PreparationInspectionState,
    inspect_materialization_preparation_status_readonly,
    inspect_preparation_receipt_status_readonly,
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


class PreparationStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase39f-status")
        goal = self.runtime.create_goal("inspect governed preparation status")
        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(self.catalog)
        capability_store.publish_policy(self.routing_policy, self.catalog)
        planning_input = freeze_governed_planning_input(
            self.runtime,
            goal,
            capability_store=capability_store,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Prepare one code Task for immutable inspection.",
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
        self.materialization = materialization
        self.task_id = materialization.task_bindings[0].task_id
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        work_orders = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(self.dispatch_catalog)
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
        return result.receipt

    def _work_order_audited(self):
        receipt = self._planner_returned()
        assert receipt is not None
        result = finalize_preparation_work_order_audit(
            self.runtime,
            receipt.preparation_id,
        )
        self.assertEqual(
            result.status,
            PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        )
        return result.receipt

    def _ready(self):
        receipt = self._work_order_audited()
        result = finalize_preparation_phase34(
            self.runtime,
            receipt.preparation_id,
        )
        self.assertEqual(result.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        return result.receipt

    def _db_signature(self):
        path = self.runtime.store.db_path
        stat = path.stat()
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            tuple(
                (suffix, Path(str(path) + suffix).exists())
                for suffix in ("-wal", "-shm", "-journal")
            ),
        )

    def test_policy_status_reports_first_eligible_task_without_mutation(self) -> None:
        with self.runtime.store.session() as conn:
            preparation_count_before = conn.execute(
                "SELECT COUNT(*) FROM task_preparations"
            ).fetchone()[0]
        task_before = self.runtime.get_task(self.task_id)
        before = self._db_signature()

        result = inspect_materialization_preparation_status_readonly(
            self.runtime,
            self.policy.preparation_policy_id,
        )
        after = self._db_signature()

        self.assertEqual(result.state, PreparationInspectionState.ELIGIBLE_QUEUED)
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.selected_task_id, self.task_id)
        self.assertEqual(result.materialization_id, self.materialization.materialization_id)
        self.assertEqual(result.preparation_policy_hash, self.policy.content_hash)
        self.assertEqual(after, before)
        self.assertEqual(task_before["status"], TaskStatus.QUEUED.value)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.QUEUED.value)
        with self.runtime.store.session() as conn:
            preparation_count_after = conn.execute(
                "SELECT COUNT(*) FROM task_preparations"
            ).fetchone()[0]
        self.assertEqual(preparation_count_after, preparation_count_before)

    def test_planner_return_and_audit_are_post_planner_resumable(self) -> None:
        receipt = self._planner_returned()
        assert receipt is not None
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("39F may not replay planner"),
        ):
            returned = inspect_preparation_receipt_status_readonly(
                self.runtime,
                receipt.preparation_id,
            )
        self.assertEqual(
            returned.state,
            PreparationInspectionState.POST_PLANNER_RESUMABLE,
        )
        self.assertTrue(returned.current)
        self.assertEqual(returned.work_order_id, receipt.work_order_id)
        self.assertIsNone(returned.work_order_audit_id)

        audited_result = finalize_preparation_work_order_audit(
            self.runtime,
            receipt.preparation_id,
        )
        self.assertEqual(
            audited_result.status,
            PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        )
        audited = inspect_preparation_receipt_status_readonly(
            self.runtime,
            receipt.preparation_id,
        )
        self.assertEqual(audited.state, PreparationInspectionState.POST_PLANNER_RESUMABLE)
        self.assertTrue(audited.current)
        self.assertEqual(
            audited.work_order_audit_id,
            audited_result.receipt.work_order_audit_id,
        )

    def test_planner_started_is_recovery_required_and_status_never_calls_model(self) -> None:
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=RuntimeError("simulated uncertain model transport"),
        ):
            tick = prepare_materialization_tick(
                self.runtime,
                self.policy.preparation_policy_id,
            )
        self.assertEqual(tick.status, PreparationTickStatus.PLANNER_RECOVERY_REQUIRED)
        self.assertIsNotNone(tick.receipt)
        assert tick.receipt is not None

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("39F status crossed model boundary"),
        ):
            status = inspect_preparation_receipt_status_readonly(
                self.runtime,
                tick.receipt.preparation_id,
            )
        self.assertEqual(
            status.state,
            PreparationInspectionState.PLANNER_RECOVERY_REQUIRED,
        )
        self.assertTrue(status.current)
        self.assertIsNone(status.work_order_id)

    def test_ready_status_requires_exact_current_phase34_chain_and_phase38_sees_it(self) -> None:
        receipt = self._ready()
        status = inspect_preparation_receipt_status_readonly(
            self.runtime,
            receipt.preparation_id,
        )
        self.assertEqual(status.state, PreparationInspectionState.READY_FOR_PHASE38)
        self.assertTrue(status.current)
        self.assertEqual(status.input_resolution_id, receipt.input_resolution_id)
        self.assertEqual(status.dispatch_binding_id, receipt.dispatch_binding_id)
        self.assertEqual(status.binding_audit_id, receipt.binding_audit_id)

        manager = inspect_manager_dispatch_admission_readonly(self.runtime)
        self.assertEqual(manager.status, ManagerDispatchAdmissionStatus.COMPLETE)
        self.assertIn(self.task_id, {candidate.task_id for candidate in manager.candidates})
        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0], 0)

    def test_ready_status_fails_closed_on_receipt_hash_tamper(self) -> None:
        receipt = self._ready()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE task_preparations SET binding_audit_hash = ? WHERE preparation_id = ?",
                ("f" * 64, receipt.preparation_id),
            )
        status = inspect_preparation_receipt_status_readonly(
            self.runtime,
            receipt.preparation_id,
        )
        self.assertEqual(status.state, PreparationInspectionState.STALE_OR_INVALID)
        self.assertFalse(status.current)
        self.assertIsNotNone(status.detail)
        assert status.detail is not None
        self.assertIn("Phase-34", status.detail)

    def test_ready_status_fails_closed_when_task_revision_drifts(self) -> None:
        receipt = self._ready()
        current = self.runtime.get_task(self.task_id)
        self.runtime.transition_task(
            self.task_id,
            TaskStatus.BLOCKED,
            expected_revision=int(current["revision"]),
        )
        status = inspect_preparation_receipt_status_readonly(
            self.runtime,
            receipt.preparation_id,
        )
        self.assertEqual(status.state, PreparationInspectionState.STALE_OR_INVALID)
        self.assertFalse(status.current)
        self.assertIsNotNone(status.detail)
        assert status.detail is not None
        self.assertIn("READY Task revision", status.detail)

    def test_status_source_has_no_mutating_or_execution_authority(self) -> None:
        source = Path(status_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_modules = {
            "production_preparation_tick",
            "production_preparation_receipts",
            "production_preparation_planner_evidence",
            "production_preparation_work_order_finalize",
            "production_preparation_phase34_finalize",
            "production_task_activation",
            "production_dispatch_claim",
            "production_dispatch_execution",
            "scheduled_model_adapter",
        }
        forbidden_calls = {
            "session",
            "prepare_materialization_tick",
            "finalize_preparation_work_order_audit",
            "finalize_preparation_phase34",
            "activate_dependency_ready_task",
            "publish_preparation_policy",
            "checkpoint_preparation_planner_returned",
            "acquire_dispatch_claim",
            "dispatch_claim_once",
            "generate",
            "propose",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                self.assertNotIn(node.module.rsplit(".", 1)[-1], forbidden_modules)
                self.assertTrue(
                    all(alias.name not in forbidden_calls for alias in node.names)
                )
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr
                else:
                    continue
                self.assertNotIn(call_name, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
