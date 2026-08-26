from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .ids import IdKind, validate_id
from .playtest_models import (
    PlaytestAction,
    PlaytestActionKind,
    PlaytestModelError,
    PlaytestScenario,
)
from .runtime import OriginForgeRuntime
from .runtime_observation_models import canonical_bytes, validate_sha256


class PlaytestScenarioStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredPlaytestScenario:
    scenario: PlaytestScenario
    path: Path
    byte_count: int


class PlaytestScenarioStore:
    """Immutable protected reader for exact cooperative-playtest scenarios."""

    _SCHEMA_VERSION = 1
    _MAX_BYTES = 512 * 1024
    _MAX_SCENARIOS = 256

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "playtest-scenarios"

    def _root(self, *, create: bool) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.root.is_symlink():
            raise PlaytestScenarioStoreError("scenario store may not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists():
            return self.root
        try:
            resolved = self.root.resolve(strict=True)
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PlaytestScenarioStoreError("scenario store escapes protected project state") from exc
        if not resolved.is_dir():
            raise PlaytestScenarioStoreError("scenario store root must be a directory")
        return resolved

    @staticmethod
    def _path(root: Path, scenario_id: str, scenario_hash: str) -> Path:
        if not validate_id(scenario_id, IdKind.PLAYTEST_SCENARIO):
            raise PlaytestScenarioStoreError("scenario_id must be a PLAYSCEN ID")
        validate_sha256(scenario_hash, "scenario_hash")
        return root / f"{scenario_id}--{scenario_hash.removeprefix('sha256:')}.json"

    @classmethod
    def _parse(cls, value: object) -> PlaytestScenario:
        if not isinstance(value, dict):
            raise PlaytestScenarioStoreError("stored playtest scenario must be an object")
        expected = {
            "schema_version", "scenario_id", "session_id", "workspace_id", "harness_id",
            "harness_version", "harness_hash", "target_id", "target_version", "max_duration_ms",
            "max_log_bytes", "progression_stall_threshold_ms", "allowed_controls", "actions", "scenario_hash",
        }
        if set(value) != expected or value.get("schema_version") != cls._SCHEMA_VERSION:
            raise PlaytestScenarioStoreError("stored playtest scenario has unknown or missing fields")
        try:
            actions = tuple(
                PlaytestAction(
                    sequence=item["sequence"], at_ms=item["at_ms"],
                    kind=PlaytestActionKind(item["kind"]), control=item.get("control"),
                    value_milli=item.get("value_milli"), duration_ms=item.get("duration_ms", 0),
                )
                for item in value["actions"]
            )
            scenario = PlaytestScenario(
                scenario_id=value["scenario_id"], session_id=value["session_id"],
                workspace_id=value["workspace_id"], harness_id=value["harness_id"],
                harness_version=value["harness_version"], harness_hash=value["harness_hash"],
                target_id=value["target_id"], target_version=value["target_version"],
                max_duration_ms=value["max_duration_ms"], max_log_bytes=value["max_log_bytes"],
                progression_stall_threshold_ms=value["progression_stall_threshold_ms"],
                allowed_controls=tuple(value["allowed_controls"]), actions=actions,
            )
        except (KeyError, TypeError, ValueError, PlaytestModelError) as exc:
            raise PlaytestScenarioStoreError("stored playtest scenario is invalid") from exc
        if value["scenario_hash"] != scenario.content_hash:
            raise PlaytestScenarioStoreError("stored playtest scenario hash mismatch")
        return scenario

    def put(self, scenario: PlaytestScenario) -> StoredPlaytestScenario:
        if not isinstance(scenario, PlaytestScenario):
            raise TypeError("scenario must be a PlaytestScenario")
        root = self._root(create=True)
        data = canonical_bytes({"schema_version": self._SCHEMA_VERSION, **scenario.to_dict(), "scenario_hash": scenario.content_hash})
        if len(data) > self._MAX_BYTES:
            raise PlaytestScenarioStoreError("playtest scenario exceeds byte limit")
        target = self._path(root, scenario.scenario_id, scenario.content_hash)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                raise PlaytestScenarioStoreError("scenario identity is already bound to different bytes")
            return StoredPlaytestScenario(scenario, target, len(data))
        if len(tuple(root.glob("*.json"))) >= self._MAX_SCENARIOS:
            raise PlaytestScenarioStoreError("playtest scenario store is full")
        temp = root / f".{target.name}.{os.getpid()}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        except (OSError, FileExistsError) as exc:
            raise PlaytestScenarioStoreError("failed to persist playtest scenario") from exc
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return StoredPlaytestScenario(scenario, target, len(data))

    def get(self, scenario_id: str, scenario_hash: str) -> PlaytestScenario:
        target = self._path(self._root(create=False), scenario_id, scenario_hash)
        if target.is_symlink() or not target.is_file():
            raise KeyError((scenario_id, scenario_hash))
        try:
            if target.stat().st_size > self._MAX_BYTES:
                raise PlaytestScenarioStoreError("stored playtest scenario exceeds byte limit")
            value = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlaytestScenarioStoreError("stored playtest scenario is not valid UTF-8 JSON") from exc
        scenario = self._parse(value)
        if scenario.scenario_id != scenario_id or scenario.content_hash != scenario_hash:
            raise PlaytestScenarioStoreError("scenario identity does not match protected path")
        return scenario
