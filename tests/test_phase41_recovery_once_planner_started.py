from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import origin_forge.production_preparation_recovery_once as module
from origin_forge.production_preparation_planner_evidence import (
    PlannerEvidenceRecovery,
    PlannerEvidenceRecoveryStatus,
)
from origin_forge.production_preparation_recovery import PreparationRecoveryState
from origin_forge.production_preparation_recovery_once import PreparationRecoveryOnceStatus
from origin_forge.runtime import OriginForgeRuntime


class Phase41PlannerStartedRecoveryTests(unittest.TestCase):
    def test_planner_started_uses_evidence_only(self) -> None:
        runtime = OriginForgeRuntime("/tmp/origin-forge-phase41e-planner-started")
        projection = Mock()
        projection.state = PreparationRecoveryState.PLANNER_EVIDENCE_ONLY
        projection.receipt_revision = 3
        projection.task_id = "TASK-test"
        projection.detail = None
        receipt = Mock()
        receipt.task_id = "TASK-test"
        lower = PlannerEvidenceRecovery(
            PlannerEvidenceRecoveryStatus.UNRESOLVED,
            "PREP-test",
            receipt,
            None,
            "no exact planner evidence",
        )
        with (
            patch.object(module, "inspect_preparation_recovery_readonly", return_value=projection),
            patch.object(module, "recover_planner_evidence", return_value=lower) as evidence,
            patch.object(module, "resume_routed_preparation_planner_once") as resume,
        ):
            result = module.recover_preparation_once(runtime, "PREP-test")
        self.assertEqual(result.status, PreparationRecoveryOnceStatus.PLANNER_RECOVERY_REQUIRED)
        evidence.assert_called_once_with(runtime, "PREP-test")
        resume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
