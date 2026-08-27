from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from .production_manager_advance_inventory import (
    ManagerAdvanceInventoryStatus,
    PreparationReceiptInventoryEntry,
    inspect_preparation_policy_inventory_readonly,
    inspect_preparation_receipt_inventory_readonly,
)
from .production_manager_dispatch_admission import (
    ManagerDispatchAdmissionStatus,
    ManagerDispatchCandidate,
    inspect_manager_dispatch_admission_readonly,
)
from .production_preparation_admission import (
    PreparationAdmissionStatus,
    PreparationCandidate,
    inspect_materialization_preparation_eligibility_readonly,
)
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    TaskPreparationPolicyBinding,
)
from .production_preparation_policy_store import ProductionPreparationPolicyStoreError
from .production_preparation_recovery import (
    PreparationRecoveryProjection,
    PreparationRecoveryReadError,
    PreparationRecoveryState,
    inspect_preparation_recovery_readonly,
)
from .production_preparation_status import (
    PreparationInspectionState,
    PreparationReceiptStatusProjection,
    PreparationStatusReadError,
    inspect_preparation_receipt_status_readonly,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime

_MAX_MANAGER_ADVANCE_CANDIDATES = 1_024


class ManagerAdvanceActionKind(StrEnum):
    DISPATCH = "DISPATCH"
    FINALIZE_WORK_ORDER = "FINALIZE_WORK_ORDER"
    FINALIZE_PHASE34 = "FINALIZE_PHASE34"
    PREPARE = "PREPARE"
    RECOVER_PREPARATION = "RECOVER_PREPARATION"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class ManagerAdvanceAdmissionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"


@dataclass(frozen=True)
class ManagerAdvanceCandidate:
    action_kind: ManagerAdvanceActionKind
    task_id: str
    task_created_at: str
    dispatch_candidate: ManagerDispatchCandidate | None = None
    preparation_policy: TaskPreparationPolicyBinding | None = None
    preparation_candidate: PreparationCandidate | None = None
    preparation_id: str | None = None
    preparation_stage: PreparationStage | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_kind, ManagerAdvanceActionKind):
            raise TypeError("action_kind must be a ManagerAdvanceActionKind")
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id must be non-empty")
        if (
            not isinstance(self.task_created_at, str)
            or not self.task_created_at
            or self.task_created_at.strip() != self.task_created_at
        ):
            raise ValueError("task_created_at is invalid")

        if self.action_kind is ManagerAdvanceActionKind.DISPATCH:
            if (
                not isinstance(self.dispatch_candidate, ManagerDispatchCandidate)
                or self.dispatch_candidate.task_id != self.task_id
                or self.dispatch_candidate.created_at != self.task_created_at
                or self.preparation_policy is not None
                or self.preparation_candidate is not None
                or self.preparation_id is not None
                or self.preparation_stage is not None
            ):
                raise ValueError("DISPATCH candidate shape is invalid")
            return

        if self.action_kind is ManagerAdvanceActionKind.PREPARE:
            if (
                not isinstance(self.preparation_policy, TaskPreparationPolicyBinding)
                or not isinstance(self.preparation_candidate, PreparationCandidate)
                or self.preparation_candidate.task_id != self.task_id
                or self.preparation_candidate.created_at != self.task_created_at
                or self.dispatch_candidate is not None
                or self.preparation_id is not None
                or self.preparation_stage is not None
            ):
                raise ValueError("PREPARE candidate shape is invalid")
            return

        if self.action_kind in {
            ManagerAdvanceActionKind.FINALIZE_WORK_ORDER,
            ManagerAdvanceActionKind.FINALIZE_PHASE34,
            ManagerAdvanceActionKind.RECOVER_PREPARATION,
            ManagerAdvanceActionKind.RECOVERY_REQUIRED,
        }:
            if (
                not isinstance(self.preparation_id, str)
                or not self.preparation_id
                or not isinstance(self.preparation_stage, PreparationStage)
                or self.dispatch_candidate is not None
                or self.preparation_policy is not None
                or self.preparation_candidate is not None
            ):
                raise ValueError("PREP lifecycle candidate shape is invalid")
            if (
                self.action_kind is ManagerAdvanceActionKind.FINALIZE_WORK_ORDER
                and self.preparation_stage
                not in {PreparationStage.PLANNER_STARTED, PreparationStage.PLANNER_RETURNED}
            ):
                raise ValueError("FINALIZE_WORK_ORDER has wrong PREP stage")
            if (
                self.action_kind is ManagerAdvanceActionKind.FINALIZE_PHASE34
                and self.preparation_stage is not PreparationStage.WORK_ORDER_AUDITED
            ):
                raise ValueError("FINALIZE_PHASE34 has wrong PREP stage")
            if (
                self.action_kind is ManagerAdvanceActionKind.RECOVER_PREPARATION
                and self.preparation_stage
                not in {PreparationStage.CLAIMED, PreparationStage.ACTIVATED, PreparationStage.ROUTED}
            ):
                raise ValueError("RECOVER_PREPARATION has wrong PREP stage")
            if (
                self.action_kind is ManagerAdvanceActionKind.RECOVERY_REQUIRED
                and not self.detail
            ):
                raise ValueError("RECOVERY_REQUIRED requires detail")
            return

        raise ValueError("unsupported Manager advance action kind")

    @property
    def order_key(self) -> tuple[str, str]:
        return (self.task_created_at, self.task_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "action_kind": self.action_kind.value,
            "task_id": self.task_id,
            "task_created_at": self.task_created_at,
            "dispatch_candidate": (
                None
                if self.dispatch_candidate is None
                else self.dispatch_candidate.to_dict()
            ),
            "preparation_policy_id": (
                None
                if self.preparation_policy is None
                else self.preparation_policy.preparation_policy_id
            ),
            "preparation_policy_hash": (
                None
                if self.preparation_policy is None
                else self.preparation_policy.content_hash
            ),
            "preparation_candidate": (
                None
                if self.preparation_candidate is None
                else self.preparation_candidate.to_dict()
            ),
            "preparation_id": self.preparation_id,
            "preparation_stage": (
                None if self.preparation_stage is None else self.preparation_stage.value
            ),
            "detail": self.detail,
            "order_key": [self.task_created_at, self.task_id],
        }


