from __future__ import annotations

from dataclasses import dataclass

from .playtest_models import (
    PlaytestModelError,
    PlaytestScenario,
    PlaytestTelemetry,
    PlaytestTelemetryKind,
)


@dataclass(frozen=True)
class PlaytestSummary:
    deaths: int
    completed_encounters: int
    incomplete_encounters: tuple[str, ...]
    unmatched_encounter_ends: tuple[str, ...]
    total_encounter_duration_ms: int
    max_encounter_duration_ms: int
    damage_dealt: int
    damage_taken: int
    resource_shortages: int
    soft_locks: int
    pathfinding_failures: int
    progression_events: int
    max_progression_gap_ms: int
    progression_stall_detected: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "deaths": self.deaths,
            "completed_encounters": self.completed_encounters,
            "incomplete_encounters": list(self.incomplete_encounters),
            "unmatched_encounter_ends": list(self.unmatched_encounter_ends),
            "total_encounter_duration_ms": self.total_encounter_duration_ms,
            "max_encounter_duration_ms": self.max_encounter_duration_ms,
            "damage_dealt": self.damage_dealt,
            "damage_taken": self.damage_taken,
            "resource_shortages": self.resource_shortages,
            "soft_locks": self.soft_locks,
            "pathfinding_failures": self.pathfinding_failures,
            "progression_events": self.progression_events,
            "max_progression_gap_ms": self.max_progression_gap_ms,
            "progression_stall_detected": self.progression_stall_detected,
            "production_task_verified": False,
            "semantic_game_quality_verified": False,
        }


def analyze_playtest(
    scenario: PlaytestScenario,
    telemetry: PlaytestTelemetry,
) -> PlaytestSummary:
    if not isinstance(scenario, PlaytestScenario):
        raise TypeError("scenario must be a PlaytestScenario")
    if not isinstance(telemetry, PlaytestTelemetry):
        raise TypeError("telemetry must be a PlaytestTelemetry")
    telemetry.bind_scenario(scenario)

    deaths = 0
    damage_dealt = 0
    damage_taken = 0
    resource_shortages = 0
    soft_locks = 0
    pathfinding_failures = 0
    encounter_starts: dict[str, int] = {}
    encounter_durations: list[int] = []
    unmatched_ends: list[str] = []
    progression_times: list[int] = []

    for event in telemetry.events:
        if event.kind is PlaytestTelemetryKind.DEATH:
            deaths += 1
        elif event.kind is PlaytestTelemetryKind.DAMAGE_DEALT:
            assert event.value is not None
            damage_dealt += event.value
        elif event.kind is PlaytestTelemetryKind.DAMAGE_TAKEN:
            assert event.value is not None
            damage_taken += event.value
        elif event.kind is PlaytestTelemetryKind.RESOURCE_SHORTAGE:
            resource_shortages += 1
        elif event.kind is PlaytestTelemetryKind.SOFT_LOCK:
            soft_locks += 1
        elif event.kind is PlaytestTelemetryKind.PATHFINDING_FAILURE:
            pathfinding_failures += 1
        elif event.kind is PlaytestTelemetryKind.PROGRESSION:
            progression_times.append(event.at_ms)
        elif event.kind is PlaytestTelemetryKind.ENCOUNTER_START:
            assert event.subject_id is not None
            if event.subject_id in encounter_starts:
                raise PlaytestModelError(
                    f"duplicate active encounter start: {event.subject_id}"
                )
            encounter_starts[event.subject_id] = event.at_ms
        elif event.kind is PlaytestTelemetryKind.ENCOUNTER_END:
            assert event.subject_id is not None
            started = encounter_starts.pop(event.subject_id, None)
            if started is None:
                unmatched_ends.append(event.subject_id)
            else:
                encounter_durations.append(event.at_ms - started)

    boundaries = [0, *progression_times, telemetry.duration_ms]
    max_gap = max(
        (right - left for left, right in zip(boundaries, boundaries[1:])),
        default=telemetry.duration_ms,
    )
    return PlaytestSummary(
        deaths=deaths,
        completed_encounters=len(encounter_durations),
        incomplete_encounters=tuple(sorted(encounter_starts)),
        unmatched_encounter_ends=tuple(sorted(unmatched_ends)),
        total_encounter_duration_ms=sum(encounter_durations),
        max_encounter_duration_ms=max(encounter_durations, default=0),
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        resource_shortages=resource_shortages,
        soft_locks=soft_locks,
        pathfinding_failures=pathfinding_failures,
        progression_events=len(progression_times),
        max_progression_gap_ms=max_gap,
        progression_stall_detected=max_gap >= scenario.progression_stall_threshold_ms,
    )
