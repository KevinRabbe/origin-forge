from __future__ import annotations

import inspect
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_activation_recovery import (
    PreparationActivationRecoveryError,
    adopt_legacy_preparation_activation,
)
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
    read_preparation_receipt,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import utc_now
from origin_forge.state import TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationActivationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase41d1-activation-adoption")
        goal = self.runtime.create_goal("adopt one proven legacy activation")

        catalog = build_builtin_capability_catalog()
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(routing_policy, catalog)

        planning_input = freeze_governed_planning_input(
            self.runtime,
            goal,
            capability_store=capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Materialize one Task for legacy activation recovery.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Recover one exact activation checkpoint.",
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

        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        ).publish_dispatch_catalog(dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=catalog.catalog_id,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(self.runtime, self.policy)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _claimed_receipt(self):
        admission = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        return acquire_preparation_receipt(
            self.runtime,
            self.policy,
            admission.candidates[0],
        )

    def _legacy_claimed_ready(self):
        receipt = self._claimed_receipt()
        activation = activate_dependency_ready_task(
            self.runtime,
            receipt.task_id,
            receipt.queued_task_revision,
        )
        return receipt, activation

    def _ready_activation_events(self):
        with self.runtime.store.session() as conn:
            return conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = 'TASK'
                     AND aggregate_id = ?
                     AND event_type = 'TASK_STATUS_CHANGED'
                     AND new_state = 'READY'
                   ORDER BY rowid""",
                (self.task_id,),
            ).fetchall()

    def test_exact_legacy_phase35_event_adopts_missing_checkpoint_only(self) -> None:
        receipt, activation = self._legacy_claimed_ready()
        task_before = self.runtime.get_task(self.task_id)
        self.assertEqual(len(self._ready_activation_events()), 1)

        adopted = adopt_legacy_preparation_activation(
            self.runtime,
            receipt.preparation_id,
            receipt.revision,
        )

        task_after = self.runtime.get_task(self.task_id)
        self.assertEqual(task_after, task_before)
        self.assertEqual(len(self._ready_activation_events()), 1)
        self.assertEqual(adopted.status, PreparationStatus.ACTIVE)
        self.assertEqual(adopted.stage, PreparationStage.ACTIVATED)
        self.assertEqual(adopted.revision, receipt.revision + 1)
        self.assertEqual(adopted.ready_task_revision, activation.new_revision)
        self.assertEqual(adopted.ready_task_hash, activation.new_task_content_hash)

    def test_generic_ready_transition_is_rejected_without_prep_mutation(self) -> None:
        receipt = self._claimed_receipt()
        self.runtime.transition_task(
            receipt.task_id,
            TaskStatus.READY,
            expected_revision=receipt.queued_task_revision,
        )

        with self.assertRaises(PreparationActivationRecoveryError):
            adopt_legacy_preparation_activation(
                self.runtime,
                receipt.preparation_id,
                receipt.revision,
            )

        durable = read_preparation_receipt(self.runtime, receipt.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.CLAIMED)
        self.assertEqual(durable.revision, receipt.revision)

    def test_stale_bound_cappol_provenance_cannot_be_adopted(self) -> None:
        receipt, _ = self._legacy_claimed_ready()
        policy_path = (
            self.runtime.state_dir
            / "production-capabilities"
            / "policies"
            / f"{self.policy.capability_routing_policy_id}.json"
        )
        policy_path.write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(
            PreparationActivationRecoveryError,
            "PREPPOL provenance",
        ):
            adopt_legacy_preparation_activation(
                self.runtime,
                receipt.preparation_id,
                receipt.revision,
            )

        durable = read_preparation_receipt(self.runtime, receipt.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.CLAIMED)
        self.assertEqual(durable.revision, receipt.revision)

    def test_duplicate_activation_revision_evidence_is_rejected(self) -> None:
        receipt, _ = self._legacy_claimed_ready()
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

        with self.assertRaisesRegex(
            PreparationActivationRecoveryError,
            "multiple post-acquisition",
        ):
            adopt_legacy_preparation_activation(
                self.runtime,
                receipt.preparation_id,
                receipt.revision,
            )

        self.assertEqual(
            read_preparation_receipt(self.runtime, receipt.preparation_id).stage,
            PreparationStage.CLAIMED,
        )

    def test_tampered_claimed_receipt_revision_cannot_be_adopted(self) -> None:
        receipt, _ = self._legacy_claimed_ready()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE task_preparations SET revision = 7 WHERE preparation_id = ?",
                (receipt.preparation_id,),
            )

        with self.assertRaisesRegex(
            PreparationActivationRecoveryError,
            "revision zero",
        ):
            adopt_legacy_preparation_activation(
                self.runtime,
                receipt.preparation_id,
                7,
            )

        durable = read_preparation_receipt(self.runtime, receipt.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.CLAIMED)
        self.assertEqual(durable.revision, 7)

    def test_concurrent_adoption_has_at_most_one_checkpoint_winner(self) -> None:
        receipt, activation = self._legacy_claimed_ready()

        def attempt():
            try:
                result = adopt_legacy_preparation_activation(
                    self.runtime,
                    receipt.preparation_id,
                    receipt.revision,
                )
            except Exception as exc:
                return ("error", type(exc).__name__)
            return ("ok", result.stage.value)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(lambda _: attempt(), range(2)))

        winners = sum(value[0] == "ok" for value in outcomes)
        self.assertLessEqual(winners, 1)
        self.assertEqual(sum(value[0] == "error" for value in outcomes), 2 - winners)
        durable = read_preparation_receipt(self.runtime, receipt.preparation_id)
        self.assertEqual(durable.status, PreparationStatus.ACTIVE)
        if winners:
            self.assertEqual(durable.stage, PreparationStage.ACTIVATED)
            self.assertEqual(durable.revision, receipt.revision + 1)
            self.assertEqual(durable.ready_task_revision, activation.new_revision)
            self.assertEqual(durable.ready_task_hash, activation.new_task_content_hash)
        else:
            self.assertEqual(durable.stage, PreparationStage.CLAIMED)
            self.assertEqual(durable.revision, receipt.revision)
            self.assertIsNone(durable.ready_task_revision)
            self.assertIsNone(durable.ready_task_hash)
        self.assertEqual(len(self._ready_activation_events()), 1)

    def test_public_adoption_surface_has_no_task_or_execution_selector_authority(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(adopt_legacy_preparation_activation).parameters),
            ("runtime", "preparation_id", "expected_revision"),
        )
        source = inspect.getsource(adopt_legacy_preparation_activation)
        for forbidden in (
            "task_id:",
            "route_decision_id:",
            "model",
            "dispatch",
            "propose",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
