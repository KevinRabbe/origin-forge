from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import content_hash, validate_sha256


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}$")
_MAX_ACTIONS = 4096
_MAX_EVENTS = 65_536
_MAX_DURATION_MS = 3_600_000
_MAX_LOG_BYTES = 16 * 1024 * 1024


class PlaytestModelError(ValueError):
    pass


class PlaytestActionKind(StrEnum):
    SET_AXIS = "SET_AXIS"
    PRESS = "PRESS"
    RELEASE = "RELEASE"
    WAIT = "WAIT"


class PlaytestTelemetryKind(StrEnum):
    DEATH = "DEATH"
    ENCOUNTER_START = "ENCOUNTER_START"
    ENCOUNTER_END = "ENCOUNTER_END"
    DAMAGE_DEALT = "DAMAGE_DEALT"
    DAMAGE_TAKEN = "DAMAGE_TAKEN"
    RESOURCE_SHORTAGE = "RESOURCE_SHORTAGE"
    SOFT_LOCK = "SOFT_LOCK"
    PATHFINDING_FAILURE = "PATHFINDING_FAILURE"
    PROGRESSION = "PROGRESSION"


class PlaytestOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise PlaytestModelError(f"{label} must be a bounded identity token")
    return value


def _bounded_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise PlaytestModelError(f"{label} must be from {minimum} to {maximum}")
    return value


