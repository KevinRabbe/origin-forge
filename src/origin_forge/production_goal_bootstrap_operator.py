from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_goal_bootstrap_authority import acquire_current_goal_bootstrap
from .production_goal_bootstrap_finalize import finalize_goal_bootstrap
from .production_goal_bootstrap_models import (
    GoalBootstrapReceipt,
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from .production_goal_bootstrap_planner import advance_goal_bootstrap_planner
from .production_goal_bootstrap_store import (
    GoalBootstrapStoreError,
    _receipt_from_row,
)
from .production_planning_evidence import ProductionPlanningEvidenceError, goal_planning_hash
from .production_preparation_policy_store import read_preparation_policy
from .production_read_guard import production_read_connection
from .runtime import OriginForgeRuntime


_MAX_GOAL_BOOTSTRAP_HISTORY = 64
_PRE_PLANNER_STAGES = frozenset(
    {
        GoalBootstrapStage.CLAIMED,
        GoalBootstrapStage.AUTHORITY_PUBLISHED,
        GoalBootstrapStage.PLANNING_INPUT_PUBLISHED,
    }
)
_POST_PLANNER_STAGES = frozenset(
    {
        GoalBootstrapStage.PLANNER_RETURNED,
        GoalBootstrapStage.PLAN_AUDITED,
    }
)


class GoalBootstrapOperatorError(RuntimeError):
    pass


class GoalBootstrapDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    ACTIVE_PRE_PLANNER = "ACTIVE_PRE_PLANNER"
    PLANNER_RECOVERY_REQUIRED = "PLANNER_RECOVERY_REQUIRED"
    POST_PLANNER_RESUMABLE = "POST_PLANNER_RESUMABLE"
    MATERIALIZED_NEEDS_PREPPOL = "MATERIALIZED_NEEDS_PREPPOL"
    READY_FOR_MANAGER = "READY_FOR_MANAGER"
    STALE_GOAL = "STALE_GOAL"
    FAILED_PRE_PLANNER = "FAILED_PRE_PLANNER"
    INTERRUPTED = "INTERRUPTED"
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"
    INVALID_STATE = "INVALID_STATE"


class GoalBootstrapOperatorAction(StrEnum):
    BOOTSTRAP = "BOOTSTRAP"
    RECOVER = "RECOVER"


class GoalBootstrapOperatorStatus(StrEnum):
    READY = "READY"
    ALREADY_READY = "ALREADY_READY"


class GoalBootstrapOperatorBlocked(GoalBootstrapOperatorError):
    def __init__(self, decision: GoalBootstrapDecision, detail: str) -> None:
        super().__init__(detail)
        self.decision = decision
        self.detail = detail


@dataclass(frozen=True)
class GoalBootstrapStatusProjection:
    decision: GoalBootstrapDecision
    goal_id: str
    goal_revision: int | None
    goal_content_hash: str | None
    receipt: GoalBootstrapReceipt | None
    exact_revision_receipt_count: int
    historical_receipt_count: int
    detail: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_content_hash": self.goal_content_hash,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "exact_revision_receipt_count": self.exact_revision_receipt_count,
            "historical_receipt_count": self.historical_receipt_count,
            "detail": self.detail,
            "authority": "phase45e-goal-bootstrap-readonly-status",
        }


@dataclass(frozen=True)
class GoalBootstrapOperatorResult:
    action: GoalBootstrapOperatorAction
    status: GoalBootstrapOperatorStatus
    receipt: GoalBootstrapReceipt

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "status": self.status.value,
            "receipt": self.receipt.to_dict(),
            "authority": "phase45e-goal-bootstrap-operator",
        }


def _projection(
    decision: GoalBootstrapDecision,
    goal_id: str,
    *,
    goal_revision: int | None,
    goal_content_hash: str | None,
    receipt: GoalBootstrapReceipt | None,
    exact_count: int,
    historical_count: int,
    detail: str | None = None,
) -> GoalBootstrapStatusProjection:
    return GoalBootstrapStatusProjection(
        decision=decision,
        goal_id=goal_id,
        goal_revision=goal_revision,
        goal_content_hash=goal_content_hash,
        receipt=receipt,
        exact_revision_receipt_count=exact_count,
        historical_receipt_count=historical_count,
        detail=detail,
    )


