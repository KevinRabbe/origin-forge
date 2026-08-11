from __future__ import annotations

from typing import Any

from .production_read_guard import production_read_connection
from .runtime import OriginForgeRuntime


_MAX_READ_LIMIT = 100_000


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_READ_LIMIT:
        raise ValueError(f"production runtime read limit must be 1..{_MAX_READ_LIMIT}")
    return value


def _row(row) -> dict[str, Any]:
    return dict(row)


class ProductionRuntimeReadService:
    """Bounded runtime-state inspection without store open/migrate side effects."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    def project_id(self) -> str:
        with production_read_connection(self.runtime) as conn:
            row = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?",
                (str(self.runtime.project_root),),
            ).fetchone()
        if row is None:
            raise KeyError(str(self.runtime.project_root))
        return str(row["id"])

    def list_goals(self, *, limit: int) -> tuple[dict[str, Any], ...]:
        limit = _limit(limit)
        with production_read_connection(self.runtime) as conn:
            rows = conn.execute(
                """SELECT * FROM goals
                   WHERE project_id = (SELECT id FROM projects WHERE root_path = ?)
                   ORDER BY created_at, rowid LIMIT ?""",
                (str(self.runtime.project_root), limit),
            ).fetchall()
        return tuple(_row(row) for row in rows)

    def list_flows(self, *, limit: int) -> tuple[dict[str, Any], ...]:
        limit = _limit(limit)
        with production_read_connection(self.runtime) as conn:
            rows = conn.execute(
                """SELECT f.* FROM flows f
                   JOIN goals g ON g.id = f.goal_id
                   JOIN projects p ON p.id = g.project_id
                   WHERE p.root_path = ?
                   ORDER BY f.created_at, f.rowid LIMIT ?""",
                (str(self.runtime.project_root), limit),
            ).fetchall()
        return tuple(_row(row) for row in rows)

    def list_tasks(self, *, limit: int) -> tuple[dict[str, Any], ...]:
        limit = _limit(limit)
        with production_read_connection(self.runtime) as conn:
            rows = conn.execute(
                """SELECT t.* FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   JOIN projects p ON p.id = g.project_id
                   WHERE p.root_path = ?
                   ORDER BY t.created_at, t.rowid LIMIT ?""",
                (str(self.runtime.project_root), limit),
            ).fetchall()
        return tuple(_row(row) for row in rows)

    def list_runs(self, *, limit: int) -> tuple[dict[str, Any], ...]:
        limit = _limit(limit)
        with production_read_connection(self.runtime) as conn:
            rows = conn.execute(
                """SELECT r.* FROM runs r
                   JOIN tasks t ON t.id = r.task_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   JOIN projects p ON p.id = g.project_id
                   WHERE p.root_path = ?
                   ORDER BY r.started_at, r.rowid LIMIT ?""",
                (str(self.runtime.project_root), limit),
            ).fetchall()
        return tuple(_row(row) for row in rows)

    def list_task_verifications(
        self, task_id: str, *, limit: int
    ) -> tuple[dict[str, Any], ...]:
        limit = _limit(limit)
        with production_read_connection(self.runtime) as conn:
            rows = conn.execute(
                """SELECT v.* FROM verifications v
                   JOIN tasks t ON t.id = v.target_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   JOIN projects p ON p.id = g.project_id
                   WHERE v.target_type = 'TASK' AND v.target_id = ? AND p.root_path = ?
                   ORDER BY v.created_at, v.rowid LIMIT ?""",
                (task_id, str(self.runtime.project_root), limit),
            ).fetchall()
        return tuple(_row(row) for row in rows)

    def count_goals(self) -> int:
        return self._count(
            """SELECT COUNT(*) FROM goals
               WHERE project_id = (SELECT id FROM projects WHERE root_path = ?)"""
        )

    def count_flows(self) -> int:
        return self._count(
            """SELECT COUNT(*) FROM flows f
               JOIN goals g ON g.id = f.goal_id
               JOIN projects p ON p.id = g.project_id
               WHERE p.root_path = ?"""
        )

    def count_tasks(self) -> int:
        return self._count(
            """SELECT COUNT(*) FROM tasks t
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               JOIN projects p ON p.id = g.project_id
               WHERE p.root_path = ?"""
        )

    def count_runs(self) -> int:
        return self._count(
            """SELECT COUNT(*) FROM runs r
               JOIN tasks t ON t.id = r.task_id
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               JOIN projects p ON p.id = g.project_id
               WHERE p.root_path = ?"""
        )

    def count_task_verifications(self) -> int:
        return self._count(
            """SELECT COUNT(*) FROM verifications v
               JOIN tasks t ON t.id = v.target_id
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               JOIN projects p ON p.id = g.project_id
               WHERE v.target_type = 'TASK' AND p.root_path = ?"""
        )

    def _count(self, sql: str) -> int:
        with production_read_connection(self.runtime) as conn:
            return int(conn.execute(sql, (str(self.runtime.project_root),)).fetchone()[0])
