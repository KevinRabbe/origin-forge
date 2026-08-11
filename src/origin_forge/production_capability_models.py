from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id


_CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_ADAPTER_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_NAME_CHARS = 160
_MAX_SUMMARY_CHARS = 2048
_MAX_CAPABILITIES = 128
_MAX_ADAPTERS = 128
_MAX_ADAPTER_CAPABILITIES = 32
_MAX_POLICY_ADAPTERS = 128
_MAX_POLICY_CAPABILITIES = 128
_MAX_OBJECT_BYTES = 1024 * 1024
_SCHEMA_VERSION = 1


class ProductionCapabilityError(ValueError):
    pass


class CapabilityDomain(StrEnum):
    CODE = "CODE"
    DESIGN = "DESIGN"
    MEDIA_2D = "MEDIA_2D"
    MEDIA_3D = "MEDIA_3D"
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"
    RUNTIME = "RUNTIME"
    PLAYTEST = "PLAYTEST"
    SIMULATION = "SIMULATION"
    GENERAL = "GENERAL"


class AdapterExecutionEffect(StrEnum):
    WORKSPACE_MUTATION = "WORKSPACE_MUTATION"
    MEDIA_WORKSPACE_MUTATION = "MEDIA_WORKSPACE_MUTATION"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    SIMULATION_ONLY = "SIMULATION_ONLY"
    PROPOSAL_ONLY = "PROPOSAL_ONLY"


class AdapterReplayClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    REVISION_BOUND = "REVISION_BOUND"
    RUNTIME_BOUND = "RUNTIME_BOUND"
    NON_REPLAYABLE = "NON_REPLAYABLE"


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionCapabilityError("capability data is not finite canonical JSON") from exc
    if not encoded or len(encoded) > _MAX_OBJECT_BYTES:
        raise ProductionCapabilityError("capability object is outside byte bounds")
    return encoded


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProductionCapabilityError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _bounded_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionCapabilityError(f"{label} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ProductionCapabilityError(f"{label} exceeds character limit")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in normalized):
        raise ProductionCapabilityError(f"{label} contains control characters")
    return normalized


def _capability_id(value: str) -> str:
    if not isinstance(value, str) or not _CAPABILITY_ID_RE.fullmatch(value):
        raise ProductionCapabilityError(f"invalid capability_id: {value!r}")
    return value


def _adapter_id(value: str) -> str:
    if not isinstance(value, str) or not _ADAPTER_ID_RE.fullmatch(value):
        raise ProductionCapabilityError(f"invalid adapter_id: {value!r}")
    return value


def _version(value: str, label: str) -> str:
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise ProductionCapabilityError(f"invalid {label}: {value!r}")
    return value


def _unique_capabilities(
    values: Iterable[str], *, label: str, maximum: int, require_one: bool = True
) -> tuple[str, ...]:
    result = tuple(_capability_id(value) for value in values)
    if (require_one and not result) or len(result) > maximum:
        raise ProductionCapabilityError(f"{label} are outside bounds")
    if len(result) != len(set(result)):
        raise ProductionCapabilityError(f"{label} contain duplicates")
    return tuple(sorted(result))


@dataclass(frozen=True)
class ProductionCapability:
    capability_id: str
    name: str
    summary: str
    media_domain: CapabilityDomain
    contract_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", _capability_id(self.capability_id))
        object.__setattr__(
            self, "name", _bounded_text(self.name, "capability name", _MAX_NAME_CHARS)
        )
        object.__setattr__(
            self,
            "summary",
            _bounded_text(self.summary, "capability summary", _MAX_SUMMARY_CHARS),
        )
        if not isinstance(self.media_domain, CapabilityDomain):
            raise ProductionCapabilityError("media_domain must be a CapabilityDomain")
        object.__setattr__(
            self,
            "contract_version",
            _version(self.contract_version, "capability contract_version"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "summary": self.summary,
            "media_domain": self.media_domain.value,
            "contract_version": self.contract_version,
        }

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True)
class TrustedProductionAdapter:
    adapter_id: str
    adapter_family: str
    adapter_version: str
    implementation_fingerprint: str
    capability_ids: tuple[str, ...]
    execution_effect: AdapterExecutionEffect
    replay_class: AdapterReplayClass

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", _adapter_id(self.adapter_id))
        object.__setattr__(
            self, "adapter_family", _adapter_id(self.adapter_family)
        )
        object.__setattr__(
            self, "adapter_version", _version(self.adapter_version, "adapter_version")
        )
        _sha256(self.implementation_fingerprint, "implementation_fingerprint")
        object.__setattr__(
            self,
            "capability_ids",
            _unique_capabilities(
                self.capability_ids,
                label="adapter capability_ids",
                maximum=_MAX_ADAPTER_CAPABILITIES,
            ),
        )
        if not isinstance(self.execution_effect, AdapterExecutionEffect):
            raise ProductionCapabilityError(
                "execution_effect must be an AdapterExecutionEffect"
            )
        if not isinstance(self.replay_class, AdapterReplayClass):
            raise ProductionCapabilityError("replay_class must be an AdapterReplayClass")

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_family": self.adapter_family,
            "adapter_version": self.adapter_version,
            "implementation_fingerprint": self.implementation_fingerprint,
            "capability_ids": list(self.capability_ids),
            "execution_effect": self.execution_effect.value,
            "replay_class": self.replay_class.value,
        }

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True)
class CapabilityCatalog:
    catalog_id: str
    capabilities: tuple[ProductionCapability, ...]
    adapters: tuple[TrustedProductionAdapter, ...]
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not validate_id(self.catalog_id, IdKind.CAPABILITY_CATALOG):
            raise ProductionCapabilityError("catalog_id must be a CAPCAT ID")
        if type(self.schema_version) is not int or self.schema_version != _SCHEMA_VERSION:
            raise ProductionCapabilityError("unsupported capability catalog schema_version")

        capabilities = tuple(self.capabilities)
        adapters = tuple(self.adapters)
        if not capabilities or len(capabilities) > _MAX_CAPABILITIES:
            raise ProductionCapabilityError("catalog capabilities are outside bounds")
        if len(adapters) > _MAX_ADAPTERS:
            raise ProductionCapabilityError("catalog adapters are outside bounds")
        if not all(isinstance(value, ProductionCapability) for value in capabilities):
            raise ProductionCapabilityError(
                "catalog capabilities must be ProductionCapability values"
            )
        if not all(isinstance(value, TrustedProductionAdapter) for value in adapters):
            raise ProductionCapabilityError(
                "catalog adapters must be TrustedProductionAdapter values"
            )

        capability_ids = [value.capability_id for value in capabilities]
        adapter_ids = [value.adapter_id for value in adapters]
        if len(capability_ids) != len(set(capability_ids)):
            raise ProductionCapabilityError("catalog contains duplicate capability IDs")
        if len(adapter_ids) != len(set(adapter_ids)):
            raise ProductionCapabilityError("catalog contains duplicate adapter IDs")

        known = set(capability_ids)
        for adapter in adapters:
            unknown = sorted(set(adapter.capability_ids) - known)
            if unknown:
                raise ProductionCapabilityError(
                    "adapter references unknown capabilities: " + ", ".join(unknown)
                )

        object.__setattr__(
            self, "capabilities", tuple(sorted(capabilities, key=lambda value: value.capability_id))
        )
        object.__setattr__(
            self, "adapters", tuple(sorted(adapters, key=lambda value: value.adapter_id))
        )
        _canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        capabilities: Iterable[ProductionCapability],
        adapters: Iterable[TrustedProductionAdapter] = (),
    ) -> "CapabilityCatalog":
        return cls(
            catalog_id=new_id(IdKind.CAPABILITY_CATALOG),
            capabilities=tuple(capabilities),
            adapters=tuple(adapters),
        )

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(value.capability_id for value in self.capabilities)

    @property
    def adapter_ids(self) -> tuple[str, ...]:
        return tuple(value.adapter_id for value in self.adapters)

    def capability(self, capability_id: str) -> ProductionCapability:
        normalized = _capability_id(capability_id)
        for value in self.capabilities:
            if value.capability_id == normalized:
                return value
        raise KeyError(normalized)

    def adapter(self, adapter_id: str) -> TrustedProductionAdapter:
        normalized = _adapter_id(adapter_id)
        for value in self.adapters:
            if value.adapter_id == normalized:
                return value
        raise KeyError(normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_id": self.catalog_id,
            "schema_version": self.schema_version,
            "capabilities": [value.to_dict() for value in self.capabilities],
            "adapters": [value.to_dict() for value in self.adapters],
        }

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True)
class CapabilityRoutingPolicy:
    routing_policy_id: str
    catalog_id: str
    catalog_hash: str
    ordered_adapter_ids: tuple[str, ...]
    allowed_capability_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not validate_id(
            self.routing_policy_id, IdKind.CAPABILITY_ROUTING_POLICY
        ):
            raise ProductionCapabilityError("routing_policy_id must be a CAPPOL ID")
        if not validate_id(self.catalog_id, IdKind.CAPABILITY_CATALOG):
            raise ProductionCapabilityError("routing policy catalog_id must be a CAPCAT ID")
        _sha256(self.catalog_hash, "routing policy catalog_hash")

        ordered = tuple(_adapter_id(value) for value in self.ordered_adapter_ids)
        if not ordered or len(ordered) > _MAX_POLICY_ADAPTERS:
            raise ProductionCapabilityError("ordered_adapter_ids are outside bounds")
        if len(ordered) != len(set(ordered)):
            raise ProductionCapabilityError("ordered_adapter_ids contain duplicates")
        object.__setattr__(self, "ordered_adapter_ids", ordered)
        object.__setattr__(
            self,
            "allowed_capability_ids",
            _unique_capabilities(
                self.allowed_capability_ids,
                label="allowed_capability_ids",
                maximum=_MAX_POLICY_CAPABILITIES,
            ),
        )
        _canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        catalog: CapabilityCatalog,
        *,
        ordered_adapter_ids: Iterable[str],
        allowed_capability_ids: Iterable[str],
    ) -> "CapabilityRoutingPolicy":
        if not isinstance(catalog, CapabilityCatalog):
            raise TypeError("catalog must be a CapabilityCatalog")
        policy = cls(
            routing_policy_id=new_id(IdKind.CAPABILITY_ROUTING_POLICY),
            catalog_id=catalog.catalog_id,
            catalog_hash=catalog.content_hash,
            ordered_adapter_ids=tuple(ordered_adapter_ids),
            allowed_capability_ids=tuple(allowed_capability_ids),
        )
        policy.validate_against(catalog)
        return policy

    def validate_against(self, catalog: CapabilityCatalog) -> None:
        if not isinstance(catalog, CapabilityCatalog):
            raise TypeError("catalog must be a CapabilityCatalog")
        if self.catalog_id != catalog.catalog_id or self.catalog_hash != catalog.content_hash:
            raise ProductionCapabilityError("routing policy catalog binding drifted")
        unknown_adapters = sorted(set(self.ordered_adapter_ids) - set(catalog.adapter_ids))
        if unknown_adapters:
            raise ProductionCapabilityError(
                "routing policy references unknown adapters: "
                + ", ".join(unknown_adapters)
            )
        unknown_capabilities = sorted(
            set(self.allowed_capability_ids) - set(catalog.capability_ids)
        )
        if unknown_capabilities:
            raise ProductionCapabilityError(
                "routing policy references unknown capabilities: "
                + ", ".join(unknown_capabilities)
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "routing_policy_id": self.routing_policy_id,
            "catalog_id": self.catalog_id,
            "catalog_hash": self.catalog_hash,
            "ordered_adapter_ids": list(self.ordered_adapter_ids),
            "allowed_capability_ids": list(self.allowed_capability_ids),
        }

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())
