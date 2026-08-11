from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .service import OriginForgeStore
from .state import TaskDependencyType, TaskStatus


class TaskReadinessError(RuntimeError):
    pass


class DependencyReadinessStatus(StrEnum):
    READY = "READY"
    WAITING_ON_DEPENDENCIES = "WAITING_ON_DEPENDENCIES"
    BLOCKED_BY_FAILED_DEPENDENCY = "BLOCKED_BY_FAILED_DEPENDENCY"
    INVALID_DEPENDENCY_STATE = "INVALID_DEPENDENCY_STATE"
    ACTIVE = "ACTIVE"
    TERMINAL = "TERMINAL"


class DependencyReasonKind(StrEnum):
    WAITING = "WAITING"
    FAILED = "FAILED"
    MISSING_PASS_VERIFICATION = "MISSING_PASS_VERIFICATION"


@dataclass(frozen=True)
class DependencyReadinessReason:
    required_task_id: str
    required_task_status: TaskStatus
    required_verification_status: str
    reason_kind: DependencyReasonKind

    def to_dict(self) -> dict[str, str]:
        return {
            "required_task_id": self.required_task_id,
            "required_task_status": self.required_task_status.value,
            "required_verification_status": self.required_verification_status,
            "reason_kind": self.reason_kind.value,
        }


@dataclass(frozen=True)
class TaskDependencyReadiness:
    task_id: str
    task_status: TaskStatus
    status: DependencyReadinessStatus
    reasons: tuple[DependencyReadinessReason, ...]
    dependency_count: int
    satisfied_dependency_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_status": self.task_status.value,
            "status": self.status.value,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "dependency_count": self.dependency_count,
            "satisfied_dependency_count": self.satisfied_dependency_count,
        }


_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.SUCCEEDED, TaskStatus.CANCELLED})
_FAILED_PREREQUISITE_STATUSES = frozenset(
    {TaskStatus.FAILED, TaskStatus.QUARANTINED, TaskStatus.CANCELLED}
)


def resolve_task_dependency_readiness(
    store: OriginForgeStore,
    task_id: str,
) -> TaskDependencyReadiness:
    """Derive dependency eligibility without mutating durable production state."""

    if not isinstance(store, OriginForgeStore):
        raise TypeError("store must be an OriginForgeStore")

    with store.session() as conn:
        task = conn.execute(
            "SELECT id, status FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise KeyError(task_id)
        try:
            task_status = TaskStatus(task["status"])
        except ValueError as exc:
            raise TaskReadinessError("task has invalid canonical status") from exc

        rows = conn.execute(
            """SELECT td.required_task_id, td.dependency_type, rt.status,
                      EXISTS(
                          SELECT 1 FROM verifications v
                          WHERE v.target_type = 'TASK'
                            AND v.target_id = td.required_task_id
                            AND v.status = 'PASS'
                      ) AS has_pass
               FROM task_dependencies td
               JOIN tasks rt ON rt.id = td.required_task_id
               WHERE td.task_id = ?
               ORDER BY td.required_task_id""",
            (task_id,),
        ).fetchall()

    if task_status in _TERMINAL_TASK_STATUSES:
        return TaskDependencyReadiness(
            task_id=task_id,
            task_status=task_status,
            status=DependencyReadinessStatus.TERMINAL,
            reasons=(),
            dependency_count=len(rows),
            satisfied_dependency_count=0,
        )

    reasons: list[DependencyReadinessReason] = []
    satisfied = 0
    has_failed = False
    has_invalid = False
    for row in rows:
        if row["dependency_type"] != TaskDependencyType.REQUIRES_SUCCESS.value:
            raise TaskReadinessError("unsupported durable dependency type")
        try:
            required_status = TaskStatus(row["status"])
        except ValueError as exc:
            raise TaskReadinessError("required task has invalid canonical status") from exc
        has_pass = bool(row["has_pass"])

        if required_status is TaskStatus.SUCCEEDED:
            if has_pass:
                satisfied += 1
                continue
            has_invalid = True
            reasons.append(
                DependencyReadinessReason(
                    required_task_id=row["required_task_id"],
                    required_task_status=required_status,
                    required_verification_status="MISSING_PASS",
                    reason_kind=DependencyReasonKind.MISSING_PASS_VERIFICATION,
                )
            )
            continue

        if required_status in _FAILED_PREREQUISITE_STATUSES:
            has_failed = True
            reasons.append(
                DependencyReadinessReason(
                    required_task_id=row["required_task_id"],
                    required_task_status=required_status,
                    required_verification_status="PASS" if has_pass else "MISSING_PASS",
                    reason_kind=DependencyReasonKind.FAILED,
                )
            )
            continue

        reasons.append(
            DependencyReadinessReason(
                required_task_id=row["required_task_id"],
                required_task_status=required_status,
                required_verification_status="PASS" if has_pass else "MISSING_PASS",
                reason_kind=DependencyReasonKind.WAITING,
            )
        )

    if has_invalid:
        status = DependencyReadinessStatus.INVALID_DEPENDENCY_STATE
    elif has_failed:
        status = DependencyReadinessStatus.BLOCKED_BY_FAILED_DEPENDENCY
    elif reasons:
        status = DependencyReadinessStatus.WAITING_ON_DEPENDENCIES
    elif task_status is TaskStatus.RUNNING:
        status = DependencyReadinessStatus.ACTIVE
    else:
        status = DependencyReadinessStatus.READY

    return TaskDependencyReadiness(
        task_id=task_id,
        task_status=task_status,
        status=status,
        reasons=tuple(reasons),
        dependency_count=len(rows),
        satisfied_dependency_count=satisfied,
    )
