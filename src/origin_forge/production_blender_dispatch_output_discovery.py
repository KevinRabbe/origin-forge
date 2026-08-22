from __future__ import annotations

from .ids import IdKind, validate_id
from .production_blender_dispatch_output_binding import (
    BLENDER_EXECUTION_OWNER_ID,
    BlenderDispatchOutputBindingError,
    read_blender_dispatch_output_binding,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime


_MAX_DISCOVERED_BINDINGS_PER_TASK = 2


class BlenderDispatchOutputDiscoveryError(RuntimeError):
    pass


def discover_blender_dispatch_output_executions_for_task_readonly(
    runtime: OriginForgeRuntime,
    task_id: str,
) -> tuple[str, ...]:
    """Return zero, one, or two exact Blender output executions for one Task.

    Two results deliberately mean ambiguous authority. Callers must not choose between
    them heuristically. The fixed bound is sufficient for zero/exact-one/ambiguous
    classification without scanning the full production database.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(task_id, str) or not validate_id(task_id, IdKind.TASK):
        raise ValueError("task_id must be a TASK ID")

    try:
        with production_read_connection(runtime) as conn:
            project_row = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?",
                (str(runtime.project_root),),
            ).fetchone()
            if project_row is None:
                raise BlenderDispatchOutputDiscoveryError(
                    "project is not initialized for current repository root"
                )
            rows = conn.execute(
                """SELECT b.execution_id
                   FROM blender_dispatch_output_bindings AS b
                   JOIN dispatch_executions AS e
                     ON e.execution_id = b.execution_id
                   WHERE b.task_id = ?
                     AND e.project_id = ?
                     AND e.task_id = b.task_id
                     AND e.execution_owner_id = ?
                   ORDER BY b.created_at, b.execution_id
                   LIMIT ?""",
                (
                    task_id,
                    project_row["id"],
                    BLENDER_EXECUTION_OWNER_ID,
                    _MAX_DISCOVERED_BINDINGS_PER_TASK,
                ),
            ).fetchall()
    except BlenderDispatchOutputDiscoveryError:
        raise
    except ProductionReadGuardError as exc:
        raise BlenderDispatchOutputDiscoveryError(str(exc)) from exc

    execution_ids = tuple(str(row["execution_id"]) for row in rows)
    for execution_id in execution_ids:
        if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
            raise BlenderDispatchOutputDiscoveryError(
                "stored Blender dispatch execution identity is invalid"
            )
        try:
            binding = read_blender_dispatch_output_binding(runtime, execution_id)
        except BlenderDispatchOutputBindingError as exc:
            raise BlenderDispatchOutputDiscoveryError(
                "stored Blender dispatch-output relation failed exact validation"
            ) from exc
        if binding.task_id != task_id:
            raise BlenderDispatchOutputDiscoveryError(
                "stored Blender dispatch-output relation belongs to another Task"
            )
    return execution_ids
