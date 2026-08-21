from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_blender_dispatch_output_binding import (
    BLENDER_EXECUTION_OWNER_ID,
    materialize_bound_blender_result,
    read_blender_dispatch_output_binding,
)
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import (
    DispatchExecutionCurrentnessStatus,
    inspect_dispatch_execution_currentness_readonly,
    read_dispatch_execution,
)
from .runtime import OriginForgeRuntime


class BlenderDispatchOutputCurrentnessStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXECUTION_NOT_RETURNED = "EXECUTION_NOT_RETURNED"
    STALE_EXECUTION = "STALE_EXECUTION"
    TASK_NOT_RUNNING = "TASK_NOT_RUNNING"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"


@dataclass(frozen=True)
class BlenderDispatchOutputCurrentness:
    execution_id: str
    task_id: str | None
    output_artifact_id: str | None
    status: BlenderDispatchOutputCurrentnessStatus
    production_task_verified: bool
    semantic_geometry_verified: bool
    detail: str | None = None

    @property
    def adoption_eligible(self) -> bool:
        return self.status is BlenderDispatchOutputCurrentnessStatus.ELIGIBLE

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "output_artifact_id": self.output_artifact_id,
            "status": self.status.value,
            "production_task_verified": self.production_task_verified,
            "semantic_geometry_verified": self.semantic_geometry_verified,
            "adoption_eligible": self.adoption_eligible,
            "detail": self.detail,
        }


def _status(
    execution_id: str,
    task_id: str | None,
    output_artifact_id: str | None,
    status: BlenderDispatchOutputCurrentnessStatus,
    detail: str | None = None,
) -> BlenderDispatchOutputCurrentness:
    return BlenderDispatchOutputCurrentness(
        execution_id=execution_id,
        task_id=task_id,
        output_artifact_id=output_artifact_id,
        status=status,
        production_task_verified=False,
        semantic_geometry_verified=False,
        detail=detail,
    )


def inspect_blender_dispatch_output_currentness_readonly(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> BlenderDispatchOutputCurrentness:
    """Resolve terminal Blender output adoption eligibility without mutating state."""
    try:
        execution = read_dispatch_execution(runtime, execution_id)
        binding = read_blender_dispatch_output_binding(runtime, execution_id)
    except Exception as exc:
        return _status(
            execution_id,
            None,
            None,
            BlenderDispatchOutputCurrentnessStatus.INVALID_EVIDENCE,
            str(exc),
        )

    if execution.execution_owner_id != BLENDER_EXECUTION_OWNER_ID:
        return _status(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            BlenderDispatchOutputCurrentnessStatus.STALE_EXECUTION,
            "dispatch execution is not owned by reviewed Blender owner",
        )

    currentness = inspect_dispatch_execution_currentness_readonly(runtime, execution_id)
    if execution.status is not DispatchExecutionStatus.RETURNED:
        status = (
            BlenderDispatchOutputCurrentnessStatus.EXECUTION_NOT_RETURNED
            if currentness.status is DispatchExecutionCurrentnessStatus.CURRENT_STARTED
            else BlenderDispatchOutputCurrentnessStatus.STALE_EXECUTION
        )
        return _status(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            status,
            currentness.detail,
        )

    if currentness.status is not DispatchExecutionCurrentnessStatus.RETURNED:
        return _status(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            BlenderDispatchOutputCurrentnessStatus.STALE_EXECUTION,
            currentness.detail,
        )

    try:
        materialize_bound_blender_result(runtime, binding)
    except Exception as exc:
        detail = str(exc)
        status = (
            BlenderDispatchOutputCurrentnessStatus.TASK_NOT_RUNNING
            if "Run/Task lifecycle" in detail or "Task" in detail and "RUNNING" in detail
            else BlenderDispatchOutputCurrentnessStatus.INVALID_EVIDENCE
        )
        return _status(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            status,
            detail,
        )

    return _status(
        execution_id,
        execution.task_id,
        binding.output_artifact_id,
        BlenderDispatchOutputCurrentnessStatus.ELIGIBLE,
    )
