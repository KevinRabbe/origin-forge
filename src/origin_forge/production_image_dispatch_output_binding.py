from __future__ import annotations

from .image_vision_service import ImageGenerationServiceResult
from .production_dispatch_execution_models import DispatchExecution
from .production_image_dispatch_output_binding_models import (
    IMAGE_EXECUTION_OWNER_ID,
    ImageDispatchOutput,
    ImageDispatchOutputBinding,
)


class ImageDispatchOutputBindingError(RuntimeError):
    pass


def binding_from_image_result(
    execution: DispatchExecution,
    result: ImageGenerationServiceResult,
    *,
    output_byte_counts: tuple[int, ...],
    created_at: str,
) -> ImageDispatchOutputBinding:
    """Build a fully checked binding candidate; do not persist or terminalize."""
    if not isinstance(execution, DispatchExecution):
        raise TypeError("execution must be a DispatchExecution")
    if not isinstance(result, ImageGenerationServiceResult):
        raise TypeError("result must be an ImageGenerationServiceResult")
    if execution.execution_owner_id != IMAGE_EXECUTION_OWNER_ID:
        raise ImageDispatchOutputBindingError("execution is not owned by image generation")
    if not result.outputs:
        raise ImageDispatchOutputBindingError("image result must contain at least one output")
    if len(output_byte_counts) != len(result.outputs):
        raise ImageDispatchOutputBindingError(
            "image output byte counts must exactly match result outputs"
        )
    outputs = tuple(
        ImageDispatchOutput(
            relative_path=value.relative_path,
            artifact_id=value.artifact_id,
            verification_id=value.verification_id,
            content_hash=value.content_hash.removeprefix("sha256:"),
            pixel_hash=value.pixel_hash.removeprefix("sha256:"),
            width=value.width,
            height=value.height,
            byte_count=byte_count,
        )
        for value, byte_count in zip(result.outputs, output_byte_counts, strict=True)
    )
    return ImageDispatchOutputBinding(
        execution_id=execution.execution_id,
        claim_id=execution.claim_id,
        task_id=execution.task_id,
        task_revision=execution.task_revision,
        task_content_hash=execution.task_content_hash,
        work_order_id=execution.work_order_id,
        work_order_hash=execution.work_order_hash,
        dispatch_binding_id=execution.dispatch_binding_id,
        dispatch_binding_hash=execution.dispatch_binding_hash,
        execution_owner_id=execution.execution_owner_id,
        run_id=result.run_id,
        request_artifact_id=result.request_artifact_id,
        result_artifact_id=result.result_artifact_id,
        outputs=outputs,
        backend_result_hash=result.backend_result_hash.removeprefix("sha256:"),
        schema_version=1,
        created_at=created_at,
    )
