from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_preparation_activation import activate_and_checkpoint_preparation
from .production_preparation_activation_recovery import adopt_legacy_preparation_activation
from .production_preparation_models import TaskPreparationReceipt
from .production_preparation_planner_evidence import (
    PlannerEvidenceRecovery,
    PlannerEvidenceRecoveryStatus,
    recover_planner_evidence,
)
from .production_preparation_planner_resume import (
    PreparationPlannerResumeResult,
    PreparationPlannerResumeStatus,
    resume_routed_preparation_planner_once,
)
from .production_preparation_recovery import (
    PreparationRecoveryProjection,
    PreparationRecoveryReadError,
    PreparationRecoveryState,
    inspect_preparation_recovery_readonly,
)
from .production_preparation_route_recovery import recover_and_checkpoint_preparation_route
from .production_read_guard import ProductionReadGuardError
from .runtime import OriginForgeRuntime


class PreparationRecoveryOnceStatus(StrEnum):
    RECOVERED_ACTIVATED = "RECOVERED_ACTIVATED"
    ADOPTED_ACTIVATION_CHECKPOINT = "ADOPTED_ACTIVATION_CHECKPOINT"
    RECOVERED_ROUTED = "RECOVERED_ROUTED"
    RESUMED_PLANNER_RETURNED = "RESUMED_PLANNER_RETURNED"
    RECOVERED_PLANNER_RETURNED = "RECOVERED_PLANNER_RETURNED"
    PLANNER_RECOVERY_REQUIRED = "PLANNER_RECOVERY_REQUIRED"
    ACTIVATION_RECOVERY_REJECTED = "ACTIVATION_RECOVERY_REJECTED"
    ROUTE_RECOVERY_REJECTED = "ROUTE_RECOVERY_REJECTED"
    INVALID_AUTHORITY = "INVALID_AUTHORITY"
    INVALID_STATE = "INVALID_STATE"
    AMBIGUOUS_EVIDENCE = "AMBIGUOUS_EVIDENCE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    POST_PLANNER_NOT_REQUIRED = "POST_PLANNER_NOT_REQUIRED"
    READY_NOT_REQUIRED = "READY_NOT_REQUIRED"
    TERMINAL_NOT_REQUIRED = "TERMINAL_NOT_REQUIRED"


@dataclass(frozen=True)
class PreparationRecoveryOnceResult:
    status: PreparationRecoveryOnceStatus
    preparation_id: str
    task_id: str | None
    classification: PreparationRecoveryProjection | None
    receipt: TaskPreparationReceipt | None
    lower_status: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "preparation_id": self.preparation_id,
            "task_id": self.task_id,
            "classification": None if self.classification is None else self.classification.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "lower_status": self.lower_status,
            "detail": self.detail,
            "authority": "single-preparation-recovery-mechanics-only",
        }


def _result(status, preparation_id, classification, receipt=None, lower_status=None, detail=None):
    task_id = None if classification is None else classification.task_id
    if receipt is not None:
        task_id = receipt.task_id
    return PreparationRecoveryOnceResult(
        status, preparation_id, task_id, classification, receipt, lower_status, detail
    )


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:4096]


