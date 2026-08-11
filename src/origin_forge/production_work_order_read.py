from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ids import validate_id
from .production_capability_read import (
    ProductionCapabilityReadError,
    read_capability_catalog,
    read_capability_policy,
    read_capability_route,
)
from .production_capability_routing import (
    CapabilityRouteOutcome,
    CapabilityRoutingError,
    TaskRouteInput,
    resolve_route_input,
)
from .production_read_guard import (
    ProductionReadGuardError,
    existing_config_path,
    production_read_connection,
)
from .production_work_order_audit import (
    WorkOrderAudit,
    WorkOrderAuditStatus,
    WorkOrderCurrentness,
    WorkOrderCurrentnessStatus,
)
from .production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
    ProductionWorkOrderModelError,
    content_hash,
)
from .production_work_order_store import (
    _CATEGORY_KIND,
    _MAX_OBJECT_BYTES,
    _MAX_OBJECTS_PER_CATEGORY,
    _audit_from_dict,
    _canonical_store_bytes,
    _catalog_from_dict,
    _strict_object,
    _work_order_from_dict,
)
from .production_work_order_validators import (
    DispatchContractValidatorRegistry,
    DispatchValidatorError,
)
from .production_work_orders import ProductionWorkOrder
from .runtime import OriginForgeRuntime
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


class ProductionWorkOrderReadError(RuntimeError):
    pass


def _state_exists(runtime: OriginForgeRuntime) -> bool:
    state = runtime.state_dir
    config = state / "config.toml"
    if state.is_symlink():
        raise ProductionWorkOrderReadError(
            "Origin Forge state directory may not be a symlink"
        )
    if not state.exists():
        return False
    if not state.is_dir():
        raise ProductionWorkOrderReadError(
            "Origin Forge state path is not a directory"
        )
    if config.is_symlink():
        raise ProductionWorkOrderReadError("Origin Forge config may not be a symlink")
    return config.is_file()


def _existing_root(runtime: OriginForgeRuntime, *, required: bool) -> Path | None:
    try:
        existing_config_path(runtime.project_root)
    except ProductionReadGuardError as exc:
        raise ProductionWorkOrderReadError(str(exc)) from exc
    root = runtime.state_dir / "production-work-orders"
    if root.is_symlink():
        raise ProductionWorkOrderReadError(
            "production-work-orders root may not be a symlink"
        )
    if not root.exists():
        if required:
            raise ProductionWorkOrderReadError(
                "production-work-orders evidence root does not exist"
            )
        return None
    if not root.is_dir():
        raise ProductionWorkOrderReadError(
            "production-work-orders root is not a directory"
        )
    try:
        state = runtime.state_dir.resolve(strict=True)
        resolved = root.resolve(strict=True)
        resolved.relative_to(state)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionWorkOrderReadError(
            "production-work-orders root escaped protected state"
        ) from exc
    return resolved


def _category_dir(
    runtime: OriginForgeRuntime,
    category: str,
    *,
    required: bool,
) -> Path | None:
    if category not in _CATEGORY_KIND:
        raise ProductionWorkOrderReadError("unknown production work-order category")
    root = _existing_root(runtime, required=required)
    if root is None:
        return None
    directory = root / category
    if directory.is_symlink():
        raise ProductionWorkOrderReadError(
            f"{category} directory may not be a symlink"
        )
    if not directory.exists():
        if required:
            raise ProductionWorkOrderReadError(
                f"{category} evidence directory does not exist"
            )
        return None
    if not directory.is_dir():
        raise ProductionWorkOrderReadError(
            f"{category} evidence path is not a directory"
        )
    try:
        resolved = directory.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionWorkOrderReadError(
            f"{category} directory escaped protected root"
        ) from exc
    return resolved


