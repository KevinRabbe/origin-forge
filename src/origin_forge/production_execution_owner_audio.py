from __future__ import annotations

from .production_capability_builtin import builtin_trusted_production_adapters
from .production_dispatch_binding_audio import (
    FfmpegAudioInputBinder,
    PiperAudioInputBinder,
)
from .production_execution_owner import (
    ProductionExecutionOwnerDescriptor,
    ProductionExecutionOwnerError,
)
from .production_work_order_audio import (
    FFMPEG_ADAPTER_ID,
    FFMPEG_CONTRACT_ID,
    PIPER_ADAPTER_ID,
    PIPER_CONTRACT_ID,
)

FFMPEG_EXECUTION_OWNER_ID = "originforge.execution.audio.ffmpeg-process@1"
PIPER_EXECUTION_OWNER_ID = "originforge.execution.audio.piper-tts@1"


def ffmpeg_execution_owner_descriptor() -> ProductionExecutionOwnerDescriptor:
    """Return the exact FFmpeg owner relation without activating dispatch."""
    adapter = next(
        (value for value in builtin_trusted_production_adapters() if value.adapter_id == FFMPEG_ADAPTER_ID),
        None,
    )
    if adapter is None:
        raise ProductionExecutionOwnerError("built-in capability inventory lacks FFmpeg adapter")
    binder = FfmpegAudioInputBinder().descriptor
    if binder.adapter_id != adapter.adapter_id or binder.dispatch_contract_id != FFMPEG_CONTRACT_ID:
        raise ProductionExecutionOwnerError("built-in FFmpeg binder relation drifted")
    return ProductionExecutionOwnerDescriptor(
        owner_id=FFMPEG_EXECUTION_OWNER_ID,
        owner_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        dispatch_contract_id=binder.dispatch_contract_id,
        binder_id=binder.binder_id,
        binder_fingerprint=binder.binder_fingerprint,
        request_type_id=binder.request_type_id,
        request_schema_hash=binder.request_schema_hash,
        model_strategy_roles=(),
        requires_sandbox=False,
        requires_workspace_manager=False,
    )


def piper_execution_owner_descriptor() -> ProductionExecutionOwnerDescriptor:
    """Return the exact Piper owner relation without activating dispatch."""
    adapter = next(
        (value for value in builtin_trusted_production_adapters() if value.adapter_id == PIPER_ADAPTER_ID),
        None,
    )
    if adapter is None:
        raise ProductionExecutionOwnerError("built-in capability inventory lacks Piper adapter")
    binder = PiperAudioInputBinder().descriptor
    if binder.adapter_id != adapter.adapter_id or binder.dispatch_contract_id != PIPER_CONTRACT_ID:
        raise ProductionExecutionOwnerError("built-in Piper binder relation drifted")
    return ProductionExecutionOwnerDescriptor(
        owner_id=PIPER_EXECUTION_OWNER_ID,
        owner_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        dispatch_contract_id=binder.dispatch_contract_id,
        binder_id=binder.binder_id,
        binder_fingerprint=binder.binder_fingerprint,
        request_type_id=binder.request_type_id,
        request_schema_hash=binder.request_schema_hash,
        model_strategy_roles=(),
        requires_sandbox=False,
        requires_workspace_manager=False,
    )
