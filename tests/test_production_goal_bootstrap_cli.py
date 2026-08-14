from __future__ import annotations

import io
import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from origin_forge import cli
from origin_forge.ids import IdKind, new_id
from origin_forge.production_goal_bootstrap_operator import (
    GoalBootstrapDecision,
    GoalBootstrapOperatorBlocked,
    GoalBootstrapOperatorError,
)
from origin_forge.runtime import OriginForgeRuntime


class _TypedResult:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = dict(payload)

    def to_dict(self) -> dict[str, object]:
        return dict(self._payload)


class GoalBootstrapCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name).resolve()
        self.goal_id = new_id(IdKind.GOAL)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _assert_runtime_goal_call(self, mocked) -> None:
        mocked.assert_called_once()
        runtime_arg, goal_arg = mocked.call_args.args
        self.assertIsInstance(runtime_arg, OriginForgeRuntime)
        self.assertEqual(runtime_arg.project_root, self.root)
        self.assertEqual(goal_arg, self.goal_id)

    def test_parser_exposes_only_status_start_and_recover_with_goal_id(self) -> None:
        parser = cli.build_parser()
        for command in ("status", "start", "recover"):
            with self.subTest(command=command):
                args = parser.parse_args(
                    [
                        "--project-root",
                        str(self.root),
                        "goal",
                        "bootstrap",
                        command,
                        self.goal_id,
                    ]
                )
                self.assertEqual(args.command, "goal")
                self.assertEqual(args.goal_command, "bootstrap")
                self.assertEqual(args.goal_bootstrap_command, command)
                self.assertEqual(args.goal_id, self.goal_id)
                self.assertEqual(args.project_root, self.root)

    def test_parser_rejects_bootstrap_repeat_or_extra_selector(self) -> None:
        parser = cli.build_parser()
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as repeated:
                parser.parse_args(
                    [
                        "goal",
                        "bootstrap",
                        "start",
                        self.goal_id,
                        "--repeat",
                    ]
                )
        self.assertEqual(repeated.exception.code, 2)

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as selected:
                parser.parse_args(
                    [
                        "goal",
                        "bootstrap",
                        "recover",
                        self.goal_id,
                        "--task-id",
                        "TASK-forbidden",
                    ]
                )
        self.assertEqual(selected.exception.code, 2)

    def test_status_delegates_once_without_mutation_or_manager(self) -> None:
        expected = {
            "decision": "INTERRUPTED",
            "goal_id": self.goal_id,
            "authority": "phase45e-goal-bootstrap-readonly-status",
        }
        stdout = io.StringIO()
        with (
            patch(
                "origin_forge.cli.inspect_goal_bootstrap_status_readonly",
                return_value=_TypedResult(expected),
            ) as status,
            patch(
                "origin_forge.cli.bootstrap_goal_once",
                side_effect=AssertionError("status must not bootstrap"),
            ) as start,
            patch(
                "origin_forge.cli.recover_goal_once",
                side_effect=AssertionError("status must not recover"),
            ) as recover,
            patch(
                "origin_forge.cli.advance_production_manager_bounded",
                side_effect=AssertionError("status must not invoke Manager"),
            ) as manager,
            redirect_stdout(stdout),
        ):
            code = cli._main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "bootstrap",
                    "status",
                    self.goal_id,
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), expected)
        self._assert_runtime_goal_call(status)
        start.assert_not_called()
        recover.assert_not_called()
        manager.assert_not_called()

    def test_start_delegates_once_without_status_recovery_or_manager(self) -> None:
        expected = {
            "action": "BOOTSTRAP",
            "status": "READY",
            "authority": "phase45e-goal-bootstrap-operator",
        }
        stdout = io.StringIO()
        with (
            patch(
                "origin_forge.cli.bootstrap_goal_once",
                return_value=_TypedResult(expected),
            ) as start,
            patch(
                "origin_forge.cli.inspect_goal_bootstrap_status_readonly",
                side_effect=AssertionError("start must not preflight status"),
            ) as status,
            patch(
                "origin_forge.cli.recover_goal_once",
                side_effect=AssertionError("start must not auto-recover"),
            ) as recover,
            patch(
                "origin_forge.cli.advance_production_manager_bounded",
                side_effect=AssertionError("start must not invoke Manager"),
            ) as manager,
            redirect_stdout(stdout),
        ):
            code = cli._main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "bootstrap",
                    "start",
                    self.goal_id,
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), expected)
        self._assert_runtime_goal_call(start)
        status.assert_not_called()
        recover.assert_not_called()
        manager.assert_not_called()

    def test_recover_delegates_once_without_status_start_or_manager(self) -> None:
        expected = {
            "action": "RECOVER",
            "status": "READY",
            "authority": "phase45e-goal-bootstrap-operator",
        }
        stdout = io.StringIO()
        with (
            patch(
                "origin_forge.cli.recover_goal_once",
                return_value=_TypedResult(expected),
            ) as recover,
            patch(
                "origin_forge.cli.inspect_goal_bootstrap_status_readonly",
                side_effect=AssertionError("recover must not preflight status"),
            ) as status,
            patch(
                "origin_forge.cli.bootstrap_goal_once",
                side_effect=AssertionError("recover must not auto-start"),
            ) as start,
            patch(
                "origin_forge.cli.advance_production_manager_bounded",
                side_effect=AssertionError("recover must not invoke Manager"),
            ) as manager,
            redirect_stdout(stdout),
        ):
            code = cli._main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "bootstrap",
                    "recover",
                    self.goal_id,
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), expected)
        self._assert_runtime_goal_call(recover)
        status.assert_not_called()
        start.assert_not_called()
        manager.assert_not_called()

    def test_blocked_operator_error_is_bounded_json_with_exact_decision(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "origin_forge.cli.bootstrap_goal_once",
                side_effect=GoalBootstrapOperatorBlocked(
                    GoalBootstrapDecision.ACTIVE_PRE_PLANNER,
                    "explicit recovery required",
                ),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "bootstrap",
                    "start",
                    self.goal_id,
                ]
            )

        self.assertEqual(code, 4)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {
                "error": "GOAL_BOOTSTRAP_BLOCKED",
                "decision": "ACTIVE_PRE_PLANNER",
                "message": "explicit recovery required",
            },
        )
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_operator_error_is_bounded_json_without_traceback(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "origin_forge.cli.inspect_goal_bootstrap_status_readonly",
                side_effect=GoalBootstrapOperatorError("bootstrap state unavailable"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "bootstrap",
                    "status",
                    self.goal_id,
                ]
            )

        self.assertEqual(code, 5)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {
                "error": "GOAL_BOOTSTRAP_ERROR",
                "message": "bootstrap state unavailable",
            },
        )
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_source_boundary_uses_only_public_goal_bootstrap_operator_surface(self) -> None:
        source = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertEqual(
            source.count("inspect_goal_bootstrap_status_readonly(runtime, args.goal_id)"),
            1,
        )
        self.assertEqual(source.count("bootstrap_goal_once(runtime, args.goal_id)"), 1)
        self.assertEqual(source.count("recover_goal_once(runtime, args.goal_id)"), 1)
        self.assertNotIn("production_goal_bootstrap_authority", source)
        self.assertNotIn("production_goal_bootstrap_planner", source)
        self.assertNotIn("production_goal_bootstrap_finalize", source)
        self.assertNotIn("acquire_current_goal_bootstrap", source)
        self.assertNotIn("advance_goal_bootstrap_planner", source)
        self.assertNotIn("finalize_goal_bootstrap", source)

    def test_packaging_remains_exactly_three_existing_entrypoints(self) -> None:
        repository_root = Path(cli.__file__).resolve().parents[2]
        pyproject = tomllib.loads(
            repository_root.joinpath("pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(pyproject["project"]["scripts"]),
            {"origin-forge", "origin-forge-attempt", "origin-forge-cockpit"},
        )


if __name__ == "__main__":
    unittest.main()