def recover_preparation_once(runtime: OriginForgeRuntime, preparation_id: str) -> PreparationRecoveryOnceResult:
    """Perform at most one already-governed recovery action for one explicit PREP."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(preparation_id, str):
        raise TypeError("preparation_id must be a string")
    try:
        projection = inspect_preparation_recovery_readonly(runtime, preparation_id)
    except (PreparationRecoveryReadError, ProductionReadGuardError, KeyError, ValueError) as exc:
        return _result(PreparationRecoveryOnceStatus.INVALID_AUTHORITY, preparation_id, None, detail=_detail(exc))

    state = projection.state
    revision = projection.receipt_revision
    if state is PreparationRecoveryState.RESUMABLE_CLAIMED:
        try:
            receipt = activate_and_checkpoint_preparation(runtime, preparation_id, revision)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            return _result(PreparationRecoveryOnceStatus.ACTIVATION_RECOVERY_REJECTED, preparation_id, projection, lower_status=state.value, detail=_detail(exc))
        return _result(PreparationRecoveryOnceStatus.RECOVERED_ACTIVATED, preparation_id, projection, receipt, state.value)

    if state is PreparationRecoveryState.ADOPTABLE_ACTIVATION_CHECKPOINT:
        try:
            receipt = adopt_legacy_preparation_activation(runtime, preparation_id, revision)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            return _result(PreparationRecoveryOnceStatus.ACTIVATION_RECOVERY_REJECTED, preparation_id, projection, lower_status=state.value, detail=_detail(exc))
        return _result(PreparationRecoveryOnceStatus.ADOPTED_ACTIVATION_CHECKPOINT, preparation_id, projection, receipt, state.value)

    if state is PreparationRecoveryState.RESUMABLE_ACTIVATED:
        try:
            receipt = recover_and_checkpoint_preparation_route(runtime, preparation_id, revision)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            return _result(PreparationRecoveryOnceStatus.ROUTE_RECOVERY_REJECTED, preparation_id, projection, lower_status=state.value, detail=_detail(exc))
        return _result(PreparationRecoveryOnceStatus.RECOVERED_ROUTED, preparation_id, projection, receipt, state.value)

    if state is PreparationRecoveryState.RESUMABLE_ROUTED:
        try:
            lower = resume_routed_preparation_planner_once(runtime, preparation_id, revision)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            return _result(PreparationRecoveryOnceStatus.INVALID_AUTHORITY, preparation_id, projection, lower_status=state.value, detail=_detail(exc))
        if not isinstance(lower, PreparationPlannerResumeResult):
            return _result(PreparationRecoveryOnceStatus.INVALID_STATE, preparation_id, projection, lower_status=state.value, detail="planner resume returned invalid result type")
        mapping = {
            PreparationPlannerResumeStatus.PLANNER_RETURNED: PreparationRecoveryOnceStatus.RESUMED_PLANNER_RETURNED,
            PreparationPlannerResumeStatus.PLANNER_RECOVERY_REQUIRED: PreparationRecoveryOnceStatus.PLANNER_RECOVERY_REQUIRED,
            PreparationPlannerResumeStatus.INVALID_AUTHORITY: PreparationRecoveryOnceStatus.INVALID_AUTHORITY,
        }
        return _result(mapping[lower.status], preparation_id, projection, lower.receipt, lower.status.value, lower.detail)

    if state is PreparationRecoveryState.PLANNER_EVIDENCE_ONLY:
        try:
            lower = recover_planner_evidence(runtime, preparation_id)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            return _result(PreparationRecoveryOnceStatus.PLANNER_RECOVERY_REQUIRED, preparation_id, projection, lower_status=state.value, detail=_detail(exc))
        if not isinstance(lower, PlannerEvidenceRecovery):
            return _result(PreparationRecoveryOnceStatus.INVALID_STATE, preparation_id, projection, lower_status=state.value, detail="planner evidence recovery returned invalid result type")
        mapping = {
            PlannerEvidenceRecoveryStatus.EXACT_RETURN: PreparationRecoveryOnceStatus.RECOVERED_PLANNER_RETURNED,
            PlannerEvidenceRecoveryStatus.RECOVERED_PLANNER_RETURNED: PreparationRecoveryOnceStatus.RECOVERED_PLANNER_RETURNED,
            PlannerEvidenceRecoveryStatus.UNRESOLVED: PreparationRecoveryOnceStatus.PLANNER_RECOVERY_REQUIRED,
            PlannerEvidenceRecoveryStatus.AMBIGUOUS: PreparationRecoveryOnceStatus.AMBIGUOUS_EVIDENCE,
            PlannerEvidenceRecoveryStatus.LIMIT_EXCEEDED: PreparationRecoveryOnceStatus.LIMIT_EXCEEDED,
            PlannerEvidenceRecoveryStatus.INVALID_STATE: PreparationRecoveryOnceStatus.INVALID_STATE,
        }
        return _result(mapping[lower.status], preparation_id, projection, lower.receipt, lower.status.value, lower.detail)

    mapping = {
        PreparationRecoveryState.POST_PLANNER_NOT_REQUIRED: PreparationRecoveryOnceStatus.POST_PLANNER_NOT_REQUIRED,
        PreparationRecoveryState.READY_NOT_REQUIRED: PreparationRecoveryOnceStatus.READY_NOT_REQUIRED,
        PreparationRecoveryState.TERMINAL_NOT_REQUIRED: PreparationRecoveryOnceStatus.TERMINAL_NOT_REQUIRED,
        PreparationRecoveryState.AMBIGUOUS_EVIDENCE: PreparationRecoveryOnceStatus.AMBIGUOUS_EVIDENCE,
        PreparationRecoveryState.STALE_OR_INVALID: PreparationRecoveryOnceStatus.INVALID_AUTHORITY,
    }
    return _result(
        mapping.get(state, PreparationRecoveryOnceStatus.INVALID_STATE),
        preparation_id,
        projection,
        lower_status=state.value,
        detail=projection.detail,
    )
