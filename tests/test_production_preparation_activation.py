from __future__ import annotations

import inspect
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_activation as activation_module
import origin_forge.production_preparation_tick as tick_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_activation import (
    activate_and_checkpoint_preparation,
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
from origin_forge.state import TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase41b-atomic-activation")
        goal = self.runtime.create_goal("atomically activate one preparation")

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
            summary="Prepare one exact Task for atomic activation.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement one bounded change.",
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
        work_orders = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(dispatch_catalog)
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

    def _acquire(self):
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

    def _activation_events(self):
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

    def test_success_commits_task_activation_and_prep_checkpoint_together(self) -> None:
        receipt = self._acquire()

        activated = activate_and_checkpoint_preparation(
            self.runtime,
            receipt.preparation_id,
            receipt.revision,
        )

        task = self.runtime.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.READY.value)
        self.assertEqual(task["revision"], receipt.queued_task_revision + 1)
        self.assertEqual(activated.status, PreparationStatus.ACTIVE)
        self.assertEqual(activated.stage, PreparationStage.ACTIVATED)
        self.assertEqual(activated.revision, receipt.revision + 1)
        self.assertEqual(activated.ready_task_revision, task["revision"])
        self.assertIsNotNone(activated.ready_task_hash)
        self.assertNotEqual(activated.ready_task_hash, receipt.queued_task_hash)
        events = self._activation_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["revision"], task["revision"])

    def test_failure_between_task_activation_and_prep_checkpoint_rolls_back_both(self) -> None:
        receipt = self._acquire()
        task_before = self.runtime.get_task(self.task_id)

        with patch.object(
            activation_module,
            "_checkpoint_preparation_activated_connection",
            side_effect=RuntimeError("injected checkpoint failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected checkpoint failure"):
                activate_and_checkpoint_preparation(
                    self.runtime,
                    receipt.preparation_id,
                    receipt.revision,
                )

        task_after = self.runtime.get_task(self.task_id)
        durable = read_preparation_receipt(self.runtime, receipt.preparation_id)
        self.assertEqual(task_after["status"], TaskStatus.QUEUED.value)
        self.assertEqual(task_after["revision"], task_before["revision"])
        self.assertEqual(durable.status, PreparationStatus.ACTIVE)
        self.assertEqual(durable.stage, PreparationStage.CLAIMED)
        self.assertEqual(durable.revision, receipt.revision)
        self.assertIsNone(durable.ready_task_revision)
        self.assertIsNone(durable.ready_task_hash)
        self.assertEqual(self._activation_events(), [])

    def test_concurrent_atomic_activation_has_one_complete_winner(self) -> None:
        receipt = self._acquire()

        def attempt():
            try:
                result = activate_and_checkpoint_preparation(
                    self.runtime,
                    receipt.preparation_id,
                    receipt.revision,
                )
            except Exception as exc:
                return ("error", type(exc).__name__)
            return ("ok", result.stage.value)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(lambda _: attempt(), range(2)))

        self.assertEqual(sum(outcome[0] == "ok" for outcome in outcomes), 1)
        self.assertEqual(sum(outcome[0] == "error" for outcome in outcomes), 1)
        task = self.runtime.get_task(self.task_id)
        durable = read_preparation_receipt(self.runtime, receipt.preparation_id)
        self.assertEqual(task["status"], TaskStatus.READY.value)
        self.assertEqual(task["revision"], receipt.queued_task_revision + 1)
        self.assertEqual(durable.stage, PreparationStage.ACTIVATED)
        self.assertEqual(durable.revision, receipt.revision + 1)
        self.assertEqual(len(self._activation_events()), 1)

    def test_public_phase35_signature_and_behavior_remain_unchanged(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(activate_dependency_ready_task).parameters),
            ("runtime", "task_id", "expected_revision"),
        )
        receipt = self._acquire()

        activation = activate_dependency_ready_task(
            self.runtime,
            receipt.task_id,
            receipt.queued_task_revision,
        )

        self.assertEqual(activation.task_id, receipt.task_id)
        self.assertEqual(activation.previous_revision, receipt.queued_task_revision)
        self.assertEqual(activation.new_revision, receipt.queued_task_revision + 1)
        self.assertEqual(self.runtime.get_task(receipt.task_id)["status"], TaskStatus.READY.value)
        durable = read_preparation_receipt(self.runtime, receipt.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.CLAIMED)
        self.assertEqual(durable.revision, receipt.revision)

    def test_atomic_preparation_surface_has_no_task_selector_authority(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(activate_and_checkpoint_preparation).parameters),
            ("runtime", "preparation_id", "expected_revision"),
        )
        source = inspect.getsource(activation_module.activate_and_checkpoint_preparation)
        self.assertNotIn("task_id:", source)
        self.assertNotIn("candidate", source)
        self.assertNotIn("route", source)
        self.assertNotIn("model", source)
        self.assertNotIn("dispatch", source)

    def test_phase39_tick_uses_only_atomic_activation_checkpoint(self) -> None:
        source = inspect.getsource(tick_module)
        self.assertIn("activate_and_checkpoint_preparation", source)
        self.assertNotIn("activate_dependency_ready_task", source)
        self.assertNotIn("checkpoint_preparation_activated", source)


if __name__ == "__main__":
    unittest.main()
