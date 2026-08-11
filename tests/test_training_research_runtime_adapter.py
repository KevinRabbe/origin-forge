from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus
from origin_forge.training_research_models import TrainingEligibilityAudit
from origin_forge.training_research_runtime_adapter import (
    TrainingTrajectoryAdapterError,
    build_verified_runtime_trajectory,
)


POLICY_HASH = "sha256:" + "f" * 64


class TrainingResearchRuntimeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("training-runtime-adapter-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _running_task(self) -> tuple[str, str]:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(
            flow,
            "SECRET-TASK-OBJECTIVE",
            acceptance_criteria=("SECRET-ACCEPTANCE",),
            constraints=("SECRET-CONSTRAINT",),
        )
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        return flow, task

    def _successful_state(self, *, bound_verification: bool = True) -> tuple[str, str]:
        _, task = self._running_task()
        run_id = self.runtime.start_run(task, role="EXECUTOR", model_profile="coding-small")
        verification_run = run_id if bound_verification else None
        self.runtime.record_verification(
            "TASK",
            task,
            verification_type="unit",
            verifier="training-adapter-test",
            status="PASS",
            evidence={"secret": "SECRET-VERIFICATION-EVIDENCE"},
            metrics={"secret_metric": "SECRET-METRIC"},
            run_id=verification_run,
        )
        self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
        revision = int(self.runtime.get_task(task)["revision"])
        self.runtime.transition_task(task, TaskStatus.SUCCEEDED, expected_revision=revision)
        return task, run_id

    def test_successful_adapter_exports_only_redacted_structural_projection(self) -> None:
        task, run_id = self._successful_state()
        trajectory = build_verified_runtime_trajectory(self.runtime, run_id=run_id)
        self.assertEqual(trajectory.task_id, task)
        self.assertEqual(trajectory.run_id, run_id)
        self.assertEqual(trajectory.objective, "verified terminal runtime trajectory")
        serialized = json.dumps(trajectory.to_dict(), sort_keys=True)
        for forbidden in (
            "SECRET-TASK-OBJECTIVE",
            "SECRET-ACCEPTANCE",
            "SECRET-CONSTRAINT",
            "SECRET-VERIFICATION-EVIDENCE",
            "SECRET-METRIC",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(trajectory.example["redaction"]["task_objective_disclosed"])
        self.assertFalse(trajectory.example["redaction"]["verification_payload_disclosed"])
        self.assertEqual(trajectory.example["target"]["task_status"], "SUCCEEDED")
        self.assertEqual(trajectory.example["target"]["run_status"], "SUCCEEDED")
        self.assertEqual(trajectory.example["target"]["verification_types"], ["unit"])

        audit = TrainingEligibilityAudit.create(
            trajectory=trajectory,
            policy_id="verified-runtime-redacted-v1",
            policy_version="1",
            policy_fingerprint=POLICY_HASH,
        )
        self.assertTrue(audit.eligible)

    def test_same_task_retries_share_leakage_group(self) -> None:
        _, task = self._running_task()
        failed = self.runtime.start_run(task, role="EXECUTOR", model_profile="coding-small")
        self.runtime.finish_run(failed, RunStatus.FAILED, failure_reason="SECRET-FAILURE")
        successful = self.runtime.start_run(task, role="EXECUTOR", model_profile="coding-small")
        self.runtime.record_verification(
            "TASK",
            task,
            verification_type="unit",
            verifier="training-adapter-test",
            status="PASS",
            run_id=successful,
        )
        self.runtime.finish_run(successful, RunStatus.SUCCEEDED)
        revision = int(self.runtime.get_task(task)["revision"])
        self.runtime.transition_task(task, TaskStatus.SUCCEEDED, expected_revision=revision)
        successful_trajectory = build_verified_runtime_trajectory(
            self.runtime,
            run_id=successful,
        )
        # Failed-attempt export is deliberately not enabled in v1, but the group
        # policy is task-based so any future attempt adapter must share this group.
        self.assertIn(task, json.dumps(successful_trajectory.to_dict()))
        with self.assertRaisesRegex(TrainingTrajectoryAdapterError, "SUCCEEDED Run"):
            build_verified_runtime_trajectory(self.runtime, run_id=failed)

    def test_unbound_pass_verification_is_not_sufficient(self) -> None:
        _, run_id = self._successful_state(bound_verification=False)
        with self.assertRaisesRegex(TrainingTrajectoryAdapterError, "bound to the exact Run"):
            build_verified_runtime_trajectory(self.runtime, run_id=run_id)

    def test_running_or_failed_run_cannot_be_exported(self) -> None:
        _, task = self._running_task()
        run_id = self.runtime.start_run(task, role="EXECUTOR")
        with self.assertRaisesRegex(TrainingTrajectoryAdapterError, "SUCCEEDED Run"):
            build_verified_runtime_trajectory(self.runtime, run_id=run_id)
        self.runtime.finish_run(run_id, RunStatus.FAILED, failure_reason="failure")
        with self.assertRaisesRegex(TrainingTrajectoryAdapterError, "SUCCEEDED Run"):
            build_verified_runtime_trajectory(self.runtime, run_id=run_id)

    def test_succeeded_run_with_nonterminal_task_is_rejected(self) -> None:
        _, task = self._running_task()
        run_id = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
        with self.assertRaisesRegex(TrainingTrajectoryAdapterError, "terminal SUCCEEDED Task"):
            build_verified_runtime_trajectory(self.runtime, run_id=run_id)

    def test_task_pass_from_different_run_does_not_authorize_export(self) -> None:
        _, task = self._running_task()
        first = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(first, RunStatus.FAILED, failure_reason="first")
        second = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.record_verification(
            "TASK",
            task,
            verification_type="unit",
            verifier="training-adapter-test",
            status="PASS",
            run_id=second,
        )
        self.runtime.finish_run(second, RunStatus.SUCCEEDED)
        revision = int(self.runtime.get_task(task)["revision"])
        self.runtime.transition_task(task, TaskStatus.SUCCEEDED, expected_revision=revision)
        with self.assertRaisesRegex(TrainingTrajectoryAdapterError, "SUCCEEDED Run"):
            build_verified_runtime_trajectory(self.runtime, run_id=first)
        trajectory = build_verified_runtime_trajectory(self.runtime, run_id=second)
        self.assertEqual(trajectory.run_id, second)


if __name__ == "__main__":
    unittest.main()
