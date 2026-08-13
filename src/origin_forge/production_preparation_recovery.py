from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .ids import IdKind, validate_id
from .production_capability_routing import CapabilityRoutingError, TaskRouteInput
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    ProductionPreparationModelError,
    TaskPreparationReceipt,
)
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_status import (
    PreparationInspectionState,
    PreparationStatusReadError,
    inspect_preparation_receipt_status_readonly,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime
from .state import TaskStatus
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


_MAX_EVENT_JSON_BYTES = 64 * 1024
_ACQUISITION_METADATA_KEYS = {
    "preparation_policy_id",
    "task_id",
    "queued_task_revision",
    "queued_task_hash",
}
_ACTIVATION_METADATA_KEYS = {
    "reason",
    "dependency_count",
    "satisfied_dependency_count",
    "previous_task_content_hash",
    "new_task_content_hash",
}


class PreparationRecoveryReadError(RuntimeError):
    pass


class PreparationRecoveryState(StrEnum):
    RESUMABLE_CLAIMED = "RESUMABLE_CLAIMED"
    ADOPTABLE_ACTIVATION_CHECKPOINT = "ADOPTABLE_ACTIVATION_CHECKPOINT"
    RESUMABLE_ACTIVATED = "RESUMABLE_ACTIVATED"
    RESUMABLE_ROUTED = "RESUMABLE_ROUTED"
    PLANNER_EVIDENCE_ONLY = "PLANNER_EVIDENCE_ONLY"
    POST_PLANNER_NOT_REQUIRED = "POST_PLANNER_NOT_REQUIRED"
    READY_NOT_REQUIRED = "READY_NOT_REQUIRED"
    TERMINAL_NOT_REQUIRED = "TERMINAL_NOT_REQUIRED"
    STALE_OR_INVALID = "STALE_OR_INVALID"
    AMBIGUOUS_EVIDENCE = "AMBIGUOUS_EVIDENCE"


@dataclass(frozen=True)
class PreparationRecoveryProjection:
    state: PreparationRecoveryState
    preparation_id: str
    preparation_policy_id: str
    preparation_policy_hash: str
    task_id: str
    receipt_status: PreparationStatus
    stage: PreparationStage
    receipt_revision: int
    task_status: TaskStatus
    task_revision: int
    task_content_hash: str
    acquisition_event_id: str | None = None
    activation_event_id: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "preparation_id": self.preparation_id,
            "preparation_policy_id": self.preparation_policy_id,
            "preparation_policy_hash": self.preparation_policy_hash,
            "task_id": self.task_id,
            "receipt_status": self.receipt_status.value,
            "stage": self.stage.value,
            "receipt_revision": self.receipt_revision,
            "task_status": self.task_status.value,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "acquisition_event_id": self.acquisition_event_id,
            "activation_event_id": self.activation_event_id,
            "detail": self.detail,
            "authority": "immutable-preparation-recovery-classification",
        }


