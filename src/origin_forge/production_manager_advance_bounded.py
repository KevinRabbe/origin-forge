from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .production_manager_advance_once import (
    ManagerAdvanceOnceResult,
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)

MAX_MANAGER_ADVANCE_STEPS = 6

MANAGER_ADVANCE_CONTINUATION_STATUSES = frozenset(
    {
        ManagerAdvanceOnceStatus.PREPARATION_RECOVERY_ADVANCED,
        ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
        ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
        ManagerAdvanceOnceStatus.PHASE34_READY,
    }
)


class BoundedManagerAdvanceStopReason(StrEnum):
    NO_ACTIONABLE_WORK = "NO_ACTIONABLE_WORK"
    NON_CONTINUABLE_RESULT = "NON_CONTINUABLE_RESULT"
    STEP_LIMIT_REACHED = "STEP_LIMIT_REACHED"


@dataclass(frozen=True)
class BoundedManagerAdvanceResult:
    steps: tuple[ManagerAdvanceOnceResult, ...]
    stop_reason: BoundedManagerAdvanceStopReason
    max_steps: int = field(default=MAX_MANAGER_ADVANCE_STEPS, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.steps, tuple):
            raise TypeError("steps must be a tuple of ManagerAdvanceOnceResult values")
        if not 1 <= len(self.steps) <= MAX_MANAGER_ADVANCE_STEPS:
            raise ValueError(
                f"steps must contain between 1 and {MAX_MANAGER_ADVANCE_STEPS} results"
            )
        if not isinstance(self.stop_reason, BoundedManagerAdvanceStopReason):
            raise TypeError("stop_reason must be a BoundedManagerAdvanceStopReason")
        for result in self.steps:
            _validate_once_result(result)
        if any(
            result.status not in MANAGER_ADVANCE_CONTINUATION_STATUSES
            for result in self.steps[:-1]
        ):
            raise ValueError("only continuable Manager results may precede the final step")

        final_status = self.steps[-1].status
        if self.stop_reason is BoundedManagerAdvanceStopReason.STEP_LIMIT_REACHED:
            if len(self.steps) != MAX_MANAGER_ADVANCE_STEPS:
                raise ValueError("STEP_LIMIT_REACHED requires exactly the fixed step limit")
            if final_status not in MANAGER_ADVANCE_CONTINUATION_STATUSES:
                raise ValueError("STEP_LIMIT_REACHED requires a continuable final result")
        elif self.stop_reason is BoundedManagerAdvanceStopReason.NO_ACTIONABLE_WORK:
            if final_status is not ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK:
                raise ValueError("NO_ACTIONABLE_WORK stop requires that exact final status")
        else:
            if final_status is ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK:
                raise ValueError("NO_ACTIONABLE_WORK has its own stop reason")
            if final_status in MANAGER_ADVANCE_CONTINUATION_STATUSES:
                raise ValueError("NON_CONTINUABLE_RESULT requires a non-continuable final status")

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def final_result(self) -> ManagerAdvanceOnceResult:
        return self.steps[-1]

    def to_dict(self) -> dict[str, object]:
        return {
            "steps": [result.to_dict() for result in self.steps],
            "step_count": self.step_count,
            "stop_reason": self.stop_reason.value,
            "max_steps": self.max_steps,
            "authority": "bounded-manager-advance-driver",
        }


def _validate_once_result(result: object) -> None:
    if not isinstance(result, ManagerAdvanceOnceResult):
        raise TypeError("advance_production_manager_once returned an invalid result type")
    if not isinstance(result.status, ManagerAdvanceOnceStatus):
        raise TypeError("ManagerAdvanceOnceResult.status must be a ManagerAdvanceOnceStatus")


def advance_production_manager_bounded(runtime: object) -> BoundedManagerAdvanceResult:
    """Perform fresh one-shot Manager admissions until a frozen stop boundary is reached."""

    steps: list[ManagerAdvanceOnceResult] = []
    for _ in range(MAX_MANAGER_ADVANCE_STEPS):
        result = advance_production_manager_once(runtime)
        _validate_once_result(result)
        steps.append(result)

        if result.status not in MANAGER_ADVANCE_CONTINUATION_STATUSES:
            stop_reason = (
                BoundedManagerAdvanceStopReason.NO_ACTIONABLE_WORK
                if result.status is ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK
                else BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT
            )
            return BoundedManagerAdvanceResult(tuple(steps), stop_reason)

    return BoundedManagerAdvanceResult(
        tuple(steps),
        BoundedManagerAdvanceStopReason.STEP_LIMIT_REACHED,
    )
