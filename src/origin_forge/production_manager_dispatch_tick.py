from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

from .ids import IdKind, validate_id
from .production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
from .production_dispatch_claims import DispatchClaimError, acquire_dispatch_claim
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from .production_dispatch_invocation_read import (
    DispatchInvocationStatus,
    ProductionDispatchInvocationReadError,
    inspect_dispatch_invocation_status_readonly,
)
from .production_manager_dispatch_admission import (
    ManagerDispatchCandidate,
    inspect_manager_dispatch_admission_readonly,
)
from .production_manager_dispatch_selection import (
    ManagerDispatchSelectionStatus,
    select_manager_dispatch_candidate,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision


class ManagerDispatchTickStatus(StrEnum):
    NO_ELIGIBLE_TASK = "NO_ELIGIBLE_TASK"
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"
    CLAIM_NOT_ACQUIRED = "CLAIM_NOT_ACQUIRED"
    CLAIM_RELATION_INVALID = "CLAIM_RELATION_INVALID"
    DISPATCH_NOT_STARTED = "DISPATCH_NOT_STARTED"
    DISPATCH_RETURNED = "DISPATCH_RETURNED"
    DISPATCH_RAISED = "DISPATCH_RAISED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class ManagerDispatchTickDetail(StrEnum):
    ADMISSION_NO_ELIGIBLE = "ADMISSION_NO_ELIGIBLE"
    ADMISSION_AMBIGUOUS = "ADMISSION_AMBIGUOUS"
    ADMISSION_LIMIT_EXCEEDED = "ADMISSION_LIMIT_EXCEEDED"
    ADMISSION_INVALID = "ADMISSION_INVALID"
    CLAIM_ACQUISITION_FAILED = "CLAIM_ACQUISITION_FAILED"
    CLAIM_RELATION_MISMATCH = "CLAIM_RELATION_MISMATCH"
    DISPATCH_PRESTART_FAILED = "DISPATCH_PRESTART_FAILED"
    DISPATCH_STATUS_UNREADABLE = "DISPATCH_STATUS_UNREADABLE"
    DISPATCH_RETURNED = "DISPATCH_RETURNED"
    DISPATCH_RAISED = "DISPATCH_RAISED"
    DISPATCH_RECOVERY_REQUIRED = "DISPATCH_RECOVERY_REQUIRED"


@dataclass(frozen=True)
class ManagerDispatchTickResult:
    status: ManagerDispatchTickStatus
    detail: ManagerDispatchTickDetail
    task_id: str | None = None
    dispatch_binding_id: str | None = None
    binding_audit_id: str | None = None
    claim_id: str | None = None
    execution_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ManagerDispatchTickStatus):
            raise TypeError("status must be a ManagerDispatchTickStatus")
        if not isinstance(self.detail, ManagerDispatchTickDetail):
            raise TypeError("detail must be a ManagerDispatchTickDetail")
        for value, kind, label in (
            (self.task_id, IdKind.TASK, "task_id"),
            (self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id"),
            (self.binding_audit_id, IdKind.DISPATCH_BINDING_AUDIT, "binding_audit_id"),
            (self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id"),
            (self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id"),
        ):
            if value is not None and (
                not isinstance(value, str) or not validate_id(value, kind)
            ):
                raise ValueError(f"{label} has wrong canonical ID kind")
        if self.status in {
            ManagerDispatchTickStatus.DISPATCH_RETURNED,
            ManagerDispatchTickStatus.DISPATCH_RAISED,
            ManagerDispatchTickStatus.RECOVERY_REQUIRED,
        } and self.claim_id is None:
            raise ValueError("execution-backed Manager result requires claim_id")
        if self.status in {
            ManagerDispatchTickStatus.DISPATCH_RETURNED,
            ManagerDispatchTickStatus.DISPATCH_RAISED,
        } and self.execution_id is None:
            raise ValueError("terminal dispatch Manager result requires execution_id")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "detail": self.detail.value,
            "task_id": self.task_id,
            "dispatch_binding_id": self.dispatch_binding_id,
            "binding_audit_id": self.binding_audit_id,
            "claim_id": self.claim_id,
            "execution_id": self.execution_id,
            "authority": "single-tick-mechanics-only",
        }


def _selection_result(status: ManagerDispatchSelectionStatus) -> ManagerDispatchTickResult:
    mapping = {
        ManagerDispatchSelectionStatus.NO_ELIGIBLE_TASK: (
            ManagerDispatchTickStatus.NO_ELIGIBLE_TASK,
            ManagerDispatchTickDetail.ADMISSION_NO_ELIGIBLE,
        ),
        ManagerDispatchSelectionStatus.AMBIGUOUS_AUTHORITY: (
            ManagerDispatchTickStatus.AMBIGUOUS_AUTHORITY,
            ManagerDispatchTickDetail.ADMISSION_AMBIGUOUS,
        ),
        ManagerDispatchSelectionStatus.LIMIT_EXCEEDED: (
            ManagerDispatchTickStatus.LIMIT_EXCEEDED,
            ManagerDispatchTickDetail.ADMISSION_LIMIT_EXCEEDED,
        ),
        ManagerDispatchSelectionStatus.INVALID_STATE: (
            ManagerDispatchTickStatus.INVALID_STATE,
            ManagerDispatchTickDetail.ADMISSION_INVALID,
        ),
    }
    target = mapping.get(status)
    if target is None:
        raise ValueError("selection status is not terminal at admission boundary")
    return ManagerDispatchTickResult(target[0], target[1])


class _ManagerDispatchCandidateFields(TypedDict):
    task_id: str
    dispatch_binding_id: str
    binding_audit_id: str


def _candidate_fields(candidate: ManagerDispatchCandidate) -> _ManagerDispatchCandidateFields:
    return {
        "task_id": candidate.task_id,
        "dispatch_binding_id": candidate.dispatch_binding_id,
        "binding_audit_id": candidate.binding_audit_id,
    }


def _claim_matches_candidate(
    claim: DispatchClaim,
    candidate: ManagerDispatchCandidate,
) -> bool:
    return (
        claim.status is DispatchClaimStatus.ACTIVE
        and claim.revision == 0
        and claim.task_id == candidate.task_id
        and claim.task_revision == candidate.task_revision
        and claim.task_content_hash == candidate.task_content_hash
        and claim.input_resolution_id == candidate.input_resolution_id
        and claim.dispatch_binding_id == candidate.dispatch_binding_id
        and claim.binding_audit_id == candidate.binding_audit_id
        and claim.work_order_hash == candidate.work_order_hash
        and claim.selected_adapter_id == candidate.selected_adapter_id
        and claim.selected_adapter_fingerprint == candidate.selected_adapter_fingerprint
        and claim.dispatch_contract_id == candidate.dispatch_contract_id
        and claim.dispatch_contract_hash == candidate.dispatch_contract_hash
        and claim.binder_id == candidate.binder_id
        and claim.binder_fingerprint == candidate.binder_fingerprint
    )


def _project_dispatch_error(
    runtime: OriginForgeRuntime,
    candidate: ManagerDispatchCandidate,
    claim: DispatchClaim,
) -> ManagerDispatchTickResult:
    fields = _candidate_fields(candidate)
    try:
        projection = inspect_dispatch_invocation_status_readonly(
            runtime,
            claim.claim_id,
        )
    except ProductionDispatchInvocationReadError:
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.RECOVERY_REQUIRED,
            ManagerDispatchTickDetail.DISPATCH_STATUS_UNREADABLE,
            claim_id=claim.claim_id,
            **fields,
        )

    if projection.claim_id != claim.claim_id or (
        projection.task_id is not None and projection.task_id != candidate.task_id
    ):
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.RECOVERY_REQUIRED,
            ManagerDispatchTickDetail.DISPATCH_RECOVERY_REQUIRED,
            claim_id=claim.claim_id,
            execution_id=projection.execution_id,
            **fields,
        )
    if projection.status is DispatchInvocationStatus.RAISED:
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.DISPATCH_RAISED,
            ManagerDispatchTickDetail.DISPATCH_RAISED,
            claim_id=claim.claim_id,
            execution_id=projection.execution_id,
            **fields,
        )
    if projection.status is DispatchInvocationStatus.READY_TO_INVOKE:
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.DISPATCH_NOT_STARTED,
            ManagerDispatchTickDetail.DISPATCH_PRESTART_FAILED,
            claim_id=claim.claim_id,
            **fields,
        )
    return ManagerDispatchTickResult(
        ManagerDispatchTickStatus.RECOVERY_REQUIRED,
        ManagerDispatchTickDetail.DISPATCH_RECOVERY_REQUIRED,
        claim_id=claim.claim_id,
        execution_id=projection.execution_id,
        **fields,
    )