@dataclass(frozen=True)
class ManagerAdvanceAdmission:
    status: ManagerAdvanceAdmissionStatus
    candidates: tuple[ManagerAdvanceCandidate, ...]
    dispatch_count: int
    finalize_work_order_count: int
    finalize_phase34_count: int
    prepare_count: int
    recovery_required_count: int
    terminal_retry_suppression_count: int
    active_claim_exclusion_count: int
    ambiguous_task_ids: tuple[str, ...] = ()
    detail: str | None = None
    recover_preparation_count: int = 0

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "candidate_count": self.candidate_count,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "dispatch_count": self.dispatch_count,
            "finalize_work_order_count": self.finalize_work_order_count,
            "finalize_phase34_count": self.finalize_phase34_count,
            "prepare_count": self.prepare_count,
            "recover_preparation_count": self.recover_preparation_count,
            "recovery_required_count": self.recovery_required_count,
            "terminal_retry_suppression_count": self.terminal_retry_suppression_count,
            "active_claim_exclusion_count": self.active_claim_exclusion_count,
            "ambiguous_task_ids": list(self.ambiguous_task_ids),
            "detail": self.detail,
            "authority": "immutable-manager-advance-admission-evidence-only",
        }


def _empty(
    status: ManagerAdvanceAdmissionStatus,
    detail: str,
    *,
    ambiguous_task_ids: tuple[str, ...] = (),
) -> ManagerAdvanceAdmission:
    return ManagerAdvanceAdmission(
        status=status,
        candidates=(),
        dispatch_count=0,
        finalize_work_order_count=0,
        finalize_phase34_count=0,
        prepare_count=0,
        recovery_required_count=0,
        terminal_retry_suppression_count=0,
        active_claim_exclusion_count=0,
        ambiguous_task_ids=ambiguous_task_ids,
        detail=detail,
        recover_preparation_count=0,
    )


