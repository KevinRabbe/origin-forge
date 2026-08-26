from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge import __version__
from origin_forge.cli import build_parser
from origin_forge.context_preview import build_context_preview
from origin_forge.doctor import inspect_project
from origin_forge.review import inspect_task_review, record_task_review_decision
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
        review_reject = parser.parse_args(
            ["review", "reject", "TASK-EXAMPLE", "--rationale", "needs revision"]
        )
        review_accept = parser.parse_args(
            ["review", "accept", "TASK-EXAMPLE", "--rationale", "looks good", "--revision", "3"]
        )
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
        self.assertEqual(review_reject.review_command, "reject")
        self.assertEqual(review_accept.review_command, "accept")
        self.assertEqual(review_accept.revision, 3)
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
            backup_checks = [item for item in result["checks"] if item["name"] == "database_backups"]
            self.assertEqual(backup_checks[0]["status"], "SKIP")
            self.assertEqual(result["schema_version"], result["expected_schema_version"])

    def test_status_exposes_configured_external_tools_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("status-tools-test")
            configured = (root / "tools" / "ffmpeg.exe").resolve()
            config = root / ".origin-forge" / "config.toml"
            config_text = config.read_text(encoding="utf-8").replace(
                "[tools]\n# Optional external capability executables. Values must be absolute paths.",
                f'[tools]\nffmpeg = "{configured.as_posix()}"',
            )
            config.write_text(config_text, encoding="utf-8")
            before = runtime.status()
            after = runtime.status()
            self.assertEqual(
                before["config"]["external_tools"], {"ffmpeg": str(configured)}
            )
            self.assertEqual(before, after)

    def test_doctor_reports_optional_tools_without_blocking_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            OriginForgeRuntime(root).initialize("doctor-tools-test")
            result = inspect_project(root)
            tool_checks = {
                item["name"]: item for item in result["checks"] if item["name"].startswith("tool:")
            }
            self.assertEqual(tool_checks["tool:ffmpeg"]["status"], "SKIP")
            self.assertTrue(result["ready"])

    def test_doctor_rejects_missing_configured_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            OriginForgeRuntime(root).initialize("doctor-configured-tool-test")
            config = root / ".origin-forge" / "config.toml"
            missing_tool = (root / "missing" / "ffmpeg.exe").resolve()
            config_text = config.read_text(encoding="utf-8").replace(
                "[tools]\n# Optional external capability executables. Values must be absolute paths.",
                f'[tools]\nffmpeg = "{missing_tool.as_posix()}"',
            )
            config.write_text(config_text, encoding="utf-8")
            result = inspect_project(root)
            checks = {item["name"]: item for item in result["checks"]}
            self.assertEqual(checks["tool:ffmpeg"]["status"], "FAIL")
            self.assertFalse(result["ready"])

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
            self.assertTrue(result["context"]["snapshot_id"].startswith("sha256:"))
            self.assertIn("max_file_bytes", result["context"]["limits"])
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
            self.assertEqual(result["decisions"], [])

    def test_review_decision_is_human_lineage_without_task_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("review-decision-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement movement")
            before = runtime.get_task(task_id)
            decision_id = record_task_review_decision(
                runtime, task_id, "refine", rationale="add acceleration behavior"
            )
            after = runtime.get_task(task_id)
            self.assertEqual(before, after)
            self.assertEqual(runtime.get_flow(flow_id)["goal_id"], goal_id)
            self.assertEqual(runtime.get_task(task_id)["id"], task_id)
            self.assertTrue(decision_id.startswith("DEC-"))

    def test_review_accept_requires_verified_succeeded_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("review-accept-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement movement")
            with self.assertRaisesRegex(ValueError, "SUCCEEDED Task"):
                record_task_review_decision(
                    runtime, task_id, "accept", rationale="looks good"
                )

    def test_review_decision_rejects_stale_task_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("review-revision-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement movement")
            with self.assertRaisesRegex(ValueError, "revision is stale"):
                record_task_review_decision(
                    runtime,
                    task_id,
                    "refine",
                    rationale="revise movement",
                    expected_revision=99,
                )
