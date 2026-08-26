from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

import origin_forge.production_manager_advance_once as advance_module
from . import test_phase40_manager_advance_acceptance as phase40
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
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import TaskStatus


class _ScenarioHarness:
    def __init__(self, testcase: unittest.TestCase) -> None:
        self.addCleanup = testcase.addCleanup

    _write_model_config = staticmethod(
        phase40.Phase40ManagerAdvanceAcceptanceTests._write_model_config
    )

    _publish_pre_activation_chain = (
        phase40.Phase40ManagerAdvanceAcceptanceTests._publish_pre_activation_chain
    )


def _scenario(testcase: unittest.TestCase, *, steps: int = 2):
    return phase40.Phase40ManagerAdvanceAcceptanceTests._preparation_scenario(
        _ScenarioHarness(testcase),
        steps=steps,
    )


def _claim_oldest(testcase: unittest.TestCase, scenario):
    admission = inspect_materialization_preparation_eligibility_readonly(
        scenario.runtime,
        scenario.preparation_policy,
    )
    testcase.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
    testcase.assertEqual(admission.candidate_count, len(scenario.task_ids))
    candidate = admission.candidates[0]
    receipt = acquire_preparation_receipt(
        scenario.runtime,
        scenario.preparation_policy,
        candidate,
    )
    testcase.assertEqual(receipt.task_id, candidate.task_id)
    testcase.assertEqual(receipt.stage, PreparationStage.CLAIMED)
    return receipt


def _other_task_id(testcase: unittest.TestCase, scenario, claimed_task_id: str) -> str:
    testcase.assertEqual(len(scenario.task_ids), 2)
    others = tuple(task_id for task_id in scenario.task_ids if task_id != claimed_task_id)
    testcase.assertEqual(len(others), 1)
    return others[0]


