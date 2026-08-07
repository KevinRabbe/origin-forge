from __future__ import annotations

import json
from typing import Any, Iterable

from .ids import IdKind, new_id
from .service import OriginForgeStore, RecoveryFinding, utc_now
from .state import FlowStatus, InvalidTransition, RunStatus, TaskStatus


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def create_run(
    store: OriginForgeStore,
    task_id: str | None,
    *,
    role: str,
    model_profile: str | None = None,
    model_hash: str | None = None,
    skills: Iterable[str] = (),
    allowed_tools: Iterable[str] = (),
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> str:
    run_id = new_id(IdKind.RUN)
    now = utc_now()
    with store.session() as conn:
        if task_id is not None:
            task = conn.execute(
                "SELECT status FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise KeyError(task_id)
            if task["status"] != TaskStatus.RUNNING.value:
                raise InvalidTransition(
                    f"run requires RUNNING task; task {task_id} is {task['status']}"
                )

        conn.execute(
            """INSERT INTO runs(
                   id, task_id, role, model_profile, model_hash, skills_json,
                   allowed_tools_json, started_at, status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                task_id,
                role,
                model_profile,
                model_hash,
                _json(list(skills)),
                _json(list(allowed_tools)),
                now,
                RunStatus.RUNNING.value,
            ),
        )
        if task_id is not None:
            conn.execute(
                """UPDATE tasks
                   SET attempt_count = attempt_count + 1,
                       assigned_run_id = ?, updated_at = ?
                   WHERE id = ?""",
                (run_id, now, task_id),
            )
        store._append_event(
            conn,
            "RUN",
            run_id,
            "RUN_STARTED",
            None,
            RunStatus.RUNNING.value,
            None,
            actor_type,
            actor_id,
            {"task_id": task_id, "role": role},
            now,
        )
    return run_id


def finish_run(
    store: OriginForgeStore,
    run_id: str,
    status: RunStatus,
    *,
    failure_reason: str | None = None,
    input_token_count: int | None = None,
    output_token_count: int | None = None,
    resource_metrics: dict[str, Any] | None = None,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> None:
    if status == RunStatus.RUNNING:
        raise InvalidTransition("cannot finish a run with RUNNING status")

    now = utc_now()
    with store.session() as conn:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        if row["status"] != RunStatus.RUNNING.value:
            raise InvalidTransition(
                f"run {run_id} is already terminal: {row['status']}"
            )

        conn.execute(
            """UPDATE runs
               SET status = ?, ended_at = ?, failure_reason = ?,
                   input_token_count = ?, output_token_count = ?,
                   resource_metrics_json = ?
               WHERE id = ? AND status = ?""",
            (
                status.value,
                now,
                failure_reason,
                input_token_count,
                output_token_count,
                _json(resource_metrics or {}),
                run_id,
                RunStatus.RUNNING.value,
            ),
        )
        store._append_event(
            conn,
            "RUN",
            run_id,
            "RUN_FINISHED",
            RunStatus.RUNNING.value,
            status.value,
            None,
            actor_type,
            actor_id,
            {"failure_reason": failure_reason} if failure_reason else {},
            now,
        )


def get_run(store: OriginForgeStore, run_id: str):
    with store.session() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row


def reconcile_interrupted(store: OriginForgeStore) -> list[RecoveryFinding]:
    """Reconcile records left RUNNING after a process interruption.

    The operation is idempotent: only currently RUNNING records are mutated.
    Runs become INTERRUPTED. Tasks and Flows become BLOCKED with revisioned
    recovery events so no work is silently treated as successful.
    """

    findings = store.recovery_findings()
    if not findings:
        return []

    now = utc_now()
    with store.session() as conn:
        for finding in findings:
            if finding.aggregate_type == "RUN":
                cursor = conn.execute(
                    """UPDATE runs
                       SET status = ?, ended_at = ?, failure_reason = ?
                       WHERE id = ? AND status = ?""",
                    (
                        RunStatus.INTERRUPTED.value,
                        now,
                        "interrupted before recovery",
                        finding.aggregate_id,
                        RunStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount:
                    store._append_event(
                        conn,
                        "RUN",
                        finding.aggregate_id,
                        "RUN_RECOVERED_AS_INTERRUPTED",
                        RunStatus.RUNNING.value,
                        RunStatus.INTERRUPTED.value,
                        None,
                        "RECOVERY",
                        None,
                        {},
                        now,
                    )

            elif finding.aggregate_type == "TASK":
                row = conn.execute(
                    "SELECT revision FROM tasks WHERE id = ? AND status = ?",
                    (finding.aggregate_id, TaskStatus.RUNNING.value),
                ).fetchone()
                if row is None:
                    continue
                old_revision = int(row["revision"])
                new_revision = old_revision + 1
                cursor = conn.execute(
                    """UPDATE tasks
                       SET status = ?, revision = ?, updated_at = ?
                       WHERE id = ? AND status = ? AND revision = ?""",
                    (
                        TaskStatus.BLOCKED.value,
                        new_revision,
                        now,
                        finding.aggregate_id,
                        TaskStatus.RUNNING.value,
                        old_revision,
                    ),
                )
                if cursor.rowcount:
                    store._append_event(
                        conn,
                        "TASK",
                        finding.aggregate_id,
                        "TASK_RECOVERED_AS_BLOCKED",
                        TaskStatus.RUNNING.value,
                        TaskStatus.BLOCKED.value,
                        new_revision,
                        "RECOVERY",
                        None,
                        {"reason": "interrupted before recovery"},
                        now,
                    )

            elif finding.aggregate_type == "FLOW":
                row = conn.execute(
                    "SELECT revision FROM flows WHERE id = ? AND status = ?",
                    (finding.aggregate_id, FlowStatus.RUNNING.value),
                ).fetchone()
                if row is None:
                    continue
                old_revision = int(row["revision"])
                new_revision = old_revision + 1
                cursor = conn.execute(
                    """UPDATE flows
                       SET status = ?, revision = ?, blocked_reason = ?, updated_at = ?
                       WHERE id = ? AND status = ? AND revision = ?""",
                    (
                        FlowStatus.BLOCKED.value,
                        new_revision,
                        "interrupted before recovery",
                        now,
                        finding.aggregate_id,
                        FlowStatus.RUNNING.value,
                        old_revision,
                    ),
                )
                if cursor.rowcount:
                    store._append_event(
                        conn,
                        "FLOW",
                        finding.aggregate_id,
                        "FLOW_RECOVERED_AS_BLOCKED",
                        FlowStatus.RUNNING.value,
                        FlowStatus.BLOCKED.value,
                        new_revision,
                        "RECOVERY",
                        None,
                        {"reason": "interrupted before recovery"},
                        now,
                    )

    return findings
