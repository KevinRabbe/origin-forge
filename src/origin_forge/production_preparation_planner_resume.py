from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_capability_store import (
    CapabilityRouteDecision,
    ProductionCapabilityStore,
)
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    TaskPreparationPolicyBinding,
    TaskPreparationReceipt,
)
from .production_preparation_planner_boundary import (
    PreparationPlannerBoundaryError,
    RoutedPreparationPlannerBoundary,
    resolve_routed_preparation_planner_boundary,
)
from .production_preparation_planner_same_call import (
    resolve_same_call_routed_preparation_planner_boundary,
)
from .production_preparation_provenance import PreparationPolicyProvenance
from .production_preparation_receipts import (
    PreparationReceiptError,
    _load_receipt_connection,
    _require_active_checkpoint,
    checkpoint_preparation_planner_returned,
    read_preparation_receipt,
)
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_planner import (
    BoundedProductionWorkOrderPlanner,
    WorkOrderPlannerResult,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


class PreparationPlannerResumeStatus(StrEnum):
    PLANNER_RETURNED = "PLANNER_RETURNED"
    PLANNER_RECOVERY_REQUIRED = "PLANNER_RECOVERY_REQUIRED"
    INVALID_AUTHORITY = "INVALID_AUTHORITY"


@dataclass(frozen=True)
class PreparationPlannerResumeResult:
    status: PreparationPlannerResumeStatus
    preparation_id: str
    task_id: str | None
    receipt: TaskPreparationReceipt | None
    planner_result: WorkOrderPlannerResult | None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "preparation_id": self.preparation_id,
            "task_id": self.task_id,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "planner_result": None
            if self.planner_result is None
            else {
                "run_id": self.planner_result.run_id,
                "route_decision_id": self.planner_result.route_decision_id,
                "route_decision_hash": self.planner_result.route_decision_hash,
                "work_order_id": self.planner_result.work_order.work_order_id,
                "work_order_hash": self.planner_result.work_order.content_hash,
                "verification_id": self.planner_result.verification_id,
            },
            "detail": self.detail,
            "authority": "single-routed-preparation-planner-resume",
        }


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:4096]


def _current_receipt(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    fallback: TaskPreparationReceipt | None,
) -> TaskPreparationReceipt | None:
    try:
        return read_preparation_receipt(runtime, preparation_id)
    except Exception:
        return fallback


