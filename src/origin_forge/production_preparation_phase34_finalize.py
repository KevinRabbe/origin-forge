from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_capability_store import ProductionCapabilityStore
from .production_dispatch_binding import (
    DispatchBindingError,
    _binding_with_id,
    _require_bundle_revalidates,
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
    inspect_dispatch_binding_currentness,
)
from .production_dispatch_binding_models import (
    BindingAuditStatus,
    DispatchBinding,
    DispatchBindingAudit,
    DispatchBindingCurrentnessStatus,
)
from .production_dispatch_resolution_models import InputResolutionBundle
from .production_dispatch_resolvers import build_core_input_resolver_registry
from .production_dispatch_store import (
    ProductionDispatchStore,
    ProductionDispatchStoreError,
    _MAX_OBJECTS_PER_CATEGORY,
)
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    TaskPreparationReceipt,
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
    WorkOrderCurrentnessStatus,
    inspect_work_order_currentness,
)
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_store import ProductionWorkOrderStore, ProductionWorkOrderStoreError
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


class PreparationPhase34FinalizeStatus(StrEnum):
    BOUND_READY = "BOUND_READY"
    ALREADY_READY = "ALREADY_READY"
    INVALID_STATE = "INVALID_STATE"
    INVALID_AUTHORITY = "INVALID_AUTHORITY"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True)
class PreparationPhase34FinalizeResult:
    status: PreparationPhase34FinalizeStatus
    preparation_id: str
    receipt: TaskPreparationReceipt
    input_resolution: InputResolutionBundle | None
    dispatch_binding: DispatchBinding | None
    binding_audit: DispatchBindingAudit | None
    reused_input_resolution: bool
    reused_dispatch_binding: bool
    reused_binding_audit: bool
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "preparation_id": self.preparation_id,
            "receipt": self.receipt.to_dict(),
            "input_resolution": (
                None if self.input_resolution is None else self.input_resolution.to_dict()
            ),
            "dispatch_binding": (
                None if self.dispatch_binding is None else self.dispatch_binding.to_dict()
            ),
            "binding_audit": (
                None if self.binding_audit is None else self.binding_audit.to_dict()
            ),
            "reused_input_resolution": self.reused_input_resolution,
            "reused_dispatch_binding": self.reused_dispatch_binding,
            "reused_binding_audit": self.reused_binding_audit,
            "detail": self.detail,
            "authority": "deterministic-phase34-finalization",
        }


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:4096]


def _semantic_dict(value: object, id_field: str) -> dict[str, object]:
    payload = dict(value.to_dict())
    payload.pop(id_field)
    return payload


def _enumerate_ids(
    store: ProductionDispatchStore,
    category: str,
    kind: IdKind,
) -> tuple[str, ...]:
    directory = store._category_dir(category, create=False)
    if not directory.exists():
        return ()
    ids: list[str] = []
    count = 0
    for path in directory.iterdir():
        count += 1
        if count > _MAX_OBJECTS_PER_CATEGORY:
            raise OverflowError(f"{category} scan limit exceeded")
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ProductionDispatchStoreError(
                f"{category} contains an undeclared or aliased entry"
            )
        object_id = path.stem
        if path.name != f"{object_id}.json" or not validate_id(object_id, kind):
            raise ProductionDispatchStoreError(
                f"{category} contains an invalid evidence filename"
            )
        if path.resolve(strict=True) != path:
            raise ProductionDispatchStoreError(f"{category} evidence path is aliased")
        ids.append(object_id)
    return tuple(sorted(ids))


def _build_stores(runtime: OriginForgeRuntime, receipt: TaskPreparationReceipt):
    policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
    if policy.content_hash != receipt.preparation_policy_hash:
        raise PreparationReceiptError("PREP policy hash drifted before Phase-34 finalization")
    capability_store = ProductionCapabilityStore(runtime)
    validators = build_builtin_dispatch_validator_registry()
    work_order_store = ProductionWorkOrderStore(runtime, capability_store, validators)
    catalog = work_order_store.load_dispatch_catalog(policy.dispatch_contract_catalog_id)
    if catalog.content_hash != policy.dispatch_contract_catalog_hash:
        raise PreparationReceiptError("PREPPOL DISPCAT hash drifted before Phase-34 finalization")
    if not receipt.work_order_id or not receipt.work_order_audit_id:
        raise PreparationReceiptError("PREP lacks exact audited Phase-33 authority")
    work_order = work_order_store.load_work_order(receipt.work_order_id)
    work_order_audit = work_order_store.load_audit(receipt.work_order_audit_id)
    if (
        work_order.content_hash != receipt.work_order_hash
        or work_order_audit.content_hash != receipt.work_order_audit_hash
    ):
        raise PreparationReceiptError("PREP Phase-33 hashes drifted before Phase-34 finalization")
    currentness = inspect_work_order_currentness(
        runtime,
        capability_store,
        catalog,
        validators,
        work_order,
        work_order_audit,
    )
    if currentness.status is not WorkOrderCurrentnessStatus.CURRENT_READY:
        raise PreparationReceiptError(
            f"PREP WorkOrder is not CURRENT_READY: {currentness.status.value}"
        )
    resolvers = build_core_input_resolver_registry()
    binders = build_builtin_dispatch_binder_registry()
    dispatch_store = ProductionDispatchStore(work_order_store, resolvers, binders)
    return policy, work_order_store, dispatch_store, resolvers, binders, work_order, work_order_audit


