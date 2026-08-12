from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_capability_read import (
    ProductionCapabilityReadError,
    read_capability_route,
)
from .production_capability_routing import CapabilityRouteOutcome, TaskRouteInput
from .production_dispatch_binding import build_builtin_dispatch_binder_registry
from .production_dispatch_binding_models import DispatchBindingCurrentnessStatus
from .production_dispatch_read import (
    ProductionDispatchReadError,
    inspect_dispatch_binding_currentness_readonly,
    read_dispatch_binding,
    read_dispatch_binding_audit,
    read_input_resolution,
)
from .production_dispatch_resolvers import build_core_input_resolver_registry
from .production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    TaskPreparationReceipt,
)
from .production_preparation_planner_evidence import (
    PreparationPlannerEvidenceError,
    _EVIDENCE_KEYS,
    _METRIC_KEYS,
    _PLANNER_ROLE,
    _VERIFICATION_TYPE,
    _VERIFIER,
    _parse_canonical_object,
    _work_order_from_evidence,
)
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_receipts import PreparationReceiptError, _receipt_from_row
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .production_work_order_audit import WorkOrderCurrentnessStatus
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_read import (
    ProductionWorkOrderReadError,
    inspect_work_order_currentness_readonly,
    read_work_order,
    read_work_order_audit,
)
from .runtime import OriginForgeRuntime
from .state import TaskStatus


class PreparationInspectionState(StrEnum):
    ELIGIBLE_QUEUED = "ELIGIBLE_QUEUED"
    NO_ELIGIBLE_TASK = "NO_ELIGIBLE_TASK"
    ACTIVE_PRE_PLANNER = "ACTIVE_PRE_PLANNER"
    PLANNER_RECOVERY_REQUIRED = "PLANNER_RECOVERY_REQUIRED"
    POST_PLANNER_RESUMABLE = "POST_PLANNER_RESUMABLE"
    READY_FOR_PHASE38 = "READY_FOR_PHASE38"
    INTERRUPTED = "INTERRUPTED"
    FAILED_PRE_PLANNER = "FAILED_PRE_PLANNER"
    STALE_OR_INVALID = "STALE_OR_INVALID"


@dataclass(frozen=True)
class MaterializationPreparationStatusProjection:
    state: PreparationInspectionState
    preparation_policy_id: str
    preparation_policy_hash: str | None
    materialization_id: str | None
    admission_status: PreparationAdmissionStatus | None
    candidate_count: int
    selected_task_id: str | None
    not_queued_exclusion_count: int
    dependency_exclusion_count: int
    active_preparation_exclusion_count: int
    phase38_admissible_exclusion_count: int
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "preparation_policy_id": self.preparation_policy_id,
            "preparation_policy_hash": self.preparation_policy_hash,
            "materialization_id": self.materialization_id,
            "admission_status": (
                None if self.admission_status is None else self.admission_status.value
            ),
            "candidate_count": self.candidate_count,
            "selected_task_id": self.selected_task_id,
            "not_queued_exclusion_count": self.not_queued_exclusion_count,
            "dependency_exclusion_count": self.dependency_exclusion_count,
            "active_preparation_exclusion_count": self.active_preparation_exclusion_count,
            "phase38_admissible_exclusion_count": self.phase38_admissible_exclusion_count,
            "detail": self.detail,
            "authority": "read-only preparation status",
        }


@dataclass(frozen=True)
class PreparationReceiptStatusProjection:
    state: PreparationInspectionState
    preparation_id: str
    preparation_policy_id: str
    preparation_policy_hash: str
    task_id: str
    receipt_status: PreparationStatus
    stage: PreparationStage
    revision: int
    current: bool
    route_decision_id: str | None
    work_order_id: str | None
    work_order_audit_id: str | None
    input_resolution_id: str | None
    dispatch_binding_id: str | None
    binding_audit_id: str | None
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
            "revision": self.revision,
            "current": self.current,
            "route_decision_id": self.route_decision_id,
            "work_order_id": self.work_order_id,
            "work_order_audit_id": self.work_order_audit_id,
            "input_resolution_id": self.input_resolution_id,
            "dispatch_binding_id": self.dispatch_binding_id,
            "binding_audit_id": self.binding_audit_id,
            "detail": self.detail,
            "authority": "read-only preparation status",
        }


