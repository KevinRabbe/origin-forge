from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmission,
    ManagerAdvanceAdmissionStatus,
    ManagerAdvanceCandidate,
)


class ManagerAdvanceSelectionStatus(StrEnum):
    NO_ACTIONABLE_WORK = "NO_ACTIONABLE_WORK"
    ONE_SELECTED = "ONE_SELECTED"
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"


@dataclass(frozen=True)
class ManagerAdvanceSelection:
    status: ManagerAdvanceSelectionStatus
    candidate: ManagerAdvanceCandidate | None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
            "detail": self.detail,
            "authority": "pure-selection-only",
        }


def _invalid(detail: str) -> ManagerAdvanceSelection:
    return ManagerAdvanceSelection(
        ManagerAdvanceSelectionStatus.INVALID_STATE,
        None,
        detail,
    )


def _nonnegative_exact_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _complete_admission_is_well_formed(admission: ManagerAdvanceAdmission) -> str | None:
    if admission.detail is not None:
        return "COMPLETE admission may not carry failure detail"
    if admission.ambiguous_task_ids:
        return "COMPLETE admission may not carry ambiguous Task IDs"

    counters = (
        admission.dispatch_count,
        admission.finalize_work_order_count,
        admission.finalize_phase34_count,
        admission.prepare_count,
        admission.recovery_required_count,
        admission.terminal_retry_suppression_count,
        admission.active_claim_exclusion_count,
    )
    if not all(_nonnegative_exact_int(value) for value in counters):
        return "admission counters must be non-negative exact integers"

    expected_counts = {kind: 0 for kind in ManagerAdvanceActionKind}
    task_ids: set[str] = set()
    previous_key: tuple[str, str] | None = None
    for candidate in admission.candidates:
        if not isinstance(candidate, ManagerAdvanceCandidate):
            return "COMPLETE admission contains a non-candidate value"
        if candidate.task_id in task_ids:
            return "COMPLETE admission contains duplicate Task authority"
        task_ids.add(candidate.task_id)
        if previous_key is not None and candidate.order_key <= previous_key:
            return "COMPLETE admission candidates are not strictly ordered by (created_at, task_id)"
        previous_key = candidate.order_key
        expected_counts[candidate.action_kind] += 1

    if (
        admission.dispatch_count != expected_counts[ManagerAdvanceActionKind.DISPATCH]
        or admission.finalize_work_order_count
        != expected_counts[ManagerAdvanceActionKind.FINALIZE_WORK_ORDER]
        or admission.finalize_phase34_count
        != expected_counts[ManagerAdvanceActionKind.FINALIZE_PHASE34]
        or admission.prepare_count != expected_counts[ManagerAdvanceActionKind.PREPARE]
        or admission.recovery_required_count
        != expected_counts[ManagerAdvanceActionKind.RECOVERY_REQUIRED]
    ):
        return "admission action counters do not match candidate contents"
    return None


def _failed_admission_is_well_formed(admission: ManagerAdvanceAdmission) -> str | None:
    if admission.candidates:
        return "failed admission may not expose partial candidates"
    if any(
        value != 0
        for value in (
            admission.dispatch_count,
            admission.finalize_work_order_count,
            admission.finalize_phase34_count,
            admission.prepare_count,
            admission.recovery_required_count,
            admission.terminal_retry_suppression_count,
            admission.active_claim_exclusion_count,
        )
    ):
        return "failed admission may not expose partial counters"
    if not admission.detail:
        return "failed admission requires detail"
    if (
        admission.status is ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY
        and not admission.ambiguous_task_ids
    ):
        # Lower Phase-38 ambiguity can be global while still naming its Tasks;
        # Phase-40-originated policy ambiguity also always names Tasks.
        return "ambiguous admission requires ambiguous Task IDs"
    if (
        admission.status is not ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY
        and admission.ambiguous_task_ids
    ):
        return "non-ambiguous failed admission may not carry ambiguous Task IDs"
    return None


def select_manager_advance_candidate(
    admission: ManagerAdvanceAdmission,
) -> ManagerAdvanceSelection:
    """Validate one Phase-40 admission and select its first candidate only.

    This function intentionally never recomputes a minimum. Ordering authority
    belongs to immutable admission. A malformed COMPLETE admission fails closed.
    """

    if not isinstance(admission, ManagerAdvanceAdmission):
        raise TypeError("admission must be a ManagerAdvanceAdmission")

    if admission.status is ManagerAdvanceAdmissionStatus.COMPLETE:
        malformed = _complete_admission_is_well_formed(admission)
        if malformed is not None:
            return _invalid(malformed)
        if not admission.candidates:
            return ManagerAdvanceSelection(
                ManagerAdvanceSelectionStatus.NO_ACTIONABLE_WORK,
                None,
                None,
            )
        return ManagerAdvanceSelection(
            ManagerAdvanceSelectionStatus.ONE_SELECTED,
            admission.candidates[0],
            None,
        )

    malformed = _failed_admission_is_well_formed(admission)
    if malformed is not None:
        return _invalid(malformed)
    mapping = {
        ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY: ManagerAdvanceSelectionStatus.AMBIGUOUS_AUTHORITY,
        ManagerAdvanceAdmissionStatus.LIMIT_EXCEEDED: ManagerAdvanceSelectionStatus.LIMIT_EXCEEDED,
        ManagerAdvanceAdmissionStatus.INVALID_STATE: ManagerAdvanceSelectionStatus.INVALID_STATE,
    }
    return ManagerAdvanceSelection(
        mapping.get(admission.status, ManagerAdvanceSelectionStatus.INVALID_STATE),
        None,
        admission.detail,
    )