def _select_or_publish_bundle(
    store: ProductionDispatchStore,
    work_order_id: str,
    work_order_audit_id: str,
) -> tuple[InputResolutionBundle, bool]:
    expected = create_input_resolution_bundle(
        store.work_order_store,
        store.resolver_registry,
        work_order_id,
        work_order_audit_id,
    )
    expected_semantic = _semantic_dict(expected, "input_resolution_id")
    current: list[InputResolutionBundle] = []
    for bundle_id in _enumerate_ids(
        store,
        "input-resolutions",
        IdKind.INPUT_RESOLUTION_BUNDLE,
    ):
        bundle = store.load_input_resolution(bundle_id)
        if (
            bundle.work_order_id != work_order_id
            or bundle.work_order_audit_id != work_order_audit_id
        ):
            continue
        try:
            _require_bundle_revalidates(
                store.work_order_store,
                store.resolver_registry,
                bundle,
            )
        except (DispatchBindingError, ProductionWorkOrderStoreError, TypeError, ValueError):
            continue
        if _semantic_dict(bundle, "input_resolution_id") != expected_semantic:
            raise PreparationReceiptError(
                "multiple current input-resolution semantics exist for exact PREP WorkOrder"
            )
        current.append(bundle)
    if current:
        return min(current, key=lambda value: value.input_resolution_id), True
    store.publish_input_resolution(expected)
    return store.load_input_resolution(expected.input_resolution_id), False


def _binding_reconstructs(
    store: ProductionDispatchStore,
    bundle: InputResolutionBundle,
    binding: DispatchBinding,
) -> bool:
    try:
        work_order = _require_bundle_revalidates(
            store.work_order_store,
            store.resolver_registry,
            bundle,
        )
        binder = store.binder_registry.binder_for(bundle)
        expected = _binding_with_id(
            bundle,
            binder,
            binder.bind(work_order, bundle),
            binding.dispatch_binding_id,
        )
    except (DispatchBindingError, ProductionWorkOrderStoreError, TypeError, ValueError):
        return False
    return expected.to_dict() == binding.to_dict()


def _select_or_publish_binding(
    store: ProductionDispatchStore,
    bundle: InputResolutionBundle,
) -> tuple[DispatchBinding, bool]:
    expected = create_dispatch_binding(
        store.work_order_store,
        store.resolver_registry,
        store.binder_registry,
        bundle,
    )
    expected_semantic = _semantic_dict(expected, "dispatch_binding_id")
    current: list[DispatchBinding] = []
    for binding_id in _enumerate_ids(
        store,
        "dispatch-bindings",
        IdKind.DISPATCH_BINDING,
    ):
        binding = store.load_binding(binding_id)
        if binding.input_resolution_id != bundle.input_resolution_id:
            continue
        if not _binding_reconstructs(store, bundle, binding):
            continue
        if _semantic_dict(binding, "dispatch_binding_id") != expected_semantic:
            raise PreparationReceiptError(
                "multiple current dispatch-binding semantics exist for chosen input resolution"
            )
        current.append(binding)
    if current:
        return min(current, key=lambda value: value.dispatch_binding_id), True
    store.publish_binding(expected)
    return store.load_binding(expected.dispatch_binding_id), False


