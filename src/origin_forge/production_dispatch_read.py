from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ids import validate_id
from .production_dispatch_binding import (
    DispatchBindingError,
    DispatchInputBinderRegistry,
    _binding_with_id,
    _frozen_binding_audit_matches,
)
from .production_dispatch_binding_models import (
    DispatchBinding,
    DispatchBindingAudit,
    DispatchBindingCurrentness,
    DispatchBindingCurrentnessStatus,
)
from .production_dispatch_resolvers import WorkOrderInputResolverRegistry
from .production_dispatch_store import (
    _CATEGORY_KIND,
    _MAX_OBJECT_BYTES,
    _MAX_OBJECTS_PER_CATEGORY,
    _audit_from_dict,
    _binding_from_dict,
    _bundle_from_dict,
    _canonical_store_bytes,
    _strict_object,
)
from .production_read_guard import ProductionReadGuardError, existing_config_path
from .production_work_order_audit import WorkOrderCurrentnessStatus
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_read import (
    ProductionWorkOrderReadError,
    inspect_work_order_currentness_readonly,
    read_work_order,
    read_work_order_audit,
)
from .runtime import OriginForgeRuntime


class ProductionDispatchReadError(RuntimeError):
    pass


def _state_exists(runtime: OriginForgeRuntime) -> bool:
    state = runtime.state_dir
    config = state / "config.toml"
    if state.is_symlink():
        raise ProductionDispatchReadError("Origin Forge state directory may not be a symlink")
    if not state.exists():
        return False
    if not state.is_dir():
        raise ProductionDispatchReadError("Origin Forge state path is not a directory")
    if config.is_symlink():
        raise ProductionDispatchReadError("Origin Forge config may not be a symlink")
    return config.is_file()


def _existing_root(runtime: OriginForgeRuntime, *, required: bool) -> Path | None:
    try:
        existing_config_path(runtime.project_root)
    except ProductionReadGuardError as exc:
        raise ProductionDispatchReadError(str(exc)) from exc
    root = runtime.state_dir / "production-dispatch-bindings"
    if root.is_symlink():
        raise ProductionDispatchReadError(
            "production-dispatch-bindings root may not be a symlink"
        )
    if not root.exists():
        if required:
            raise ProductionDispatchReadError(
                "production-dispatch-bindings evidence root does not exist"
            )
        return None
    if not root.is_dir():
        raise ProductionDispatchReadError(
            "production-dispatch-bindings root is not a directory"
        )
    try:
        state = runtime.state_dir.resolve(strict=True)
        resolved = root.resolve(strict=True)
        resolved.relative_to(state)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionDispatchReadError(
            "production-dispatch-bindings root escaped protected state"
        ) from exc
    return resolved


def _category_dir(
    runtime: OriginForgeRuntime,
    category: str,
    *,
    required: bool,
) -> Path | None:
    if category not in _CATEGORY_KIND:
        raise ProductionDispatchReadError("unknown production dispatch category")
    root = _existing_root(runtime, required=required)
    if root is None:
        return None
    directory = root / category
    if directory.is_symlink():
        raise ProductionDispatchReadError(f"{category} directory may not be a symlink")
    if not directory.exists():
        if required:
            raise ProductionDispatchReadError(f"{category} evidence directory does not exist")
        return None
    if not directory.is_dir():
        raise ProductionDispatchReadError(f"{category} evidence path is not a directory")
    try:
        resolved = directory.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionDispatchReadError(f"{category} directory escaped protected root") from exc
    return resolved


def _object_path(runtime: OriginForgeRuntime, category: str, object_id: str) -> Path:
    kind = _CATEGORY_KIND.get(category)
    if kind is None or not validate_id(object_id, kind):
        raise ProductionDispatchReadError("invalid production dispatch object ID")
    directory = _category_dir(runtime, category, required=True)
    assert directory is not None
    path = directory / f"{object_id}.json"
    if path.is_symlink():
        raise ProductionDispatchReadError("production dispatch object may not be a symlink")
    if not path.is_file():
        raise ProductionDispatchReadError("production dispatch object does not exist")
    try:
        root = (runtime.state_dir / "production-dispatch-bindings").resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionDispatchReadError(
            "production dispatch object escaped protected root"
        ) from exc
    if resolved != path:
        raise ProductionDispatchReadError("production dispatch object path is aliased")
    return path


