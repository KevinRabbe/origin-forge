from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.simulation_cli import build_parser, main
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class SimulationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("simulation-cli-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str) -> tuple[int, object]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def _simulation_run(self) -> str:
        goal = self.runtime.create_goal("Simulate")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Run simulator")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        run_id = self.runtime.start_run(task, role="SIMULATOR")
        self.runtime.record_verification(
            "RUN",
            run_id,
            verification_type="simulation-structure",
            verifier="test",
            status="PASS",
            evidence={"production_task_verified": False},
            run_id=run_id,
        )
        self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
        return run_id

    def test_surface_is_strictly_read_only(self) -> None:
        parser = build_parser()
        subparsers = next(action for action in parser._actions if action.dest == "command")
        commands = set(subparsers.choices)
        self.assertEqual(commands, {"status", "sessions", "run-show", "artifact-show"})
        for forbidden in (
            "simulate",
            "run",
            "execute",
            "spec-set",
            "tune",
            "balance",
            "verify-task",
            "adopt",
            "sign",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_is_deterministic_and_non_mutating(self) -> None:
        before = self.runtime.status()
        code, value = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "OK")
        self.assertEqual(value["simulation_run_count"], 0)
        self.assertEqual(value["artifact_counts"], {})
        self.assertFalse(value["simulation_execution_enabled"])
        self.assertFalse(value["specification_mutation_enabled"])
        self.assertFalse(value["task_mutation_enabled"])
        self.assertFalse(value["semantic_balance_authority_enabled"])
        self.assertFalse(value["automatic_tuning_enabled"])
        self.assertFalse(value["canonical_asset_adoption_enabled"])
        self.assertFalse(value["provenance_signing_enabled"])
        self.assertFalse(value["merge_release_enabled"])
        self.assertEqual(self.runtime.status(), before)

    def test_sessions_and_run_show_are_limited_to_simulator_role(self) -> None:
        run_id = self._simulation_run()
        code, listing = self._call("sessions")
        self.assertEqual(code, 0)
        self.assertEqual([run["id"] for run in listing["runs"]], [run_id])
        self.assertIsNotNone(listing["runs"][0]["ended_at"])
        code, shown = self._call("run-show", run_id)
        self.assertEqual(code, 0)
        self.assertEqual(shown["run"]["id"], run_id)
        self.assertEqual(
            shown["verifications"][0]["verification_type"], "simulation-structure"
        )

    def test_artifact_show_is_limited_to_phase25_types(self) -> None:
        lineage = OriginForgeLineage(self.runtime)
        path = self.root / "summary.json"
        path.write_text("{}", encoding="utf-8")
        artifact_id = lineage.create_artifact(
            artifact_type="SIMULATION_SUMMARY",
            path_or_uri=str(path),
            status="DERIVED",
        )
        code, value = self._call("artifact-show", artifact_id)
        self.assertEqual(code, 0)
        self.assertEqual(value["artifact"]["id"], artifact_id)

        other = self.root / "other.bin"
        other.write_bytes(b"other")
        other_id = lineage.create_artifact(
            artifact_type="OTHER",
            path_or_uri=str(other),
            status="PRODUCED",
        )
        code, value = self._call("artifact-show", other_id)
        self.assertEqual(code, 2)
        self.assertIn("Phase-25 simulation Artifact", value["detail"])

    def test_invalid_ids_return_structured_errors(self) -> None:
        code, value = self._call("run-show", "not-a-run")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")
        code, value = self._call("artifact-show", "not-an-artifact")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
