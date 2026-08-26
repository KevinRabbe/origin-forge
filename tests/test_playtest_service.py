from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from origin_forge.lineage import OriginForgeLineage
from origin_forge.playtest_harness import (
    CooperativePlaytestHarness,
    PlaytestHarnessExecution,
)
from origin_forge.playtest_models import (
    PlaytestAction,
    PlaytestActionKind,
    PlaytestOutcome,
    PlaytestScenario,
    PlaytestTelemetry,
    PlaytestTelemetryEvent,
    PlaytestTelemetryKind,
)
from origin_forge.playtest_service import PlaytestService, PlaytestServiceError
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observation_models import canonical_bytes
from origin_forge.runtime_observer import sha256_file
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


FAKE_HASH = "sha256:" + "d" * 64


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _FakePlaytestBackend:
    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        outcome: PlaytestOutcome = PlaytestOutcome.FAILED,
        reported_workspace: Path | None = None,
        corrupt_stdout_hash: bool = False,
        escaped_stdout: bool = False,
        aliased_stdout: bool = False,
        escaped_scenario: bool = False,
        inconsistent_exit_state: bool = False,
    ):
        self.runtime = runtime
        self.outcome = outcome
        self.reported_workspace = reported_workspace
        self.corrupt_stdout_hash = corrupt_stdout_hash
        self.escaped_stdout = escaped_stdout
        self.aliased_stdout = aliased_stdout
        self.escaped_scenario = escaped_scenario
        self.inconsistent_exit_state = inconsistent_exit_state

    def execute(self, scenario: PlaytestScenario) -> PlaytestHarnessExecution:
        workspace = self.runtime.state_dir / "playtests" / scenario.workspace_id
        for name in ("runtime", "logs"):
            (workspace / name).mkdir(parents=True, exist_ok=True)
        (workspace / "runtime" / "home").mkdir(exist_ok=True)
        (workspace / "runtime" / "tmp").mkdir(exist_ok=True)
        scenario_bytes = canonical_bytes(scenario.to_dict())
        if self.escaped_scenario:
            escaped_request = self.runtime.state_dir / "unrelated-playtest-request"
            escaped_request.mkdir()
            (escaped_request / "scenario.json").write_bytes(scenario_bytes)
            (workspace / "request").symlink_to(escaped_request, target_is_directory=True)
        else:
            (workspace / "request").mkdir()
            (workspace / "request" / "scenario.json").write_bytes(scenario_bytes)

        stdout = b"synthetic player started\n"
        stderr = b"target exited nonzero\n" if self.outcome is PlaytestOutcome.FAILED else b""
        stdout_path = workspace / "logs" / "stdout.log"
        stderr_path = workspace / "logs" / "stderr.log"
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        reported_stdout_path = stdout_path
        if self.escaped_stdout:
            reported_stdout_path = self.runtime.state_dir / "unrelated-playtest-stdout.log"
            reported_stdout_path.write_bytes(stdout)
        elif self.aliased_stdout:
            reported_stdout_path = workspace / "logs" / ".." / "logs" / "stdout.log"

        events = (
            PlaytestTelemetryEvent(
                0, 100, PlaytestTelemetryKind.PROGRESSION, "spawn"
            ),
            PlaytestTelemetryEvent(
                1, 200, PlaytestTelemetryKind.ENCOUNTER_START, "enc-a"
            ),
            PlaytestTelemetryEvent(
                2, 400, PlaytestTelemetryKind.DAMAGE_TAKEN, None, 7
            ),
            PlaytestTelemetryEvent(
                3, 600, PlaytestTelemetryKind.RESOURCE_SHORTAGE, "ammo", 0
            ),
            PlaytestTelemetryEvent(
                4, 800, PlaytestTelemetryKind.PATHFINDING_FAILURE, "bot-a"
            ),
        )
        telemetry = PlaytestTelemetry(
            session_id=scenario.session_id,
            scenario_hash=scenario.content_hash,
            harness_id=scenario.harness_id,
            harness_version=scenario.harness_version,
            harness_hash=scenario.harness_hash,
            target_id=scenario.target_id,
            target_version=scenario.target_version,
            outcome=self.outcome,
            duration_ms=1000,
            events=events,
        )
        timed_out = self.outcome is PlaytestOutcome.TIMEOUT
        exit_code = None if timed_out else (0 if self.outcome is PlaytestOutcome.COMPLETED else 7)
        if self.inconsistent_exit_state:
            timed_out = False
            exit_code = 0
        return PlaytestHarnessExecution(
            scenario=scenario,
            telemetry=telemetry,
            workspace_path=self.reported_workspace or workspace,
            stdout_path=reported_stdout_path,
            stderr_path=stderr_path,
            stdout_hash=("sha256:" + "0" * 64) if self.corrupt_stdout_hash else _hash(stdout),
            stderr_hash=_hash(stderr),
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            process_duration_ms=1010,
            exit_code=exit_code,
            timed_out=timed_out,
        )


class PlaytestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("playtest-service-test")
        goal = self.runtime.create_goal("Playtest game")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "Run synthetic player")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _scenario(self, *, harness_hash: str = FAKE_HASH) -> PlaytestScenario:
        return PlaytestScenario.create(
            harness_id="fixture-harness",
            harness_version="1",
            harness_hash=harness_hash,
            target_id="fixture-game",
            target_version="1",
            allowed_controls=("move-x", "attack"),
            actions=(
                PlaytestAction(0, 0, PlaytestActionKind.SET_AXIS, "move-x", 1000),
                PlaytestAction(1, 100, PlaytestActionKind.PRESS, "attack", None, 50),
            ),
            max_duration_ms=5000,
            max_log_bytes=4096,
            progression_stall_threshold_ms=500,
        )

    @staticmethod
    def _assert_task_observation_only(before, after) -> None:
        if after["status"] != TaskStatus.RUNNING.value:
            raise AssertionError("playtest changed production Task status")
        if after["revision"] != before["revision"]:
            raise AssertionError("playtest changed production Task revision")
        if after["attempt_count"] != before["attempt_count"] + 1:
            raise AssertionError("playtest did not record exactly one Run attempt")
        if after["assigned_run_id"] is not None:
            raise AssertionError("finished playtest left Task assigned")

    def test_failed_game_session_persists_evidence_without_task_authority(self) -> None:
        before = self.runtime.get_task(self.task)
        result = PlaytestService(
            self.runtime,
            _FakePlaytestBackend(self.runtime, outcome=PlaytestOutcome.FAILED),
        ).execute(self.task, self._scenario())

        self.assertEqual(result.outcome, PlaytestOutcome.FAILED.value)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(result.summary.damage_taken, 7)
        self.assertEqual(result.summary.resource_shortages, 1)
        self.assertEqual(result.summary.pathfinding_failures, 1)
        self.assertTrue(result.summary.progression_stall_detected)
        self.assertFalse(result.to_dict()["production_task_verified"])
        self.assertFalse(result.to_dict()["semantic_game_quality_verified"])
        self._assert_task_observation_only(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], PlaytestService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        verification = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(verification), 1)
        self.assertEqual(verification[0]["verification_type"], "playtest-structure")
        evidence = json.loads(verification[0]["evidence_json"])
        self.assertEqual(evidence["outcome"], PlaytestOutcome.FAILED.value)
        self.assertFalse(evidence["production_task_verified"])
        self.assertFalse(evidence["semantic_game_quality_verified"])

        lineage = OriginForgeLineage(self.runtime)
        artifacts = {artifact["id"]: artifact for artifact in lineage.list_artifacts()}
        expected_types = {
            result.scenario_artifact_id: "PLAYTEST_SCENARIO",
            result.telemetry_artifact_id: "PLAYTEST_TELEMETRY",
            result.summary_artifact_id: "PLAYTEST_SUMMARY",
            result.stdout_artifact_id: "PLAYTEST_STDOUT_LOG",
            result.stderr_artifact_id: "PLAYTEST_STDERR_LOG",
        }
        for artifact_id, artifact_type in expected_types.items():
            self.assertEqual(artifacts[artifact_id]["type"], artifact_type)
            lineage.local_artifact_path(artifact_id)

    def test_timeout_is_successful_playtest_evidence_not_task_failure_authority(self) -> None:
        before = self.runtime.get_task(self.task)
        result = PlaytestService(
            self.runtime,
            _FakePlaytestBackend(self.runtime, outcome=PlaytestOutcome.TIMEOUT),
        ).execute(self.task, self._scenario())
        self.assertEqual(result.outcome, PlaytestOutcome.TIMEOUT.value)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertEqual(self.runtime.get_run(result.run_id)["status"], RunStatus.SUCCEEDED.value)
        self._assert_task_observation_only(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_workspace_escape_fails_only_playtest_run(self) -> None:
        before = self.runtime.get_task(self.task)
        with self.assertRaisesRegex(PlaytestServiceError, "outside"):
            PlaytestService(
                self.runtime,
                _FakePlaytestBackend(
                    self.runtime,
                    reported_workspace=self.runtime.state_dir,
                ),
            ).execute(self.task, self._scenario())
        self._assert_task_observation_only(before, self.runtime.get_task(self.task))
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == PlaytestService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_log_path_escape_fails_before_artifact_persistence(self) -> None:
        lineage = OriginForgeLineage(self.runtime)
        self.assertEqual(lineage.list_artifacts(), [])
        with self.assertRaisesRegex(PlaytestServiceError, "exact governed"):
            PlaytestService(
                self.runtime,
                _FakePlaytestBackend(self.runtime, escaped_stdout=True),
            ).execute(self.task, self._scenario())
        self.assertEqual(lineage.list_artifacts(), [])
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == PlaytestService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_log_path_alias_is_rejected_even_when_it_resolves_to_exact_file(self) -> None:
        with self.assertRaisesRegex(PlaytestServiceError, "exact governed"):
            PlaytestService(
                self.runtime,
                _FakePlaytestBackend(self.runtime, aliased_stdout=True),
            ).execute(self.task, self._scenario())
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])

    def test_scenario_parent_symlink_escape_fails_before_artifact_persistence(self) -> None:
        try:
            with self.assertRaisesRegex(PlaytestServiceError, "may not use symlinks"):
                PlaytestService(
                    self.runtime,
                    _FakePlaytestBackend(self.runtime, escaped_scenario=True),
                ).execute(self.task, self._scenario())
        except OSError as exc:
            if getattr(exc, "winerror", None) != 1314:
                raise
            self.skipTest("Windows symlink privilege is unavailable")
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])

    def test_backend_outcome_exit_inconsistency_fails_closed(self) -> None:
        with self.assertRaisesRegex(PlaytestServiceError, "disagrees"):
            PlaytestService(
                self.runtime,
                _FakePlaytestBackend(self.runtime, inconsistent_exit_state=True),
            ).execute(self.task, self._scenario())
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])

    def test_log_hash_drift_fails_closed(self) -> None:
        with self.assertRaisesRegex(PlaytestServiceError, "hash drifted"):
            PlaytestService(
                self.runtime,
                _FakePlaytestBackend(self.runtime, corrupt_stdout_hash=True),
            ).execute(self.task, self._scenario())

    def test_service_exposes_no_production_or_raw_input_authority(self) -> None:
        service = PlaytestService(self.runtime, _FakePlaytestBackend(self.runtime))
        for forbidden in (
            "transition_task",
            "verify_task",
            "complete_task",
            "keyboard",
            "mouse",
            "shell",
            "script",
            "adopt",
            "sign",
            "merge",
            "release",
        ):
            self.assertFalse(hasattr(service, forbidden))

    def test_real_harness_to_durable_lineage_round_trip(self) -> None:
        executable = Path(sys.executable).resolve(strict=True)
        executable_hash = sha256_file(executable)
        script = self.root / "real-playtest-harness.py"
        script.write_text(
            textwrap.dedent(
                """
                import json
                import os
                from pathlib import Path

                scenario = json.loads(Path(os.environ['ORIGIN_FORGE_PLAYTEST_SCENARIO']).read_text())
                telemetry = {
                    'session_id': scenario['session_id'],
                    'scenario_hash': os.environ['ORIGIN_FORGE_PLAYTEST_SCENARIO_HASH'],
                    'harness_id': scenario['harness_id'],
                    'harness_version': scenario['harness_version'],
                    'harness_hash': scenario['harness_hash'],
                    'target_id': scenario['target_id'],
                    'target_version': scenario['target_version'],
                    'outcome': 'COMPLETED',
                    'duration_ms': 900,
                    'events': [
                        {'sequence': 0, 'at_ms': 100, 'kind': 'PROGRESSION', 'subject_id': 'spawn', 'value': None},
                        {'sequence': 1, 'at_ms': 300, 'kind': 'DAMAGE_DEALT', 'subject_id': None, 'value': 11},
                    ],
                }
                Path(os.environ['ORIGIN_FORGE_PLAYTEST_TELEMETRY']).write_text(
                    json.dumps(telemetry, sort_keys=True, separators=(',', ':'))
                )
                print('real-playtest-complete')
                """
            ),
            encoding="utf-8",
        )
        scenario = self._scenario(harness_hash=executable_hash)
        backend = CooperativePlaytestHarness(
            workspace_root=self.runtime.state_dir / "playtests",
            executable=executable,
            executable_hash=executable_hash,
            harness_id="fixture-harness",
            harness_version="1",
            target_id="fixture-game",
            target_version="1",
            fixed_args=(str(script),),
        )
        result = PlaytestService(self.runtime, backend).execute(self.task, scenario)
        self.assertEqual(result.outcome, PlaytestOutcome.COMPLETED.value)
        self.assertEqual(result.summary.damage_dealt, 11)
        self.assertEqual(self.runtime.get_run(result.run_id)["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])


if __name__ == "__main__":
    unittest.main()
