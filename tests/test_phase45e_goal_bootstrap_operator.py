from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from origin_forge import cli_entry
from origin_forge.production_goal_bootstrap import bootstrap_goal, goal_bootstrap_status
from origin_forge.production_goal_bootstrap_authority import acquire_current_goal_bootstrap
from origin_forge.production_goal_bootstrap_models import GoalBootstrapStatus
from origin_forge.production_goal_bootstrap_store import fail_goal_bootstrap_before_planner
from origin_forge.runtime import OriginForgeRuntime


class Phase45EGoalBootstrapOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase45e-operator")
        self.goal_id = self.runtime.create_goal("bootstrap one governed code goal")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _bootstrap_count(self) -> int:
        with self.runtime.store.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM goal_bootstraps").fetchone()[0])

    def test_status_without_attempt_is_strictly_read_only(self) -> None:
        before = self._bootstrap_count()
        view = goal_bootstrap_status(self.runtime, self.goal_id)
        after = self._bootstrap_count()

        self.assertFalse(view.exists)
        self.assertEqual(view.attempt_count, 0)
        self.assertIsNone(view.receipt)
        self.assertEqual(before, 0)
        self.assertEqual(after, 0)
        self.assertTrue(view.to_dict()["read_only"])

    def test_terminal_attempt_is_surfaced_without_hidden_retry(self) -> None:
        receipt = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        terminal = fail_goal_bootstrap_before_planner(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            receipt.stage,
            "operator-visible terminal fixture",
        )
        with patch(
            "origin_forge.production_goal_bootstrap.acquire_current_goal_bootstrap"
        ) as acquire, patch(
            "origin_forge.production_goal_bootstrap.prepare_goal_bootstrap_input"
        ) as prepare:
            result = bootstrap_goal(self.runtime, self.goal_id)

        self.assertEqual(result.receipt.bootstrap_id, terminal.bootstrap_id)
        self.assertEqual(result.receipt.status, GoalBootstrapStatus.FAILED_PRE_PLANNER)
        self.assertTrue(result.terminal)
        self.assertFalse(result.created)
        self.assertFalse(result.advanced)
        acquire.assert_not_called()
        prepare.assert_not_called()
        self.assertEqual(self._bootstrap_count(), 1)

    def test_fresh_attempt_uses_only_fixed_phase45_composition(self) -> None:
        active = Mock()
        active.bootstrap_id = "GOALBOOT-fixed"
        active.status = GoalBootstrapStatus.ACTIVE
        ready = Mock()
        ready.status = GoalBootstrapStatus.READY
        ready.to_dict.return_value = {"bootstrap_id": "GOALBOOT-fixed", "status": "READY"}

        with patch(
            "origin_forge.production_goal_bootstrap._goal_attempts",
            return_value=(0, "0" * 64, ()),
        ), patch(
            "origin_forge.production_goal_bootstrap.acquire_current_goal_bootstrap",
            return_value=active,
        ) as acquire, patch(
            "origin_forge.production_goal_bootstrap.prepare_goal_bootstrap_input"
        ) as prepare, patch(
            "origin_forge.production_goal_bootstrap.advance_goal_bootstrap_planner"
        ) as planner, patch(
            "origin_forge.production_goal_bootstrap.finalize_goal_bootstrap",
            return_value=SimpleNamespace(receipt=ready),
        ) as finalize:
            result = bootstrap_goal(self.runtime, self.goal_id)

        self.assertTrue(result.created)
        self.assertTrue(result.advanced)
        self.assertTrue(result.ready)
        self.assertFalse(result.to_dict()["manager_advanced"])
        acquire.assert_called_once_with(self.runtime, self.goal_id)
        prepare.assert_called_once_with(self.runtime, active.bootstrap_id)
        planner.assert_called_once_with(self.runtime, active.bootstrap_id)
        finalize.assert_called_once_with(self.runtime, active.bootstrap_id)

    def test_existing_ready_attempt_is_idempotent(self) -> None:
        ready = Mock()
        ready.status = GoalBootstrapStatus.READY
        with patch(
            "origin_forge.production_goal_bootstrap._goal_attempts",
            return_value=(0, "0" * 64, (ready,)),
        ), patch(
            "origin_forge.production_goal_bootstrap.prepare_goal_bootstrap_input"
        ) as prepare:
            result = bootstrap_goal(self.runtime, self.goal_id)

        self.assertIs(result.receipt, ready)
        self.assertFalse(result.created)
        self.assertFalse(result.advanced)
        prepare.assert_not_called()

    def test_cli_status_emits_json_and_does_not_create_attempt(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_entry.main(
                ["--project-root", str(self.root), "goal", "bootstrap-status", self.goal_id]
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["goal_id"], self.goal_id)
        self.assertFalse(payload["exists"])
        self.assertTrue(payload["read_only"])
        self.assertEqual(self._bootstrap_count(), 0)

    def test_cli_bootstrap_accepts_only_goal_id_and_reports_fixed_result(self) -> None:
        result = Mock()
        result.ready = True
        result.terminal = False
        result.to_dict.return_value = {
            "ready": True,
            "terminal": False,
            "manager_advanced": False,
        }
        with patch("origin_forge.cli_entry.bootstrap_goal", return_value=result) as invoke:
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_entry.main(
                    ["--project-root", str(self.root), "goal", "bootstrap", self.goal_id]
                )

        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())["manager_advanced"])
        invoke.assert_called_once()
        runtime_arg, goal_arg = invoke.call_args.args
        self.assertIsInstance(runtime_arg, OriginForgeRuntime)
        self.assertEqual(goal_arg, self.goal_id)

    def test_non_bootstrap_manager_cli_is_delegated_unchanged(self) -> None:
        with patch("origin_forge.cli_entry.legacy_cli.main", return_value=23) as legacy:
            code = cli_entry.main(["manager", "status"])
        self.assertEqual(code, 23)
        legacy.assert_called_once_with(["manager", "status"])


if __name__ == "__main__":
    unittest.main()