def _dispatch_selected_candidate_once(
    runtime: OriginForgeRuntime,
    candidate: ManagerDispatchCandidate,
) -> ManagerDispatchTickResult:
    """Execute one exact already-admitted Phase-38 candidate and never reselect."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(candidate, ManagerDispatchCandidate):
        raise TypeError("candidate must be a ManagerDispatchCandidate")

    fields = _candidate_fields(candidate)
    try:
        claim = acquire_dispatch_claim(
            runtime,
            candidate.dispatch_binding_id,
            candidate.binding_audit_id,
            candidate.task_revision,
        )
    except (DispatchClaimError, StaleRevision):
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED,
            ManagerDispatchTickDetail.CLAIM_ACQUISITION_FAILED,
            **fields,
        )

    if not isinstance(claim, DispatchClaim) or not _claim_matches_candidate(
        claim,
        candidate,
    ):
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.CLAIM_RELATION_INVALID,
            ManagerDispatchTickDetail.CLAIM_RELATION_MISMATCH,
            claim_id=getattr(claim, "claim_id", None),
            **fields,
        )

    try:
        completed = dispatch_claim_once(runtime, claim.claim_id, claim.revision)
    except ProductionDispatchInvocationRecoveryRequired as exc:
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.RECOVERY_REQUIRED,
            ManagerDispatchTickDetail.DISPATCH_RECOVERY_REQUIRED,
            claim_id=claim.claim_id,
            execution_id=exc.execution_id,
            **fields,
        )
    except ProductionDispatchInvocationError:
        return _project_dispatch_error(runtime, candidate, claim)

    if not isinstance(completed, CompletedDispatchInvocation):
        return _project_dispatch_error(runtime, candidate, claim)
    if (
        completed.execution.claim_id != claim.claim_id
        or completed.execution.task_id != candidate.task_id
        or completed.execution.dispatch_binding_id != candidate.dispatch_binding_id
    ):
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.RECOVERY_REQUIRED,
            ManagerDispatchTickDetail.DISPATCH_RECOVERY_REQUIRED,
            claim_id=claim.claim_id,
            execution_id=completed.execution.execution_id,
            **fields,
        )
    return ManagerDispatchTickResult(
        ManagerDispatchTickStatus.DISPATCH_RETURNED,
        ManagerDispatchTickDetail.DISPATCH_RETURNED,
        claim_id=claim.claim_id,
        execution_id=completed.execution.execution_id,
        **fields,
    )


def dispatch_manager_tick(runtime: OriginForgeRuntime) -> ManagerDispatchTickResult:
    """Perform one bounded Manager admission/claim/dispatch attempt and stop."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    admission = inspect_manager_dispatch_admission_readonly(runtime)
    selection = select_manager_dispatch_candidate(admission)
    if selection.status is not ManagerDispatchSelectionStatus.ONE_SELECTED:
        return _selection_result(selection.status)
    candidate = selection.candidate
    if not isinstance(candidate, ManagerDispatchCandidate):
        return ManagerDispatchTickResult(
            ManagerDispatchTickStatus.INVALID_STATE,
            ManagerDispatchTickDetail.ADMISSION_INVALID,
        )
    return _dispatch_selected_candidate_once(runtime, candidate)
