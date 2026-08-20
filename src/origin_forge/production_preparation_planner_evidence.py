from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .production_capability_store import ProductionCapabilityStore, ProductionCapabilityStoreError
from .production_preparation_models import PreparationStage, PreparationStatus, TaskPreparationReceipt
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_provenance import (
    ProductionPreparationProvenanceError,
    resolve_preparation_policy_provenance,
)
from .production_preparation_receipts import (
    PreparationReceiptError,
    checkpoint_preparation_planner_returned,
    read_preparation_receipt,
)
from .production_work_order_models import (
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
from .production_work_order_planner import WorkOrderPlannerResult
from .production_work_orders import ProductionWorkOrder, ProductionWorkOrderError
from .runtime import OriginForgeRuntime
from .state import TaskStatus


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CANDIDATE_RUNS = 256
_PLANNER_ROLE = "WORK_ORDER_PLANNER"
_VERIFICATION_TYPE = "work-order-planner-generation"
_VERIFIER = "OriginForge.BoundedProductionWorkOrderPlanner"
_EVIDENCE_KEYS = {
    "route_decision_id",
    "route_decision_hash",
    "task_id",
    "task_revision",
    "task_content_hash",
    "dispatch_catalog_id",
    "dispatch_catalog_hash",
    "dispatch_contract_id",
    "dispatch_contract_hash",
    "validator_id",
    "validator_fingerprint",
    "payload_schema_id",
    "payload_schema_hash",
    "request_hash",
    "response_hash",
    "proposal_hash",
    "proposal",
    "work_order_id",
    "work_order_hash",
    "work_order",
    "model_id",
    "model_hash",
    "audited",
    "dispatched",
}
_METRIC_KEYS = {
    "response_bytes",
    "allowed_input_refs",
    "input_tokens",
    "output_tokens",
    "model_calls",
}
_WORK_ORDER_KEYS = {
    "work_order_id",
    "task_id",
    "task_revision",
    "task_content_hash",
    "flow_id",
    "route_decision_id",
    "route_decision_hash",
    "selected_adapter_id",
    "selected_adapter_fingerprint",
    "dispatch_catalog_id",
    "dispatch_catalog_hash",
    "dispatch_contract_id",
    "dispatch_contract_hash",
    "input_refs",
    "payload",
}


class PreparationPlannerEvidenceError(RuntimeError):
    pass


class PlannerEvidenceRecoveryStatus(StrEnum):
    EXACT_RETURN = "EXACT_RETURN"
    RECOVERED_PLANNER_RETURNED = "RECOVERED_PLANNER_RETURNED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"


@dataclass(frozen=True)
class PlannerEvidenceRecovery:
    status: PlannerEvidenceRecoveryStatus
    preparation_id: str
    receipt: TaskPreparationReceipt
    planner_result: WorkOrderPlannerResult | None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "preparation_id": self.preparation_id,
            "receipt": self.receipt.to_dict(),
            "planner_result": None
            if self.planner_result is None
            else {
                "run_id": self.planner_result.run_id,
                "verification_id": self.planner_result.verification_id,
                "route_decision_id": self.planner_result.route_decision_id,
                "route_decision_hash": self.planner_result.route_decision_hash,
                "work_order_id": self.planner_result.work_order.work_order_id,
                "work_order_hash": self.planner_result.work_order.content_hash,
                "model_id": self.planner_result.model_id,
                "model_hash": self.planner_result.model_hash,
            },
            "detail": self.detail,
            "authority": "deterministic-post-planner-evidence-recovery",
        }


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreparationPlannerEvidenceError(
                f"planner verification contains duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _parse_canonical_object(raw: object, label: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > 4 * 1024 * 1024:
        raise PreparationPlannerEvidenceError(f"{label} JSON is outside byte bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except PreparationPlannerEvidenceError:
        raise
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise PreparationPlannerEvidenceError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise PreparationPlannerEvidenceError(f"{label} must decode to an object")
    expected = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if expected != raw:
        raise PreparationPlannerEvidenceError(f"{label} JSON is not canonical")
    return value


def _digest(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PreparationPlannerEvidenceError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _single_input_ref_from_evidence(
    raw_refs: list[object],
    *,
    label: str,
    ref_type: WorkOrderRefType,
    role: str,
) -> tuple[WorkOrderInputRef, ...]:
    if len(raw_refs) != 1 or not isinstance(raw_refs[0], dict):
        raise PreparationPlannerEvidenceError(
            f"{label} planner WorkOrder requires exactly one input ref"
        )
    raw_ref = raw_refs[0]
    if set(raw_ref) != {"ref_type", "ref_id", "content_hash", "role", "revision"}:
        raise PreparationPlannerEvidenceError(
            f"{label} planner WorkOrder input ref schema drifted"
        )
    try:
        ref = WorkOrderInputRef(
            ref_type=WorkOrderRefType(raw_ref["ref_type"]),
            ref_id=raw_ref["ref_id"],
            content_hash=raw_ref["content_hash"],
            role=raw_ref["role"],
            revision=raw_ref["revision"],
        )
    except (ProductionWorkOrderModelError, TypeError, ValueError) as exc:
        raise PreparationPlannerEvidenceError(
            f"{label} planner WorkOrder input ref failed reconstruction"
        ) from exc
    if ref.ref_type is not ref_type or ref.role != role or ref.revision is not None:
        raise PreparationPlannerEvidenceError(
            f"{label} planner WorkOrder input ref authority drifted"
        )
    return (ref,)


def _work_order_from_evidence(value: object) -> ProductionWorkOrder:
    if not isinstance(value, dict) or set(value) != _WORK_ORDER_KEYS:
        raise PreparationPlannerEvidenceError("planner WorkOrder schema drifted")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise PreparationPlannerEvidenceError("planner WorkOrder payload is invalid")

    raw_refs = value["input_refs"]
    if not isinstance(raw_refs, list):
        raise PreparationPlannerEvidenceError("planner WorkOrder input refs are not a list")
    if (
        value["selected_adapter_id"] == "originforge.pixelorama.export"
        and value["dispatch_contract_id"] == "pixelorama.spritesheet-export@1"
    ):
        refs = _single_input_ref_from_evidence(
            raw_refs,
            label="Pixelorama",
            ref_type=WorkOrderRefType.ARTIFACT,
            role="pixelorama_project",
        )
    elif (
        value["selected_adapter_id"] == "originforge.blender.model3d"
        and value["dispatch_contract_id"] == "blender.export-glb@1"
    ):
        refs = _single_input_ref_from_evidence(
            raw_refs,
            label="Blender",
            ref_type=WorkOrderRefType.MODEL3D_REQUEST,
            role="model3d_request",
        )
    else:
        if raw_refs != []:
            raise PreparationPlannerEvidenceError(
                "planner evidence contains input refs outside reviewed preparation authority"
            )
        refs = ()

    try:
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        work_order = ProductionWorkOrder(
            work_order_id=value["work_order_id"],
            task_id=value["task_id"],
            task_revision=value["task_revision"],
            task_content_hash=value["task_content_hash"],
            flow_id=value["flow_id"],
            route_decision_id=value["route_decision_id"],
            route_decision_hash=value["route_decision_hash"],
            selected_adapter_id=value["selected_adapter_id"],
            selected_adapter_fingerprint=value["selected_adapter_fingerprint"],
            dispatch_catalog_id=value["dispatch_catalog_id"],
            dispatch_catalog_hash=value["dispatch_catalog_hash"],
            dispatch_contract_id=value["dispatch_contract_id"],
            dispatch_contract_hash=value["dispatch_contract_hash"],
            input_refs=refs,
            payload_json=payload_json,
        )
    except (
        ProductionWorkOrderError,
        ProductionWorkOrderModelError,
        TypeError,
        ValueError,
    ) as exc:
        raise PreparationPlannerEvidenceError(
            "planner WorkOrder failed exact contract reconstruction"
        ) from exc
    if work_order.to_dict() != value:
        raise PreparationPlannerEvidenceError(
            "planner WorkOrder derived fields do not reconstruct exactly"
        )
    return work_order


def _row_to_result(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
    run_row,
    verification_row,
) -> WorkOrderPlannerResult:
    if (
        run_row["task_id"] is not None
        or run_row["role"] != _PLANNER_ROLE
        or run_row["status"] != "SUCCEEDED"
        or verification_row["target_type"] != "RUN"
        or verification_row["target_id"] != run_row["id"]
        or verification_row["run_id"] != run_row["id"]
        or verification_row["verification_type"] != _VERIFICATION_TYPE
        or verification_row["verifier"] != _VERIFIER
        or verification_row["status"] != "PASS"
    ):
        raise PreparationPlannerEvidenceError(
            "planner Run/verification relation is not an exact successful taskless planner result"
        )

    evidence = _parse_canonical_object(verification_row["evidence_json"], "planner evidence")
    metrics = _parse_canonical_object(verification_row["metrics_json"], "planner metrics")
    if set(evidence) != _EVIDENCE_KEYS or set(metrics) != _METRIC_KEYS:
        raise PreparationPlannerEvidenceError("planner verification schema drifted")
    if (
        evidence["audited"] is not False
        or evidence["dispatched"] is not False
        or metrics["model_calls"] != 1
        or type(metrics["response_bytes"]) is not int
        or metrics["response_bytes"] < 0
    ):
        raise PreparationPlannerEvidenceError(
            "planner verification crosses or misstates the Phase-33 one-shot boundary"
        )
    for label in (
        "route_decision_hash",
        "task_content_hash",
        "dispatch_catalog_hash",
        "dispatch_contract_hash",
        "validator_fingerprint",
        "payload_schema_hash",
        "request_hash",
        "response_hash",
        "proposal_hash",
        "work_order_hash",
    ):
        _digest(evidence[label], label)
    _digest(evidence["model_hash"], "model_hash", nullable=True)
    if not isinstance(evidence["model_id"], str) or not evidence["model_id"]:
        raise PreparationPlannerEvidenceError("planner model_id is invalid")
    if not isinstance(evidence["proposal"], dict):
        raise PreparationPlannerEvidenceError("planner proposal evidence is invalid")
    try:
        proposal_hash = content_hash(evidence["proposal"])
    except ProductionWorkOrderModelError as exc:
        raise PreparationPlannerEvidenceError(
            "planner proposal is outside canonical bounds"
        ) from exc
    if proposal_hash != evidence["proposal_hash"]:
        raise PreparationPlannerEvidenceError("planner proposal hash does not recompute")

    work_order = _work_order_from_evidence(evidence["work_order"])
    if (
        metrics["allowed_input_refs"] != len(work_order.input_refs)
        or work_order.work_order_id != evidence["work_order_id"]
        or work_order.content_hash != evidence["work_order_hash"]
        or work_order.task_id != evidence["task_id"]
        or work_order.task_revision != evidence["task_revision"]
        or work_order.task_content_hash != evidence["task_content_hash"]
        or work_order.route_decision_id != evidence["route_decision_id"]
        or work_order.route_decision_hash != evidence["route_decision_hash"]
        or work_order.dispatch_catalog_id != evidence["dispatch_catalog_id"]
        or work_order.dispatch_catalog_hash != evidence["dispatch_catalog_hash"]
        or work_order.dispatch_contract_id != evidence["dispatch_contract_id"]
        or work_order.dispatch_contract_hash != evidence["dispatch_contract_hash"]
    ):
        raise PreparationPlannerEvidenceError(
            "planner evidence does not bind its reconstructed WorkOrder exactly"
        )

    try:
        policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
        if policy.content_hash != receipt.preparation_policy_hash:
            raise PreparationPlannerEvidenceError(
                "PREP policy hash drifted before planner evidence recovery"
            )
        provenance = resolve_preparation_policy_provenance(runtime, policy)
        route = ProductionCapabilityStore(runtime).require_current_route(
            receipt.route_decision_id
        )
        task = runtime.get_task(receipt.task_id)
    except (
        ProductionPreparationPolicyStoreError,
        ProductionPreparationProvenanceError,
        ProductionCapabilityStoreError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise PreparationPlannerEvidenceError(
            "current PREPPOL/route/Task authority cannot revalidate planner evidence"
        ) from exc
    if (
        route.content_hash != receipt.route_decision_hash
        or route.route_decision_id != work_order.route_decision_id
        or work_order.task_id != receipt.task_id
        or work_order.task_revision != receipt.ready_task_revision
        or work_order.task_content_hash != receipt.ready_task_hash
        or work_order.dispatch_catalog_id != policy.dispatch_contract_catalog_id
        or work_order.dispatch_catalog_hash != policy.dispatch_contract_catalog_hash
        or task["status"] != TaskStatus.READY.value
        or int(task["revision"]) != receipt.ready_task_revision
    ):
        raise PreparationPlannerEvidenceError(
            "planner evidence is stale against exact PREP READY Task authority"
        )
    try:
        contract = provenance.dispatch_contract_catalog.contract_for_adapter(
            work_order.selected_adapter_id
        )
    except KeyError as exc:
        raise PreparationPlannerEvidenceError(
            "PREPPOL DISPCAT lacks reconstructed WorkOrder adapter"
        ) from exc
    if (
        contract.contract_id != work_order.dispatch_contract_id
        or contract.content_hash != work_order.dispatch_contract_hash
        or contract.adapter_fingerprint != work_order.selected_adapter_fingerprint
        or evidence["validator_id"] != contract.validator_id
        or evidence["validator_fingerprint"] != contract.validator_fingerprint
        or evidence["payload_schema_id"] != contract.payload_schema_id
        or evidence["payload_schema_hash"] != contract.payload_schema_hash
    ):
        raise PreparationPlannerEvidenceError(
            "planner evidence drifted from exact PREPPOL dispatch contract"
        )

    return WorkOrderPlannerResult(
        run_id=run_row["id"],
        route_decision_id=work_order.route_decision_id,
        route_decision_hash=work_order.route_decision_hash,
        request_hash=evidence["request_hash"],
        response_hash=evidence["response_hash"],
        proposal_hash=evidence["proposal_hash"],
        work_order=work_order,
        verification_id=verification_row["id"],
        model_id=evidence["model_id"],
        model_hash=evidence["model_hash"],
    )


def _exact_run_result(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
    run_id: str,
) -> WorkOrderPlannerResult:
    with runtime.store.session() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        rows = conn.execute(
            """SELECT * FROM verifications
               WHERE target_type = 'RUN' AND target_id = ?
                 AND run_id = ? AND verification_type = ?
                 AND verifier = ? AND status = 'PASS'
               ORDER BY created_at, rowid
               LIMIT 2""",
            (run_id, run_id, _VERIFICATION_TYPE, _VERIFIER),
        ).fetchall()
    if run is None or len(rows) != 1:
        raise PreparationPlannerEvidenceError(
            "planner receipt does not resolve exactly one successful planner verification"
        )
    return _row_to_result(runtime, receipt, run, rows[0])


def _candidate_success_results(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
) -> tuple[WorkOrderPlannerResult, ...]:
    with runtime.store.session() as conn:
        rows = conn.execute(
            """SELECT
                   r.id AS candidate_run_id,
                   v.id AS candidate_verification_id
               FROM runs r
               JOIN verifications v
                 ON v.target_type = 'RUN'
                AND v.target_id = r.id
                AND v.run_id = r.id
               WHERE r.task_id IS NULL
                 AND r.role = ?
                 AND r.status = 'SUCCEEDED'
                 AND r.started_at >= ?
                 AND v.verification_type = ?
                 AND v.verifier = ?
                 AND v.status = 'PASS'
               ORDER BY r.started_at, r.rowid, v.created_at, v.rowid
               LIMIT ?""",
            (
                _PLANNER_ROLE,
                receipt.updated_at,
                _VERIFICATION_TYPE,
                _VERIFIER,
                _MAX_CANDIDATE_RUNS + 1,
            ),
        ).fetchall()
    if len(rows) > _MAX_CANDIDATE_RUNS:
        raise OverflowError("planner recovery candidate limit exceeded")

    results: list[WorkOrderPlannerResult] = []
    for row in rows:
        try:
            candidate = _exact_run_result(runtime, receipt, row["candidate_run_id"])
        except PreparationPlannerEvidenceError:
            continue
        # Multiple verification rows for one Run are rejected by _exact_run_result.
        if candidate.verification_id != row["candidate_verification_id"]:
            continue
        if (
            candidate.work_order.task_id == receipt.task_id
            and candidate.work_order.task_revision == receipt.ready_task_revision
            and candidate.work_order.task_content_hash == receipt.ready_task_hash
            and candidate.route_decision_id == receipt.route_decision_id
            and candidate.route_decision_hash == receipt.route_decision_hash
        ):
            results.append(candidate)
    return tuple(results)


def recover_planner_evidence(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> PlannerEvidenceRecovery:
    """Reconstruct a trustworthy planner return without calling or replaying a model.

    PLANNER_RETURNED is verified by its exact stored planner Run. PLANNER_STARTED
    may advance only when bounded evidence contains exactly one independently
    reconstructable successful planner result for the exact PREP Task/route.
    Zero, multiple, stale, malformed, or over-limit matches never trigger a
    planner call or an optimistic failure transition.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    receipt = read_preparation_receipt(runtime, preparation_id)
    if receipt.status is not PreparationStatus.ACTIVE or receipt.stage not in (
        PreparationStage.PLANNER_STARTED,
        PreparationStage.PLANNER_RETURNED,
    ):
        return PlannerEvidenceRecovery(
            PlannerEvidenceRecoveryStatus.INVALID_STATE,
            preparation_id,
            receipt,
            None,
            "PREP is not ACTIVE at a recoverable planner checkpoint",
        )

    if receipt.stage is PreparationStage.PLANNER_RETURNED:
        if not receipt.planner_run_id:
            return PlannerEvidenceRecovery(
                PlannerEvidenceRecoveryStatus.INVALID_STATE,
                preparation_id,
                receipt,
                None,
                "PLANNER_RETURNED lacks durable planner_run_id",
            )
        try:
            result = _exact_run_result(runtime, receipt, receipt.planner_run_id)
        except PreparationPlannerEvidenceError as exc:
            return PlannerEvidenceRecovery(
                PlannerEvidenceRecoveryStatus.UNRESOLVED,
                preparation_id,
                receipt,
                None,
                f"{type(exc).__name__}: {exc}",
            )
        if (
            result.work_order.work_order_id != receipt.work_order_id
            or result.work_order.content_hash != receipt.work_order_hash
        ):
            return PlannerEvidenceRecovery(
                PlannerEvidenceRecoveryStatus.UNRESOLVED,
                preparation_id,
                receipt,
                None,
                "durable PREP WorkOrder checkpoint differs from planner verification",
            )
        return PlannerEvidenceRecovery(
            PlannerEvidenceRecoveryStatus.EXACT_RETURN,
            preparation_id,
            receipt,
            result,
            None,
        )

    try:
        matches = _candidate_success_results(runtime, receipt)
    except OverflowError as exc:
        return PlannerEvidenceRecovery(
            PlannerEvidenceRecoveryStatus.LIMIT_EXCEEDED,
            preparation_id,
            receipt,
            None,
            str(exc),
        )
    if not matches:
        return PlannerEvidenceRecovery(
            PlannerEvidenceRecoveryStatus.UNRESOLVED,
            preparation_id,
            receipt,
            None,
            "no existing successful planner evidence reconstructs exact PREP authority",
        )
    if len(matches) != 1:
        return PlannerEvidenceRecovery(
            PlannerEvidenceRecoveryStatus.AMBIGUOUS,
            preparation_id,
            receipt,
            None,
            "multiple successful planner results reconstruct exact PREP authority",
        )
    result = matches[0]
    try:
        returned = checkpoint_preparation_planner_returned(
            runtime,
            preparation_id,
            receipt.revision,
            result,
        )
    except (PreparationReceiptError, RuntimeError, TypeError, ValueError) as exc:
        return PlannerEvidenceRecovery(
            PlannerEvidenceRecoveryStatus.UNRESOLVED,
            preparation_id,
            read_preparation_receipt(runtime, preparation_id),
            None,
            f"planner evidence reconstructed but durable checkpoint failed: {type(exc).__name__}: {exc}",
        )
    return PlannerEvidenceRecovery(
        PlannerEvidenceRecoveryStatus.RECOVERED_PLANNER_RETURNED,
        preparation_id,
        returned,
        result,
        None,
    )
