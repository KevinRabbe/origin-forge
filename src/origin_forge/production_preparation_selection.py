from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_preparation_admission import (
    MaterializationPreparationAdmission,
    PreparationAdmissionStatus,
    PreparationCandidate,
)


class PreparationSelectionStatus(StrEnum):
    NO_ELIGIBLE_TASK = "NO_ELIGIBLE_TASK"
    ONE_SELECTED = "ONE_SELECTED"
    INVALID_STATE = "INVALID_STATE"


@dataclass(frozen=True)
class PreparationSelection:
    status: PreparationSelectionStatus
    candidate: PreparationCandidate | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, PreparationSelectionStatus):
            raise TypeError("status must be a PreparationSelectionStatus")
        if self.status is PreparationSelectionStatus.ONE_SELECTED:
            if not isinstance(self.candidate, PreparationCandidate):
                raise ValueError("ONE_SELECTED requires one typed candidate")
        elif self.candidate is not None:
            raise ValueError("non-selected preparation state may not carry a candidate")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
            "authority": "pure-selection",
        }


def _complete_admission_is_well_formed(
    admission: MaterializationPreparationAdmission,
) -> bool:
    if admission.detail is not None:
        return False
    counters = (
        admission.not_queued_exclusion_count,
        admission.dependency_exclusion_count,
        admission.active_preparation_exclusion_count,
        admission.phase38_admissible_exclusion_count,
    )
    if any(type(value) is not int or value < 0 for value in counters):
        return False
    candidates = admission.candidates
    if not isinstance(candidates, tuple) or any(
        not isinstance(candidate, PreparationCandidate) for candidate in candidates
    ):
        return False
    if len({candidate.task_id for candidate in candidates}) != len(candidates):
        return False
    if any(
        not candidate.created_at
        or type(candidate.task_revision) is not int
        or candidate.task_revision < 0
        for candidate in candidates
    ):
        return False
    return candidates == tuple(
        sorted(candidates, key=lambda candidate: (candidate.created_at, candidate.task_id))
    )


def select_preparation_candidate(
    admission: MaterializationPreparationAdmission,
) -> PreparationSelection:
    """Select exactly the first valid 39B candidate without I/O or mutation."""

    if not isinstance(admission, MaterializationPreparationAdmission):
        raise TypeError("admission must be a MaterializationPreparationAdmission")
    if admission.status is not PreparationAdmissionStatus.COMPLETE:
        return PreparationSelection(PreparationSelectionStatus.INVALID_STATE, None)
    if not _complete_admission_is_well_formed(admission):
        return PreparationSelection(PreparationSelectionStatus.INVALID_STATE, None)
    if not admission.candidates:
        return PreparationSelection(PreparationSelectionStatus.NO_ELIGIBLE_TASK, None)
    return PreparationSelection(
        PreparationSelectionStatus.ONE_SELECTED,
        admission.candidates[0],
    )
