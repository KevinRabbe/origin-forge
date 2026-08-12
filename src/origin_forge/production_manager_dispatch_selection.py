from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_manager_dispatch_admission import (
    ManagerDispatchAdmission,
    ManagerDispatchAdmissionStatus,
    ManagerDispatchCandidate,
)


class ManagerDispatchSelectionStatus(StrEnum):
    NO_ELIGIBLE_TASK = "NO_ELIGIBLE_TASK"
    ONE_SELECTED = "ONE_SELECTED"
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"


@dataclass(frozen=True)
class ManagerDispatchSelection:
    status: ManagerDispatchSelectionStatus
    candidate: ManagerDispatchCandidate | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ManagerDispatchSelectionStatus):
            raise TypeError("status must be a ManagerDispatchSelectionStatus")
        if self.status is ManagerDispatchSelectionStatus.ONE_SELECTED:
            if not isinstance(self.candidate, ManagerDispatchCandidate):
                raise ValueError("ONE_SELECTED requires one typed candidate")
        elif self.candidate is not None:
            raise ValueError("non-selected Manager state may not carry a candidate")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
            "authority": "pure-selection",
        }


def _invalid() -> ManagerDispatchSelection:
    return ManagerDispatchSelection(
        ManagerDispatchSelectionStatus.INVALID_STATE,
        None,
    )


def _complete_admission_is_well_formed(admission: ManagerDispatchAdmission) -> bool:
    if admission.detail is not None or admission.ambiguous_task_ids:
        return False

    counters = (
        admission.scanned_audit_count,
        admission.current_chain_count,
        admission.active_claim_exclusion_count,
        admission.not_ready_exclusion_count,
    )
    if any(type(value) is not int or value < 0 for value in counters):
        return False
    if admission.current_chain_count > admission.scanned_audit_count:
        return False

    candidates = admission.candidates
    if not isinstance(candidates, tuple) or any(
        not isinstance(candidate, ManagerDispatchCandidate) for candidate in candidates
    ):
        return False
    if len({candidate.task_id for candidate in candidates}) != len(candidates):
        return False
    if any(not candidate.created_at for candidate in candidates):
        return False
    return candidates == tuple(
        sorted(candidates, key=lambda candidate: (candidate.created_at, candidate.task_id))
    )


def select_manager_dispatch_candidate(
    admission: ManagerDispatchAdmission,
) -> ManagerDispatchSelection:
    """Select at most one Phase-38 candidate without I/O or mutation."""

    if not isinstance(admission, ManagerDispatchAdmission):
        raise TypeError("admission must be a ManagerDispatchAdmission")

    if admission.status is ManagerDispatchAdmissionStatus.AMBIGUOUS_AUTHORITY:
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.AMBIGUOUS_AUTHORITY,
            None,
        )
    if admission.status is ManagerDispatchAdmissionStatus.LIMIT_EXCEEDED:
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.LIMIT_EXCEEDED,
            None,
        )
    if admission.status is ManagerDispatchAdmissionStatus.INVALID_STATE:
        return _invalid()
    if admission.status is not ManagerDispatchAdmissionStatus.COMPLETE:
        return _invalid()
    if not _complete_admission_is_well_formed(admission):
        return _invalid()
    if not admission.candidates:
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.NO_ELIGIBLE_TASK,
            None,
        )
    return ManagerDispatchSelection(
        ManagerDispatchSelectionStatus.ONE_SELECTED,
        admission.candidates[0],
    )
