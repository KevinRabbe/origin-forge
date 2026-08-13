from __future__ import annotations

import ast
import unittest
from pathlib import Path

import origin_forge.production_manager_advance_selection as selection_module
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmission,
    ManagerAdvanceAdmissionStatus,
    ManagerAdvanceCandidate,
)
from origin_forge.production_manager_advance_selection import (
    ManagerAdvanceSelectionStatus,
    select_manager_advance_candidate,
)
from origin_forge.production_preparation_models import PreparationStage


class ManagerAdvanceSelectionTests(unittest.TestCase):
    def _recovery(self, task_id: str, created_at: str) -> ManagerAdvanceCandidate:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVERY_REQUIRED,
            task_id,
            created_at,
            preparation_id="PREP-00000000-0000-4000-8000-000000000001",
            preparation_stage=PreparationStage.CLAIMED,
            detail="recovery required",
        )

    def _complete(self, candidates: tuple[ManagerAdvanceCandidate, ...]) -> ManagerAdvanceAdmission:
        return ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.COMPLETE,
            candidates=candidates,
            dispatch_count=0,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=len(candidates),
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )

    def test_selects_exactly_first_admitted_candidate(self) -> None:
        first = self._recovery("TASK-00000000-0000-4000-8000-000000000001", "2026-01-01")
        second = self._recovery("TASK-00000000-0000-4000-8000-000000000002", "2026-01-02")

        result = select_manager_advance_candidate(self._complete((first, second)))

        self.assertEqual(result.status, ManagerAdvanceSelectionStatus.ONE_SELECTED)
        self.assertIs(result.candidate, first)

    def test_empty_complete_admission_is_no_actionable_work(self) -> None:
        result = select_manager_advance_candidate(self._complete(()))

        self.assertEqual(result.status, ManagerAdvanceSelectionStatus.NO_ACTIONABLE_WORK)
        self.assertIsNone(result.candidate)

    def test_unsorted_complete_admission_fails_closed_instead_of_recomputing_minimum(self) -> None:
        older = self._recovery("TASK-00000000-0000-4000-8000-000000000001", "2026-01-01")
        newer = self._recovery("TASK-00000000-0000-4000-8000-000000000002", "2026-01-02")

        result = select_manager_advance_candidate(self._complete((newer, older)))

        self.assertEqual(result.status, ManagerAdvanceSelectionStatus.INVALID_STATE)
        self.assertIsNone(result.candidate)

    def test_duplicate_task_authority_fails_closed(self) -> None:
        first = self._recovery("TASK-00000000-0000-4000-8000-000000000001", "2026-01-01")
        duplicate = self._recovery("TASK-00000000-0000-4000-8000-000000000001", "2026-01-02")

        result = select_manager_advance_candidate(self._complete((first, duplicate)))

        self.assertEqual(result.status, ManagerAdvanceSelectionStatus.INVALID_STATE)

    def test_counter_drift_fails_closed(self) -> None:
        candidate = self._recovery("TASK-00000000-0000-4000-8000-000000000001", "2026-01-01")
        admission = self._complete((candidate,))
        malformed = ManagerAdvanceAdmission(
            status=admission.status,
            candidates=admission.candidates,
            dispatch_count=1,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=1,
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )

        result = select_manager_advance_candidate(malformed)

        self.assertEqual(result.status, ManagerAdvanceSelectionStatus.INVALID_STATE)

    def test_upstream_ambiguous_admission_is_preserved(self) -> None:
        admission = ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY,
            candidates=(),
            dispatch_count=0,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=0,
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            ambiguous_task_ids=("TASK-00000000-0000-4000-8000-000000000001",),
            detail="ambiguous authority",
        )

        result = select_manager_advance_candidate(admission)

        self.assertEqual(result.status, ManagerAdvanceSelectionStatus.AMBIGUOUS_AUTHORITY)
        self.assertIsNone(result.candidate)

    def test_malformed_failed_admission_with_partial_candidate_is_invalid(self) -> None:
        candidate = self._recovery("TASK-00000000-0000-4000-8000-000000000001", "2026-01-01")
        admission = ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.LIMIT_EXCEEDED,
            candidates=(candidate,),
            dispatch_count=0,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=0,
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            ambiguous_task_ids=(),
            detail="limit",
        )

        result = select_manager_advance_candidate(admission)

        self.assertEqual(result.status, ManagerAdvanceSelectionStatus.INVALID_STATE)

    def test_selector_source_is_pure(self) -> None:
        source = Path(selection_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        forbidden_fragments = (
            "runtime",
            "store",
            "sqlite",
            "dispatch_tick",
            "preparation_tick",
            "finalize",
            "claim",
            "invocation",
            "model_adapter",
        )
        self.assertTrue(
            all(
                all(fragment not in module for fragment in forbidden_fragments)
                for module in imported_modules
            )
        )


if __name__ == "__main__":
    unittest.main()