def _policy_authority_key(policy: TaskPreparationPolicyBinding) -> tuple[object, ...]:
    return (
        policy.project_id,
        policy.materialization_id,
        policy.materialization_hash,
        policy.planning_input_id,
        policy.planning_input_hash,
        policy.capability_catalog_id,
        policy.capability_catalog_hash,
        policy.capability_routing_policy_id,
        policy.capability_routing_policy_hash,
        policy.dispatch_contract_catalog_id,
        policy.dispatch_contract_catalog_hash,
        policy.preparation_owner_id,
        policy.preparation_owner_fingerprint,
        policy.planner_request_version,
        policy.planner_contract_id,
        policy.model_strategy_roles,
        policy.schema_version,
    )


def _phase38_failure(status: ManagerDispatchAdmissionStatus, detail: object) -> ManagerAdvanceAdmission:
    if status is ManagerDispatchAdmissionStatus.AMBIGUOUS_AUTHORITY:
        target = ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY
    elif status is ManagerDispatchAdmissionStatus.LIMIT_EXCEEDED:
        target = ManagerAdvanceAdmissionStatus.LIMIT_EXCEEDED
    else:
        target = ManagerAdvanceAdmissionStatus.INVALID_STATE
    return _empty(target, f"Phase-38 admission is {status.value}: {detail}")


def _inventory_failure(
    label: str,
    status: ManagerAdvanceInventoryStatus,
    detail: str | None,
) -> ManagerAdvanceAdmission:
    target = (
        ManagerAdvanceAdmissionStatus.LIMIT_EXCEEDED
        if status is ManagerAdvanceInventoryStatus.LIMIT_EXCEEDED
        else ManagerAdvanceAdmissionStatus.INVALID_STATE
    )
    return _empty(target, f"{label} inventory is {status.value}: {detail}")


def _status_matches_inventory(
    entry: PreparationReceiptInventoryEntry,
    projection: PreparationReceiptStatusProjection,
) -> bool:
    receipt = entry.receipt
    return (
        projection.preparation_id == receipt.preparation_id
        and projection.preparation_policy_id == receipt.preparation_policy_id
        and projection.preparation_policy_hash == receipt.preparation_policy_hash
        and projection.task_id == receipt.task_id
        and projection.receipt_status is receipt.status
        and projection.stage is receipt.stage
        and projection.revision == receipt.revision
    )


def _recovery_matches_inventory(
    entry: PreparationReceiptInventoryEntry,
    projection: PreparationRecoveryProjection,
) -> bool:
    receipt = entry.receipt
    return (
        projection.preparation_id == receipt.preparation_id
        and projection.preparation_policy_id == receipt.preparation_policy_id
        and projection.preparation_policy_hash == receipt.preparation_policy_hash
        and projection.task_id == receipt.task_id
        and projection.receipt_status is receipt.status
        and projection.stage is receipt.stage
        and projection.receipt_revision == receipt.revision
    )


