from __future__ import annotations

from dataclasses import dataclass

from .ids import IdKind, validate_id
from .production_goal_bootstrap_authority import (
    acquire_current_goal_bootstrap,
    prepare_goal_bootstrap_input,
)
from .production_goal_bootstrap_finalize import finalize_goal_bootstrap
from .production_goal_bootstrap_models import GoalBootstrapReceipt, GoalBootstrapStatus
from .production_goal_bootstrap_planner import advance_goal_bootstrap_planner
from .production_goal_bootstrap_store import (
    GoalBootstrapStoreError,
    read_goal_bootstrap_receipt,
)
from .production_planning_evidence import goal_planning_hash
from .runtime import OriginForgeRuntime


class GoalBootstrapOperatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoalBootstrapStatusView:
    goal_id: str
    goal_revision: int
    goal_content_hash: str
    attempt_count: int
    receipt: GoalBootstrapReceipt | None

    @property
    def exists(self) -> bool:
        return self.receipt is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_content_hash": self.goal_content_hash,
            "attempt_count": self.attempt_count,
            "exists": self.exists,
            "receipt": self.receipt.to_dict() if self.receipt is not None else None,
            "read_only": True,
            "authority": "phase45e-goal-bootstrap-status",
        }


@dataclass(frozen=True)
class GoalBootstrapOperatorResult:
    receipt: GoalBootstrapReceipt
    created: bool
    advanced: bool

    @property
    def ready(self) -> bool:
        return self.receipt.status is GoalBootstrapStatus.READY

    @property
    def terminal(self) -> bool:
        return self.receipt.status in (
            GoalBootstrapStatus.FAILED_PRE_PLANNER,
            GoalBootstrapStatus.INTERRUPTED,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt": self.receipt.to_dict(),
            "created": self.created,
            "advanced": self.advanced,
            "ready": self.ready,
            "terminal": self.terminal,
            "manager_advanced": False,
            "authority": "phase45e-goal-bootstrap-operator",
        }


def _goal_attempts(
    runtime: OriginForgeRuntime,
    goal_id: str,
) -> tuple[int, str, tuple[GoalBootstrapReceipt, ...]]:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(goal_id, str) or not validate_id(goal_id, IdKind.GOAL):
        raise GoalBootstrapOperatorError("goal_id must be a valid GOAL ID")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        goal = conn.execute(
            "SELECT * FROM goals WHERE id = ? AND project_id = ?",
            (goal_id, project_id),
        ).fetchone()
        if goal is None:
            raise GoalBootstrapOperatorError("Goal does not exist in current project")
        try:
            goal_revision = int(goal["revision"])
            goal_content_hash = goal_planning_hash(goal)
        except (TypeError, ValueError) as exc:
            raise GoalBootstrapOperatorError("current Goal state is invalid") from exc
        rows = conn.execute(
            """SELECT bootstrap_id, status, created_at
               FROM goal_bootstraps
               WHERE project_id = ? AND goal_id = ? AND goal_revision = ?
               ORDER BY created_at DESC, bootstrap_id DESC""",
            (project_id, goal_id, goal_revision),
        ).fetchall()

    receipts = tuple(
        read_goal_bootstrap_receipt(runtime, str(row["bootstrap_id"]))
        for row in rows
    )
    for receipt in receipts:
        if (
            receipt.goal_revision != goal_revision
            or receipt.goal_content_hash != goal_content_hash
        ):
            raise GoalBootstrapOperatorError(
                "GOALBOOT history drifted from the current Goal revision"
            )
    current = [
        receipt
        for receipt in receipts
        if receipt.status in (GoalBootstrapStatus.ACTIVE, GoalBootstrapStatus.READY)
    ]
    if len(current) > 1:
        raise GoalBootstrapOperatorError(
            "multiple current GOALBOOT receipts exist for one Goal revision"
        )
    return goal_revision, goal_content_hash, receipts


def _selected_attempt(receipts: tuple[GoalBootstrapReceipt, ...]) -> GoalBootstrapReceipt | None:
    for receipt in receipts:
        if receipt.status in (GoalBootstrapStatus.ACTIVE, GoalBootstrapStatus.READY):
            return receipt
    if receipts:
        # Terminal history is deliberately surfaced instead of being converted
        # into an implicit retry. A later retry/recovery authority must be explicit.
        return receipts[0]
    return None


def goal_bootstrap_status(
    runtime: OriginForgeRuntime,
    goal_id: str,
) -> GoalBootstrapStatusView:
    """Return the exact current-revision bootstrap view without writing state."""

    goal_revision, goal_content_hash, receipts = _goal_attempts(runtime, goal_id)
    return GoalBootstrapStatusView(
        goal_id=goal_id,
        goal_revision=goal_revision,
        goal_content_hash=goal_content_hash,
        attempt_count=len(receipts),
        receipt=_selected_attempt(receipts),
    )


def bootstrap_goal(
    runtime: OriginForgeRuntime,
    goal_id: str,
) -> GoalBootstrapOperatorResult:
    """Explicitly advance one Goal through governed bootstrap authority only.

    This composes the existing Phase-45 authorities and stops at READY /
    PREPPOL_PUBLISHED. It never invokes Manager advancement and never turns a
    terminal bootstrap into an implicit retry.
    """

    _, _, receipts = _goal_attempts(runtime, goal_id)
    receipt = _selected_attempt(receipts)
    created = False
    if receipt is None:
        try:
            receipt = acquire_current_goal_bootstrap(runtime, goal_id)
            created = True
        except GoalBootstrapStoreError:
            # A concurrent explicit caller may have won acquisition. Converge
            # only to the newly durable attempt; never manufacture another one.
            _, _, raced = _goal_attempts(runtime, goal_id)
            receipt = _selected_attempt(raced)
            if receipt is None:
                raise

    if receipt.status is GoalBootstrapStatus.READY:
        return GoalBootstrapOperatorResult(receipt=receipt, created=created, advanced=False)
    if receipt.status is not GoalBootstrapStatus.ACTIVE:
        return GoalBootstrapOperatorResult(receipt=receipt, created=created, advanced=False)

    advanced = False
    try:
        prepare_goal_bootstrap_input(runtime, receipt.bootstrap_id)
        advanced = True
        advance_goal_bootstrap_planner(runtime, receipt.bootstrap_id)
        finalized = finalize_goal_bootstrap(runtime, receipt.bootstrap_id)
        return GoalBootstrapOperatorResult(
            receipt=finalized.receipt,
            created=created,
            advanced=True,
        )
    except Exception:
        durable = read_goal_bootstrap_receipt(runtime, receipt.bootstrap_id)
        if durable.status is not GoalBootstrapStatus.ACTIVE:
            return GoalBootstrapOperatorResult(
                receipt=durable,
                created=created,
                advanced=advanced,
            )
        raise
