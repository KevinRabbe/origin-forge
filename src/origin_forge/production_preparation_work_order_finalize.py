from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_capability_store import ProductionCapabilityStore
from .production_preparation_models import PreparationStage, PreparationStatus, TaskPreparationReceipt
from .production_preparation_planner_evidence import (
    PlannerEvidenceRecoveryStatus,
    recover_planner_evidence,
)
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_receipts import (
    PreparationReceiptError,
    _load_receipt_connection,
    _require_active_checkpoint,
    read_preparation_receipt,
)
from .production_work_order_audit import (
    WorkOrderAudit,
    WorkOrderAuditStatus,
    WorkOrderCurrentnessStatus,
    audit_work_order_frozen,
    inspect_work_order_currentness,
)
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_store import (
    ProductionWorkOrderStore,
    ProductionWorkOrderStoreError,
    _MAX_OBJECTS_PER_CATEGORY,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


class PreparationWorkOrderFinalizeStatus(StrEnum):
    WORK_ORDER_AUDITED = "WORK_ORDER_AUDITED"
    ALREADY_AUDITED = "ALREADY_AUDITED"
    PLANNER_UNRESOLVED = "PLANNER_UNRESOLVED"
    INVALID_STATE = "INVALID_STATE"
    INVALID_AUTHORITY = "INVALID_AUTHORITY"
    AMBIGUOUS_AUDIT = "AMBIGUOUS_AUDIT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True)
class PreparationWorkOrderFinalizeResult:
    status: PreparationWorkOrderFinalizeStatus
    preparation_id: str
    receipt: TaskPreparationReceipt
    work_order_audit: WorkOrderAudit | None
    reused_work_order: bool
    reused_audit: bool
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "preparation_id": self.preparation_id,
            "receipt": self.receipt.to_dict(),
            "work_order_audit": (
                None if self.work_order_audit is None else self.work_order_audit.to_dict()
            ),
            "reused_work_order": self.reused_work_order,
            "reused_audit": self.reused_audit,
            "detail": self.detail,
            "authority": "deterministic-phase33-publication-and-audit",
        }


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:4096]


def _semantic_audit_key(audit: WorkOrderAudit) -> tuple[tuple[str, object], ...]:
    value = audit.to_dict()
    value.pop("work_order_audit_id")
    return tuple(sorted(value.items(), key=lambda item: item[0]))


def _existing_audits_for_work_order(
    store: ProductionWorkOrderStore,
    work_order_id: str,
    work_order_hash: str,
) -> tuple[WorkOrderAudit, ...]:
    directory = store._category_dir("audits", create=False)
    if not directory.exists():
        return ()
    audit_ids: list[str] = []
    count = 0
    for path in directory.iterdir():
        count += 1
        if count > _MAX_OBJECTS_PER_CATEGORY:
            raise OverflowError("WorkOrder audit scan limit exceeded")
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ProductionWorkOrderStoreError(
                "WorkOrder audit store contains an undeclared or aliased entry"
            )
        audit_id = path.stem
        if path.name != f"{audit_id}.json" or not validate_id(
            audit_id, IdKind.WORK_ORDER_AUDIT
        ):
            raise ProductionWorkOrderStoreError(
                "WorkOrder audit store contains an invalid evidence filename"
            )
        if path.resolve(strict=True) != path:
            raise ProductionWorkOrderStoreError("WorkOrder audit evidence path is aliased")
        audit_ids.append(audit_id)
    result: list[WorkOrderAudit] = []
    for audit_id in sorted(audit_ids):
        audit = store.load_audit(audit_id)
        if audit.work_order_id == work_order_id:
            if audit.work_order_hash != work_order_hash:
                raise ProductionWorkOrderStoreError(
                    "one WorkOrder ID resolves to conflicting audit hashes"
                )
            result.append(audit)
    return tuple(result)


