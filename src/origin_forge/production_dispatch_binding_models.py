from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, new_id, validate_id
from .production_dispatch_resolution_models import InputResolutionBundle
from .production_work_order_models import canonical_bytes, content_hash


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ROLES = 128
_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_DETAIL_CHARS = 2048


class DispatchBindingModelError(ValueError):
    pass


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise DispatchBindingModelError(f"invalid {label}: {value!r}")
    return value


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise DispatchBindingModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _canonical_json(value: object, label: str) -> str:
    raw = canonical_bytes(value)
    if len(raw) > _MAX_REQUEST_BYTES:
        raise DispatchBindingModelError(f"{label} exceeds byte bound")
    return raw.decode("utf-8")


def _decode_canonical(value: str, label: str) -> object:
    if not isinstance(value, str) or not value:
        raise DispatchBindingModelError(f"{label} must be canonical JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DispatchBindingModelError(f"{label} is invalid JSON") from exc
    if _canonical_json(decoded, label) != value:
        raise DispatchBindingModelError(f"{label} is not canonical JSON")
    return decoded


def _detail(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DispatchBindingModelError("detail must be bounded text or null")
    normalized = value.strip()
    if len(normalized) > _MAX_DETAIL_CHARS:
        normalized = normalized[:_MAX_DETAIL_CHARS]
    return normalized


@dataclass(frozen=True)
class DispatchBinderDescriptor:
    binder_id: str
    binder_fingerprint: str
    adapter_id: str
    dispatch_contract_id: str
    request_type_id: str
    request_schema_hash: str
    accepted_input_roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "binder_id",
            "adapter_id",
            "dispatch_contract_id",
            "request_type_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _token(getattr(self, field_name), field_name),
            )
        _sha256(self.binder_fingerprint, "binder_fingerprint")
        _sha256(self.request_schema_hash, "request_schema_hash")
        roles = tuple(self.accepted_input_roles)
        if len(roles) > _MAX_ROLES:
            raise DispatchBindingModelError("accepted input roles exceed bounds")
        normalized: list[str] = []
        for role in roles:
            if not isinstance(role, str) or not _ROLE_RE.fullmatch(role):
                raise DispatchBindingModelError(f"invalid accepted input role: {role!r}")
            normalized.append(role)
        if len(normalized) != len(set(normalized)):
            raise DispatchBindingModelError("accepted input roles contain duplicates")
        object.__setattr__(self, "accepted_input_roles", tuple(sorted(normalized)))
        canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "binder_id": self.binder_id,
            "binder_fingerprint": self.binder_fingerprint,
            "adapter_id": self.adapter_id,
            "dispatch_contract_id": self.dispatch_contract_id,
            "request_type_id": self.request_type_id,
            "request_schema_hash": self.request_schema_hash,
            "accepted_input_roles": list(self.accepted_input_roles),
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class DispatchBinding:
    dispatch_binding_id: str
    work_order_id: str
    work_order_hash: str
    work_order_audit_id: str
    work_order_audit_hash: str
    input_resolution_id: str
    input_resolution_hash: str
    task_id: str
    task_revision: int
    task_content_hash: str
    route_decision_id: str
    route_decision_hash: str
    selected_adapter_id: str
    selected_adapter_fingerprint: str
    dispatch_catalog_id: str
    dispatch_catalog_hash: str
    dispatch_contract_id: str
    dispatch_contract_hash: str
    binder_id: str
    binder_fingerprint: str
    request_type_id: str
    request_schema_hash: str
    request_projection_json: str

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id"),
            (self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id"),
            (self.work_order_audit_id, IdKind.WORK_ORDER_AUDIT, "work_order_audit_id"),
            (self.input_resolution_id, IdKind.INPUT_RESOLUTION_BUNDLE, "input_resolution_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.route_decision_id, IdKind.CAPABILITY_ROUTE_DECISION, "route_decision_id"),
            (self.dispatch_catalog_id, IdKind.DISPATCH_CONTRACT_CATALOG, "dispatch_catalog_id"),
        ):
            if not validate_id(value, kind):
                raise DispatchBindingModelError(f"{label} has wrong ID kind")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise DispatchBindingModelError("task_revision must be non-negative")
        for value, label in (
            (self.work_order_hash, "work_order_hash"),
            (self.work_order_audit_hash, "work_order_audit_hash"),
            (self.input_resolution_hash, "input_resolution_hash"),
            (self.task_content_hash, "task_content_hash"),
            (self.route_decision_hash, "route_decision_hash"),
            (self.selected_adapter_fingerprint, "selected_adapter_fingerprint"),
            (self.dispatch_catalog_hash, "dispatch_catalog_hash"),
            (self.dispatch_contract_hash, "dispatch_contract_hash"),
            (self.binder_fingerprint, "binder_fingerprint"),
            (self.request_schema_hash, "request_schema_hash"),
        ):
            _sha256(value, label)
        for field_name in (
            "selected_adapter_id",
            "dispatch_contract_id",
            "binder_id",
            "request_type_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _token(getattr(self, field_name), field_name),
            )
        _decode_canonical(self.request_projection_json, "request projection")
        canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        bundle: InputResolutionBundle,
        binder: DispatchBinderDescriptor,
        *,
        request_projection: object,
    ) -> "DispatchBinding":
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        if not isinstance(binder, DispatchBinderDescriptor):
            raise TypeError("binder must be a DispatchBinderDescriptor")
        if binder.adapter_id != bundle.selected_adapter_id:
            raise DispatchBindingModelError(
                "binder adapter does not match resolved WorkOrder adapter"
            )
        if binder.dispatch_contract_id != bundle.dispatch_contract_id:
            raise DispatchBindingModelError(
                "binder contract does not match resolved WorkOrder contract"
            )
        roles = {value.original_ref.role for value in bundle.resolved_inputs}
        if roles != set(binder.accepted_input_roles):
            raise DispatchBindingModelError(
                "binder input roles do not exactly match resolved WorkOrder roles"
            )
        return cls(
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            work_order_id=bundle.work_order_id,
            work_order_hash=bundle.work_order_hash,
            work_order_audit_id=bundle.work_order_audit_id,
            work_order_audit_hash=bundle.work_order_audit_hash,
            input_resolution_id=bundle.input_resolution_id,
            input_resolution_hash=bundle.content_hash,
            task_id=bundle.task_id,
            task_revision=bundle.task_revision,
            task_content_hash=bundle.task_content_hash,
            route_decision_id=bundle.route_decision_id,
            route_decision_hash=bundle.route_decision_hash,
            selected_adapter_id=bundle.selected_adapter_id,
            selected_adapter_fingerprint=bundle.selected_adapter_fingerprint,
            dispatch_catalog_id=bundle.dispatch_catalog_id,
            dispatch_catalog_hash=bundle.dispatch_catalog_hash,
            dispatch_contract_id=bundle.dispatch_contract_id,
            dispatch_contract_hash=bundle.dispatch_contract_hash,
            binder_id=binder.binder_id,
            binder_fingerprint=binder.binder_fingerprint,
            request_type_id=binder.request_type_id,
            request_schema_hash=binder.request_schema_hash,
            request_projection_json=_canonical_json(
                request_projection, "request projection"
            ),
        )

    @property
    def request_projection(self) -> object:
        return _decode_canonical(self.request_projection_json, "request projection")

    @property
    def request_content_hash(self) -> str:
        return content_hash(self.request_projection)

    def to_dict(self) -> dict[str, object]:
        return {
            "dispatch_binding_id": self.dispatch_binding_id,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "work_order_audit_id": self.work_order_audit_id,
            "work_order_audit_hash": self.work_order_audit_hash,
            "input_resolution_id": self.input_resolution_id,
            "input_resolution_hash": self.input_resolution_hash,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "route_decision_id": self.route_decision_id,
            "route_decision_hash": self.route_decision_hash,
            "selected_adapter_id": self.selected_adapter_id,
            "selected_adapter_fingerprint": self.selected_adapter_fingerprint,
            "dispatch_catalog_id": self.dispatch_catalog_id,
            "dispatch_catalog_hash": self.dispatch_catalog_hash,
            "dispatch_contract_id": self.dispatch_contract_id,
            "dispatch_contract_hash": self.dispatch_contract_hash,
            "binder_id": self.binder_id,
            "binder_fingerprint": self.binder_fingerprint,
            "request_type_id": self.request_type_id,
            "request_schema_hash": self.request_schema_hash,
            "request_projection": self.request_projection,
            "request_content_hash": self.request_content_hash,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


class BindingAuditStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class DispatchBindingAudit:
    binding_audit_id: str
    dispatch_binding_id: str
    dispatch_binding_hash: str
    input_resolution_id: str
    input_resolution_hash: str
    work_order_id: str
    work_order_hash: str
    work_order_audit_id: str
    work_order_audit_hash: str
    resolver_registry_fingerprint: str
    binder_id: str
    binder_fingerprint: str
    request_type_id: str
    request_schema_hash: str
    request_content_hash: str | None
    status: BindingAuditStatus
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.binding_audit_id, IdKind.DISPATCH_BINDING_AUDIT, "binding_audit_id"),
            (self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id"),
            (self.input_resolution_id, IdKind.INPUT_RESOLUTION_BUNDLE, "input_resolution_id"),
            (self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id"),
            (self.work_order_audit_id, IdKind.WORK_ORDER_AUDIT, "work_order_audit_id"),
        ):
            if not validate_id(value, kind):
                raise DispatchBindingModelError(f"{label} has wrong ID kind")
        for value, label in (
            (self.dispatch_binding_hash, "dispatch_binding_hash"),
            (self.input_resolution_hash, "input_resolution_hash"),
            (self.work_order_hash, "work_order_hash"),
            (self.work_order_audit_hash, "work_order_audit_hash"),
            (self.resolver_registry_fingerprint, "resolver_registry_fingerprint"),
            (self.binder_fingerprint, "binder_fingerprint"),
            (self.request_schema_hash, "request_schema_hash"),
        ):
            _sha256(value, label)
        object.__setattr__(self, "binder_id", _token(self.binder_id, "binder_id"))
        object.__setattr__(
            self,
            "request_type_id",
            _token(self.request_type_id, "request_type_id"),
        )
        if self.request_content_hash is not None:
            _sha256(self.request_content_hash, "request_content_hash")
        if not isinstance(self.status, BindingAuditStatus):
            raise DispatchBindingModelError("binding audit status is invalid")
        object.__setattr__(self, "failure_reason", _detail(self.failure_reason))
        if self.status is BindingAuditStatus.PASS:
            if self.request_content_hash is None or self.failure_reason is not None:
                raise DispatchBindingModelError(
                    "PASS binding audit requires request hash and no failure reason"
                )
        elif self.failure_reason is None:
            raise DispatchBindingModelError("FAIL binding audit requires failure reason")
        canonical_bytes(self.to_dict())

    @classmethod
    def pass_for(
        cls,
        binding: DispatchBinding,
        bundle: InputResolutionBundle,
    ) -> "DispatchBindingAudit":
        if not isinstance(binding, DispatchBinding):
            raise TypeError("binding must be a DispatchBinding")
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        if (
            binding.input_resolution_id != bundle.input_resolution_id
            or binding.input_resolution_hash != bundle.content_hash
        ):
            raise DispatchBindingModelError(
                "binding does not belong to supplied resolution bundle"
            )
        return cls(
            binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
            dispatch_binding_id=binding.dispatch_binding_id,
            dispatch_binding_hash=binding.content_hash,
            input_resolution_id=bundle.input_resolution_id,
            input_resolution_hash=bundle.content_hash,
            work_order_id=binding.work_order_id,
            work_order_hash=binding.work_order_hash,
            work_order_audit_id=binding.work_order_audit_id,
            work_order_audit_hash=binding.work_order_audit_hash,
            resolver_registry_fingerprint=bundle.resolver_registry_fingerprint,
            binder_id=binding.binder_id,
            binder_fingerprint=binding.binder_fingerprint,
            request_type_id=binding.request_type_id,
            request_schema_hash=binding.request_schema_hash,
            request_content_hash=binding.request_content_hash,
            status=BindingAuditStatus.PASS,
            failure_reason=None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_audit_id": self.binding_audit_id,
            "dispatch_binding_id": self.dispatch_binding_id,
            "dispatch_binding_hash": self.dispatch_binding_hash,
            "input_resolution_id": self.input_resolution_id,
            "input_resolution_hash": self.input_resolution_hash,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "work_order_audit_id": self.work_order_audit_id,
            "work_order_audit_hash": self.work_order_audit_hash,
            "resolver_registry_fingerprint": self.resolver_registry_fingerprint,
            "binder_id": self.binder_id,
            "binder_fingerprint": self.binder_fingerprint,
            "request_type_id": self.request_type_id,
            "request_schema_hash": self.request_schema_hash,
            "request_content_hash": self.request_content_hash,
            "status": self.status.value,
            "failure_reason": self.failure_reason,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


class DispatchBindingCurrentnessStatus(StrEnum):
    CURRENT_READY = "CURRENT_READY"
    NOT_READY = "NOT_READY"
    STALE_WORK_ORDER = "STALE_WORK_ORDER"
    STALE_INPUT = "STALE_INPUT"
    RESOLVER_DRIFT = "RESOLVER_DRIFT"
    BINDER_DRIFT = "BINDER_DRIFT"
    INVALID_AUDIT = "INVALID_AUDIT"


@dataclass(frozen=True)
class DispatchBindingCurrentness:
    dispatch_binding_id: str
    binding_audit_id: str
    work_order_id: str
    task_id: str
    status: DispatchBindingCurrentnessStatus
    detail: str | None = None

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id"),
            (self.binding_audit_id, IdKind.DISPATCH_BINDING_AUDIT, "binding_audit_id"),
            (self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id"),
            (self.task_id, IdKind.TASK, "task_id"),
        ):
            if not validate_id(value, kind):
                raise DispatchBindingModelError(f"{label} has wrong ID kind")
        if not isinstance(self.status, DispatchBindingCurrentnessStatus):
            raise DispatchBindingModelError("binding currentness status is invalid")
        object.__setattr__(self, "detail", _detail(self.detail))

    def to_dict(self) -> dict[str, object]:
        return {
            "dispatch_binding_id": self.dispatch_binding_id,
            "binding_audit_id": self.binding_audit_id,
            "work_order_id": self.work_order_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "detail": self.detail,
        }