def _load_envelope(
    runtime: OriginForgeRuntime,
    category: str,
    object_id: str,
) -> dict[str, Any]:
    path = _object_path(runtime, category, object_id)
    try:
        size = path.stat().st_size
        if size <= 0 or size > _MAX_OBJECT_BYTES:
            raise ProductionDispatchReadError(
                "production dispatch object byte size is outside bounds"
            )
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except ProductionDispatchReadError:
        raise
    except Exception as exc:
        raise ProductionDispatchReadError(
            "production dispatch object is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "object_type",
        "object_id",
        "content_hash",
        "payload",
    }:
        raise ProductionDispatchReadError("production dispatch envelope schema drifted")
    if (
        envelope["schema_version"] != 1
        or envelope["object_type"] != category
        or envelope["object_id"] != object_id
        or not isinstance(envelope["payload"], dict)
    ):
        raise ProductionDispatchReadError("production dispatch envelope binding drifted")
    if _canonical_store_bytes(envelope) != raw:
        raise ProductionDispatchReadError("production dispatch object bytes are not canonical")
    return envelope


def _validate_bundle_relation(
    runtime: OriginForgeRuntime,
    bundle,
) -> None:
    registry = build_builtin_dispatch_validator_registry()
    try:
        work_order = read_work_order(runtime, bundle.work_order_id, registry)
        work_order_audit = read_work_order_audit(runtime, bundle.work_order_audit_id, registry)
    except ProductionWorkOrderReadError as exc:
        raise ProductionDispatchReadError(
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
        raise ProductionDispatchReadError(
            "input resolution frozen relation does not match exact WorkOrder"
        )


def read_input_resolution(runtime: OriginForgeRuntime, bundle_id: str):
    envelope = _load_envelope(runtime, "input-resolutions", bundle_id)
    try:
        bundle = _bundle_from_dict(envelope["payload"])
    except Exception as exc:
        raise ProductionDispatchReadError(
            "stored input resolution failed validation"
        ) from exc
    if bundle.input_resolution_id != bundle_id or bundle.content_hash != envelope["content_hash"]:
        raise ProductionDispatchReadError("input resolution content hash drifted")
    _validate_bundle_relation(runtime, bundle)
    return bundle


def read_dispatch_binding(runtime: OriginForgeRuntime, binding_id: str) -> DispatchBinding:
    envelope = _load_envelope(runtime, "dispatch-bindings", binding_id)
    try:
        binding = _binding_from_dict(envelope["payload"])
    except Exception as exc:
        raise ProductionDispatchReadError("stored dispatch binding failed validation") from exc
    if binding.dispatch_binding_id != binding_id or binding.content_hash != envelope["content_hash"]:
        raise ProductionDispatchReadError("dispatch binding content hash drifted")
    bundle = read_input_resolution(runtime, binding.input_resolution_id)
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
        raise ProductionDispatchReadError(
            "dispatch binding frozen resolution relation drifted"
        )
    return binding


def read_dispatch_binding_audit(
    runtime: OriginForgeRuntime,
    audit_id: str,
) -> DispatchBindingAudit:
    envelope = _load_envelope(runtime, "binding-audits", audit_id)
    try:
        audit = _audit_from_dict(envelope["payload"])
    except Exception as exc:
        raise ProductionDispatchReadError(
            "stored binding audit failed validation"
        ) from exc
    if audit.binding_audit_id != audit_id or audit.content_hash != envelope["content_hash"]:
        raise ProductionDispatchReadError("binding audit content hash drifted")
    bundle = read_input_resolution(runtime, audit.input_resolution_id)
    binding = read_dispatch_binding(runtime, audit.dispatch_binding_id)
    if not _frozen_binding_audit_matches(bundle, binding, audit):
        raise ProductionDispatchReadError(
            "stored binding audit failed frozen relation revalidation"
        )
    return audit


def inspect_dispatch_binding_currentness_readonly(
    runtime: OriginForgeRuntime,
    bundle_id: str,
    binding_id: str,
    audit_id: str,
    resolver_registry: WorkOrderInputResolverRegistry,
    binder_registry: DispatchInputBinderRegistry,
) -> DispatchBindingCurrentness:
    bundle = read_input_resolution(runtime, bundle_id)
    binding = read_dispatch_binding(runtime, binding_id)
    audit = read_dispatch_binding_audit(runtime, audit_id)
    if (
        binding.input_resolution_id != bundle.input_resolution_id
        or audit.input_resolution_id != bundle.input_resolution_id
        or audit.dispatch_binding_id != binding.dispatch_binding_id
    ):
        raise ProductionDispatchReadError(
            "requested dispatch evidence objects do not form one frozen chain"
        )

    def result(status: DispatchBindingCurrentnessStatus, detail: str | None):
        return DispatchBindingCurrentness(
            binding.dispatch_binding_id,
            audit.binding_audit_id,
            binding.work_order_id,
            binding.task_id,
            status,
            detail,
        )

    if bundle.resolver_registry_fingerprint != resolver_registry.fingerprint:
        return result(
            DispatchBindingCurrentnessStatus.RESOLVER_DRIFT,
            "resolver registry fingerprint no longer matches frozen input resolution",
        )
    try:
        binder = binder_registry.binder_for(bundle)
    except (DispatchBindingError, TypeError, ValueError) as exc:
        return result(
            DispatchBindingCurrentnessStatus.BINDER_DRIFT,
            f"{type(exc).__name__}: {exc}",
        )
    if (
        binding.binder_id != binder.descriptor.binder_id
        or binding.binder_fingerprint != binder.descriptor.binder_fingerprint
        or binding.request_type_id != binder.descriptor.request_type_id
        or binding.request_schema_hash != binder.descriptor.request_schema_hash
    ):
        return result(
            DispatchBindingCurrentnessStatus.BINDER_DRIFT,
            "binding binder identity/schema no longer matches trusted registry",
        )
    if not _frozen_binding_audit_matches(bundle, binding, audit):
        return result(
            DispatchBindingCurrentnessStatus.INVALID_AUDIT,
            "binding audit does not match exact frozen relation",
        )

    registry = build_builtin_dispatch_validator_registry()
    try:
        work_currentness = inspect_work_order_currentness_readonly(
            runtime,
            bundle.work_order_id,
            bundle.work_order_audit_id,
            registry,
        )
    except ProductionWorkOrderReadError as exc:
        return result(
            DispatchBindingCurrentnessStatus.STALE_WORK_ORDER,
            f"{type(exc).__name__}: {exc}",
        )
    if work_currentness.status is not WorkOrderCurrentnessStatus.CURRENT_READY:
        if work_currentness.status in {
            WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
            WorkOrderCurrentnessStatus.INVALID_AUDIT,
        }:
            status = DispatchBindingCurrentnessStatus.STALE_WORK_ORDER
        else:
            status = DispatchBindingCurrentnessStatus.NOT_READY
        return result(status, f"WorkOrder currentness is {work_currentness.status.value}")

    if bundle.resolved_inputs:
        return result(
            DispatchBindingCurrentnessStatus.STALE_INPUT,
            "current read-only v1 binding eligibility supports only the proven zero-ref dispatch contract",
        )
    try:
        work_order = read_work_order(runtime, bundle.work_order_id, registry)
        expected = _binding_with_id(
            bundle,
            binder,
            binder.bind(work_order, bundle),
            binding.dispatch_binding_id,
        )
    except Exception as exc:
        return result(
            DispatchBindingCurrentnessStatus.BINDER_DRIFT,
            f"{type(exc).__name__}: {exc}",
        )
    if expected.to_dict() != binding.to_dict():
        return result(
            DispatchBindingCurrentnessStatus.INVALID_AUDIT,
            "binding request does not independently reconstruct from current trusted binder",
        )
    return result(DispatchBindingCurrentnessStatus.CURRENT_READY, None)


def _count_category(runtime: OriginForgeRuntime, category: str) -> int:
    directory = _category_dir(runtime, category, required=False)
    if directory is None:
        return 0
    count = 0
    for path in directory.iterdir():
        if path.is_symlink():
            raise ProductionDispatchReadError(
                "production dispatch category contains a symlink"
            )
        if not path.is_file() or path.suffix != ".json":
            raise ProductionDispatchReadError(
                "production dispatch category contains an undeclared entry"
            )
        count += 1
        if count > _MAX_OBJECTS_PER_CATEGORY:
            raise ProductionDispatchReadError(
                "production dispatch object-count limit exceeded"
            )
    return count


def production_dispatch_read_status(runtime: OriginForgeRuntime) -> dict[str, object]:
    if not _state_exists(runtime):
        return {
            "initialized": False,
            "evidence_root_present": False,
            "input_resolution_count": 0,
            "dispatch_binding_count": 0,
            "binding_audit_count": 0,
            "authority": "read-only",
        }
    root = _existing_root(runtime, required=False)
    return {
        "initialized": True,
        "evidence_root_present": root is not None,
        "input_resolution_count": _count_category(runtime, "input-resolutions") if root else 0,
        "dispatch_binding_count": _count_category(runtime, "dispatch-bindings") if root else 0,
        "binding_audit_count": _count_category(runtime, "binding-audits") if root else 0,
        "authority": "read-only",
    }
