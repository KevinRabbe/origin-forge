from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_manager_advance_bounded as bounded_module
from origin_forge.production_manager_advance_bounded import (
    MANAGER_ADVANCE_CONTINUATION_STATUSES,
    MAX_MANAGER_ADVANCE_STEPS,
    BoundedManagerAdvanceResult,
    BoundedManagerAdvanceStopReason,
    advance_production_manager_bounded,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceResult,
    ManagerAdvanceOnceStatus,
)


class BoundedManagerAdvanceTests(unittest.TestCase):
    @staticmethod
    def _result(status: ManagerAdvanceOnceStatus) -> ManagerAdvanceOnceResult:
        return ManagerAdvanceOnceResult(
            status=status,
            action_kind=None,
            task_id=None,
            task_created_at=None,
            detail=f"{status.value}-detail",
        )

    def test_only_frozen_four_statuses_continue(self) -> None:
        self.assertEqual(
            MANAGER_ADVANCE_CONTINUATION_STATUSES,
            frozenset(
                {
                    ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED,
                    ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
                    ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
                    ManagerAdvanceOnceStatus.PHASE34_READY,
                }
            ),
        )

        terminal = self._result(ManagerAdvanceOnceStatus.DISPATCH_RETURNED)
        for status in MANAGER_ADVANCE_CONTINUATION_STATUSES:
            with self.subTest(status=status):
                first = self._result(status)
                with patch.object(
                    bounded_module,
                    "advance_production_manager_once",
                    side_effect=(first, terminal),
                ) as advance:
                    result = advance_production_manager_bounded(object())

                self.assertEqual(advance.call_count, 2)
                self.assertEqual(result.steps, (first, terminal))
                self.assertEqual(
                    result.stop_reason,
                    BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
                )

    def test_every_noncontinuable_status_stops_after_one_call(self) -> None:
        for status in ManagerAdvanceOnceStatus:
            if status in MANAGER_ADVANCE_CONTINUATION_STATUSES:
                continue
            with self.subTest(status=status):
                once = self._result(status)
                with patch.object(
                    bounded_module,
                    "advance_production_manager_once",
                    return_value=once,
                ) as advance:
                    result = advance_production_manager_bounded(object())

                self.assertEqual(advance.call_count, 1)
                self.assertEqual(result.steps, (once,))
                expected = (
                    BoundedManagerAdvanceStopReason.NO_ACTIONABLE_WORK
                    if status is ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK
                    else BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT
                )
                self.assertEqual(result.stop_reason, expected)

    def test_positive_lifecycle_trace_stops_at_first_dispatch_result(self) -> None:
        sequence = (
            self._result(ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED),
            self._result(ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED),
            self._result(ManagerAdvanceOnceStatus.PHASE34_READY),
            self._result(ManagerAdvanceOnceStatus.DISPATCH_RETURNED),
            self._result(ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED),
        )
        with patch.object(
            bounded_module,
            "advance_production_manager_once",
            side_effect=sequence,
        ) as advance:
            result = advance_production_manager_bounded(object())

        self.assertEqual(advance.call_count, 4)
        self.assertEqual(result.steps, sequence[:4])
        self.assertIs(result.final_result, sequence[3])
        self.assertEqual(result.step_count, 4)
        self.assertEqual(
            result.stop_reason,
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
        )

    def test_six_continuable_results_hit_hard_limit_without_seventh_call(self) -> None:
        status_cycle = tuple(MANAGER_ADVANCE_CONTINUATION_STATUSES)
        sequence = tuple(
            self._result(status_cycle[index % len(status_cycle)])
            for index in range(MAX_MANAGER_ADVANCE_STEPS)
        )
        with patch.object(
            bounded_module,
            "advance_production_manager_once",
            side_effect=sequence,
        ) as advance:
            result = advance_production_manager_bounded(object())

        self.assertEqual(MAX_MANAGER_ADVANCE_STEPS, 6)
        self.assertEqual(advance.call_count, MAX_MANAGER_ADVANCE_STEPS)
        self.assertEqual(result.steps, sequence)
        self.assertEqual(result.step_count, MAX_MANAGER_ADVANCE_STEPS)
        self.assertEqual(result.max_steps, MAX_MANAGER_ADVANCE_STEPS)
        self.assertEqual(
            result.stop_reason,
            BoundedManagerAdvanceStopReason.STEP_LIMIT_REACHED,
        )

    def test_invalid_one_shot_result_type_fails_closed_without_retry(self) -> None:
        with patch.object(
            bounded_module,
            "advance_production_manager_once",
            return_value=object(),
        ) as advance:
            with self.assertRaisesRegex(TypeError, "invalid result type"):
                advance_production_manager_bounded(object())

        self.assertEqual(advance.call_count, 1)

    def test_invalid_one_shot_status_type_fails_closed_without_retry(self) -> None:
        malformed = ManagerAdvanceOnceResult(
            status="BROKEN",  # type: ignore[arg-type]
            action_kind=None,
            task_id=None,
            task_created_at=None,
        )
        with patch.object(
            bounded_module,
            "advance_production_manager_once",
            return_value=malformed,
        ) as advance:
            with self.assertRaisesRegex(TypeError, "status must be"):
                advance_production_manager_bounded(object())

        self.assertEqual(advance.call_count, 1)

    def test_result_trace_is_immutable_and_serializes_exact_steps(self) -> None:
        first = self._result(ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED)
        second = self._result(ManagerAdvanceOnceStatus.DISPATCH_RAISED)
        result = BoundedManagerAdvanceResult(
            (first, second),
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
        )

        self.assertEqual(result.step_count, 2)
        self.assertIs(result.final_result, second)
        self.assertEqual(
            result.to_dict(),
            {
                "steps": [first.to_dict(), second.to_dict()],
                "step_count": 2,
                "stop_reason": "NON_CONTINUABLE_RESULT",
                "max_steps": 6,
                "authority": "bounded-manager-advance-driver",
            },
        )
        with self.assertRaises(FrozenInstanceError):
            result.stop_reason = BoundedManagerAdvanceStopReason.NO_ACTIONABLE_WORK  # type: ignore[misc]

    def test_result_constructor_rejects_inconsistent_stop_claims(self) -> None:
        continuable = self._result(ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED)
        terminal = self._result(ManagerAdvanceOnceStatus.DISPATCH_RETURNED)
        idle = self._result(ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK)

        with self.assertRaises(ValueError):
            BoundedManagerAdvanceResult(
                (continuable,),
                BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
            )
        with self.assertRaises(ValueError):
            BoundedManagerAdvanceResult(
                (terminal,),
                BoundedManagerAdvanceStopReason.NO_ACTIONABLE_WORK,
            )
        with self.assertRaises(ValueError):
            BoundedManagerAdvanceResult(
                (idle,),
                BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT,
            )
        with self.assertRaises(ValueError):
            BoundedManagerAdvanceResult(
                (continuable,),
                BoundedManagerAdvanceStopReason.STEP_LIMIT_REACHED,
            )

    def test_public_driver_surface_has_no_caller_selected_budget(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(advance_production_manager_bounded).parameters),
            ("runtime",),
        )
        self.assertEqual(
            tuple(inspect.signature(BoundedManagerAdvanceResult).parameters),
            ("steps", "stop_reason"),
        )

    def test_source_composes_only_public_one_shot_manager_primitive(self) -> None:
        source = Path(bounded_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        relative_imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level > 0
        }
        self.assertEqual(relative_imports, {"production_manager_advance_once"})
        self.assertFalse(any(isinstance(node, ast.While) for node in ast.walk(tree)))
        self.assertFalse(any(isinstance(node, ast.Try) for node in ast.walk(tree)))

        one_shot_calls = 0
        forbidden_calls = {
            "recover_preparation_once",
            "finalize_preparation_work_order_audit",
            "finalize_preparation_phase34",
            "acquire_dispatch_claim",
            "dispatch_claim_once",
            "prepare_materialization_tick",
            "dispatch_manager_tick",
            "generate",
            "propose",
            "sleep",
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            else:
                continue
            if call_name == "advance_production_manager_once":
                one_shot_calls += 1
            self.assertNotIn(call_name, forbidden_calls)
        self.assertEqual(one_shot_calls, 1)


if __name__ == "__main__":
    unittest.main()
