from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .runtime import OriginForgeRuntime
from .runtime_observation_models import content_hash


_MAX_TEXT_CHARS = 4096


class ProductionInterfaceSnapshotError(ValueError):
    pass


def _bounded_text(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= _MAX_TEXT_CHARS:
        return value, False
    return value[:_MAX_TEXT_CHARS], True


def _limit_rows(rows: Iterable[dict[str, Any]], limit: int) -> tuple[tuple[dict[str, Any], ...], bool]:
    values = tuple(rows)
    if type(limit) is not int or not 1 <= limit <= 10_000:
        raise ProductionInterfaceSnapshotError("interface section limit must be 1..10000")
    if len(values) <= limit:
        return values, False
    return values[:limit], True


def _goal_projection(row: dict[str, Any]) -> dict[str, object]:
    objective, truncated = _bounded_text(row.get("objective"))
    return {
        "id": row["id"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "priority": int(row["priority"]),
        "objective": objective,
        "objective_truncated": truncated,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _flow_projection(row: dict[str, Any]) -> dict[str, object]:
    controller, controller_truncated = _bounded_text(row.get("controller"))
    blocked_reason, blocked_truncated = _bounded_text(row.get("blocked_reason"))
    return {
        "id": row["id"],
        "goal_id": row["goal_id"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "controller": controller,
        "controller_truncated": controller_truncated,
        "blocked_reason": blocked_reason,
        "blocked_reason_truncated": blocked_truncated,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_projection(row: dict[str, Any]) -> dict[str, object]:
    objective, truncated = _bounded_text(row.get("objective"))
    return {
        "id": row["id"],
        "flow_id": row["flow_id"],
        "parent_task_id": row["parent_task_id"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "attempt_count": int(row["attempt_count"]),
        "priority": int(row["priority"]),
        "objective": objective,
        "objective_truncated": truncated,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _run_projection(row: dict[str, Any]) -> dict[str, object]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "role": row["role"],
        "model_profile": row["model_profile"],
        "model_hash": row["model_hash"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "input_token_count": row["input_token_count"],
        "output_token_count": row["output_token_count"],
    }


def _verification_projection(row: dict[str, Any]) -> dict[str, object]:
    verifier, verifier_truncated = _bounded_text(row.get("verifier"))
    verification_type, type_truncated = _bounded_text(row.get("verification_type"))
    return {
        "id": row["id"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "verification_type": verification_type,
        "verification_type_truncated": type_truncated,
        "verifier": verifier,
        "verifier_truncated": verifier_truncated,
        "status": row["status"],
        "run_id": row["run_id"],
        "created_at": row["created_at"],
    }


@dataclass(frozen=True)
class ProductionInterfaceSnapshot:
    project_id: str
    goals: tuple[dict[str, object], ...]
    flows: tuple[dict[str, object], ...]
    tasks: tuple[dict[str, object], ...]
    runs: tuple[dict[str, object], ...]
    task_verifications: tuple[dict[str, object], ...]
    total_counts: dict[str, int]
    truncated: dict[str, bool]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "project_id": self.project_id,
            "goals": list(self.goals),
            "flows": list(self.flows),
            "tasks": list(self.tasks),
            "runs": list(self.runs),
            "task_verifications": list(self.task_verifications),
            "total_counts": dict(sorted(self.total_counts.items())),
            "truncated": dict(sorted(self.truncated.items())),
            "authority": {
                "read_only": True,
                "task_mutation": False,
                "model_execution": False,
                "tool_execution": False,
                "artifact_adoption": False,
                "provenance_signing": False,
                "merge_release": False,
            },
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


def build_production_interface_snapshot(
    runtime: OriginForgeRuntime,
    *,
    max_goals: int = 128,
    max_flows: int = 256,
    max_tasks: int = 512,
    max_runs: int = 512,
    max_verifications: int = 1024,
) -> ProductionInterfaceSnapshot:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    raw_goals = tuple(runtime.list_goals())
    raw_flows = tuple(runtime.list_flows())
    raw_tasks = tuple(runtime.list_tasks())
    raw_runs = tuple(runtime.list_runs())

    goals, goals_truncated = _limit_rows(raw_goals, max_goals)
    flows, flows_truncated = _limit_rows(raw_flows, max_flows)
    tasks, tasks_truncated = _limit_rows(raw_tasks, max_tasks)
    runs, runs_truncated = _limit_rows(raw_runs, max_runs)

    verification_rows: list[dict[str, Any]] = []
    verification_truncated = False
    for task in tasks:
        remaining = max_verifications - len(verification_rows)
        if remaining <= 0:
            verification_truncated = True
            break
        values = runtime.list_verifications("TASK", str(task["id"]))
        if len(values) > remaining:
            verification_rows.extend(values[:remaining])
            verification_truncated = True
            break
        verification_rows.extend(values)

    return ProductionInterfaceSnapshot(
        project_id=runtime.project_id(),
        goals=tuple(_goal_projection(value) for value in goals),
        flows=tuple(_flow_projection(value) for value in flows),
        tasks=tuple(_task_projection(value) for value in tasks),
        runs=tuple(_run_projection(value) for value in runs),
        task_verifications=tuple(
            _verification_projection(value) for value in verification_rows
        ),
        total_counts={
            "goals": len(raw_goals),
            "flows": len(raw_flows),
            "tasks": len(raw_tasks),
            "runs": len(raw_runs),
            "task_verifications": len(verification_rows),
        },
        truncated={
            "goals": goals_truncated,
            "flows": flows_truncated,
            "tasks": tasks_truncated,
            "runs": runs_truncated,
            "task_verifications": verification_truncated,
        },
    )
