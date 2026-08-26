from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .config import ensure_config, load_config
from .goals import transition_goal
from .runs import create_run, finish_run, get_run, reconcile_interrupted
from .service import OriginForgeStore
from .state import FlowStatus, GoalStatus, RunStatus, TaskStatus


_MAX_READ_LIMIT = 100_000


class RuntimeInvariantError(RuntimeError):
    pass


def _row_dict(row) -> dict[str, Any]:
    return dict(row)


def _read_limit(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= _MAX_READ_LIMIT:
        raise ValueError(f"read limit must be an integer from 1 to {_MAX_READ_LIMIT}")
    return value


def _with_limit(sql: str, params: list[Any], limit: int | None) -> tuple[str, list[Any]]:
    normalized = _read_limit(limit)
    if normalized is not None:
        sql += " LIMIT ?"
        params.append(normalized)
    return sql, params


class OriginForgeRuntime:
    """Application-service boundary above durable persistence."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.state_dir = self.project_root / ".origin-forge"
        self.store = OriginForgeStore(self.state_dir / "project.db")

    def initialize(self, name: str | None = None) -> dict[str, Any]:
        ensure_config(self.project_root)
        config = load_config(self.project_root)
        project_id = self.store.initialize_project(
            name or self.project_root.name, self.project_root
        )
        return {
            "project_id": project_id,
            "database": str(self.store.db_path),
            "config": str(self.state_dir / "config.toml"),
            "config_version": config.version,
        }

    def project_id(self) -> str:
        root = str(self.project_root)
        with self.store.session() as conn:
            row = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?", (root,)
            ).fetchone()
            if row is None:
                raise RuntimeInvariantError(
                    "project is not initialized; run `origin-forge init` first"
                )
            return row["id"]

    def create_goal(
        self,
        objective: str,
        *,
        success_criteria: Iterable[str] = (),
        constraints: Iterable[str] = (),
        priority: int = 0,
    ) -> str:
        return self.store.create_goal(
            self.project_id(),
            objective,
            success_criteria=success_criteria,
            constraints=constraints,
            priority=priority,
        )

    def list_goals(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        project_id = self.project_id()
        sql, params = _with_limit(
            "SELECT * FROM goals WHERE project_id = ? ORDER BY created_at, rowid",
            [project_id],
            limit,
        )
        with self.store.session() as conn:
            return [_row_dict(row) for row in conn.execute(sql, params)]

    def count_goals(self) -> int:
        project_id = self.project_id()
        with self.store.session() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM goals WHERE project_id = ?", (project_id,)
                ).fetchone()[0]
            )

    def get_goal(self, goal_id: str) -> dict[str, Any]:
        project_id = self.project_id()
        with self.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                (goal_id, project_id),
            ).fetchone()
            if row is None:
                raise KeyError(goal_id)
            return _row_dict(row)

    def transition_goal(
        self, goal_id: str, target: GoalStatus, *, expected_revision: int
    ) -> int:
        self.get_goal(goal_id)
        if target == GoalStatus.SUCCEEDED:
            with self.store.session() as conn:
                flows = conn.execute(
                    "SELECT id, status FROM flows WHERE goal_id = ? ORDER BY created_at, rowid",
                    (goal_id,),
                ).fetchall()
            if not flows:
                raise RuntimeInvariantError("goal cannot succeed without at least one flow")
            incomplete = [
                row
                for row in flows
                if row["status"]
                not in (FlowStatus.SUCCEEDED.value, FlowStatus.CANCELLED.value)
            ]
            if incomplete:
                details = ", ".join(
                    f"{row['id']}={row['status']}" for row in incomplete
                )
                raise RuntimeInvariantError(
                    f"goal cannot succeed while flows are incomplete: {details}"
                )
        return transition_goal(
            self.store, goal_id, target, expected_revision=expected_revision
        )

    def create_flow(self, goal_id: str, *, controller: str | None = None) -> str:
        self.get_goal(goal_id)
        return self.store.create_flow(goal_id, controller=controller)

    def list_flows(
        self, goal_id: str | None = None, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        project_id = self.project_id()
        params: list[Any] = [project_id]
        sql = """SELECT f.* FROM flows f
                 JOIN goals g ON g.id = f.goal_id
                 WHERE g.project_id = ?"""
        if goal_id is not None:
            self.get_goal(goal_id)
            sql += " AND f.goal_id = ?"
            params.append(goal_id)
        sql += " ORDER BY f.created_at, f.rowid"
        sql, params = _with_limit(sql, params, limit)
        with self.store.session() as conn:
            return [_row_dict(row) for row in conn.execute(sql, params)]

    def count_flows(self, goal_id: str | None = None) -> int:
        project_id = self.project_id()
        params: list[Any] = [project_id]
        sql = """SELECT COUNT(*) FROM flows f
                 JOIN goals g ON g.id = f.goal_id
                 WHERE g.project_id = ?"""
        if goal_id is not None:
            self.get_goal(goal_id)
            sql += " AND f.goal_id = ?"
            params.append(goal_id)
        with self.store.session() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def get_flow(self, flow_id: str) -> dict[str, Any]:
        project_id = self.project_id()
        row = self.store.get_flow(flow_id)
        with self.store.session() as conn:
            owner = conn.execute(
                """SELECT g.project_id FROM flows f
                   JOIN goals g ON g.id = f.goal_id
                   WHERE f.id = ?""",
                (flow_id,),
            ).fetchone()
            if owner is None or owner["project_id"] != project_id:
                raise KeyError(flow_id)
        return _row_dict(row)

    def transition_flow(
        self, flow_id: str, target: FlowStatus, *, expected_revision: int
    ) -> int:
        self.get_flow(flow_id)
        if target == FlowStatus.SUCCEEDED:
            with self.store.session() as conn:
                incomplete = conn.execute(
                    """SELECT id, status FROM tasks
                       WHERE flow_id = ? AND status NOT IN (?, ?)
                       ORDER BY created_at, rowid""",
                    (
                        flow_id,
                        TaskStatus.SUCCEEDED.value,
                        TaskStatus.CANCELLED.value,
                    ),
                ).fetchall()
            if incomplete:
                details = ", ".join(
                    f"{row['id']}={row['status']}" for row in incomplete
                )
                raise RuntimeInvariantError(
                    f"flow cannot succeed while tasks are incomplete: {details}"
                )
        return self.store.transition_flow(
            flow_id, target, expected_revision=expected_revision
        )

    def create_task(
        self,
        flow_id: str,
        objective: str,
        *,
        parent_task_id: str | None = None,
        acceptance_criteria: Iterable[str] = (),
        constraints: Iterable[str] = (),
        required_capabilities: Iterable[str] = (),
        priority: int = 0,
    ) -> str:
        self.get_flow(flow_id)
        if parent_task_id is not None:
            parent = self.get_task(parent_task_id)
            if parent["flow_id"] != flow_id:
                raise RuntimeInvariantError("parent task must belong to the same flow")
        return self.store.create_task(
            flow_id,
            objective,
            parent_task_id=parent_task_id,
            acceptance_criteria=acceptance_criteria,
            constraints=constraints,
            required_capabilities=required_capabilities,
            priority=priority,
        )

    def list_tasks(
        self, flow_id: str | None = None, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        project_id = self.project_id()
        params: list[Any] = [project_id]
        sql = """SELECT t.* FROM tasks t
                 JOIN flows f ON f.id = t.flow_id
                 JOIN goals g ON g.id = f.goal_id
                 WHERE g.project_id = ?"""
        if flow_id is not None:
            self.get_flow(flow_id)
            sql += " AND t.flow_id = ?"
            params.append(flow_id)
        sql += " ORDER BY t.created_at, t.rowid"
        sql, params = _with_limit(sql, params, limit)
        with self.store.session() as conn:
            return [_row_dict(row) for row in conn.execute(sql, params)]

    def count_tasks(self, flow_id: str | None = None) -> int:
        project_id = self.project_id()
        params: list[Any] = [project_id]
        sql = """SELECT COUNT(*) FROM tasks t
                 JOIN flows f ON f.id = t.flow_id
                 JOIN goals g ON g.id = f.goal_id
                 WHERE g.project_id = ?"""
        if flow_id is not None:
            self.get_flow(flow_id)
            sql += " AND t.flow_id = ?"
            params.append(flow_id)
        with self.store.session() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def get_task(self, task_id: str) -> dict[str, Any]:
        project_id = self.project_id()
        row = self.store.get_task(task_id)
        with self.store.session() as conn:
            owner = conn.execute(
                """SELECT g.project_id FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE t.id = ?""",
                (task_id,),
            ).fetchone()
            if owner is None or owner["project_id"] != project_id:
                raise KeyError(task_id)
        return _row_dict(row)

    def transition_task(
        self, task_id: str, target: TaskStatus, *, expected_revision: int
    ) -> int:
        self.get_task(task_id)
        if target == TaskStatus.SUCCEEDED:
            with self.store.session() as conn:
                incomplete = conn.execute(
                    """SELECT id, status FROM tasks
                       WHERE parent_task_id = ? AND status NOT IN (?, ?)
                       ORDER BY created_at, rowid""",
                    (
                        task_id,
                        TaskStatus.SUCCEEDED.value,
                        TaskStatus.CANCELLED.value,
                    ),
                ).fetchall()
            if incomplete:
                details = ", ".join(
                    f"{row['id']}={row['status']}" for row in incomplete
                )
                raise RuntimeInvariantError(
                    f"task cannot succeed while child tasks are incomplete: {details}"
                )
        return self.store.transition_task(
            task_id, target, expected_revision=expected_revision
        )

    def start_run(
        self,
        task_id: str,
        *,
        role: str,
        model_profile: str | None = None,
    ) -> str:
        self.get_task(task_id)
        return create_run(
            self.store,
            task_id,
            role=role,
            model_profile=model_profile,
        )

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        failure_reason: str | None = None,
    ) -> None:
        self.get_run(run_id)
        finish_run(self.store, run_id, status, failure_reason=failure_reason)

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = get_run(self.store, run_id)
        if row["task_id"] is not None:
            self.get_task(row["task_id"])
        return _row_dict(row)

    def list_runs(
        self, task_id: str | None = None, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        project_id = self.project_id()
        params: list[Any] = [project_id]
        sql = """SELECT r.* FROM runs r
                 JOIN tasks t ON t.id = r.task_id
                 JOIN flows f ON f.id = t.flow_id
                 JOIN goals g ON g.id = f.goal_id
                 WHERE g.project_id = ?"""
        if task_id is not None:
            self.get_task(task_id)
            sql += " AND r.task_id = ?"
            params.append(task_id)
        sql += " ORDER BY r.started_at, r.rowid"
        sql, params = _with_limit(sql, params, limit)
        with self.store.session() as conn:
            return [_row_dict(row) for row in conn.execute(sql, params)]

    def count_runs(self, task_id: str | None = None) -> int:
        project_id = self.project_id()
        params: list[Any] = [project_id]
        sql = """SELECT COUNT(*) FROM runs r
                 JOIN tasks t ON t.id = r.task_id
                 JOIN flows f ON f.id = t.flow_id
                 JOIN goals g ON g.id = f.goal_id
                 WHERE g.project_id = ?"""
        if task_id is not None:
            self.get_task(task_id)
            sql += " AND r.task_id = ?"
            params.append(task_id)
        with self.store.session() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def record_verification(
        self,
        target_type: str,
        target_id: str,
        *,
        verification_type: str,
        verifier: str,
        status: str,
        evidence: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        kind = target_type.upper()
        if kind == "GOAL":
            self.get_goal(target_id)
        elif kind == "FLOW":
            self.get_flow(target_id)
        elif kind == "TASK":
            self.get_task(target_id)
        elif kind == "RUN":
            self.get_run(target_id)
        else:
            raise ValueError(f"unsupported Phase 1 verification target: {target_type}")
        if run_id is not None:
            self.get_run(run_id)
        return self.store.record_verification(
            target_type=kind,
            target_id=target_id,
            verification_type=verification_type,
            verifier=verifier,
            status=status,
            evidence=evidence,
            metrics=metrics,
            run_id=run_id,
        )

    def list_verifications(
        self, target_type: str, target_id: str, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        kind = target_type.upper()
        if kind == "GOAL":
            self.get_goal(target_id)
        elif kind == "FLOW":
            self.get_flow(target_id)
        elif kind == "TASK":
            self.get_task(target_id)
        elif kind == "RUN":
            self.get_run(target_id)
        else:
            raise ValueError(f"unsupported Phase 1 verification target: {target_type}")
        sql, params = _with_limit(
            """SELECT * FROM verifications
               WHERE target_type = ? AND target_id = ?
               ORDER BY created_at, rowid""",
            [kind, target_id],
            limit,
        )
        with self.store.session() as conn:
            return [_row_dict(row) for row in conn.execute(sql, params)]

    def count_task_verifications(self) -> int:
        project_id = self.project_id()
        with self.store.session() as conn:
            return int(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications v
                       JOIN tasks t ON t.id = v.target_id
                       JOIN flows f ON f.id = t.flow_id
                       JOIN goals g ON g.id = f.goal_id
                       WHERE v.target_type = 'TASK' AND g.project_id = ?""",
                    (project_id,),
                ).fetchone()[0]
            )

    def recovery_findings(self):
        return self.store.recovery_findings()

    def recover(self):
        return reconcile_interrupted(self.store)

    def status(self) -> dict[str, Any]:
        project_id = self.project_id()
        result = self.store.status_summary()
        config = load_config(self.project_root)
        with self.store.session() as conn:
            result["goals"] = {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM goals WHERE project_id = ? GROUP BY status",
                    (project_id,),
                )
            }
            result["runs"] = {
                row["status"]: row["count"]
                for row in conn.execute(
                    """SELECT r.status, COUNT(*) AS count FROM runs r
                       JOIN tasks t ON t.id = r.task_id
                       JOIN flows f ON f.id = t.flow_id
                       JOIN goals g ON g.id = f.goal_id
                       WHERE g.project_id = ? GROUP BY r.status""",
                    (project_id,),
                )
            }
        result["config"] = {
            "version": config.version,
            "policy_profile": config.policy_profile,
            "max_strategy_retries": config.max_strategy_retries,
            "max_verification_failures": config.max_verification_failures,
            "approved_build_commands": list(config.approved_build_commands),
            "approved_test_commands": list(config.approved_test_commands),
            "external_tools": dict(config.external_tools.paths),
        }
        return result