def _decision_for_receipt(receipt: GoalBootstrapReceipt) -> GoalBootstrapDecision:
    if receipt.status is GoalBootstrapStatus.READY:
        if receipt.stage is GoalBootstrapStage.PREPPOL_PUBLISHED:
            return GoalBootstrapDecision.READY_FOR_MANAGER
        return GoalBootstrapDecision.INVALID_STATE
    if receipt.status is GoalBootstrapStatus.FAILED_PRE_PLANNER:
        return GoalBootstrapDecision.FAILED_PRE_PLANNER
    if receipt.status is GoalBootstrapStatus.INTERRUPTED:
        return GoalBootstrapDecision.INTERRUPTED
    if receipt.status is not GoalBootstrapStatus.ACTIVE:
        return GoalBootstrapDecision.INVALID_STATE
    if receipt.stage in _PRE_PLANNER_STAGES:
        return GoalBootstrapDecision.ACTIVE_PRE_PLANNER
    if receipt.stage is GoalBootstrapStage.PLANNER_STARTED:
        return GoalBootstrapDecision.PLANNER_RECOVERY_REQUIRED
    if receipt.stage in _POST_PLANNER_STAGES:
        return GoalBootstrapDecision.POST_PLANNER_RESUMABLE
    if receipt.stage is GoalBootstrapStage.MATERIALIZED:
        return GoalBootstrapDecision.MATERIALIZED_NEEDS_PREPPOL
    return GoalBootstrapDecision.INVALID_STATE


