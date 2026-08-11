from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .ids import IdKind, validate_id
from .production_capability_store import (
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_work_order_audit import (
    WorkOrderAudit,
    WorkOrderAuditError,
    WorkOrderAuditStatus,
    audit_work_order_frozen,
)
from .production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
)
from .production_work_order_validators import (
    DispatchContractValidatorRegistry,
    DispatchValidatorError,
)
from .production_work_orders import ProductionWorkOrder, ProductionWorkOrderError
from .runtime import OriginForgeRuntime


_SCHEMA_VERSION = 1
_MAX_OBJECT_BYTES = 3 * 1024 * 1024
_MAX_OBJECTS_PER_CATEGORY = 10_000
_CATEGORY_KIND = {
    "dispatch-catalogs": IdKind.DISPATCH_CONTRACT_CATALOG,
    "work-orders": IdKind.PRODUCTION_WORK_ORDER,
    "audits": IdKind.WORK_ORDER_AUDIT,
}


class ProductionWorkOrderStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionWorkOrderStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_store_bytes(value: object) -> bytes:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionWorkOrderStoreError(
            "production work-order evidence is not canonical JSON"
        ) from exc
    if not data or len(data) > _MAX_OBJECT_BYTES:
        raise ProductionWorkOrderStoreError(
            "production work-order evidence is outside byte bounds"
        )
    return data


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProductionWorkOrderStoreError(f"{label} schema drifted")
    return value


def _input_ref_from_dict(value: object) -> WorkOrderInputRef:
    raw = _exact_keys(
        value,
        {"ref_type", "ref_id", "content_hash", "role", "revision"},
        "WorkOrderInputRef",
    )
    try:
        return WorkOrderInputRef(
            ref_type=WorkOrderRefType(raw["ref_type"]),
            ref_id=raw["ref_id"],
            content_hash=raw["content_hash"],
            role=raw["role"],
            revision=raw["revision"],
        )
    except (ProductionWorkOrderModelError, TypeError, ValueError) as exc:
        raise ProductionWorkOrderStoreError(
            "stored WorkOrderInputRef failed validation"
        ) from exc


def _contract_from_dict(value: object) -> DispatchContract:
    raw = _exact_keys(
        value,
        {
            "contract_id",
            "contract_version",
            "adapter_id",
            "adapter_fingerprint",
            "validator_id",
            "validator_fingerprint",
            "payload_schema_id",
            "payload_schema_hash",
            "allowed_input_ref_types",
            "max_payload_bytes",
            "max_input_refs",
        },
        "DispatchContract",
    )
    if not isinstance(raw["allowed_input_ref_types"], list):
        raise ProductionWorkOrderStoreError(
            "stored DispatchContract ref types are invalid"
        )
    try:
        return DispatchContract(
            contract_id=raw["contract_id"],
            contract_version=raw["contract_version"],
            adapter_id=raw["adapter_id"],
            adapter_fingerprint=raw["adapter_fingerprint"],
            validator_id=raw["validator_id"],
            validator_fingerprint=raw["validator_fingerprint"],
            payload_schema_id=raw["payload_schema_id"],
            payload_schema_hash=raw["payload_schema_hash"],
            allowed_input_ref_types=tuple(
                WorkOrderRefType(item) for item in raw["allowed_input_ref_types"]
            ),
            max_payload_bytes=raw["max_payload_bytes"],
            max_input_refs=raw["max_input_refs"],
        )
    except (ProductionWorkOrderModelError, TypeError, ValueError) as exc:
        raise ProductionWorkOrderStoreError(
            "stored DispatchContract failed validation"
        ) from exc


def _catalog_from_dict(value: object) -> DispatchContractCatalog:
    raw = _exact_keys(
        value,
        {
            "dispatch_catalog_id",
            "phase32_catalog_id",
            "phase32_catalog_hash",
            "schema_version",
            "contracts",
        },
        "DispatchContractCatalog",
    )
    if not isinstance(raw["contracts"], list):
        raise ProductionWorkOrderStoreError("stored dispatch contracts are invalid")
    try:
        return DispatchContractCatalog(
            dispatch_catalog_id=raw["dispatch_catalog_id"],
            phase32_catalog_id=raw["phase32_catalog_id"],
            phase32_catalog_hash=raw["phase32_catalog_hash"],
            contracts=tuple(_contract_from_dict(item) for item in raw["contracts"]),
            schema_version=raw["schema_version"],
        )
    except (ProductionWorkOrderModelError, TypeError, ValueError) as exc:
        raise ProductionWorkOrderStoreError(
            "stored DispatchContractCatalog failed validation"
        ) from exc


