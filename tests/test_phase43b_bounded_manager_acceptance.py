from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

import origin_forge.production_manager_advance_bounded as bounded_module
import origin_forge.production_manager_dispatch_tick as dispatch_tick_module
import origin_forge.production_preparation_tick as preparation_tick_module
from . import test_phase40_manager_advance_acceptance as phase40
from . import test_phase42c_manager_recovery_acceptance as phase42
from origin_forge.ids import IdKind, new_id
from origin_forge.orchestration_policy import PolicyOutcome
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_invocation import ProductionDispatchInvocationError
from origin_forge.production_dispatch_invocation_read import (
    DispatchInvocationStatus,
    DispatchInvocationStatusProjection,
)
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmissionStatus,
    inspect_manager_advance_admission_readonly,
)
from origin_forge.production_manager_advance_bounded import (
    BoundedManagerAdvanceStopReason,
    advance_production_manager_bounded,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)
from origin_forge.production_preparation_models import PreparationStage
from origin_forge.production_preparation_receipts import read_preparation_receipt
from origin_forge.production_preparation_recovery_once import PreparationRecoveryOnceStatus
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import TaskStatus


def _dispatch_scenario(testcase: unittest.TestCase, *, tasks: int = 2):
    return phase40.Phase40ManagerAdvanceAcceptanceTests._dispatch_scenario(
        phase42._ScenarioHarness(testcase),
        tasks=tasks,
    )


