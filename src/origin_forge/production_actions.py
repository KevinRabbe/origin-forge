from __future__ import annotations

from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_trace import inspect_task_production_trace
from .review import record_task_review_decision, refine_task, replace_task
from .runtime import OriginForgeRuntime

_MEDIA_ACCEPTORS = {
    "originforge.execution.blender.export-glb@1": (
        "production_blender_task_acceptor",
        "GovernedBlenderProductionTaskAcceptor",
    ),
    "originforge.execution.pixelorama.spritesheet-export@1": (
        "production_pixelorama_task_acceptor",
        "GovernedPixeloramaProductionTaskAcceptor",
    ),
    "originforge.execution.pixelorama.source-create@1": (
        "production_pixelorama_source_task_acceptance",
        "GovernedPixeloramaSourceTaskAcceptor",
    ),
}
_MEDIA_ADOPTERS = {
    "originforge.execution.blender.export-glb@1": (
        "production_blender_adoption",
        "GovernedBlenderProductionOutputAdopter",
    ),
    "originforge.execution.pixelorama.spritesheet-export@1": (
        "production_pixelorama_adoption",
        "GovernedPixeloramaProductionOutputAdopter",
    ),
    "originforge.execution.pixelorama.source-create@1": (
        "production_pixelorama_source_adoption",
        "GovernedPixeloramaSourceOutputAdopter",
    ),
}


def inspect_production_execution(
    runtime: OriginForgeRuntime, execution_id: str
) -> dict:
    execution = read_dispatch_execution(runtime, execution_id)
    trace = inspect_task_production_trace(runtime, execution.task_id)
    owner = execution.execution_owner_id
    reviewable = (
        execution.status is DispatchExecutionStatus.RETURNED
        and int(runtime.get_task(execution.task_id)["revision"])
        == execution.task_revision + 1
    )
    return {
        "execution": execution.to_dict(),
        "task_id": execution.task_id,
        "owner": owner,
        "trace": trace,
        "supported_actions": {
            "accept": owner in _MEDIA_ACCEPTORS,
            "adopt": owner in _MEDIA_ADOPTERS,
            "reject": reviewable,
            "refine": reviewable,
            "replace": reviewable,
        },
    }


def _service(runtime: OriginForgeRuntime, execution_id: str, mapping: dict):
    execution = read_dispatch_execution(runtime, execution_id)
    target = mapping.get(execution.execution_owner_id)
    if target is None:
        raise RuntimeError(
            f"execution owner {execution.execution_owner_id} has no governed action service"
        )
    module_name, class_name = target
    module = __import__(f"origin_forge.{module_name}", fromlist=[class_name])
    return getattr(module, class_name)(runtime)


def accept_production_execution(
    runtime: OriginForgeRuntime, execution_id: str, *, actor_id: str | None = None
):
    return _service(runtime, execution_id, _MEDIA_ACCEPTORS).accept(
        execution_id, actor_id=actor_id
    )


def adopt_production_execution(
    runtime: OriginForgeRuntime, execution_id: str, destination_relative_path: str
):
    return _service(runtime, execution_id, _MEDIA_ADOPTERS).adopt_new(
        execution_id, destination_relative_path
    )


def _reviewable_execution(runtime: OriginForgeRuntime, execution_id: str):
    execution = read_dispatch_execution(runtime, execution_id)
    if execution.status is not DispatchExecutionStatus.RETURNED:
        raise RuntimeError("production review requires a RETURNED execution")
    task = runtime.get_task(execution.task_id)
    expected_revision = execution.task_revision + 1
    if int(task["revision"]) != expected_revision:
        raise RuntimeError("production review requires the current Task revision")
    return execution, expected_revision


def reject_production_execution(
    runtime: OriginForgeRuntime,
    execution_id: str,
    *,
    rationale: str,
    expected_revision: int | None = None,
) -> str:
    execution, revision = _reviewable_execution(runtime, execution_id)
    if expected_revision is not None and expected_revision != revision:
        raise RuntimeError("production review Task revision is stale")
    return record_task_review_decision(
        runtime,
        execution.task_id,
        "reject",
        rationale=rationale,
        expected_revision=revision,
        execution_id=execution_id,
    )


def refine_production_execution(
    runtime: OriginForgeRuntime,
    execution_id: str,
    *,
    rationale: str,
    expected_revision: int | None = None,
):
    execution, revision = _reviewable_execution(runtime, execution_id)
    if expected_revision is not None and expected_revision != revision:
        raise RuntimeError("production review Task revision is stale")
    return refine_task(
        runtime,
        execution.task_id,
        rationale=rationale,
        expected_revision=revision,
        execution_id=execution_id,
    )


def replace_production_execution(
    runtime: OriginForgeRuntime,
    execution_id: str,
    *,
    rationale: str,
    expected_revision: int | None = None,
):
    execution, revision = _reviewable_execution(runtime, execution_id)
    if expected_revision is not None and expected_revision != revision:
        raise RuntimeError("production review Task revision is stale")
    return replace_task(
        runtime,
        execution.task_id,
        rationale=rationale,
        expected_revision=revision,
        execution_id=execution_id,
    )
