from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
    content_hash,
)


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,31}-$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CLAIMS = 256
_MAX_INPUTS = 128
_MAX_PROJECTION_BYTES = 1024 * 1024


class DispatchResolutionModelError(ValueError):
    pass


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise DispatchResolutionModelError(f"invalid {label}: {value!r}")
    return value


def _role(value: str) -> str:
    if not isinstance(value, str) or not _ROLE_RE.fullmatch(value):
        raise DispatchResolutionModelError(f"invalid role: {value!r}")
    return value


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise DispatchResolutionModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _canonical_json(value: object, label: str) -> str:
    raw = canonical_bytes(value)
    if len(raw) > _MAX_PROJECTION_BYTES:
        raise DispatchResolutionModelError(f"{label} exceeds byte bound")
    return raw.decode("utf-8")


def _decode_canonical(value: str, label: str) -> object:
    if not isinstance(value, str) or not value:
        raise DispatchResolutionModelError(f"{label} must be canonical JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DispatchResolutionModelError(
            f"{label} must be canonical JSON text"
        ) from exc
    if _canonical_json(decoded, label) != value:
        raise DispatchResolutionModelError(f"{label} is not canonical JSON")
    return decoded


@dataclass(frozen=True)
class ResolverClaim:
    ref_type: WorkOrderRefType
    source_id_prefix: str
    source_object_type: str
    role: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ref_type, WorkOrderRefType):
            raise DispatchResolutionModelError(
                "resolver claim ref_type must be a WorkOrderRefType"
            )
        if not isinstance(self.source_id_prefix, str) or not _PREFIX_RE.fullmatch(
            self.source_id_prefix
        ):
            raise DispatchResolutionModelError(
                "resolver claim source_id_prefix is invalid"
            )
        object.__setattr__(
            self,
            "source_object_type",
            _token(self.source_object_type, "source_object_type"),
        )
        if self.role is not None:
            object.__setattr__(self, "role", _role(self.role))

    def to_dict(self) -> dict[str, object]:
        return {
            "ref_type": self.ref_type.value,
            "source_id_prefix": self.source_id_prefix,
            "source_object_type": self.source_object_type,
            "role": self.role,
        }