def _object_path(runtime: OriginForgeRuntime, category: str, object_id: str) -> Path:
    kind = _CATEGORY_KIND.get(category)
    if kind is None or not validate_id(object_id, kind):
        raise ProductionWorkOrderReadError("invalid production work-order object ID")
    directory = _category_dir(runtime, category, required=True)
    assert directory is not None
    path = directory / f"{object_id}.json"
    if path.is_symlink():
        raise ProductionWorkOrderReadError(
            "production work-order object may not be a symlink"
        )
    if not path.is_file():
        raise ProductionWorkOrderReadError(
            "production work-order object does not exist"
        )
    try:
        root = (runtime.state_dir / "production-work-orders").resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionWorkOrderReadError(
            "production work-order object escaped protected root"
        ) from exc
    if resolved != path:
        raise ProductionWorkOrderReadError(
            "production work-order object path is aliased"
        )
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
            raise ProductionWorkOrderReadError(
                "production work-order object byte size is outside bounds"
            )
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except ProductionWorkOrderReadError:
        raise
    except Exception as exc:
        raise ProductionWorkOrderReadError(
            "production work-order object is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "object_type",
        "object_id",
        "content_hash",
        "payload",
    }:
        raise ProductionWorkOrderReadError(
            "production work-order envelope schema drifted"
        )
    if (
        envelope["schema_version"] != 1
        or envelope["object_type"] != category
        or envelope["object_id"] != object_id
        or not isinstance(envelope["payload"], dict)
    ):
        raise ProductionWorkOrderReadError(
            "production work-order envelope binding drifted"
        )
    try:
        if _canonical_store_bytes(envelope) != raw:
            raise ProductionWorkOrderReadError(
                "production work-order object bytes are not canonical"
            )
    except Exception as exc:
        if isinstance(exc, ProductionWorkOrderReadError):
            raise
        raise ProductionWorkOrderReadError(str(exc)) from exc
    return envelope


def _registry(value: DispatchContractValidatorRegistry) -> DispatchContractValidatorRegistry:
    if not isinstance(value, DispatchContractValidatorRegistry):
        raise TypeError("validator_registry must be a DispatchContractValidatorRegistry")
    return value