def _select_or_publish_audit(
    store: ProductionDispatchStore,
    bundle: InputResolutionBundle,
    binding: DispatchBinding,
) -> tuple[DispatchBindingAudit, bool]:
    expected = audit_dispatch_binding_frozen(
        store.work_order_store,
        store.resolver_registry,
        store.binder_registry,
        bundle,
        binding,
    )
    if expected.status is not BindingAuditStatus.PASS:
        raise PreparationReceiptError("fresh Phase-34 binding audit is not PASS")
    expected_currentness = inspect_dispatch_binding_currentness(
        store.work_order_store,
        store.resolver_registry,
        store.binder_registry,
        bundle,
        binding,
        expected,
    )
    if expected_currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
        raise PreparationReceiptError(
            f"fresh Phase-34 binding is not CURRENT_READY: {expected_currentness.status.value}"
        )
    expected_semantic = _semantic_dict(expected, "binding_audit_id")
    current: list[DispatchBindingAudit] = []
    for audit_id in _enumerate_ids(
        store,
        "binding-audits",
        IdKind.DISPATCH_BINDING_AUDIT,
    ):
        audit = store.load_audit(audit_id)
        if audit.dispatch_binding_id != binding.dispatch_binding_id:
            continue
        currentness = inspect_dispatch_binding_currentness(
            store.work_order_store,
            store.resolver_registry,
            store.binder_registry,
            bundle,
            binding,
            audit,
        )
        if currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
            continue
        if _semantic_dict(audit, "binding_audit_id") != expected_semantic:
            raise PreparationReceiptError(
                "multiple current binding-audit semantics exist for chosen dispatch binding"
            )
        current.append(audit)
    if current:
        return min(current, key=lambda value: value.binding_audit_id), True
    store.publish_audit(expected)
    return store.load_audit(expected.binding_audit_id), False


