from __future__ import annotations

import unittest
from unittest.mock import patch

import origin_forge.production_preparation_planner_resume as planner_resume_module
import test_phase39_preparation_acceptance as phase39
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage
from origin_forge.production_preparation_receipts import (
    PreparationReceiptError,
    acquire_preparation_receipt,
)
from origin_forge.production_preparation_recovery_once import (
    PreparationRecoveryOnceStatus,
    recover_preparation_once,
)
from origin_forge.production_preparation_tick import (
    PreparationTickStatus,
    prepare_materialization_tick,
)
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import TaskStatus


class _ScenarioHarness:
    def __init__(self, testcase: unittest.TestCase) -> None:
        self.addCleanup = testcase.addCleanup

    _write_model_config = staticmethod(
        phase39.Phase39PreparationAcceptanceTests._write_model_config
    )


def _scenario(testcase: unittest.TestCase, *, steps: int = 1):
    return phase39.Phase39PreparationAcceptanceTests._scenario(
        _ScenarioHarness(testcase),
        steps=steps,
    )


def _response():
    return phase39.Phase39PreparationAcceptanceTests._response()


def _assert_no_dispatch(testcase: unittest.TestCase, runtime) -> None:
    with runtime.store.session() as conn:
        testcase.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)
        testcase.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0], 0)


class Phase41CrossPhaseAcceptanceTests(unittest.TestCase):
    def test_acquisition_crash_recovers_one_edge_per_call_then_stops_post_planner(self) -> None:
        scenario = _scenario(self)
        admission = inspect_materialization_preparation_eligibility_readonly(
            scenario.runtime,
            scenario.preparation_policy,
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        claimed = acquire_preparation_receipt(
            scenario.runtime,
            scenario.preparation_policy,
            admission.candidates[0],
        )
        self.assertEqual(claimed.stage, PreparationStage.CLAIMED)
        self.assertEqual(scenario.runtime.get_task(claimed.task_id)["status"], TaskStatus.QUEUED.value)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("model crossed before ROUTED recovery"),
        ):
            activated = recover_preparation_once(scenario.runtime, claimed.preparation_id)
            routed = recover_preparation_once(scenario.runtime, claimed.preparation_id)
        self.assertEqual(activated.status, PreparationRecoveryOnceStatus.RECOVERED_ACTIVATED)
        self.assertEqual(routed.status, PreparationRecoveryOnceStatus.RECOVERED_ROUTED)
        self.assertEqual(scenario.runtime.get_task(claimed.task_id)["status"], TaskStatus.READY.value)

        calls = 0

        def generate(*args, **kwargs):
            nonlocal calls
            calls += 1
            return _response()

        with patch.object(ScheduledModelAdapter, "generate", side_effect=generate):
            planner = recover_preparation_once(scenario.runtime, claimed.preparation_id)
        self.assertEqual(planner.status, PreparationRecoveryOnceStatus.RESUMED_PLANNER_RETURNED)
        self.assertEqual(calls, 1)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("post-planner recovery replayed model"),
        ):
            stopped = recover_preparation_once(scenario.runtime, claimed.preparation_id)
        self.assertEqual(stopped.status, PreparationRecoveryOnceStatus.POST_PLANNER_NOT_REQUIRED)
        _assert_no_dispatch(self, scenario.runtime)

    def test_planner_started_recovers_existing_success_without_model_replay(self) -> None:
        scenario = _scenario(self)
        with (
            patch.object(ScheduledModelAdapter, "generate", return_value=_response()),
            patch.object(
                planner_resume_module,
                "checkpoint_preparation_planner_returned",
                side_effect=PreparationReceiptError("simulated lost return checkpoint"),
            ),
        ):
            tick = prepare_materialization_tick(
                scenario.runtime,
                scenario.preparation_policy.preparation_policy_id,
            )
        self.assertEqual(tick.status, PreparationTickStatus.PLANNER_RECOVERY_REQUIRED)
        self.assertIsNotNone(tick.receipt)
        assert tick.receipt is not None
        self.assertEqual(tick.receipt.stage, PreparationStage.PLANNER_STARTED)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("PLANNER_STARTED recovery replayed model"),
        ):
            recovered = recover_preparation_once(
                scenario.runtime,
                tick.receipt.preparation_id,
            )
        self.assertEqual(
            recovered.status,
            PreparationRecoveryOnceStatus.RECOVERED_PLANNER_RETURNED,
        )
        self.assertIsNotNone(recovered.receipt)
        assert recovered.receipt is not None
        self.assertEqual(recovered.receipt.stage, PreparationStage.PLANNER_RETURNED)
        _assert_no_dispatch(self, scenario.runtime)


if __name__ == "__main__":
    unittest.main()
