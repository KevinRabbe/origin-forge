from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from .ids import IdKind, new_id, validate_id
from .production_capability_routing import CapabilityRouteOutcome
from .production_capability_store import (
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_work_order_models import (
    DispatchContractCatalog,
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    canonical_bytes,
    content_hash,
)
from .production_work_order_validators import (
    DispatchContractValidatorRegistry,
    DispatchValidatorError,
)
from .runtime import OriginForgeRuntime


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_INPUT_REFS = 128


class ProductionWorkOrderError(RuntimeError):
    pass


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ProductionWorkOrderError(f"invalid {label}: {value!r}")
    return value


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProductionWorkOrderError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _exact_revision(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ProductionWorkOrderError("task_revision must be a non-negative integer")
    return value


@dataclass(frozen=True)
class ProductionWorkOrder:
    work_order_id: str
    task_id: str
    task_revision: int
    task_content_hash: str
    flow_id: str
    route_decision_id: str
    route_decision_hash: str
    selected_adapter_id: str
    selected_adapter_fingerprint: str
    dispatch_catalog_id: str
    dispatch_catalog_hash: str
    dispatch_contract_id: str
    dispatch_contract_hash: str
    input_refs: tuple[WorkOrderInputRef, ...]
    payload_json: str

    def __post_init__(self) -> None:
        if not validate_id(self.work_order_id, IdKind.PRODUCTION_WORK_ORDER):
            raise ProductionWorkOrderError("work_order_id must be a WORKORD ID")
        if not validate_id(self.task_id, IdKind.TASK):
            raise ProductionWorkOrderError("task_id must be a TASK ID")
        if not validate_id(self.flow_id, IdKind.FLOW):
            raise ProductionWorkOrderError("flow_id must be a FLOW ID")
        if not validate_id(self.route_decision_id, IdKind.CAPABILITY_ROUTE_DECISION):
            raise ProductionWorkOrderError("route_decision_id must be a CAPROUTE ID")
        if not validate_id(
            self.dispatch_catalog_id, IdKind.DISPATCH_CONTRACT_CATALOG
        ):
            raise ProductionWorkOrderError("dispatch_catalog_id must be a DISPCAT ID")
        _exact_revision(self.task_revision)
        for value, label in (
            (self.task_content_hash, "task_content_hash"),
            (self.route_decision_hash, "route_decision_hash"),
            (self.selected_adapter_fingerprint, "selected_adapter_fingerprint"),
            (self.dispatch_catalog_hash, "dispatch_catalog_hash"),
            (self.dispatch_contract_hash, "dispatch_contract_hash"),
        ):
            _sha256(value, label)
        object.__setattr__(
            self,
            "selected_adapter_id",
            _token(self.selected_adapter_id, "selected_adapter_id"),
        )
        object.__setattr__(
            self,
            "dispatch_contract_id",
            _token(self.dispatch_contract_id, "dispatch_contract_id"),
        )

        refs = tuple(self.input_refs)
        if len(refs) > _MAX_INPUT_REFS or not all(
            isinstance(value, WorkOrderInputRef) for value in refs
        ):
            raise ProductionWorkOrderError("input_refs are outside bounds")
        identities = [
            (value.role, value.ref_type.value, value.ref_id, value.content_hash, value.revision)
            for value in refs
        ]
        if len(identities) != len(set(identities)):
            raise ProductionWorkOrderError("input_refs contain duplicates")
        object.__setattr__(
            self,
            "input_refs",
            tuple(
                sorted(
                    refs,
                    key=lambda value: (
                        value.role,
                        value.ref_type.value,
                        value.ref_id,
                        value.content_hash,
                        -1 if value.revision is None else value.revision,
                    ),
                )
            ),
        )

        if not isinstance(self.payload_json, str) or not self.payload_json:
            raise ProductionWorkOrderError("payload_json must be canonical JSON text")
        try:
            payload = json.loads(self.payload_json)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProductionWorkOrderError("payload_json is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProductionWorkOrderError("payload must decode to an object")
        try:
            expected = canonical_bytes(payload).decode("utf-8")
        except ProductionWorkOrderModelError as exc:
            raise ProductionWorkOrderError("payload is outside canonical bounds") from exc
        if expected != self.payload_json:
            raise ProductionWorkOrderError("payload_json is not canonical")
        try:
            canonical_bytes(self.to_dict())
        except ProductionWorkOrderModelError as exc:
            raise ProductionWorkOrderError("work order is outside canonical bounds") from exc

    @property
    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_json)
        assert isinstance(value, dict)
        return value

    @property
    def payload_hash(self) -> str:
        return content_hash(self.payload)

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "work_order_id": self.work_order_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "flow_id": self.flow_id,
            "route_decision_id": self.route_decision_id,
            "route_decision_hash": self.route_decision_hash,
            "selected_adapter_id": self.selected_adapter_id,
            "selected_adapter_fingerprint": self.selected_adapter_fingerprint,
            "dispatch_catalog_id": self.dispatch_catalog_id,
            "dispatch_catalog_hash": self.dispatch_catalog_hash,
            "dispatch_contract_id": self.dispatch_contract_id,
            "dispatch_contract_hash": self.dispatch_contract_hash,
            "input_refs": [value.to_dict() for value in self.input_refs],
            "payload": self.payload,
        }


def create_current_work_order(
    runtime: OriginForgeRuntime,
    capability_store: ProductionCapabilityStore,
    dispatch_catalog: DispatchContractCatalog,
    validator_registry: DispatchContractValidatorRegistry,
    route_decision_id: str,
    *,
    input_refs: Sequence[WorkOrderInputRef] = (),
    payload: dict[str, Any],
) -> ProductionWorkOrder:
    """Construct one immutable current WorkOrder without dispatching anything."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(capability_store, ProductionCapabilityStore):
        raise TypeError("capability_store must be a ProductionCapabilityStore")
    if capability_store.runtime.project_root != runtime.project_root:
        raise ProductionWorkOrderError(
            "capability route evidence belongs to a different project root"
        )
    if not isinstance(dispatch_catalog, DispatchContractCatalog):
        raise TypeError("dispatch_catalog must be a DispatchContractCatalog")
    if not isinstance(validator_registry, DispatchContractValidatorRegistry):
        raise TypeError("validator_registry must be a DispatchContractValidatorRegistry")

    try:
        route = capability_store.require_current_route(route_decision_id)
    except ProductionCapabilityStoreError as exc:
        raise ProductionWorkOrderError(
            "Phase-32 route is unavailable or stale"
        ) from exc
    resolution = route.resolution
    if resolution.outcome is not CapabilityRouteOutcome.ROUTABLE:
        raise ProductionWorkOrderError("Phase-32 route is not ROUTABLE")
    if not resolution.selected_adapter_id or not resolution.selected_adapter_fingerprint:
        raise ProductionWorkOrderError("ROUTABLE decision lacks selected adapter identity")

    try:
        phase32_catalog = capability_store.load_catalog(resolution.catalog_id)
        dispatch_catalog.validate_against(phase32_catalog)
    except (ProductionCapabilityStoreError, ProductionWorkOrderModelError) as exc:
        raise ProductionWorkOrderError(
            "dispatch catalog is not valid for the current Phase-32 catalog"
        ) from exc
    if (
        dispatch_catalog.phase32_catalog_id != resolution.catalog_id
        or dispatch_catalog.phase32_catalog_hash != resolution.catalog_hash
    ):
        raise ProductionWorkOrderError(
            "dispatch catalog does not bind the route's exact Phase-32 catalog"
        )

    try:
        contract = dispatch_catalog.contract_for_adapter(
            resolution.selected_adapter_id
        )
    except KeyError as exc:
        raise ProductionWorkOrderError(
            "dispatch catalog has no contract for selected adapter"
        ) from exc
    if contract.adapter_fingerprint != resolution.selected_adapter_fingerprint:
        raise ProductionWorkOrderError(
            "dispatch contract selected-adapter fingerprint drifted"
        )

    refs = tuple(input_refs)
    try:
        normalized_payload = validator_registry.validate_payload(
            contract,
            payload,
            refs,
        )
    except DispatchValidatorError as exc:
        raise ProductionWorkOrderError("work-order payload failed dispatch contract") from exc

    route_input = resolution.route_input
    return ProductionWorkOrder(
        work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
        task_id=route_input.task_id,
        task_revision=route_input.task_revision,
        task_content_hash=route_input.task_content_hash,
        flow_id=route_input.flow_id,
        route_decision_id=route.route_decision_id,
        route_decision_hash=route.content_hash,
        selected_adapter_id=resolution.selected_adapter_id,
        selected_adapter_fingerprint=resolution.selected_adapter_fingerprint,
        dispatch_catalog_id=dispatch_catalog.dispatch_catalog_id,
        dispatch_catalog_hash=dispatch_catalog.content_hash,
        dispatch_contract_id=contract.contract_id,
        dispatch_contract_hash=contract.content_hash,
        input_refs=refs,
        payload_json=canonical_bytes(normalized_payload).decode("utf-8"),
    )
