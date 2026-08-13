from __future__ import annotations

import ast
import inspect
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import origin_forge.production_manager_advance_once as advance_module
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmission,
    ManagerAdvanceAdmissionStatus,
    ManagerAdvanceCandidate,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)
from origin_forge.production_preparation_models import PreparationStage
from origin_forge.production_preparation_recovery_once import (
    PreparationRecoveryOnceResult,
    PreparationRecoveryOnceStatus,
)
from origin_forge.runtime import OriginForgeRuntime


TASK_ID = "TASK-00000000-0000-4000-8000-000000000042"
PREP_ID = "PREP-00000000-0000-4000-8000-000000000042"
CREATED_AT = "2026-01-01T00:00:00Z"


class Phase42BManagerRecoveryProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = OriginForgeRuntime("/tmp/origin-forge-phase42b-manager")

    @staticmethod
    def _candidate(stage: PreparationStage = PreparationStage.ROUTED) -> ManagerAdvanceCandidate:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVER_PREPARATION,
            TASK_ID,
            CREATED_AT,
            preparation_id=PREP_ID,
            preparation_stage=stage,
        )

    @staticmethod
    def _recovery_required_candidate() -> ManagerAdvanceCandidate:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVERY_REQUIRED,
            TASK_ID,
            CREATED_AT,
            preparation_id=PREP_ID,
            preparation_stage=PreparationStage.CLAIMED,
            detail="stale or unsupported authority",
        )

    @staticmethod
    def _admission(candidate: ManagerAdvanceCandidate) -> ManagerAdvanceAdmission:
        return ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.COMPLETE,
            candidates=(candidate,),
            dispatch_count=0,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=(
                1 if candidate.action_kind is ManagerAdvanceActionKind.RECOVERY_REQUIRED else 0
            ),
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            recover_preparation_count=(
                1 if candidate.action_kind is ManagerAdvanceActionKind.RECOVER_PREPARATION else 0
            ),
        )

    @staticmethod
    def _lower(
        status: PreparationRecoveryOnceStatus,
        *,
        preparation_id: str = PREP_ID,
        task_id: str | None = TASK_ID,
        detail: str | None = "lower detail",
    ) -> PreparationRecoveryOnceResult:
        return PreparationRecoveryOnceResult(
            status=status,
            preparation_id=preparation_id,
            task_id=task_id,
            classification=None,
            receipt=None,
            lower_status="phase41-internal-status",
            detail=detail,
        )

    def _run_recovery(
        self,
        candidate: ManagerAdvanceCandidate,
        lower: object,
    ):
        stack = ExitStack()
        stack.enter_context(
            patch.object(
                advance_module,
                "inspect_manager_advance_admission_readonly",
                return_value=self._admission(candidate),
            )
        )
        recover = stack.enter_context(
            patch.object(
                advance_module,
                "recover_preparation_once",
                return_value=lower,
            )
        )
        stack.enter_context(
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                side_effect=AssertionError("same-call dispatch attempted"),
            )
        )
        stack.enter_context(
            patch.object(
                advance_module,
                "_prepare_selected_candidate_once",
                side_effect=AssertionError("same-call preparation attempted"),
            )
        )
        stack.enter_context(
            patch.object(
                advance_module,
                "finalize_preparation_work_order_audit",
                side_effect=AssertionError("same-call WorkOrder finalization attempted"),
            )
        )
        stack.enter_context(
            patch.object(
                advance_module,
                "finalize_preparation_phase34",
                side_effect=AssertionError("same-call Phase34 finalization attempted"),
            )
        )
        try:
            result = advance_production_manager_once(self.runtime)
        finally:
            stack.close()
        return result, recover

    def test_selected_recovery_calls_phase41_once_and_stops(self) -> None:
        candidate = self._candidate()
        lower = self._lower(PreparationRecoveryOnceStatus.RECOVERED_ROUTED)
        result, recover = self._run_recovery(candidate, lower)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED)
        self.assertEqual(result.action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
        self.assertEqual(result.task_id, candidate.task_id)
        self.assertEqual(result.preparation_id, candidate.preparation_id)
        self.assertEqual(result.lower_status, PreparationRecoveryOnceStatus.RECOVERED_ROUTED.value)
        self.assertEqual(result.detail, lower.detail)
        recover.assert_called_once_with(self.runtime, candidate.preparation_id)

    def test_all_phase41_advancement_statuses_project_to_manager_success(self) -> None:
        statuses = (
            PreparationRecoveryOnceStatus.RECOVERED_ACTIVATED,
            PreparationRecoveryOnceStatus.ADOPTED_ACTIVATION_CHECKPOINT,
            PreparationRecoveryOnceStatus.RECOVERED_ROUTED,
            PreparationRecoveryOnceStatus.RESUMED_PLANNER_RETURNED,
            PreparationRecoveryOnceStatus.RECOVERED_PLANNER_RETURNED,
        )
        for lower_status in statuses:
            with self.subTest(lower_status=lower_status):
                candidate = self._candidate()
                result, recover = self._run_recovery(candidate, self._lower(lower_status))
                self.assertEqual(
                    result.status,
                    ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED,
                )
                self.assertEqual(result.lower_status, lower_status.value)
                recover.assert_called_once_with(self.runtime, candidate.preparation_id)

    def test_phase41_fail_closed_status_projection_is_exact(self) -> None:
        expected = {
            PreparationRecoveryOnceStatus.AMBIGUOUS_EVIDENCE: ManagerAdvanceOnceStatus.AMBIGUOUS_AUTHORITY,
            PreparationRecoveryOnceStatus.LIMIT_EXCEEDED: ManagerAdvanceOnceStatus.LIMIT_EXCEEDED,
            PreparationRecoveryOnceStatus.INVALID_STATE: ManagerAdvanceOnceStatus.INVALID_STATE,
            PreparationRecoveryOnceStatus.PLANNER_RECOVERY_REQUIRED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
            PreparationRecoveryOnceStatus.ACTIVATION_RECOVERY_REJECTED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
            PreparationRecoveryOnceStatus.ROUTE_RECOVERY_REJECTED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
            PreparationRecoveryOnceStatus.INVALID_AUTHORITY: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
            PreparationRecoveryOnceStatus.POST_PLANNER_NOT_REQUIRED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
            PreparationRecoveryOnceStatus.READY_NOT_REQUIRED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
            PreparationRecoveryOnceStatus.TERMINAL_NOT_REQUIRED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
        }
        for lower_status, manager_status in expected.items():
            with self.subTest(lower_status=lower_status):
                candidate = self._candidate()
                result, recover = self._run_recovery(candidate, self._lower(lower_status))
                self.assertEqual(result.status, manager_status)
                self.assertEqual(result.lower_status, lower_status.value)
                self.assertEqual(result.detail, "lower detail")
                recover.assert_called_once_with(self.runtime, candidate.preparation_id)

    def test_invalid_lower_type_fails_closed(self) -> None:
        candidate = self._candidate()
        result, recover = self._run_recovery(candidate, object())

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.INVALID_STATE)
        self.assertIsNone(result.lower_status)
        self.assertIn("invalid result type", result.detail or "")
        recover.assert_called_once_with(self.runtime, candidate.preparation_id)

    def test_typed_identity_mismatch_fails_closed_and_preserves_lower_status(self) -> None:
        cases = (
            (
                "mismatched PREP",
                self._lower(
                    PreparationRecoveryOnceStatus.RECOVERED_ROUTED,
                    preparation_id="PREP-00000000-0000-4000-8000-000000000099",
                ),
                "mismatched PREP ID",
            ),
            (
                "mismatched Task",
                self._lower(
                    PreparationRecoveryOnceStatus.RECOVERED_ROUTED,
                    task_id="TASK-00000000-0000-4000-8000-000000000099",
                ),
                "mismatched Task ID",
            ),
        )
        for label, lower, detail_fragment in cases:
            with self.subTest(case=label):
                candidate = self._candidate()
                result, recover = self._run_recovery(candidate, lower)
                self.assertEqual(result.status, ManagerAdvanceOnceStatus.INVALID_STATE)
                self.assertEqual(
                    result.lower_status,
                    PreparationRecoveryOnceStatus.RECOVERED_ROUTED.value,
                )
                self.assertIn(detail_fragment, result.detail or "")
                self.assertIn("lower detail", result.detail or "")
                recover.assert_called_once_with(self.runtime, candidate.preparation_id)

    def test_invalid_selected_recovery_shape_fails_before_phase41_call(self) -> None:
        candidate = self._candidate()
        object.__setattr__(candidate, "preparation_id", "")
        with (
            patch.object(
                advance_module,
                "inspect_manager_advance_admission_readonly",
                return_value=self._admission(candidate),
            ),
            patch.object(
                advance_module,
                "recover_preparation_once",
                side_effect=AssertionError("invalid candidate reached Phase 41"),
            ) as recover,
        ):
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.INVALID_STATE)
        self.assertIn("lacks PREP ID", result.detail or "")
        recover.assert_not_called()

    def test_ordinary_recovery_required_remains_zero_action(self) -> None:
        candidate = self._recovery_required_candidate()
        with (
            patch.object(
                advance_module,
                "inspect_manager_advance_admission_readonly",
                return_value=self._admission(candidate),
            ),
            patch.object(
                advance_module,
                "recover_preparation_once",
                side_effect=AssertionError("fail-closed candidate entered Phase 41"),
            ) as recover,
        ):
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.detail, candidate.detail)
        recover.assert_not_called()

    def test_manager_source_keeps_exact_one_shot_action_sites_and_no_loop(self) -> None:
        source = inspect.getsource(advance_production_manager_once)
        tree = ast.parse(source)
        calls = [
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        ]

        self.assertEqual(calls.count("inspect_manager_advance_admission_readonly"), 1)
        self.assertEqual(calls.count("select_manager_advance_candidate"), 1)
        self.assertEqual(calls.count("recover_preparation_once"), 1)
        self.assertEqual(calls.count("_dispatch_selected_candidate_once"), 1)
        self.assertEqual(calls.count("_prepare_selected_candidate_once"), 1)
        self.assertEqual(calls.count("finalize_preparation_work_order_audit"), 1)
        self.assertEqual(calls.count("finalize_preparation_phase34"), 1)
        self.assertFalse(any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree)))
        self.assertEqual(
            tuple(inspect.signature(advance_production_manager_once).parameters),
            ("runtime",),
        )


if __name__ == "__main__":
    unittest.main()
