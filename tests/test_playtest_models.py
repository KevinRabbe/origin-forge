from __future__ import annotations

import unittest

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


HARNESS_HASH = "sha256:" + "a" * 64


class PlaytestModelTests(unittest.TestCase):
    def _scenario(self) -> PlaytestScenario:
        return PlaytestScenario.create(
            harness_id="fixture-harness",
            harness_version="1",
            harness_hash=HARNESS_HASH,
            target_id="fixture-game",
            target_version="1",
            allowed_controls=("move-x", "attack", "interact"),
            actions=(
                PlaytestAction(0, 0, PlaytestActionKind.SET_AXIS, "move-x", 1000),
                PlaytestAction(1, 500, PlaytestActionKind.PRESS, "attack", None, 100),
                PlaytestAction(2, 1000, PlaytestActionKind.WAIT, None, None, 500),
                PlaytestAction(3, 1500, PlaytestActionKind.RELEASE, "move-x"),
            ),
            max_duration_ms=5000,
            progression_stall_threshold_ms=2000,
        )

    def test_scenario_is_content_addressed_and_control_bounded(self) -> None:
        scenario = self._scenario()
        self.assertTrue(scenario.scenario_id.startswith("PLAYSCEN-"))
        self.assertTrue(scenario.session_id.startswith("PLAY-"))
        self.assertTrue(scenario.workspace_id.startswith("PLAYWS-"))
        self.assertEqual(scenario.allowed_controls, ("attack", "interact", "move-x"))
        self.assertTrue(scenario.content_hash.startswith("sha256:"))

        with self.assertRaisesRegex(PlaytestModelError, "outside allowed_controls"):
            PlaytestScenario.create(
                harness_id="fixture-harness",
                harness_version="1",
                harness_hash=HARNESS_HASH,
                target_id="fixture-game",
                target_version="1",
                allowed_controls=("attack",),
                actions=(
                    PlaytestAction(0, 0, PlaytestActionKind.PRESS, "debug-console", None, 10),
                ),
            )

    def test_action_contract_rejects_ambiguous_or_unbounded_shapes(self) -> None:
        with self.assertRaisesRegex(PlaytestModelError, "WAIT requires"):
            PlaytestAction(0, 0, PlaytestActionKind.WAIT)
        with self.assertRaisesRegex(PlaytestModelError, "value_milli"):
            PlaytestAction(0, 0, PlaytestActionKind.SET_AXIS, "move-x")
        with self.assertRaisesRegex(PlaytestModelError, "-1000 to 1000"):
            PlaytestAction(0, 0, PlaytestActionKind.SET_AXIS, "move-x", 1001)
        with self.assertRaisesRegex(PlaytestModelError, "contiguous"):
            PlaytestScenario.create(
                harness_id="fixture-harness",
                harness_version="1",
                harness_hash=HARNESS_HASH,
                target_id="fixture-game",
                target_version="1",
                allowed_controls=("attack",),
                actions=(
                    PlaytestAction(1, 0, PlaytestActionKind.PRESS, "attack", None, 10),
                ),
            )

    def test_telemetry_binds_exact_scenario_identity(self) -> None:
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
            duration_ms=2000,
            events=(
                PlaytestTelemetryEvent(0, 100, PlaytestTelemetryKind.PROGRESSION, "spawn"),
                PlaytestTelemetryEvent(1, 500, PlaytestTelemetryKind.DAMAGE_DEALT, None, 20),
            ),
        )
        telemetry.bind_scenario(scenario)
        self.assertTrue(telemetry.content_hash.startswith("sha256:"))

        drifted = PlaytestTelemetry(
            session_id=scenario.session_id,
            scenario_hash="sha256:" + "b" * 64,
            harness_id=scenario.harness_id,
            harness_version=scenario.harness_version,
            harness_hash=scenario.harness_hash,
            target_id=scenario.target_id,
            target_version=scenario.target_version,
            outcome=PlaytestOutcome.COMPLETED,
            duration_ms=2000,
            events=(),
        )
        with self.assertRaisesRegex(PlaytestModelError, "exact playtest scenario"):
            drifted.bind_scenario(scenario)

    def test_telemetry_shapes_are_typed_and_ordered(self) -> None:
        with self.assertRaisesRegex(PlaytestModelError, "requires subject_id"):
            PlaytestTelemetryEvent(0, 0, PlaytestTelemetryKind.DEATH)
        with self.assertRaisesRegex(PlaytestModelError, "positive value"):
            PlaytestTelemetryEvent(0, 0, PlaytestTelemetryKind.DAMAGE_TAKEN, None, 0)
        with self.assertRaisesRegex(PlaytestModelError, "current resource"):
            PlaytestTelemetryEvent(
                0, 0, PlaytestTelemetryKind.RESOURCE_SHORTAGE, "ammo"
            )
        scenario = self._scenario()
        with self.assertRaisesRegex(PlaytestModelError, "ordered"):
            PlaytestTelemetry(
                session_id=scenario.session_id,
                scenario_hash=scenario.content_hash,
                harness_id=scenario.harness_id,
                harness_version=scenario.harness_version,
                harness_hash=scenario.harness_hash,
                target_id=scenario.target_id,
                target_version=scenario.target_version,
                outcome=PlaytestOutcome.FAILED,
                duration_ms=1000,
                events=(
                    PlaytestTelemetryEvent(0, 900, PlaytestTelemetryKind.PROGRESSION, "late"),
                    PlaytestTelemetryEvent(1, 100, PlaytestTelemetryKind.PROGRESSION, "early"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