def _validate_ready_policy_readonly(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> str | None:
    policy_id = receipt.preparation_policy_id
    if policy_id is None or receipt.preparation_policy_hash is None:
        return "READY GOALBOOT lacks PREPPOL identity"
    try:
        policy = read_preparation_policy(runtime, policy_id)
    except Exception as exc:
        return f"READY PREPPOL is not current: {type(exc).__name__}: {exc}"
    if (
        policy.content_hash != receipt.preparation_policy_hash
        or policy.materialization_id != receipt.materialization_id
        or policy.materialization_hash != receipt.materialization_hash
        or policy.planning_input_id != receipt.planning_input_id
        or policy.planning_input_hash != receipt.planning_input_hash
        or policy.capability_catalog_id != receipt.capability_catalog_id
        or policy.capability_catalog_hash != receipt.capability_catalog_hash
        or policy.capability_routing_policy_id != receipt.capability_routing_policy_id
        or policy.capability_routing_policy_hash != receipt.capability_routing_policy_hash
        or policy.dispatch_contract_catalog_id != receipt.dispatch_contract_catalog_id
        or policy.dispatch_contract_catalog_hash != receipt.dispatch_contract_catalog_hash
    ):
        return "READY PREPPOL drifted from exact GOALBOOT authority"
    return None


def inspect_goal_bootstrap_status_readonly(
    runtime: OriginForgeRuntime,
    goal_id: str,
) -> GoalBootstrapStatusProjection:
    """Classify one explicit Goal without creating, migrating, repairing, or replaying work."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(goal_id, str) or not validate_id(goal_id, IdKind.GOAL):
        raise GoalBootstrapOperatorError("goal_id must be a valid GOAL ID")

    try:
        with production_read_connection(runtime) as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?",
                (str(runtime.project_root),),
            ).fetchone()
            if project is None:
                raise GoalBootstrapOperatorError("project is not initialized")
            project_id = str(project["id"])
            goal = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                (goal_id, project_id),
            ).fetchone()
            if goal is None:
                return _projection(
                    GoalBootstrapDecision.INVALID_STATE,
                    goal_id,
                    goal_revision=None,
                    goal_content_hash=None,
                    receipt=None,
                    exact_count=0,
                    historical_count=0,
                    detail="Goal does not exist in the current project",
                )
            try:
                goal_revision = int(goal["revision"])
                goal_content_hash = goal_planning_hash(goal)
            except (TypeError, ValueError, ProductionPlanningEvidenceError) as exc:
                return _projection(
                    GoalBootstrapDecision.INVALID_STATE,
                    goal_id,
                    goal_revision=None,
                    goal_content_hash=None,
                    receipt=None,
                    exact_count=0,
                    historical_count=0,
                    detail=f"canonical Goal state is invalid: {type(exc).__name__}: {exc}",
                )

            count_row = conn.execute(
                "SELECT COUNT(*) AS count FROM goal_bootstraps WHERE project_id = ? AND goal_id = ?",
                (project_id, goal_id),
            ).fetchone()
            history_count = 0 if count_row is None else int(count_row["count"])
            if history_count > _MAX_GOAL_BOOTSTRAP_HISTORY:
                return _projection(
                    GoalBootstrapDecision.INVALID_STATE,
                    goal_id,
                    goal_revision=goal_revision,
                    goal_content_hash=goal_content_hash,
                    receipt=None,
                    exact_count=0,
                    historical_count=history_count,
                    detail="Goal bootstrap history exceeds the bounded Phase-45 inspection limit",
                )

            rows = conn.execute(
                """SELECT * FROM goal_bootstraps
                   WHERE project_id = ? AND goal_id = ?
                   ORDER BY created_at, bootstrap_id""",
                (project_id, goal_id),
            ).fetchall()
            try:
                receipts = tuple(_receipt_from_row(row) for row in rows)
            except GoalBootstrapStoreError as exc:
                return _projection(
                    GoalBootstrapDecision.INVALID_STATE,
                    goal_id,
                    goal_revision=goal_revision,
                    goal_content_hash=goal_content_hash,
                    receipt=None,
                    exact_count=0,
                    historical_count=history_count,
                    detail=f"stored GOALBOOT receipt is invalid: {exc}",
                )
    except GoalBootstrapOperatorError:
        raise
    except Exception as exc:
        raise GoalBootstrapOperatorError(
            f"Goal bootstrap status is unavailable: {type(exc).__name__}: {exc}"
        ) from exc

    exact = tuple(
        receipt
        for receipt in receipts
        if receipt.goal_revision == goal_revision
        and receipt.goal_content_hash == goal_content_hash
    )
    same_revision_drift = tuple(
        receipt
        for receipt in receipts
        if receipt.goal_revision == goal_revision
        and receipt.goal_content_hash != goal_content_hash
    )
    historical_count = len(receipts) - len(exact)

    if len(exact) > 1:
        return _projection(
            GoalBootstrapDecision.AMBIGUOUS_AUTHORITY,
            goal_id,
            goal_revision=goal_revision,
            goal_content_hash=goal_content_hash,
            receipt=None,
            exact_count=len(exact),
            historical_count=historical_count,
            detail="multiple GOALBOOT receipts bind the exact current Goal revision",
        )
    if not exact:
        if same_revision_drift:
            return _projection(
                GoalBootstrapDecision.STALE_GOAL,
                goal_id,
                goal_revision=goal_revision,
                goal_content_hash=goal_content_hash,
                receipt=None,
                exact_count=0,
                historical_count=historical_count,
                detail="stored GOALBOOT authority uses the current revision number with a different Goal hash",
            )
        return _projection(
            GoalBootstrapDecision.ELIGIBLE,
            goal_id,
            goal_revision=goal_revision,
            goal_content_hash=goal_content_hash,
            receipt=None,
            exact_count=0,
            historical_count=historical_count,
        )

    receipt = exact[0]
    decision = _decision_for_receipt(receipt)
    detail = None
    if decision is GoalBootstrapDecision.READY_FOR_MANAGER:
        detail = _validate_ready_policy_readonly(runtime, receipt)
        if detail is not None:
            decision = GoalBootstrapDecision.INVALID_STATE
    elif decision is GoalBootstrapDecision.INVALID_STATE:
        detail = "GOALBOOT status/stage combination is outside the Phase-45 operator contract"
    return _projection(
        decision,
        goal_id,
        goal_revision=goal_revision,
        goal_content_hash=goal_content_hash,
        receipt=receipt,
        exact_count=1,
        historical_count=historical_count,
        detail=detail,
    )


def _blocked(projection: GoalBootstrapStatusProjection, *, operation: str) -> GoalBootstrapOperatorBlocked:
    detail = projection.detail or (
        f"Goal bootstrap decision {projection.decision.value} does not permit {operation}"
    )
    return GoalBootstrapOperatorBlocked(projection.decision, detail)


def _ready_result(
    runtime: OriginForgeRuntime,
    projection: GoalBootstrapStatusProjection,
    *,
    action: GoalBootstrapOperatorAction,
) -> GoalBootstrapOperatorResult:
    receipt = projection.receipt
    if receipt is None:
        raise GoalBootstrapOperatorError("READY decision lacks an exact GOALBOOT receipt")
    try:
        finalized = finalize_goal_bootstrap(runtime, receipt.bootstrap_id)
    except Exception as exc:
        raise GoalBootstrapOperatorError(
            f"READY GOALBOOT failed exact revalidation: {type(exc).__name__}: {exc}"
        ) from exc
    return GoalBootstrapOperatorResult(
        action=action,
        status=GoalBootstrapOperatorStatus.ALREADY_READY,
        receipt=finalized.receipt,
    )


def bootstrap_goal_once(
    runtime: OriginForgeRuntime,
    goal_id: str,
) -> GoalBootstrapOperatorResult:
    """Bootstrap one explicit current Goal once; existing non-READY work requires recovery."""

    projection = inspect_goal_bootstrap_status_readonly(runtime, goal_id)
    if projection.decision is GoalBootstrapDecision.READY_FOR_MANAGER:
        return _ready_result(
            runtime,
            projection,
            action=GoalBootstrapOperatorAction.BOOTSTRAP,
        )
    if projection.decision is not GoalBootstrapDecision.ELIGIBLE:
        raise _blocked(projection, operation="a fresh bootstrap")

    try:
        receipt = acquire_current_goal_bootstrap(runtime, goal_id)
        advance_goal_bootstrap_planner(runtime, receipt.bootstrap_id)
        finalized = finalize_goal_bootstrap(runtime, receipt.bootstrap_id)
    except GoalBootstrapOperatorError:
        raise
    except Exception as exc:
        raise GoalBootstrapOperatorError(
            f"Goal bootstrap failed closed: {type(exc).__name__}: {exc}"
        ) from exc
    return GoalBootstrapOperatorResult(
        action=GoalBootstrapOperatorAction.BOOTSTRAP,
        status=GoalBootstrapOperatorStatus.READY,
        receipt=finalized.receipt,
    )


def recover_goal_once(
    runtime: OriginForgeRuntime,
    goal_id: str,
) -> GoalBootstrapOperatorResult:
    """Explicitly resume one unique exact current GOALBOOT without acquiring a replacement."""

    projection = inspect_goal_bootstrap_status_readonly(runtime, goal_id)
    if projection.decision is GoalBootstrapDecision.READY_FOR_MANAGER:
        return _ready_result(
            runtime,
            projection,
            action=GoalBootstrapOperatorAction.RECOVER,
        )
    recoverable = {
        GoalBootstrapDecision.ACTIVE_PRE_PLANNER,
        GoalBootstrapDecision.PLANNER_RECOVERY_REQUIRED,
        GoalBootstrapDecision.POST_PLANNER_RESUMABLE,
        GoalBootstrapDecision.MATERIALIZED_NEEDS_PREPPOL,
    }
    if projection.decision not in recoverable or projection.receipt is None:
        raise _blocked(projection, operation="explicit recovery")

    receipt = projection.receipt
    try:
        if receipt.stage in _PRE_PLANNER_STAGES or receipt.stage is GoalBootstrapStage.PLANNER_STARTED:
            advance_goal_bootstrap_planner(runtime, receipt.bootstrap_id)
        finalized = finalize_goal_bootstrap(runtime, receipt.bootstrap_id)
    except Exception as exc:
        raise GoalBootstrapOperatorError(
            f"Goal bootstrap recovery failed closed: {type(exc).__name__}: {exc}"
        ) from exc
    return GoalBootstrapOperatorResult(
        action=GoalBootstrapOperatorAction.RECOVER,
        status=GoalBootstrapOperatorStatus.READY,
        receipt=finalized.receipt,
    )