def _empty_policy_projection(
    preparation_policy_id: str,
    detail: str,
) -> MaterializationPreparationStatusProjection:
    return MaterializationPreparationStatusProjection(
        state=PreparationInspectionState.STALE_OR_INVALID,
        preparation_policy_id=preparation_policy_id,
        preparation_policy_hash=None,
        materialization_id=None,
        admission_status=None,
        candidate_count=0,
        selected_task_id=None,
        not_queued_exclusion_count=0,
        dependency_exclusion_count=0,
        active_preparation_exclusion_count=0,
        phase38_admissible_exclusion_count=0,
        detail=detail,
    )


def inspect_materialization_preparation_status_readonly(
    runtime: OriginForgeRuntime,
    preparation_policy_id: str,
) -> MaterializationPreparationStatusProjection:
    """Inspect one persisted PREPPOL and its deterministic eligibility without mutation."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(preparation_policy_id, str) or not validate_id(
        preparation_policy_id, IdKind.TASK_PREPARATION_POLICY
    ):
        raise ValueError("preparation_policy_id must be a valid PREPPOL ID")
    try:
        policy = read_preparation_policy(runtime, preparation_policy_id)
        admission = inspect_materialization_preparation_eligibility_readonly(
            runtime,
            policy,
        )
    except (
        ProductionPreparationPolicyStoreError,
        ProductionReadGuardError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _empty_policy_projection(
            preparation_policy_id,
            f"{type(exc).__name__}: {exc}",
        )

    if admission.status is not PreparationAdmissionStatus.COMPLETE:
        state = PreparationInspectionState.STALE_OR_INVALID
        selected_task_id = None
    elif admission.candidates:
        state = PreparationInspectionState.ELIGIBLE_QUEUED
        selected_task_id = admission.candidates[0].task_id
    else:
        state = PreparationInspectionState.NO_ELIGIBLE_TASK
        selected_task_id = None
    return MaterializationPreparationStatusProjection(
        state=state,
        preparation_policy_id=policy.preparation_policy_id,
        preparation_policy_hash=policy.content_hash,
        materialization_id=policy.materialization_id,
        admission_status=admission.status,
        candidate_count=admission.candidate_count,
        selected_task_id=selected_task_id,
        not_queued_exclusion_count=admission.not_queued_exclusion_count,
        dependency_exclusion_count=admission.dependency_exclusion_count,
        active_preparation_exclusion_count=admission.active_preparation_exclusion_count,
        phase38_admissible_exclusion_count=admission.phase38_admissible_exclusion_count,
        detail=admission.detail,
    )


def _load_receipt_and_task_snapshot(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> tuple[TaskPreparationReceipt, TaskStatus, TaskRouteInput]:
    if not isinstance(preparation_id, str) or not validate_id(
        preparation_id, IdKind.TASK_PREPARATION
    ):
        raise PreparationReceiptError("preparation_id must be a valid PREP ID")
    with production_read_connection(runtime) as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE root_path = ?",
            (str(runtime.project_root),),
        ).fetchone()
        if project is None:
            raise PreparationReceiptError("current project is unavailable")
        row = conn.execute(
            "SELECT * FROM task_preparations WHERE preparation_id = ?",
            (preparation_id,),
        ).fetchone()
        if row is None:
            raise PreparationReceiptError("PREP receipt does not exist")
        receipt = _receipt_from_row(row)
        if receipt.project_id != project["id"]:
            raise PreparationReceiptError("PREP receipt belongs to another project")
        task = conn.execute(
            """SELECT t.*, g.project_id
               FROM tasks t
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               WHERE t.id = ?""",
            (receipt.task_id,),
        ).fetchone()
        if task is None or task["project_id"] != project["id"]:
            raise PreparationReceiptError("PREP Task is unavailable in current project")
        return receipt, TaskStatus(task["status"]), TaskRouteInput.from_row(task)


def _require_receipt_policy_relation(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
):
    policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
    if (
        policy.content_hash != receipt.preparation_policy_hash
        or policy.project_id != receipt.project_id
        or policy.materialization_id != receipt.materialization_id
        or policy.materialization_hash != receipt.materialization_hash
        or policy.planning_input_id != receipt.planning_input_id
        or policy.planning_input_hash != receipt.planning_input_hash
    ):
        raise PreparationReceiptError(
            "PREP receipt no longer matches exact current PREPPOL authority"
        )
    return policy


def _require_task_checkpoint_current(
    receipt: TaskPreparationReceipt,
    task_status: TaskStatus,
    task_input: TaskRouteInput,
) -> None:
    if receipt.stage is PreparationStage.CLAIMED:
        if (
            task_status is not TaskStatus.QUEUED
            or task_input.task_revision != receipt.queued_task_revision
            or task_input.task_content_hash != receipt.queued_task_hash
        ):
            raise PreparationReceiptError(
                "CLAIMED PREP no longer binds the exact QUEUED Task revision"
            )
        return
    if (
        task_status is not TaskStatus.READY
        or receipt.ready_task_revision is None
        or receipt.ready_task_hash is None
        or task_input.task_revision != receipt.ready_task_revision
        or task_input.task_content_hash != receipt.ready_task_hash
    ):
        raise PreparationReceiptError(
            "post-activation PREP no longer binds the exact READY Task revision"
        )


def _require_route_checkpoint_current(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
    policy,
) -> None:
    if receipt.stage in (PreparationStage.CLAIMED, PreparationStage.ACTIVATED):
        return
    if receipt.route_decision_id is None or receipt.route_decision_hash is None:
        raise PreparationReceiptError("routed PREP lacks exact Phase-32 checkpoint")
    route = read_capability_route(runtime, receipt.route_decision_id)
    resolution = route.resolution
    if (
        route.content_hash != receipt.route_decision_hash
        or resolution.outcome is not CapabilityRouteOutcome.ROUTABLE
        or resolution.catalog_id != policy.capability_catalog_id
        or resolution.catalog_hash != policy.capability_catalog_hash
        or resolution.routing_policy_id != policy.capability_routing_policy_id
        or resolution.routing_policy_hash != policy.capability_routing_policy_hash
        or resolution.route_input.task_id != receipt.task_id
        or resolution.route_input.task_revision != receipt.ready_task_revision
        or resolution.route_input.task_content_hash != receipt.ready_task_hash
    ):
        raise PreparationReceiptError(
            "PREP route checkpoint is stale or outside exact PREPPOL authority"
        )


def _require_planner_return_checkpoint_current(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
    policy,
) -> None:
    if receipt.stage in (
        PreparationStage.CLAIMED,
        PreparationStage.ACTIVATED,
        PreparationStage.ROUTED,
        PreparationStage.PLANNER_STARTED,
    ):
        return
    if (
        receipt.planner_run_id is None
        or receipt.work_order_id is None
        or receipt.work_order_hash is None
    ):
        raise PreparationReceiptError(
            "post-planner PREP lacks trustworthy planner-return checkpoint"
        )
    try:
        with production_read_connection(runtime) as conn:
            run = conn.execute(
                "SELECT * FROM runs WHERE id = ?",
                (receipt.planner_run_id,),
            ).fetchone()
            verifications = conn.execute(
                """SELECT * FROM verifications
                   WHERE target_type = 'RUN' AND target_id = ?
                     AND run_id = ? AND verification_type = ?
                     AND verifier = ? AND status = 'PASS'
                   ORDER BY created_at, rowid
                   LIMIT 2""",
                (
                    receipt.planner_run_id,
                    receipt.planner_run_id,
                    _VERIFICATION_TYPE,
                    _VERIFIER,
                ),
            ).fetchall()
        if run is None or len(verifications) != 1:
            raise PreparationPlannerEvidenceError(
                "PREP planner Run does not resolve exactly one PASS verification"
            )
        verification = verifications[0]
        if (
            run["task_id"] is not None
            or run["role"] != _PLANNER_ROLE
            or run["status"] != "SUCCEEDED"
            or verification["target_type"] != "RUN"
            or verification["target_id"] != run["id"]
            or verification["run_id"] != run["id"]
            or verification["verification_type"] != _VERIFICATION_TYPE
            or verification["verifier"] != _VERIFIER
            or verification["status"] != "PASS"
        ):
            raise PreparationPlannerEvidenceError(
                "PREP planner Run/verification relation is not exact successful taskless authority"
            )
        evidence = _parse_canonical_object(
            verification["evidence_json"],
            "planner evidence",
        )
        metrics = _parse_canonical_object(
            verification["metrics_json"],
            "planner metrics",
        )
        if set(evidence) != _EVIDENCE_KEYS or set(metrics) != _METRIC_KEYS:
            raise PreparationPlannerEvidenceError(
                "planner verification schema drifted"
            )
        if (
            evidence["audited"] is not False
            or evidence["dispatched"] is not False
            or metrics["model_calls"] != 1
            or metrics["allowed_input_refs"] != 0
        ):
            raise PreparationPlannerEvidenceError(
                "planner verification crosses or misstates one-shot authority"
            )
        work_order = _work_order_from_evidence(evidence["work_order"])
    except (
        PreparationPlannerEvidenceError,
        ProductionReadGuardError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise PreparationReceiptError(
            "PREP planner-return evidence is unavailable or invalid"
        ) from exc

    if (
        run["id"] != receipt.planner_run_id
        or work_order.work_order_id != receipt.work_order_id
        or work_order.content_hash != receipt.work_order_hash
        or work_order.task_id != receipt.task_id
        or work_order.task_revision != receipt.ready_task_revision
        or work_order.task_content_hash != receipt.ready_task_hash
        or work_order.route_decision_id != receipt.route_decision_id
        or work_order.route_decision_hash != receipt.route_decision_hash
        or work_order.dispatch_catalog_id != policy.dispatch_contract_catalog_id
        or work_order.dispatch_catalog_hash != policy.dispatch_contract_catalog_hash
        or evidence["work_order_id"] != work_order.work_order_id
        or evidence["work_order_hash"] != work_order.content_hash
        or evidence["task_id"] != work_order.task_id
        or evidence["task_revision"] != work_order.task_revision
        or evidence["task_content_hash"] != work_order.task_content_hash
        or evidence["route_decision_id"] != work_order.route_decision_id
        or evidence["route_decision_hash"] != work_order.route_decision_hash
        or evidence["dispatch_catalog_id"] != work_order.dispatch_catalog_id
        or evidence["dispatch_catalog_hash"] != work_order.dispatch_catalog_hash
        or evidence["dispatch_contract_id"] != work_order.dispatch_contract_id
        or evidence["dispatch_contract_hash"] != work_order.dispatch_contract_hash
    ):
        raise PreparationReceiptError(
            "planner-return evidence does not exactly continue PREP authority"
        )


def _require_work_order_checkpoint_current(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
) -> None:
    if receipt.stage not in (PreparationStage.WORK_ORDER_AUDITED, PreparationStage.BOUND):
        return
    if (
        receipt.work_order_id is None
        or receipt.work_order_hash is None
        or receipt.work_order_audit_id is None
        or receipt.work_order_audit_hash is None
    ):
        raise PreparationReceiptError("audited PREP lacks exact Phase-33 checkpoint")
    validators = build_builtin_dispatch_validator_registry()
    work_order = read_work_order(runtime, receipt.work_order_id, validators)
    audit = read_work_order_audit(runtime, receipt.work_order_audit_id, validators)
    if (
        work_order.content_hash != receipt.work_order_hash
        or audit.content_hash != receipt.work_order_audit_hash
        or audit.work_order_id != work_order.work_order_id
        or audit.work_order_hash != work_order.content_hash
        or work_order.task_id != receipt.task_id
        or work_order.task_revision != receipt.ready_task_revision
        or work_order.task_content_hash != receipt.ready_task_hash
        or work_order.route_decision_id != receipt.route_decision_id
        or work_order.route_decision_hash != receipt.route_decision_hash
    ):
        raise PreparationReceiptError(
            "PREP WorkOrder/audit hashes or frozen relation drifted"
        )
    currentness = inspect_work_order_currentness_readonly(
        runtime,
        work_order.work_order_id,
        audit.work_order_audit_id,
        validators,
    )
    if (
        currentness.status is not WorkOrderCurrentnessStatus.CURRENT_READY
        or currentness.task_id != receipt.task_id
    ):
        raise PreparationReceiptError(
            f"PREP WorkOrder checkpoint is {currentness.status.value}, not CURRENT_READY"
        )


def _require_bound_checkpoint_current(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
) -> None:
    if receipt.stage is not PreparationStage.BOUND:
        return
    if (
        receipt.input_resolution_id is None
        or receipt.input_resolution_hash is None
        or receipt.dispatch_binding_id is None
        or receipt.dispatch_binding_hash is None
        or receipt.binding_audit_id is None
        or receipt.binding_audit_hash is None
    ):
        raise PreparationReceiptError("BOUND PREP lacks exact Phase-34 authority")

    bundle = read_input_resolution(runtime, receipt.input_resolution_id)
    binding = read_dispatch_binding(runtime, receipt.dispatch_binding_id)
    audit = read_dispatch_binding_audit(runtime, receipt.binding_audit_id)
    if (
        bundle.content_hash != receipt.input_resolution_hash
        or binding.content_hash != receipt.dispatch_binding_hash
        or audit.content_hash != receipt.binding_audit_hash
        or bundle.work_order_id != receipt.work_order_id
        or bundle.work_order_hash != receipt.work_order_hash
        or bundle.work_order_audit_id != receipt.work_order_audit_id
        or bundle.work_order_audit_hash != receipt.work_order_audit_hash
        or bundle.task_id != receipt.task_id
        or bundle.task_revision != receipt.ready_task_revision
        or bundle.task_content_hash != receipt.ready_task_hash
        or bundle.route_decision_id != receipt.route_decision_id
        or bundle.route_decision_hash != receipt.route_decision_hash
        or binding.input_resolution_id != bundle.input_resolution_id
        or binding.input_resolution_hash != bundle.content_hash
        or binding.work_order_id != bundle.work_order_id
        or binding.work_order_hash != bundle.work_order_hash
        or audit.input_resolution_id != bundle.input_resolution_id
        or audit.input_resolution_hash != bundle.content_hash
        or audit.dispatch_binding_id != binding.dispatch_binding_id
        or audit.dispatch_binding_hash != binding.content_hash
    ):
        raise PreparationReceiptError(
            "PREP Phase-34 IDs/hashes do not form the exact frozen receipt chain"
        )

    currentness = inspect_dispatch_binding_currentness_readonly(
        runtime,
        bundle.input_resolution_id,
        binding.dispatch_binding_id,
        audit.binding_audit_id,
        build_core_input_resolver_registry(),
        build_builtin_dispatch_binder_registry(),
    )
    if (
        currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY
        or currentness.task_id != receipt.task_id
    ):
        raise PreparationReceiptError(
            f"PREP Phase-34 authority is {currentness.status.value}, not CURRENT_READY"
        )


def _state_for_current_receipt(
    receipt: TaskPreparationReceipt,
) -> PreparationInspectionState:
    if receipt.status is PreparationStatus.INTERRUPTED:
        return PreparationInspectionState.INTERRUPTED
    if receipt.status is PreparationStatus.FAILED_PRE_PLANNER:
        return PreparationInspectionState.FAILED_PRE_PLANNER
    if receipt.status is PreparationStatus.READY:
        if receipt.stage is not PreparationStage.BOUND:
            raise PreparationReceiptError("READY PREP is not at BOUND checkpoint")
        return PreparationInspectionState.READY_FOR_PHASE38
    if receipt.status is not PreparationStatus.ACTIVE:
        raise PreparationReceiptError("PREP status is outside Phase-39 contract")
    if receipt.stage in (
        PreparationStage.CLAIMED,
        PreparationStage.ACTIVATED,
        PreparationStage.ROUTED,
    ):
        return PreparationInspectionState.ACTIVE_PRE_PLANNER
    if receipt.stage is PreparationStage.PLANNER_STARTED:
        return PreparationInspectionState.PLANNER_RECOVERY_REQUIRED
    if receipt.stage in (
        PreparationStage.PLANNER_RETURNED,
        PreparationStage.WORK_ORDER_AUDITED,
    ):
        return PreparationInspectionState.POST_PLANNER_RESUMABLE
    raise PreparationReceiptError(
        "ACTIVE PREP stage is outside resumable Phase-39 states"
    )


def inspect_preparation_receipt_status_readonly(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> PreparationReceiptStatusProjection:
    """Inspect durable PREP lifecycle/currentness without creating or repairing authority."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    receipt, task_status, task_input = _load_receipt_and_task_snapshot(
        runtime,
        preparation_id,
    )
    state = _state_for_current_receipt(receipt)
    try:
        policy = _require_receipt_policy_relation(runtime, receipt)
        _require_task_checkpoint_current(receipt, task_status, task_input)
        _require_route_checkpoint_current(runtime, receipt, policy)
        _require_planner_return_checkpoint_current(runtime, receipt, policy)
        _require_work_order_checkpoint_current(runtime, receipt)
        _require_bound_checkpoint_current(runtime, receipt)
        current = True
        detail = None
    except (
        PreparationReceiptError,
        ProductionPreparationPolicyStoreError,
        ProductionCapabilityReadError,
        ProductionWorkOrderReadError,
        ProductionDispatchReadError,
        ProductionReadGuardError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        current = False
        detail = f"{type(exc).__name__}: {exc}"
        if receipt.status in (PreparationStatus.ACTIVE, PreparationStatus.READY):
            state = PreparationInspectionState.STALE_OR_INVALID

    return PreparationReceiptStatusProjection(
        state=state,
        preparation_id=receipt.preparation_id,
        preparation_policy_id=receipt.preparation_policy_id,
        preparation_policy_hash=receipt.preparation_policy_hash,
        task_id=receipt.task_id,
        receipt_status=receipt.status,
        stage=receipt.stage,
        revision=receipt.revision,
        current=current,
        route_decision_id=receipt.route_decision_id,
        work_order_id=receipt.work_order_id,
        work_order_audit_id=receipt.work_order_audit_id,
        input_resolution_id=receipt.input_resolution_id,
        dispatch_binding_id=receipt.dispatch_binding_id,
        binding_audit_id=receipt.binding_audit_id,
        detail=detail,
    )
