from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge import __version__
from origin_forge.cli import build_parser
from origin_forge.context_preview import build_context_preview
from origin_forge.doctor import inspect_project
from origin_forge.review import inspect_task_review
from origin_forge.runtime import OriginForgeRuntime


class DoctorTests(unittest.TestCase):
    def test_cli_exposes_read_only_doctor_and_run_inspect(self) -> None:
        parser = build_parser()
        doctor = parser.parse_args(["doctor", "--strict"])
        inspect = parser.parse_args(["run", "inspect", "RUN-EXAMPLE"])
        advance = parser.parse_args(["advance"])
        context = parser.parse_args(["context", "preview", "TASK-EXAMPLE", "--file", "game.py"])
        attempt = parser.parse_args(["attempt", "TASK-EXAMPLE", "--auto-context"])
        review = parser.parse_args(["review", "inspect", "TASK-EXAMPLE"])
        graph_inspects = [
            parser.parse_args([kind, "inspect", "EXAMPLE"])
            for kind in ("goal", "flow", "task")
        ]
        self.assertTrue(doctor.strict)
        self.assertEqual(inspect.run_command, "inspect")
        self.assertEqual(inspect.run_id, "RUN-EXAMPLE")
        self.assertEqual(advance.command, "advance")
        self.assertEqual(context.context_command, "preview")
        self.assertEqual(context.files, ["game.py"])
        self.assertEqual(attempt.command, "attempt")
        self.assertTrue(attempt.auto_context)
        self.assertEqual(review.review_command, "inspect")
        self.assertEqual(
            [item.goal_command if item.command == "goal" else item.flow_command if item.command == "flow" else item.task_command for item in graph_inspects],
            ["inspect", "inspect", "inspect"],
        )

    def test_package_version_matches_v05_release(self) -> None:
        self.assertEqual(__version__, "0.5.0")

    def test_uninitialized_project_is_diagnosed_without_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = inspect_project(root)
            self.assertFalse(result["ready"])
            self.assertFalse((root / ".origin-forge").exists())

    def test_initialized_project_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            OriginForgeRuntime(root).initialize("doctor-test")
            result = inspect_project(root)
            self.assertTrue(result["ready"])
            self.assertEqual(result["schema_version"], result["expected_schema_version"])

    def test_context_preview_is_read_only_and_hashes_selected_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("context-preview-test")
            goal_id = runtime.create_goal("build a game mechanic")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement mechanic")
            source = root / "game.py"
            source.write_text("class Mechanic: pass\n", encoding="utf-8")
            before = runtime.status()
            result = build_context_preview(runtime, task_id, selected_paths=["game.py"])
            after = runtime.status()
            self.assertEqual(result["task"]["id"], task_id)
            self.assertEqual(result["context"]["paths"], ["game.py"])
            self.assertEqual(result["context"]["files"][0]["path"], "game.py")
            self.assertEqual(before["tasks"], after["tasks"])
            self.assertEqual(before["runs"], after["runs"])

    def test_review_projection_is_read_only_for_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("review-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement movement")
            result = inspect_task_review(runtime, task_id)
            self.assertEqual(result["task"]["id"], task_id)
            self.assertEqual(result["next_action"], "WAIT_FOR_READINESS")
            self.assertEqual(result["runs"], [])
            self.assertEqual(result["workspaces"], [])
            self.assertEqual(result["artifacts"], [])
