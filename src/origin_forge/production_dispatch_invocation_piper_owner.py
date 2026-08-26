from __future__ import annotations

from .adapters.audio_piper import PiperAudioAdapter
from .audio_service import (
    AudioOperationService,
    AudioOperationServiceResult,
    AudioOutputArtifactEvidence,
)
from .production_audio_dispatch_output_binding import (
    binding_from_audio_result,
    publish_audio_dispatch_output_binding,
    read_audio_dispatch_output_binding,
)
from .production_dispatch_binding_audio import PiperAudioInputBinder
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
from .production_dispatch_invocation_piper import PiperInvocationRequest
from .production_execution_owner_audio import PIPER_EXECUTION_OWNER_ID
from .service import utc_now
from .state import TaskStatus

PIPER_RETURNED_DETAIL = "trusted Piper audio execution owner returned normally"


def dispatch_piper_claim_once_if_applicable(runtime, claim_id: str, expected_claim_revision: int):
    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(runtime, claim_id, expected_claim_revision)
    descriptor = PiperAudioInputBinder().descriptor
    if binding.request_type_id != descriptor.request_type_id:
        return None
    legacy._require_trusted_relation(
        binding, descriptor=descriptor, expected_owner_id=PIPER_EXECUTION_OWNER_ID,
        expected_adapter_id="originforge.audio.piper", expected_contract_id="audio.piper-tts@1",
        expected_binder_id=descriptor.binder_id, expected_request_type_id=descriptor.request_type_id,
    )
    request = PiperInvocationRequest.from_projection(binding.request_projection, binding.request_content_hash)
    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    if started.execution.execution_owner_id != PIPER_EXECUTION_OWNER_ID or started.dependencies.plan.request_content_hash != request.request_content_hash:
        raise ProductionDispatchInvocationRecoveryRequired(started.execution.execution_id, "STARTED_RELATION_MISMATCH")
    payload = started.dependencies.payload
    try:
        operation_request = request.to_operation_request(payload.profile)
        result = AudioOperationService(
            runtime,
            PiperAudioAdapter(
                runtime, payload.profile,
                runtime_root=payload.infrastructure.runtime_root,
                executable=payload.infrastructure.executable,
                espeak_data_path=payload.infrastructure.espeak_data_path,
                model_path=payload.infrastructure.model_path,
                model_config_path=payload.infrastructure.model_config_path,
                license_path=payload.infrastructure.license_path,
            ),
        ).execute(request.task_id, operation_request)
        publish_audio_dispatch_output_binding(
            runtime,
            binding_from_audio_result(started.execution, result, created_at=utc_now()),
        )
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        legacy._record_raised_or_recovery(runtime, started, frozen_claim, detail=f"trusted Piper owner raised {type(exc).__name__}")
        raise ProductionDispatchInvocationError(
            f"trusted Piper owner raised {type(exc).__name__}; dispatch execution {started.execution.execution_id} recorded RAISED"
        ) from exc
    returned = legacy._record_returned_or_recovery(runtime, started, frozen_claim, detail=PIPER_RETURNED_DETAIL)
    return CompletedDispatchInvocation(returned, audio_result=result)


def _materialize(binding):
    return AudioOperationServiceResult(
        run_id=binding.run_id,
        request_artifact_id=binding.request_artifact_id,
        result_artifact_id=binding.result_artifact_id,
        output=AudioOutputArtifactEvidence(
            relative_path=binding.output_relative_path,
            artifact_id=binding.output_artifact_id,
            verification_id=binding.output_verification_id,
            content_hash="sha256:" + binding.output_content_hash,
            pcm_hash="sha256:" + binding.output_pcm_hash,
            byte_count=binding.output_byte_count,
            frame_count=binding.output_frame_count,
            sample_rate=binding.output_sample_rate,
            channels=binding.output_channels,
            peak_abs_sample=binding.output_peak_abs_sample,
            clipped_sample_count=binding.output_clipped_sample_count,
            nonzero_sample_count=binding.output_nonzero_sample_count,
        ),
        backend_result_hash="sha256:" + binding.backend_result_hash,
    )


def recover_piper_dispatch_execution_once(runtime, execution_id: str) -> CompletedDispatchInvocation:
    execution = read_dispatch_execution(runtime, execution_id)
    if execution.execution_owner_id != PIPER_EXECUTION_OWNER_ID:
        raise ProductionDispatchInvocationError("execution is not owned by Piper")
    try:
        result = _materialize(read_audio_dispatch_output_binding(runtime, execution_id))
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "OWNER_RETURN_CONTRACT_MISMATCH") from exc
    if execution.status is DispatchExecutionStatus.RETURNED:
        return CompletedDispatchInvocation(execution, audio_result=result)
    if execution.status is not DispatchExecutionStatus.STARTED:
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "STARTED_RELATION_MISMATCH")
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if claim.status is not DispatchClaimStatus.ACTIVE or claim.revision != execution.claim_revision_at_start or task["status"] != TaskStatus.RUNNING.value or int(task["revision"]) != execution.task_revision + 1:
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "STARTED_RELATION_MISMATCH")
    try:
        returned = mark_dispatch_execution_returned(runtime, execution_id, execution.revision, execution.claim_revision_at_start, PIPER_RETURNED_DETAIL)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "RETURNED_TERMINALIZATION_FAILED") from exc
    return CompletedDispatchInvocation(returned, audio_result=result)