def _work_order_from_dict(value: object) -> ProductionWorkOrder:
    raw = _exact_keys(
        value,
        {
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
        },
        "ProductionWorkOrder",
    )
    if not isinstance(raw["input_refs"], list) or not isinstance(raw["payload"], dict):
        raise ProductionWorkOrderStoreError("stored WorkOrder arrays/payload are invalid")
    try:
        return ProductionWorkOrder(
            work_order_id=raw["work_order_id"],
            task_id=raw["task_id"],
            task_revision=raw["task_revision"],
            task_content_hash=raw["task_content_hash"],
            flow_id=raw["flow_id"],
            route_decision_id=raw["route_decision_id"],
            route_decision_hash=raw["route_decision_hash"],
            selected_adapter_id=raw["selected_adapter_id"],
            selected_adapter_fingerprint=raw["selected_adapter_fingerprint"],
            dispatch_catalog_id=raw["dispatch_catalog_id"],
            dispatch_catalog_hash=raw["dispatch_catalog_hash"],
            dispatch_contract_id=raw["dispatch_contract_id"],
            dispatch_contract_hash=raw["dispatch_contract_hash"],
            input_refs=tuple(_input_ref_from_dict(item) for item in raw["input_refs"]),
            payload_json=canonical_bytes(raw["payload"]).decode("utf-8"),
        )
    except (ProductionWorkOrderError, ProductionWorkOrderModelError, TypeError, ValueError) as exc:
        raise ProductionWorkOrderStoreError(
            "stored ProductionWorkOrder failed validation"
        ) from exc


def _audit_from_dict(value: object) -> WorkOrderAudit:
    raw = _exact_keys(
        value,
        {
            "work_order_audit_id",
            "work_order_id",
            "work_order_hash",
            "task_id",
            "task_revision",
            "task_content_hash",
            "route_decision_id",
            "route_decision_hash",
            "dispatch_catalog_id",
            "dispatch_catalog_hash",
            "dispatch_contract_id",
            "dispatch_contract_hash",
            "validator_id",
            "validator_fingerprint",
            "status",
            "normalized_payload_hash",
            "failure_reason",
        },
        "WorkOrderAudit",
    )
    try:
        return WorkOrderAudit(
            work_order_audit_id=raw["work_order_audit_id"],
            work_order_id=raw["work_order_id"],
            work_order_hash=raw["work_order_hash"],
            task_id=raw["task_id"],
            task_revision=raw["task_revision"],
            task_content_hash=raw["task_content_hash"],
            route_decision_id=raw["route_decision_id"],
            route_decision_hash=raw["route_decision_hash"],
            dispatch_catalog_id=raw["dispatch_catalog_id"],
            dispatch_catalog_hash=raw["dispatch_catalog_hash"],
            dispatch_contract_id=raw["dispatch_contract_id"],
            dispatch_contract_hash=raw["dispatch_contract_hash"],
            validator_id=raw["validator_id"],
            validator_fingerprint=raw["validator_fingerprint"],
            status=WorkOrderAuditStatus(raw["status"]),
            normalized_payload_hash=raw["normalized_payload_hash"],
            failure_reason=raw["failure_reason"],
        )
    except (WorkOrderAuditError, TypeError, ValueError) as exc:
        raise ProductionWorkOrderStoreError(
            "stored WorkOrderAudit failed validation"
        ) from exc


def _expected_audit_dict(
    capability_store: ProductionCapabilityStore,
    dispatch_catalog: DispatchContractCatalog,
    validator_registry: DispatchContractValidatorRegistry,
    work_order: ProductionWorkOrder,
    audit_id: str,
) -> dict[str, object]:
    expected = audit_work_order_frozen(
        capability_store,
        dispatch_catalog,
        validator_registry,
        work_order,
    ).to_dict()
    expected["work_order_audit_id"] = audit_id
    return expected


