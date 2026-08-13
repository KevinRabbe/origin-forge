from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import origin_forge.production_preparation_recovery_once as module
from origin_forge.production_preparation_recovery import PreparationRecoveryState
from origin_forge.production_preparation_recovery_once import PreparationRecoveryOnceStatus
from origin_forge.runtime import OriginForgeRuntime


class Phase41PreplannerRecoveryTests(unittest.TestCase):
    def test_claimed_uses_atomic_activation_once(self) -> None:
        runtime = OriginForgeRuntime("/tmp/origin-forge-phase41e-claimed")
        projection = Mock()
        projection.state = PreparationRecoveryState.RESUMABLE_CLAIMED
        projection.receipt_revision = 0
        projection.task_id = "TASK-test"
        projection.detail = None
        receipt = Mock()
        receipt.task_id = "TASK-test"
        with (
            patch.object(module, "inspect_preparation_recovery_readonly", return_value=projection),
            patch.object(module, "activate_and_checkpoint_preparation", return_value=receipt) as activate,
            patch.object(module, "recover_and_checkpoint_preparation_route") as route,
            patch.object(module, "resume_routed_preparation_planner_once") as resume,
        ):
            result = module.recover_preparation_once(runtime, "PREP-test")
        self.assertEqual(result.status, PreparationRecoveryOnceStatus.RECOVERED_ACTIVATED)
        activate.assert_called_once_with(runtime, "PREP-test", 0)
        route.assert_not_called()
        resume.assert_not_called()

    def test_activated_uses_route_recovery_once(self) -> None:
        runtime = OriginForgeRuntime("/tmp/origin-forge-phase41e-activated")
        projection = Mock()
        projection.state = PreparationRecoveryState.RESUMABLE_ACTIVATED
        projection.receipt_revision = 1
        projection.task_id = "TASK-test"
        projection.detail = None
        receipt = Mock()
        receipt.task_id = "TASK-test"
        with (
            patch.object(module, "inspect_preparation_recovery_readonly", return_value=projection),
            patch.object(module, "recover_and_checkpoint_preparation_route", return_value=receipt) as route,
            patch.object(module, "activate_and_checkpoint_preparation") as activate,
            patch.object(module, "resume_routed_preparation_planner_once") as resume,
        ):
            result = module.recover_preparation_once(runtime, "PREP-test")
        self.assertEqual(result.status, PreparationRecoveryOnceStatus.RECOVERED_ROUTED)
        route.assert_called_once_with(runtime, "PREP-test", 1)
        activate.assert_not_called()
        resume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
