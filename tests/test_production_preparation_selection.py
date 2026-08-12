from __future__ import annotations

import unittest

from origin_forge.production_preparation_admission import (
    MaterializationPreparationAdmission,
    PreparationAdmissionStatus,
    PreparationCandidate,
)
from origin_forge.production_preparation_selection import (
    PreparationSelectionStatus,
    select_preparation_candidate,
)


class PreparationSelectionTests(unittest.TestCase):
    def _candidate(self, task_id: str, created_at: str) -> PreparationCandidate:
        return PreparationCandidate(
            task_id=task_id,
            task_revision=0,
            task_content_hash="a" * 64,
            created_at=created_at,
            step_key=task_id,
            required_capabilities=("code.change",),
        )

    def _admission(self, candidates: tuple[PreparationCandidate, ...]):
        return MaterializationPreparationAdmission(
            status=PreparationAdmissionStatus.COMPLETE,
            preparation_policy_id="PREPPOL-test",
            materialization_id="PLMAT-test",
            candidates=candidates,
            not_queued_exclusion_count=0,
            dependency_exclusion_count=0,
            active_preparation_exclusion_count=0,
            phase38_admissible_exclusion_count=0,
            detail=None,
        )

    def test_selects_exact_first_candidate_without_recomputing_minimum(self) -> None:
        first = self._candidate("TASK-a", "2026-01-01T00:00:00+00:00")
        second = self._candidate("TASK-b", "2026-01-02T00:00:00+00:00")
        selected = select_preparation_candidate(self._admission((first, second)))
        self.assertEqual(selected.status, PreparationSelectionStatus.ONE_SELECTED)
        self.assertIs(selected.candidate, first)

    def test_unsorted_complete_admission_is_invalid_instead_of_resorted(self) -> None:
        first = self._candidate("TASK-a", "2026-01-01T00:00:00+00:00")
        second = self._candidate("TASK-b", "2026-01-02T00:00:00+00:00")
        selected = select_preparation_candidate(self._admission((second, first)))
        self.assertEqual(selected.status, PreparationSelectionStatus.INVALID_STATE)
        self.assertIsNone(selected.candidate)

    def test_empty_complete_admission_returns_no_eligible_task(self) -> None:
        selected = select_preparation_candidate(self._admission(()))
        self.assertEqual(selected.status, PreparationSelectionStatus.NO_ELIGIBLE_TASK)
        self.assertIsNone(selected.candidate)

    def test_non_complete_admission_is_invalid(self) -> None:
        admission = MaterializationPreparationAdmission(
            status=PreparationAdmissionStatus.INVALID_POLICY_PROVENANCE,
            preparation_policy_id="PREPPOL-test",
            materialization_id="PLMAT-test",
            candidates=(),
            not_queued_exclusion_count=0,
            dependency_exclusion_count=0,
            active_preparation_exclusion_count=0,
            phase38_admissible_exclusion_count=0,
            detail="invalid",
        )
        selected = select_preparation_candidate(admission)
        self.assertEqual(selected.status, PreparationSelectionStatus.INVALID_STATE)
        self.assertIsNone(selected.candidate)


if __name__ == "__main__":
    unittest.main()
