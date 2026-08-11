from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, new_id, validate_id
from .production_capability_routing import (
    CapabilityRouteOutcome,
    CapabilityRoutingError,
    resolve_route_input,
)
from .production_capability_store import (
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_work_order_models import (
    DispatchContractCatalog,
    ProductionWorkOrderModelError,
    content_hash,
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
    resolve_task_dependency_readiness,
)


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FAILURE_CHARS = 2048


class WorkOrderAuditError(RuntimeError):
    pass


class WorkOrderAuditStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class WorkOrderCurrentnessStatus(StrEnum):
    CURRENT_READY = "CURRENT_READY"
    WAITING_ON_DEPENDENCIES = "WAITING_ON_DEPENDENCIES"
    BLOCKED_BY_FAILED_DEPENDENCY = "BLOCKED_BY_FAILED_DEPENDENCY"
    INVALID_DEPENDENCY_STATE = "INVALID_DEPENDENCY_STATE"
    ACTIVE = "ACTIVE"
    TERMINAL = "TERMINAL"
    STALE_TASK_ROUTE = "STALE_TASK_ROUTE"
    INVALID_AUDIT = "INVALID_AUDIT"


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise WorkOrderAuditError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise WorkOrderAuditError(f"invalid {label}: {value!r}")
    return value


def _failure_reason(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkOrderAuditError("failure_reason must be bounded text or null")
    normalized = value.strip()
    if len(normalized) > _MAX_FAILURE_CHARS:
        normalized = normalized[:_MAX_FAILURE_CHARS]
    return normalized


@dataclass(frozen=True)
class WorkOrderAudit:
    work_order_audit_id: str
    work_order_id: str
    work_order_hash: str
    task_id: str
    task_revision: int
    task_content_hash: str
    route_decision_id: str
    route_decision_hash: str
    dispatch_catalog_id: str
    dispatch_catalog_hash: str
    dispatch_contract_id: str
    dispatch_contract_hash: str
    validator_id: str | None
    validator_fingerprint: str | None
    status: WorkOrderAuditStatus
    normalized_payload_hash: str | None
    failure_reason: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.work_order_audit_id, IdKind.WORK_ORDER_AUDIT):
            raise WorkOrderAuditError("work_order_audit_id must be a WORKAUD ID")
        if not validate_id(self.work_order_id, IdKind.PRODUCTION_WORK_ORDER):
            raise WorkOrderAuditError("work_order_id must be a WORKORD ID")
        if not validate_id(self.task_id, IdKind.TASK):
            raise WorkOrderAuditError("task_id must be a TASK ID")
        if not validate_id(
            self.route_decision_id, IdKind.CAPABILITY_ROUTE_DECISION
        ):
            raise WorkOrderAuditError("route_decision_id must be a CAPROUTE ID")
        if not validate_id(
            self.dispatch_catalog_id, IdKind.DISPATCH_CONTRACT_CATALOG
        ):
            raise WorkOrderAuditError("dispatch_catalog_id must be a DISPCAT ID")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise WorkOrderAuditError("task_revision must be a non-negative integer")
        for value, label in (
            (self.work_order_hash, "work_order_hash"),
            (self.task_content_hash, "task_content_hash"),
            (self.route_decision_hash, "route_decision_hash"),
            (self.dispatch_catalog_hash, "dispatch_catalog_hash"),
            (self.dispatch_contract_hash, "dispatch_contract_hash"),
        ):
            _sha256(value, label)
        object.__setattr__(
            self,
            "dispatch_contract_id",
            _token(self.dispatch_contract_id, "dispatch_contract_id"),
        )
        if not isinstance(self.status, WorkOrderAuditStatus):
            raise WorkOrderAuditError("status must be a WorkOrderAuditStatus")
        if self.validator_id is not None:
            object.__setattr__(
                self, "validator_id", _token(self.validator_id, "validator_id")
            )
        if self.validator_fingerprint is not None:
            _sha256(self.validator_fingerprint, "validator_fingerprint")
        if self.normalized_payload_hash is not None:
            _sha256(self.normalized_payload_hash, "normalized_payload_hash")
        object.__setattr__(self, "failure_reason", _failure_reason(self.failure_reason))
        if self.status is WorkOrderAuditStatus.PASS:
            if (
                self.validator_id is None
                or self.validator_fingerprint is None
                or self.normalized_payload_hash is None
                or self.failure_reason is not None
            ):
                raise WorkOrderAuditError(
                    "PASS audit requires validator/payload evidence and no failure_reason"
                )
        elif self.failure_reason is None:
            raise WorkOrderAuditError("FAIL audit requires failure_reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "work_order_audit_id": self.work_order_audit_id,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "route_decision_id": self.route_decision_id,
            "route_decision_hash": self.route_decision_hash,
            "dispatch_catalog_id": self.dispatch_catalog_id,
            "dispatch_catalog_hash": self.dispatch_catalog_hash,
            "dispatch_contract_id": self.dispatch_contract_id,
            "dispatch_contract_hash": self.dispatch_contract_hash,
            "validator_id": self.validator_id,
            "validator_fingerprint": self.validator_fingerprint,
            "status": self.status.value,
            "normalized_payload_hash": self.normalized_payload_hash,
            "failure_reason": self.failure_reason,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class WorkOrderCurrentness:
    work_order_id: str
    work_order_audit_id: str
    task_id: str
    status: WorkOrderCurrentnessStatus
    dependency_readiness_status: DependencyReadinessStatus | None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.work_order_id, IdKind.PRODUCTION_WORK_ORDER):
            raise WorkOrderAuditError("currentness work_order_id must be a WORKORD ID")
        if not validate_id(self.work_order_audit_id, IdKind.WORK_ORDER_AUDIT):
            raise WorkOrderAuditError("currentness audit ID must be a WORKAUD ID")
        if not validate_id(self.task_id, IdKind.TASK):
            raise WorkOrderAuditError("currentness task_id must be a TASK ID")
        if not isinstance(self.status, WorkOrderCurrentnessStatus):
            raise WorkOrderAuditError("currentness status is invalid")
        if self.dependency_readiness_status is not None and not isinstance(
            self.dependency_readiness_status, DependencyReadinessStatus
        ):
            raise WorkOrderAuditError("dependency readiness status is invalid")
        object.__setattr__(self, "detail", _failure_reason(self.detail))

    def to_dict(self) -> dict[str, object]:
        return {
            "work_order_id": self.work_order_id,
            "work_order_audit_id": self.work_order_audit_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "dependency_readiness_status": (
                None
                if self.dependency_readiness_status is None
                else self.dependency_readiness_status.value
            ),
            "detail": self.detail,
        }


def _evaluate_work_order_audit(
    capability_store: ProductionCapabilityStore,
    dispatch_catalog: DispatchContractCatalog,
    validator_registry: DispatchContractValidatorRegistry,
    work_order: ProductionWorkOrder,
    *,
    audit_id: str,
) -> WorkOrderAudit:
    validator_id: str | None = None
    validator_fingerprint: str | None = None
    normalized_payload_hash: str | None = None
    failure: str | None = None

    try:
        route = capability_store.load_route(work_order.route_decision_id)
        if route.content_hash != work_order.route_decision_hash:
            raise WorkOrderAuditError("WorkOrder route decision hash drifted")

        resolution = route.resolution
        phase32_catalog = capability_store.load_catalog(resolution.catalog_id)
        phase32_policy = capability_store.load_policy(resolution.routing_policy_id)
        expected_resolution = resolve_route_input(
            resolution.route_input,
            phase32_catalog,
            phase32_policy,
        )
        if expected_resolution.to_dict() != resolution.to_dict():
            raise WorkOrderAuditError(
                "Phase-32 route outcome does not match frozen routing inputs"
            )
        if resolution.outcome is not CapabilityRouteOutcome.ROUTABLE:
            raise WorkOrderAuditError("Phase-32 frozen route is not ROUTABLE")
        if not resolution.selected_adapter_id or not resolution.selected_adapter_fingerprint:
            raise WorkOrderAuditError("ROUTABLE route lacks selected adapter identity")

        route_input = resolution.route_input
        if (
            work_order.task_id != route_input.task_id
            or work_order.task_revision != route_input.task_revision
            or work_order.task_content_hash != route_input.task_content_hash
            or work_order.flow_id != route_input.flow_id
        ):
            raise WorkOrderAuditError("WorkOrder Task binding drifted from frozen route")
        if (
            work_order.selected_adapter_id != resolution.selected_adapter_id
            or work_order.selected_adapter_fingerprint
            != resolution.selected_adapter_fingerprint
        ):
            raise WorkOrderAuditError("WorkOrder selected adapter drifted from frozen route")

        dispatch_catalog.validate_against(phase32_catalog)
        if (
            work_order.dispatch_catalog_id != dispatch_catalog.dispatch_catalog_id
            or work_order.dispatch_catalog_hash != dispatch_catalog.content_hash
            or dispatch_catalog.phase32_catalog_id != resolution.catalog_id
            or dispatch_catalog.phase32_catalog_hash != resolution.catalog_hash
        ):
            raise WorkOrderAuditError("WorkOrder dispatch catalog binding drifted")
        try:
            selected_contract = dispatch_catalog.contract_for_adapter(
                resolution.selected_adapter_id
            )
        except KeyError as exc:
            raise WorkOrderAuditError(
                "dispatch catalog has no contract for frozen selected adapter"
            ) from exc
        if (
            selected_contract.contract_id != work_order.dispatch_contract_id
            or selected_contract.content_hash != work_order.dispatch_contract_hash
            or selected_contract.adapter_fingerprint
            != resolution.selected_adapter_fingerprint
        ):
            raise WorkOrderAuditError("WorkOrder dispatch contract binding drifted")

        validator = validator_registry.validate_contract(selected_contract)
        validator_id = validator.validator_id
        validator_fingerprint = validator.validator_fingerprint
        normalized = validator_registry.validate_payload(
            selected_contract,
            work_order.payload,
            work_order.input_refs,
        )
        if normalized != work_order.payload:
            raise WorkOrderAuditError(
                "WorkOrder payload is not the validator's canonical normalized payload"
            )
        normalized_payload_hash = content_hash(normalized)
    except (
        CapabilityRoutingError,
        DispatchValidatorError,
        ProductionCapabilityStoreError,
        ProductionWorkOrderModelError,
        WorkOrderAuditError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        failure = f"{type(exc).__name__}: {exc}"

    return WorkOrderAudit(
        work_order_audit_id=audit_id,
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
        validator_id=validator_id,
        validator_fingerprint=validator_fingerprint,
        status=(
            WorkOrderAuditStatus.PASS
            if failure is None
            else WorkOrderAuditStatus.FAIL
        ),
        normalized_payload_hash=normalized_payload_hash,
        failure_reason=failure,
    )


def audit_work_order_frozen(
    capability_store: ProductionCapabilityStore,
    dispatch_catalog: DispatchContractCatalog,
    validator_registry: DispatchContractValidatorRegistry,
    work_order: ProductionWorkOrder,
) -> WorkOrderAudit:
    """Independently audit frozen WorkOrder evidence without requiring live Task currentness."""

    if not isinstance(capability_store, ProductionCapabilityStore):
        raise TypeError("capability_store must be a ProductionCapabilityStore")
    if not isinstance(dispatch_catalog, DispatchContractCatalog):
        raise TypeError("dispatch_catalog must be a DispatchContractCatalog")
    if not isinstance(validator_registry, DispatchContractValidatorRegistry):
        raise TypeError("validator_registry must be a DispatchContractValidatorRegistry")
    if not isinstance(work_order, ProductionWorkOrder):
        raise TypeError("work_order must be a ProductionWorkOrder")
    return _evaluate_work_order_audit(
        capability_store,
        dispatch_catalog,
        validator_registry,
        work_order,
        audit_id=new_id(IdKind.WORK_ORDER_AUDIT),
    )


def _audit_revalidates(
    capability_store: ProductionCapabilityStore,
    dispatch_catalog: DispatchContractCatalog,
    validator_registry: DispatchContractValidatorRegistry,
    work_order: ProductionWorkOrder,
    audit: WorkOrderAudit,
) -> bool:
    expected = _evaluate_work_order_audit(
        capability_store,
        dispatch_catalog,
        validator_registry,
        work_order,
        audit_id=audit.work_order_audit_id,
    )
    return expected.to_dict() == audit.to_dict()


def inspect_work_order_currentness(
    runtime: OriginForgeRuntime,
    capability_store: ProductionCapabilityStore,
    dispatch_catalog: DispatchContractCatalog,
    validator_registry: DispatchContractValidatorRegistry,
    work_order: ProductionWorkOrder,
    audit: WorkOrderAudit,
) -> WorkOrderCurrentness:
    """Recheck current route + canonical Phase-31 dependency readiness without mutation."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if capability_store.runtime.project_root != runtime.project_root:
        raise WorkOrderAuditError("capability evidence belongs to a different project root")
    if not isinstance(audit, WorkOrderAudit):
        raise TypeError("audit must be a WorkOrderAudit")
    if not _audit_revalidates(
        capability_store,
        dispatch_catalog,
        validator_registry,
        work_order,
        audit,
    ) or audit.status is not WorkOrderAuditStatus.PASS:
        return WorkOrderCurrentness(
            work_order.work_order_id,
            audit.work_order_audit_id,
            work_order.task_id,
            WorkOrderCurrentnessStatus.INVALID_AUDIT,
            None,
            "WorkOrder audit does not independently revalidate as PASS",
        )

    try:
        current_route = capability_store.require_current_route(
            work_order.route_decision_id
        )
    except ProductionCapabilityStoreError as exc:
        return WorkOrderCurrentness(
            work_order.work_order_id,
            audit.work_order_audit_id,
            work_order.task_id,
            WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
            None,
            f"{type(exc).__name__}: {exc}",
        )
    if (
        current_route.content_hash != work_order.route_decision_hash
        or current_route.resolution.route_input.task_id != work_order.task_id
        or current_route.resolution.route_input.task_revision != work_order.task_revision
        or current_route.resolution.route_input.task_content_hash
        != work_order.task_content_hash
    ):
        return WorkOrderCurrentness(
            work_order.work_order_id,
            audit.work_order_audit_id,
            work_order.task_id,
            WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
            None,
            "current Phase-32 route no longer matches WorkOrder Task binding",
        )

    try:
        readiness = resolve_task_dependency_readiness(
            runtime.store,
            work_order.task_id,
        )
    except (TaskReadinessError, KeyError, TypeError, ValueError) as exc:
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
