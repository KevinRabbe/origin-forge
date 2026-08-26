from __future__ import annotations

from typing import Any

from .production_planning_inspection import (
    inspect_flow_dependency_graph,
    inspect_task_dependency_readiness,
)
from .production_read_guard import ensure_production_runtime_readable
from .runtime import OriginForgeRuntime


def _next_action(task: dict[str, Any], readiness: dict[str, Any]) -> str:
    status = str(task["status"])
    readiness_status = str(readiness["status"])
    if status == "QUEUED":
        if readiness_status == "READY":
            return "ACTIVATE"
        if readiness_status == "BLOCKED_BY_FAILED_DEPENDENCY":
            return "RESOLVE_FAILED_DEPENDENCY"
        return "WAIT_FOR_DEPENDENCIES"
    if status == "READY":
        return "ATTEMPT"
    if status == "RUNNING":
        return "INSPECT_OR_RECOVER"
    if status == "SUCCEEDED":
        return "REVIEW_OR_ACCEPT"
    return "INSPECT"


def inspect_goal_plan(runtime: OriginForgeRuntime, goal_id: str) -> dict[str, Any]:
    """Return a bounded, read-only view of one Goal's production plan."""
    ensure_production_runtime_readable(runtime)
    goal = runtime.get_goal(goal_id)
    flows: list[dict[str, Any]] = []
    for flow in runtime.list_flows(goal_id):
        tasks: list[dict[str, Any]] = []
        for task in runtime.list_tasks(flow["id"]):
            readiness = inspect_task_dependency_readiness(runtime, task["id"]).to_dict()
            tasks.append(
                {
                    "task": task,
                    "readiness": readiness,
                    "next_action": _next_action(task, readiness),
                }
            )
        graph = inspect_flow_dependency_graph(runtime, flow["id"]).to_dict()
        flows.append({"flow": flow, "dependency_graph": graph, "tasks": tasks})

    task_views = [task for flow in flows for task in flow["tasks"]]
    action_order = (
        "RECOVER",
        "RESOLVE_FAILED_DEPENDENCY",
        "ATTEMPT",
        "ACTIVATE",
        "REVIEW_OR_ACCEPT",
        "WAIT_FOR_DEPENDENCIES",
        "INSPECT",
    )
    next_action = "COMPLETE"
    for action in action_order:
        if any(item["next_action"] == action for item in task_views):
            next_action = action
            break
    return {
        "goal": goal,
        "flows": flows,
        "summary": {
            "flow_count": len(flows),
            "task_count": len(task_views),
            "task_statuses": {
                status: sum(1 for item in task_views if item["task"]["status"] == status)
                for status in sorted({item["task"]["status"] for item in task_views})
            },
            "next_action": next_action,
        },
    }
