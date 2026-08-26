from __future__ import annotations

from typing import Any

from .lineage import OriginForgeLineage
from .production_evidence_read import ProductionEvidenceReadService
from .production_read_guard import ensure_production_runtime_readable
from .runtime import OriginForgeRuntime
from .workspaces import GitWorkspaceManager


def inspect_task_review(runtime: OriginForgeRuntime, task_id: str) -> dict[str, Any]:
    """Build one bounded, read-only review projection for a Task."""
    ensure_production_runtime_readable(runtime)
    task = runtime.get_task(task_id)
    runs = runtime.list_runs(task_id)
    verifications = runtime.list_verifications("TASK", task_id)
    workspaces = GitWorkspaceManager(runtime).list(task_id)
    run_ids = {str(row["id"]) for row in runs}
    artifacts = [
        artifact
        for artifact in ProductionEvidenceReadService(runtime).list_artifacts()
        if artifact.get("created_by_run_id") in run_ids
    ]
    if task["status"] == "QUEUED":
        next_action = "WAIT_FOR_READINESS"
    elif task["status"] == "READY":
        next_action = "ATTEMPT"
    elif task["status"] == "RUNNING":
        next_action = "INSPECT_OR_RECOVER"
    elif task["status"] == "SUCCEEDED":
        next_action = "COMPLETE"
    else:
        next_action = "INSPECT"
    return {
        "task": task,
        "runs": runs,
        "workspaces": workspaces,
        "verifications": verifications,
        "artifacts": artifacts,
        "next_action": next_action,
    }


def record_task_review_decision(
    runtime: OriginForgeRuntime,
    task_id: str,
    action: str,
    *,
    rationale: str,
) -> str:
    """Record an explicit human review decision without changing Task state."""
    if action not in {"reject", "refine", "replace"}:
        raise ValueError("review action must be reject, refine, or replace")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("review rationale must be non-empty")
    task = runtime.get_task(task_id)
    return OriginForgeLineage(runtime).create_decision(
        title=f"Task review: {action.upper()}",
        decision=action.upper(),
        context=f"task_id={task_id}; task_revision={int(task['revision'])}",
        rationale=rationale.strip(),
        goal_id=runtime.get_flow(task["flow_id"])["goal_id"],
        task_id=task_id,
    )
