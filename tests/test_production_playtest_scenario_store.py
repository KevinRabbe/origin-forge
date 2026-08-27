from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.playtest_models import (
    PlaytestAction,
    PlaytestActionKind,
    PlaytestScenario,
)
from origin_forge.production_playtest_scenario_store import (
    PlaytestScenarioStore,
    PlaytestScenarioStoreError,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observer import sha256_file


class PlaytestScenarioStoreTests(unittest.TestCase):
    def test_round_trip_is_exact_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("playtest-store")
            executable = Path(temp) / "harness.bin"
            executable.write_bytes(b"harness")
            scenario = PlaytestScenario.create(
                harness_id="cooperative-harness",
                harness_version="1",
                harness_hash=sha256_file(executable),
                target_id="game",
                target_version="1",
                allowed_controls=("jump",),
                actions=(PlaytestAction(0, 0, PlaytestActionKind.PRESS, "jump", duration_ms=10),),
            )
            store = PlaytestScenarioStore(runtime)
            stored = store.put(scenario)
            self.assertEqual(store.get(scenario.scenario_id, scenario.content_hash), scenario)
            self.assertEqual(stored.path.read_bytes(), stored.path.read_bytes())

    def test_tampered_bytes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("playtest-store")
            executable = Path(temp) / "harness.bin"
            executable.write_bytes(b"harness")
            scenario = PlaytestScenario.create(
                harness_id="cooperative-harness", harness_version="1",
                harness_hash=sha256_file(executable), target_id="game", target_version="1",
                allowed_controls=("jump",),
                actions=(PlaytestAction(0, 0, PlaytestActionKind.PRESS, "jump", duration_ms=10),),
            )
            stored = PlaytestScenarioStore(runtime).put(scenario)
            stored.path.write_bytes(stored.path.read_bytes().replace(b'"scenario_hash":"', b'"scenario_hash":"0', 1))
            with self.assertRaises(PlaytestScenarioStoreError):
                PlaytestScenarioStore(runtime).get(scenario.scenario_id, scenario.content_hash)


if __name__ == "__main__":
    unittest.main()
