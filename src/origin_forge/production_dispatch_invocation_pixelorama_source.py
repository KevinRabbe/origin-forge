from __future__ import annotations

from pathlib import Path

from .ids import IdKind, validate_id
from .pixelorama_media import PixeloramaMediaResult, PixeloramaMediaService
from .production_capability_store import ProductionCapabilityStore
from .production_dispatch_binding import build_pixelorama_source_dispatch_binder_registry
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_claim_read import read_dispatch_claim, read_input_resolution
from .production_dispatch_execution import mark_dispatch_execution_returned
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_execution_assembly import PixeloramaSourceCreationExecutionPayload
from .production_pixelorama_source_dispatch_output_binding import (
    PixeloramaSourceOutputBindingError,
    binding_from_pixelorama_source_result,
    materialize_pixelorama_source_result,
    publish_pixelorama_source_dispatch_output_binding,
    read_pixelorama_source_dispatch_output_binding,
)
from .production_pixelorama_source_request import decode_pixelorama_source_request
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_store import ProductionWorkOrderStore
from .runtime import OriginForgeRuntime
from .service import utc_now
from .state import TaskStatus


PIXELORAMA_SOURCE_EXECUTION_OWNER_ID = "originforge.execution.pixelorama.source-create@1"
PIXELORAMA_SOURCE_REQUEST_TYPE_ID = "PixeloramaSourceService.create@production-v1"
PIXELORAMA_SOURCE_RETURNED_DETAIL = (
    "trusted Pixelorama source-create execution owner returned normally"
)


def _read_source_request(runtime, claim_id, expected_claim_revision):
    import origin_forge.production_dispatch_invocation as legacy

    claim, binding = legacy._read_frozen_request_evidence(
        runtime, claim_id, expected_claim_revision
    )
    if binding.request_type_id != PIXELORAMA_SOURCE_REQUEST_TYPE_ID:
        return None
    bundle = read_input_resolution(runtime, claim.input_resolution_id)
    work_order = ProductionWorkOrderStore(
        runtime,
        ProductionCapabilityStore(runtime),
        build_builtin_dispatch_validator_registry(),
    ).load_work_order(claim.work_order_id)
    binder = build_pixelorama_source_dispatch_binder_registry().binder_for(bundle)
    projection = binder.bind(work_order, bundle)
    if not isinstance(projection, dict):
        raise ProductionDispatchInvocationError(
            "Pixelorama source binder returned the wrong projection type"
        )
    try:
        request = decode_pixelorama_source_request(
            work_order.task_id,
            projection,
            bundle.resolved_inputs[0].projection,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama source binder projection could not be decoded"
        ) from exc
    return claim, binding, request


def _require_started_source_authority(runtime, execution) -> None:
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if (
        read_dispatch_execution(runtime, execution.execution_id) != execution
        or execution.status is not DispatchExecutionStatus.STARTED
        or execution.execution_owner_id != PIXELORAMA_SOURCE_EXECUTION_OWNER_ID
        or claim.status is not DispatchClaimStatus.ACTIVE
        or claim.revision != execution.claim_revision_at_start
        or claim.claim_id != execution.claim_id
        or claim.task_id != execution.task_id
        or claim.task_revision != execution.task_revision
        or claim.task_content_hash != execution.task_content_hash
        or claim.work_order_id != execution.work_order_id
        or claim.work_order_hash != execution.work_order_hash
        or claim.dispatch_binding_id != execution.dispatch_binding_id
        or claim.dispatch_binding_hash != execution.dispatch_binding_hash
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != execution.task_revision + 1
    ):
        raise RuntimeError("Pixelorama source STARTED execution authority drifted")


def _safe_output_bytes(runtime: OriginForgeRuntime, result: PixeloramaMediaResult) -> tuple[int, ...]:
    counts: list[int] = []
    root = runtime.project_root.resolve()
    for output in result.output_evidence:
        path = result.operation.workspace_path / Path(output.relative_path)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Pixelorama source output is not a regular file")
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise RuntimeError("Pixelorama source output escaped project state") from exc
        counts.append(path.stat().st_size)
    return tuple(counts)


