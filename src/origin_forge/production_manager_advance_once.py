from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceCandidate,
    inspect_manager_advance_admission_readonly,
)
from .production_manager_advance_selection import (
    ManagerAdvanceSelectionStatus,
    select_manager_advance_candidate,
)
from .production_manager_dispatch_tick import (
    ManagerDispatchTickResult,
    ManagerDispatchTickStatus,
    _dispatch_selected_candidate_once,
)
from .production_preparation_phase34_finalize import (
    PreparationPhase34FinalizeStatus,
    finalize_preparation_phase34,
)
from .production_preparation_tick import (
    PreparationTickResult,
    PreparationTickStatus,
    _prepare_selected_candidate_once,
)
from .production_preparation_work_order_finalize import (
    PreparationWorkOrderFinalizeStatus,
    finalize_preparation_work_order_audit,
)
from .runtime import OriginForgeRuntime


class ManagerAdvanceOnceStatus(StrEnum):
    NO_ACTIONABLE_WORK = "NO_ACTIONABLE_WORK"
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    PREPARATION_NOT_ACQUIRED = "PREPARATION_NOT_ACQUIRED"
    PREPARATION_FAILED_PRE_PLANNER = "PREPARATION_FAILED_PRE_PLANNER"
    PREPARATION_PLANNER_RETURNED = "PREPARATION_PLANNER_RETURNED"
    PREPARATION_PLANNER_RECOVERY_REQUIRED = "PREPARATION_PLANNER_RECOVERY_REQUIRED"
    WORK_ORDER_AUDITED = "WORK_ORDER_AUDITED"
    PHASE34_READY = "PHASE34_READY"
    DISPATCH_CLAIM_NOT_ACQUIRED = "DISPATCH_CLAIM_NOT_ACQUIRED"
    DISPATCH_NOT_STARTED = "DISPATCH_NOT_STARTED"
    DISPATCH_RETURNED = "DISPATCH_RETURNED"
    DISPATCH_RAISED = "DISPATCH_RAISED"
    DISPATCH_RECOVERY_REQUIRED = "DISPATCH_RECOVERY_REQUIRED"


@dataclass(frozen=True)
class ManagerAdvanceOnceResult:
    status: ManagerAdvanceOnceStatus
    action_kind: ManagerAdvanceActionKind | None
    task_id: str | None
    task_created_at: str | None
    preparation_policy_id: str | None = None
    preparation_id: str | None = None
    dispatch_binding_id: str | None = None
    binding_audit_id: str | None = None
    claim_id: str | None = None
    execution_id: str | None = None
    lower_status: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "action_kind": None if self.action_kind is None else self.action_kind.value,
            "task_id": self.task_id,
            "task_created_at": self.task_created_at,
            "preparation_policy_id": self.preparation_policy_id,
            "preparation_id": self.preparation_id,
            "dispatch_binding_id": self.dispatch_binding_id,
            "binding_audit_id": self.binding_audit_id,
            "claim_id": self.claim_id,
            "execution_id": self.execution_id,
            "lower_status": self.lower_status,
            "detail": self.detail,
            "authority": "single-manager-action-mechanics-only",
        }


def _selection_result(status: ManagerAdvanceSelectionStatus, detail: str | None) -> ManagerAdvanceOnceResult:
    mapping = {
        ManagerAdvanceSelectionStatus.NO_ACTIONABLE_WORK: ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK,
        ManagerAdvanceSelectionStatus.AMBIGUOUS_AUTHORITY: ManagerAdvanceOnceStatus.AMBIGUOUS_AUTHORITY,
        ManagerAdvanceSelectionStatus.LIMIT_EXCEEDED: ManagerAdvanceOnceStatus.LIMIT_EXCEEDED,
        ManagerAdvanceSelectionStatus.INVALID_STATE: ManagerAdvanceOnceStatus.INVALID_STATE,
    }
    target = mapping.get(status)
    if target is None:
        target = ManagerAdvanceOnceStatus.INVALID_STATE
        detail = detail or f"unexpected selection status: {status.value}"
    return ManagerAdvanceOnceResult(target, None, None, None, detail=detail)


def _candidate_fields(candidate: ManagerAdvanceCandidate) -> dict[str, object]:
    return {
        "action_kind": candidate.action_kind,
        "task_id": candidate.task_id,
        "task_created_at": candidate.task_created_at,
        "preparation_policy_id": (
            None
            if candidate.preparation_policy is None
            else candidate.preparation_policy.preparation_policy_id
        ),
        "preparation_id": candidate.preparation_id,
        "dispatch_binding_id": (
            None
            if candidate.dispatch_candidate is None
            else candidate.dispatch_candidate.dispatch_binding_id
        ),
        "binding_audit_id": (
            None
            if candidate.dispatch_candidate is None
            else candidate.dispatch_candidate.binding_audit_id
        ),
    }