class ProductionWorkOrderStore:
    """Protected immutable persistence for trusted Phase-33 frozen evidence."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        capability_store: ProductionCapabilityStore,
        validator_registry: DispatchContractValidatorRegistry,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(capability_store, ProductionCapabilityStore):
            raise TypeError("capability_store must be a ProductionCapabilityStore")
        if capability_store.runtime.project_root != runtime.project_root:
            raise ProductionWorkOrderStoreError(
                "capability store belongs to a different project root"
            )
        if not isinstance(validator_registry, DispatchContractValidatorRegistry):
            raise TypeError("validator_registry must be a DispatchContractValidatorRegistry")
        self.runtime = runtime
        self.capability_store = capability_store
        self.validator_registry = validator_registry
        self.root = runtime.state_dir / "production-work-orders"

    def _ensure_root(self) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        if self.root.is_symlink():
            raise ProductionWorkOrderStoreError(
                "production-work-orders root may not be a symlink"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            root = self.root.resolve(strict=True)
            root.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionWorkOrderStoreError(
                "production-work-orders root escaped protected project state"
            ) from exc
        return root

    def _category_dir(self, category: str, *, create: bool) -> Path:
        if category not in _CATEGORY_KIND:
            raise ProductionWorkOrderStoreError("unknown production work-order category")
        root = self._ensure_root()
        directory = root / category
        if directory.is_symlink():
            raise ProductionWorkOrderStoreError(
                f"{category} directory may not be a symlink"
            )
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.exists():
            return directory
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionWorkOrderStoreError(
                f"{category} directory escaped protected root"
            ) from exc
        return directory

    def _exact_path(self, category: str, object_id: str, *, require_file: bool) -> Path:
        kind = _CATEGORY_KIND.get(category)
        if kind is None or not validate_id(object_id, kind):
            raise ProductionWorkOrderStoreError("invalid production work-order object ID")
        directory = self._category_dir(category, create=False)
        path = directory / f"{object_id}.json"
        if path.is_symlink():
            raise ProductionWorkOrderStoreError(
                "production work-order object may not be a symlink"
            )
        if require_file and not path.is_file():
            raise ProductionWorkOrderStoreError(
                "production work-order object does not exist"
            )
        if not path.exists():
            return path
        try:
            root = self.root.resolve(strict=True)
            expected = root / category / f"{object_id}.json"
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionWorkOrderStoreError(
                "production work-order object escaped protected root"
            ) from exc
        if resolved != expected:
            raise ProductionWorkOrderStoreError(
                "production work-order object path is aliased"
            )
        return path

    @staticmethod
    def _identity(category: str, value: object) -> tuple[str, str, dict[str, object]]:
        if category == "dispatch-catalogs" and isinstance(
            value, DispatchContractCatalog
        ):
            return value.dispatch_catalog_id, value.content_hash, value.to_dict()
        if category == "work-orders" and isinstance(value, ProductionWorkOrder):
            return value.work_order_id, value.content_hash, value.to_dict()
        if category == "audits" and isinstance(value, WorkOrderAudit):
            return value.work_order_audit_id, value.content_hash, value.to_dict()
        raise TypeError(f"object type does not belong in production-work-orders/{category}")

    def _publish(self, category: str, value: object) -> Path:
        directory = self._category_dir(category, create=True)
        object_id, object_hash, payload = self._identity(category, value)
        if not validate_id(object_id, _CATEGORY_KIND[category]):
            raise ProductionWorkOrderStoreError("object ID has wrong category prefix")
        if len(tuple(directory.glob("*.json"))) >= _MAX_OBJECTS_PER_CATEGORY:
            raise ProductionWorkOrderStoreError(
                f"{category} object-count limit reached"
            )
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "object_type": category,
            "object_id": object_id,
            "content_hash": object_hash,
            "payload": payload,
        }
        data = _canonical_store_bytes(envelope)
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            raise ProductionWorkOrderStoreError(
                "production work-order object already exists"
            )
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ProductionWorkOrderStoreError(
                "production work-order object already exists"
            ) from exc
        return self._exact_path(category, object_id, require_file=True)

    def _load_envelope(self, category: str, object_id: str) -> dict[str, Any]:
        path = self._exact_path(category, object_id, require_file=True)
        try:
            size = path.stat().st_size
            if size <= 0 or size > _MAX_OBJECT_BYTES:
                raise ProductionWorkOrderStoreError(
                    "production work-order object byte size is outside bounds"
                )
            raw = path.read_bytes()
            envelope = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_strict_object
            )
        except ProductionWorkOrderStoreError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionWorkOrderStoreError(
                "production work-order object is not strict UTF-8 JSON"
            ) from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "object_type",
            "object_id",
            "content_hash",
            "payload",
        }:
            raise ProductionWorkOrderStoreError(
                "production work-order envelope schema drifted"
            )
        if (
            envelope["schema_version"] != _SCHEMA_VERSION
            or envelope["object_type"] != category
            or envelope["object_id"] != object_id
            or not isinstance(envelope["payload"], dict)
        ):
            raise ProductionWorkOrderStoreError(
                "production work-order envelope binding drifted"
            )
        if _canonical_store_bytes(envelope) != raw:
            raise ProductionWorkOrderStoreError(
                "production work-order object bytes are not canonical"
            )
        return envelope

    def publish_dispatch_catalog(self, catalog: DispatchContractCatalog) -> Path:
        if not isinstance(catalog, DispatchContractCatalog):
            raise TypeError("catalog must be a DispatchContractCatalog")
        try:
            phase32 = self.capability_store.load_catalog(catalog.phase32_catalog_id)
            catalog.validate_against(phase32)
            for contract in catalog.contracts:
                self.validator_registry.validate_contract(contract)
        except (
            ProductionCapabilityStoreError,
            ProductionWorkOrderModelError,
            DispatchValidatorError,
        ) as exc:
            raise ProductionWorkOrderStoreError(
                "dispatch catalog failed frozen authority validation"
            ) from exc
        return self._publish("dispatch-catalogs", catalog)

    def load_dispatch_catalog(self, catalog_id: str) -> DispatchContractCatalog:
        envelope = self._load_envelope("dispatch-catalogs", catalog_id)
        catalog = _catalog_from_dict(envelope["payload"])
        if (
            catalog.dispatch_catalog_id != catalog_id
            or catalog.content_hash != envelope["content_hash"]
        ):
            raise ProductionWorkOrderStoreError("dispatch catalog content hash drifted")
        try:
            phase32 = self.capability_store.load_catalog(catalog.phase32_catalog_id)
            catalog.validate_against(phase32)
            for contract in catalog.contracts:
                self.validator_registry.validate_contract(contract)
        except (
            ProductionCapabilityStoreError,
            ProductionWorkOrderModelError,
            DispatchValidatorError,
        ) as exc:
            raise ProductionWorkOrderStoreError(
                "stored dispatch catalog relation drifted"
            ) from exc
        return catalog

    def publish_work_order(self, work_order: ProductionWorkOrder) -> Path:
        if not isinstance(work_order, ProductionWorkOrder):
            raise TypeError("work_order must be a ProductionWorkOrder")
        catalog = self.load_dispatch_catalog(work_order.dispatch_catalog_id)
        if catalog.content_hash != work_order.dispatch_catalog_hash:
            raise ProductionWorkOrderStoreError(
                "WorkOrder dispatch catalog hash does not match stored catalog"
            )
        audit = audit_work_order_frozen(
            self.capability_store,
            catalog,
            self.validator_registry,
            work_order,
        )
        if audit.status is not WorkOrderAuditStatus.PASS:
            raise ProductionWorkOrderStoreError(
                "WorkOrder failed frozen validation before publication"
            )
        return self._publish("work-orders", work_order)

    def load_work_order(self, work_order_id: str) -> ProductionWorkOrder:
        envelope = self._load_envelope("work-orders", work_order_id)
        work_order = _work_order_from_dict(envelope["payload"])
        if (
            work_order.work_order_id != work_order_id
            or work_order.content_hash != envelope["content_hash"]
        ):
            raise ProductionWorkOrderStoreError("WorkOrder content hash drifted")
        catalog = self.load_dispatch_catalog(work_order.dispatch_catalog_id)
        if catalog.content_hash != work_order.dispatch_catalog_hash:
            raise ProductionWorkOrderStoreError("WorkOrder dispatch catalog relation drifted")
        audit = audit_work_order_frozen(
            self.capability_store,
            catalog,
            self.validator_registry,
            work_order,
        )
        if audit.status is not WorkOrderAuditStatus.PASS:
            raise ProductionWorkOrderStoreError("stored WorkOrder failed frozen revalidation")
        return work_order

    def publish_audit(self, audit: WorkOrderAudit) -> Path:
        if not isinstance(audit, WorkOrderAudit):
            raise TypeError("audit must be a WorkOrderAudit")
        work_order = self.load_work_order(audit.work_order_id)
        catalog = self.load_dispatch_catalog(work_order.dispatch_catalog_id)
        expected = _expected_audit_dict(
            self.capability_store,
            catalog,
            self.validator_registry,
            work_order,
            audit.work_order_audit_id,
        )
        if expected != audit.to_dict():
            raise ProductionWorkOrderStoreError(
                "WorkOrder audit does not independently recompute"
            )
        return self._publish("audits", audit)

    def load_audit(self, audit_id: str) -> WorkOrderAudit:
        envelope = self._load_envelope("audits", audit_id)
        audit = _audit_from_dict(envelope["payload"])
        if (
            audit.work_order_audit_id != audit_id
            or audit.content_hash != envelope["content_hash"]
        ):
            raise ProductionWorkOrderStoreError("WorkOrder audit content hash drifted")
        work_order = self.load_work_order(audit.work_order_id)
        catalog = self.load_dispatch_catalog(work_order.dispatch_catalog_id)
        expected = _expected_audit_dict(
            self.capability_store,
            catalog,
            self.validator_registry,
            work_order,
            audit.work_order_audit_id,
        )
        if expected != audit.to_dict():
            raise ProductionWorkOrderStoreError(
                "stored WorkOrder audit failed frozen recomputation"
            )
        return audit