def _recover_to_routed(testcase: unittest.TestCase, scenario, claimed):
    with patch.object(
        ScheduledModelAdapter,
        "generate",
        side_effect=AssertionError("pre-planner recovery crossed planner boundary"),
    ):
        first = advance_production_manager_once(scenario.runtime)
        testcase.assertEqual(first.status, ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED)
        testcase.assertEqual(first.action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        testcase.assertEqual(first.task_id, claimed.task_id)
        testcase.assertEqual(first.preparation_id, claimed.preparation_id)
        testcase.assertEqual(first.lower_status, PreparationRecoveryOnceStatus.RECOVERED_ACTIVATED.value)
        activated = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
        testcase.assertEqual(activated.stage, PreparationStage.ACTIVATED)
        testcase.assertEqual(activated.revision, claimed.revision + 1)

        second = advance_production_manager_once(scenario.runtime)
        testcase.assertEqual(second.status, ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED)
        testcase.assertEqual(second.action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        testcase.assertEqual(second.task_id, claimed.task_id)
        testcase.assertEqual(second.preparation_id, claimed.preparation_id)
        testcase.assertEqual(second.lower_status, PreparationRecoveryOnceStatus.RECOVERED_ROUTED.value)
        routed = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
        testcase.assertEqual(routed.stage, PreparationStage.ROUTED)
        testcase.assertEqual(routed.revision, claimed.revision + 2)
    return routed


def _assert_no_dispatch(testcase: unittest.TestCase, runtime: OriginForgeRuntime, task_id: str | None = None) -> None:
    with runtime.store.session() as conn:
        if task_id is None:
            claims = conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0]
            executions = conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0]
        else:
            claims = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            executions = conn.execute(
                "SELECT COUNT(*) FROM dispatch_executions WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
    testcase.assertEqual(claims, 0)
    testcase.assertEqual(executions, 0)


class Phase42CManagerRecoveryAcceptanceTests(unittest.TestCase):
    def test_oldest_recovery_advances_one_edge_per_call_and_never_falls_through(self) -> None:
        scenario = _scenario(self, steps=2)
        claimed = _claim_oldest(self, scenario)
        newer_task_id = _other_task_id(self, scenario, claimed.task_id)

        initial = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(initial.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(initial.candidate_count, 2)
        self.assertEqual(initial.candidates[0].task_id, claimed.task_id)
        self.assertEqual(initial.candidates[0].action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        self.assertEqual(initial.candidates[1].task_id, newer_task_id)
        self.assertEqual(initial.candidates[1].action_kind, ManagerAdvanceActionKind.PREPARE)

        _recover_to_routed(self, scenario, claimed)

        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(newer["revision"], 0)
        after = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(after.candidates[0].task_id, claimed.task_id)
        self.assertEqual(after.candidates[0].action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        self.assertEqual(after.candidates[0].preparation_stage, PreparationStage.ROUTED)
        self.assertEqual(after.candidates[1].task_id, newer_task_id)
        self.assertEqual(after.candidates[1].action_kind, ManagerAdvanceActionKind.PREPARE)
        _assert_no_dispatch(self, scenario.runtime)

    def test_routed_recovery_persists_planner_fence_and_stops_before_finalization(self) -> None:
        scenario = _scenario(self, steps=2)
        claimed = _claim_oldest(self, scenario)
        newer_task_id = _other_task_id(self, scenario, claimed.task_id)
        routed = _recover_to_routed(self, scenario, claimed)
        observed_stages: list[PreparationStage] = []

        def fake_generate(*args, **kwargs):
            durable = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
            observed_stages.append(durable.stage)
            self.assertEqual(durable.stage, PreparationStage.PLANNER_STARTED)
            self.assertEqual(durable.revision, routed.revision + 1)
            return phase40.Phase40ManagerAdvanceAcceptanceTests._response()

        with (
            patch.object(ScheduledModelAdapter, "generate", side_effect=fake_generate) as generate,
            patch.object(
                advance_module,
                "finalize_preparation_work_order_audit",
                side_effect=AssertionError("recovery same-call finalized WorkOrder"),
            ) as finalize_work_order,
            patch.object(
                advance_module,
                "finalize_preparation_phase34",
                side_effect=AssertionError("recovery same-call finalized Phase 34"),
            ) as finalize_phase34,
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                side_effect=AssertionError("recovery same-call dispatched"),
            ) as dispatch,
        ):
            result = advance_production_manager_once(scenario.runtime)

        self.assertEqual(generate.call_count, 1)
        finalize_work_order.assert_not_called()
        finalize_phase34.assert_not_called()
        dispatch.assert_not_called()
        self.assertEqual(observed_stages, [PreparationStage.PLANNER_STARTED])
        self.assertEqual(result.status, ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED)
        self.assertEqual(result.action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        self.assertEqual(result.task_id, claimed.task_id)
        self.assertEqual(result.preparation_id, claimed.preparation_id)
        self.assertEqual(result.lower_status, PreparationRecoveryOnceStatus.RESUMED_PLANNER_RETURNED.value)

        durable = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.PLANNER_RETURNED)
        post = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(post.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(post.candidates[0].task_id, claimed.task_id)
        self.assertEqual(post.candidates[0].action_kind, ManagerAdvanceActionKind.FINALIZE_WORK_ORDER)
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(newer["revision"], 0)
        _assert_no_dispatch(self, scenario.runtime)

    def test_concurrent_recovery_has_at_most_one_planner_call_and_never_dispatches_newer_task(self) -> None:
        scenario = _scenario(self, steps=2)
        claimed = _claim_oldest(self, scenario)
        newer_task_id = _other_task_id(self, scenario, claimed.task_id)
        _recover_to_routed(self, scenario, claimed)

        activate_dependency_ready_task(scenario.runtime, newer_task_id, 0)
        phase40.Phase40ManagerAdvanceAcceptanceTests._publish_pre_activation_chain(
            _ScenarioHarness(self),
            scenario,
            newer_task_id,
        )
        before = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(before.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(before.candidate_count, 2)
        self.assertEqual(before.candidates[0].task_id, claimed.task_id)
        self.assertEqual(before.candidates[0].action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        self.assertEqual(before.candidates[1].task_id, newer_task_id)
        self.assertEqual(before.candidates[1].action_kind, ManagerAdvanceActionKind.DISPATCH)

        real_recover = advance_module.recover_preparation_once
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        results = []
        failures: list[BaseException] = []
        model_calls = 0
        planner_stages: list[PreparationStage] = []

        def racing_recover(runtime, preparation_id):
            self.assertEqual(preparation_id, claimed.preparation_id)
            barrier.wait(timeout=15)
            return real_recover(runtime, preparation_id)

        def fake_generate(*args, **kwargs):
            nonlocal model_calls
            durable = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
            self.assertEqual(durable.stage, PreparationStage.PLANNER_STARTED)
            with lock:
                model_calls += 1
                planner_stages.append(durable.stage)
            return phase40.Phase40ManagerAdvanceAcceptanceTests._response()

        def worker() -> None:
            runtime = OriginForgeRuntime(scenario.root)
            try:
                value = advance_production_manager_once(runtime)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(advance_module, "recover_preparation_once", side_effect=racing_recover),
            patch.object(ScheduledModelAdapter, "generate", side_effect=fake_generate),
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                side_effect=AssertionError("recovery loser fell through to newer dispatchable Task"),
            ) as dispatch,
        ):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertLessEqual(model_calls, 1)
        self.assertEqual(len(planner_stages), model_calls)
        self.assertTrue(
            all(stage is PreparationStage.PLANNER_STARTED for stage in planner_stages)
        )
        dispatch.assert_not_called()
        self.assertTrue(all(result.task_id == claimed.task_id for result in results))
        self.assertTrue(all(result.preparation_id == claimed.preparation_id for result in results))
        self.assertTrue(all(result.action_kind is ManagerAdvanceActionKind.RECOVER_PREPARATION for result in results))
        self.assertTrue(
            all(
                result.status in {
                    ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED,
                    ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
                    ManagerAdvanceOnceStatus.INVALID_STATE,
                    ManagerAdvanceOnceStatus.AMBIGUOUS_AUTHORITY,
                }
                for result in results
            )
        )

        durable = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
        self.assertIn(
            durable.stage,
            {
                PreparationStage.ROUTED,
                PreparationStage.PLANNER_STARTED,
                PreparationStage.PLANNER_RETURNED,
            },
        )
        if planner_stages:
            self.assertIn(
                durable.stage,
                {
                    PreparationStage.PLANNER_STARTED,
                    PreparationStage.PLANNER_RETURNED,
                },
            )
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.READY.value)
        _assert_no_dispatch(self, scenario.runtime, newer_task_id)


if __name__ == "__main__":
    unittest.main()