def _checkpoint_validated_planner_started(
    runtime: OriginForgeRuntime,
    boundary: RoutedPreparationPlannerBoundary,
) -> TaskPreparationReceipt:
    """CAS one already-validated ROUTED boundary to PLANNER_STARTED.

    Boundary resolution has already proved protected PREPPOL/provenance, route,
    owner, dispatch-contract, and model dependency authority. This writer performs
    no protected immutable reads: it reloads only the exact durable PREP row under
    BEGIN IMMEDIATE, proves it is byte-for-byte the validated receipt, rechecks
    the PREP/PREPPOL and plan/PREPPOL identities, then commits the no-replay marker.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(boundary, RoutedPreparationPlannerBoundary):
        raise TypeError("boundary must be a RoutedPreparationPlannerBoundary")

    snapshot = boundary.receipt
    policy = boundary.policy
    plan = boundary.dependencies.plan
    _require_active_checkpoint(
        snapshot,
        expected_stage=PreparationStage.ROUTED,
        expected_revision=snapshot.revision,
    )
    if (
        snapshot.preparation_policy_id != policy.preparation_policy_id
        or snapshot.preparation_policy_hash != policy.content_hash
        or plan.preparation_policy_id != policy.preparation_policy_id
        or plan.preparation_policy_hash != policy.content_hash
    ):
        raise PreparationReceiptError(
            "validated planner boundary no longer has an exact PREPPOL identity relation"
        )

    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, snapshot.preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.ROUTED,
            expected_revision=snapshot.revision,
        )
        if receipt != snapshot:
            raise StaleRevision(
                "PREP changed after planner-boundary validation"
            )
        if (
            receipt.preparation_policy_id != policy.preparation_policy_id
            or receipt.preparation_policy_hash != policy.content_hash
        ):
            raise PreparationReceiptError(
                "durable PREP no longer binds the validated PREPPOL"
            )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET planner_dependency_plan_hash = ?,
                   stage = 'PLANNER_STARTED', revision = ?, updated_at = ?
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = 'ROUTED' AND revision = ?
                 AND preparation_policy_id = ? AND preparation_policy_hash = ?""",
            (
                plan.plan_hash,
                new_revision,
                now,
                receipt.preparation_id,
                receipt.revision,
                policy.preparation_policy_id,
                policy.content_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("PREP changed during planner-start checkpoint")
        return _load_receipt_connection(conn, receipt.preparation_id)


def _resume_validated_routed_preparation_planner_once(
    runtime: OriginForgeRuntime,
    boundary: RoutedPreparationPlannerBoundary,
) -> PreparationPlannerResumeResult:
    """Persist one no-replay marker, invoke one planner at most once, then stop."""

    receipt = boundary.receipt
    preparation_id = receipt.preparation_id
    try:
        started = _checkpoint_validated_planner_started(runtime, boundary)
    except (PreparationReceiptError, StaleRevision, RuntimeError, TypeError, ValueError) as exc:
        current = _current_receipt(runtime, preparation_id, receipt)
        if (
            current is not None
            and current.status is PreparationStatus.ACTIVE
            and current.stage is PreparationStage.PLANNER_STARTED
        ):
            status = PreparationPlannerResumeStatus.PLANNER_RECOVERY_REQUIRED
        else:
            status = PreparationPlannerResumeStatus.INVALID_AUTHORITY
        return PreparationPlannerResumeResult(
            status,
            preparation_id,
            receipt.task_id,
            current,
            None,
            _detail(exc),
        )

    # The no-replay fence is now durable. Only this CAS winner may invoke the
    # model-backed planner, and it does so exactly once.
    try:
        route_decision_id = started.route_decision_id
        if route_decision_id is None:
            raise PreparationReceiptError(
                "PLANNER_STARTED receipt lacks exact route decision identity"
            )
        planner = BoundedProductionWorkOrderPlanner(
            runtime,
            ProductionCapabilityStore(runtime),
            boundary.dispatch_catalog,
            build_builtin_dispatch_validator_registry(),
            boundary.dependencies.model,
        )
        planner_result = planner.propose(
            route_decision_id,
            allowed_input_refs=boundary.allowed_input_refs,
        )
        returned = checkpoint_preparation_planner_returned(
            runtime,
            preparation_id,
            started.revision,
            planner_result,
        )
    except Exception as exc:
        current = _current_receipt(runtime, preparation_id, started)
        return PreparationPlannerResumeResult(
            PreparationPlannerResumeStatus.PLANNER_RECOVERY_REQUIRED,
            preparation_id,
            started.task_id,
            current,
            None,
            _detail(exc),
        )

    return PreparationPlannerResumeResult(
        PreparationPlannerResumeStatus.PLANNER_RETURNED,
        preparation_id,
        returned.task_id,
        returned,
        planner_result,
        None,
    )


def _resume_same_call_routed_preparation_planner_once(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
    policy: TaskPreparationPolicyBinding,
    route: CapabilityRouteDecision,
    provenance: PreparationPolicyProvenance,
) -> PreparationPlannerResumeResult:
    """Normal Phase39 entrypoint using WAL-safe same-call boundary validation."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(receipt, TaskPreparationReceipt):
        raise TypeError("receipt must be a TaskPreparationReceipt")
    preparation_id = receipt.preparation_id
    try:
        boundary = resolve_same_call_routed_preparation_planner_boundary(
            runtime,
            receipt,
            policy,
            route,
            provenance,
        )
    except PreparationPlannerBoundaryError as exc:
        current = _current_receipt(runtime, preparation_id, receipt)
        return PreparationPlannerResumeResult(
            PreparationPlannerResumeStatus.INVALID_AUTHORITY,
            preparation_id,
            receipt.task_id,
            current,
            None,
            _detail(exc),
        )
    return _resume_validated_routed_preparation_planner_once(runtime, boundary)


def resume_routed_preparation_planner_once(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
) -> PreparationPlannerResumeResult:
    """Cross one exact ROUTED recovery planner boundary at most once and stop.

    D1 reconstructs all current authority before mutation. The durable
    PLANNER_STARTED compare-and-swap is committed before the only planner call.
    Any loser, stale state, ordinary post-marker failure, or pre-existing marker
    returns without replaying or selecting another PREP/Task.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(preparation_id, str):
        raise TypeError("preparation_id must be a string")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")

    try:
        boundary = resolve_routed_preparation_planner_boundary(
            runtime,
            preparation_id,
            expected_revision,
        )
    except PreparationPlannerBoundaryError as exc:
        current = _current_receipt(runtime, preparation_id, None)
        if (
            current is not None
            and current.status is PreparationStatus.ACTIVE
            and current.stage is PreparationStage.PLANNER_STARTED
        ):
            return PreparationPlannerResumeResult(
                PreparationPlannerResumeStatus.PLANNER_RECOVERY_REQUIRED,
                preparation_id,
                current.task_id,
                current,
                None,
                "durable PLANNER_STARTED already exists; planner replay is forbidden",
            )
        return PreparationPlannerResumeResult(
            PreparationPlannerResumeStatus.INVALID_AUTHORITY,
            preparation_id,
            None if current is None else current.task_id,
            current,
            None,
            _detail(exc),
        )

    return _resume_validated_routed_preparation_planner_once(runtime, boundary)