def _invalid_candidate(candidate: ManagerAdvanceCandidate, detail: str) -> ManagerAdvanceOnceResult:
    return ManagerAdvanceOnceResult(
        ManagerAdvanceOnceStatus.INVALID_STATE,
        **_candidate_fields(candidate),
        detail=detail,
    )


def _project_dispatch(
    candidate: ManagerAdvanceCandidate,
    result: object,
) -> ManagerAdvanceOnceResult:
    if not isinstance(result, ManagerDispatchTickResult):
        return _invalid_candidate(candidate, "pinned Phase-38 helper returned invalid result type")
    mapping = {
        ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED: ManagerAdvanceOnceStatus.DISPATCH_CLAIM_NOT_ACQUIRED,
        ManagerDispatchTickStatus.CLAIM_RELATION_INVALID: ManagerAdvanceOnceStatus.DISPATCH_RECOVERY_REQUIRED,
        ManagerDispatchTickStatus.DISPATCH_NOT_STARTED: ManagerAdvanceOnceStatus.DISPATCH_NOT_STARTED,
        ManagerDispatchTickStatus.DISPATCH_RETURNED: ManagerAdvanceOnceStatus.DISPATCH_RETURNED,
        ManagerDispatchTickStatus.DISPATCH_RAISED: ManagerAdvanceOnceStatus.DISPATCH_RAISED,
        ManagerDispatchTickStatus.RECOVERY_REQUIRED: ManagerAdvanceOnceStatus.DISPATCH_RECOVERY_REQUIRED,
    }
    status = mapping.get(result.status)
    if status is None:
        return _invalid_candidate(
            candidate,
            f"pinned Phase-38 helper returned impossible status {result.status.value}",
        )
    detail = result.detail.value
    return ManagerAdvanceOnceResult(
        status,
        **_candidate_fields(candidate),
        claim_id=result.claim_id,
        execution_id=result.execution_id,
        lower_status=result.status.value,
        detail=detail,
    )


def _project_preparation(
    candidate: ManagerAdvanceCandidate,
    result: object,
) -> ManagerAdvanceOnceResult:
    if not isinstance(result, PreparationTickResult):
        return _invalid_candidate(candidate, "pinned Phase-39 helper returned invalid result type")
    mapping = {
        PreparationTickStatus.PREPARATION_NOT_ACQUIRED: ManagerAdvanceOnceStatus.PREPARATION_NOT_ACQUIRED,
        PreparationTickStatus.FAILED_PRE_PLANNER: ManagerAdvanceOnceStatus.PREPARATION_FAILED_PRE_PLANNER,
        PreparationTickStatus.PLANNER_RECOVERY_REQUIRED: ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RECOVERY_REQUIRED,
        PreparationTickStatus.PLANNER_RETURNED: ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
    }
    status = mapping.get(result.status)
    if status is None:
        return _invalid_candidate(
            candidate,
            f"pinned Phase-39 helper returned impossible status {result.status.value}",
        )
    fields = _candidate_fields(candidate)
    fields["preparation_id"] = result.preparation_id
    return ManagerAdvanceOnceResult(
        status,
        **fields,
        lower_status=result.status.value,
        detail=result.detail,
    )


def _project_work_order_finalize(
    candidate: ManagerAdvanceCandidate,
    result: object,
) -> ManagerAdvanceOnceResult:
    status_value = getattr(result, "status", None)
    if not isinstance(status_value, PreparationWorkOrderFinalizeStatus):
        return _invalid_candidate(candidate, "Phase-39 WorkOrder finalizer returned invalid status")
    mapping = {
        PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED: ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
        PreparationWorkOrderFinalizeStatus.ALREADY_AUDITED: ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
        PreparationWorkOrderFinalizeStatus.PLANNER_UNRESOLVED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
        PreparationWorkOrderFinalizeStatus.INVALID_STATE: ManagerAdvanceOnceStatus.INVALID_STATE,
        PreparationWorkOrderFinalizeStatus.INVALID_AUTHORITY: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
        PreparationWorkOrderFinalizeStatus.AMBIGUOUS_AUDIT: ManagerAdvanceOnceStatus.AMBIGUOUS_AUTHORITY,
        PreparationWorkOrderFinalizeStatus.LIMIT_EXCEEDED: ManagerAdvanceOnceStatus.LIMIT_EXCEEDED,
        PreparationWorkOrderFinalizeStatus.RECOVERY_REQUIRED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
    }
    return ManagerAdvanceOnceResult(
        mapping[status_value],
        **_candidate_fields(candidate),
        lower_status=status_value.value,
        detail=getattr(result, "detail", None),
    )


