from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_blender_dispatch_output_currentness as currentness_module
from origin_forge.production_blender_dispatch_output_binding import BLENDER_EXECUTION_OWNER_ID
from origin_forge.production_blender_dispatch_output_currentness import (
    BlenderDispatchOutputCurrentnessStatus,
    inspect_blender_dispatch_output_currentness_readonly,
)
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_execution_read import DispatchExecutionCurrentnessStatus


class BlenderDispatchOutputCurrentnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = object()
        self.execution_id = "DISPEXEC-test"
        self.execution = SimpleNamespace(
            execution_owner_id=BLENDER_EXECUTION_OWNER_ID,
            task_id="TASK-test",
            status=DispatchExecutionStatus.RETURNED,
        )
        self.binding = SimpleNamespace(output_artifact_id="ART-test")
        self.currentness = SimpleNamespace(
            status=DispatchExecutionCurrentnessStatus.RETURNED,
            detail=None,
        )

    def _patch_authority(self):
        return (
            patch.object(currentness_module, "read_dispatch_execution", return_value=self.execution),
            patch.object(
                currentness_module,
                "read_blender_dispatch_output_binding",
                return_value=self.binding,
            ),
            patch.object(
                currentness_module,
                "inspect_dispatch_execution_currentness_readonly",
                return_value=self.currentness,
            ),
            patch.object(currentness_module, "materialize_bound_blender_result"),
        )

    def test_returned_current_bound_output_is_adoption_eligible(self) -> None:
        read_execution, read_binding, inspect_execution, materialize = self._patch_authority()
        with read_execution, read_binding, inspect_execution, materialize as materialize_mock:
            result = inspect_blender_dispatch_output_currentness_readonly(
                self.runtime, self.execution_id
            )

        self.assertEqual(result.status, BlenderDispatchOutputCurrentnessStatus.ELIGIBLE)
        self.assertTrue(result.adoption_eligible)
        self.assertFalse(result.production_task_verified)
        self.assertFalse(result.semantic_geometry_verified)
        materialize_mock.assert_called_once_with(self.runtime, self.binding)
        self.assertEqual(
            result.to_dict(),
            {
                "execution_id": self.execution_id,
                "task_id": "TASK-test",
                "output_artifact_id": "ART-test",
                "status": "ELIGIBLE",
                "production_task_verified": False,
                "semantic_geometry_verified": False,
                "adoption_eligible": True,
                "detail": None,
            },
        )

    def test_started_execution_is_recovery_only_and_never_materialized_for_adoption(self) -> None:
        self.execution.status = DispatchExecutionStatus.STARTED
        self.currentness.status = DispatchExecutionCurrentnessStatus.CURRENT_STARTED
        read_execution, read_binding, inspect_execution, materialize = self._patch_authority()
        with read_execution, read_binding, inspect_execution, materialize as materialize_mock:
            result = inspect_blender_dispatch_output_currentness_readonly(
                self.runtime, self.execution_id
            )

        self.assertEqual(
            result.status,
            BlenderDispatchOutputCurrentnessStatus.EXECUTION_NOT_RETURNED,
        )
        self.assertFalse(result.adoption_eligible)
        materialize_mock.assert_not_called()

    def test_wrong_execution_owner_is_stale_and_fails_before_currentness(self) -> None:
        self.execution.execution_owner_id = "originforge.execution.other@1"
        read_execution, read_binding, inspect_execution, materialize = self._patch_authority()
        with (
            read_execution,
            read_binding,
            inspect_execution as inspect_mock,
            materialize as materialize_mock,
        ):
            result = inspect_blender_dispatch_output_currentness_readonly(
                self.runtime, self.execution_id
            )

        self.assertEqual(result.status, BlenderDispatchOutputCurrentnessStatus.STALE_EXECUTION)
        self.assertFalse(result.adoption_eligible)
        inspect_mock.assert_not_called()
        materialize_mock.assert_not_called()

    def test_returned_execution_requires_exact_generic_terminal_currentness(self) -> None:
        self.currentness.status = DispatchExecutionCurrentnessStatus.STALE_CLAIM
        self.currentness.detail = "claim terminal relation drifted"
        read_execution, read_binding, inspect_execution, materialize = self._patch_authority()
        with read_execution, read_binding, inspect_execution, materialize as materialize_mock:
            result = inspect_blender_dispatch_output_currentness_readonly(
                self.runtime, self.execution_id
            )

        self.assertEqual(result.status, BlenderDispatchOutputCurrentnessStatus.STALE_EXECUTION)
        self.assertEqual(result.detail, "claim terminal relation drifted")
        self.assertFalse(result.adoption_eligible)
        materialize_mock.assert_not_called()

    def test_invalid_bound_glb_evidence_is_ineligible(self) -> None:
        read_execution, read_binding, inspect_execution, materialize = self._patch_authority()
        with (
            read_execution,
            read_binding,
            inspect_execution,
            materialize as materialize_mock,
        ):
            materialize_mock.side_effect = RuntimeError(
                "bound Blender GLB output failed structural validation"
            )
            result = inspect_blender_dispatch_output_currentness_readonly(
                self.runtime, self.execution_id
            )

        self.assertEqual(result.status, BlenderDispatchOutputCurrentnessStatus.INVALID_EVIDENCE)
        self.assertFalse(result.adoption_eligible)

    def test_task_lifecycle_drift_is_reported_without_mutation(self) -> None:
        read_execution, read_binding, inspect_execution, materialize = self._patch_authority()
        with (
            read_execution,
            read_binding,
            inspect_execution,
            materialize as materialize_mock,
        ):
            materialize_mock.side_effect = RuntimeError(
                "bound Blender Run/Task lifecycle is not exact"
            )
            result = inspect_blender_dispatch_output_currentness_readonly(
                self.runtime, self.execution_id
            )

        self.assertEqual(result.status, BlenderDispatchOutputCurrentnessStatus.TASK_NOT_RUNNING)
        self.assertFalse(result.adoption_eligible)

    def test_missing_binding_is_invalid_evidence(self) -> None:
        with (
            patch.object(
                currentness_module,
                "read_dispatch_execution",
                side_effect=RuntimeError("missing execution"),
            ),
            patch.object(currentness_module, "read_blender_dispatch_output_binding") as read_binding,
            patch.object(currentness_module, "materialize_bound_blender_result") as materialize,
        ):
            result = inspect_blender_dispatch_output_currentness_readonly(
                self.runtime, self.execution_id
            )

        self.assertEqual(result.status, BlenderDispatchOutputCurrentnessStatus.INVALID_EVIDENCE)
        self.assertFalse(result.adoption_eligible)
        read_binding.assert_not_called()
        materialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
