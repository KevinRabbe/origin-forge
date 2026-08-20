from __future__ import annotations

from .ids import IdKind, validate_id
from .production_blender_dispatch_output_binding import (
    BLENDER_EXECUTION_OWNER_ID,
    BlenderDispatchOutputBindingError,
    materialize_bound_blender_result,
    read_blender_dispatch_output_binding,
)
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_claim_read import read_dispatch_claim
from .production_dispatch_execution import mark_dispatch_execution_returned
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_dispatch_invocation_blender import CompletedBlenderDispatchInvocation
from .state import TaskStatus


_BLENDER_RETURNED_DETAIL = "trusted Blender export-glb execution owner returned normally"


def _require_started_binding_authority(runtime, execution) -> None:
    """Require the exact ACTIVE-claim/RUNNING-Task relation after Blender STARTED."""
    durable_execution = read_dispatch_execution(runtime, execution.execution_id)
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if (
        durable_execution != execution
        or execution.status is not DispatchExecutionStatus.STARTED
        or execution.execution_owner_id != BLENDER_EXECUTION_OWNER_ID
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
        raise RuntimeError("Blender STARTED execution authority drifted")


def recover_blender_dispatch_execution_once(
    runtime,
    execution_id: str,
) -> CompletedBlenderDispatchInvocation:
    """Repair or reread one bound Blender execution without invoking Blender again."""
    if not isinstance(execution_id, str) or not validate_id(
        execution_id, IdKind.DISPATCH_EXECUTION
    ):
        raise ProductionDispatchInvocationError(
            "execution_id must be a valid DISPEXEC ID"
        )
    try:
        execution = read_dispatch_execution(runtime, execution_id)
        binding = read_blender_dispatch_output_binding(runtime, execution_id)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    if (
        execution.execution_owner_id != BLENDER_EXECUTION_OWNER_ID
        or binding.execution_id != execution.execution_id
        or binding.claim_id != execution.claim_id
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        blender_result = materialize_bound_blender_result(runtime, binding)
    except BlenderDispatchOutputBindingError as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc

    if execution.status is DispatchExecutionStatus.RETURNED:
        claim = read_dispatch_claim(runtime, execution.claim_id)
        task = runtime.get_task(execution.task_id)
        if (
            claim.status is not DispatchClaimStatus.CONSUMED
            or claim.revision != execution.claim_revision_at_start + 1
            or task["status"] != TaskStatus.RUNNING.value
            or int(task["revision"]) != execution.task_revision + 1
        ):
            raise ProductionDispatchInvocationRecoveryRequired(
                execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
            )
        return CompletedBlenderDispatchInvocation(
            execution,
            blender_result=blender_result,
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
            _BLENDER_RETURNED_DETAIL,
        )
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedBlenderDispatchInvocation(
        returned,
        blender_result=blender_result,
    )
