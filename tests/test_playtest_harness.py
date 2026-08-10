from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from origin_forge.playtest_analysis import analyze_playtest
from origin_forge.playtest_harness import (
    CooperativePlaytestHarness,
    PlaytestHarnessError,
)
from origin_forge.playtest_models import (
    PlaytestAction,
    PlaytestActionKind,
    PlaytestOutcome,
    PlaytestScenario,
)
from origin_forge.runtime_observer import sha256_file


class CooperativePlaytestHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.executable = Path(sys.executable).resolve(strict=True)
        self.executable_hash = sha256_file(self.executable)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _script(self, body: str) -> Path:
        path = self.root / f"harness-{len(list(self.root.glob('harness-*.py')))}.py"
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def _scenario(
        self,
        *,
        max_duration_ms: int = 5000,
        max_log_bytes: int = 4096,
    ) -> PlaytestScenario:
        return PlaytestScenario.create(
            harness_id="fixture-harness",
            harness_version="1",
            harness_hash=self.executable_hash,
            target_id="fixture-game",
            target_version="1",
            allowed_controls=("move-x", "attack"),
            actions=(
                PlaytestAction(0, 0, PlaytestActionKind.SET_AXIS, "move-x", 1000),
                PlaytestAction(1, 100, PlaytestActionKind.PRESS, "attack", None, 50),
            ),
            max_duration_ms=max_duration_ms,
            max_log_bytes=max_log_bytes,
            progression_stall_threshold_ms=max(1, min(1000, max_duration_ms)),
        )

    def _adapter(self, script: Path) -> CooperativePlaytestHarness:
        return CooperativePlaytestHarness(
            workspace_root=self.root / "state" / "playtests",
            executable=self.executable,
            executable_hash=self.executable_hash,
            harness_id="fixture-harness",
            harness_version="1",
            target_id="fixture-game",
            target_version="1",
            fixed_args=(str(script),),
        )

    def test_real_harness_receives_semantic_plan_and_returns_bound_telemetry(self) -> None:
        script = self._script(
            """
            import json
            import os
            from pathlib import Path

            scenario = json.loads(Path(os.environ['ORIGIN_FORGE_PLAYTEST_SCENARIO']).read_text())
            assert [item['control'] for item in scenario['actions']] == ['move-x', 'attack']
            telemetry = {
                'session_id': scenario['session_id'],
                'scenario_hash': os.environ['ORIGIN_FORGE_PLAYTEST_SCENARIO_HASH'],
                'harness_id': scenario['harness_id'],
                'harness_version': scenario['harness_version'],
                'harness_hash': scenario['harness_hash'],
                'target_id': scenario['target_id'],
                'target_version': scenario['target_version'],
                'outcome': 'COMPLETED',
                'duration_ms': 1200,
                'events': [
                    {'sequence': 0, 'at_ms': 100, 'kind': 'PROGRESSION', 'subject_id': 'spawn', 'value': None},
                    {'sequence': 1, 'at_ms': 200, 'kind': 'ENCOUNTER_START', 'subject_id': 'enc-a', 'value': None},
                    {'sequence': 2, 'at_ms': 400, 'kind': 'DAMAGE_DEALT', 'subject_id': None, 'value': 25},
                    {'sequence': 3, 'at_ms': 800, 'kind': 'ENCOUNTER_END', 'subject_id': 'enc-a', 'value': None},
                ],
            }
            Path(os.environ['ORIGIN_FORGE_PLAYTEST_TELEMETRY']).write_text(
                json.dumps(telemetry, sort_keys=True, separators=(',', ':'))
            )
            print('harness-ok')
            """
        )
        scenario = self._scenario()
        execution = self._adapter(script).execute(scenario)
        self.assertEqual(execution.exit_code, 0)
        self.assertFalse(execution.timed_out)
        self.assertIs(execution.telemetry.outcome, PlaytestOutcome.COMPLETED)
        execution.telemetry.bind_scenario(scenario)
        summary = analyze_playtest(scenario, execution.telemetry)
        self.assertEqual(summary.completed_encounters, 1)
        self.assertEqual(summary.total_encounter_duration_ms, 600)
        self.assertEqual(summary.damage_dealt, 25)
        self.assertIn(b"harness-ok", execution.stdout_path.read_bytes())

    def test_nonzero_exit_without_telemetry_is_preserved_as_failed_playtest(self) -> None:
        script = self._script("raise SystemExit(7)\n")
        scenario = self._scenario()
        execution = self._adapter(script).execute(scenario)
        self.assertEqual(execution.exit_code, 7)
        self.assertFalse(execution.timed_out)
        self.assertIs(execution.telemetry.outcome, PlaytestOutcome.FAILED)
        self.assertEqual(execution.telemetry.events, ())
        execution.telemetry.bind_scenario(scenario)

    def test_timeout_is_preserved_without_requiring_target_telemetry(self) -> None:
        script = self._script(
            """
            import time
            print('started', flush=True)
            time.sleep(10)
            """
        )
        scenario = self._scenario(max_duration_ms=250)
        execution = self._adapter(script).execute(scenario)
        self.assertTrue(execution.timed_out)
        self.assertIsNone(execution.exit_code)
        self.assertIs(execution.telemetry.outcome, PlaytestOutcome.TIMEOUT)
        self.assertEqual(execution.telemetry.duration_ms, 250)
        self.assertIn(b"started", execution.stdout_path.read_bytes())

    def test_success_without_telemetry_fails_closed(self) -> None:
        script = self._script("print('no telemetry')\n")
        with self.assertRaisesRegex(PlaytestHarnessError, "omitted telemetry"):
            self._adapter(script).execute(self._scenario())

    def test_telemetry_extra_field_is_rejected(self) -> None:
        script = self._script(
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
                'duration_ms': 1,
                'events': [],
                'script': 'caller-controlled',
            }
            Path(os.environ['ORIGIN_FORGE_PLAYTEST_TELEMETRY']).write_text(json.dumps(telemetry))
            """
        )
        with self.assertRaisesRegex(PlaytestHarnessError, "fields differ"):
            self._adapter(script).execute(self._scenario())

    def test_log_budget_overflow_terminates_harness(self) -> None:
        script = self._script(
            """
            import sys
            sys.stdout.write('x' * 200000)
            sys.stdout.flush()
            """
        )
        with self.assertRaisesRegex(PlaytestHarnessError, "log byte budget"):
            self._adapter(script).execute(self._scenario(max_log_bytes=1024))


if __name__ == "__main__":
    unittest.main()