@dataclass(frozen=True)
class PlaytestAction:
    sequence: int
    at_ms: int
    kind: PlaytestActionKind
    control: str | None = None
    value_milli: int | None = None
    duration_ms: int = 0

    def __post_init__(self) -> None:
        _bounded_int(self.sequence, "action sequence", 0, _MAX_ACTIONS - 1)
        _bounded_int(self.at_ms, "action at_ms", 0, _MAX_DURATION_MS)
        if not isinstance(self.kind, PlaytestActionKind):
            raise PlaytestModelError("action kind must be a PlaytestActionKind")
        _bounded_int(self.duration_ms, "action duration_ms", 0, 60_000)

        if self.kind is PlaytestActionKind.WAIT:
            if self.control is not None or self.value_milli is not None:
                raise PlaytestModelError("WAIT may not name a control or axis value")
            if self.duration_ms <= 0:
                raise PlaytestModelError("WAIT requires positive duration_ms")
            return

        if self.control is None:
            raise PlaytestModelError(f"{self.kind.value} requires a control")
        object.__setattr__(self, "control", _token(self.control, "action control"))

        if self.kind is PlaytestActionKind.SET_AXIS:
            if self.value_milli is None:
                raise PlaytestModelError("SET_AXIS requires value_milli")
            _bounded_int(self.value_milli, "action value_milli", -1000, 1000)
            if self.duration_ms != 0:
                raise PlaytestModelError("SET_AXIS duration_ms must be zero")
            return

        if self.value_milli is not None:
            raise PlaytestModelError(f"{self.kind.value} may not carry value_milli")
        if self.kind is PlaytestActionKind.PRESS:
            if self.duration_ms <= 0:
                raise PlaytestModelError("PRESS requires positive duration_ms")
        elif self.duration_ms != 0:
            raise PlaytestModelError("RELEASE duration_ms must be zero")

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "at_ms": self.at_ms,
            "kind": self.kind.value,
            "control": self.control,
            "value_milli": self.value_milli,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class PlaytestScenario:
    scenario_id: str
    session_id: str
    workspace_id: str
    harness_id: str
    harness_version: str
    harness_hash: str
    target_id: str
    target_version: str
    max_duration_ms: int
    max_log_bytes: int
    progression_stall_threshold_ms: int
    allowed_controls: tuple[str, ...]
    actions: tuple[PlaytestAction, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.scenario_id, IdKind.PLAYTEST_SCENARIO):
            raise PlaytestModelError("scenario_id must be a PLAYSCEN ID")
        if not validate_id(self.session_id, IdKind.PLAYTEST_SESSION):
            raise PlaytestModelError("session_id must be a PLAY ID")
        if not validate_id(self.workspace_id, IdKind.PLAYTEST_WORKSPACE):
            raise PlaytestModelError("workspace_id must be a PLAYWS ID")
        object.__setattr__(self, "harness_id", _token(self.harness_id, "harness_id"))
        object.__setattr__(
            self, "harness_version", _token(self.harness_version, "harness_version")
        )
        validate_sha256(self.harness_hash, "harness_hash")
        object.__setattr__(self, "target_id", _token(self.target_id, "target_id"))
        object.__setattr__(
            self, "target_version", _token(self.target_version, "target_version")
        )
        _bounded_int(self.max_duration_ms, "max_duration_ms", 1, _MAX_DURATION_MS)
        _bounded_int(self.max_log_bytes, "max_log_bytes", 1, _MAX_LOG_BYTES)
        _bounded_int(
            self.progression_stall_threshold_ms,
            "progression_stall_threshold_ms",
            1,
            self.max_duration_ms,
        )

        controls = tuple(_token(value, "allowed control") for value in self.allowed_controls)
        if not controls or len(controls) > 128:
            raise PlaytestModelError("allowed_controls must contain from 1 to 128 controls")
        if len(set(controls)) != len(controls):
            raise PlaytestModelError("allowed_controls contain duplicates")
        object.__setattr__(self, "allowed_controls", tuple(sorted(controls)))

        actions = tuple(self.actions)
        if not actions or len(actions) > _MAX_ACTIONS:
            raise PlaytestModelError("actions must contain from 1 to 4096 entries")
        expected_sequences = list(range(len(actions)))
        if [value.sequence for value in actions] != expected_sequences:
            raise PlaytestModelError("action sequence must be contiguous from zero")
        previous_at = -1
        allowed = set(controls)
        for action in actions:
            if action.at_ms < previous_at:
                raise PlaytestModelError("actions must be ordered by nondecreasing at_ms")
            previous_at = action.at_ms
            if action.at_ms > self.max_duration_ms:
                raise PlaytestModelError("action occurs after max_duration_ms")
            if action.at_ms + action.duration_ms > self.max_duration_ms:
                raise PlaytestModelError("action duration exceeds max_duration_ms")
            if action.control is not None and action.control not in allowed:
                raise PlaytestModelError("action references a control outside allowed_controls")
        object.__setattr__(self, "actions", actions)

    @classmethod
    def create(
        cls,
        *,
        harness_id: str,
        harness_version: str,
        harness_hash: str,
        target_id: str,
        target_version: str,
        allowed_controls: Iterable[str],
        actions: Iterable[PlaytestAction],
        max_duration_ms: int = 60_000,
        max_log_bytes: int = 1_048_576,
        progression_stall_threshold_ms: int = 10_000,
    ) -> "PlaytestScenario":
        return cls(
            scenario_id=new_id(IdKind.PLAYTEST_SCENARIO),
            session_id=new_id(IdKind.PLAYTEST_SESSION),
            workspace_id=new_id(IdKind.PLAYTEST_WORKSPACE),
            harness_id=harness_id,
            harness_version=harness_version,
            harness_hash=harness_hash,
            target_id=target_id,
            target_version=target_version,
            max_duration_ms=max_duration_ms,
            max_log_bytes=max_log_bytes,
            progression_stall_threshold_ms=progression_stall_threshold_ms,
            allowed_controls=tuple(allowed_controls),
            actions=tuple(actions),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "harness_id": self.harness_id,
            "harness_version": self.harness_version,
            "harness_hash": self.harness_hash,
            "target_id": self.target_id,
            "target_version": self.target_version,
            "max_duration_ms": self.max_duration_ms,
            "max_log_bytes": self.max_log_bytes,
            "progression_stall_threshold_ms": self.progression_stall_threshold_ms,
            "allowed_controls": list(self.allowed_controls),
            "actions": [value.to_dict() for value in self.actions],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class PlaytestTelemetryEvent:
    sequence: int
    at_ms: int
    kind: PlaytestTelemetryKind
    subject_id: str | None = None
    value: int | None = None

    def __post_init__(self) -> None:
        _bounded_int(self.sequence, "telemetry sequence", 0, _MAX_EVENTS - 1)
        _bounded_int(self.at_ms, "telemetry at_ms", 0, _MAX_DURATION_MS)
        if not isinstance(self.kind, PlaytestTelemetryKind):
            raise PlaytestModelError("telemetry kind must be a PlaytestTelemetryKind")
        if self.subject_id is not None:
            object.__setattr__(
                self, "subject_id", _token(self.subject_id, "telemetry subject_id")
            )
        if self.value is not None:
            _bounded_int(self.value, "telemetry value", 0, 2_147_483_647)

        subject_required = {
            PlaytestTelemetryKind.DEATH,
            PlaytestTelemetryKind.ENCOUNTER_START,
            PlaytestTelemetryKind.ENCOUNTER_END,
            PlaytestTelemetryKind.RESOURCE_SHORTAGE,
            PlaytestTelemetryKind.SOFT_LOCK,
            PlaytestTelemetryKind.PATHFINDING_FAILURE,
            PlaytestTelemetryKind.PROGRESSION,
        }
        value_required = {
            PlaytestTelemetryKind.DAMAGE_DEALT,
            PlaytestTelemetryKind.DAMAGE_TAKEN,
        }
        if self.kind in subject_required and self.subject_id is None:
            raise PlaytestModelError(f"{self.kind.value} requires subject_id")
        if self.kind in value_required:
            if self.value is None or self.value <= 0:
                raise PlaytestModelError(f"{self.kind.value} requires positive value")
        elif self.kind is PlaytestTelemetryKind.RESOURCE_SHORTAGE:
            if self.value is None:
                raise PlaytestModelError("RESOURCE_SHORTAGE requires current resource value")
        elif self.value is not None:
            raise PlaytestModelError(f"{self.kind.value} may not carry value")

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "at_ms": self.at_ms,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "value": self.value,
        }


