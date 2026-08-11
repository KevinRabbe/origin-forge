from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class RuntimeReadLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("runtime-read-limit-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _records(self) -> tuple[str, str, str]:
        first_goal = self.runtime.create_goal("first")
        second_goal = self.runtime.create_goal("second")
        first_flow = self.runtime.create_flow(first_goal)
        second_flow = self.runtime.create_flow(first_goal)
        first_task = self.runtime.create_task(first_flow, "first task")
        second_task = self.runtime.create_task(first_flow, "second task")
        for task in (first_task, second_task):
            revision = self.runtime.transition_task(
                task,
                TaskStatus.READY,
                expected_revision=0,
            )
            self.runtime.transition_task(
                task,
                TaskStatus.RUNNING,
                expected_revision=revision,
            )
        first_run = self.runtime.start_run(first_task, role="OBSERVER")
        second_run = self.runtime.start_run(second_task, role="OBSERVER")
        self.runtime.record_verification(
            "TASK",
            first_task,
            verification_type="one",
            verifier="read-limit-test",
            status="PASS",
            run_id=first_run,
        )
        self.runtime.record_verification(
            "TASK",
            first_task,
            verification_type="two",
            verifier="read-limit-test",
            status="PASS",
            run_id=first_run,
        )
        self.assertNotEqual(second_goal, first_goal)
        self.assertNotEqual(second_flow, first_flow)
        self.assertNotEqual(second_run, first_run)
        return first_goal, first_flow, first_task

    def test_optional_limits_bound_rows_without_changing_default_reads(self) -> None:
        _, _, task = self._records()
        self.assertEqual(len(self.runtime.list_goals()), 2)
        self.assertEqual(len(self.runtime.list_goals(limit=1)), 1)
        self.assertEqual(len(self.runtime.list_flows()), 2)
        self.assertEqual(len(self.runtime.list_flows(limit=1)), 1)
        self.assertEqual(len(self.runtime.list_tasks()), 2)
        self.assertEqual(len(self.runtime.list_tasks(limit=1)), 1)
        self.assertEqual(len(self.runtime.list_runs()), 2)
        self.assertEqual(len(self.runtime.list_runs(limit=1)), 1)
        self.assertEqual(len(self.runtime.list_verifications("TASK", task)), 2)
        self.assertEqual(
            len(self.runtime.list_verifications("TASK", task, limit=1)),
            1,
        )

    def test_count_reads_are_exact_and_filter_aware(self) -> None:
        goal, flow, _ = self._records()
        self.assertEqual(self.runtime.count_goals(), 2)
        self.assertEqual(self.runtime.count_flows(), 2)
        self.assertEqual(self.runtime.count_flows(goal), 2)
        self.assertEqual(self.runtime.count_tasks(), 2)
        self.assertEqual(self.runtime.count_tasks(flow), 2)
        self.assertEqual(self.runtime.count_runs(), 2)
        self.assertEqual(self.runtime.count_task_verifications(), 2)

    def test_invalid_limits_fail_before_query_materialization(self) -> None:
        for value in (0, -1, 100_001, True, 1.5, "1"):
            with self.assertRaises(ValueError):
                self.runtime.list_goals(limit=value)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                self.runtime.list_flows(limit=value)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                self.runtime.list_tasks(limit=value)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                self.runtime.list_runs(limit=value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
