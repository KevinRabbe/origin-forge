from __future__ import annotations

from .production_dispatch_execution_read import read_dispatch_execution
from .production_trace import inspect_task_production_trace
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
}


def inspect_production_execution(runtime: OriginForgeRuntime, execution_id: str) -> dict:
    execution = read_dispatch_execution(runtime, execution_id)
    trace = inspect_task_production_trace(runtime, execution.task_id)
    owner = execution.execution_owner_id
    return {
        "execution": execution.to_dict(),
        "task_id": execution.task_id,
        "owner": owner,
        "trace": trace,
        "supported_actions": {
            "accept": owner in _MEDIA_ACCEPTORS,
            "adopt": owner in _MEDIA_ADOPTERS,
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
