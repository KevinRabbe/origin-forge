from __future__ import annotations

from . import _production_dispatch_invocation_pixelorama_core as core
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
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
from .production_dispatch_invocation_blender import (
    dispatch_blender_claim_once_if_applicable,
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
from .production_pixelorama_dispatch_output_currentness import (
    PixeloramaDispatchOutputCurrentnessStatus,
    inspect_pixelorama_dispatch_output_currentness_readonly,
    materialize_bound_pixelorama_result,
)
from .service import utc_now
from .state import TaskStatus

PixeloramaInvocationRequest = core.PixeloramaInvocationRequest
_decode_pixelorama_request_projection = core._decode_pixelorama_request_projection
_require_trusted_pixelorama_relation = core._require_trusted_pixelorama_relation
_safe_source_path = core._safe_source_path
_require_pixelorama_result_durable = core._require_pixelorama_result_durable
_PIXELORAMA_OWNER_ID = core._PIXELORAMA_OWNER_ID
_PIXELORAMA_RETURNED_DETAIL = core._PIXELORAMA_RETURNED_DETAIL
_MAX_OUTPUT_BYTES = core._MAX_OUTPUT_BYTES


def _require_started_binding_authority(runtime, execution) -> None:
    """Require the exact ACTIVE-claim/RUNNING-Task relation after Pixelorama STARTED."""
    durable_execution = read_dispatch_execution(runtime, execution.execution_id)
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if (
        durable_execution != execution
        or execution.status is not DispatchExecutionStatus.STARTED
        or execution.execution_owner_id != PIXELORAMA_EXECUTION_OWNER_ID
        or claim.status is not DispatchClaimStatus.ACTIVE
        or claim.revision != execution.claim_revision_at_start
        or claim.terminal_reason is not None
        or claim.project_id != execution.project_id
        or claim.claim_id != execution.claim_id
        or claim.task_id != execution.task_id
        or claim.task_revision != execution.task_revision
        or claim.task_content_hash != execution.task_content_hash
        or claim.work_order_id != execution.work_order_id
        or claim.work_order_hash != execution.work_order_hash
        or claim.input_resolution_id != execution.input_resolution_id
        or claim.input_resolution_hash != execution.input_resolution_hash
        or claim.dispatch_binding_id != execution.dispatch_binding_id
        or claim.dispatch_binding_hash != execution.dispatch_binding_hash
        or claim.binding_audit_id != execution.binding_audit_id
        or claim.binding_audit_hash != execution.binding_audit_hash
        or claim.selected_adapter_id != execution.selected_adapter_id
        or claim.selected_adapter_fingerprint != execution.selected_adapter_fingerprint
        or claim.dispatch_contract_id != execution.dispatch_contract_id
        or claim.dispatch_contract_hash != execution.dispatch_contract_hash
        or claim.binder_id != execution.binder_id
        or claim.binder_fingerprint != execution.binder_fingerprint
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != execution.task_revision + 1
    ):
        raise RuntimeError("Pixelorama STARTED execution authority drifted")


def _publish_result_binding(
    runtime,
    execution,
    frozen_request,
    concrete_request,
    pixelorama_result,
    payload,
) -> PixeloramaDispatchOutputBinding:
    """Revalidate and publish the exact Phase-48 result before RETURNED terminalization."""
    try:
        _require_started_binding_authority(runtime, execution)
        core._require_pixelorama_result_durable(
            runtime,
            frozen_request,
            concrete_request,
            pixelorama_result,
            payload,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "OWNER_RETURN_CONTRACT_MISMATCH",
        ) from exc

    try:
        existing = read_pixelorama_dispatch_output_binding(runtime, execution.execution_id)
    except PixeloramaDispatchOutputBindingReadError:
        existing = None

    lineage = OriginForgeLineage(runtime)
    try:
        output_artifact = lineage.get_artifact(pixelorama_result.output_artifact_id)
        output_path = lineage.local_artifact_path(pixelorama_result.output_artifact_id)
        output_byte_count = output_path.stat().st_size
        stored_output_hash = output_artifact["content_hash"]
    except (KeyError, OSError, RuntimeError) as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "RETURNED_TERMINALIZATION_FAILED",
        ) from exc
    if (
        not isinstance(stored_output_hash, str)
        or not stored_output_hash.startswith("sha256:")
        or len(stored_output_hash) != 71
        or any(ch not in "0123456789abcdef" for ch in stored_output_hash[7:])
        or stored_output_hash != pixelorama_result.operation.output_hash
        or output_byte_count != pixelorama_result.operation.output_byte_count
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "OWNER_RETURN_CONTRACT_MISMATCH",
        )

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
        output_content_hash=stored_output_hash[7:],
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
            "RETURNED_TERMINALIZATION_FAILED",
        ) from exc
    if published != candidate or reread != candidate:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "RETURNED_TERMINALIZATION_FAILED",
        )
    return reread


