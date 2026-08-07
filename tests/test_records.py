from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.state import TaskStatus


class ProvenanceRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("records-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.goal = self.runtime.create_goal("goal")
        self.flow = self.runtime.create_flow(self.goal)
        self.task = self.runtime.create_task(self.flow, "task")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_decision_change_artifact_lineage_and_hash(self) -> None:
        decision = self.lineage.create_decision(
            title="Use deterministic state",
            decision="SQLite owns durable state",
            goal_id=self.goal,
            task_id=self.task,
            rationale="The model must not own project truth",
        )
        change = self.lineage.create_change(
            self.task,
            summary="Record durable state decision",
            change_type="documentation",
            decision_id=decision,
        )

        artifact_path = self.root / "artifact.txt"
        artifact_path.write_text("origin forge", encoding="utf-8")
        artifact = self.lineage.create_artifact(
            artifact_type="text",
            path_or_uri="artifact.txt",
            change_id=change,
            tool_versions=["test-tool@1"],
        )
        row = self.lineage.get_artifact(artifact)
        expected = hashlib.sha256(b"origin forge").hexdigest()
        self.assertEqual(row["path_or_uri"], "artifact.txt")
        self.assertEqual(row["content_hash"], f"sha256:{expected}")
        self.assertEqual(row["change_id"], change)

        events = self.runtime.store.event_history("ARTIFACT", artifact)
        self.assertEqual(events[-1]["event_type"], "ARTIFACT_CREATED")

        verification = self.lineage.record_artifact_verification(
            artifact,
            verification_type="hash-check",
            verifier="records-test",
            status="PASS",
        )
        self.assertEqual(
            self.lineage.list_artifact_verifications(artifact)[0]["id"],
            verification,
        )

    def test_decision_goal_must_match_task_goal(self) -> None:
        other_goal = self.runtime.create_goal("other")
        with self.assertRaises(RuntimeInvariantError):
            self.lineage.create_decision(
                title="bad",
                decision="bad",
                goal_id=other_goal,
                task_id=self.task,
            )

    def test_change_run_must_match_task(self) -> None:
        other_task = self.runtime.create_task(self.flow, "other")
        revision = self.runtime.transition_task(
            other_task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            other_task, TaskStatus.RUNNING, expected_revision=revision
        )
        run_id = self.runtime.start_run(other_task, role="EXECUTOR")
        with self.assertRaises(RuntimeInvariantError):
            self.lineage.create_change(
                self.task,
                summary="wrong run",
                change_type="code",
                run_id=run_id,
            )

    def test_local_artifact_cannot_escape_project_root(self) -> None:
        outside = self.root.parent / "outside-origin-forge-test.txt"
        try:
            outside.write_text("outside", encoding="utf-8")
            with self.assertRaises(RuntimeInvariantError):
                self.lineage.create_artifact(
                    artifact_type="text",
                    path_or_uri=str(outside),
                )
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
