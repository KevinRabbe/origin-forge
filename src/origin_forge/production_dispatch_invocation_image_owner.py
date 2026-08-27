from __future__ import annotations

import hashlib
from typing import cast

from .adapters.comfyui import ComfyUiAdapter
from .image_vision_service import (
    ImageBackendAdapter,
    ImageGenerationService,
    ImageGenerationServiceResult,
)
from .lineage import OriginForgeLineage
from .pixelorama_png import inspect_rgba8_png
from .production_dispatch_binding_image import ImageGenerationInputBinder
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
from .production_dispatch_invocation_image import ImageGenerationInvocationRequest
from .production_execution_owner_image import IMAGE_EXECUTION_OWNER_ID
from .production_image_dispatch_output_binding import (
    binding_from_image_result,
    publish_image_dispatch_output_binding,
    read_image_dispatch_output_binding,
)
from .runtime import OriginForgeRuntime
from .service import utc_now
from .state import TaskStatus

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
    projection = binding.request_projection
    if not isinstance(projection, dict):
        raise ProductionDispatchInvocationRecoveryRequired(
            claim_id, "REQUEST_PROJECTION_INVALID"
        )
    request = ImageGenerationInvocationRequest.from_projection(
        projection,
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
            cast(
                ImageBackendAdapter,
                ComfyUiAdapter(runtime, payload.profile, payload.template),
            ),
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


def _materialize_image_result(binding):
    from .image_vision_service import GeneratedImageEvidence

    return ImageGenerationServiceResult(
        run_id=binding.run_id,
        request_artifact_id=binding.request_artifact_id,
        result_artifact_id=binding.result_artifact_id,
        outputs=tuple(
            GeneratedImageEvidence(
                relative_path=value.relative_path,
                artifact_id=value.artifact_id,
                verification_id=value.verification_id,
                content_hash="sha256:" + value.content_hash,
                pixel_hash="sha256:" + value.pixel_hash,
                width=value.width,
                height=value.height,
            )
            for value in binding.outputs
        ),
        backend_result_hash="sha256:" + binding.backend_result_hash,
    )


def _require_image_binding_evidence(runtime: OriginForgeRuntime, binding) -> None:
    """Revalidate every generated PNG before recovery terminalization."""
    lineage = OriginForgeLineage(runtime)
    result_artifact = lineage.get_artifact(binding.result_artifact_id)
    if (
        result_artifact.get("created_by_run_id") != binding.run_id
        or result_artifact.get("parent_artifact_id") != binding.request_artifact_id
        or result_artifact.get("status") != "CAPTURED"
    ):
        raise ProductionDispatchInvocationError("image result Artifact lineage drifted")
    for output in binding.outputs:
        artifact = lineage.get_artifact(output.artifact_id)
        path = lineage.local_artifact_path(output.artifact_id)
        data = path.read_bytes()
        inspection = inspect_rgba8_png(data)
        verification_ids = {
            value["id"]
            for value in lineage.list_artifact_verifications(output.artifact_id)
        }
        if (
            artifact.get("parent_artifact_id") != binding.result_artifact_id
            or artifact.get("created_by_run_id") != binding.run_id
            or artifact.get("status") != "PRODUCED"
            or artifact.get("content_hash")
            != "sha256:" + hashlib.sha256(data).hexdigest()
            or artifact.get("content_hash") != "sha256:" + output.content_hash
            or inspection.pixel_hash.removeprefix("sha256:") != output.pixel_hash
            or inspection.width != output.width
            or inspection.height != output.height
            or len(data) != output.byte_count
            or output.verification_id not in verification_ids
        ):
            raise ProductionDispatchInvocationError(
                f"image output evidence drifted: {output.relative_path}"
            )


def _require_started_image_authority(runtime, execution) -> None:
    durable = read_dispatch_execution(runtime, execution.execution_id)
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if (
        durable != execution
        or execution.status is not DispatchExecutionStatus.STARTED
        or execution.execution_owner_id != IMAGE_EXECUTION_OWNER_ID
        or claim.status is not DispatchClaimStatus.ACTIVE
        or claim.revision != execution.claim_revision_at_start
        or claim.project_id != execution.project_id
        or claim.task_id != execution.task_id
        or claim.task_revision != execution.task_revision
        or claim.task_content_hash != execution.task_content_hash
        or claim.dispatch_binding_id != execution.dispatch_binding_id
        or claim.dispatch_binding_hash != execution.dispatch_binding_hash
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != execution.task_revision + 1
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "STARTED_RELATION_MISMATCH"
        )


def recover_image_dispatch_execution_once(runtime, execution_id: str) -> CompletedDispatchInvocation:
    """Materialize a durable image result and never invoke ComfyUI during recovery."""
    execution = read_dispatch_execution(runtime, execution_id)
    if execution.execution_owner_id != IMAGE_EXECUTION_OWNER_ID:
        raise ProductionDispatchInvocationError("execution is not owned by image generation")
    try:
        binding = read_image_dispatch_output_binding(runtime, execution_id)
        if isinstance(runtime, OriginForgeRuntime):
            _require_image_binding_evidence(runtime, binding)
        result = _materialize_image_result(binding)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    if execution.status is DispatchExecutionStatus.RETURNED:
        return CompletedDispatchInvocation(execution, image_result=result)
    if execution.status is not DispatchExecutionStatus.STARTED:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        _require_started_image_authority(runtime, execution)
        returned = mark_dispatch_execution_returned(
            runtime,
            execution.execution_id,
            execution.revision,
            execution.claim_revision_at_start,
            IMAGE_RETURNED_DETAIL,
        )
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedDispatchInvocation(returned, image_result=result)
