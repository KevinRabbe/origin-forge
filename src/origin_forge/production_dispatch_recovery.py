from __future__ import annotations

from .production_dispatch_execution_read import read_dispatch_execution
from .production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .runtime import OriginForgeRuntime

_RECOVERERS = {
    "originforge.execution.pixelorama.spritesheet-export@1": (
        ".production_dispatch_invocation_pixelorama",
        "recover_pixelorama_dispatch_execution_once",
    ),
    "originforge.execution.blender.export-glb@1": (
        ".production_dispatch_invocation_blender_recovery",
        "recover_blender_dispatch_execution_once",
    ),
    "originforge.execution.image.generate@1": (
        ".production_dispatch_invocation_image_owner",
        "recover_image_dispatch_execution_once",
    ),
    "originforge.execution.audio.ffmpeg-process@1": (
        ".production_dispatch_invocation_ffmpeg_owner",
        "recover_ffmpeg_dispatch_execution_once",
    ),
    "originforge.execution.audio.piper-tts@1": (
        ".production_dispatch_invocation_piper_owner",
        "recover_piper_dispatch_execution_once",
    ),
    "originforge.execution.runtime.observe@1": (
        ".production_dispatch_invocation_runtime_owner",
        "recover_runtime_dispatch_execution_once",
    ),
    "originforge.execution.playtest.cooperative@1": (
        ".production_dispatch_invocation_playtest_owner",
        "recover_playtest_dispatch_execution_once",
    ),
    "originforge.execution.build.integration@1": (
        ".production_dispatch_invocation_build",
        "recover_build_dispatch_execution_once",
    ),
}


def recover_dispatch_execution_once(
    runtime: OriginForgeRuntime, execution_id: str
):
    """Route one explicit dispatch recovery to its trusted owner handler."""
    execution = read_dispatch_execution(runtime, execution_id)
    target = _RECOVERERS.get(execution.execution_owner_id)
    if target is None:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    module_name, function_name = target
    try:
        module = __import__(
            f"origin_forge{module_name}", fromlist=[function_name]
        )
        recoverer = getattr(module, function_name)
    except (ImportError, AttributeError) as exc:
        raise ProductionDispatchInvocationError(
            "trusted dispatch recovery handler is unavailable"
        ) from exc
    return recoverer(runtime, execution_id)
