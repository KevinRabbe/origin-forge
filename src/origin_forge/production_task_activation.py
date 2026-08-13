from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .ids import IdKind, validate_id
from .production_capability_routing import task_routing_hash
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now
from .state import TASK_TRANSITIONS, TaskStatus, ensure_transition
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


class TaskActivationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskActivationResult:
    task_id: str
    previous_revision: int
    new_revision: int
    previous_task_content_hash: str
    new_task_content_hash: str
    dependency_count: int
    satisfied_dependency_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "previous_revision": self.previous_revision,
            "new_revision": self.new_revision,
            "previous_task_content_hash": self.previous_task_content_hash,
            "new_task_content_hash": self.new_task_content_hash,
            "dependency_count": self.dependency_count,
            "satisfied_dependency_count": self.satisfied_dependency_count,
        }


def _activate_dependency_ready_task_connection(
    runtime: OriginForgeRuntime,
    conn: sqlite3.Connection,
    project_id: str,
    task_id: str,
    expected_revision: int,
    now: str,
) -> TaskActivationResult:
    """Execute the exact Phase-35 activation semantics inside an owned transaction.

    This helper never opens, commits, or rolls back a transaction. Callers must
    already own the write transaction. Keeping the canonical Task transition and
    event append here lets preparation infrastructure compose Phase-35 activation
    atomically with its own durable checkpoint without duplicating authority.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be a sqlite3.Connection")
    if not isinstance(project_id, str) or not project_id:
        raise TaskActivationError("project_id must be a non-empty string")
    if not isinstance(task_id, str) or not validate_id(task_id, IdKind.TASK):
        raise TaskActivationError("task_id must be a valid TASK ID")
    if type(expected_revision) is not int or expected_revision < 0:
        raise TaskActivationError("expected_revision must be a non-negative integer")
    if not isinstance(now, str) or not now:
        raise TaskActivationError("activation timestamp must be non-empty text")

    row = conn.execute(
        """SELECT t.*, g.project_id
           FROM tasks t
           JOIN flows f ON f.id = t.flow_id
           JOIN goals g ON g.id = f.goal_id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    if row is None:
        raise KeyError(task_id)
    if row["project_id"] != project_id:
        raise TaskActivationError("Task does not belong to the current project")
    try:
        current_status = TaskStatus(row["status"])
    except ValueError as exc:
        raise TaskActivationError("Task has invalid canonical status") from exc
    actual_revision = int(row["revision"])
    if actual_revision != expected_revision:
        raise StaleRevision(
            f"task {task_id} revision {actual_revision} != expected {expected_revision}"
        )
    if current_status is not TaskStatus.QUEUED:
        raise TaskActivationError(
            "dependency-ready activation requires canonical QUEUED Task"
        )

    try:
        readiness = resolve_task_dependency_readiness_connection(conn, task_id)
    except TaskReadinessError as exc:
        raise TaskActivationError("Task dependency readiness is invalid") from exc
    if readiness.task_status is not TaskStatus.QUEUED:
        raise TaskActivationError(
            "dependency readiness snapshot does not bind the QUEUED Task"
        )
    if readiness.status is not DependencyReadinessStatus.READY:
        raise TaskActivationError(
            f"Task dependency readiness is {readiness.status.value}, not READY"
        )

    previous_hash = task_routing_hash(row)
    ensure_transition(current_status, TaskStatus.READY, TASK_TRANSITIONS)
    new_revision = actual_revision + 1
    cursor = conn.execute(
        """UPDATE tasks
           SET status = ?, revision = ?, updated_at = ?
           WHERE id = ? AND status = ? AND revision = ?""",
        (
            TaskStatus.READY.value,
            new_revision,
            now,
            task_id,
            TaskStatus.QUEUED.value,
            actual_revision,
        ),
    )
    if cursor.rowcount != 1:
        raise StaleRevision(f"task {task_id} changed concurrently")

    updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if updated is None:
        raise TaskActivationError("Task disappeared during activation")
    new_hash = task_routing_hash(updated)
    if new_hash == previous_hash:
        raise TaskActivationError(
            "Task activation did not change revision-bound content hash"
        )

    runtime.store._append_event(
        conn,
        "TASK",
        task_id,
        "TASK_STATUS_CHANGED",
        TaskStatus.QUEUED.value,
        TaskStatus.READY.value,
        new_revision,
        "SYSTEM",
        None,
        {
            "reason": "DEPENDENCY_READY_ACTIVATION",
            "dependency_count": readiness.dependency_count,
            "satisfied_dependency_count": readiness.satisfied_dependency_count,
            "previous_task_content_hash": previous_hash,
            "new_task_content_hash": new_hash,
        },
        now,
    )

    return TaskActivationResult(
        task_id=task_id,
        previous_revision=actual_revision,
        new_revision=new_revision,
        previous_task_content_hash=previous_hash,
        new_task_content_hash=new_hash,
        dependency_count=readiness.dependency_count,
        satisfied_dependency_count=readiness.satisfied_dependency_count,
    )


def activate_dependency_ready_task(
    runtime: OriginForgeRuntime,
    task_id: str,
    expected_revision: int,
) -> TaskActivationResult:
    """Atomically activate one dependency-ready QUEUED Task.

    The caller supplies no readiness/status/hash authority. Dependency readiness
    and both Task hashes are derived from canonical state inside the same write
    transaction. The only mutation is QUEUED -> READY plus one state event.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(task_id, str) or not validate_id(task_id, IdKind.TASK):
        raise TaskActivationError("task_id must be a valid TASK ID")
    if type(expected_revision) is not int or expected_revision < 0:
        raise TaskActivationError("expected_revision must be a non-negative integer")

    project_id = runtime.project_id()
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _activate_dependency_ready_task_connection(
            runtime,
            conn,
            project_id,
            task_id,
            expected_revision,
            now,
        )
