from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .db import connect, migrate
from .ids import IdKind, new_id
from .state import (
    FLOW_TRANSITIONS,
    TASK_TRANSITIONS,
    FlowStatus,
    TaskStatus,
    ensure_transition,
)


class StaleRevision(RuntimeError):
    pass


class VerificationRequired(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class RecoveryFinding:
    aggregate_type: str
    aggregate_id: str
    status: str
    reason: str


class OriginForgeStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def open(self) -> sqlite3.Connection:
        connection = connect(self.db_path)
        migrate(connection, utc_now())
        return connection

    @contextmanager
    def session(self):
        connection = self.open()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize_project(self, name: str, root_path: str | Path) -> str:
        root = str(Path(root_path).resolve())
        now = utc_now()
        with self.session() as conn:
            existing = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?", (root,)
            ).fetchone()
            if existing:
                return existing["id"]
            project_id = new_id(IdKind.PROJECT)
            conn.execute(
                "INSERT INTO projects(id, name, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (project_id, name, root, now, now),
            )
            self._append_event(
                conn,
                "PROJECT",
                project_id,
                "PROJECT_CREATED",
                None,
                "ACTIVE",
                0,
                "SYSTEM",
                None,
                {"name": name, "root_path": root},
                now,
            )
            return project_id

    def create_goal(
        self,
        project_id: str,
        objective: str,
        *,
        success_criteria: Iterable[str] = (),
        constraints: Iterable[str] = (),
        budgets: dict[str, Any] | None = None,
        priority: int = 0,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> str:
        now = utc_now()
        goal_id = new_id(IdKind.GOAL)
        with self.session() as conn:
            conn.execute(
                """INSERT INTO goals(
                       id, project_id, objective, success_criteria_json,
                       constraints_json, budgets_json, priority, status,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)""",
                (
                    goal_id,
                    project_id,
                    objective,
                    _json(list(success_criteria)),
                    _json(list(constraints)),
                    _json(budgets or {}),
                    priority,
                    now,
                    now,
                ),
            )
            self._append_event(
                conn,
                "GOAL",
                goal_id,
                "GOAL_CREATED",
                None,
                "OPEN",
                0,
                actor_type,
                actor_id,
                {"objective": objective},
                now,
            )
        return goal_id

    def create_flow(
        self,
        goal_id: str,
        *,
        controller: str | None = None,
        state: dict[str, Any] | None = None,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
    ) -> str:
        flow_id = new_id(IdKind.FLOW)
        now = utc_now()
        with self.session() as conn:
            conn.execute(
                """INSERT INTO flows(
                       id, goal_id, status, revision, controller, state_json,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, 0, ?, ?, ?, ?)""",
                (
                    flow_id,
                    goal_id,
                    FlowStatus.QUEUED.value,
                    controller,
                    _json(state or {}),
                    now,
                    now,
                ),
            )
            self._append_event(
                conn,
                "FLOW",
                flow_id,
                "FLOW_CREATED",
                None,
                FlowStatus.QUEUED.value,
                0,
                actor_type,
                actor_id,
                {},
                now,
            )
        return flow_id

    def create_task(
        self,
        flow_id: str,
        objective: str,
        *,
        parent_task_id: str | None = None,
        acceptance_criteria: Iterable[str] = (),
        constraints: Iterable[str] = (),
        required_capabilities: Iterable[str] = (),
        budget: dict[str, Any] | None = None,
        priority: int = 0,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
    ) -> str:
        task_id = new_id(IdKind.TASK)
        now = utc_now()
        with self.session() as conn:
            conn.execute(
                """INSERT INTO tasks(
                       id, flow_id, parent_task_id, objective,
                       acceptance_criteria_json, constraints_json,
                       required_capabilities_json, budget_json, priority,
                       status, revision, attempt_count, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                (
                    task_id,
                    flow_id,
                    parent_task_id,
                    objective,
                    _json(list(acceptance_criteria)),
                    _json(list(constraints)),
                    _json(list(required_capabilities)),
                    _json(budget or {}),
                    priority,
                    TaskStatus.QUEUED.value,
                    now,
                    now,
                ),
            )
            self._append_event(
                conn,
                "TASK",
                task_id,
                "TASK_CREATED",
                None,
                TaskStatus.QUEUED.value,
                0,
                actor_type,
                actor_id,
                {"objective": objective},
                now,
            )
        return task_id

    def transition_flow(
        self,
        flow_id: str,
        target: FlowStatus,
        *,
        expected_revision: int,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> int:
        now = utc_now()
        with self.session() as conn:
            row = conn.execute(
                "SELECT status, revision FROM flows WHERE id = ?", (flow_id,)
            ).fetchone()
            if row is None:
                raise KeyError(flow_id)
            current = FlowStatus(row["status"])
            actual_revision = int(row["revision"])
            if actual_revision != expected_revision:
                raise StaleRevision(
                    f"flow {flow_id} revision {actual_revision} != expected {expected_revision}"
                )
            ensure_transition(current, target, FLOW_TRANSITIONS)
            new_revision = actual_revision + 1
            cursor = conn.execute(
                """UPDATE flows
                   SET status = ?, revision = ?, blocked_reason = ?, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (
                    target.value,
                    new_revision,
                    reason if target == FlowStatus.BLOCKED else None,
                    now,
                    flow_id,
                    actual_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(f"flow {flow_id} changed concurrently")
            self._append_event(
                conn,
                "FLOW",
                flow_id,
                "FLOW_STATUS_CHANGED",
                current.value,
                target.value,
                new_revision,
                actor_type,
                actor_id,
                {"reason": reason} if reason else {},
                now,
            )
            return new_revision

    def transition_task(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        expected_revision: int,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> int:
        now = utc_now()
        with self.session() as conn:
            row = conn.execute(
                "SELECT status, revision FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row["status"])
            actual_revision = int(row["revision"])
            if actual_revision != expected_revision:
                raise StaleRevision(
                    f"task {task_id} revision {actual_revision} != expected {expected_revision}"
                )
            ensure_transition(current, target, TASK_TRANSITIONS)
            if target == TaskStatus.SUCCEEDED and not self._task_has_required_pass(
                conn, task_id
            ):
                raise VerificationRequired(
                    f"task {task_id} cannot succeed without a passing task verification"
                )
            new_revision = actual_revision + 1
            cursor = conn.execute(
                """UPDATE tasks
                   SET status = ?, revision = ?, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (target.value, new_revision, now, task_id, actual_revision),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(f"task {task_id} changed concurrently")
            self._append_event(
                conn,
                "TASK",
                task_id,
                "TASK_STATUS_CHANGED",
                current.value,
                target.value,
                new_revision,
                actor_type,
                actor_id,
                {"reason": reason} if reason else {},
                now,
            )
            return new_revision

    def record_verification(
        self,
        *,
        target_type: str,
        target_id: str,
        verification_type: str,
        verifier: str,
        status: str,
        evidence: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        run_id: str | None = None,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
    ) -> str:
        verification_id = new_id(IdKind.VERIFICATION)
        now = utc_now()
        normalized_status = status.upper()
        if normalized_status not in {
            "PASS",
            "FAIL",
            "INCONCLUSIVE",
            "SKIPPED",
            "BLOCKED",
        }:
            raise ValueError(f"invalid verification status: {status}")
        with self.session() as conn:
            conn.execute(
                """INSERT INTO verifications(
                       id, target_type, target_id, verification_type, verifier,
                       status, evidence_json, metrics_json, run_id, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    verification_id,
                    target_type.upper(),
                    target_id,
                    verification_type,
                    verifier,
                    normalized_status,
                    _json(evidence or {}),
                    _json(metrics or {}),
                    run_id,
                    now,
                ),
            )
            self._append_event(
                conn,
                target_type.upper(),
                target_id,
                "VERIFICATION_RECORDED",
                None,
                normalized_status,
                None,
                actor_type,
                actor_id,
                {
                    "verification_id": verification_id,
                    "verification_type": verification_type,
                },
                now,
            )
        return verification_id

    def get_flow(self, flow_id: str) -> sqlite3.Row:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM flows WHERE id = ?", (flow_id,)
            ).fetchone()
            if row is None:
                raise KeyError(flow_id)
            return row

    def get_task(self, task_id: str) -> sqlite3.Row:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            return row

    def event_history(
        self, aggregate_type: str, aggregate_id: str
    ) -> list[sqlite3.Row]:
        with self.session() as conn:
            return list(
                conn.execute(
                    """SELECT * FROM state_events
                       WHERE aggregate_type = ? AND aggregate_id = ?
                       ORDER BY created_at, rowid""",
                    (aggregate_type.upper(), aggregate_id),
                ).fetchall()
            )

    def recovery_findings(self) -> list[RecoveryFinding]:
        findings: list[RecoveryFinding] = []
        with self.session() as conn:
            for row in conn.execute(
                "SELECT id, status FROM flows WHERE status = ?",
                (FlowStatus.RUNNING.value,),
            ):
                findings.append(
                    RecoveryFinding(
                        "FLOW",
                        row["id"],
                        row["status"],
                        "flow was RUNNING at startup",
                    )
                )
            for row in conn.execute(
                "SELECT id, status FROM tasks WHERE status = ?",
                (TaskStatus.RUNNING.value,),
            ):
                findings.append(
                    RecoveryFinding(
                        "TASK",
                        row["id"],
                        row["status"],
                        "task was RUNNING at startup",
                    )
                )
            for row in conn.execute(
                "SELECT id, status FROM runs WHERE status = 'RUNNING'"
            ):
                findings.append(
                    RecoveryFinding(
                        "RUN",
                        row["id"],
                        row["status"],
                        "run was RUNNING at startup",
                    )
                )
        return findings

    def status_summary(self) -> dict[str, Any]:
        with self.session() as conn:
            project_count = conn.execute(
                "SELECT COUNT(*) FROM projects"
            ).fetchone()[0]
            flow_counts = {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM flows GROUP BY status"
                )
            }
            task_counts = {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
                )
            }
            schema_version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        return {
            "schema_version": schema_version,
            "projects": project_count,
            "flows": flow_counts,
            "tasks": task_counts,
            "recovery_findings": len(self.recovery_findings()),
        }

    @staticmethod
    def _task_has_required_pass(conn: sqlite3.Connection, task_id: str) -> bool:
        row = conn.execute(
            """SELECT 1 FROM verifications
               WHERE target_type = 'TASK' AND target_id = ? AND status = 'PASS'
               LIMIT 1""",
            (task_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        old_state: str | None,
        new_state: str | None,
        revision: int | None,
        actor_type: str,
        actor_id: str | None,
        metadata: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """INSERT INTO state_events(
                   id, aggregate_type, aggregate_id, event_type, old_state,
                   new_state, revision, actor_type, actor_id, metadata_json,
                   created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id(IdKind.EVENT),
                aggregate_type,
                aggregate_id,
                event_type,
                old_state,
                new_state,
                revision,
                actor_type,
                actor_id,
                _json(metadata),
                created_at,
            ),
        )
