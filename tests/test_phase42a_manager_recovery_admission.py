from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_manager_advance_admission as admission_module
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmission,
    ManagerAdvanceAdmissionStatus,
    ManagerAdvanceCandidate,
    _receipt_candidate,
)
from origin_forge.production_manager_advance_selection import (
    ManagerAdvanceSelectionStatus,
    select_manager_advance_candidate,
)
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_status import PreparationInspectionState


class Phase42ARecoveryAdmissionTests(unittest.TestCase):
    @staticmethod
    def _entry(stage: PreparationStage):
        receipt = SimpleNamespace(
            status=PreparationStatus.ACTIVE,
            stage=stage,
            task_id="TASK-00000000-0000-4000-8000-000000000001",
            preparation_id="PREP-00000000-0000-4000-8000-000000000001",
        )
        return SimpleNamespace(receipt=receipt, task_created_at="2026-01-01T00:00:00Z")

    @staticmethod
    def _projection(*, current: bool = True, stale: bool = False):
        return SimpleNamespace(
            current=current,
            state=(
                PreparationInspectionState.STALE_OR_INVALID
                if stale
                else PreparationInspectionState.ACTIVE_PRE_PLANNER
            ),
            detail="stale authority" if stale else None,
        )

    @staticmethod
    def _admission(candidate: ManagerAdvanceCandidate, *, recover_count: int = 1):
        return ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.COMPLETE,
            candidates=(candidate,),
            dispatch_count=0,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=0,
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            recover_preparation_count=recover_count,
        )

    def test_exact_current_preplanner_stages_admit_safe_recovery(self) -> None:
        runtime = object()
        for stage in (
            PreparationStage.CLAIMED,
            PreparationStage.ACTIVATED,
            PreparationStage.ROUTED,
        ):
            with self.subTest(stage=stage):
                candidate = _receipt_candidate(runtime, self._entry(stage), self._projection())
                self.assertEqual(candidate.action_kind, ManagerAdvanceActionKind.RECOVER_PREPARATION)
                self.assertEqual(candidate.preparation_stage, stage)
                self.assertIsNone(candidate.detail)

    def test_noncurrent_or_stale_preplanner_authority_remains_fail_closed(self) -> None:
        runtime = object()
        with patch.object(
            admission_module,
            "_legacy_claimed_recovery_is_adoptable",
            return_value=False,
        ) as legacy_adoptable:
            for projection in (
                self._projection(current=False),
                self._projection(stale=True),
            ):
                with self.subTest(projection=projection):
                    candidate = _receipt_candidate(
                        runtime,
                        self._entry(PreparationStage.CLAIMED),
                        projection,
                    )
                    self.assertEqual(candidate.action_kind, ManagerAdvanceActionKind.RECOVERY_REQUIRED)
                    self.assertTrue(candidate.detail)
        self.assertEqual(legacy_adoptable.call_count, 2)

    def test_selector_validates_recover_preparation_counter(self) -> None:
        candidate = ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVER_PREPARATION,
            "TASK-00000000-0000-4000-8000-000000000001",
            "2026-01-01T00:00:00Z",
            preparation_id="PREP-00000000-0000-4000-8000-000000000001",
            preparation_stage=PreparationStage.CLAIMED,
        )
        accepted = select_manager_advance_candidate(self._admission(candidate))
        rejected = select_manager_advance_candidate(self._admission(candidate, recover_count=0))

        self.assertEqual(accepted.status, ManagerAdvanceSelectionStatus.ONE_SELECTED)
        self.assertIs(accepted.candidate, candidate)
        self.assertEqual(rejected.status, ManagerAdvanceSelectionStatus.INVALID_STATE)
        self.assertIsNone(rejected.candidate)


if __name__ == "__main__":
    unittest.main()
