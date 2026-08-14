from __future__ import annotations

import sqlite3
from dataclasses import replace

from .ids import IdKind, new_id, validate_id
from .production_goal_bootstrap_models import (
    GoalBootstrapReceipt,
    GoalBootstrapStage,
    GoalBootstrapStatus,
    ProductionGoalBootstrapModelError,
)
from .production_planning_evidence import (
    ProductionPlanningEvidenceError,
    goal_planning_hash,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


class GoalBootstrapStoreError(RuntimeError):
    pass


def _receipt_from_row(row: sqlite3.Row) -> GoalBootstrapReceipt:
    try:
        return GoalBootstrapReceipt(
            bootstrap_id=row["bootstrap_id"],
            project_id=row["project_id"],
            goal_id=row["goal_id"],
            goal_revision=int(row["goal_revision"]),
            goal_content_hash=row["goal_content_hash"],
            bootstrap_owner_id=row["bootstrap_owner_id"],
            bootstrap_owner_fingerprint=row["bootstrap_owner_fingerprint"],
            bootstrap_contract_version=row["bootstrap_contract_version"],
            capability_catalog_id=row["capability_catalog_id"],
            capability_catalog_hash=row["capability_catalog_hash"],
            capability_routing_policy_id=row["capability_routing_policy_id"],
            capability_routing_policy_hash=row["capability_routing_policy_hash"],
            dispatch_contract_catalog_id=row["dispatch_contract_catalog_id"],
            dispatch_contract_catalog_hash=row["dispatch_contract_catalog_hash"],
            planning_input_id=row["planning_input_id"],
            planning_input_hash=row["planning_input_hash"],
            planner_dependency_plan_hash=row["planner_dependency_plan_hash"],
            planner_run_id=row["planner_run_id"],
            plan_proposal_id=row["plan_proposal_id"],
            plan_proposal_hash=row["plan_proposal_hash"],
            plan_audit_id=row["plan_audit_id"],
            plan_audit_hash=row["plan_audit_hash"],
            materialization_id=row["materialization_id"],
            materialization_hash=row["materialization_hash"],
            preparation_policy_id=row["preparation_policy_id"],
            preparation_policy_hash=row["preparation_policy_hash"],
            stage=GoalBootstrapStage(row["stage"]),
            status=GoalBootstrapStatus(row["status"]),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_reason=row["terminal_reason"],
        )
    except (KeyError, TypeError, ValueError, ProductionGoalBootstrapModelError) as exc:
        raise GoalBootstrapStoreError("stored GOALBOOT receipt is invalid") from exc


def _load_receipt_connection(
    conn: sqlite3.Connection,
    bootstrap_id: str,
) -> GoalBootstrapReceipt:
    if not isinstance(bootstrap_id, str) or not validate_id(
        bootstrap_id, IdKind.GOAL_BOOTSTRAP
    ):
        raise GoalBootstrapStoreError("bootstrap_id must be a valid GOALBOOT ID")
    row = conn.execute(
        "SELECT * FROM goal_bootstraps WHERE bootstrap_id = ?",
        (bootstrap_id,),
    ).fetchone()
    if row is None:
        raise GoalBootstrapStoreError("GOALBOOT receipt does not exist")
    return _receipt_from_row(row)


def read_goal_bootstrap_receipt(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
) -> GoalBootstrapReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        receipt = _load_receipt_connection(conn, bootstrap_id)
    if receipt.project_id != project_id:
        raise GoalBootstrapStoreError("GOALBOOT receipt belongs to another project")
    return receipt


def _require_active_checkpoint(
    receipt: GoalBootstrapReceipt,
    *,
    expected_stage: GoalBootstrapStage,
    expected_revision: int,
) -> None:
    if type(expected_revision) is not int or expected_revision < 0:
        raise GoalBootstrapStoreError(
            "expected_revision must be a non-negative integer"
        )
    if receipt.status is not GoalBootstrapStatus.ACTIVE:
        raise GoalBootstrapStoreError("GOALBOOT receipt is not ACTIVE")
    if receipt.stage is not expected_stage:
        raise GoalBootstrapStoreError(
            f"GOALBOOT receipt stage is {receipt.stage.value}, not {expected_stage.value}"
        )
    if receipt.revision != expected_revision:
        raise StaleRevision(
            f"goal bootstrap {receipt.bootstrap_id} revision {receipt.revision} != expected {expected_revision}"
        )


def _require_goal_current(
    conn: sqlite3.Connection,
    receipt: GoalBootstrapReceipt,
) -> None:
    row = conn.execute(
        "SELECT * FROM goals WHERE id = ? AND project_id = ?",
        (receipt.goal_id, receipt.project_id),
    ).fetchone()
    if row is None:
        raise GoalBootstrapStoreError("GOALBOOT Goal is unavailable")
    try:
        current_revision = int(row["revision"])
        current_hash = goal_planning_hash(row)
    except (TypeError, ValueError, ProductionPlanningEvidenceError) as exc:
        raise GoalBootstrapStoreError("GOALBOOT Goal state is invalid") from exc
    if (
        current_revision != receipt.goal_revision
        or current_hash != receipt.goal_content_hash
    ):
        raise StaleRevision("Goal changed after GOALBOOT acquisition")


def acquire_goal_bootstrap_receipt(
    runtime: OriginForgeRuntime,
    goal_id: str,
    *,
    bootstrap_owner_id: str,
    bootstrap_owner_fingerprint: str,
    bootstrap_contract_version: str,
) -> GoalBootstrapReceipt:
    """Acquire durable ownership for one exact current Goal revision.

    This is receipt acquisition only. It does not publish authority, freeze a
    PlanningInput, invoke a model, audit a proposal, materialize work, or
    publish PREPPOL.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(goal_id, str) or not validate_id(goal_id, IdKind.GOAL):
        raise GoalBootstrapStoreError("goal_id must be a valid GOAL ID")
    project_id = runtime.project_id()
    bootstrap_id = new_id(IdKind.GOAL_BOOTSTRAP)
    now = utc_now()
    try:
        with runtime.store.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                (goal_id, project_id),
            ).fetchone()
            if row is None:
                raise GoalBootstrapStoreError("Goal does not exist in current project")
            try:
                goal_revision = int(row["revision"])
                goal_content_hash = goal_planning_hash(row)
            except (TypeError, ValueError, ProductionPlanningEvidenceError) as exc:
                raise GoalBootstrapStoreError("canonical Goal state is invalid") from exc
            existing = conn.execute(
                """SELECT bootstrap_id FROM goal_bootstraps
                   WHERE project_id = ? AND goal_id = ? AND goal_revision = ?
                     AND status IN ('ACTIVE', 'READY')
                   LIMIT 1""",
                (project_id, goal_id, goal_revision),
            ).fetchone()
            if existing is not None:
                raise GoalBootstrapStoreError(
                    f"Goal revision already has current bootstrap {existing['bootstrap_id']}"
                )
            receipt = GoalBootstrapReceipt(
                bootstrap_id=bootstrap_id,
                project_id=project_id,
                goal_id=goal_id,
                goal_revision=goal_revision,
                goal_content_hash=goal_content_hash,
                bootstrap_owner_id=bootstrap_owner_id,
                bootstrap_owner_fingerprint=bootstrap_owner_fingerprint,
                bootstrap_contract_version=bootstrap_contract_version,
                capability_catalog_id=None,
                capability_catalog_hash=None,
                capability_routing_policy_id=None,
                capability_routing_policy_hash=None,
                dispatch_contract_catalog_id=None,
                dispatch_contract_catalog_hash=None,
                planning_input_id=None,
                planning_input_hash=None,
                planner_dependency_plan_hash=None,
                planner_run_id=None,
                plan_proposal_id=None,
                plan_proposal_hash=None,
                plan_audit_id=None,
                plan_audit_hash=None,
                materialization_id=None,
                materialization_hash=None,
                preparation_policy_id=None,
                preparation_policy_hash=None,
                stage=GoalBootstrapStage.CLAIMED,
                status=GoalBootstrapStatus.ACTIVE,
                revision=0,
                created_at=now,
                updated_at=now,
                terminal_reason=None,
            )
            conn.execute(
                """INSERT INTO goal_bootstraps(
                    bootstrap_id, project_id, goal_id, goal_revision,
                    goal_content_hash, bootstrap_owner_id,
                    bootstrap_owner_fingerprint, bootstrap_contract_version,
                    capability_catalog_id, capability_catalog_hash,
                    capability_routing_policy_id, capability_routing_policy_hash,
                    dispatch_contract_catalog_id, dispatch_contract_catalog_hash,
                    planning_input_id, planning_input_hash,
                    planner_dependency_plan_hash, planner_run_id,
                    plan_proposal_id, plan_proposal_hash,
                    plan_audit_id, plan_audit_hash,
                    materialization_id, materialization_hash,
                    preparation_policy_id, preparation_policy_hash,
                    stage, status, revision, created_at, updated_at, terminal_reason
                ) VALUES (
                    :bootstrap_id, :project_id, :goal_id, :goal_revision,
                    :goal_content_hash, :bootstrap_owner_id,
                    :bootstrap_owner_fingerprint, :bootstrap_contract_version,
                    :capability_catalog_id, :capability_catalog_hash,
                    :capability_routing_policy_id, :capability_routing_policy_hash,
                    :dispatch_contract_catalog_id, :dispatch_contract_catalog_hash,
                    :planning_input_id, :planning_input_hash,
                    :planner_dependency_plan_hash, :planner_run_id,
                    :plan_proposal_id, :plan_proposal_hash,
                    :plan_audit_id, :plan_audit_hash,
                    :materialization_id, :materialization_hash,
                    :preparation_policy_id, :preparation_policy_hash,
                    :stage, :status, :revision, :created_at, :updated_at, :terminal_reason
                )""",
                receipt.to_dict(),
            )
            runtime.store._append_event(
                conn,
                "GOAL_BOOTSTRAP",
                bootstrap_id,
                "GOAL_BOOTSTRAP_ACQUIRED",
                None,
                GoalBootstrapStatus.ACTIVE.value,
                0,
                "SYSTEM",
                None,
                {
                    "goal_id": goal_id,
                    "goal_revision": goal_revision,
                    "goal_content_hash": goal_content_hash,
                },
                now,
            )
    except sqlite3.IntegrityError as exc:
        raise GoalBootstrapStoreError(
            "GOALBOOT acquisition lost the durable ownership race"
        ) from exc
    return receipt


def _checkpoint(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    expected_stage: GoalBootstrapStage,
    target_stage: GoalBootstrapStage,
    updates: dict[str, object],
    target_status: GoalBootstrapStatus = GoalBootstrapStatus.ACTIVE,
) -> GoalBootstrapReceipt:
    project_id = runtime.project_id()
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, bootstrap_id)
        if receipt.project_id != project_id:
            raise GoalBootstrapStoreError("GOALBOOT receipt belongs to another project")
        _require_active_checkpoint(
            receipt,
            expected_stage=expected_stage,
            expected_revision=expected_revision,
        )
        _require_goal_current(conn, receipt)
        candidate = replace(
            receipt,
            **updates,
            stage=target_stage,
            status=target_status,
            revision=receipt.revision + 1,
            updated_at=now,
        )
        set_values = dict(updates)
        set_values.update(
            {
                "stage": target_stage.value,
                "status": target_status.value,
                "new_revision": candidate.revision,
                "updated_at": now,
                "bootstrap_id": receipt.bootstrap_id,
                "expected_stage": expected_stage.value,
                "expected_revision": receipt.revision,
            }
        )
        set_clause = ", ".join(f"{column} = :{column}" for column in updates)
        if set_clause:
            set_clause += ", "
        cursor = conn.execute(
            f"""UPDATE goal_bootstraps
                SET {set_clause}stage = :stage, status = :status,
                    revision = :new_revision, updated_at = :updated_at
                WHERE bootstrap_id = :bootstrap_id AND status = 'ACTIVE'
                  AND stage = :expected_stage AND revision = :expected_revision""",
            set_values,
        )
        if cursor.rowcount != 1:
            raise StaleRevision("GOALBOOT changed during checkpoint")
        return _load_receipt_connection(conn, bootstrap_id)


def checkpoint_goal_bootstrap_authority_published(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    capability_catalog_id: str,
    capability_catalog_hash: str,
    capability_routing_policy_id: str,
    capability_routing_policy_hash: str,
    dispatch_contract_catalog_id: str,
    dispatch_contract_catalog_hash: str,
) -> GoalBootstrapReceipt:
    return _checkpoint(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=GoalBootstrapStage.CLAIMED,
        target_stage=GoalBootstrapStage.AUTHORITY_PUBLISHED,
        updates={
            "capability_catalog_id": capability_catalog_id,
            "capability_catalog_hash": capability_catalog_hash,
            "capability_routing_policy_id": capability_routing_policy_id,
            "capability_routing_policy_hash": capability_routing_policy_hash,
            "dispatch_contract_catalog_id": dispatch_contract_catalog_id,
            "dispatch_contract_catalog_hash": dispatch_contract_catalog_hash,
        },
    )


def checkpoint_goal_bootstrap_planning_input_published(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    planning_input_id: str,
    planning_input_hash: str,
) -> GoalBootstrapReceipt:
    return _checkpoint(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=GoalBootstrapStage.AUTHORITY_PUBLISHED,
        target_stage=GoalBootstrapStage.PLANNING_INPUT_PUBLISHED,
        updates={
            "planning_input_id": planning_input_id,
            "planning_input_hash": planning_input_hash,
        },
    )


def checkpoint_goal_bootstrap_planner_started(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    planner_dependency_plan_hash: str,
) -> GoalBootstrapReceipt:
    return _checkpoint(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=GoalBootstrapStage.PLANNING_INPUT_PUBLISHED,
        target_stage=GoalBootstrapStage.PLANNER_STARTED,
        updates={"planner_dependency_plan_hash": planner_dependency_plan_hash},
    )


def checkpoint_goal_bootstrap_planner_returned(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    planner_run_id: str,
    plan_proposal_id: str,
    plan_proposal_hash: str,
) -> GoalBootstrapReceipt:
    return _checkpoint(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=GoalBootstrapStage.PLANNER_STARTED,
        target_stage=GoalBootstrapStage.PLANNER_RETURNED,
        updates={
            "planner_run_id": planner_run_id,
            "plan_proposal_id": plan_proposal_id,
            "plan_proposal_hash": plan_proposal_hash,
        },
    )


def checkpoint_goal_bootstrap_plan_audited(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    plan_audit_id: str,
    plan_audit_hash: str,
) -> GoalBootstrapReceipt:
    return _checkpoint(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=GoalBootstrapStage.PLANNER_RETURNED,
        target_stage=GoalBootstrapStage.PLAN_AUDITED,
        updates={
            "plan_audit_id": plan_audit_id,
            "plan_audit_hash": plan_audit_hash,
        },
    )


def checkpoint_goal_bootstrap_materialized(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    materialization_id: str,
    materialization_hash: str,
) -> GoalBootstrapReceipt:
    return _checkpoint(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=GoalBootstrapStage.PLAN_AUDITED,
        target_stage=GoalBootstrapStage.MATERIALIZED,
        updates={
            "materialization_id": materialization_id,
            "materialization_hash": materialization_hash,
        },
    )


def checkpoint_goal_bootstrap_preppol_published(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    preparation_policy_id: str,
    preparation_policy_hash: str,
) -> GoalBootstrapReceipt:
    return _checkpoint(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=GoalBootstrapStage.MATERIALIZED,
        target_stage=GoalBootstrapStage.PREPPOL_PUBLISHED,
        target_status=GoalBootstrapStatus.READY,
        updates={
            "preparation_policy_id": preparation_policy_id,
            "preparation_policy_hash": preparation_policy_hash,
        },
    )


def fail_goal_bootstrap_before_planner(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    expected_stage: GoalBootstrapStage,
    reason: str,
) -> GoalBootstrapReceipt:
    if expected_stage not in (
        GoalBootstrapStage.CLAIMED,
        GoalBootstrapStage.AUTHORITY_PUBLISHED,
        GoalBootstrapStage.PLANNING_INPUT_PUBLISHED,
    ):
        raise GoalBootstrapStoreError(
            "pre-planner failure may not cross PLANNER_STARTED"
        )
    normalized = reason.strip() if isinstance(reason, str) else ""
    if not normalized:
        raise GoalBootstrapStoreError(
            "pre-planner failure reason must be non-empty"
        )
    normalized = normalized[:4096]
    return _terminalize(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=expected_stage,
        target_status=GoalBootstrapStatus.FAILED_PRE_PLANNER,
        reason=normalized,
    )


def interrupt_goal_bootstrap(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    expected_stage: GoalBootstrapStage,
    reason: str,
) -> GoalBootstrapReceipt:
    if not isinstance(expected_stage, GoalBootstrapStage):
        raise GoalBootstrapStoreError("expected_stage must be a GoalBootstrapStage")
    normalized = reason.strip() if isinstance(reason, str) else ""
    if not normalized:
        raise GoalBootstrapStoreError("interruption reason must be non-empty")
    normalized = normalized[:4096]
    return _terminalize(
        runtime,
        bootstrap_id,
        expected_revision,
        expected_stage=expected_stage,
        target_status=GoalBootstrapStatus.INTERRUPTED,
        reason=normalized,
    )


def _terminalize(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
    expected_revision: int,
    *,
    expected_stage: GoalBootstrapStage,
    target_status: GoalBootstrapStatus,
    reason: str,
) -> GoalBootstrapReceipt:
    project_id = runtime.project_id()
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, bootstrap_id)
        if receipt.project_id != project_id:
            raise GoalBootstrapStoreError("GOALBOOT receipt belongs to another project")
        _require_active_checkpoint(
            receipt,
            expected_stage=expected_stage,
            expected_revision=expected_revision,
        )
        candidate = replace(
            receipt,
            status=target_status,
            revision=receipt.revision + 1,
            updated_at=now,
            terminal_reason=reason,
        )
        cursor = conn.execute(
            """UPDATE goal_bootstraps
               SET status = ?, revision = ?, updated_at = ?, terminal_reason = ?
               WHERE bootstrap_id = ? AND status = 'ACTIVE'
                 AND stage = ? AND revision = ?""",
            (
                target_status.value,
                candidate.revision,
                now,
                reason,
                receipt.bootstrap_id,
                expected_stage.value,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("GOALBOOT changed during terminalization")
        return _load_receipt_connection(conn, bootstrap_id)
