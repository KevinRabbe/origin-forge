from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge import __version__
from origin_forge.cli import build_parser
from origin_forge.code_adoption import CodeAdoptionError, VerifiedCodeAdopter
from origin_forge.context_preview import build_context_preview
from origin_forge.doctor import inspect_project
from origin_forge.pixelorama_source import (
    PixeloramaSourceImportError,
    import_pixelorama_source,
    inspect_pixelorama_source,
    replace_pixelorama_source,
)
from origin_forge.plan import inspect_goal_plan
from origin_forge.production_trace import inspect_task_production_trace
from origin_forge.review import inspect_task_review, record_task_review_decision
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.task_dependencies import add_task_dependency


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
        plan = parser.parse_args(["plan", "inspect", "GOAL-EXAMPLE"])
        adopt = parser.parse_args(["adopt", "TASK-EXAMPLE", "--revision", "2"])
        trace = parser.parse_args(["production", "trace", "TASK-EXAMPLE"])
        source_import = parser.parse_args(["production", "source", "import", "assets/player.pxo"])
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
        self.assertEqual(plan.plan_command, "inspect")
        self.assertEqual(plan.goal_id, "GOAL-EXAMPLE")
        self.assertEqual(adopt.task_id, "TASK-EXAMPLE")
        self.assertEqual(adopt.revision, 2)
        self.assertEqual(trace.production_command, "trace")
        self.assertEqual(trace.task_id, "TASK-EXAMPLE")
        self.assertEqual(source_import.source_command, "import")
        self.assertEqual(source_import.path, "assets/player.pxo")
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

    def test_plan_projection_is_read_only_and_exposes_dependency_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("plan-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            first = runtime.create_task(flow_id, "implement movement")
            second = runtime.create_task(flow_id, "add movement tests")
            add_task_dependency(runtime.store, second, first)
            before = runtime.status()
            result = inspect_goal_plan(runtime, goal_id)
            after = runtime.status()
            self.assertEqual(result["goal"]["id"], goal_id)
            self.assertEqual(result["summary"]["flow_count"], 1)
            self.assertEqual(result["summary"]["task_count"], 2)
            flow_view = result["flows"][0]
            self.assertEqual(flow_view["dependency_graph"]["topological_task_ids"], [first, second])
            task_views = {item["task"]["id"]: item for item in flow_view["tasks"]}
            self.assertEqual(task_views[first]["next_action"], "ACTIVATE")
            self.assertEqual(task_views[second]["next_action"], "WAIT_FOR_DEPENDENCIES")
            self.assertEqual(result["summary"]["next_action"], "ACTIVATE")
            self.assertEqual(before["tasks"], after["tasks"])
            self.assertEqual(before["runs"], after["runs"])

    def test_production_trace_is_read_only_and_correlates_task_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("trace-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement movement")
            before = runtime.status()
            result = inspect_task_production_trace(runtime, task_id)
            after = runtime.status()
            self.assertEqual(result["goal"]["id"], goal_id)
            self.assertEqual(result["flow"]["id"], flow_id)
            self.assertEqual(result["task"]["id"], task_id)
            self.assertEqual(result["dispatch"]["claims"], [])
            self.assertEqual(result["dispatch"]["executions"], [])
            self.assertEqual(
                set(result["dispatch"]["output_bindings"]),
                {
                    "pixelorama_dispatch_output_bindings",
                    "blender_dispatch_output_bindings",
                    "image_dispatch_output_bindings",
                    "audio_dispatch_output_bindings",
                    "runtime_dispatch_output_bindings",
                    "playtest_dispatch_output_bindings",
                },
            )
            self.assertEqual(result["next_action"], "ADVANCE")
            self.assertEqual(before["tasks"], after["tasks"])
            self.assertEqual(before["runs"], after["runs"])

    def test_pixelorama_source_import_is_explicit_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("pixelorama-source-test")
            source = root / "assets" / "player.pxo"
            source.parent.mkdir()
            source.write_bytes(b"pixelorama-source")
            result = import_pixelorama_source(runtime, "assets/player.pxo")
            self.assertTrue(result.artifact_id.startswith("ART-"))
            self.assertTrue(result.verification_id.startswith("VER"))
            self.assertEqual(result.relative_path, "assets/player.pxo")
            inspected = inspect_pixelorama_source(runtime, result.artifact_id)
            self.assertEqual(inspected.byte_count, len(b"pixelorama-source"))
            self.assertIn(result.verification_id, inspected.verification_ids)
            self.assertTrue(inspected.to_dict()["read_only"])
            repeated = import_pixelorama_source(runtime, "assets/player.pxo")
            self.assertEqual(repeated, result)
            replacement = root / "assets" / "player-v2.pxo"
            replacement.write_bytes(b"pixelorama-source-v2")
            revised = replace_pixelorama_source(
                runtime, result.artifact_id, "assets/player-v2.pxo"
            )
            self.assertNotEqual(revised.artifact_id, result.artifact_id)
            self.assertEqual(
                inspect_pixelorama_source(runtime, revised.artifact_id).artifact[
                    "parent_artifact_id"
                ],
                result.artifact_id,
            )
            with self.assertRaisesRegex(PixeloramaSourceImportError, r"\.pxo"):
                import_pixelorama_source(runtime, "assets/player.png")

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

    def test_review_projection_does_not_expose_adoption_before_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("review-adoption-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement movement")
            with self.assertRaisesRegex(ValueError, "SUCCEEDED Task"):
                record_task_review_decision(runtime, task_id, "accept", rationale="ready")
            # A queued Task remains reviewable, but the projection must not
            # claim adoption eligibility until a current accepted result exists.
            self.assertEqual(inspect_task_review(runtime, task_id)["next_action"], "WAIT_FOR_READINESS")

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

    def test_code_adoption_requires_human_acceptance_and_verified_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(Path(directory))
            runtime.initialize("code-adoption-test")
            goal_id = runtime.create_goal("build a game")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "implement movement")
            with self.assertRaisesRegex(CodeAdoptionError, "SUCCEEDED Task"):
                VerifiedCodeAdopter(runtime).adopt_new(task_id, expected_revision=0)

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