@dataclass(frozen=True)
class InputResolverDescriptor:
    resolver_id: str
    resolver_fingerprint: str
    claims: tuple[ResolverClaim, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolver_id", _token(self.resolver_id, "resolver_id"))
        _sha256(self.resolver_fingerprint, "resolver_fingerprint")
        claims = tuple(self.claims)
        if not claims or len(claims) > _MAX_CLAIMS:
            raise DispatchResolutionModelError("resolver claims are outside bounds")
        if not all(isinstance(value, ResolverClaim) for value in claims):
            raise DispatchResolutionModelError(
                "resolver claims must contain ResolverClaim values"
            )
        keys = [
            (
                value.ref_type.value,
                value.source_id_prefix,
                value.source_object_type,
                value.role,
            )
            for value in claims
        ]
        if len(keys) != len(set(keys)):
            raise DispatchResolutionModelError(
                "resolver descriptor contains duplicate claims"
            )
        object.__setattr__(
            self,
            "claims",
            tuple(
                sorted(
                    claims,
                    key=lambda value: (
                        value.ref_type.value,
                        value.source_id_prefix,
                        value.source_object_type,
                        "" if value.role is None else value.role,
                    ),
                )
            ),
        )
        canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "resolver_id": self.resolver_id,
            "resolver_fingerprint": self.resolver_fingerprint,
            "claims": [value.to_dict() for value in self.claims],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


class ResolvedInputCurrentness(StrEnum):
    CURRENT = "CURRENT"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    STALE = "STALE"


@dataclass(frozen=True)
class ResolvedWorkOrderInput:
    original_ref: WorkOrderInputRef
    resolver_id: str
    resolver_fingerprint: str
    source_object_type: str
    source_id: str
    source_content_hash: str
    source_revision: int | None
    resolution_class: str
    projection_json: str
    currentness: ResolvedInputCurrentness

    def __post_init__(self) -> None:
        if not isinstance(self.original_ref, WorkOrderInputRef):
            raise DispatchResolutionModelError(
                "original_ref must be a WorkOrderInputRef"
            )
        object.__setattr__(self, "resolver_id", _token(self.resolver_id, "resolver_id"))
        _sha256(self.resolver_fingerprint, "resolver_fingerprint")
        object.__setattr__(
            self,
            "source_object_type",
            _token(self.source_object_type, "source_object_type"),
        )
        if self.source_id != self.original_ref.ref_id:
            raise DispatchResolutionModelError(
                "resolved source_id must equal original ref_id"
            )
        _sha256(self.source_content_hash, "source_content_hash")
        if self.source_content_hash != self.original_ref.content_hash:
            raise DispatchResolutionModelError(
                "resolved source hash must equal original ref hash"
            )
        if self.source_revision != self.original_ref.revision:
            raise DispatchResolutionModelError(
                "resolved source revision must equal original ref revision"
            )
        if self.source_revision is not None and (
            type(self.source_revision) is not int
            or not 0 <= self.source_revision <= 2_147_483_647
        ):
            raise DispatchResolutionModelError("source_revision is invalid")
        object.__setattr__(
            self,
            "resolution_class",
            _token(self.resolution_class, "resolution_class"),
        )
        _decode_canonical(self.projection_json, "resolved input projection")
        if not isinstance(self.currentness, ResolvedInputCurrentness):
            raise DispatchResolutionModelError("resolved input currentness is invalid")
        canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        original_ref: WorkOrderInputRef,
        *,
        resolver_id: str,
        resolver_fingerprint: str,
        source_object_type: str,
        resolution_class: str,
        projection: object,
        currentness: ResolvedInputCurrentness = ResolvedInputCurrentness.CURRENT,
    ) -> "ResolvedWorkOrderInput":
        if not isinstance(original_ref, WorkOrderInputRef):
            raise TypeError("original_ref must be a WorkOrderInputRef")
        return cls(
            original_ref=original_ref,
            resolver_id=resolver_id,
            resolver_fingerprint=resolver_fingerprint,
            source_object_type=source_object_type,
            source_id=original_ref.ref_id,
            source_content_hash=original_ref.content_hash,
            source_revision=original_ref.revision,
            resolution_class=resolution_class,
            projection_json=_canonical_json(projection, "resolved input projection"),
            currentness=currentness,
        )

    @property
    def projection(self) -> object:
        return _decode_canonical(self.projection_json, "resolved input projection")

    @property
    def projection_hash(self) -> str:
        return content_hash(self.projection)

    def to_dict(self) -> dict[str, object]:
        return {
            "original_ref": self.original_ref.to_dict(),
            "resolver_id": self.resolver_id,
            "resolver_fingerprint": self.resolver_fingerprint,
            "source_object_type": self.source_object_type,
            "source_id": self.source_id,
            "source_content_hash": self.source_content_hash,
            "source_revision": self.source_revision,
            "resolution_class": self.resolution_class,
            "projection": self.projection,
            "projection_hash": self.projection_hash,
            "currentness": self.currentness.value,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


def _resolved_key(value: ResolvedWorkOrderInput) -> tuple[str, str, str]:
    return (
        value.original_ref.ref_type.value,
        value.original_ref.role,
        value.original_ref.ref_id,
    )


@dataclass(frozen=True)
class InputResolutionBundle:
    input_resolution_id: str
    work_order_id: str
    work_order_hash: str
    work_order_audit_id: str
    work_order_audit_hash: str
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
    resolver_registry_fingerprint: str
    resolved_inputs: tuple[ResolvedWorkOrderInput, ...]

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.input_resolution_id, IdKind.INPUT_RESOLUTION_BUNDLE, "input_resolution_id"),
            (self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id"),
            (self.work_order_audit_id, IdKind.WORK_ORDER_AUDIT, "work_order_audit_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.route_decision_id, IdKind.CAPABILITY_ROUTE_DECISION, "route_decision_id"),
            (self.dispatch_catalog_id, IdKind.DISPATCH_CONTRACT_CATALOG, "dispatch_catalog_id"),
        ):
            if not validate_id(value, kind):
                raise DispatchResolutionModelError(f"{label} has wrong ID kind")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise DispatchResolutionModelError("task_revision must be non-negative")
        for value, label in (
            (self.work_order_hash, "work_order_hash"),
            (self.work_order_audit_hash, "work_order_audit_hash"),
            (self.task_content_hash, "task_content_hash"),
            (self.route_decision_hash, "route_decision_hash"),
            (self.selected_adapter_fingerprint, "selected_adapter_fingerprint"),
            (self.dispatch_catalog_hash, "dispatch_catalog_hash"),
            (self.dispatch_contract_hash, "dispatch_contract_hash"),
            (self.resolver_registry_fingerprint, "resolver_registry_fingerprint"),
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
        inputs = tuple(self.resolved_inputs)
        if len(inputs) > _MAX_INPUTS or not all(
            isinstance(value, ResolvedWorkOrderInput) for value in inputs
        ):
            raise DispatchResolutionModelError("resolved_inputs are outside bounds")
        keys = [_resolved_key(value) for value in inputs]
        if len(keys) != len(set(keys)):
            raise DispatchResolutionModelError(
                "input resolution bundle contains duplicate resolved refs"
            )
        object.__setattr__(self, "resolved_inputs", tuple(sorted(inputs, key=_resolved_key)))
        canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        *,
        work_order_id: str,
        work_order_hash: str,
        work_order_audit_id: str,
        work_order_audit_hash: str,
        task_id: str,
        task_revision: int,
        task_content_hash: str,
        route_decision_id: str,
        route_decision_hash: str,
        selected_adapter_id: str,
        selected_adapter_fingerprint: str,
        dispatch_catalog_id: str,
        dispatch_catalog_hash: str,
        dispatch_contract_id: str,
        dispatch_contract_hash: str,
        resolver_registry_fingerprint: str,
        resolved_inputs: Iterable[ResolvedWorkOrderInput],
    ) -> "InputResolutionBundle":
        return cls(
            input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
            work_order_id=work_order_id,
            work_order_hash=work_order_hash,
            work_order_audit_id=work_order_audit_id,
            work_order_audit_hash=work_order_audit_hash,
            task_id=task_id,
            task_revision=task_revision,
            task_content_hash=task_content_hash,
            route_decision_id=route_decision_id,
            route_decision_hash=route_decision_hash,
            selected_adapter_id=selected_adapter_id,
            selected_adapter_fingerprint=selected_adapter_fingerprint,
            dispatch_catalog_id=dispatch_catalog_id,
            dispatch_catalog_hash=dispatch_catalog_hash,
            dispatch_contract_id=dispatch_contract_id,
            dispatch_contract_hash=dispatch_contract_hash,
            resolver_registry_fingerprint=resolver_registry_fingerprint,
            resolved_inputs=tuple(resolved_inputs),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "input_resolution_id": self.input_resolution_id,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "work_order_audit_id": self.work_order_audit_id,
            "work_order_audit_hash": self.work_order_audit_hash,
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
            "resolver_registry_fingerprint": self.resolver_registry_fingerprint,
            "resolved_inputs": [value.to_dict() for value in self.resolved_inputs],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