def _legacy_claimed_recovery_is_adoptable(
    runtime: OriginForgeRuntime,
    entry: PreparationReceiptInventoryEntry,
) -> bool:
    receipt = entry.receipt
    if (
        receipt.status is not PreparationStatus.ACTIVE
        or receipt.stage is not PreparationStage.CLAIMED
    ):
        return False
    try:
        recovery = inspect_preparation_recovery_readonly(
            runtime,
            receipt.preparation_id,
        )
    except (
        PreparationRecoveryReadError,
        ProductionPreparationPolicyStoreError,
        ProductionReadGuardError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return False
    return (
        _recovery_matches_inventory(entry, recovery)
        and recovery.state is PreparationRecoveryState.ADOPTABLE_ACTIVATION_CHECKPOINT
    )


def _active_claim_exists_readonly(runtime: OriginForgeRuntime, task_id: str) -> bool:
    with production_read_connection(runtime) as conn:
        rows = conn.execute(
            """SELECT dc.claim_id
               FROM dispatch_claims dc
               JOIN tasks t ON t.id = dc.task_id
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               JOIN projects p ON p.id = g.project_id
               WHERE dc.task_id = ? AND dc.status = 'ACTIVE'
                 AND p.root_path = ?
               LIMIT 2""",
            (task_id, str(runtime.project_root)),
        ).fetchall()
    if len(rows) > 1:
        raise ValueError("Task has multiple ACTIVE dispatch claims")
    return bool(rows)


def _receipt_candidate(
    runtime: OriginForgeRuntime,
    entry: PreparationReceiptInventoryEntry,
    projection: PreparationReceiptStatusProjection,
) -> ManagerAdvanceCandidate:
    receipt = entry.receipt
    if receipt.status is not PreparationStatus.ACTIVE:
        raise ValueError("receipt continuation requires ACTIVE PREP")

    if not projection.current or projection.state is PreparationInspectionState.STALE_OR_INVALID:
        if _legacy_claimed_recovery_is_adoptable(runtime, entry):
            return ManagerAdvanceCandidate(
                ManagerAdvanceActionKind.RECOVER_PREPARATION,
                receipt.task_id,
                entry.task_created_at,
                preparation_id=receipt.preparation_id,
                preparation_stage=receipt.stage,
            )
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVERY_REQUIRED,
            receipt.task_id,
            entry.task_created_at,
            preparation_id=receipt.preparation_id,
            preparation_stage=receipt.stage,
            detail=projection.detail or "ACTIVE PREP authority is stale or invalid",
        )
    if receipt.stage in {
        PreparationStage.CLAIMED,
        PreparationStage.ACTIVATED,
        PreparationStage.ROUTED,
    }:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVER_PREPARATION,
            receipt.task_id,
            entry.task_created_at,
            preparation_id=receipt.preparation_id,
            preparation_stage=receipt.stage,
        )
    if receipt.stage in {PreparationStage.PLANNER_STARTED, PreparationStage.PLANNER_RETURNED}:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.FINALIZE_WORK_ORDER,
            receipt.task_id,
            entry.task_created_at,
            preparation_id=receipt.preparation_id,
            preparation_stage=receipt.stage,
        )
    if receipt.stage is PreparationStage.WORK_ORDER_AUDITED:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.FINALIZE_PHASE34,
            receipt.task_id,
            entry.task_created_at,
            preparation_id=receipt.preparation_id,
            preparation_stage=receipt.stage,
        )
    raise ValueError("ACTIVE PREP stage is outside Manager continuation contract")


def _counts(candidates: tuple[ManagerAdvanceCandidate, ...]) -> dict[ManagerAdvanceActionKind, int]:
    result = {kind: 0 for kind in ManagerAdvanceActionKind}
    for candidate in candidates:
        result[candidate.action_kind] += 1
    return result


