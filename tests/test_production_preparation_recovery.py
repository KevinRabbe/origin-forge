from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_preparation_recovery as recovery_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_receipts import (
    acquire_preparation_receipt,
    checkpoint_preparation_activated,
    fail_preparation_before_planner,
)
from origin_forge.production_preparation_recovery import (
    PreparationRecoveryState,
    inspect_preparation_recovery_readonly,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus
from origin_forge.service import utc_now


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationRecoveryReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase41a-recovery-read")
        goal = self.runtime.create_goal("recover one stranded PREP without guessing")

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
            summary="Materialize one bounded code task for recovery inspection.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement a bounded recovery fixture.",
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
        self.materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=plan_audit.audit_id,
        )
        self.task_id = self.materialization.task_bindings[0].task_id

        dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        work_orders = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=self.materialization.materialization_id,
            capability_catalog_id=self.catalog.catalog_id,
            capability_routing_policy_id=self.routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(self.runtime, self.policy)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _candidate(self):
        admission = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        return admission.candidates[0]

    def _acquire(self):
        return acquire_preparation_receipt(
            self.runtime,
            self.policy,
            self._candidate(),
        )

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

    def test_exact_claimed_queued_is_resumable_and_read_only(self) -> None:
        receipt = self._acquire()
        before = self._db_signature()

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        after = self._db_signature()
        self.assertEqual(after, before)
        self.assertEqual(result.state, PreparationRecoveryState.RESUMABLE_CLAIMED)
        self.assertEqual(result.preparation_id, receipt.preparation_id)
        self.assertEqual(result.stage, PreparationStage.CLAIMED)
        self.assertEqual(result.receipt_status, PreparationStatus.ACTIVE)
        self.assertEqual(result.task_status, TaskStatus.QUEUED)
        self.assertEqual(result.task_revision, receipt.queued_task_revision)
        self.assertEqual(result.task_content_hash, receipt.queued_task_hash)
        self.assertIsNotNone(result.acquisition_event_id)
        self.assertIsNone(result.activation_event_id)

    def test_legacy_claimed_ready_with_exact_phase35_event_is_adoptable(self) -> None:
        receipt = self._acquire()
        activation = activate_dependency_ready_task(
            self.runtime,
            receipt.task_id,
            receipt.queued_task_revision,
        )
        before = self._db_signature()

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(self._db_signature(), before)
        self.assertEqual(
            result.state,
            PreparationRecoveryState.ADOPTABLE_ACTIVATION_CHECKPOINT,
        )
        self.assertEqual(result.stage, PreparationStage.CLAIMED)
        self.assertEqual(result.task_status, TaskStatus.READY)
        self.assertEqual(result.task_revision, activation.new_revision)
        self.assertEqual(result.task_content_hash, activation.new_task_content_hash)
        self.assertIsNotNone(result.acquisition_event_id)
        self.assertIsNotNone(result.activation_event_id)

    def test_generic_ready_transition_is_never_adoptable(self) -> None:
        receipt = self._acquire()
        self.runtime.transition_task(
            receipt.task_id,
            TaskStatus.READY,
            expected_revision=receipt.queued_task_revision,
        )

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(result.state, PreparationRecoveryState.STALE_OR_INVALID)
        self.assertEqual(result.task_status, TaskStatus.READY)
        self.assertIsNotNone(result.activation_event_id)
        self.assertIn("Phase-35", result.detail or "")

    def test_duplicate_post_acquisition_activation_revision_is_ambiguous(self) -> None:
        receipt = self._acquire()
        activate_dependency_ready_task(
            self.runtime,
            receipt.task_id,
            receipt.queued_task_revision,
        )
        with self.runtime.store.session() as conn:
            event = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                     AND event_type = 'TASK_STATUS_CHANGED' AND revision = ?
                   ORDER BY rowid DESC LIMIT 1""",
                (receipt.task_id, receipt.queued_task_revision + 1),
            ).fetchone()
            self.assertIsNotNone(event)
            conn.execute(
                """INSERT INTO state_events(
                       id, aggregate_type, aggregate_id, event_type, old_state,
                       new_state, revision, actor_type, actor_id, metadata_json,
                       created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id(IdKind.EVENT),
                    event["aggregate_type"],
                    event["aggregate_id"],
                    event["event_type"],
                    event["old_state"],
                    event["new_state"],
                    event["revision"],
                    event["actor_type"],
                    event["actor_id"],
                    event["metadata_json"],
                    utc_now(),
                ),
            )

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(result.state, PreparationRecoveryState.AMBIGUOUS_EVIDENCE)
        self.assertIn("multiple", result.detail or "")

    def test_noncanonical_acquisition_metadata_is_rejected(self) -> None:
        receipt = self._acquire()
        with self.runtime.store.session() as conn:
            conn.execute(
                """UPDATE state_events
                   SET metadata_json = ?
                   WHERE aggregate_type = 'TASK_PREPARATION'
                     AND aggregate_id = ?
                     AND event_type = 'TASK_PREPARATION_ACQUIRED'""",
                (
                    json.dumps(
                        {
                            "task_id": receipt.task_id,
                            "preparation_policy_id": receipt.preparation_policy_id,
                            "queued_task_revision": receipt.queued_task_revision,
                            "queued_task_hash": receipt.queued_task_hash,
                        },
                        separators=(", ", ": "),
                        sort_keys=False,
                    ),
                    receipt.preparation_id,
                ),
            )

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(result.state, PreparationRecoveryState.STALE_OR_INVALID)
        self.assertIn("canonical", result.detail or "")


    def test_legacy_claimed_ready_requires_receipt_revision_zero(self) -> None:
        receipt = self._acquire()
        activate_dependency_ready_task(
            self.runtime,
            receipt.task_id,
            receipt.queued_task_revision,
        )
        with self.runtime.store.session() as conn:
            conn.execute(
                """UPDATE task_preparations
                   SET revision = 7
                   WHERE preparation_id = ?""",
                (receipt.preparation_id,),
            )

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(result.state, PreparationRecoveryState.STALE_OR_INVALID)
        self.assertIn("Phase-35", result.detail or "")

    def test_durable_activated_checkpoint_maps_to_resumable_activated(self) -> None:
        receipt = self._acquire()
        activation = activate_dependency_ready_task(
            self.runtime,
            receipt.task_id,
            receipt.queued_task_revision,
        )
        activated = checkpoint_preparation_activated(
            self.runtime,
            receipt.preparation_id,
            receipt.revision,
            activation,
        )

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(
            result.state,
            PreparationRecoveryState.RESUMABLE_ACTIVATED,
        )
        self.assertEqual(result.stage, PreparationStage.ACTIVATED)
        self.assertEqual(result.receipt_revision, activated.revision)
        self.assertEqual(result.task_status, TaskStatus.READY)

    def test_terminal_preplanner_receipt_never_becomes_recovery_authority(self) -> None:
        receipt = self._acquire()
        failed = fail_preparation_before_planner(
            self.runtime,
            receipt.preparation_id,
            receipt.revision,
            PreparationStage.CLAIMED,
            "test terminal evidence",
        )

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(
            result.state,
            PreparationRecoveryState.TERMINAL_NOT_REQUIRED,
        )
        self.assertEqual(result.receipt_status, PreparationStatus.FAILED_PRE_PLANNER)
        self.assertEqual(result.receipt_revision, failed.revision)

    def test_policy_hash_drift_fails_closed(self) -> None:
        receipt = self._acquire()
        with self.runtime.store.session() as conn:
            conn.execute(
                """UPDATE task_preparations
                   SET preparation_policy_hash = ?
                   WHERE preparation_id = ?""",
                ("f" * 64, receipt.preparation_id),
            )

        result = inspect_preparation_recovery_readonly(
            self.runtime,
            receipt.preparation_id,
        )

        self.assertEqual(result.state, PreparationRecoveryState.STALE_OR_INVALID)
        self.assertIn("PREPPOL", result.detail or "")

    def test_public_inspection_surface_contains_no_mutation_or_execution_authority(self) -> None:
        signature = inspect.signature(inspect_preparation_recovery_readonly)
        self.assertEqual(tuple(signature.parameters), ("runtime", "preparation_id"))

        source = inspect.getsource(recovery_module)
        for forbidden_sql in (
            "INSERT INTO",
            "UPDATE task",
            "DELETE FROM",
            "BEGIN IMMEDIATE",
        ):
            self.assertNotIn(forbidden_sql, source)
        tree = ast.parse(source)
        forbidden_calls = {
            "generate",
            "propose",
            "drive",
            "publish",
            "resolve_and_publish",
            "activate_dependency_ready_task",
            "checkpoint_preparation_activated",
            "checkpoint_preparation_routed",
            "checkpoint_preparation_planner_started",
            "acquire_preparation_receipt",
            "dispatch_claim_once",
            "dispatch_manager_tick",
            "advance_production_manager_once",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
