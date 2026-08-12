from __future__ import annotations

import sqlite3

from .ids import IdKind, new_id, validate_id
from .production_capability_routing import TaskRouteInput
from .production_capability_store import ProductionCapabilityStore, ProductionCapabilityStoreError
from .production_planning_inspection import (
    ProductionPlanningInspectionError,
    _load_materialization_connection,
)
from .production_preparation_admission import PreparationCandidate
from .production_preparation_assembly import PreparationPlannerDependencyPlan
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    ProductionPreparationModelError,
    TaskPreparationPolicyBinding,
    TaskPreparationReceipt,
)
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_provenance import (
    ProductionPreparationProvenanceError,
    resolve_preparation_policy_provenance,
)
from .production_task_activation import TaskActivationResult
from .production_work_order_planner import WorkOrderPlannerResult
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now
from .state import TaskStatus
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


class PreparationReceiptError(RuntimeError):
    pass


def _receipt_from_row(row: sqlite3.Row) -> TaskPreparationReceipt:
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
        raise PreparationReceiptError("stored PREP receipt is invalid") from exc


def _load_receipt_connection(
    conn: sqlite3.Connection,
    preparation_id: str,
) -> TaskPreparationReceipt:
    if not isinstance(preparation_id, str) or not validate_id(
        preparation_id, IdKind.TASK_PREPARATION
    ):
        raise PreparationReceiptError("preparation_id must be a valid PREP ID")
    row = conn.execute(
        "SELECT * FROM task_preparations WHERE preparation_id = ?",
        (preparation_id,),
    ).fetchone()
    if row is None:
        raise PreparationReceiptError("PREP receipt does not exist")
    return _receipt_from_row(row)


