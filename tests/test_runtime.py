from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.cli import main
from origin_forge.config import load_config
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.service import VerificationRequired
from origin_forge.state import FlowStatus, GoalStatus, InvalidTransition, RunStatus, TaskStatus


class RuntimeFacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("runtime-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_initialize_creates_and_loads_project_config(self) -> None:
        config_path = self.root / ".origin-forge" / "config.toml"
        self.assertTrue(config_path.exists())
        config = load_config(self.root)
        self.assertEqual(config.version, 4)
        self.assertEqual(config.policy_profile, "local-default")
        self.assertEqual(config.max_strategy_retries, 2)
        self.assertEqual(config.max_verification_failures, 3)
        self.assertEqual(config.approved_build_commands, ())
        self.assertEqual(config.approved_test_commands, ())
        self.assertEqual(config.lsp_servers, ())

    def test_parent_task_must_belong_to_same_flow(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow_a = self.runtime.create_flow(goal)
        flow_b = self.runtime.create_flow(goal)
        parent = self.runtime.create_task(flow_a, "parent")
        with self.assertRaises(RuntimeInvariantError):
            self.runtime.create_task(flow_b, "child", parent_task_id=parent)

    def test_parent_cannot_succeed_with_incomplete_child(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        parent = self.runtime.create_task(flow, "parent")
        child = self.runtime.create_task(flow, "child", parent_task_id=parent)

        parent_rev = self.runtime.transition_task(
            parent, TaskStatus.READY, expected_revision=0
        )
        parent_rev = self.runtime.transition_task(
            parent, TaskStatus.RUNNING, expected_revision=parent_rev
        )
        self.runtime.store.record_verification(
            target_type="TASK",
            target_id=parent,
            verification_type="test",
            verifier="runtime-test",
            status="PASS",
        )

        with self.assertRaises(RuntimeInvariantError):
            self.runtime.transition_task(
                parent, TaskStatus.SUCCEEDED, expected_revision=parent_rev
            )

        self.runtime.transition_task(child, TaskStatus.CANCELLED, expected_revision=0)
        self.runtime.transition_task(
            parent, TaskStatus.SUCCEEDED, expected_revision=parent_rev
        )

    def test_flow_cannot_succeed_with_active_task(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "work")
        flow_rev = self.runtime.transition_flow(
            flow, FlowStatus.RUNNING, expected_revision=0
        )

        with self.assertRaises(RuntimeInvariantError):
            self.runtime.transition_flow(
                flow, FlowStatus.SUCCEEDED, expected_revision=flow_rev
            )

        self.runtime.transition_task(task, TaskStatus.CANCELLED, expected_revision=0)
        self.runtime.transition_flow(
            flow, FlowStatus.SUCCEEDED, expected_revision=flow_rev
        )

    def test_goal_success_requires_completed_flow_and_goal_verification(self) -> None:
        goal = self.runtime.create_goal("goal")
        goal_rev = self.runtime.transition_goal(
            goal, GoalStatus.ACTIVE, expected_revision=0
        )
        flow = self.runtime.create_flow(goal)
        flow_rev = self.runtime.transition_flow(
            flow, FlowStatus.RUNNING, expected_revision=0
        )
        self.runtime.transition_flow(
            flow, FlowStatus.SUCCEEDED, expected_revision=flow_rev
        )

        with self.assertRaises(VerificationRequired):
            self.runtime.transition_goal(
                goal, GoalStatus.SUCCEEDED, expected_revision=goal_rev
            )

        self.runtime.record_verification(
            "GOAL",
            goal,
            verification_type="acceptance",
            verifier="runtime-test",
            status="PASS",
        )
        self.runtime.transition_goal(
            goal, GoalStatus.SUCCEEDED, expected_revision=goal_rev
        )
        self.assertEqual(
            self.runtime.get_goal(goal)["status"], GoalStatus.SUCCEEDED.value
        )

    def test_only_one_active_run_per_task_and_assignment_clears(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "work")
        rev = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=rev)

        run_id = self.runtime.start_run(task, role="EXECUTOR")
        self.assertEqual(self.runtime.get_task(task)["assigned_run_id"], run_id)
        with self.assertRaises(InvalidTransition):
            self.runtime.start_run(task, role="EXECUTOR")

        self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
        self.assertIsNone(self.runtime.get_task(task)["assigned_run_id"])

    def test_runtime_lists_and_records_verification(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "work")
        verification_id = self.runtime.record_verification(
            "TASK",
            task,
            verification_type="unit",
            verifier="runtime-test",
            status="PASS",
        )
        self.assertEqual(len(self.runtime.list_goals()), 1)
        self.assertEqual(len(self.runtime.list_flows(goal)), 1)
        self.assertEqual(len(self.runtime.list_tasks(flow)), 1)
        verifications = self.runtime.list_verifications("TASK", task)
        self.assertEqual(verifications[0]["id"], verification_id)

    def test_cli_returns_structured_not_found_error(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "show",
                    "GOAL-not-real",
                ]
            )
        self.assertEqual(code, 3)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"], "NOT_FOUND")

    def test_cli_can_create_and_show_goal(self) -> None:
        with redirect_stdout(StringIO()):
            code = main(
                ["--project-root", str(self.root), "init", "--name", "runtime-test"]
            )
        self.assertEqual(code, 0)

        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "create",
                    "Create a test feature",
                    "--success",
                    "tests pass",
                ]
            )
        self.assertEqual(code, 0)
        created = json.loads(output.getvalue())
        self.assertEqual(created["objective"], "Create a test feature")

        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "show",
                    created["id"],
                ]
            )
        self.assertEqual(code, 0)
        shown = json.loads(output.getvalue())
        self.assertEqual(shown["id"], created["id"])


if __name__ == "__main__":
    unittest.main()
