from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_interface_snapshot as snapshot_module
from origin_forge.production_interface_snapshot import (
    ProductionInterfaceSnapshotError,
    build_production_interface_snapshot,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus


class ProductionInterfaceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-snapshot-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _successful_task(self, objective: str = "Build safe cockpit") -> tuple[str, str, str]:
        goal = self.runtime.create_goal(objective)
        flow = self.runtime.create_flow(goal, controller="manager")
        task = self.runtime.create_task(flow, objective, priority=3)
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        run_id = self.runtime.start_run(task, role="EXECUTOR", model_profile="coding-small")
        self.runtime.record_verification(
            "TASK",
            task,
            verification_type="unit",
            verifier="snapshot-test",
            status="PASS",
            evidence={"secret": "DO-NOT-RENDER"},
            metrics={"private_metric": 123},
            run_id=run_id,
        )
        self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
        return goal, flow, task

    def test_snapshot_is_deterministic_and_read_only(self) -> None:
        self._successful_task()
        before = self.runtime.status()
        first = build_production_interface_snapshot(self.runtime)
        second = build_production_interface_snapshot(self.runtime)
        after = self.runtime.status()
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.production_trace), 1)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(before, after)
        self.assertTrue(first.to_dict()["authority"]["read_only"])
        self.assertFalse(first.to_dict()["authority"]["task_mutation"])

    def test_snapshot_excludes_verification_payloads_and_runtime_commands(self) -> None:
        self._successful_task()
        payload = json.dumps(build_production_interface_snapshot(self.runtime).to_dict())
        self.assertNotIn("DO-NOT-RENDER", payload)
        self.assertNotIn("private_metric", payload)
        self.assertNotIn("approved_build_commands", payload)
        self.assertNotIn("approved_test_commands", payload)
        verification = build_production_interface_snapshot(self.runtime).task_verifications[0]
        self.assertEqual(verification["verification_type"], "unit")
        self.assertEqual(verification["status"], "PASS")
        self.assertNotIn("evidence_json", verification)
        self.assertNotIn("metrics_json", verification)

    def test_section_limits_are_explicit(self) -> None:
        self.runtime.create_goal("first")
        self.runtime.create_goal("second")
        snapshot = build_production_interface_snapshot(self.runtime, max_goals=1)
        self.assertEqual(len(snapshot.goals), 1)
        self.assertEqual(snapshot.total_counts["goals"], 2)
        self.assertTrue(snapshot.truncated["goals"])

    def test_untrusted_text_is_bounded_not_interpreted(self) -> None:
        hostile = '<script>alert("x")</script>' + ("z" * 5000)
        self.runtime.create_goal(hostile)
        snapshot = build_production_interface_snapshot(self.runtime)
        goal = snapshot.goals[0]
        self.assertTrue(goal["objective_truncated"])
        self.assertEqual(len(goal["objective"]), 4096)
        self.assertIn("<script>", goal["objective"])

    def test_invalid_limits_fail_closed(self) -> None:
        with self.assertRaises(ProductionInterfaceSnapshotError):
            build_production_interface_snapshot(self.runtime, max_goals=0)
        with self.assertRaises(ProductionInterfaceSnapshotError):
            build_production_interface_snapshot(self.runtime, max_runs=10001)

    def test_projector_has_no_raw_store_or_sql_surface(self) -> None:
        source = inspect.getsource(snapshot_module)
        for forbidden in (
            ".store",
            "sqlite3",
            ".execute(",
            "subprocess",
            "os.system",
            "ModelAdapter",
            "private_key",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