@dataclass(frozen=True)
class _RecoverySnapshot:
    receipt: TaskPreparationReceipt
    task_status: TaskStatus
    task_input: TaskRouteInput
    acquisition_event_id: str | None
    activation_event_id: str | None
    activation_evidence_status: PreparationRecoveryState | None
    activation_evidence_detail: str | None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreparationRecoveryReadError(
                f"state-event metadata contains duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _parse_canonical_object(raw: object, label: str) -> dict[str, Any]:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw.encode("utf-8")) > _MAX_EVENT_JSON_BYTES
    ):
        raise PreparationRecoveryReadError(f"{label} metadata is outside byte bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except PreparationRecoveryReadError:
        raise
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise PreparationRecoveryReadError(f"{label} metadata is not strict JSON") from exc
    if not isinstance(value, dict):
        raise PreparationRecoveryReadError(f"{label} metadata must be an object")
    expected = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if expected != raw:
        raise PreparationRecoveryReadError(f"{label} metadata is not canonical JSON")
    return value


def _receipt_from_row(row) -> TaskPreparationReceipt:
    try:
        return TaskPreparationReceipt(
            preparation_id=row["preparation_id"],
            project_id=row["project_id"],
            preparation_policy_id=row["preparation_policy_id"],
            preparation_policy_hash=row["preparation_policy_hash"],
            materialization_id=row["materialization_id"],
            materialization_hash=row["materialization_hash"],
            planning_input_id=row["planning_input_id"],
            planning_input_hash=row["planning_input_hash"],
            task_id=row["task_id"],
            queued_task_revision=int(row["queued_task_revision"]),
            queued_task_hash=row["queued_task_hash"],
            ready_task_revision=(
                None
                if row["ready_task_revision"] is None
                else int(row["ready_task_revision"])
            ),
            ready_task_hash=row["ready_task_hash"],
            route_decision_id=row["route_decision_id"],
            route_decision_hash=row["route_decision_hash"],
            planner_dependency_plan_hash=row["planner_dependency_plan_hash"],
            planner_run_id=row["planner_run_id"],
            work_order_id=row["work_order_id"],
            work_order_hash=row["work_order_hash"],
            work_order_audit_id=row["work_order_audit_id"],
            work_order_audit_hash=row["work_order_audit_hash"],
            input_resolution_id=row["input_resolution_id"],
            input_resolution_hash=row["input_resolution_hash"],
            dispatch_binding_id=row["dispatch_binding_id"],
            dispatch_binding_hash=row["dispatch_binding_hash"],
            binding_audit_id=row["binding_audit_id"],
            binding_audit_hash=row["binding_audit_hash"],
            stage=PreparationStage(row["stage"]),
            status=PreparationStatus(row["status"]),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_reason=row["terminal_reason"],
        )
    except (KeyError, TypeError, ValueError, ProductionPreparationModelError) as exc:
        raise PreparationRecoveryReadError("stored PREP receipt is invalid") from exc


def _acquisition_event(conn, receipt: TaskPreparationReceipt):
    rows = conn.execute(
        """SELECT rowid AS event_rowid, *
           FROM state_events
           WHERE aggregate_type = 'TASK_PREPARATION'
             AND aggregate_id = ?
             AND event_type = 'TASK_PREPARATION_ACQUIRED'
           ORDER BY rowid
           LIMIT 3""",
        (receipt.preparation_id,),
    ).fetchall()
    if len(rows) != 1:
        return None, (
            PreparationRecoveryState.AMBIGUOUS_EVIDENCE
            if len(rows) > 1
            else PreparationRecoveryState.STALE_OR_INVALID
        ), (
            "multiple PREP acquisition events exist"
            if len(rows) > 1
            else "exact PREP acquisition event is missing"
        )
    row = rows[0]
    try:
        metadata = _parse_canonical_object(row["metadata_json"], "PREP acquisition")
    except PreparationRecoveryReadError as exc:
        return row, PreparationRecoveryState.STALE_OR_INVALID, str(exc)
    expected = {
        "preparation_policy_id": receipt.preparation_policy_id,
        "task_id": receipt.task_id,
        "queued_task_revision": receipt.queued_task_revision,
        "queued_task_hash": receipt.queued_task_hash,
    }
    if (
        set(metadata) != _ACQUISITION_METADATA_KEYS
        or metadata != expected
        or row["old_state"] is not None
        or row["new_state"] != PreparationStatus.ACTIVE.value
        or row["revision"] != 0
        or row["actor_type"] != "SYSTEM"
        or row["actor_id"] is not None
        or row["created_at"] != receipt.created_at
        or receipt.revision < 0
    ):
        return row, PreparationRecoveryState.STALE_OR_INVALID, (
            "PREP acquisition event does not exactly bind durable receipt authority"
        )
    return row, None, None


def _activation_event_evidence(
    conn,
    receipt: TaskPreparationReceipt,
    task_status: TaskStatus,
    task_input: TaskRouteInput,
    readiness,
    acquisition_row,
):
    if acquisition_row is None:
        return None, PreparationRecoveryState.STALE_OR_INVALID, (
            "activation recovery requires exact PREP acquisition evidence"
        )
    rows = conn.execute(
        """SELECT rowid AS event_rowid, *
           FROM state_events
           WHERE aggregate_type = 'TASK'
             AND aggregate_id = ?
             AND event_type = 'TASK_STATUS_CHANGED'
             AND revision = ?
             AND rowid > ?
           ORDER BY rowid
           LIMIT 3""",
        (
            receipt.task_id,
            receipt.queued_task_revision + 1,
            acquisition_row["event_rowid"],
        ),
    ).fetchall()
    if len(rows) != 1:
        return None, (
            PreparationRecoveryState.AMBIGUOUS_EVIDENCE
            if len(rows) > 1
            else PreparationRecoveryState.STALE_OR_INVALID
        ), (
            "multiple post-acquisition Task revision events exist"
            if len(rows) > 1
            else "no exact post-acquisition Task revision event exists"
        )
    row = rows[0]
    try:
        metadata = _parse_canonical_object(row["metadata_json"], "Phase-35 activation")
    except PreparationRecoveryReadError as exc:
        return row, PreparationRecoveryState.STALE_OR_INVALID, str(exc)
    counts_valid = (
        type(metadata.get("dependency_count")) is int
        and metadata["dependency_count"] >= 0
        and type(metadata.get("satisfied_dependency_count")) is int
        and metadata["satisfied_dependency_count"] >= 0
        and metadata["satisfied_dependency_count"] == metadata["dependency_count"]
        and readiness.task_status is TaskStatus.READY
        and readiness.status is DependencyReadinessStatus.READY
        and metadata["dependency_count"] == readiness.dependency_count
        and metadata["satisfied_dependency_count"] == readiness.satisfied_dependency_count
    )
    if (
        set(metadata) != _ACTIVATION_METADATA_KEYS
        or metadata.get("reason") != "DEPENDENCY_READY_ACTIVATION"
        or not counts_valid
        or metadata.get("previous_task_content_hash") != receipt.queued_task_hash
        or metadata.get("new_task_content_hash") != task_input.task_content_hash
        or row["old_state"] != TaskStatus.QUEUED.value
        or row["new_state"] != TaskStatus.READY.value
        or row["revision"] != receipt.queued_task_revision + 1
        or row["actor_type"] != "SYSTEM"
        or row["actor_id"] is not None
        or receipt.revision != 0
        or task_status is not TaskStatus.READY
        or task_input.task_revision != receipt.queued_task_revision + 1
    ):
        return row, PreparationRecoveryState.STALE_OR_INVALID, (
            "Task READY state does not reconstruct exact Phase-35 activation evidence"
        )
    return row, PreparationRecoveryState.ADOPTABLE_ACTIVATION_CHECKPOINT, None


def _load_recovery_snapshot(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> _RecoverySnapshot:
    if not isinstance(preparation_id, str) or not validate_id(
        preparation_id, IdKind.TASK_PREPARATION
    ):
        raise ValueError("preparation_id must be a valid PREP ID")
    with production_read_connection(runtime) as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE root_path = ?",
            (str(runtime.project_root),),
        ).fetchone()
        if project is None:
            raise PreparationRecoveryReadError("current project is unavailable")
        row = conn.execute(
            "SELECT * FROM task_preparations WHERE preparation_id = ?",
            (preparation_id,),
        ).fetchone()
        if row is None:
            raise PreparationRecoveryReadError("PREP receipt does not exist")
        receipt = _receipt_from_row(row)
        if receipt.project_id != project["id"]:
            raise PreparationRecoveryReadError(
                "PREP receipt belongs to another project"
            )
        task = conn.execute(
            """SELECT t.*, g.project_id
               FROM tasks t
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               WHERE t.id = ?""",
            (receipt.task_id,),
        ).fetchone()
        if task is None or task["project_id"] != project["id"]:
            raise PreparationRecoveryReadError(
                "PREP Task is unavailable in current project"
            )
        try:
            task_status = TaskStatus(task["status"])
            task_input = TaskRouteInput.from_row(task)
        except (CapabilityRoutingError, TypeError, ValueError) as exc:
            raise PreparationRecoveryReadError(
                "PREP Task canonical routing state is invalid"
            ) from exc

        acquisition_row, acquisition_state, acquisition_detail = _acquisition_event(
            conn, receipt
        )
        activation_row = None
        activation_state = acquisition_state
        activation_detail = acquisition_detail
        if (
            receipt.status is PreparationStatus.ACTIVE
            and receipt.stage is PreparationStage.CLAIMED
            and task_status is TaskStatus.READY
            and acquisition_state is None
        ):
            try:
                readiness = resolve_task_dependency_readiness_connection(
                    conn, receipt.task_id
                )
            except (KeyError, TaskReadinessError, TypeError, ValueError) as exc:
                activation_state = PreparationRecoveryState.STALE_OR_INVALID
                activation_detail = (
                    "dependency readiness is invalid: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                activation_row, activation_state, activation_detail = (
                    _activation_event_evidence(
                        conn,
                        receipt,
                        task_status,
                        task_input,
                        readiness,
                        acquisition_row,
                    )
                )

        if (
            receipt.status is PreparationStatus.ACTIVE
            and receipt.stage is PreparationStage.CLAIMED
            and task_status is TaskStatus.QUEUED
        ):
            if acquisition_state is None:
                try:
                    readiness = resolve_task_dependency_readiness_connection(
                        conn, receipt.task_id
                    )
                except (KeyError, TaskReadinessError, TypeError, ValueError) as exc:
                    activation_state = PreparationRecoveryState.STALE_OR_INVALID
                    activation_detail = (
                        "dependency readiness is invalid: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    if (
                        receipt.revision == 0
                        and task_input.task_revision == receipt.queued_task_revision
                        and task_input.task_content_hash == receipt.queued_task_hash
                        and readiness.task_status is TaskStatus.QUEUED
                        and readiness.status is DependencyReadinessStatus.READY
                    ):
                        activation_state = PreparationRecoveryState.RESUMABLE_CLAIMED
                        activation_detail = None
                    else:
                        activation_state = PreparationRecoveryState.STALE_OR_INVALID
                        activation_detail = (
                            "CLAIMED PREP no longer binds exact dependency-ready QUEUED Task"
                        )

        return _RecoverySnapshot(
            receipt=receipt,
            task_status=task_status,
            task_input=task_input,
            acquisition_event_id=(
                None if acquisition_row is None else acquisition_row["id"]
            ),
            activation_event_id=(
                None if activation_row is None else activation_row["id"]
            ),
            activation_evidence_status=activation_state,
            activation_evidence_detail=activation_detail,
        )


def _projection(
    snapshot: _RecoverySnapshot,
    state: PreparationRecoveryState,
    detail: str | None,
) -> PreparationRecoveryProjection:
    return PreparationRecoveryProjection(
        state=state,
        preparation_id=snapshot.receipt.preparation_id,
        preparation_policy_id=snapshot.receipt.preparation_policy_id,
        preparation_policy_hash=snapshot.receipt.preparation_policy_hash,
        task_id=snapshot.receipt.task_id,
        receipt_status=snapshot.receipt.status,
        stage=snapshot.receipt.stage,
        receipt_revision=snapshot.receipt.revision,
        task_status=snapshot.task_status,
        task_revision=snapshot.task_input.task_revision,
        task_content_hash=snapshot.task_input.task_content_hash,
        acquisition_event_id=snapshot.acquisition_event_id,
        activation_event_id=snapshot.activation_event_id,
        detail=detail,
    )


def _require_policy_relation(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
) -> None:
    policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
    if (
        policy.content_hash != receipt.preparation_policy_hash
        or policy.project_id != receipt.project_id
        or policy.materialization_id != receipt.materialization_id
        or policy.materialization_hash != receipt.materialization_hash
        or policy.planning_input_id != receipt.planning_input_id
        or policy.planning_input_hash != receipt.planning_input_hash
    ):
        raise PreparationRecoveryReadError(
            "PREP receipt no longer matches exact current PREPPOL authority"
        )


def inspect_preparation_recovery_readonly(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> PreparationRecoveryProjection:
    """Classify one existing PREP recovery state without creating or repairing authority."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    snapshot = _load_recovery_snapshot(runtime, preparation_id)
    receipt = snapshot.receipt

    if receipt.status in (
        PreparationStatus.INTERRUPTED,
        PreparationStatus.FAILED_PRE_PLANNER,
    ):
        return _projection(
            snapshot,
            PreparationRecoveryState.TERMINAL_NOT_REQUIRED,
            None,
        )

    try:
        _require_policy_relation(runtime, receipt)
    except (
        PreparationRecoveryReadError,
        ProductionPreparationPolicyStoreError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _projection(
            snapshot,
            PreparationRecoveryState.STALE_OR_INVALID,
            f"{type(exc).__name__}: {exc}",
        )

    if receipt.status is PreparationStatus.ACTIVE and receipt.stage is PreparationStage.CLAIMED:
        state = snapshot.activation_evidence_status
        if state is None:
            state = PreparationRecoveryState.STALE_OR_INVALID
        return _projection(snapshot, state, snapshot.activation_evidence_detail)

    try:
        current = inspect_preparation_receipt_status_readonly(
            runtime, preparation_id
        )
    except (
        PreparationStatusReadError,
        ProductionReadGuardError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _projection(
            snapshot,
            PreparationRecoveryState.STALE_OR_INVALID,
            f"{type(exc).__name__}: {exc}",
        )

    if receipt.status is PreparationStatus.READY:
        if (
            receipt.stage is PreparationStage.BOUND
            and current.state is PreparationInspectionState.READY_FOR_PHASE38
            and current.current
        ):
            return _projection(
                snapshot,
                PreparationRecoveryState.READY_NOT_REQUIRED,
                None,
            )
        return _projection(
            snapshot,
            PreparationRecoveryState.STALE_OR_INVALID,
            current.detail or "READY PREP is not exact current Phase-34 authority",
        )

    if receipt.status is not PreparationStatus.ACTIVE or not current.current:
        return _projection(
            snapshot,
            PreparationRecoveryState.STALE_OR_INVALID,
            current.detail or "PREP is not exact current recovery authority",
        )

    if receipt.stage is PreparationStage.ACTIVATED:
        return _projection(
            snapshot,
            PreparationRecoveryState.RESUMABLE_ACTIVATED,
            None,
        )
    if receipt.stage is PreparationStage.ROUTED:
        return _projection(
            snapshot,
            PreparationRecoveryState.RESUMABLE_ROUTED,
            None,
        )
    if receipt.stage is PreparationStage.PLANNER_STARTED:
        return _projection(
            snapshot,
            PreparationRecoveryState.PLANNER_EVIDENCE_ONLY,
            None,
        )
    if receipt.stage in (
        PreparationStage.PLANNER_RETURNED,
        PreparationStage.WORK_ORDER_AUDITED,
    ):
        return _projection(
            snapshot,
            PreparationRecoveryState.POST_PLANNER_NOT_REQUIRED,
            None,
        )

    return _projection(
        snapshot,
        PreparationRecoveryState.STALE_OR_INVALID,
        "PREP stage is outside Phase-41 recovery classification",
    )
