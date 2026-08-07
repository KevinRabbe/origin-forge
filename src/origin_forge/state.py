from __future__ import annotations

from enum import StrEnum


class InvalidTransition(ValueError):
    pass


class FlowStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"
    SUCCEEDED = "SUCCEEDED"
    CANCELLED = "CANCELLED"


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"
    SUCCEEDED = "SUCCEEDED"
    CANCELLED = "CANCELLED"


FLOW_TRANSITIONS: dict[FlowStatus, frozenset[FlowStatus]] = {
    FlowStatus.QUEUED: frozenset({FlowStatus.RUNNING, FlowStatus.CANCELLED}),
    FlowStatus.RUNNING: frozenset(
        {
            FlowStatus.WAITING,
            FlowStatus.BLOCKED,
            FlowStatus.FAILED,
            FlowStatus.QUARANTINED,
            FlowStatus.SUCCEEDED,
            FlowStatus.CANCELLED,
        }
    ),
    FlowStatus.WAITING: frozenset(
        {FlowStatus.RUNNING, FlowStatus.BLOCKED, FlowStatus.CANCELLED}
    ),
    FlowStatus.BLOCKED: frozenset(
        {
            FlowStatus.RUNNING,
            FlowStatus.FAILED,
            FlowStatus.QUARANTINED,
            FlowStatus.CANCELLED,
        }
    ),
    FlowStatus.FAILED: frozenset(
        {FlowStatus.RUNNING, FlowStatus.QUARANTINED, FlowStatus.CANCELLED}
    ),
    FlowStatus.QUARANTINED: frozenset(
        {FlowStatus.RUNNING, FlowStatus.CANCELLED}
    ),
    FlowStatus.SUCCEEDED: frozenset(),
    FlowStatus.CANCELLED: frozenset(),
}


TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset(
        {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.QUARANTINED,
            TaskStatus.SUCCEEDED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING: frozenset(
        {
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.BLOCKED: frozenset(
        {
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.QUARANTINED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.FAILED: frozenset(
        {
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.QUARANTINED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.QUARANTINED: frozenset(
        {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.CANCELLED}
    ),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def ensure_transition(current: StrEnum, target: StrEnum, transitions: dict) -> None:
    allowed = transitions[current]
    if target not in allowed:
        raise InvalidTransition(f"invalid transition: {current.value} -> {target.value}")
