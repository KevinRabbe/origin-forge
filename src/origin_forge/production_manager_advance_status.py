from __future__ import annotations

from dataclasses import dataclass

from .production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmissionStatus,
    inspect_manager_advance_admission_readonly,
)
from .production_manager_advance_selection import (
    ManagerAdvanceSelectionStatus,
    select_manager_advance_candidate,
)
from .runtime import OriginForgeRuntime


@dataclass(frozen=True)
class ManagerAdvanceStatusProjection:
    admission_status: ManagerAdvanceAdmissionStatus
    selection_status: ManagerAdvanceSelectionStatus
    candidate_count: int
    dispatch_count: int
    finalize_work_order_count: int
    finalize_phase34_count: int
    prepare_count: int
    recovery_required_count: int
    terminal_retry_suppression_count: int
    active_claim_exclusion_count: int
    selected_task_id: str | None
    selected_task_created_at: str | None
    selected_action_kind: ManagerAdvanceActionKind | None
    selected_preparation_policy_id: str | None
    selected_preparation_policy_hash: str | None
    selected_preparation_id: str | None
    selected_preparation_stage: str | None
    selected_dispatch_binding_id: str | None
    selected_binding_audit_id: str | None
    ambiguous_task_ids: tuple[str, ...]
    detail: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "admission_status": self.admission_status.value,
            "selection_status": self.selection_status.value,
            "candidate_count": self.candidate_count,
            "dispatch_count": self.dispatch_count,
            "finalize_work_order_count": self.finalize_work_order_count,
            "finalize_phase34_count": self.finalize_phase34_count,
            "prepare_count": self.prepare_count,
            "recovery_required_count": self.recovery_required_count,
            "terminal_retry_suppression_count": self.terminal_retry_suppression_count,
            "active_claim_exclusion_count": self.active_claim_exclusion_count,
            "selected_task_id": self.selected_task_id,
            "selected_task_created_at": self.selected_task_created_at,
            "selected_action_kind": (
                None if self.selected_action_kind is None else self.selected_action_kind.value
            ),
            "selected_preparation_policy_id": self.selected_preparation_policy_id,
            "selected_preparation_policy_hash": self.selected_preparation_policy_hash,
            "selected_preparation_id": self.selected_preparation_id,
            "selected_preparation_stage": self.selected_preparation_stage,
            "selected_dispatch_binding_id": self.selected_dispatch_binding_id,
            "selected_binding_audit_id": self.selected_binding_audit_id,
            "ambiguous_task_ids": list(self.ambiguous_task_ids),
            "detail": self.detail,
            "authority": "immutable-manager-advance-status",
        }


def inspect_manager_advance_status_readonly(
    runtime: OriginForgeRuntime,
) -> ManagerAdvanceStatusProjection:
    """Project Phase-40 admission/selection without creating or repairing authority."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    admission = inspect_manager_advance_admission_readonly(runtime)
    selection = select_manager_advance_candidate(admission)
    candidate = (
        selection.candidate
        if selection.status is ManagerAdvanceSelectionStatus.ONE_SELECTED
        else None
    )

    policy = None if candidate is None else candidate.preparation_policy
    dispatch = None if candidate is None else candidate.dispatch_candidate
    stage = None if candidate is None else candidate.preparation_stage

    return ManagerAdvanceStatusProjection(
        admission_status=admission.status,
        selection_status=selection.status,
        candidate_count=admission.candidate_count,
        dispatch_count=admission.dispatch_count,
        finalize_work_order_count=admission.finalize_work_order_count,
        finalize_phase34_count=admission.finalize_phase34_count,
        prepare_count=admission.prepare_count,
        recovery_required_count=admission.recovery_required_count,
        terminal_retry_suppression_count=admission.terminal_retry_suppression_count,
        active_claim_exclusion_count=admission.active_claim_exclusion_count,
        selected_task_id=None if candidate is None else candidate.task_id,
        selected_task_created_at=(
            None if candidate is None else candidate.task_created_at
        ),
        selected_action_kind=(
            None if candidate is None else candidate.action_kind
        ),
        selected_preparation_policy_id=(
            None if policy is None else policy.preparation_policy_id
        ),
        selected_preparation_policy_hash=(
            None if policy is None else policy.content_hash
        ),
        selected_preparation_id=(
            None if candidate is None else candidate.preparation_id
        ),
        selected_preparation_stage=None if stage is None else stage.value,
        selected_dispatch_binding_id=(
            None if dispatch is None else dispatch.dispatch_binding_id
        ),
        selected_binding_audit_id=(
            None if dispatch is None else dispatch.binding_audit_id
        ),
        ambiguous_task_ids=admission.ambiguous_task_ids,
        detail=selection.detail or admission.detail,
    )
