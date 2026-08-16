from __future__ import annotations

from . import _production_dispatch_invocation_pixelorama_core as core
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_execution import mark_dispatch_execution_returned
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_execution_assembly import PixeloramaSpritesheetExportExecutionPayload
from .production_pixelorama_dispatch_output_binding_models import (
    PIXELORAMA_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION,
    PIXELORAMA_EXECUTION_OWNER_ID,
    PixeloramaDispatchOutputBinding,
)
from .production_pixelorama_dispatch_output_binding_read import (
    PixeloramaDispatchOutputBindingReadError,
    read_pixelorama_dispatch_output_binding,
)
from .production_pixelorama_dispatch_output_binding_store import (
    publish_pixelorama_dispatch_output_binding,
)
from .service import utc_now


PixeloramaInvocationRequest = core.PixeloramaInvocationRequest
_decode_pixelorama_request_projection = core._decode_pixelorama_request_projection
_require_trusted_pixelorama_relation = core._require_trusted_pixelorama_relation
_safe_source_path = core._safe_source_path
_require_pixelorama_result_durable = core._require_pixelorama_result_durable
_PIXELORAMA_OWNER_ID = core._PIXELORAMA_OWNER_ID
_PIXELORAMA_RETURNED_DETAIL = core._PIXELORAMA_RETURNED_DETAIL
_MAX_OUTPUT_BYTES = core._MAX_OUTPUT_BYTES


def _publish_result_binding(runtime, execution, pixelorama_result) -> PixeloramaDispatchOutputBinding:
    """Publish the exact Phase-48 result relation before RETURNED terminalization."""
    try:
        existing = read_pixelorama_dispatch_output_binding(runtime, execution.execution_id)
    except PixeloramaDispatchOutputBindingReadError:
        existing = None

    lineage = OriginForgeLineage(runtime)
    try:
        output_artifact = lineage.get_artifact(pixelorama_result.output_artifact_id)
        output_path = lineage.local_artifact_path(pixelorama_result.output_artifact_id)
        output_byte_count = output_path.stat().st_size
    except (KeyError, OSError, RuntimeError) as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "PIXELORAMA_BINDING_PERSISTENCE_FAILED",
        ) from exc

    candidate = PixeloramaDispatchOutputBinding(
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
        run_id=pixelorama_result.run_id,
        request_artifact_id=pixelorama_result.request_artifact_id,
        result_artifact_id=pixelorama_result.result_artifact_id,
        output_artifact_id=pixelorama_result.output_artifact_id,
        output_verification_id=pixelorama_result.output_verification_id,
        run_verification_id=pixelorama_result.run_verification_id,
        output_content_hash=output_artifact["content_hash"],
        output_byte_count=output_byte_count,
        schema_version=PIXELORAMA_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION,
        created_at=existing.created_at if existing is not None else utc_now(),
    )
    try:
        published = publish_pixelorama_dispatch_output_binding(runtime, candidate)
        reread = read_pixelorama_dispatch_output_binding(runtime, execution.execution_id)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "PIXELORAMA_BINDING_PERSISTENCE_FAILED",
        ) from exc
    if published != candidate or reread != candidate:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "PIXELORAMA_BINDING_PERSISTENCE_FAILED",
        )
    return reread


