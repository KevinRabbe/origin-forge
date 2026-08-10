from __future__ import annotations

import unittest

from origin_forge.playtest_analysis import analyze_playtest
from origin_forge.playtest_models import (
    PlaytestAction,
    PlaytestActionKind,
    PlaytestModelError,
    PlaytestOutcome,
    PlaytestScenario,
    PlaytestTelemetry,
    PlaytestTelemetryEvent,
    PlaytestTelemetryKind,
)


HARNESS_HASH = "sha256:" + "c" * 64


class PlaytestAnalysisTests(unittest.TestCase):
    def _scenario(self) -> PlaytestScenario:
        return PlaytestScenario.create(
            harness_id="fixture-harness",
            harness_version="1",
            harness_hash=HARNESS_HASH,
            target_id="fixture-game",
            target_version="1",
            allowed_controls=("move",),
            actions=(PlaytestAction(0, 0, PlaytestActionKind.SET_AXIS, "move", 1000),),
            max_duration_ms=20_000,
            progression_stall_threshold_ms=5_000,
        )

    def test_summary_covers_roadmap_runtime_outcomes(self) -> None:
        scenario = self._scenario()
        telemetry = PlaytestTelemetry(
            session_id=scenario.session_id,
            scenario_hash=scenario.content_hash,
            harness_id=scenario.harness_id,
            harness_version=scenario.harness_version,
            harness_hash=scenario.harness_hash,
            target_id=scenario.target_id,
            target_version=scenario.target_version,
            outcome=PlaytestOutcome.COMPLETED,
            duration_ms=12_000,
            events=(
                PlaytestTelemetryEvent(0, 500, PlaytestTelemetryKind.PROGRESSION, "spawn"),
                PlaytestTelemetryEvent(1, 1000, PlaytestTelemetryKind.ENCOUNTER_START, "enc-a"),
                PlaytestTelemetryEvent(2, 1500, PlaytestTelemetryKind.DAMAGE_DEALT, None, 40),
                PlaytestTelemetryEvent(3, 2000, PlaytestTelemetryKind.DAMAGE_TAKEN, None, 15),
                PlaytestTelemetryEvent(4, 3000, PlaytestTelemetryKind.RESOURCE_SHORTAGE, "ammo", 0),
                PlaytestTelemetryEvent(5, 3500, PlaytestTelemetryKind.PATHFINDING_FAILURE, "bot-1"),
                PlaytestTelemetryEvent(6, 4000, PlaytestTelemetryKind.ENCOUNTER_END, "enc-a"),
                PlaytestTelemetryEvent(7, 4500, PlaytestTelemetryKind.DEATH, "player"),
                PlaytestTelemetryEvent(8, 5000, PlaytestTelemetryKind.SOFT_LOCK, "door-a"),
                PlaytestTelemetryEvent(9, 6000, PlaytestTelemetryKind.PROGRESSION, "factory"),
            ),
        )
        summary = analyze_playtest(scenario, telemetry)
        self.assertEqual(summary.deaths, 1)
        self.assertEqual(summary.completed_encounters, 1)
        self.assertEqual(summary.total_encounter_duration_ms, 3000)
        self.assertEqual(summary.max_encounter_duration_ms, 3000)
        self.assertEqual(summary.damage_dealt, 40)
        self.assertEqual(summary.damage_taken, 15)
        self.assertEqual(summary.resource_shortages, 1)
        self.assertEqual(summary.soft_locks, 1)
        self.assertEqual(summary.pathfinding_failures, 1)
        self.assertEqual(summary.progression_events, 2)
        self.assertEqual(summary.max_progression_gap_ms, 6000)
        self.assertTrue(summary.progression_stall_detected)
        self.assertFalse(summary.to_dict()["production_task_verified"])
        self.assertFalse(summary.to_dict()["semantic_game_quality_verified"])

    def test_incomplete_and_unmatched_encounters_are_evidence_not_parse_failure(self) -> None:
        scenario = self._scenario()
        telemetry = PlaytestTelemetry(
            session_id=scenario.session_id,
            scenario_hash=scenario.content_hash,
            harness_id=scenario.harness_id,
            harness_version=scenario.harness_version,
            harness_hash=scenario.harness_hash,
            target_id=scenario.target_id,
            target_version=scenario.target_version,
            outcome=PlaytestOutcome.FAILED,
            duration_ms=4000,
            events=(
                PlaytestTelemetryEvent(0, 100, PlaytestTelemetryKind.ENCOUNTER_END, "never-started"),
                PlaytestTelemetryEvent(1, 1000, PlaytestTelemetryKind.ENCOUNTER_START, "still-open"),
            ),
        )
        summary = analyze_playtest(scenario, telemetry)
        self.assertEqual(summary.completed_encounters, 0)
        self.assertEqual(summary.incomplete_encounters, ("still-open",))
        self.assertEqual(summary.unmatched_encounter_ends, ("never-started",))

    def test_duplicate_active_encounter_fails_closed(self) -> None:
        scenario = self._scenario()
        telemetry = PlaytestTelemetry(
            session_id=scenario.session_id,
            scenario_hash=scenario.content_hash,
            harness_id=scenario.harness_id,
            harness_version=scenario.harness_version,
            harness_hash=scenario.harness_hash,
            target_id=scenario.target_id,
            target_version=scenario.target_version,
            outcome=PlaytestOutcome.FAILED,
            duration_ms=4000,
            events=(
                PlaytestTelemetryEvent(0, 100, PlaytestTelemetryKind.ENCOUNTER_START, "enc-a"),
                PlaytestTelemetryEvent(1, 200, PlaytestTelemetryKind.ENCOUNTER_START, "enc-a"),
            ),
        )
        with self.assertRaisesRegex(PlaytestModelError, "duplicate active encounter"):
            analyze_playtest(scenario, telemetry)


if __name__ == "__main__":
    unittest.main()
