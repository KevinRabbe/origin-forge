from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.cli import main
from origin_forge.config import load_config
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.state import FlowStatus, TaskStatus


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
        self.assertEqual(config.version, 1)
        self.assertEqual(config.policy_profile, "local-default")
        self.assertEqual(config.max_strategy_retries, 2)
        self.assertEqual(config.max_verification_failures, 3)

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