def _dispatch_claim_once_three_owner(
    runtime,
    claim_id: str,
    expected_claim_revision: int,
) -> CompletedDispatchInvocation:
    """Single-shot coordinator with immutable Pixelorama output binding."""
    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(
        runtime, claim_id, expected_claim_revision
    )
    if binding.request_type_id != core.PIXELORAMA_REQUEST_TYPE_ID:
        return legacy._legacy_dispatch_claim_once(runtime, claim_id, expected_claim_revision)

    core._require_trusted_pixelorama_relation(binding)
    request = core._decode_pixelorama_request_projection(binding)
    if (
        frozen_claim.status is not DispatchClaimStatus.ACTIVE
        or frozen_claim.revision != expected_claim_revision
        or frozen_claim.task_id != request.task_id
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama dispatch claim changed before execution ownership begin"
        )

    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    execution = started.execution
    plan = started.dependencies.plan
    payload = started.dependencies.payload
    if (
        execution.status is not DispatchExecutionStatus.STARTED
        or execution.claim_id != frozen_claim.claim_id
        or execution.claim_revision_at_start != frozen_claim.revision
        or execution.task_id != request.task_id
        or execution.dispatch_binding_id != frozen_claim.dispatch_binding_id
        or execution.dispatch_binding_hash != frozen_claim.dispatch_binding_hash
        or execution.execution_owner_id != _PIXELORAMA_OWNER_ID
        or plan.claim_id != frozen_claim.claim_id
        or plan.claim_revision != frozen_claim.revision
        or plan.task_id != request.task_id
        or plan.dispatch_binding_id != frozen_claim.dispatch_binding_id
        or plan.dispatch_binding_hash != frozen_claim.dispatch_binding_hash
        or plan.request_type_id != core.PIXELORAMA_REQUEST_TYPE_ID
        or plan.request_content_hash != request.request_content_hash
        or plan.owner_id != _PIXELORAMA_OWNER_ID
        or not isinstance(payload, PixeloramaSpritesheetExportExecutionPayload)
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "STARTED_RELATION_MISMATCH"
        )

    try:
        source_path, source_byte_count = core._safe_source_path(runtime, request)
        concrete_request = core.PixeloramaCliExportRequest.create(
            source_hash="sha256:" + request.source_artifact_hash,
            source_byte_count=source_byte_count,
            source_relative_path=request.staged_source_relative_path,
            output_relative_path=request.output_relative_path,
            timeout_seconds=min(60, payload.profile.timeout_seconds),
            max_output_bytes=_MAX_OUTPUT_BYTES,
        )
        pixelorama_result = core.PixeloramaCliExportService(runtime, payload.profile).execute(
            request.task_id, concrete_request, source_path=source_path
        )
    except Exception as exc:
        exception_type = legacy._exception_type_commitment(exc)
        legacy._record_raised_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=(
                "trusted Pixelorama spritesheet-export execution owner raised "
                f"{exception_type}"
            ),
        )
        raise ProductionDispatchInvocationError(
            "trusted Pixelorama spritesheet-export execution owner raised "
            f"{exception_type}; dispatch execution {execution.execution_id} recorded RAISED"
        ) from exc

    try:
        core._require_pixelorama_result_durable(
            runtime, request, concrete_request, pixelorama_result, payload
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc

    _publish_result_binding(runtime, execution, pixelorama_result)
    returned = legacy._record_returned_or_recovery(
        runtime, started, frozen_claim, detail=_PIXELORAMA_RETURNED_DETAIL
    )
    return CompletedDispatchInvocation(returned, pixelorama_result=pixelorama_result)


def recover_pixelorama_dispatch_execution_once(
    runtime,
    execution_id: str,
) -> CompletedDispatchInvocation:
    """Repair STARTED+bound Pixelorama execution without invoking Pixelorama again."""
    if not isinstance(execution_id, str) or not validate_id(
        execution_id, IdKind.DISPATCH_EXECUTION
    ):
        raise ProductionDispatchInvocationError(
            "execution_id must be a valid DISPEXEC ID"
        )
    try:
        execution = read_dispatch_execution(runtime, execution_id)
        binding = read_pixelorama_dispatch_output_binding(runtime, execution_id)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "PIXELORAMA_BOUND_RESULT_UNAVAILABLE"
        ) from exc
    if (
        execution.execution_owner_id != PIXELORAMA_EXECUTION_OWNER_ID
        or binding.execution_id != execution.execution_id
        or binding.claim_id != execution.claim_id
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    if execution.status is DispatchExecutionStatus.RETURNED:
        return CompletedDispatchInvocation(execution)
    if execution.status is not DispatchExecutionStatus.STARTED:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        returned = mark_dispatch_execution_returned(
            runtime,
            execution.execution_id,
            execution.revision,
            execution.claim_revision_at_start,
            _PIXELORAMA_RETURNED_DETAIL,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedDispatchInvocation(returned)