def read_dispatch_catalog(
    runtime: OriginForgeRuntime,
    catalog_id: str,
    validator_registry: DispatchContractValidatorRegistry,
) -> DispatchContractCatalog:
    _registry(validator_registry)
    envelope = _load_envelope(runtime, "dispatch-catalogs", catalog_id)
    try:
        catalog = _catalog_from_dict(envelope["payload"])
    except Exception as exc:
        raise ProductionWorkOrderReadError(
            "stored dispatch catalog failed validation"
        ) from exc
    if (
        catalog.dispatch_catalog_id != catalog_id
        or catalog.content_hash != envelope["content_hash"]
    ):
        raise ProductionWorkOrderReadError("dispatch catalog content hash drifted")
    try:
        phase32 = read_capability_catalog(runtime, catalog.phase32_catalog_id)
        catalog.validate_against(phase32)
        for contract in catalog.contracts:
            validator_registry.validate_contract(contract)
    except (
        ProductionCapabilityReadError,
        ProductionWorkOrderModelError,
        DispatchValidatorError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionWorkOrderReadError(
            "dispatch catalog frozen authority relation drifted"
        ) from exc
    return catalog


def _validate_work_order_relations(
    runtime: OriginForgeRuntime,
    validator_registry: DispatchContractValidatorRegistry,
    work_order: ProductionWorkOrder,
) -> DispatchContract:
    try:
        route = read_capability_route(runtime, work_order.route_decision_id)
        if route.content_hash != work_order.route_decision_hash:
            raise ProductionWorkOrderReadError("WorkOrder route hash drifted")
        resolution = route.resolution
        if resolution.outcome is not CapabilityRouteOutcome.ROUTABLE:
            raise ProductionWorkOrderReadError("WorkOrder frozen route is not ROUTABLE")
        route_input = resolution.route_input
        if (
            work_order.task_id != route_input.task_id
            or work_order.task_revision != route_input.task_revision
            or work_order.task_content_hash != route_input.task_content_hash
            or work_order.flow_id != route_input.flow_id
            or work_order.selected_adapter_id != resolution.selected_adapter_id
            or work_order.selected_adapter_fingerprint
            != resolution.selected_adapter_fingerprint
        ):
            raise ProductionWorkOrderReadError(
                "WorkOrder frozen Task/adapter binding drifted"
            )
        catalog = read_dispatch_catalog(
            runtime,
            work_order.dispatch_catalog_id,
            validator_registry,
        )
        if (
            catalog.content_hash != work_order.dispatch_catalog_hash
            or catalog.phase32_catalog_id != resolution.catalog_id
            or catalog.phase32_catalog_hash != resolution.catalog_hash
        ):
            raise ProductionWorkOrderReadError(
                "WorkOrder dispatch catalog binding drifted"
            )
        contract = catalog.contract_for_adapter(work_order.selected_adapter_id)
        if (
            contract.contract_id != work_order.dispatch_contract_id
            or contract.content_hash != work_order.dispatch_contract_hash
            or contract.adapter_fingerprint != work_order.selected_adapter_fingerprint
        ):
            raise ProductionWorkOrderReadError(
                "WorkOrder dispatch contract binding drifted"
            )
        normalized = validator_registry.validate_payload(
            contract,
            work_order.payload,
            work_order.input_refs,
        )
        if normalized != work_order.payload:
            raise ProductionWorkOrderReadError(
                "WorkOrder payload is not canonical validator output"
            )
        return contract
    except ProductionWorkOrderReadError:
        raise
    except (
        ProductionCapabilityReadError,
        ProductionWorkOrderModelError,
        DispatchValidatorError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionWorkOrderReadError(
            "WorkOrder frozen relation failed revalidation"
        ) from exc


def read_work_order(
    runtime: OriginForgeRuntime,
    work_order_id: str,
    validator_registry: DispatchContractValidatorRegistry,
) -> ProductionWorkOrder:
    _registry(validator_registry)
    envelope = _load_envelope(runtime, "work-orders", work_order_id)
    try:
        work_order = _work_order_from_dict(envelope["payload"])
    except Exception as exc:
        raise ProductionWorkOrderReadError(
            "stored WorkOrder failed validation"
        ) from exc
    if (
        work_order.work_order_id != work_order_id
        or work_order.content_hash != envelope["content_hash"]
    ):
        raise ProductionWorkOrderReadError("WorkOrder content hash drifted")
    _validate_work_order_relations(runtime, validator_registry, work_order)
    return work_order


def read_work_order_audit(
    runtime: OriginForgeRuntime,
    audit_id: str,
    validator_registry: DispatchContractValidatorRegistry,
) -> WorkOrderAudit:
    _registry(validator_registry)
    envelope = _load_envelope(runtime, "audits", audit_id)
    try:
        audit = _audit_from_dict(envelope["payload"])
    except Exception as exc:
        raise ProductionWorkOrderReadError(
            "stored WorkOrder audit failed validation"
        ) from exc
    if (
        audit.work_order_audit_id != audit_id
        or audit.content_hash != envelope["content_hash"]
    ):
        raise ProductionWorkOrderReadError("WorkOrder audit content hash drifted")
    work_order = read_work_order(runtime, audit.work_order_id, validator_registry)
    contract = _validate_work_order_relations(
        runtime,
        validator_registry,
        work_order,
    )
    expected = WorkOrderAudit(
        work_order_audit_id=audit.work_order_audit_id,
        work_order_id=work_order.work_order_id,
        work_order_hash=work_order.content_hash,
        task_id=work_order.task_id,
        task_revision=work_order.task_revision,
        task_content_hash=work_order.task_content_hash,
        route_decision_id=work_order.route_decision_id,
        route_decision_hash=work_order.route_decision_hash,
        dispatch_catalog_id=work_order.dispatch_catalog_id,
        dispatch_catalog_hash=work_order.dispatch_catalog_hash,
        dispatch_contract_id=work_order.dispatch_contract_id,
        dispatch_contract_hash=work_order.dispatch_contract_hash,
        validator_id=contract.validator_id,
        validator_fingerprint=contract.validator_fingerprint,
        status=WorkOrderAuditStatus.PASS,
        normalized_payload_hash=content_hash(work_order.payload),
        failure_reason=None,
    )
    if expected.to_dict() != audit.to_dict():
        raise ProductionWorkOrderReadError(
            "WorkOrder audit does not independently recompute as PASS"
        )
    return audit


def inspect_work_order_currentness_readonly(
    runtime: OriginForgeRuntime,
    work_order_id: str,
    audit_id: str,
    validator_registry: DispatchContractValidatorRegistry,
) -> WorkOrderCurrentness:
    work_order = read_work_order(runtime, work_order_id, validator_registry)
    audit = read_work_order_audit(runtime, audit_id, validator_registry)
    if audit.work_order_id != work_order.work_order_id:
        raise ProductionWorkOrderReadError(
            "audit does not belong to requested WorkOrder"
        )
    historical_route = read_capability_route(runtime, work_order.route_decision_id)
    try:
        catalog = read_capability_catalog(runtime, historical_route.resolution.catalog_id)
        policy = read_capability_policy(runtime, historical_route.resolution.routing_policy_id)
        with production_read_connection(runtime) as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (work_order.task_id,),
            ).fetchone()
            if row is None:
                return WorkOrderCurrentness(
                    work_order.work_order_id,
                    audit.work_order_audit_id,
                    work_order.task_id,
                    WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
                    None,
                    "current Task no longer exists",
                )
            current_input = TaskRouteInput.from_row(row)
            current_resolution = resolve_route_input(current_input, catalog, policy)
            if (
                current_input.to_dict()
                != historical_route.resolution.route_input.to_dict()
                or current_resolution.to_dict()
                != historical_route.resolution.to_dict()
            ):
                return WorkOrderCurrentness(
                    work_order.work_order_id,
                    audit.work_order_audit_id,
                    work_order.task_id,
                    WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
                    None,
                    "current Phase-32 routing input/outcome no longer matches WorkOrder",
                )
            readiness = resolve_task_dependency_readiness_connection(
                conn,
                work_order.task_id,
            )
    except (
        ProductionCapabilityReadError,
        ProductionReadGuardError,
        CapabilityRoutingError,
        TaskReadinessError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return WorkOrderCurrentness(
            work_order.work_order_id,
            audit.work_order_audit_id,
            work_order.task_id,
            WorkOrderCurrentnessStatus.INVALID_DEPENDENCY_STATE,
            DependencyReadinessStatus.INVALID_DEPENDENCY_STATE,
            f"{type(exc).__name__}: {exc}",
        )

    mapping = {
        DependencyReadinessStatus.READY: WorkOrderCurrentnessStatus.CURRENT_READY,
        DependencyReadinessStatus.WAITING_ON_DEPENDENCIES: WorkOrderCurrentnessStatus.WAITING_ON_DEPENDENCIES,
        DependencyReadinessStatus.BLOCKED_BY_FAILED_DEPENDENCY: WorkOrderCurrentnessStatus.BLOCKED_BY_FAILED_DEPENDENCY,
        DependencyReadinessStatus.INVALID_DEPENDENCY_STATE: WorkOrderCurrentnessStatus.INVALID_DEPENDENCY_STATE,
        DependencyReadinessStatus.ACTIVE: WorkOrderCurrentnessStatus.ACTIVE,
        DependencyReadinessStatus.TERMINAL: WorkOrderCurrentnessStatus.TERMINAL,
    }
    return WorkOrderCurrentness(
        work_order.work_order_id,
        audit.work_order_audit_id,
        work_order.task_id,
        mapping[readiness.status],
        readiness.status,
        None,
    )


def work_order_read_status(runtime: OriginForgeRuntime) -> dict[str, object]:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _state_exists(runtime):
        return {
            "initialized": False,
            "evidence_root_present": False,
            "dispatch_catalogs": 0,
            "work_orders": 0,
            "audits": 0,
        }
    try:
        with production_read_connection(runtime):
            pass
    except ProductionReadGuardError as exc:
        raise ProductionWorkOrderReadError(str(exc)) from exc
    root = _existing_root(runtime, required=False)
    if root is None:
        return {
            "initialized": True,
            "evidence_root_present": False,
            "dispatch_catalogs": 0,
            "work_orders": 0,
            "audits": 0,
        }
    counts: dict[str, int] = {}
    for category in ("dispatch-catalogs", "work-orders", "audits"):
        directory = _category_dir(runtime, category, required=False)
        if directory is None:
            counts[category] = 0
            continue
        paths = tuple(directory.glob("*.json"))
        if len(paths) > _MAX_OBJECTS_PER_CATEGORY:
            raise ProductionWorkOrderReadError(
                f"{category} object-count limit exceeded"
            )
        if any(path.is_symlink() or not path.is_file() for path in paths):
            raise ProductionWorkOrderReadError(
                f"{category} contains invalid evidence entries"
            )
        counts[category] = len(paths)
    return {
        "initialized": True,
        "evidence_root_present": True,
        "dispatch_catalogs": counts["dispatch-catalogs"],
        "work_orders": counts["work-orders"],
        "audits": counts["audits"],
    }
