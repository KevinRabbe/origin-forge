from __future__ import annotations

from dataclasses import dataclass

from .ids import IdKind, validate_id
from .production_manager_dispatch_admission import (
    ManagerDispatchAdmissionDetail,
    ManagerDispatchAdmissionStatus,
    inspect_manager_dispatch_admission_readonly,
)
from .production_manager_dispatch_selection import (
    ManagerDispatchSelectionStatus,
    select_manager_dispatch_candidate,
)
from .runtime import OriginForgeRuntime


@dataclass(frozen=True)
class ManagerDispatchStatusProjection:
    admission_status: ManagerDispatchAdmissionStatus
    selection_status: ManagerDispatchSelectionStatus
    candidate_count: int
    scanned_audit_count: int
    current_chain_count: int
    active_claim_exclusion_count: int
    not_ready_exclusion_count: int
    ambiguous_task_count: int
    selected_task_id: str | None
    selected_dispatch_binding_id: str | None
    selected_binding_audit_id: str | None
    detail: ManagerDispatchAdmissionDetail | None

    def __post_init__(self) -> None:
        if not isinstance(self.admission_status, ManagerDispatchAdmissionStatus):
            raise TypeError("admission_status must be a ManagerDispatchAdmissionStatus")
        if not isinstance(self.selection_status, ManagerDispatchSelectionStatus):
            raise TypeError("selection_status must be a ManagerDispatchSelectionStatus")
        for value, label in (
            (self.candidate_count, "candidate_count"),
            (self.scanned_audit_count, "scanned_audit_count"),
            (self.current_chain_count, "current_chain_count"),
            (self.active_claim_exclusion_count, "active_claim_exclusion_count"),
            (self.not_ready_exclusion_count, "not_ready_exclusion_count"),
            (self.ambiguous_task_count, "ambiguous_task_count"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        for selected_id, kind, label in (
            (self.selected_task_id, IdKind.TASK, "selected_task_id"),
            (
                self.selected_dispatch_binding_id,
                IdKind.DISPATCH_BINDING,
                "selected_dispatch_binding_id",
            ),
            (
                self.selected_binding_audit_id,
                IdKind.DISPATCH_BINDING_AUDIT,
                "selected_binding_audit_id",
            ),
        ):
            if selected_id is not None and (
                not isinstance(selected_id, str) or not validate_id(selected_id, kind)
            ):
                raise ValueError(f"{label} has wrong canonical ID kind")
        selected_ids = (
            self.selected_task_id,
            self.selected_dispatch_binding_id,
            self.selected_binding_audit_id,
        )
        if self.selection_status is ManagerDispatchSelectionStatus.ONE_SELECTED:
            if any(value is None for value in selected_ids):
                raise ValueError("ONE_SELECTED status requires exact selected authority IDs")
        elif any(value is not None for value in selected_ids):
            raise ValueError("non-selected Manager status may not carry selected IDs")

    def to_dict(self) -> dict[str, object]:
        return {
            "admission_status": self.admission_status.value,
            "selection_status": self.selection_status.value,
            "candidate_count": self.candidate_count,
            "scanned_audit_count": self.scanned_audit_count,
            "current_chain_count": self.current_chain_count,
            "active_claim_exclusion_count": self.active_claim_exclusion_count,
            "not_ready_exclusion_count": self.not_ready_exclusion_count,
            "ambiguous_task_count": self.ambiguous_task_count,
            "selected_task_id": self.selected_task_id,
            "selected_dispatch_binding_id": self.selected_dispatch_binding_id,
            "selected_binding_audit_id": self.selected_binding_audit_id,
            "detail": None if self.detail is None else self.detail.value,
            "authority": "read-only",
        }


def inspect_manager_dispatch_status_readonly(
    runtime: OriginForgeRuntime,
) -> ManagerDispatchStatusProjection:
    """Project bounded Manager admission/selection status without mutation."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    admission = inspect_manager_dispatch_admission_readonly(runtime)
    selection = select_manager_dispatch_candidate(admission)
    candidate = selection.candidate
    return ManagerDispatchStatusProjection(
        admission_status=admission.status,
        selection_status=selection.status,
        candidate_count=admission.candidate_count,
        scanned_audit_count=admission.scanned_audit_count,
        current_chain_count=admission.current_chain_count,
        active_claim_exclusion_count=admission.active_claim_exclusion_count,
        not_ready_exclusion_count=admission.not_ready_exclusion_count,
        ambiguous_task_count=admission.ambiguous_task_count,
        selected_task_id=None if candidate is None else candidate.task_id,
        selected_dispatch_binding_id=(
            None if candidate is None else candidate.dispatch_binding_id
        ),
        selected_binding_audit_id=(
            None if candidate is None else candidate.binding_audit_id
        ),
        detail=admission.detail,
    )