def _checkpoint_preparation_bound(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
    store: ProductionDispatchStore,
    bundle: InputResolutionBundle,
    binding: DispatchBinding,
    audit: DispatchBindingAudit,
) -> TaskPreparationReceipt:
    # Re-read and independently revalidate the entire chosen Phase-34 chain
    # immediately before the authoritative PREP READY transition.
    persisted_bundle = store.load_input_resolution(bundle.input_resolution_id)
    persisted_binding = store.load_binding(binding.dispatch_binding_id)
    persisted_audit = store.load_audit(audit.binding_audit_id)
    currentness = inspect_dispatch_binding_currentness(
        store.work_order_store,
        store.resolver_registry,
        store.binder_registry,
        persisted_bundle,
        persisted_binding,
        persisted_audit,
    )
    if currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
        raise PreparationReceiptError(
            f"chosen Phase-34 chain is not CURRENT_READY: {currentness.status.value}"
        )

    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt = _load_receipt_connection(conn, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.WORK_ORDER_AUDITED,
            expected_revision=expected_revision,
        )
        if (
            persisted_bundle.work_order_id != receipt.work_order_id
            or persisted_bundle.work_order_hash != receipt.work_order_hash
            or persisted_bundle.work_order_audit_id != receipt.work_order_audit_id
            or persisted_bundle.work_order_audit_hash != receipt.work_order_audit_hash
            or persisted_bundle.task_id != receipt.task_id
            or persisted_bundle.task_revision != receipt.ready_task_revision
            or persisted_bundle.task_content_hash != receipt.ready_task_hash
            or persisted_bundle.route_decision_id != receipt.route_decision_id
            or persisted_bundle.route_decision_hash != receipt.route_decision_hash
            or persisted_binding.input_resolution_id != persisted_bundle.input_resolution_id
            or persisted_binding.input_resolution_hash != persisted_bundle.content_hash
            or persisted_audit.dispatch_binding_id != persisted_binding.dispatch_binding_id
            or persisted_audit.dispatch_binding_hash != persisted_binding.content_hash
        ):
            raise PreparationReceiptError(
                "chosen Phase-34 chain does not exactly continue durable PREP authority"
            )
        new_revision = receipt.revision + 1
        cursor = conn.execute(
            """UPDATE task_preparations
               SET input_resolution_id = ?, input_resolution_hash = ?,
                   dispatch_binding_id = ?, dispatch_binding_hash = ?,
                   binding_audit_id = ?, binding_audit_hash = ?,
                   stage = 'BOUND', status = 'READY',
                   revision = ?, updated_at = ?, terminal_reason = NULL
               WHERE preparation_id = ? AND status = 'ACTIVE'
                 AND stage = 'WORK_ORDER_AUDITED' AND revision = ?""",
            (
                persisted_bundle.input_resolution_id,
                persisted_bundle.content_hash,
                persisted_binding.dispatch_binding_id,
                persisted_binding.content_hash,
                persisted_audit.binding_audit_id,
                persisted_audit.content_hash,
                new_revision,
                now,
                receipt.preparation_id,
                receipt.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision("PREP changed during Phase-34 READY checkpoint")
        return _load_receipt_connection(conn, preparation_id)


def _validate_ready_checkpoint(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
) -> tuple[InputResolutionBundle, DispatchBinding, DispatchBindingAudit]:
    _, _, store, _, _, _, _ = _build_stores(runtime, receipt)
    if not receipt.input_resolution_id or not receipt.dispatch_binding_id or not receipt.binding_audit_id:
        raise PreparationReceiptError("READY PREP lacks exact Phase-34 IDs")
    bundle = store.load_input_resolution(receipt.input_resolution_id)
    binding = store.load_binding(receipt.dispatch_binding_id)
    audit = store.load_audit(receipt.binding_audit_id)
    if (
        bundle.content_hash != receipt.input_resolution_hash
        or binding.content_hash != receipt.dispatch_binding_hash
        or audit.content_hash != receipt.binding_audit_hash
    ):
        raise PreparationReceiptError("READY PREP Phase-34 hashes drifted")
    currentness = inspect_dispatch_binding_currentness(
        store.work_order_store,
        store.resolver_registry,
        store.binder_registry,
        bundle,
        binding,
        audit,
    )
    if currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
        raise PreparationReceiptError(
            f"READY PREP Phase-34 chain is not CURRENT_READY: {currentness.status.value}"
        )
    return bundle, binding, audit


def finalize_preparation_phase34(
    runtime: OriginForgeRuntime,
    preparation_id: str,
) -> PreparationPhase34FinalizeResult:
    """Create/reuse exact Phase-34 authority, mark PREP READY, then stop.

    This function has no model, claim, execution, retry, fallback-Task, or daemon
    authority. Crash-created immutable INRES/DISPBIND/BINDAUD artifacts are
    boundedly enumerated and independently reconstructed before reuse.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    receipt = read_preparation_receipt(runtime, preparation_id)
    if receipt.status is PreparationStatus.READY and receipt.stage is PreparationStage.BOUND:
        try:
            bundle, binding, audit = _validate_ready_checkpoint(runtime, receipt)
        except Exception as exc:
            return PreparationPhase34FinalizeResult(
                PreparationPhase34FinalizeStatus.INVALID_AUTHORITY,
                preparation_id,
                receipt,
                None,
                None,
                None,
                False,
                False,
                False,
                _detail(exc),
            )
        return PreparationPhase34FinalizeResult(
            PreparationPhase34FinalizeStatus.ALREADY_READY,
            preparation_id,
            receipt,
            bundle,
            binding,
            audit,
            True,
            True,
            True,
            None,
        )
    if (
        receipt.status is not PreparationStatus.ACTIVE
        or receipt.stage is not PreparationStage.WORK_ORDER_AUDITED
    ):
        return PreparationPhase34FinalizeResult(
            PreparationPhase34FinalizeStatus.INVALID_STATE,
            preparation_id,
            receipt,
            None,
            None,
            None,
            False,
            False,
            False,
            f"PREP must be ACTIVE/WORK_ORDER_AUDITED, got {receipt.status.value}/{receipt.stage.value}",
        )

    try:
        _, _, store, _, _, _, _ = _build_stores(runtime, receipt)
        bundle, reused_bundle = _select_or_publish_bundle(
            store,
            receipt.work_order_id,
            receipt.work_order_audit_id,
        )
        binding, reused_binding = _select_or_publish_binding(store, bundle)
        audit, reused_audit = _select_or_publish_audit(store, bundle, binding)
        updated = _checkpoint_preparation_bound(
            runtime,
            preparation_id,
            receipt.revision,
            store,
            bundle,
            binding,
            audit,
        )
    except OverflowError as exc:
        return PreparationPhase34FinalizeResult(
            PreparationPhase34FinalizeStatus.LIMIT_EXCEEDED,
            preparation_id,
            read_preparation_receipt(runtime, preparation_id),
            None,
            None,
            None,
            False,
            False,
            False,
            str(exc),
        )
    except (
        PreparationReceiptError,
        ProductionPreparationPolicyStoreError,
        ProductionWorkOrderStoreError,
        ProductionDispatchStoreError,
        DispatchBindingError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        return PreparationPhase34FinalizeResult(
            PreparationPhase34FinalizeStatus.RECOVERY_REQUIRED,
            preparation_id,
            read_preparation_receipt(runtime, preparation_id),
            locals().get("bundle"),
            locals().get("binding"),
            locals().get("audit"),
            locals().get("reused_bundle", False),
            locals().get("reused_binding", False),
            locals().get("reused_audit", False),
            _detail(exc),
        )

    return PreparationPhase34FinalizeResult(
        PreparationPhase34FinalizeStatus.BOUND_READY,
        preparation_id,
        updated,
        bundle,
        binding,
        audit,
        reused_bundle,
        reused_binding,
        reused_audit,
        None,
    )
