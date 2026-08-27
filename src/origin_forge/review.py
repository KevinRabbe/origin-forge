from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .lineage import OriginForgeLineage
from .production_evidence_read import ProductionEvidenceReadService
from .production_read_guard import ensure_production_runtime_readable
from .production_trace import inspect_task_production_trace
from .runtime import OriginForgeRuntime
from .workspaces import GitWorkspaceManager

_ACCEPT_CONTEXT = re.compile(
    r"^task_id=(?P<task_id>[^;]+); task_revision=(?P<revision>[0-9]+)$"
)


@dataclass(frozen=True)
class TaskRefinementResult:
    decision_id: str
    refined_task_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "decision_id": self.decision_id,
            "refined_task_id": self.refined_task_id,
            "authority": "human-review-refinement",
        }


@dataclass(frozen=True)
class TaskReplacementResult:
    decision_id: str
    replacement_task_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "decision_id": self.decision_id,
            "replacement_task_id": self.replacement_task_id,
            "authority": "human-review-replacement",
        }


def _has_current_accept(
    decisions: list[dict[str, Any]], task_id: str, revision: int
) -> bool:
    for decision in decisions:
        if decision.get("decision") != "ACCEPT":
            continue
        context = decision.get("context")
        if not isinstance(context, str):
            continue
        parsed = _ACCEPT_CONTEXT.fullmatch(context)
        if (
            parsed is not None
            and parsed.group("task_id") == task_id
            and int(parsed.group("revision")) == revision
        ):
            return True
    return False


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
    decisions = [
        decision
        for decision in OriginForgeLineage(runtime).list_decisions()
        if decision.get("task_id") == task_id
    ]
    if task["status"] == "QUEUED":
        next_action = "WAIT_FOR_READINESS"
    elif task["status"] == "READY":
        next_action = "ATTEMPT"
    elif task["status"] == "RUNNING":
        next_action = "INSPECT_OR_RECOVER"
    elif task["status"] == "SUCCEEDED":
        next_action = (
            "ADOPT"
            if _has_current_accept(decisions, task_id, int(task["revision"]))
            else "REVIEW_OR_ACCEPT"
        )
    else:
        next_action = "INSPECT"
    return {
        "task": task,
        "production_trace": inspect_task_production_trace(runtime, task_id),
        "runs": runs,
        "workspaces": workspaces,
        "verifications": verifications,
        "artifacts": artifacts,
        "decisions": decisions,
        "next_action": next_action,
    }


def record_task_review_decision(
    runtime: OriginForgeRuntime,
    task_id: str,
    action: str,
    *,
    rationale: str,
    expected_revision: int | None = None,
) -> str:
    """Record an explicit human review decision without changing Task state."""
    if action not in {"accept", "reject", "refine", "replace"}:
        raise ValueError("review action must be accept, reject, refine, or replace")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("review rationale must be non-empty")
    task = runtime.get_task(task_id)
    if expected_revision is not None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("review expected_revision must be a non-negative integer")
        if int(task["revision"]) != expected_revision:
            raise ValueError(
                f"review task revision is stale: expected {expected_revision}; "
                f"current {task['revision']}"
            )
    if action == "accept":
        if task["status"] != "SUCCEEDED":
            raise ValueError("review accept requires a SUCCEEDED Task")
        verifications = runtime.list_verifications("TASK", task_id)
        if not any(item["status"] == "PASS" for item in verifications):
            raise ValueError("review accept requires PASS Task Verification evidence")
    return OriginForgeLineage(runtime).create_decision(
        title=f"Task review: {action.upper()}",
        decision=action.upper(),
        context=f"task_id={task_id}; task_revision={int(task['revision'])}",
        rationale=rationale.strip(),
        goal_id=runtime.get_flow(task["flow_id"])["goal_id"],
        task_id=task_id,
    )


def refine_task(
    runtime: OriginForgeRuntime,
    task_id: str,
    *,
    rationale: str,
    expected_revision: int | None = None,
) -> TaskRefinementResult:
    """Record human refinement and create a new immutable child Task proposal."""
    task = runtime.get_task(task_id)
    if expected_revision is not None and int(task["revision"]) != expected_revision:
        raise ValueError(
            f"review task revision is stale: expected {expected_revision}; "
            f"current {task['revision']}"
        )
    decision_id = record_task_review_decision(
        runtime,
        task_id,
        "refine",
        rationale=rationale,
        expected_revision=expected_revision,
    )
    refined_task_id = runtime.create_task(
        task["flow_id"],
        f"Refine {task['objective']}",
        parent_task_id=task_id,
        constraints=(rationale.strip(),),
        priority=int(task["priority"]),
    )
    return TaskRefinementResult(decision_id, refined_task_id)


def replace_task(
    runtime: OriginForgeRuntime,
    task_id: str,
    *,
    rationale: str,
    expected_revision: int | None = None,
) -> TaskReplacementResult:
    """Create a new replacement Task while preserving the rejected Task evidence."""
    task = runtime.get_task(task_id)
    if expected_revision is not None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("review expected_revision must be a non-negative integer")
        if int(task["revision"]) != expected_revision:
            raise ValueError(
                f"review task revision is stale: expected {expected_revision}; current {task['revision']}"
            )
    decision_id = record_task_review_decision(
        runtime,
        task_id,
        "replace",
        rationale=rationale,
        expected_revision=expected_revision,
    )
    replacement_task_id = runtime.create_task(
        task["flow_id"],
        f"Replace {task['objective']}",
        parent_task_id=task_id,
        constraints=(f"replacement: {rationale.strip()}",),
        priority=int(task["priority"]),
        required_capabilities=tuple(task.get("required_capabilities", ())),
    )
    return TaskReplacementResult(decision_id, replacement_task_id)