def _project_phase34_finalize(
    candidate: ManagerAdvanceCandidate,
    result: object,
) -> ManagerAdvanceOnceResult:
    status_value = getattr(result, "status", None)
    if not isinstance(status_value, PreparationPhase34FinalizeStatus):
        return _invalid_candidate(candidate, "Phase-39 Phase-34 finalizer returned invalid status")
    mapping = {
        PreparationPhase34FinalizeStatus.BOUND_READY: ManagerAdvanceOnceStatus.PHASE34_READY,
        PreparationPhase34FinalizeStatus.ALREADY_READY: ManagerAdvanceOnceStatus.PHASE34_READY,
        PreparationPhase34FinalizeStatus.INVALID_STATE: ManagerAdvanceOnceStatus.INVALID_STATE,
        PreparationPhase34FinalizeStatus.INVALID_AUTHORITY: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
        PreparationPhase34FinalizeStatus.LIMIT_EXCEEDED: ManagerAdvanceOnceStatus.LIMIT_EXCEEDED,
        PreparationPhase34FinalizeStatus.RECOVERY_REQUIRED: ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
    }
    return ManagerAdvanceOnceResult(
        mapping[status_value],
        **_candidate_fields(candidate),
        lower_status=status_value.value,
        detail=getattr(result, "detail", None),
    )


def advance_production_manager_once(runtime: OriginForgeRuntime) -> ManagerAdvanceOnceResult:
    """Perform one immutable admission, one selection, one governed action, then stop."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    admission = inspect_manager_advance_admission_readonly(runtime)
    selection = select_manager_advance_candidate(admission)
    if selection.status is not ManagerAdvanceSelectionStatus.ONE_SELECTED:
        return _selection_result(selection.status, selection.detail)
    candidate = selection.candidate
    if not isinstance(candidate, ManagerAdvanceCandidate):
        return ManagerAdvanceOnceResult(
            ManagerAdvanceOnceStatus.INVALID_STATE,
            None,
            None,
            None,
            detail="selection did not return a typed ManagerAdvanceCandidate",
        )

    if candidate.action_kind is ManagerAdvanceActionKind.RECOVERY_REQUIRED:
        return ManagerAdvanceOnceResult(
            ManagerAdvanceOnceStatus.RECOVERY_REQUIRED,
            **_candidate_fields(candidate),
            detail=candidate.detail,
        )

    if candidate.action_kind is ManagerAdvanceActionKind.DISPATCH:
        if candidate.dispatch_candidate is None:
            return _invalid_candidate(candidate, "DISPATCH candidate lacks pinned Phase-38 authority")
        return _project_dispatch(
            candidate,
            _dispatch_selected_candidate_once(runtime, candidate.dispatch_candidate),
        )

    if candidate.action_kind is ManagerAdvanceActionKind.PREPARE:
        if candidate.preparation_policy is None or candidate.preparation_candidate is None:
            return _invalid_candidate(candidate, "PREPARE candidate lacks pinned Phase-39 authority")
        return _project_preparation(
            candidate,
            _prepare_selected_candidate_once(
                runtime,
                candidate.preparation_policy,
                candidate.preparation_candidate,
            ),
        )

    if candidate.action_kind is ManagerAdvanceActionKind.FINALIZE_WORK_ORDER:
        if candidate.preparation_id is None:
            return _invalid_candidate(candidate, "FINALIZE_WORK_ORDER candidate lacks PREP ID")
        return _project_work_order_finalize(
            candidate,
            finalize_preparation_work_order_audit(runtime, candidate.preparation_id),
        )

    if candidate.action_kind is ManagerAdvanceActionKind.FINALIZE_PHASE34:
        if candidate.preparation_id is None:
            return _invalid_candidate(candidate, "FINALIZE_PHASE34 candidate lacks PREP ID")
        return _project_phase34_finalize(
            candidate,
            finalize_preparation_phase34(runtime, candidate.preparation_id),
        )

    return _invalid_candidate(candidate, f"unsupported Manager action {candidate.action_kind.value}")