def _dispatch_claim_once_three_owner(
    runtime,
    claim_id: str,
    expected_claim_revision: int,
) -> CompletedDispatchInvocation:
    """Single-shot coordinator with reviewed Pixelorama and Blender fanout."""
    import origin_forge.production_dispatch_invocation as legacy

    from .production_dispatch_invocation_image_owner import (
        dispatch_image_claim_once_if_applicable,
    )
    from .production_dispatch_invocation_piper_owner import (
        dispatch_piper_claim_once_if_applicable,
    )
    from .production_dispatch_invocation_playtest_owner import (
        dispatch_playtest_claim_once_if_applicable,
    )
    from .production_dispatch_invocation_runtime_owner import (
        dispatch_runtime_claim_once_if_applicable,
    )

    piper = dispatch_piper_claim_once_if_applicable(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    if piper is not None:
        return piper

    runtime_observation = dispatch_runtime_claim_once_if_applicable(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    if runtime_observation is not None:
        return runtime_observation

    playtest = dispatch_playtest_claim_once_if_applicable(
        runtime, claim_id, expected_claim_revision
    )
    if playtest is not None:
        return playtest

    image = dispatch_image_claim_once_if_applicable(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    if image is not None:
        return image

    blender = dispatch_blender_claim_once_if_applicable(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    if blender is not None:
        return blender

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

    _publish_result_binding(
        runtime,
        execution,
        request,
        concrete_request,
        pixelorama_result,
        payload,
    )
    returned = legacy._record_returned_or_recovery(
        runtime, started, frozen_claim, detail=_PIXELORAMA_RETURNED_DETAIL
    )
    return CompletedDispatchInvocation(returned, pixelorama_result=pixelorama_result)


def recover_pixelorama_dispatch_execution_once(
    runtime,
    execution_id: str,
) -> CompletedDispatchInvocation:
    """Repair or reread one bound Pixelorama execution without invoking Pixelorama again."""
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
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    if (
        execution.execution_owner_id != PIXELORAMA_EXECUTION_OWNER_ID
        or binding.execution_id != execution.execution_id
        or binding.claim_id != execution.claim_id
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        pixelorama_result = materialize_bound_pixelorama_result(runtime, binding)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc

    if execution.status is DispatchExecutionStatus.RETURNED:
        currentness = inspect_pixelorama_dispatch_output_currentness_readonly(
            runtime, execution_id
        )
        if currentness.status is not PixeloramaDispatchOutputCurrentnessStatus.ELIGIBLE:
            raise ProductionDispatchInvocationRecoveryRequired(
                execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
            )
        return CompletedDispatchInvocation(
            execution,
            pixelorama_result=pixelorama_result,
        )
    if execution.status is not DispatchExecutionStatus.STARTED:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        _require_started_binding_authority(runtime, execution)
        returned = mark_dispatch_execution_returned(
            runtime,
            execution.execution_id,
            execution.revision,
            execution.claim_revision_at_start,
            _PIXELORAMA_RETURNED_DETAIL,
        )
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedDispatchInvocation(
        returned,
        pixelorama_result=pixelorama_result,
    )
