from __future__ import annotations

import unittest
from unittest.mock import patch

import origin_forge.production_manager_advance_once as advance_module
import test_phase40_manager_advance_acceptance as phase40
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmissionStatus,
    inspect_manager_advance_admission_readonly,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage
from origin_forge.production_preparation_receipts import (
    acquire_preparation_receipt,
    read_preparation_receipt,
)
from origin_forge.production_preparation_recovery_once import PreparationRecoveryOnceStatus
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import TaskStatus


class _ScenarioHarness:
    def __init__(self, testcase: unittest.TestCase) -> None:
        self.addCleanup = testcase.addCleanup

    _write_model_config = staticmethod(
        phase40.Phase40ManagerAdvanceAcceptanceTests._write_model_config
    )


def _scenario(testcase: unittest.TestCase):
    return phase40.Phase40ManagerAdvanceAcceptanceTests._preparation_scenario(
        _ScenarioHarness(testcase),
        steps=1,
    )


def _claimed_receipt(testcase: unittest.TestCase, scenario):
    admission = inspect_materialization_preparation_eligibility_readonly(
        scenario.runtime,
        scenario.preparation_policy,
    )
    testcase.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
    testcase.assertEqual(admission.candidate_count, 1)
    return acquire_preparation_receipt(
        scenario.runtime,
        scenario.preparation_policy,
        admission.candidates[0],
    )


def _assert_no_dispatch(testcase: unittest.TestCase, runtime) -> None:
    with runtime.store.session() as conn:
        testcase.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)
        testcase.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0], 0)


class Phase42CLegacyRecoveryAdmissionTests(unittest.TestCase):
    def test_exact_phase35_activation_evidence_is_admitted_and_adopted_once(self) -> None:
        scenario = _scenario(self)
        claimed = _claimed_receipt(self, scenario)
        activation = activate_dependency_ready_task(
            scenario.runtime,
            claimed.task_id,
            claimed.queued_task_revision,
        )
        self.assertEqual(scenario.runtime.get_task(claimed.task_id)["status"], TaskStatus.READY.value)

        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        self.assertEqual(admission.recover_preparation_count, 1)
        self.assertEqual(admission.recovery_required_count, 0)
        candidate = admission.candidates[0]
        self.assertEqual(candidate.action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        self.assertEqual(candidate.preparation_id, claimed.preparation_id)
        self.assertEqual(candidate.preparation_stage, PreparationStage.CLAIMED)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("legacy activation adoption crossed planner boundary"),
        ):
            result = advance_production_manager_once(scenario.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED)
        self.assertEqual(result.action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        self.assertEqual(result.preparation_id, claimed.preparation_id)
        self.assertEqual(
            result.lower_status,
            PreparationRecoveryOnceStatus.ADOPTED_ACTIVATION_CHECKPOINT.value,
        )
        durable = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.ACTIVATED)
        self.assertEqual(durable.revision, claimed.revision + 1)
        self.assertEqual(durable.ready_task_revision, activation.new_revision)
        self.assertEqual(durable.ready_task_hash, activation.new_task_content_hash)
        _assert_no_dispatch(self, scenario.runtime)

    def test_generic_ready_transition_stays_recovery_required_and_never_calls_phase41(self) -> None:
        scenario = _scenario(self)
        claimed = _claimed_receipt(self, scenario)
        scenario.runtime.transition_task(
            claimed.task_id,
            TaskStatus.READY,
            expected_revision=claimed.queued_task_revision,
        )

        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        self.assertEqual(admission.recover_preparation_count, 0)
        self.assertEqual(admission.recovery_required_count, 1)
        candidate = admission.candidates[0]
        self.assertEqual(candidate.action_kind, ManagerAdvanceActionKind.RECOVERY_REQUIRED)
        self.assertEqual(candidate.preparation_id, claimed.preparation_id)
        self.assertEqual(candidate.preparation_stage, PreparationStage.CLAIMED)

        with patch.object(
            advance_module,
            "recover_preparation_once",
            side_effect=AssertionError("generic READY transition reached Phase-41 mutation"),
        ) as recover:
            result = advance_production_manager_once(scenario.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.action_kind, ManagerAdvanceActionKind.RECOVERY_REQUIRED)
        recover.assert_not_called()
        durable = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.CLAIMED)
        self.assertEqual(durable.revision, claimed.revision)
        _assert_no_dispatch(self, scenario.runtime)


if __name__ == "__main__":
    unittest.main()