def _checkpoint_work_order_audited(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
    audit: WorkOrderAudit,
    store: ProductionWorkOrderStore,
) -> TaskPreparationReceipt:
    if not isinstance(audit, WorkOrderAudit):
        raise TypeError("audit must be a WorkOrderAudit")
    # Re-read both immutable Phase-33 artifacts immediately before durable PREP mutation.
    work_order = store.load_work_order(audit.work_order_id)
    persisted_audit = store.load_audit(audit.work_order_audit_id)
    if persisted_audit != audit or persisted_audit.status is not WorkOrderAuditStatus.PASS:
        raise PreparationReceiptError("persisted WorkOrder audit is not exact PASS authority")

    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.PLANNER_RETURNED,
            expected_revision=expected_revision,
        )
        if (
            work_order.work_order_id != receipt.work_order_id
            or work_order.content_hash != receipt.work_order_hash
            or audit.work_order_id != receipt.work_order_id
            or audit.work_order_hash != receipt.work_order_hash
            or audit.task_id != receipt.task_id
            or audit.task_revision != receipt.ready_task_revision
            or audit.task_content_hash != receipt.ready_task_hash
            or audit.route_decision_id != receipt.route_decision_id
            or audit.route_decision_hash != receipt.route_decision_hash
        ):
            raise PreparationReceiptError(
                "WorkOrder audit does not exactly continue PREP planner-return authority"
            )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET work_order_audit_id = ?, work_order_audit_hash = ?,
                   stage = 'WORK_ORDER_AUDITED', revision = ?, updated_at = ?
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = 'PLANNER_RETURNED' AND revision = ?""",
            (
                audit.work_order_audit_id,
                audit.content_hash,
                new_revision,
                now,
                receipt.preparation_id,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("PREP changed during WorkOrder-audit checkpoint")
        return _load_receipt_connection(conn, preparation_id)


def _validate_existing_audited_checkpoint(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
) -> tuple[WorkOrderAudit, bool, bool]:
    if not receipt.work_order_id or not receipt.work_order_audit_id:
        raise PreparationReceiptError("WORK_ORDER_AUDITED receipt lacks Phase-33 IDs")
    policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
    if policy.content_hash != receipt.preparation_policy_hash:
        raise PreparationReceiptError("PREP policy hash drifted at audited checkpoint")
    capability_store = ProductionCapabilityStore(runtime)
    validators = build_builtin_dispatch_validator_registry()
    store = ProductionWorkOrderStore(runtime, capability_store, validators)
    catalog = store.load_dispatch_catalog(policy.dispatch_contract_catalog_id)
    if catalog.content_hash != policy.dispatch_contract_catalog_hash:
        raise PreparationReceiptError("PREPPOL DISPCAT hash drifted at audited checkpoint")
    work_order = store.load_work_order(receipt.work_order_id)
    audit = store.load_audit(receipt.work_order_audit_id)
    currentness = inspect_work_order_currentness(
        runtime,
        capability_store,
        catalog,
        validators,
        work_order,
        audit,
    )
    if (
        work_order.content_hash != receipt.work_order_hash
        or audit.content_hash != receipt.work_order_audit_hash
        or currentness.status is not WorkOrderCurrentnessStatus.CURRENT_READY
    ):
        raise PreparationReceiptError(
            "audited PREP checkpoint is no longer exact CURRENT_READY authority"
        )
    return audit, True, True


def finalize_preparation_work_order_audit(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> PreparationWorkOrderFinalizeResult:
    """Recover/publish/audit Phase-33 WorkOrder evidence and stop before Phase 34.

    The operation contains no model call. Existing immutable WorkOrder/audit
    artifacts are reloaded and independently recomputed so a crash after publish
    but before the PREP checkpoint can be retried without manufacturing a second
    authority chain unnecessarily.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    receipt = read_preparation_receipt(runtime, preparation_id)
    if receipt.status is not PreparationStatus.ACTIVE:
        return PreparationWorkOrderFinalizeResult(
            PreparationWorkOrderFinalizeStatus.INVALID_STATE,
            preparation_id,
            receipt,
            None,
            False,
            False,
            "PREP is not ACTIVE",
        )
    if receipt.stage is PreparationStage.WORK_ORDER_AUDITED:
        try:
            audit, reused_work_order, reused_audit = _validate_existing_audited_checkpoint(
                runtime, receipt
            )
        except Exception as exc:
            return PreparationWorkOrderFinalizeResult(
                PreparationWorkOrderFinalizeStatus.INVALID_AUTHORITY,
                preparation_id,
                receipt,
                None,
                False,
                False,
                _detail(exc),
            )
        return PreparationWorkOrderFinalizeResult(
            PreparationWorkOrderFinalizeStatus.ALREADY_AUDITED,
            preparation_id,
            receipt,
            audit,
            reused_work_order,
            reused_audit,
            None,
        )
    if receipt.stage not in (
        PreparationStage.PLANNER_STARTED,
        PreparationStage.PLANNER_RETURNED,
    ):
        return PreparationWorkOrderFinalizeResult(
            PreparationWorkOrderFinalizeStatus.INVALID_STATE,
            preparation_id,
            receipt,
            None,
            False,
            False,
            f"PREP stage {receipt.stage.value} is not a Phase-33 finalization checkpoint",
        )

    recovered = recover_planner_evidence(runtime, preparation_id)
    if recovered.status not in (
        PlannerEvidenceRecoveryStatus.EXACT_RETURN,
        PlannerEvidenceRecoveryStatus.RECOVERED_PLANNER_RETURNED,
    ) or recovered.planner_result is None:
        return PreparationWorkOrderFinalizeResult(
            PreparationWorkOrderFinalizeStatus.PLANNER_UNRESOLVED,
            preparation_id,
            recovered.receipt,
            None,
            False,
            False,
            recovered.detail or recovered.status.value,
        )
    receipt = recovered.receipt
    work_order = recovered.planner_result.work_order

    try:
        policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
        if policy.content_hash != receipt.preparation_policy_hash:
            raise PreparationReceiptError("PREP policy hash drifted before Phase-33 publication")
        capability_store = ProductionCapabilityStore(runtime)
        validators = build_builtin_dispatch_validator_registry()
        store = ProductionWorkOrderStore(runtime, capability_store, validators)
        catalog = store.load_dispatch_catalog(policy.dispatch_contract_catalog_id)
        if catalog.content_hash != policy.dispatch_contract_catalog_hash:
            raise PreparationReceiptError("PREPPOL DISPCAT hash drifted before publication")

        ephemeral_audit = audit_work_order_frozen(
            capability_store,
            catalog,
            validators,
            work_order,
        )
        if ephemeral_audit.status is not WorkOrderAuditStatus.PASS:
            raise PreparationReceiptError("reconstructed WorkOrder does not frozen-audit as PASS")
        ephemeral_currentness = inspect_work_order_currentness(
            runtime,
            capability_store,
            catalog,
            validators,
            work_order,
            ephemeral_audit,
        )
        if ephemeral_currentness.status is not WorkOrderCurrentnessStatus.CURRENT_READY:
            raise PreparationReceiptError(
                f"reconstructed WorkOrder is not CURRENT_READY: {ephemeral_currentness.status.value}"
            )

        work_order_path = store._exact_path(
            "work-orders", work_order.work_order_id, require_file=False
        )
        reused_work_order = work_order_path.exists()
        if reused_work_order:
            persisted_work_order = store.load_work_order(work_order.work_order_id)
            if persisted_work_order.to_dict() != work_order.to_dict():
                raise PreparationReceiptError(
                    "persisted WorkOrder ID conflicts with reconstructed planner result"
                )
        else:
            store.publish_work_order(work_order)

        existing_audits = _existing_audits_for_work_order(
            store,
            work_order.work_order_id,
            work_order.content_hash,
        )
        if existing_audits:
            semantic_keys = {_semantic_audit_key(audit) for audit in existing_audits}
            if len(semantic_keys) != 1 or any(
                audit.status is not WorkOrderAuditStatus.PASS for audit in existing_audits
            ):
                return PreparationWorkOrderFinalizeResult(
                    PreparationWorkOrderFinalizeStatus.AMBIGUOUS_AUDIT,
                    preparation_id,
                    receipt,
                    None,
                    reused_work_order,
                    True,
                    "existing WorkOrder audits do not collapse to one semantic PASS authority",
                )
            audit = min(existing_audits, key=lambda value: value.work_order_audit_id)
            reused_audit = True
        else:
            audit = ephemeral_audit
            store.publish_audit(audit)
            reused_audit = False

        currentness = inspect_work_order_currentness(
            runtime,
            capability_store,
            catalog,
            validators,
            store.load_work_order(work_order.work_order_id),
            store.load_audit(audit.work_order_audit_id),
        )
        if currentness.status is not WorkOrderCurrentnessStatus.CURRENT_READY:
            raise PreparationReceiptError(
                f"persisted WorkOrder authority is not CURRENT_READY: {currentness.status.value}"
            )
        updated = _checkpoint_work_order_audited(
            runtime,
            preparation_id,
            receipt.revision,
            audit,
            store,
        )
    except OverflowError as exc:
        return PreparationWorkOrderFinalizeResult(
            PreparationWorkOrderFinalizeStatus.LIMIT_EXCEEDED,
            preparation_id,
            read_preparation_receipt(runtime, preparation_id),
            None,
            False,
            False,
            str(exc),
        )
    except (
        PreparationReceiptError,
        ProductionPreparationPolicyStoreError,
        ProductionWorkOrderStoreError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        return PreparationWorkOrderFinalizeResult(
            PreparationWorkOrderFinalizeStatus.RECOVERY_REQUIRED,
            preparation_id,
            read_preparation_receipt(runtime, preparation_id),
            None,
            locals().get("reused_work_order", False),
            locals().get("reused_audit", False),
            _detail(exc),
        )

    return PreparationWorkOrderFinalizeResult(
        PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        preparation_id,
        updated,
        audit,
        reused_work_order,
        reused_audit,
        None,
    )
