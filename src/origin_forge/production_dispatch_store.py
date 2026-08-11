from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .ids import IdKind, validate_id
from .production_dispatch_binding import (
    DispatchBindingError,
    DispatchInputBinderRegistry,
    _binding_with_id,
    _frozen_binding_audit_matches,
    _require_bundle_revalidates,
)
from .production_dispatch_binding_models import (
    BindingAuditStatus,
    DispatchBinding,
    DispatchBindingAudit,
    DispatchBindingModelError,
)
from .production_dispatch_resolution_models import (
    DispatchResolutionModelError,
    InputResolutionBundle,
    ResolvedInputCurrentness,
    ResolvedWorkOrderInput,
)
from .production_dispatch_resolvers import WorkOrderInputResolverRegistry
from .production_work_order_models import (
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
)
from .production_work_order_store import (
    ProductionWorkOrderStore,
    ProductionWorkOrderStoreError,
)


_SCHEMA_VERSION = 1
_MAX_OBJECT_BYTES = 4 * 1024 * 1024
_MAX_OBJECTS_PER_CATEGORY = 10_000
_CATEGORY_KIND = {
    "input-resolutions": IdKind.INPUT_RESOLUTION_BUNDLE,
    "dispatch-bindings": IdKind.DISPATCH_BINDING,
    "binding-audits": IdKind.DISPATCH_BINDING_AUDIT,
}


class ProductionDispatchStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionDispatchStoreError(f"duplicate JSON key: {key}")
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
        raise ProductionDispatchStoreError(
            "production dispatch evidence is not canonical JSON"
        ) from exc
    if not data or len(data) > _MAX_OBJECT_BYTES:
        raise ProductionDispatchStoreError(
            "production dispatch evidence is outside byte bounds"
        )
    return data


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProductionDispatchStoreError(f"{label} schema drifted")
    return value


def _input_ref_from_dict(value: object) -> WorkOrderInputRef:
    raw = _exact_keys(
        value,
        {"ref_type", "ref_id", "content_hash", "role", "revision"},
        "WorkOrderInputRef",
    )
    try:
        return WorkOrderInputRef(
            WorkOrderRefType(raw["ref_type"]),
            raw["ref_id"],
            raw["content_hash"],
            raw["role"],
            raw["revision"],
        )
    except (ProductionWorkOrderModelError, TypeError, ValueError) as exc:
        raise ProductionDispatchStoreError(
            "stored WorkOrderInputRef failed validation"
        ) from exc


