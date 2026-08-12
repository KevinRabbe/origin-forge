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
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.INVALID_STATE,
            None,
        )
    if admission.status is not ManagerDispatchAdmissionStatus.COMPLETE:
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.INVALID_STATE,
            None,
        )

    # COMPLETE is the only selection-bearing admission.  Defensive relation
    # checks prevent a hand-constructed inconsistent object from becoming
    # Manager authority.
    if admission.detail is not None or admission.ambiguous_task_ids:
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.INVALID_STATE,
            None,
        )
    if not admission.candidates:
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.NO_ELIGIBLE_TASK,
            None,
        )
    if any(not isinstance(value, ManagerDispatchCandidate) for value in admission.candidates):
        return ManagerDispatchSelection(
            ManagerDispatchSelectionStatus.INVALID_STATE,
            None,
        )

    candidate = min(
        admission.candidates,
        key=lambda value: (value.created_at, value.task_id),
    )
    return ManagerDispatchSelection(
        ManagerDispatchSelectionStatus.ONE_SELECTED,
        candidate,
    )