class Phase43BBoundedManagerAcceptanceTests(unittest.TestCase):
    def test_fresh_prepare_path_reaches_one_dispatch_return_and_never_drains_newer_task(self) -> None:
        scenario = phase42._scenario(self, steps=2)
        claims_by_id = {}
        completed = []

        def capture_claim(runtime, binding_id, audit_id, revision):
            claim = acquire_dispatch_claim(runtime, binding_id, audit_id, revision)
            claims_by_id[claim.claim_id] = claim
            return claim

        def fake_dispatch(runtime, claim_id, expected_revision):
            self.assertEqual(expected_revision, 0)
            invocation = phase40.Phase40ManagerAdvanceAcceptanceTests._completed_for_claim(
                claims_by_id[claim_id]
            )
            completed.append(invocation)
            return invocation

        with (
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=phase40.Phase40ManagerAdvanceAcceptanceTests._response(),
            ) as generate,
            patch.object(
                dispatch_tick_module,
                "acquire_dispatch_claim",
                side_effect=capture_claim,
            ),
            patch.object(
                dispatch_tick_module,
                "dispatch_claim_once",
                side_effect=fake_dispatch,
            ) as dispatch,
            patch.object(
                bounded_module,
                "advance_production_manager_once",
                wraps=advance_production_manager_once,
            ) as advance,
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(
            tuple(step.status for step in result.steps),
            (
                ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
                ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
                ManagerAdvanceOnceStatus.PHASE34_READY,
                ManagerAdvanceOnceStatus.DISPATCH_RETURNED,
            ),
        )
        self.assertEqual(result.step_count, 4)
        self.assertEqual(advance.call_count, 4)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(
            result.stop_reason,
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
        )
        self.assertEqual(len(completed), 1)
        self.assertIs(completed[0].policy_result.outcome, PolicyOutcome.BLOCKED)
        self.assertEqual(result.final_result.claim_id, completed[0].execution.claim_id)
        self.assertEqual(result.final_result.execution_id, completed[0].execution.execution_id)

        selected_task_id = result.steps[0].task_id
        self.assertIsNotNone(selected_task_id)
        self.assertTrue(all(step.task_id == selected_task_id for step in result.steps))
        newer_task_id = phase42._other_task_id(self, scenario, selected_task_id)
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(newer["revision"], 0)
        phase42._assert_no_dispatch(self, scenario.runtime, newer_task_id)

    def test_claimed_recovery_path_uses_exactly_six_steps_and_stops_on_dispatch(self) -> None:
        scenario = phase42._scenario(self, steps=1)
        claimed = phase42._claim_oldest(self, scenario)
        claims_by_id = {}
        planner_stages: list[PreparationStage] = []

        def fake_generate(*args, **kwargs):
            durable = read_preparation_receipt(scenario.runtime, claimed.preparation_id)
            planner_stages.append(durable.stage)
            self.assertEqual(durable.stage, PreparationStage.PLANNER_STARTED)
            return phase40.Phase40ManagerAdvanceAcceptanceTests._response()

        def capture_claim(runtime, binding_id, audit_id, revision):
            claim = acquire_dispatch_claim(runtime, binding_id, audit_id, revision)
            claims_by_id[claim.claim_id] = claim
            return claim

        def fake_dispatch(runtime, claim_id, expected_revision):
            self.assertEqual(expected_revision, 0)
            return phase40.Phase40ManagerAdvanceAcceptanceTests._completed_for_claim(
                claims_by_id[claim_id]
            )

        with (
            patch.object(ScheduledModelAdapter, "generate", side_effect=fake_generate) as generate,
            patch.object(
                dispatch_tick_module,
                "acquire_dispatch_claim",
                side_effect=capture_claim,
            ),
            patch.object(
                dispatch_tick_module,
                "dispatch_claim_once",
                side_effect=fake_dispatch,
            ) as dispatch,
            patch.object(
                bounded_module,
                "advance_production_manager_once",
                wraps=advance_production_manager_once,
            ) as advance,
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(result.step_count, 6)
        self.assertEqual(advance.call_count, 6)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(planner_stages, [PreparationStage.PLANNER_STARTED])
        self.assertEqual(
            tuple(step.status for step in result.steps),
            (
                ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED,
                ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED,
                ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED,
                ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
                ManagerAdvanceOnceStatus.PHASE34_READY,
                ManagerAdvanceOnceStatus.DISPATCH_RETURNED,
            ),
        )
        self.assertEqual(
            tuple(step.lower_status for step in result.steps[:3]),
            (
                PreparationRecoveryOnceStatus.RECOVERED_ACTIVATED.value,
                PreparationRecoveryOnceStatus.RECOVERED_ROUTED.value,
                PreparationRecoveryOnceStatus.RESUMED_PLANNER_RETURNED.value,
            ),
        )
        self.assertTrue(all(step.task_id == claimed.task_id for step in result.steps))
        self.assertEqual(
            result.stop_reason,
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
        )

    def test_preplanner_failure_stops_without_falling_through_to_newer_task(self) -> None:
        scenario = phase42._scenario(self, steps=2)
        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        selected_task_id = admission.candidates[0].task_id
        newer_task_id = phase42._other_task_id(self, scenario, selected_task_id)

        with (
            patch.object(
                preparation_tick_module.ProductionCapabilityStore,
                "resolve_and_publish",
                side_effect=RuntimeError("forced pre-planner routing failure"),
            ),
            patch.object(
                ScheduledModelAdapter,
                "generate",
                side_effect=AssertionError("pre-planner failure crossed model boundary"),
            ) as generate,
            patch.object(
                bounded_module,
                "advance_production_manager_once",
                wraps=advance_production_manager_once,
            ) as advance,
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(result.step_count, 1)
        self.assertEqual(advance.call_count, 1)
        generate.assert_not_called()
        self.assertEqual(
            result.final_result.status,
            ManagerAdvanceOnceStatus.PREPARATION_FAILED_PRE_PLANNER,
        )
        self.assertEqual(result.final_result.task_id, selected_task_id)
        self.assertEqual(
            result.stop_reason,
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
        )
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(newer["revision"], 0)
        phase42._assert_no_dispatch(self, scenario.runtime)
        with scenario.runtime.store.session() as conn:
            prep_rows = conn.execute(
                "SELECT task_id, status FROM task_preparations ORDER BY rowid"
            ).fetchall()
        self.assertEqual(len(prep_rows), 1)
        self.assertEqual(prep_rows[0]["task_id"], selected_task_id)
        self.assertEqual(prep_rows[0]["status"], "FAILED_PRE_PLANNER")

    def test_dispatch_raised_stops_without_dispatching_newer_task(self) -> None:
        scenario = _dispatch_scenario(self, tasks=2)
        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 2)
        selected = admission.candidates[0]
        newer = admission.candidates[1]
        self.assertEqual(selected.action_kind, ManagerAdvanceActionKind.DISPATCH)
        self.assertEqual(newer.action_kind, ManagerAdvanceActionKind.DISPATCH)

        claims_by_id = {}
        execution_id = new_id(IdKind.DISPATCH_EXECUTION)

        def capture_claim(runtime, binding_id, audit_id, revision):
            claim = acquire_dispatch_claim(runtime, binding_id, audit_id, revision)
            claims_by_id[claim.claim_id] = claim
            return claim

        def raised_projection(runtime, claim_id):
            claim = claims_by_id[claim_id]
            return DispatchInvocationStatusProjection(
                claim.claim_id,
                claim.task_id,
                execution_id,
                DispatchInvocationStatus.RAISED,
                None,
            )

        with (
            patch.object(
                dispatch_tick_module,
                "acquire_dispatch_claim",
                side_effect=capture_claim,
            ),
            patch.object(
                dispatch_tick_module,
                "dispatch_claim_once",
                side_effect=ProductionDispatchInvocationError("forced owner raise"),
            ) as dispatch,
            patch.object(
                dispatch_tick_module,
                "inspect_dispatch_invocation_status_readonly",
                side_effect=raised_projection,
            ),
            patch.object(
                bounded_module,
                "advance_production_manager_once",
                wraps=advance_production_manager_once,
            ) as advance,
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(result.step_count, 1)
        self.assertEqual(advance.call_count, 1)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(result.final_result.status, ManagerAdvanceOnceStatus.DISPATCH_RAISED)
        self.assertEqual(result.final_result.task_id, selected.task_id)
        self.assertEqual(result.final_result.execution_id, execution_id)
        self.assertEqual(
            result.stop_reason,
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
        )
        with scenario.runtime.store.session() as conn:
            selected_claims = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (selected.task_id,),
            ).fetchone()[0]
            newer_claims = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (newer.task_id,),
            ).fetchone()[0]
        self.assertEqual(selected_claims, 1)
        self.assertEqual(newer_claims, 0)

    def test_concurrent_drivers_stop_after_first_race_result_and_never_try_newer_task(self) -> None:
        scenario = phase42._scenario(self, steps=2)
        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        selected_task_id = admission.candidates[0].task_id
        newer_task_id = phase42._other_task_id(self, scenario, selected_task_id)

        real_acquire = preparation_tick_module.acquire_preparation_receipt
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        model_calls = 0
        results = []
        failures: list[BaseException] = []

        def racing_acquire(runtime, policy, candidate):
            self.assertEqual(candidate.task_id, selected_task_id)
            barrier.wait(timeout=15)
            return real_acquire(runtime, policy, candidate)

        def uncertain_generate(*args, **kwargs):
            nonlocal model_calls
            with lock:
                model_calls += 1
            raise RuntimeError("forced uncertain planner transport")

        def worker() -> None:
            runtime = OriginForgeRuntime(scenario.root)
            try:
                value = advance_production_manager_bounded(runtime)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(
                preparation_tick_module,
                "acquire_preparation_receipt",
                side_effect=racing_acquire,
            ),
            patch.object(ScheduledModelAdapter, "generate", side_effect=uncertain_generate),
        ):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=25)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertLessEqual(model_calls, 1)
        self.assertTrue(all(result.step_count == 1 for result in results))
        self.assertTrue(
            all(
                result.stop_reason is BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT
                for result in results
            )
        )
        self.assertTrue(all(result.final_result.task_id == selected_task_id for result in results))
        self.assertTrue(
            all(
                result.final_result.status
                in {
                    ManagerAdvanceOnceStatus.PREPARATION_NOT_ACQUIRED,
                    ManagerAdvanceOnceStatus.PREPARATION_FAILED_PRE_PLANNER,
                    ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RECOVERY_REQUIRED,
                }
                for result in results
            )
        )
        self.assertEqual(
            sum(
                result.final_result.status is ManagerAdvanceOnceStatus.PREPARATION_NOT_ACQUIRED
                for result in results
            ),
            1,
        )

        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(newer["revision"], 0)
        phase42._assert_no_dispatch(self, scenario.runtime)
        with scenario.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT task_id FROM task_preparations ORDER BY rowid"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_id"], selected_task_id)


if __name__ == "__main__":
    unittest.main()
