from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_preparation_planner_boundary as boundary_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_activation import activate_and_checkpoint_preparation
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_planner_boundary import (
    PreparationPlannerBoundaryError,
    resolve_routed_preparation_planner_boundary,
)
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_receipts import acquire_preparation_receipt
from origin_forge.production_preparation_route_recovery import (
    recover_and_checkpoint_preparation_route,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationPlannerBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase41d1-planner-boundary")
        goal = self.runtime.create_goal("prove exact routed planner authority")

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
            summary="Materialize one bounded code Task.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement one governed code change.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(self.runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        self.task_id = materialization.task_bindings[0].task_id

        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        ).publish_dispatch_catalog(self.dispatch_catalog)
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

    def _routed_receipt(self):
        admission = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        claimed = acquire_preparation_receipt(
            self.runtime,
            self.policy,
            admission.candidates[0],
        )
        activated = activate_and_checkpoint_preparation(
            self.runtime,
            claimed.preparation_id,
            claimed.revision,
        )
        return recover_and_checkpoint_preparation_route(
            self.runtime,
            activated.preparation_id,
            activated.revision,
        )

    def _effect_counts(self) -> tuple[int, int, int]:
        with self.runtime.store.session() as conn:
            return (
                int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]),
                int(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0]),
                int(conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0]),
            )

    def test_exact_routed_boundary_reconstructs_without_mutation_or_model_call(self) -> None:
        routed = self._routed_receipt()
        self.assertEqual(routed.stage, PreparationStage.ROUTED)
        self.assertEqual(routed.status, PreparationStatus.ACTIVE)
        before = self._effect_counts()

        boundary = resolve_routed_preparation_planner_boundary(
            self.runtime,
            routed.preparation_id,
            routed.revision,
        )

        self.assertEqual(boundary.receipt, routed)
        self.assertEqual(boundary.policy, self.policy)
        self.assertEqual(boundary.route.route_decision_id, routed.route_decision_id)
        self.assertEqual(boundary.route.content_hash, routed.route_decision_hash)
        self.assertEqual(
            boundary.dispatch_catalog.dispatch_catalog_id,
            self.policy.dispatch_contract_catalog_id,
        )
        self.assertEqual(
            boundary.dispatch_catalog.content_hash,
            self.policy.dispatch_contract_catalog_hash,
        )
        self.assertEqual(
            boundary.dependencies.owner.owner_id,
            self.policy.preparation_owner_id,
        )
        self.assertEqual(
            boundary.dependencies.owner.fingerprint,
            self.policy.preparation_owner_fingerprint,
        )
        self.assertEqual(
            boundary.dependencies.plan.preparation_policy_hash,
            self.policy.content_hash,
        )
        self.assertEqual(self._effect_counts(), before)
        with self.runtime.store.session() as conn:
            stage = conn.execute(
                "SELECT stage FROM task_preparations WHERE preparation_id = ?",
                (routed.preparation_id,),
            ).fetchone()[0]
        self.assertEqual(stage, PreparationStage.ROUTED.value)

    def test_stale_expected_revision_fails_without_crossing_planner_boundary(self) -> None:
        routed = self._routed_receipt()
        before = self._effect_counts()
        with self.assertRaises(PreparationPlannerBoundaryError):
            resolve_routed_preparation_planner_boundary(
                self.runtime,
                routed.preparation_id,
                routed.revision + 1,
            )
        self.assertEqual(self._effect_counts(), before)

    def test_task_drift_invalidates_routed_boundary(self) -> None:
        routed = self._routed_receipt()
        self.runtime.transition_task(
            self.task_id,
            TaskStatus.RUNNING,
            expected_revision=routed.ready_task_revision,
        )
        before = self._effect_counts()
        with self.assertRaises(PreparationPlannerBoundaryError):
            resolve_routed_preparation_planner_boundary(
                self.runtime,
                routed.preparation_id,
                routed.revision,
            )
        self.assertEqual(self._effect_counts(), before)

    def test_route_hash_drift_invalidates_routed_boundary(self) -> None:
        routed = self._routed_receipt()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE task_preparations SET route_decision_hash = ? WHERE preparation_id = ?",
                ("f" * 64, routed.preparation_id),
            )
        before = self._effect_counts()
        with self.assertRaises(PreparationPlannerBoundaryError):
            resolve_routed_preparation_planner_boundary(
                self.runtime,
                routed.preparation_id,
                routed.revision,
            )
        self.assertEqual(self._effect_counts(), before)

    def test_source_contains_no_planner_checkpoint_or_execution_authority(self) -> None:
        source = inspect.getsource(boundary_module)
        for forbidden in (
            "planner.propose(",
            ".generate(",
            "checkpoint_preparation_planner_started",
            "checkpoint_preparation_planner_returned",
            "dispatch_claim_once",
            "acquire_dispatch_claim",
            "BEGIN IMMEDIATE",
            "INSERT INTO",
            "UPDATE task_preparations",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