def inspect_manager_advance_admission_readonly(
    runtime: OriginForgeRuntime,
) -> ManagerAdvanceAdmission:
    """Compose Phase-38/39 read authority into one bounded global admission.

    This is scheduling evidence only. It performs no selection and creates no
    authority. Any later mutating helper must independently revalidate the exact
    frozen candidate under the lower phase's authoritative transaction/currentness
    checks.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    policies = inspect_preparation_policy_inventory_readonly(runtime)
    if policies.status is not ManagerAdvanceInventoryStatus.COMPLETE:
        return _inventory_failure("PREPPOL", policies.status, policies.detail)
    receipts = inspect_preparation_receipt_inventory_readonly(runtime)
    if receipts.status is not ManagerAdvanceInventoryStatus.COMPLETE:
        return _inventory_failure("PREP", receipts.status, receipts.detail)

    dispatch = inspect_manager_dispatch_admission_readonly(runtime)
    if dispatch.status is not ManagerDispatchAdmissionStatus.COMPLETE:
        result = _phase38_failure(dispatch.status, dispatch.detail)
        if dispatch.status is ManagerDispatchAdmissionStatus.AMBIGUOUS_AUTHORITY:
            return ManagerAdvanceAdmission(
                **{
                    **result.__dict__,
                    "ambiguous_task_ids": dispatch.ambiguous_task_ids,
                }
            )
        return result

    dispatch_by_task: dict[str, ManagerDispatchCandidate] = {}
    for candidate in dispatch.candidates:
        if candidate.task_id in dispatch_by_task:
            return _empty(
                ManagerAdvanceAdmissionStatus.INVALID_STATE,
                "Phase-38 admission exposed more than one representative per Task",
            )
        dispatch_by_task[candidate.task_id] = candidate

    receipt_groups: dict[
        str,
        list[tuple[PreparationReceiptInventoryEntry, PreparationReceiptStatusProjection]],
    ] = defaultdict(list)
    try:
        for entry in receipts.entries:
            projection = inspect_preparation_receipt_status_readonly(
                runtime,
                entry.preparation_id,
            )
            if not _status_matches_inventory(entry, projection):
                raise ValueError("PREP status projection changed after immutable inventory")
            receipt_groups[entry.task_id].append((entry, projection))
    except (
        PreparationStatusReadError,
        ProductionPreparationPolicyStoreError,
        ProductionReadGuardError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _empty(
            ManagerAdvanceAdmissionStatus.INVALID_STATE,
            f"PREP lifecycle classification failed: {type(exc).__name__}: {exc}",
        )

    chosen: dict[str, ManagerAdvanceCandidate] = {}
    terminal_retry_blockers: set[str] = set()
    active_claim_exclusion_count = 0

    try:
        for task_id, values in receipt_groups.items():
            active = [value for value in values if value[0].receipt.status is PreparationStatus.ACTIVE]
            ready = [value for value in values if value[0].receipt.status is PreparationStatus.READY]
            terminal = [
                value
                for value in values
                if value[0].receipt.status
                in {PreparationStatus.FAILED_PRE_PLANNER, PreparationStatus.INTERRUPTED}
            ]

            if len(active) > 1:
                raise ValueError("Task has multiple ACTIVE PREP receipts")
            if len(ready) > 1:
                raise ValueError("Task has multiple READY PREP receipts")

            if active:
                if task_id in dispatch_by_task:
                    raise ValueError("Task has simultaneous ACTIVE PREP and Phase-38 dispatch authority")
                entry, projection = active[0]
                chosen[task_id] = _receipt_candidate(runtime, entry, projection)
                continue

            if ready:
                entry, projection = ready[0]
                if task_id in dispatch_by_task:
                    # Phase 38 independently owns current READY/BOUND dispatch truth.
                    continue
                if _active_claim_exists_readonly(runtime, task_id):
                    active_claim_exclusion_count += 1
                    continue
                chosen[task_id] = ManagerAdvanceCandidate(
                    ManagerAdvanceActionKind.RECOVERY_REQUIRED,
                    task_id,
                    entry.task_created_at,
                    preparation_id=entry.preparation_id,
                    preparation_stage=entry.receipt.stage,
                    detail=(
                        projection.detail
                        or "READY/BOUND PREP is not currently Phase-38-admissible"
                    ),
                )
                continue

            # Terminal receipts are history, not a Manager action. A terminal
            # receipt that still exactly binds current Task authority suppresses
            # an implicit PREPARE retry for that Task, but stale historical
            # terminal evidence does not acquire scheduling authority.
            if any(projection.current for _, projection in terminal):
                terminal_retry_blockers.add(task_id)

        for task_id, dispatch_candidate in dispatch_by_task.items():
            if task_id in chosen:
                raise ValueError("Task has conflicting dispatch and preparation action authority")
            chosen[task_id] = ManagerAdvanceCandidate(
                ManagerAdvanceActionKind.DISPATCH,
                task_id,
                dispatch_candidate.created_at,
                dispatch_candidate=dispatch_candidate,
            )
    except (ProductionReadGuardError, TypeError, ValueError) as exc:
        return _empty(
            ManagerAdvanceAdmissionStatus.INVALID_STATE,
            f"same-Task authority classification failed: {type(exc).__name__}: {exc}",
        )

    prepare_by_task: dict[
        str,
        list[tuple[TaskPreparationPolicyBinding, PreparationCandidate]],
    ] = defaultdict(list)
    try:
        for policy in policies.policies:
            policy_admission = inspect_materialization_preparation_eligibility_readonly(
                runtime,
                policy,
            )
            if policy_admission.status is not PreparationAdmissionStatus.COMPLETE:
                raise ValueError(
                    f"PREPPOL {policy.preparation_policy_id} admission is {policy_admission.status.value}: {policy_admission.detail}"
                )
            for preparation_candidate in policy_admission.candidates:
                prepare_by_task[preparation_candidate.task_id].append(
                    (policy, preparation_candidate)
                )
    except (ProductionReadGuardError, KeyError, TypeError, ValueError) as exc:
        return _empty(
            ManagerAdvanceAdmissionStatus.INVALID_STATE,
            f"fresh preparation admission failed: {type(exc).__name__}: {exc}",
        )

    ambiguous_task_ids: list[str] = []
    try:
        for task_id, alternatives in prepare_by_task.items():
            if task_id in chosen:
                raise ValueError("Task has both existing action authority and fresh PREPARE authority")
            if task_id in terminal_retry_blockers:
                continue

            authority_keys = {_policy_authority_key(policy) for policy, _ in alternatives}
            if len(authority_keys) != 1:
                ambiguous_task_ids.append(task_id)
                continue
            preparation_candidates = {candidate for _, candidate in alternatives}
            if len(preparation_candidates) != 1:
                raise ValueError("equivalent PREPPOLs yielded different preparation candidates")
            representative_policy, candidate = min(
                alternatives,
                key=lambda value: value[0].preparation_policy_id,
            )
            chosen[task_id] = ManagerAdvanceCandidate(
                ManagerAdvanceActionKind.PREPARE,
                task_id,
                candidate.created_at,
                preparation_policy=representative_policy,
                preparation_candidate=candidate,
            )
    except (TypeError, ValueError) as exc:
        return _empty(
            ManagerAdvanceAdmissionStatus.INVALID_STATE,
            f"fresh preparation authority collapse failed: {type(exc).__name__}: {exc}",
        )

    if ambiguous_task_ids:
        ambiguous_task_ids.sort()
        return _empty(
            ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY,
            "one or more Tasks are eligible under semantically different current PREPPOL authority",
            ambiguous_task_ids=tuple(ambiguous_task_ids),
        )

    if len(chosen) > _MAX_MANAGER_ADVANCE_CANDIDATES:
        return _empty(
            ManagerAdvanceAdmissionStatus.LIMIT_EXCEEDED,
            "Manager advance candidate-count limit exceeded",
        )

    candidates = tuple(sorted(chosen.values(), key=lambda value: value.order_key))
    count = _counts(candidates)
    return ManagerAdvanceAdmission(
        status=ManagerAdvanceAdmissionStatus.COMPLETE,
        candidates=candidates,
        dispatch_count=count[ManagerAdvanceActionKind.DISPATCH],
        finalize_work_order_count=count[ManagerAdvanceActionKind.FINALIZE_WORK_ORDER],
        finalize_phase34_count=count[ManagerAdvanceActionKind.FINALIZE_PHASE34],
        prepare_count=count[ManagerAdvanceActionKind.PREPARE],
        recovery_required_count=count[ManagerAdvanceActionKind.RECOVERY_REQUIRED],
        terminal_retry_suppression_count=len(terminal_retry_blockers),
        active_claim_exclusion_count=active_claim_exclusion_count,
        ambiguous_task_ids=(),
        detail=None,
        recover_preparation_count=count[ManagerAdvanceActionKind.RECOVER_PREPARATION],
    )
