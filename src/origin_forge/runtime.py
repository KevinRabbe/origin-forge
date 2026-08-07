from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .config import ensure_config, load_config
from .runs import create_run, finish_run, get_run, reconcile_interrupted
from .service import OriginForgeStore
from .state import FlowStatus, RunStatus, TaskStatus


class RuntimeInvariantError(RuntimeError):
    pass


def _row_dict(row) -> dict[str, Any]:
    return dict(row)


class OriginForgeRuntime:
    """Application-service boundary above durable persistence.

    The Store owns database mechanics. Runtime owns cross-record invariants and
    is the surface the CLI and future Manager should use.
    """

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

    def list_goals(self) -> list[dict[str, Any]]:
        project_id = self.project_id()
        with self.store.session() as conn:
            return [
                _row_dict(row)
                for row in conn.execute(
                    "SELECT * FROM goals WHERE project_id = ? ORDER BY created_at, rowid",
                    (project_id,),
                )
            ]

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

    def create_flow(self, goal_id: str, *, controller: str | None = None) -> str:
        self.get_goal(goal_id)
        return self.store.create_flow(goal_id, controller=controller)

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

    def recovery_findings(self):
        return self.store.recovery_findings()

    def recover(self):
        return reconcile_interrupted(self.store)

    def status(self) -> dict[str, Any]:
        result = self.store.status_summary()
        config = load_config(self.project_root)
        result["config"] = {
            "version": config.version,
            "policy_profile": config.policy_profile,
            "max_strategy_retries": config.max_strategy_retries,
            "max_verification_failures": config.max_verification_failures,
        }
        return result
