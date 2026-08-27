from __future__ import annotations

from .adapters.audio_ffmpeg import FfmpegAudioAdapter
from .audio_service import AudioOperationService
from .production_audio_dispatch_output_binding import (
    binding_from_audio_result,
    publish_audio_dispatch_output_binding,
    read_audio_dispatch_output_binding,
)
from .production_dispatch_binding_audio import FfmpegAudioInputBinder
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_claim_read import read_dispatch_claim
from .production_dispatch_execution import mark_dispatch_execution_returned
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_dispatch_invocation_ffmpeg import FfmpegInvocationRequest
from .production_dispatch_invocation_piper_owner import (
    _materialize,
    _require_audio_binding_evidence,
)
from .production_execution_assembly import FfmpegExecutionPayload
from .production_execution_owner_audio import FFMPEG_EXECUTION_OWNER_ID
from .runtime import OriginForgeRuntime
from .service import utc_now
from .state import TaskStatus

FFMPEG_RETURNED_DETAIL = "trusted FFmpeg audio execution owner returned normally"


def dispatch_ffmpeg_claim_once_if_applicable(runtime, claim_id: str, expected_claim_revision: int):
    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(runtime, claim_id, expected_claim_revision)
    descriptor = FfmpegAudioInputBinder().descriptor
    if binding.request_type_id != descriptor.request_type_id:
        return None
    legacy._require_trusted_relation(
        binding,
        descriptor=descriptor,
        expected_owner_id=FFMPEG_EXECUTION_OWNER_ID,
        expected_adapter_id="originforge.audio.ffmpeg",
        expected_contract_id="audio.ffmpeg-process@1",
        expected_binder_id=descriptor.binder_id,
        expected_request_type_id=descriptor.request_type_id,
    )
    projection = binding.request_projection
    if not isinstance(projection, dict):
        raise ProductionDispatchInvocationRecoveryRequired(claim_id, "REQUEST_PROJECTION_INVALID")
    request = FfmpegInvocationRequest.from_projection(projection, binding.request_content_hash)
    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    if (
        started.execution.execution_owner_id != FFMPEG_EXECUTION_OWNER_ID
        or started.dependencies.plan.request_content_hash != request.request_content_hash
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            started.execution.execution_id, "STARTED_RELATION_MISMATCH"
        )
    payload = started.dependencies.payload
    if not isinstance(payload, FfmpegExecutionPayload):
        raise ProductionDispatchInvocationRecoveryRequired(
            started.execution.execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        operation_request = request.to_operation_request(payload.profile)
        result = AudioOperationService(
            runtime,
            FfmpegAudioAdapter(
                runtime,
                payload.profile,
                executable=payload.infrastructure.executable,
            ),
        ).execute(
            request.task_id,
            operation_request,
            source_artifact_ids={request.source_artifact_id: request.source_artifact_id},
        )
        publish_audio_dispatch_output_binding(
            runtime,
            binding_from_audio_result(started.execution, result, created_at=utc_now()),
        )
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        legacy._record_raised_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=f"trusted FFmpeg owner raised {type(exc).__name__}",
        )
        raise ProductionDispatchInvocationError(
            f"trusted FFmpeg owner raised {type(exc).__name__}; dispatch execution {started.execution.execution_id} recorded RAISED"
        ) from exc
    returned = legacy._record_returned_or_recovery(
        runtime, started, frozen_claim, detail=FFMPEG_RETURNED_DETAIL
    )
    return CompletedDispatchInvocation(returned, audio_result=result)


def recover_ffmpeg_dispatch_execution_once(runtime, execution_id: str) -> CompletedDispatchInvocation:
    execution = read_dispatch_execution(runtime, execution_id)
    if execution.execution_owner_id != FFMPEG_EXECUTION_OWNER_ID:
        raise ProductionDispatchInvocationError("execution is not owned by FFmpeg")
    try:
        binding = read_audio_dispatch_output_binding(runtime, execution_id)
        if isinstance(runtime, OriginForgeRuntime):
            _require_audio_binding_evidence(runtime, binding)
        result = _materialize(binding)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    if execution.status is DispatchExecutionStatus.RETURNED:
        return CompletedDispatchInvocation(execution, audio_result=result)
    if execution.status is not DispatchExecutionStatus.STARTED:
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "STARTED_RELATION_MISMATCH")
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if (
        claim.status is not DispatchClaimStatus.ACTIVE
        or claim.revision != execution.claim_revision_at_start
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != execution.task_revision + 1
    ):
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "STARTED_RELATION_MISMATCH")
    try:
        returned = mark_dispatch_execution_returned(
            runtime,
            execution_id,
            execution.revision,
            execution.claim_revision_at_start,
            FFMPEG_RETURNED_DETAIL,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedDispatchInvocation(returned, audio_result=result)
