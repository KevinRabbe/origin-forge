from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, validate_id
from origin_forge.service import OriginForgeStore, StaleRevision, VerificationRequired
from origin_forge.state import FlowStatus, InvalidTransition, TaskStatus


class OriginForgeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = OriginForgeStore(self.root / ".origin-forge" / "project.db")
        self.project_id = self.store.initialize_project("test-project", self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _flow_and_task(self) -> tuple[str, str]:
        goal = self.store.create_goal(
            self.project_id,
            "Build a verified thing",
            success_criteria=["task verification passes"],
        )
        flow = self.store.create_flow(goal)
        task = self.store.create_task(flow, "Implement bounded work")
        return flow, task

    def test_ids_are_typed_and_unique(self) -> None:
        goal_a = self.store.create_goal(self.project_id, "A")
        goal_b = self.store.create_goal(self.project_id, "B")
        self.assertNotEqual(goal_a, goal_b)
        self.assertTrue(validate_id(goal_a, IdKind.GOAL))
        self.assertTrue(validate_id(goal_b, IdKind.GOAL))

    def test_initialize_project_is_idempotent(self) -> None:
        again = self.store.initialize_project("different display name", self.root)
        self.assertEqual(self.project_id, again)

    def test_flow_transition_and_event_journal(self) -> None:
        flow, _ = self._flow_and_task()
        revision = self.store.transition_flow(
            flow, FlowStatus.RUNNING, expected_revision=0
        )
        self.assertEqual(revision, 1)
        row = self.store.get_flow(flow)
        self.assertEqual(row["status"], FlowStatus.RUNNING.value)
        self.assertEqual(row["revision"], 1)

        events = self.store.event_history("FLOW", flow)
        self.assertEqual(
            [event["event_type"] for event in events],
            ["FLOW_CREATED", "FLOW_STATUS_CHANGED"],
        )

    def test_stale_revision_is_rejected(self) -> None:
        flow, _ = self._flow_and_task()
        self.store.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        with self.assertRaises(StaleRevision):
            self.store.transition_flow(flow, FlowStatus.BLOCKED, expected_revision=0)

    def test_invalid_terminal_transition_is_rejected(self) -> None:
        flow, _ = self._flow_and_task()
        revision = self.store.transition_flow(
            flow, FlowStatus.RUNNING, expected_revision=0
        )
        revision = self.store.transition_flow(
            flow, FlowStatus.SUCCEEDED, expected_revision=revision
        )
        self.assertEqual(revision, 2)
        with self.assertRaises(InvalidTransition):
            self.store.transition_flow(
                flow, FlowStatus.RUNNING, expected_revision=revision
            )

    def test_task_requires_verification_before_success(self) -> None:
        _, task = self._flow_and_task()
        revision = self.store.transition_task(
            task, TaskStatus.READY, expected_revision=0
        )
        revision = self.store.transition_task(
            task, TaskStatus.RUNNING, expected_revision=revision
        )
        with self.assertRaises(VerificationRequired):
            self.store.transition_task(
                task, TaskStatus.SUCCEEDED, expected_revision=revision
            )

        self.store.record_verification(
            target_type="TASK",
            target_id=task,
            verification_type="unit-test",
            verifier="test-suite",
            status="PASS",
            evidence={"tests": 10},
        )
        self.store.transition_task(
            task, TaskStatus.SUCCEEDED, expected_revision=revision
        )
        self.assertEqual(
            self.store.get_task(task)["status"], TaskStatus.SUCCEEDED.value
        )

    def test_recovery_finds_running_records_and_is_idempotent(self) -> None:
        flow, task = self._flow_and_task()
        self.store.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        revision = self.store.transition_task(
            task, TaskStatus.READY, expected_revision=0
        )
        self.store.transition_task(
            task, TaskStatus.RUNNING, expected_revision=revision
        )

        first = self.store.recovery_findings()
        second = self.store.recovery_findings()
        self.assertEqual(first, second)
        self.assertEqual({finding.aggregate_type for finding in first}, {"FLOW", "TASK"})

    def test_foreign_keys_are_enforced(self) -> None:
        with self.store.session() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO goals(
                           id, project_id, objective, created_at, updated_at
                       ) VALUES ('GOAL-invalid', 'PROJECT-missing', 'x', 'x', 'x')"""
                )

    def test_state_persists_after_reopen(self) -> None:
        flow, _ = self._flow_and_task()
        self.store.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        reopened = OriginForgeStore(self.store.db_path)
        self.assertEqual(
            reopened.get_flow(flow)["status"], FlowStatus.RUNNING.value
        )


if __name__ == "__main__":
    unittest.main()
