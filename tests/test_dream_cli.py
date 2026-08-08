from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.dream_cli import build_parser, main
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class DreamCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-cli-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _completed_failed_run(self) -> str:
        goal = self.runtime.create_goal("Goal")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Completed failed work")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        run = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(run, RunStatus.FAILED, failure_reason="known evidence")
        task_row = self.runtime.get_task(task)
        self.runtime.transition_task(
            task,
            TaskStatus.FAILED,
            expected_revision=int(task_row["revision"]),
        )
        return run

    def _call(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_cli_surface_has_durable_run_but_no_promotion_model_or_mutation_command(self) -> None:
        parser = build_parser()
        subparsers = [
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        ]
        self.assertEqual(len(subparsers), 1)
        commands = set(subparsers[0].choices)
        self.assertIn("status", commands)
        self.assertIn("plan", commands)
        self.assertIn("run", commands)
        self.assertIn("active-memory", commands)
        for forbidden in (
            "approve",
            "promote",
            "apply",
            "merge",
            "model-run",
            "run-model",
            "generate",
            "skill-update",
            "policy-update",
            "generation-create",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_is_non_generative_and_reports_only_dream_runs(self) -> None:
        ordinary = self._completed_failed_run()
        before_runs = len(self.runtime.list_runs())
        code, payload = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(payload["manifests"], 0)
        self.assertEqual(payload["candidates"], 0)
        self.assertEqual(payload["audits"], 0)
        self.assertEqual(payload["memory_entries"], 0)
        self.assertEqual(payload["memory_generations"], 0)
        self.assertEqual(payload["dream_runs"], [])
        self.assertFalse(payload["generative_model_cli_enabled"])
        self.assertFalse(payload["automatic_memory_generation_enabled"])
        self.assertEqual(len(self.runtime.list_runs()), before_runs)
        self.assertIn(ordinary, [item["id"] for item in self.runtime.list_runs()])

    def test_plan_completed_run_persists_manifest_without_generation_or_model(self) -> None:
        run = self._completed_failed_run()
        code, payload = self._call("plan", "--run", run)
        self.assertEqual(code, 0)
        self.assertTrue(payload["manifest_id"].startswith("DREAMIN-"))
        self.assertTrue(payload["manifest_hash"].startswith("sha256:"))
        self.assertEqual(payload["active_memory_entry_count"], 0)
        self.assertEqual(payload["candidate_ids"], [])
        self.assertEqual(payload["audit_ids"], [])
        self.assertFalse(payload["memory_generation_created"])
        self.assertFalse(payload["model_invoked"])

        code, listed = self._call("manifest-list")
        self.assertEqual(code, 0)
        self.assertEqual(listed["manifests"], [payload["manifest_id"]])

        code, shown = self._call("manifest-show", payload["manifest_id"])
        self.assertEqual(code, 0)
        self.assertEqual(shown["manifest_id"], payload["manifest_id"])
        self.assertEqual(shown["content_hash"], payload["manifest_hash"])

        code, generations = self._call("generation-list")
        self.assertEqual(code, 0)
        self.assertEqual(generations["generations"], [])

    def test_run_completed_evidence_creates_closed_durable_dream_cycle_only(self) -> None:
        evidence_run = self._completed_failed_run()
        code, payload = self._call("run", "--run", evidence_run)
        self.assertEqual(code, 0)
        self.assertTrue(payload["goal_id"].startswith("GOAL-"))
        self.assertTrue(payload["flow_id"].startswith("FLOW-"))
        self.assertTrue(payload["task_id"].startswith("TASK-"))
        self.assertTrue(payload["run_id"].startswith("RUN-"))
        self.assertTrue(payload["verification_id"].startswith("VERIFY-"))
        self.assertTrue(payload["manifest_id"].startswith("DREAMIN-"))
        self.assertFalse(payload["model_invoked"])
        self.assertFalse(payload["memory_generation_created"])
        self.assertEqual(self.runtime.get_run(payload["run_id"])["status"], RunStatus.SUCCEEDED.value)

        code, status = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(status["manifests"], 1)
        self.assertEqual(len(status["dream_runs"]), 1)
        self.assertEqual(status["dream_runs"][0]["run_id"], payload["run_id"])
        self.assertEqual(status["dream_runs"][0]["role"], "DREAM_CYCLE")
        self.assertEqual(status["dream_runs"][0]["status"], RunStatus.SUCCEEDED.value)
        self.assertIsNone(status["dream_runs"][0]["model_profile"])
        self.assertFalse(status["generative_model_cli_enabled"])
        self.assertFalse(status["automatic_memory_generation_enabled"])

        code, generations = self._call("generation-list")
        self.assertEqual(code, 0)
        self.assertEqual(generations["generations"], [])

    def test_plan_active_run_returns_structured_failure_and_persists_nothing(self) -> None:
        goal = self.runtime.create_goal("Active")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Active task")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        run = self.runtime.start_run(task, role="EXECUTOR")

        code, payload = self._call("plan", "--run", run)
        self.assertEqual(code, 2)
        self.assertIn("RUN is still active", payload["detail"])
        _, listed = self._call("manifest-list")
        self.assertEqual(listed["manifests"], [])

    def test_run_active_evidence_returns_structured_failure_and_closes_dream_run(self) -> None:
        goal = self.runtime.create_goal("Active")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Active task")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        run = self.runtime.start_run(task, role="EXECUTOR")

        code, payload = self._call("run", "--run", run)
        self.assertEqual(code, 2)
        self.assertIn("RUN is still active", payload["detail"])
        _, status = self._call("status")
        self.assertEqual(len(status["dream_runs"]), 1)
        self.assertEqual(status["dream_runs"][0]["role"], "DREAM_CYCLE")
        self.assertEqual(status["dream_runs"][0]["status"], RunStatus.FAILED.value)
        _, listed = self._call("manifest-list")
        self.assertEqual(listed["manifests"], [])

    def test_invalid_budget_is_structured_failure(self) -> None:
        run = self._completed_failed_run()
        code, payload = self._call(
            "plan",
            "--run",
            run,
            "--max-runs",
            "0",
        )
        self.assertEqual(code, 2)
        self.assertIn("Dream budget", payload["detail"])

    def test_unknown_object_is_structured_not_found(self) -> None:
        code, payload = self._call("candidate-show", "DREAM-not-real")
        self.assertEqual(code, 2)
        # Invalid IDs fail before filesystem lookup, which is safer than probing arbitrary paths.
        self.assertIn("invalid Dream candidate ID", payload["detail"])

    def test_empty_catalogs_are_read_only_and_deterministic(self) -> None:
        for command, field in (
            ("manifest-list", "manifests"),
            ("candidate-list", "candidates"),
            ("audit-list", "audits"),
            ("memory-list", "memory_entries"),
            ("generation-list", "generations"),
        ):
            code, payload = self._call(command)
            self.assertEqual(code, 0)
            self.assertEqual(payload[field], [])


if __name__ == "__main__":
    unittest.main()
