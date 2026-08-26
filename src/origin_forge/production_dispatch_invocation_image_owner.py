from __future__ import annotations

from .adapters.comfyui import ComfyUiAdapter
from .image_vision_service import ImageGenerationService, ImageGenerationServiceResult
from .lineage import OriginForgeLineage
from .production_dispatch_binding_image import ImageGenerationInputBinder
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_dispatch_invocation_image import ImageGenerationInvocationRequest
from .production_execution_owner_image import IMAGE_EXECUTION_OWNER_ID
from .production_image_dispatch_output_binding import (
    binding_from_image_result,
    publish_image_dispatch_output_binding,
)
from .service import utc_now


IMAGE_RETURNED_DETAIL = "trusted image-generation execution owner returned normally"


def _require_started_matches(started, claim, request: ImageGenerationInvocationRequest) -> None:
    execution = started.execution
    plan = started.dependencies.plan
    if (
        execution.claim_id != claim.claim_id
        or execution.claim_revision_at_start != claim.revision
        or execution.task_id != claim.task_id
        or execution.task_id != request.task_id
        or execution.dispatch_binding_id != claim.dispatch_binding_id
        or execution.dispatch_binding_hash != claim.dispatch_binding_hash
        or execution.execution_owner_id != IMAGE_EXECUTION_OWNER_ID
        or plan.claim_id != claim.claim_id
        or plan.claim_revision != claim.revision
        or plan.task_id != request.task_id
        or plan.dispatch_binding_id != claim.dispatch_binding_id
        or plan.dispatch_binding_hash != claim.dispatch_binding_hash
        or plan.request_type_id != ImageGenerationInputBinder().descriptor.request_type_id
        or plan.request_content_hash != request.request_content_hash
        or plan.owner_id != IMAGE_EXECUTION_OWNER_ID
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "STARTED_RELATION_MISMATCH"
        )


def dispatch_image_claim_once_if_applicable(
    runtime,
    claim_id: str,
    expected_claim_revision: int,
) -> CompletedDispatchInvocation | None:
    """Invoke one image claim, or return None for a different capability."""
    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(
        runtime, claim_id, expected_claim_revision
    )
    descriptor = ImageGenerationInputBinder().descriptor
    if binding.request_type_id != descriptor.request_type_id:
        return None
    legacy._require_trusted_relation(
        binding,
        descriptor=descriptor,
        expected_owner_id=IMAGE_EXECUTION_OWNER_ID,
        expected_adapter_id="originforge.image.generate",
        expected_contract_id="image.generate@1",
        expected_binder_id=descriptor.binder_id,
        expected_request_type_id=descriptor.request_type_id,
    )
    request = ImageGenerationInvocationRequest.from_projection(
        binding.request_projection,
        binding.request_content_hash,
    )
    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    _require_started_matches(started, frozen_claim, request)
    from .production_execution_assembly import ImageGenerationExecutionPayload

    payload = started.dependencies.payload
    if not isinstance(payload, ImageGenerationExecutionPayload):
        raise ProductionDispatchInvocationRecoveryRequired(
            started.execution.execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        operation_request = request.to_operation_request(template=payload.template)
        result = ImageGenerationService(
            runtime,
            ComfyUiAdapter(runtime, payload.profile, payload.template),
        ).execute(request.task_id, operation_request)
        if not isinstance(result, ImageGenerationServiceResult):
            raise ProductionDispatchInvocationError("image service returned an invalid result")
        lineage = OriginForgeLineage(runtime)
        byte_counts = tuple(
            lineage.local_artifact_path(output.artifact_id).stat().st_size
            for output in result.outputs
        )
        candidate = binding_from_image_result(
            started.execution,
            result,
            output_byte_counts=byte_counts,
            created_at=utc_now(),
        )
        publish_image_dispatch_output_binding(runtime, candidate)
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        exception_type = legacy._exception_type_commitment(exc)
        legacy._record_raised_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=f"trusted image-generation execution owner raised {exception_type}",
        )
        raise ProductionDispatchInvocationError(
            "trusted image-generation execution owner raised "
            f"{exception_type}; dispatch execution {started.execution.execution_id} recorded RAISED"
        ) from exc
    returned = legacy._record_returned_or_recovery(
        runtime,
        started,
        frozen_claim,
        detail=IMAGE_RETURNED_DETAIL,
    )
    return CompletedDispatchInvocation(returned, image_result=result)