def dispatch_pixelorama_source_claim_once_if_applicable(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_claim_revision: int,
) -> CompletedDispatchInvocation | None:
    import origin_forge.production_dispatch_invocation as legacy

    frozen = _read_source_request(runtime, claim_id, expected_claim_revision)
    if frozen is None:
        return None
    claim, binding, request = frozen
    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    execution = started.execution
    payload = started.dependencies.payload
    if not isinstance(payload, PixeloramaSourceCreationExecutionPayload):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "STARTED_RELATION_MISMATCH"
        )
    if (
        execution.execution_owner_id != PIXELORAMA_SOURCE_EXECUTION_OWNER_ID
        or started.dependencies.plan.request_type_id != PIXELORAMA_SOURCE_REQUEST_TYPE_ID
        or started.dependencies.plan.request_content_hash != binding.request_content_hash
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        from .production_design_specification_currentness import (
            bridge_accepted_design_to_planning_input,
        )

        planning_input = bridge_accepted_design_to_planning_input(
            runtime, request.accepted_design_id
        )
        if request.planning_input_id is not None and request.planning_input_id != planning_input.planning_input_id:
            raise RuntimeError("Pixelorama source PlanningInput identity drifted")
        concrete_request = request.to_bridge_request()
        result = PixeloramaMediaService(runtime, payload.profile).execute(
            request.task_id,
            concrete_request,
            accepted_design_lineage={
                "acceptance_id": request.accepted_design_id,
                "acceptance_hash": request.accepted_design_hash,
                "design_input_id": request.design_input_id,
                "planning_input_id": planning_input.planning_input_id,
                "planning_input_hash": planning_input.content_hash,
            },
        )
    except Exception as exc:
        exception_type = legacy._exception_type_commitment(exc)
        legacy._record_raised_or_recovery(
            runtime,
            started,
            claim,
            detail=f"trusted Pixelorama source-create execution owner raised {exception_type}",
        )
        raise ProductionDispatchInvocationError(
            "trusted Pixelorama source-create execution owner raised "
            f"{exception_type}; dispatch execution {execution.execution_id} recorded RAISED"
        ) from exc

    try:
        run_verifications = runtime.list_verifications("RUN", result.run_id)
        if len(run_verifications) != 1 or run_verifications[0]["status"] != "PASS":
            raise RuntimeError("Pixelorama source run verification is not exact PASS")
        candidate = binding_from_pixelorama_source_result(
            execution,
            result,
            output_byte_counts=_safe_output_bytes(runtime, result),
            run_verification_id=run_verifications[0]["id"],
            created_at=utc_now(),
        )
        published = publish_pixelorama_source_dispatch_output_binding(runtime, candidate)
        reread = read_pixelorama_source_dispatch_output_binding(runtime, execution.execution_id)
        if published != candidate or reread != candidate:
            raise RuntimeError("Pixelorama source output binding changed during publication")
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc

    returned = legacy._record_returned_or_recovery(
        runtime, started, claim, detail=PIXELORAMA_SOURCE_RETURNED_DETAIL
    )
    return CompletedDispatchInvocation(returned, pixelorama_source_result=result)


def recover_pixelorama_source_dispatch_execution_once(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> CompletedDispatchInvocation:
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise ProductionDispatchInvocationError("execution_id must be a valid DISPEXEC ID")
    execution = read_dispatch_execution(runtime, execution_id)
    if execution.execution_owner_id != PIXELORAMA_SOURCE_EXECUTION_OWNER_ID:
        raise ProductionDispatchInvocationError("execution is not a Pixelorama source execution")
    try:
        binding = read_pixelorama_source_dispatch_output_binding(runtime, execution_id)
    except PixeloramaSourceOutputBindingError as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    try:
        result = materialize_pixelorama_source_result(runtime, binding)
        _require_started_source_authority(runtime, execution) if execution.status is DispatchExecutionStatus.STARTED else None
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    if execution.status is DispatchExecutionStatus.RETURNED:
        return CompletedDispatchInvocation(execution, pixelorama_source_result=result)
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
            PIXELORAMA_SOURCE_RETURNED_DETAIL,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedDispatchInvocation(returned, pixelorama_source_result=result)