def _resolved_input_from_dict(value: object) -> ResolvedWorkOrderInput:
    raw = _exact_keys(
        value,
        {
            "original_ref",
            "resolver_id",
            "resolver_fingerprint",
            "source_object_type",
            "source_id",
            "source_content_hash",
            "source_revision",
            "resolution_class",
            "projection",
            "projection_hash",
            "currentness",
        },
        "ResolvedWorkOrderInput",
    )
    try:
        result = ResolvedWorkOrderInput(
            original_ref=_input_ref_from_dict(raw["original_ref"]),
            resolver_id=raw["resolver_id"],
            resolver_fingerprint=raw["resolver_fingerprint"],
            source_object_type=raw["source_object_type"],
            source_id=raw["source_id"],
            source_content_hash=raw["source_content_hash"],
            source_revision=raw["source_revision"],
            resolution_class=raw["resolution_class"],
            projection_json=canonical_bytes(raw["projection"]).decode("utf-8"),
            currentness=ResolvedInputCurrentness(raw["currentness"]),
        )
    except (
        DispatchResolutionModelError,
        ProductionDispatchStoreError,
        ProductionWorkOrderModelError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionDispatchStoreError(
            "stored ResolvedWorkOrderInput failed validation"
        ) from exc
    if result.to_dict() != raw:
        raise ProductionDispatchStoreError(
            "stored ResolvedWorkOrderInput derived fields drifted"
        )
    return result


def _bundle_from_dict(value: object) -> InputResolutionBundle:
    raw = _exact_keys(
        value,
        {
            "input_resolution_id",
            "work_order_id",
            "work_order_hash",
            "work_order_audit_id",
            "work_order_audit_hash",
            "task_id",
            "task_revision",
            "task_content_hash",
            "route_decision_id",
            "route_decision_hash",
            "selected_adapter_id",
            "selected_adapter_fingerprint",
            "dispatch_catalog_id",
            "dispatch_catalog_hash",
            "dispatch_contract_id",
            "dispatch_contract_hash",
            "resolver_registry_fingerprint",
            "resolved_inputs",
        },
        "InputResolutionBundle",
    )
    if not isinstance(raw["resolved_inputs"], list):
        raise ProductionDispatchStoreError("stored resolved_inputs must be a list")
    try:
        return InputResolutionBundle(
            input_resolution_id=raw["input_resolution_id"],
            work_order_id=raw["work_order_id"],
            work_order_hash=raw["work_order_hash"],
            work_order_audit_id=raw["work_order_audit_id"],
            work_order_audit_hash=raw["work_order_audit_hash"],
            task_id=raw["task_id"],
            task_revision=raw["task_revision"],
            task_content_hash=raw["task_content_hash"],
            route_decision_id=raw["route_decision_id"],
            route_decision_hash=raw["route_decision_hash"],
            selected_adapter_id=raw["selected_adapter_id"],
            selected_adapter_fingerprint=raw["selected_adapter_fingerprint"],
            dispatch_catalog_id=raw["dispatch_catalog_id"],
            dispatch_catalog_hash=raw["dispatch_catalog_hash"],
            dispatch_contract_id=raw["dispatch_contract_id"],
            dispatch_contract_hash=raw["dispatch_contract_hash"],
            resolver_registry_fingerprint=raw["resolver_registry_fingerprint"],
            resolved_inputs=tuple(
                _resolved_input_from_dict(item) for item in raw["resolved_inputs"]
            ),
        )
    except (DispatchResolutionModelError, TypeError, ValueError) as exc:
        raise ProductionDispatchStoreError(
            "stored InputResolutionBundle failed validation"
        ) from exc


def _binding_from_dict(value: object) -> DispatchBinding:
    raw = _exact_keys(
        value,
        {
            "dispatch_binding_id",
            "work_order_id",
            "work_order_hash",
            "work_order_audit_id",
            "work_order_audit_hash",
            "input_resolution_id",
            "input_resolution_hash",
            "task_id",
            "task_revision",
            "task_content_hash",
            "route_decision_id",
            "route_decision_hash",
            "selected_adapter_id",
            "selected_adapter_fingerprint",
            "dispatch_catalog_id",
            "dispatch_catalog_hash",
            "dispatch_contract_id",
            "dispatch_contract_hash",
            "binder_id",
            "binder_fingerprint",
            "request_type_id",
            "request_schema_hash",
            "request_projection",
            "request_content_hash",
        },
        "DispatchBinding",
    )
    try:
        result = DispatchBinding(
            dispatch_binding_id=raw["dispatch_binding_id"],
            work_order_id=raw["work_order_id"],
            work_order_hash=raw["work_order_hash"],
            work_order_audit_id=raw["work_order_audit_id"],
            work_order_audit_hash=raw["work_order_audit_hash"],
            input_resolution_id=raw["input_resolution_id"],
            input_resolution_hash=raw["input_resolution_hash"],
            task_id=raw["task_id"],
            task_revision=raw["task_revision"],
            task_content_hash=raw["task_content_hash"],
            route_decision_id=raw["route_decision_id"],
            route_decision_hash=raw["route_decision_hash"],
            selected_adapter_id=raw["selected_adapter_id"],
            selected_adapter_fingerprint=raw["selected_adapter_fingerprint"],
            dispatch_catalog_id=raw["dispatch_catalog_id"],
            dispatch_catalog_hash=raw["dispatch_catalog_hash"],
            dispatch_contract_id=raw["dispatch_contract_id"],
            dispatch_contract_hash=raw["dispatch_contract_hash"],
            binder_id=raw["binder_id"],
            binder_fingerprint=raw["binder_fingerprint"],
            request_type_id=raw["request_type_id"],
            request_schema_hash=raw["request_schema_hash"],
            request_projection_json=canonical_bytes(raw["request_projection"]).decode("utf-8"),
        )
    except (
        DispatchBindingModelError,
        ProductionWorkOrderModelError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionDispatchStoreError(
            "stored DispatchBinding failed validation"
        ) from exc
    if result.to_dict() != raw:
        raise ProductionDispatchStoreError(
            "stored DispatchBinding derived fields drifted"
        )
    return result


def _audit_from_dict(value: object) -> DispatchBindingAudit:
    raw = _exact_keys(
        value,
        {
            "binding_audit_id",
            "dispatch_binding_id",
            "dispatch_binding_hash",
            "input_resolution_id",
            "input_resolution_hash",
            "work_order_id",
            "work_order_hash",
            "work_order_audit_id",
            "work_order_audit_hash",
            "resolver_registry_fingerprint",
            "binder_id",
            "binder_fingerprint",
            "request_type_id",
            "request_schema_hash",
            "request_content_hash",
            "status",
            "failure_reason",
        },
        "DispatchBindingAudit",
    )
    try:
        return DispatchBindingAudit(
            binding_audit_id=raw["binding_audit_id"],
            dispatch_binding_id=raw["dispatch_binding_id"],
            dispatch_binding_hash=raw["dispatch_binding_hash"],
            input_resolution_id=raw["input_resolution_id"],
            input_resolution_hash=raw["input_resolution_hash"],
            work_order_id=raw["work_order_id"],
            work_order_hash=raw["work_order_hash"],
            work_order_audit_id=raw["work_order_audit_id"],
            work_order_audit_hash=raw["work_order_audit_hash"],
            resolver_registry_fingerprint=raw["resolver_registry_fingerprint"],
            binder_id=raw["binder_id"],
            binder_fingerprint=raw["binder_fingerprint"],
            request_type_id=raw["request_type_id"],
            request_schema_hash=raw["request_schema_hash"],
            request_content_hash=raw["request_content_hash"],
            status=BindingAuditStatus(raw["status"]),
            failure_reason=raw["failure_reason"],
        )
    except (DispatchBindingModelError, TypeError, ValueError) as exc:
        raise ProductionDispatchStoreError(
            "stored DispatchBindingAudit failed validation"
        ) from exc


class ProductionDispatchStore:
    """Protected no-overwrite persistence for trusted Phase-34 evidence."""

    def __init__(
        self,
        work_order_store: ProductionWorkOrderStore,
        resolver_registry: WorkOrderInputResolverRegistry,
        binder_registry: DispatchInputBinderRegistry,
    ):
        if not isinstance(work_order_store, ProductionWorkOrderStore):
            raise TypeError("work_order_store must be a ProductionWorkOrderStore")
        if not isinstance(resolver_registry, WorkOrderInputResolverRegistry):
            raise TypeError("resolver_registry must be a WorkOrderInputResolverRegistry")
        if not isinstance(binder_registry, DispatchInputBinderRegistry):
            raise TypeError("binder_registry must be a DispatchInputBinderRegistry")
        self.work_order_store = work_order_store
        self.runtime = work_order_store.runtime
        self.resolver_registry = resolver_registry
        self.binder_registry = binder_registry
        self.root = self.runtime.state_dir / "production-dispatch-bindings"

    def _ensure_root(self) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        if self.root.is_symlink():
            raise ProductionDispatchStoreError(
                "production-dispatch-bindings root may not be a symlink"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            root = self.root.resolve(strict=True)
            root.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionDispatchStoreError(
                "production-dispatch-bindings root escaped protected project state"
            ) from exc
        return root

    def _category_dir(self, category: str, *, create: bool) -> Path:
        if category not in _CATEGORY_KIND:
            raise ProductionDispatchStoreError("unknown production dispatch category")
        root = self._ensure_root()
        directory = root / category
        if directory.is_symlink():
            raise ProductionDispatchStoreError(
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
            raise ProductionDispatchStoreError(
                f"{category} directory escaped protected root"
            ) from exc
        return directory

    def _exact_path(self, category: str, object_id: str, *, require_file: bool) -> Path:
        kind = _CATEGORY_KIND.get(category)
        if kind is None or not validate_id(object_id, kind):
            raise ProductionDispatchStoreError("invalid production dispatch object ID")
        directory = self._category_dir(category, create=False)
        path = directory / f"{object_id}.json"
        if path.is_symlink():
            raise ProductionDispatchStoreError(
                "production dispatch object may not be a symlink"
            )
        if require_file and not path.is_file():
            raise ProductionDispatchStoreError(
                "production dispatch object does not exist"
            )
        if not path.exists():
            return path
        try:
            root = self.root.resolve(strict=True)
            expected = root / category / f"{object_id}.json"
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionDispatchStoreError(
                "production dispatch object escaped protected root"
            ) from exc
        if resolved != expected:
            raise ProductionDispatchStoreError(
                "production dispatch object path is aliased"
            )
        return path

    @staticmethod
    def _identity(category: str, value: object) -> tuple[str, str, dict[str, object]]:
        if category == "input-resolutions" and isinstance(value, InputResolutionBundle):
            return value.input_resolution_id, value.content_hash, value.to_dict()
        if category == "dispatch-bindings" and isinstance(value, DispatchBinding):
            return value.dispatch_binding_id, value.content_hash, value.to_dict()
        if category == "binding-audits" and isinstance(value, DispatchBindingAudit):
            return value.binding_audit_id, value.content_hash, value.to_dict()
        raise TypeError(f"object type does not belong in production-dispatch-bindings/{category}")

    def _publish(self, category: str, value: object) -> Path:
        directory = self._category_dir(category, create=True)
        object_id, object_hash, payload = self._identity(category, value)
        if not validate_id(object_id, _CATEGORY_KIND[category]):
            raise ProductionDispatchStoreError("object ID has wrong category prefix")
        if len(tuple(directory.glob("*.json"))) >= _MAX_OBJECTS_PER_CATEGORY:
            raise ProductionDispatchStoreError(f"{category} object-count limit reached")
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
            raise ProductionDispatchStoreError("production dispatch object already exists")
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ProductionDispatchStoreError(
                "production dispatch object already exists"
            ) from exc
        return self._exact_path(category, object_id, require_file=True)

    def _load_envelope(self, category: str, object_id: str) -> dict[str, Any]:
        path = self._exact_path(category, object_id, require_file=True)
        try:
            size = path.stat().st_size
            if size <= 0 or size > _MAX_OBJECT_BYTES:
                raise ProductionDispatchStoreError(
                    "production dispatch object byte size is outside bounds"
                )
            raw = path.read_bytes()
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except ProductionDispatchStoreError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionDispatchStoreError(
                "production dispatch object is not strict UTF-8 JSON"
            ) from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "object_type",
            "object_id",
            "content_hash",
            "payload",
        }:
            raise ProductionDispatchStoreError(
                "production dispatch envelope schema drifted"
            )
        if (
            envelope["schema_version"] != _SCHEMA_VERSION
            or envelope["object_type"] != category
            or envelope["object_id"] != object_id
            or not isinstance(envelope["payload"], dict)
        ):
            raise ProductionDispatchStoreError(
                "production dispatch envelope binding drifted"
            )
        if _canonical_store_bytes(envelope) != raw:
            raise ProductionDispatchStoreError(
                "production dispatch object bytes are not canonical"
            )
        return envelope

    def publish_input_resolution(self, bundle: InputResolutionBundle) -> Path:
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        try:
            _require_bundle_revalidates(
                self.work_order_store,
                self.resolver_registry,
                bundle,
            )
        except (
            DispatchBindingError,
            ProductionWorkOrderStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise ProductionDispatchStoreError(
                "input resolution failed independent source/WorkOrder revalidation"
            ) from exc
        return self._publish("input-resolutions", bundle)

    def load_input_resolution(self, bundle_id: str) -> InputResolutionBundle:
        envelope = self._load_envelope("input-resolutions", bundle_id)
        bundle = _bundle_from_dict(envelope["payload"])
        if (
            bundle.input_resolution_id != bundle_id
            or bundle.content_hash != envelope["content_hash"]
        ):
            raise ProductionDispatchStoreError("input resolution content hash drifted")
        try:
            work_order = self.work_order_store.load_work_order(bundle.work_order_id)
            work_order_audit = self.work_order_store.load_audit(bundle.work_order_audit_id)
        except ProductionWorkOrderStoreError as exc:
            raise ProductionDispatchStoreError(
                "input resolution frozen WorkOrder relation drifted"
            ) from exc
        if (
            work_order.content_hash != bundle.work_order_hash
            or work_order_audit.content_hash != bundle.work_order_audit_hash
            or work_order_audit.work_order_id != work_order.work_order_id
            or bundle.task_id != work_order.task_id
            or bundle.task_revision != work_order.task_revision
            or bundle.task_content_hash != work_order.task_content_hash
            or bundle.route_decision_id != work_order.route_decision_id
            or bundle.route_decision_hash != work_order.route_decision_hash
            or bundle.selected_adapter_id != work_order.selected_adapter_id
            or bundle.selected_adapter_fingerprint != work_order.selected_adapter_fingerprint
            or bundle.dispatch_catalog_id != work_order.dispatch_catalog_id
            or bundle.dispatch_catalog_hash != work_order.dispatch_catalog_hash
            or bundle.dispatch_contract_id != work_order.dispatch_contract_id
            or bundle.dispatch_contract_hash != work_order.dispatch_contract_hash
        ):
            raise ProductionDispatchStoreError(
                "input resolution frozen relation does not match exact WorkOrder"
            )
        return bundle

    def publish_binding(self, binding: DispatchBinding) -> Path:
        if not isinstance(binding, DispatchBinding):
            raise TypeError("binding must be a DispatchBinding")
        bundle = self.load_input_resolution(binding.input_resolution_id)
        try:
            work_order = _require_bundle_revalidates(
                self.work_order_store,
                self.resolver_registry,
                bundle,
            )
            binder = self.binder_registry.binder_for(bundle)
            expected = _binding_with_id(
                bundle,
                binder,
                binder.bind(work_order, bundle),
                binding.dispatch_binding_id,
            )
        except (
            DispatchBindingError,
            DispatchBindingModelError,
            ProductionWorkOrderStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise ProductionDispatchStoreError(
                "dispatch binding failed independent trusted-binder reconstruction"
            ) from exc
        if expected.to_dict() != binding.to_dict():
            raise ProductionDispatchStoreError(
                "dispatch binding does not independently reconstruct"
            )
        return self._publish("dispatch-bindings", binding)

    def load_binding(self, binding_id: str) -> DispatchBinding:
        envelope = self._load_envelope("dispatch-bindings", binding_id)
        binding = _binding_from_dict(envelope["payload"])
        if (
            binding.dispatch_binding_id != binding_id
            or binding.content_hash != envelope["content_hash"]
        ):
            raise ProductionDispatchStoreError("dispatch binding content hash drifted")
        bundle = self.load_input_resolution(binding.input_resolution_id)
        if (
            binding.input_resolution_hash != bundle.content_hash
            or binding.work_order_id != bundle.work_order_id
            or binding.work_order_hash != bundle.work_order_hash
            or binding.work_order_audit_id != bundle.work_order_audit_id
            or binding.work_order_audit_hash != bundle.work_order_audit_hash
            or binding.task_id != bundle.task_id
            or binding.task_revision != bundle.task_revision
            or binding.task_content_hash != bundle.task_content_hash
            or binding.route_decision_id != bundle.route_decision_id
            or binding.route_decision_hash != bundle.route_decision_hash
            or binding.selected_adapter_id != bundle.selected_adapter_id
            or binding.selected_adapter_fingerprint != bundle.selected_adapter_fingerprint
            or binding.dispatch_catalog_id != bundle.dispatch_catalog_id
            or binding.dispatch_catalog_hash != bundle.dispatch_catalog_hash
            or binding.dispatch_contract_id != bundle.dispatch_contract_id
            or binding.dispatch_contract_hash != bundle.dispatch_contract_hash
        ):
            raise ProductionDispatchStoreError(
                "dispatch binding frozen resolution relation drifted"
            )
        return binding

    def publish_audit(self, audit: DispatchBindingAudit) -> Path:
        if not isinstance(audit, DispatchBindingAudit):
            raise TypeError("audit must be a DispatchBindingAudit")
        bundle = self.load_input_resolution(audit.input_resolution_id)
        binding = self.load_binding(audit.dispatch_binding_id)
        if not _frozen_binding_audit_matches(bundle, binding, audit):
            raise ProductionDispatchStoreError(
                "binding audit does not match exact frozen bundle/binding relation"
            )
        if audit.status is not BindingAuditStatus.PASS:
            raise ProductionDispatchStoreError(
                "only independently passing binding audits enter trusted store"
            )
        try:
            work_order = _require_bundle_revalidates(
                self.work_order_store,
                self.resolver_registry,
                bundle,
            )
            binder = self.binder_registry.binder_for(bundle)
            expected_binding = _binding_with_id(
                bundle,
                binder,
                binder.bind(work_order, bundle),
                binding.dispatch_binding_id,
            )
        except (
            DispatchBindingError,
            DispatchBindingModelError,
            ProductionWorkOrderStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise ProductionDispatchStoreError(
                "binding audit failed independent live reconstruction before publication"
            ) from exc
        if expected_binding.to_dict() != binding.to_dict():
            raise ProductionDispatchStoreError(
                "binding audit cannot authorize a non-reconstructable request"
            )
        return self._publish("binding-audits", audit)

    def load_audit(self, audit_id: str) -> DispatchBindingAudit:
        envelope = self._load_envelope("binding-audits", audit_id)
        audit = _audit_from_dict(envelope["payload"])
        if (
            audit.binding_audit_id != audit_id
            or audit.content_hash != envelope["content_hash"]
        ):
            raise ProductionDispatchStoreError("binding audit content hash drifted")
        bundle = self.load_input_resolution(audit.input_resolution_id)
        binding = self.load_binding(audit.dispatch_binding_id)
        if not _frozen_binding_audit_matches(bundle, binding, audit):
            raise ProductionDispatchStoreError(
                "stored binding audit failed frozen relation revalidation"
            )
        return audit