@dataclass(frozen=True)
class PlaytestTelemetry:
    session_id: str
    scenario_hash: str
    harness_id: str
    harness_version: str
    harness_hash: str
    target_id: str
    target_version: str
    outcome: PlaytestOutcome
    duration_ms: int
    events: tuple[PlaytestTelemetryEvent, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.session_id, IdKind.PLAYTEST_SESSION):
            raise PlaytestModelError("telemetry session_id must be a PLAY ID")
        validate_sha256(self.scenario_hash, "scenario_hash")
        object.__setattr__(self, "harness_id", _token(self.harness_id, "harness_id"))
        object.__setattr__(
            self, "harness_version", _token(self.harness_version, "harness_version")
        )
        validate_sha256(self.harness_hash, "harness_hash")
        object.__setattr__(self, "target_id", _token(self.target_id, "target_id"))
        object.__setattr__(
            self, "target_version", _token(self.target_version, "target_version")
        )
        if not isinstance(self.outcome, PlaytestOutcome):
            raise PlaytestModelError("outcome must be a PlaytestOutcome")
        _bounded_int(self.duration_ms, "telemetry duration_ms", 0, _MAX_DURATION_MS)
        events = tuple(self.events)
        if len(events) > _MAX_EVENTS:
            raise PlaytestModelError("telemetry event count exceeds 65536")
        if [value.sequence for value in events] != list(range(len(events))):
            raise PlaytestModelError("telemetry sequence must be contiguous from zero")
        previous_at = -1
        for event in events:
            if event.at_ms < previous_at:
                raise PlaytestModelError("telemetry events must be ordered by at_ms")
            if event.at_ms > self.duration_ms:
                raise PlaytestModelError("telemetry event occurs after duration_ms")
            previous_at = event.at_ms
        object.__setattr__(self, "events", events)

    def bind_scenario(self, scenario: PlaytestScenario) -> None:
        if not isinstance(scenario, PlaytestScenario):
            raise TypeError("scenario must be a PlaytestScenario")
        expected = (
            scenario.session_id,
            scenario.content_hash,
            scenario.harness_id,
            scenario.harness_version,
            scenario.harness_hash,
            scenario.target_id,
            scenario.target_version,
        )
        actual = (
            self.session_id,
            self.scenario_hash,
            self.harness_id,
            self.harness_version,
            self.harness_hash,
            self.target_id,
            self.target_version,
        )
        if actual != expected:
            raise PlaytestModelError("telemetry does not bind exact playtest scenario identity")
        if self.duration_ms > scenario.max_duration_ms:
            raise PlaytestModelError("telemetry duration exceeds scenario max_duration_ms")

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "scenario_hash": self.scenario_hash,
            "harness_id": self.harness_id,
            "harness_version": self.harness_version,
            "harness_hash": self.harness_hash,
            "target_id": self.target_id,
            "target_version": self.target_version,
            "outcome": self.outcome.value,
            "duration_ms": self.duration_ms,
            "events": [value.to_dict() for value in self.events],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
