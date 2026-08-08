from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_cycle import DreamCycleService
from origin_forge.dream_store import DreamStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, GoalStatus, RunStatus, TaskStatus


class DreamCycleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-cycle-service-test")
        self.store = DreamStore(self.runtime)

        goal = self.runtime.create_goal("Completed evidence")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Produce terminal evidence")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        self.evidence_run = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(
            self.evidence_run,
            RunStatus.FAILED,
            failure_reason="known completed evidence",
        )
        task_row = self.runtime.get_task(task)
        self.runtime.transition_task(
            task,
            TaskStatus.FAILED,
            expected_revision=int(task_row["revision"]),
        )
        self.service = DreamCycleService(self.runtime, self.store)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_successful_cycle_has_durable_closed_lifecycle_and_no_generation(self) -> None:
        before_generations = self.store.list_generation_ids()
        result = self.service.run((self.evidence_run,))

        self.assertEqual(self.runtime.get_goal(result.goal_id)["status"], GoalStatus.SUCCEEDED.value)
        self.assertEqual(self.runtime.get_flow(result.flow_id)["status"], FlowStatus.SUCCEEDED.value)
        self.assertEqual(self.runtime.get_task(result.task_id)["status"], TaskStatus.SUCCEEDED.value)
        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(run["role"], DreamCycleService.RUN_ROLE)
        self.assertEqual(self.store.load_manifest(result.plan.manifest.manifest_id), result.plan.manifest)
        self.assertEqual(self.store.list_generation_ids(), before_generations)

        run_verifications = self.runtime.list_verifications("RUN", result.run_id)
        task_verifications = self.runtime.list_verifications("TASK", result.task_id)
        goal_verifications = self.runtime.list_verifications("GOAL", result.goal_id)
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(len(task_verifications), 1)
        self.assertEqual(len(goal_verifications), 1)
        self.assertEqual(run_verifications[0]["id"], result.verification_id)
        self.assertEqual(run_verifications[0]["verification_type"], "dream-cycle-plan")
        self.assertEqual(run_verifications[0]["status"], "PASS")
        self.assertEqual(goal_verifications[0]["verification_type"], "dream-cycle-plan")
        self.assertEqual(goal_verifications[0]["status"], "PASS")
        evidence = json.loads(run_verifications[0]["evidence_json"])
        metrics = json.loads(run_verifications[0]["metrics_json"])
        goal_evidence = json.loads(goal_verifications[0]["evidence_json"])
        self.assertEqual(evidence["manifest_id"], result.plan.manifest.manifest_id)
        self.assertFalse(evidence["model_invoked"])
        self.assertFalse(evidence["memory_generation_created"])
        self.assertFalse(evidence["canonical_project_state_changed_by_dream_output"])
        self.assertEqual(goal_evidence["flow_id"], result.flow_id)
        self.assertEqual(goal_evidence["task_id"], result.task_id)
        self.assertEqual(goal_evidence["run_id"], result.run_id)
        self.assertEqual(goal_evidence["run_verification_id"], result.verification_id)
        self.assertEqual(goal_evidence["manifest_hash"], result.plan.manifest.content_hash)
        self.assertEqual(goal_evidence["plan_hash"], result.plan.content_hash)
        self.assertFalse(goal_evidence["model_invoked"])
        self.assertFalse(goal_evidence["memory_generation_created"])
        self.assertFalse(goal_evidence["canonical_project_state_changed_by_dream_output"])
        self.assertEqual(metrics["candidate_count"], len(result.plan.candidates))
        self.assertEqual(metrics["audit_count"], len(result.plan.audits))
        self.assertFalse(result.to_dict()["model_invoked"])
        self.assertFalse(result.to_dict()["memory_generation_created"])

    def test_planning_failure_closes_own_lifecycle_as_failed_or_blocked(self) -> None:
        goal = self.runtime.create_goal("Still active evidence")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Active evidence")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        active_run = self.runtime.start_run(task, role="EXECUTOR")
        before_manifests = self.store.list_manifest_ids()

        with self.assertRaisesRegex(RuntimeError, "RUN is still active"):
            self.service.run((active_run,))

        dream_runs = [
            row for row in self.runtime.list_runs() if row["role"] == DreamCycleService.RUN_ROLE
        ]
        self.assertEqual(len(dream_runs), 1)
        dream_run = dream_runs[0]
        self.assertEqual(dream_run["status"], RunStatus.FAILED.value)
        dream_task = self.runtime.get_task(dream_run["task_id"])
        self.assertEqual(dream_task["status"], TaskStatus.FAILED.value)
        dream_flow = self.runtime.get_flow(dream_task["flow_id"])
        self.assertEqual(dream_flow["status"], FlowStatus.FAILED.value)
        dream_goal = self.runtime.get_goal(dream_flow["goal_id"])
        self.assertEqual(dream_goal["status"], GoalStatus.BLOCKED.value)
        verifications = self.runtime.list_verifications("RUN", dream_run["id"])
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["status"], "FAIL")
        self.assertEqual(verifications[0]["verification_type"], "dream-cycle-plan")
        self.assertEqual(self.runtime.list_verifications("GOAL", dream_goal["id"]), [])
        self.assertEqual(self.store.list_manifest_ids(), before_manifests)

    def test_cycle_service_exposes_no_model_generation_promotion_or_project_write_surface(self) -> None:
        for forbidden in (
            "run_model",
            "build_generation",
            "promote",
            "apply",
            "write_source",
            "change_policy",
            "merge",
        ):
            self.assertFalse(hasattr(self.service, forbidden))


if __name__ == "__main__":
    unittest.main()
