from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from .ids import IdKind, new_id
from .service import OriginForgeStore, utc_now
from .state import TaskDependencyType


class TaskDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskDependencyEdge:
    task_id: str
    required_task_id: str
    dependency_type: TaskDependencyType
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "required_task_id": self.required_task_id,
            "dependency_type": self.dependency_type.value,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class TaskDependencyGraph:
    flow_id: str
    task_ids: tuple[str, ...]
    edges: tuple[TaskDependencyEdge, ...]
    topological_task_ids: tuple[str, ...]
    max_depth: int

    def to_dict(self) -> dict[str, object]:
        return {
            "flow_id": self.flow_id,
            "task_ids": list(self.task_ids),
            "edges": [edge.to_dict() for edge in self.edges],
            "topological_task_ids": list(self.topological_task_ids),
            "max_depth": self.max_depth,
        }


def _event_metadata(value: dict[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _require_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, flow_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise KeyError(task_id)
    return row


def _would_create_cycle(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    required_task_id: str,
) -> bool:
    row = conn.execute(
        """WITH RECURSIVE requirements(task_id) AS (
               SELECT required_task_id
               FROM task_dependencies
               WHERE task_id = ?
               UNION
               SELECT td.required_task_id
               FROM task_dependencies td
               JOIN requirements r ON td.task_id = r.task_id
           )
           SELECT 1 FROM requirements WHERE task_id = ? LIMIT 1""",
        (required_task_id, task_id),
    ).fetchone()
    return row is not None


def add_task_dependency(
    store: OriginForgeStore,
    task_id: str,
    required_task_id: str,
    *,
    dependency_type: TaskDependencyType = TaskDependencyType.REQUIRES_SUCCESS,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> TaskDependencyEdge:
    if not isinstance(store, OriginForgeStore):
        raise TypeError("store must be an OriginForgeStore")
    if not isinstance(dependency_type, TaskDependencyType):
        raise TypeError("dependency_type must be a TaskDependencyType")
    if dependency_type is not TaskDependencyType.REQUIRES_SUCCESS:
        raise TaskDependencyError("unsupported task dependency type")
    if task_id == required_task_id:
        raise TaskDependencyError("task cannot depend on itself")

    now = utc_now()
    with store.session() as conn:
        task = _require_task(conn, task_id)
        required = _require_task(conn, required_task_id)
        if task["flow_id"] != required["flow_id"]:
            raise TaskDependencyError("task dependencies must belong to the same flow")
        duplicate = conn.execute(
            """SELECT 1 FROM task_dependencies
               WHERE task_id = ? AND required_task_id = ?""",
            (task_id, required_task_id),
        ).fetchone()
        if duplicate is not None:
            raise TaskDependencyError("task dependency already exists")
        if _would_create_cycle(
            conn,
            task_id=task_id,
            required_task_id=required_task_id,
        ):
            raise TaskDependencyError("task dependency would create a cycle")
        try:
            conn.execute(
                """INSERT INTO task_dependencies(
                       task_id, required_task_id, dependency_type, created_at
                   ) VALUES (?, ?, ?, ?)""",
                (task_id, required_task_id, dependency_type.value, now),
            )
        except sqlite3.IntegrityError as exc:
            raise TaskDependencyError("task dependency violates durable graph invariants") from exc

        aggregate_id = f"{task_id}|{required_task_id}"
        conn.execute(
            """INSERT INTO state_events(
                   id, aggregate_type, aggregate_id, event_type, old_state,
                   new_state, revision, actor_type, actor_id, metadata_json,
                   created_at
               ) VALUES (?, 'TASK_DEPENDENCY', ?, 'TASK_DEPENDENCY_CREATED',
                         NULL, ?, NULL, ?, ?, ?, ?)""",
            (
                new_id(IdKind.EVENT),
                aggregate_id,
                dependency_type.value,
                actor_type,
                actor_id,
                _event_metadata(
                    {
                        "task_id": task_id,
                        "required_task_id": required_task_id,
                        "dependency_type": dependency_type.value,
                    }
                ),
                now,
            ),
        )
    return TaskDependencyEdge(task_id, required_task_id, dependency_type, now)


def _rows_to_edges(rows: Iterable[sqlite3.Row]) -> tuple[TaskDependencyEdge, ...]:
    return tuple(
        TaskDependencyEdge(
            task_id=row["task_id"],
            required_task_id=row["required_task_id"],
            dependency_type=TaskDependencyType(row["dependency_type"]),
            created_at=row["created_at"],
        )
        for row in rows
    )


def list_task_dependencies(
    store: OriginForgeStore,
    task_id: str,
) -> tuple[TaskDependencyEdge, ...]:
    with store.session() as conn:
        _require_task(conn, task_id)
        rows = conn.execute(
            """SELECT task_id, required_task_id, dependency_type, created_at
               FROM task_dependencies
               WHERE task_id = ?
               ORDER BY required_task_id""",
            (task_id,),
        ).fetchall()
    return _rows_to_edges(rows)


def list_task_dependents(
    store: OriginForgeStore,
    required_task_id: str,
) -> tuple[TaskDependencyEdge, ...]:
    with store.session() as conn:
        _require_task(conn, required_task_id)
        rows = conn.execute(
            """SELECT task_id, required_task_id, dependency_type, created_at
               FROM task_dependencies
               WHERE required_task_id = ?
               ORDER BY task_id""",
            (required_task_id,),
        ).fetchall()
    return _rows_to_edges(rows)


def _topological_order(
    task_ids: tuple[str, ...],
    edges: tuple[TaskDependencyEdge, ...],
) -> tuple[tuple[str, ...], int]:
    key_set = set(task_ids)
    indegree = {task_id: 0 for task_id in task_ids}
    outgoing: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    for edge in edges:
        if edge.task_id not in key_set or edge.required_task_id not in key_set:
            raise TaskDependencyError("dependency graph references a task outside its flow")
        indegree[edge.task_id] += 1
        outgoing[edge.required_task_id].append(edge.task_id)

    ready = sorted(task_id for task_id, count in indegree.items() if count == 0)
    depth = {task_id: 1 for task_id in ready}
    order: list[str] = []
    while ready:
        task_id = ready.pop(0)
        order.append(task_id)
        for child in sorted(outgoing[task_id]):
            depth[child] = max(depth.get(child, 1), depth[task_id] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()

    if len(order) != len(task_ids):
        raise TaskDependencyError("durable task dependency graph contains a cycle")
    return tuple(order), max(depth.values(), default=0)


def flow_dependency_graph(
    store: OriginForgeStore,
    flow_id: str,
) -> TaskDependencyGraph:
    with store.session() as conn:
        flow = conn.execute("SELECT id FROM flows WHERE id = ?", (flow_id,)).fetchone()
        if flow is None:
            raise KeyError(flow_id)
        task_ids = tuple(
            row["id"]
            for row in conn.execute(
                "SELECT id FROM tasks WHERE flow_id = ? ORDER BY id",
                (flow_id,),
            ).fetchall()
        )
        rows = conn.execute(
            """SELECT td.task_id, td.required_task_id, td.dependency_type, td.created_at
               FROM task_dependencies td
               JOIN tasks t ON t.id = td.task_id
               WHERE t.flow_id = ?
               ORDER BY td.task_id, td.required_task_id""",
            (flow_id,),
        ).fetchall()
    edges = _rows_to_edges(rows)
    order, max_depth = _topological_order(task_ids, edges)
    return TaskDependencyGraph(
        flow_id=flow_id,
        task_ids=task_ids,
        edges=edges,
        topological_task_ids=order,
        max_depth=max_depth,
    )
