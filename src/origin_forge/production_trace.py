from __future__ import annotations

from typing import Any

from .lineage import OriginForgeLineage
from .production_evidence_read import ProductionEvidenceReadService
from .production_read_guard import (
    ensure_production_runtime_readable,
    production_read_connection,
)
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_read import read_work_order
from .runtime import OriginForgeRuntime
from .workspaces import GitWorkspaceManager


def _rows(conn, sql: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def inspect_task_production_trace(runtime: OriginForgeRuntime, task_id: str) -> dict[str, Any]:
    """Correlate one Task's durable production lifecycle without mutation."""
    ensure_production_runtime_readable(runtime)
    task = runtime.get_task(task_id)
    flow = runtime.get_flow(task["flow_id"])
    goal = runtime.get_goal(flow["goal_id"])
    runs = runtime.list_runs(task_id)
    run_ids = tuple(str(row["id"]) for row in runs)
    artifacts = [
        item
        for item in ProductionEvidenceReadService(runtime).list_artifacts()
        if item.get("created_by_run_id") in run_ids
    ]
    with production_read_connection(runtime) as conn:
        claims = _rows(
            conn,
            "SELECT * FROM dispatch_claims WHERE project_id = ? AND task_id = ? ORDER BY created_at, claim_id",
            (runtime.project_id(), task_id),
        )
        executions = _rows(
            conn,
            "SELECT * FROM dispatch_executions WHERE project_id = ? AND task_id = ? ORDER BY created_at, execution_id",
            (runtime.project_id(), task_id),
        )
        output_bindings = {
            table: _rows(
                conn,
                f"SELECT * FROM {table} WHERE task_id = ? ORDER BY created_at, execution_id",
                (task_id,),
            )
            for table in (
                "pixelorama_dispatch_output_bindings",
                "blender_dispatch_output_bindings",
                "image_dispatch_output_bindings",
                "audio_dispatch_output_bindings",
                "runtime_dispatch_output_bindings",
                "playtest_dispatch_output_bindings",
            )
        }
        model3d_approvals = _rows(
            conn,
            "SELECT * FROM model3d_request_approvals WHERE project_id = ? AND task_id = ? ORDER BY approved_at, approval_id",
            (runtime.project_id(), task_id),
        )
        model3d_publications = _rows(
            conn,
            "SELECT * FROM model3d_request_publications WHERE project_id = ? AND task_id = ? ORDER BY published_at, publication_id",
            (runtime.project_id(), task_id),
        )
    validator_registry = build_builtin_dispatch_validator_registry()
    work_order_ids = tuple(
        dict.fromkeys(str(row["work_order_id"]) for row in executions)
    )
    work_orders = [
        read_work_order(runtime, work_order_id, validator_registry).to_dict()
        for work_order_id in work_order_ids
    ]
    decisions = [
        item for item in OriginForgeLineage(runtime).list_decisions() if item.get("task_id") == task_id
    ]
    workspaces = GitWorkspaceManager(runtime).list(task_id)
    workspace_verifications = {
        str(workspace["id"]): runtime.list_verifications("WORKSPACE", str(workspace["id"]))
        for workspace in workspaces
    }
    return {
        "goal": goal,
        "flow": flow,
        "task": task,
        "runs": runs,
        "workspaces": workspaces,
        "workspace_verifications": workspace_verifications,
        "dispatch": {
            "work_orders": work_orders,
            "claims": claims,
            "executions": executions,
            "output_bindings": output_bindings,
            "model3d_approvals": model3d_approvals,
            "model3d_publications": model3d_publications,
        },
        "artifacts": artifacts,
        "verifications": runtime.list_verifications("TASK", task_id),
        "decisions": decisions,
        "next_action": (
            "RECOVER"
            if any(row["status"] in {"STARTED", "INTERRUPTED"} for row in executions)
            or task["status"] == "RUNNING"
            else "REVIEW"
            if task["status"] == "SUCCEEDED"
            else "ADVANCE"
        ),
    }