def read_preparation_receipt(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> TaskPreparationReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        receipt = _load_receipt_connection(conn, preparation_id)
    if receipt.project_id != project_id:
        raise PreparationReceiptError("PREP receipt belongs to another project")
    return receipt


def _require_active_checkpoint(
    receipt: TaskPreparationReceipt,
    *,
    expected_stage: PreparationStage,
    expected_revision: int,
) -> None:
    if type(expected_revision) is not int or expected_revision < 0:
        raise PreparationReceiptError(
            "expected_revision must be a non-negative integer"
        )
    if receipt.status is not PreparationStatus.ACTIVE:
        raise PreparationReceiptError("PREP receipt is not ACTIVE")
    if receipt.stage is not expected_stage:
        raise PreparationReceiptError(
            f"PREP receipt stage is {receipt.stage.value}, not {expected_stage.value}"
        )
    if receipt.revision != expected_revision:
        raise StaleRevision(
            f"preparation {receipt.preparation_id} revision {receipt.revision} != expected {expected_revision}"
        )


def _read_receipt_policy(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
) -> TaskPreparationPolicyBinding:
    try:
        policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
    except ProductionPreparationPolicyStoreError as exc:
        raise PreparationReceiptError(
            "PREP policy is unavailable or no longer current"
        ) from exc
    if policy.content_hash != receipt.preparation_policy_hash:
        raise PreparationReceiptError("PREP policy hash drifted from durable receipt")
    return policy


def acquire_preparation_receipt(
    runtime: OriginForgeRuntime,
    policy: TaskPreparationPolicyBinding,
    candidate: PreparationCandidate,
) -> TaskPreparationReceipt:
    """Acquire durable exclusive PREP ownership for one exact queued candidate.

    Admission is evidence only. This transaction independently revalidates the
    persisted PREPPOL plus selected PLMAT/Task/dependency relation under
    BEGIN IMMEDIATE before creating the ACTIVE receipt. It never activates,
    routes, plans, or dispatches work.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(policy, TaskPreparationPolicyBinding):
        raise TypeError("policy must be a TaskPreparationPolicyBinding")
    if not isinstance(candidate, PreparationCandidate):
        raise TypeError("candidate must be a PreparationCandidate")
    try:
        persisted = read_preparation_policy(runtime, policy.preparation_policy_id)
        if persisted != policy or persisted.content_hash != policy.content_hash:
            raise PreparationReceiptError(
                "caller PREPPOL differs from protected persisted authority"
            )
        provenance = resolve_preparation_policy_provenance(runtime, persisted)
    except (
        ProductionPreparationPolicyStoreError,
        ProductionPreparationProvenanceError,
    ) as exc:
        raise PreparationReceiptError("PREPPOL authority is not current") from exc

    project_id = runtime.project_id()
    preparation_id = new_id(IdKind.TASK_PREPARATION)
    now = utc_now()
    try:
        with runtime.store.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            materialization = _load_materialization_connection(
                conn,
                project_id,
                persisted.materialization_id,
            )
            if (
                materialization.content_hash != persisted.materialization_hash
                or materialization.planning_input_id != persisted.planning_input_id
                or materialization.planning_input_hash != persisted.planning_input_hash
            ):
                raise PreparationReceiptError(
                    "PREPPOL materialization relation changed before acquisition"
                )
            bindings = tuple(
                binding
                for binding in materialization.task_bindings
                if binding.task_id == candidate.task_id
            )
            if len(bindings) != 1 or bindings[0].step_key != candidate.step_key:
                raise PreparationReceiptError(
                    "selected candidate is not exactly bound by PREPPOL materialization"
                )

            row = conn.execute(
                """SELECT t.*, g.project_id
                   FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE t.id = ?""",
                (candidate.task_id,),
            ).fetchone()
            if row is None or row["project_id"] != project_id:
                raise PreparationReceiptError(
                    "selected Task is not in current project"
                )
            if row["flow_id"] != materialization.flow_id:
                raise PreparationReceiptError("selected Task left materialized Flow")
            try:
                status = TaskStatus(row["status"])
                route_input = TaskRouteInput.from_row(row)
                readiness = resolve_task_dependency_readiness_connection(
                    conn,
                    candidate.task_id,
                )
            except (TaskReadinessError, TypeError, ValueError) as exc:
                raise PreparationReceiptError(
                    "selected Task canonical state is invalid"
                ) from exc
            if status is not TaskStatus.QUEUED:
                raise PreparationReceiptError("selected Task is no longer QUEUED")
            if (
                route_input.task_revision != candidate.task_revision
                or route_input.task_content_hash != candidate.task_content_hash
                or route_input.required_capabilities != candidate.required_capabilities
            ):
                raise StaleRevision("selected Task changed after immutable admission")
            if (
                readiness.task_status is not TaskStatus.QUEUED
                or readiness.status is not DependencyReadinessStatus.READY
            ):
                raise PreparationReceiptError(
                    "selected Task is no longer dependency-ready"
                )
            if not set(route_input.required_capabilities).issubset(
                set(provenance.capability_routing_policy.allowed_capability_ids)
            ):
                raise PreparationReceiptError(
                    "selected Task capabilities exceed PREPPOL authority"
                )
            existing = conn.execute(
                """SELECT preparation_id FROM task_preparations
                   WHERE task_id = ? AND status = 'ACTIVE'
                   LIMIT 1""",
                (candidate.task_id,),
            ).fetchone()
            if existing is not None:
                raise PreparationReceiptError(
                    f"Task already has ACTIVE preparation {existing['preparation_id']}"
                )

            receipt = TaskPreparationReceipt(
                preparation_id=preparation_id,
                project_id=project_id,
                preparation_policy_id=persisted.preparation_policy_id,
                preparation_policy_hash=persisted.content_hash,
                materialization_id=persisted.materialization_id,
                materialization_hash=persisted.materialization_hash,
                planning_input_id=persisted.planning_input_id,
                planning_input_hash=persisted.planning_input_hash,
                task_id=candidate.task_id,
                queued_task_revision=candidate.task_revision,
                queued_task_hash=candidate.task_content_hash,
                ready_task_revision=None,
                ready_task_hash=None,
                route_decision_id=None,
                route_decision_hash=None,
                planner_dependency_plan_hash=None,
                planner_run_id=None,
                work_order_id=None,
                work_order_hash=None,
                work_order_audit_id=None,
                work_order_audit_hash=None,
                input_resolution_id=None,
                input_resolution_hash=None,
                dispatch_binding_id=None,
                dispatch_binding_hash=None,
                binding_audit_id=None,
                binding_audit_hash=None,
                stage=PreparationStage.CLAIMED,
                status=PreparationStatus.ACTIVE,
                revision=0,
                created_at=now,
                updated_at=now,
                terminal_reason=None,
            )
            values = receipt.to_dict()
            conn.execute(
                """INSERT INTO task_preparations(
                    preparation_id, project_id,
                    preparation_policy_id, preparation_policy_hash,
                    materialization_id, materialization_hash,
                    planning_input_id, planning_input_hash,
                    task_id, queued_task_revision, queued_task_hash,
                    ready_task_revision, ready_task_hash,
                    route_decision_id, route_decision_hash,
                    planner_dependency_plan_hash, planner_run_id,
                    work_order_id, work_order_hash,
                    work_order_audit_id, work_order_audit_hash,
                    input_resolution_id, input_resolution_hash,
                    dispatch_binding_id, dispatch_binding_hash,
                    binding_audit_id, binding_audit_hash,
                    stage, status, revision, created_at, updated_at, terminal_reason
                ) VALUES (
                    :preparation_id, :project_id,
                    :preparation_policy_id, :preparation_policy_hash,
                    :materialization_id, :materialization_hash,
                    :planning_input_id, :planning_input_hash,
                    :task_id, :queued_task_revision, :queued_task_hash,
                    :ready_task_revision, :ready_task_hash,
                    :route_decision_id, :route_decision_hash,
                    :planner_dependency_plan_hash, :planner_run_id,
                    :work_order_id, :work_order_hash,
                    :work_order_audit_id, :work_order_audit_hash,
                    :input_resolution_id, :input_resolution_hash,
                    :dispatch_binding_id, :dispatch_binding_hash,
                    :binding_audit_id, :binding_audit_hash,
                    :stage, :status, :revision, :created_at, :updated_at, :terminal_reason
                )""",
                values,
            )
            runtime.store._append_event(
                conn,
                "TASK_PREPARATION",
                preparation_id,
                "TASK_PREPARATION_ACQUIRED",
                None,
                PreparationStatus.ACTIVE.value,
                0,
                "SYSTEM",
                None,
                {
                    "preparation_policy_id": persisted.preparation_policy_id,
                    "task_id": candidate.task_id,
                    "queued_task_revision": candidate.task_revision,
                    "queued_task_hash": candidate.task_content_hash,
                },
                now,
            )
    except sqlite3.IntegrityError as exc:
        raise PreparationReceiptError(
            "preparation acquisition lost the durable exclusivity race"
        ) from exc
    except ProductionPlanningInspectionError as exc:
        raise PreparationReceiptError(
            "materialization could not be revalidated during acquisition"
        ) from exc
    return receipt


def checkpoint_preparation_activated(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
    activation: TaskActivationResult,
) -> TaskPreparationReceipt:
    if not isinstance(activation, TaskActivationResult):
        raise TypeError("activation must be a TaskActivationResult")
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.CLAIMED,
            expected_revision=expected_revision,
        )
        if (
            activation.task_id != receipt.task_id
            or activation.previous_revision != receipt.queued_task_revision
            or activation.previous_task_content_hash != receipt.queued_task_hash
            or activation.new_revision != receipt.queued_task_revision + 1
        ):
            raise PreparationReceiptError(
                "activation result does not exactly continue PREP queued authority"
            )
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (receipt.task_id,),
        ).fetchone()
        if row is None:
            raise PreparationReceiptError("activated Task disappeared")
        try:
            status = TaskStatus(row["status"])
            current = TaskRouteInput.from_row(row)
        except (TypeError, ValueError) as exc:
            raise PreparationReceiptError(
                "activated Task canonical state is invalid"
            ) from exc
        if (
            status is not TaskStatus.READY
            or current.task_revision != activation.new_revision
            or current.task_content_hash != activation.new_task_content_hash
        ):
            raise PreparationReceiptError(
                "canonical READY Task does not match Phase-35 activation result"
            )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET ready_task_revision = ?, ready_task_hash = ?,
                   stage = 'ACTIVATED', revision = ?, updated_at = ?
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = 'CLAIMED' AND revision = ?""",
            (
                activation.new_revision,
                activation.new_task_content_hash,
                new_revision,
                now,
                receipt.preparation_id,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("PREP changed during activation checkpoint")
        return _load_receipt_connection(conn, preparation_id)


def checkpoint_preparation_routed(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
    route_decision_id: str,
) -> TaskPreparationReceipt:
    snapshot = read_preparation_receipt(runtime, preparation_id)
    _require_active_checkpoint(
        snapshot,
        expected_stage=PreparationStage.ACTIVATED,
        expected_revision=expected_revision,
    )
    policy = _read_receipt_policy(runtime, snapshot)
    capability_store = ProductionCapabilityStore(runtime)
    try:
        route = capability_store.require_current_route(route_decision_id)
    except ProductionCapabilityStoreError as exc:
        raise PreparationReceiptError("Phase-32 route is unavailable or stale") from exc
    resolution = route.resolution
    if (
        resolution.catalog_id != policy.capability_catalog_id
        or resolution.catalog_hash != policy.capability_catalog_hash
        or resolution.routing_policy_id != policy.capability_routing_policy_id
        or resolution.routing_policy_hash != policy.capability_routing_policy_hash
    ):
        raise PreparationReceiptError(
            "Phase-32 route does not use exact PREPPOL CAPCAT/CAPPOL authority"
        )

    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.ACTIVATED,
            expected_revision=expected_revision,
        )
        route_input = resolution.route_input
        if (
            route_input.task_id != receipt.task_id
            or route_input.task_revision != receipt.ready_task_revision
            or route_input.task_content_hash != receipt.ready_task_hash
        ):
            raise PreparationReceiptError(
                "Phase-32 route does not exactly bind PREP READY Task checkpoint"
            )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET route_decision_id = ?, route_decision_hash = ?,
                   stage = 'ROUTED', revision = ?, updated_at = ?
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = 'ACTIVATED' AND revision = ?""",
            (
                route.route_decision_id,
                route.content_hash,
                new_revision,
                now,
                receipt.preparation_id,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("PREP changed during route checkpoint")
        return _load_receipt_connection(conn, preparation_id)


def checkpoint_preparation_planner_started(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
    plan: PreparationPlannerDependencyPlan,
) -> TaskPreparationReceipt:
    if not isinstance(plan, PreparationPlannerDependencyPlan):
        raise TypeError("plan must be a PreparationPlannerDependencyPlan")
    snapshot = read_preparation_receipt(runtime, preparation_id)
    _require_active_checkpoint(
        snapshot,
        expected_stage=PreparationStage.ROUTED,
        expected_revision=expected_revision,
    )
    policy = _read_receipt_policy(runtime, snapshot)
    if (
        plan.preparation_policy_id != policy.preparation_policy_id
        or plan.preparation_policy_hash != policy.content_hash
    ):
        raise PreparationReceiptError(
            "planner dependency plan does not bind exact durable PREPPOL authority"
        )

    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.ROUTED,
            expected_revision=expected_revision,
        )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET planner_dependency_plan_hash = ?,
                   stage = 'PLANNER_STARTED', revision = ?, updated_at = ?
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = 'ROUTED' AND revision = ?""",
            (
                plan.plan_hash,
                new_revision,
                now,
                receipt.preparation_id,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("PREP changed during planner-start checkpoint")
        return _load_receipt_connection(conn, preparation_id)


def checkpoint_preparation_planner_returned(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
    result: WorkOrderPlannerResult,
) -> TaskPreparationReceipt:
    if not isinstance(result, WorkOrderPlannerResult):
        raise TypeError("result must be a WorkOrderPlannerResult")
    snapshot = read_preparation_receipt(runtime, preparation_id)
    _require_active_checkpoint(
        snapshot,
        expected_stage=PreparationStage.PLANNER_STARTED,
        expected_revision=expected_revision,
    )
    policy = _read_receipt_policy(runtime, snapshot)
    try:
        provenance = resolve_preparation_policy_provenance(runtime, policy)
        route = ProductionCapabilityStore(runtime).require_current_route(
            snapshot.route_decision_id
        )
    except (
        ProductionPreparationProvenanceError,
        ProductionCapabilityStoreError,
    ) as exc:
        raise PreparationReceiptError(
            "planner return authority cannot be revalidated"
        ) from exc
    if route.content_hash != snapshot.route_decision_hash:
        raise PreparationReceiptError("PREP route hash drifted before planner return")
    resolution = route.resolution
    work_order = result.work_order
    try:
        contract = provenance.dispatch_contract_catalog.contract_for_adapter(
            resolution.selected_adapter_id
        )
    except KeyError as exc:
        raise PreparationReceiptError(
            "PREPPOL DISPCAT has no contract for returned route"
        ) from exc
    if (
        work_order.dispatch_catalog_id != policy.dispatch_contract_catalog_id
        or work_order.dispatch_catalog_hash != policy.dispatch_contract_catalog_hash
        or work_order.dispatch_contract_id != contract.contract_id
        or work_order.dispatch_contract_hash != contract.content_hash
        or work_order.selected_adapter_id != resolution.selected_adapter_id
        or work_order.selected_adapter_fingerprint
        != resolution.selected_adapter_fingerprint
        or work_order.input_refs
    ):
        raise PreparationReceiptError(
            "planner WorkOrder exceeds exact PREPPOL route/dispatch authority"
        )

    run = runtime.get_run(result.run_id)
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.PLANNER_STARTED,
            expected_revision=expected_revision,
        )
        if (
            result.route_decision_id != receipt.route_decision_id
            or result.route_decision_hash != receipt.route_decision_hash
            or run["id"] != result.run_id
            or run["task_id"] is not None
            or run["role"] != "WORK_ORDER_PLANNER"
            or run["status"] != "SUCCEEDED"
            or work_order.task_id != receipt.task_id
            or work_order.task_revision != receipt.ready_task_revision
            or work_order.task_content_hash != receipt.ready_task_hash
            or work_order.route_decision_id != receipt.route_decision_id
            or work_order.route_decision_hash != receipt.route_decision_hash
        ):
            raise PreparationReceiptError(
                "planner return does not exactly bind PREP route/Task authority"
            )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET planner_run_id = ?, work_order_id = ?, work_order_hash = ?,
                   stage = 'PLANNER_RETURNED', revision = ?, updated_at = ?
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = 'PLANNER_STARTED' AND revision = ?""",
            (
                result.run_id,
                work_order.work_order_id,
                work_order.content_hash,
                new_revision,
                now,
                receipt.preparation_id,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("PREP changed during planner-return checkpoint")
        return _load_receipt_connection(conn, preparation_id)


def fail_preparation_before_planner(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
    expected_stage: PreparationStage,
    reason: str,
) -> TaskPreparationReceipt:
    if expected_stage not in (
        PreparationStage.CLAIMED,
        PreparationStage.ACTIVATED,
        PreparationStage.ROUTED,
    ):
        raise PreparationReceiptError(
            "pre-planner failure may only terminalize CLAIMED/ACTIVATED/ROUTED"
        )
    normalized = reason.strip() if isinstance(reason, str) else ""
    if not normalized:
        raise PreparationReceiptError(
            "pre-planner failure reason must be non-empty"
        )
    normalized = normalized[:4096]
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=expected_stage,
            expected_revision=expected_revision,
        )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET status = 'FAILED_PRE_PLANNER', terminal_reason = ?,
                   revision = ?, updated_at = ?
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = ? AND revision = ?""",
            (
                normalized,
                new_revision,
                now,
                receipt.preparation_id,
                expected_stage.value,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision(
                "PREP changed during pre-planner terminalization"
            )
        return _load_receipt_connection(conn, preparation_id)
