from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .production_capability_models import CapabilityCatalog


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_REF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONTRACTS = 128
_MAX_REF_TYPES = 32
_MAX_PAYLOAD_BYTES = 1024 * 1024
_MAX_INPUT_REFS = 128
_MAX_OBJECT_BYTES = 2 * 1024 * 1024
_SCHEMA_VERSION = 1


class ProductionWorkOrderModelError(ValueError):
    pass


class WorkOrderRefType(StrEnum):
    ARTIFACT = "ARTIFACT"
    VERIFICATION = "VERIFICATION"
    PROJECT_ENTITY = "PROJECT_ENTITY"
    DESIGN_RULE = "DESIGN_RULE"
    AUDIO_PROFILE = "AUDIO_PROFILE"
    MEDIA_PROFILE = "MEDIA_PROFILE"
    SIMULATION_SPEC = "SIMULATION_SPEC"
    PLAYTEST_SCENARIO = "PLAYTEST_SCENARIO"
    MODEL3D_REQUEST = "MODEL3D_REQUEST"
    PHASE_SPECIFIC_EVIDENCE = "PHASE_SPECIFIC_EVIDENCE"


def canonical_bytes(value: object) -> bytes:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionWorkOrderModelError(
            "work-order object is not finite canonical JSON"
        ) from exc
    if not data or len(data) > _MAX_OBJECT_BYTES:
        raise ProductionWorkOrderModelError("work-order object is outside byte bounds")
    return data


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ProductionWorkOrderModelError(f"invalid {label}: {value!r}")
    return value


def _role(value: str) -> str:
    if not isinstance(value, str) or not _ROLE_RE.fullmatch(value):
        raise ProductionWorkOrderModelError(f"invalid work-order input role: {value!r}")
    return value


def _ref_id(value: str) -> str:
    if not isinstance(value, str) or not _REF_ID_RE.fullmatch(value):
        raise ProductionWorkOrderModelError(f"invalid work-order input ref_id: {value!r}")
    return value


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProductionWorkOrderModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _exact_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProductionWorkOrderModelError(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


@dataclass(frozen=True)
class WorkOrderInputRef:
    ref_type: WorkOrderRefType
    ref_id: str
    content_hash: str
    role: str
    revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ref_type, WorkOrderRefType):
            raise ProductionWorkOrderModelError("ref_type must be a WorkOrderRefType")
        object.__setattr__(self, "ref_id", _ref_id(self.ref_id))
        _sha256(self.content_hash, "input ref content_hash")
        object.__setattr__(self, "role", _role(self.role))
        if self.revision is not None:
            _exact_int(self.revision, "input ref revision", 0, 2_147_483_647)

    def to_dict(self) -> dict[str, object]:
        return {
            "ref_type": self.ref_type.value,
            "ref_id": self.ref_id,
            "content_hash": self.content_hash,
            "role": self.role,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class DispatchContract:
    contract_id: str
    contract_version: str
    adapter_id: str
    adapter_fingerprint: str
    validator_id: str
    validator_fingerprint: str
    payload_schema_id: str
    payload_schema_hash: str
    allowed_input_ref_types: tuple[WorkOrderRefType, ...]
    max_payload_bytes: int
    max_input_refs: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _token(self.contract_id, "contract_id"))
        object.__setattr__(
            self, "contract_version", _token(self.contract_version, "contract_version")
        )
        object.__setattr__(self, "adapter_id", _token(self.adapter_id, "adapter_id"))
        _sha256(self.adapter_fingerprint, "adapter_fingerprint")
        object.__setattr__(self, "validator_id", _token(self.validator_id, "validator_id"))
        _sha256(self.validator_fingerprint, "validator_fingerprint")
        object.__setattr__(
            self, "payload_schema_id", _token(self.payload_schema_id, "payload_schema_id")
        )
        _sha256(self.payload_schema_hash, "payload_schema_hash")

        ref_types = tuple(self.allowed_input_ref_types)
        if len(ref_types) > _MAX_REF_TYPES or not all(
            isinstance(value, WorkOrderRefType) for value in ref_types
        ):
            raise ProductionWorkOrderModelError("allowed_input_ref_types are invalid")
        if len(ref_types) != len(set(ref_types)):
            raise ProductionWorkOrderModelError(
                "allowed_input_ref_types contain duplicates"
            )
        object.__setattr__(
            self,
            "allowed_input_ref_types",
            tuple(sorted(ref_types, key=lambda value: value.value)),
        )
        _exact_int(
            self.max_payload_bytes,
            "max_payload_bytes",
            1,
            _MAX_PAYLOAD_BYTES,
        )
        _exact_int(self.max_input_refs, "max_input_refs", 0, _MAX_INPUT_REFS)
        canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "adapter_id": self.adapter_id,
            "adapter_fingerprint": self.adapter_fingerprint,
            "validator_id": self.validator_id,
            "validator_fingerprint": self.validator_fingerprint,
            "payload_schema_id": self.payload_schema_id,
            "payload_schema_hash": self.payload_schema_hash,
            "allowed_input_ref_types": [
                value.value for value in self.allowed_input_ref_types
            ],
            "max_payload_bytes": self.max_payload_bytes,
            "max_input_refs": self.max_input_refs,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class DispatchContractCatalog:
    dispatch_catalog_id: str
    phase32_catalog_id: str
    phase32_catalog_hash: str
    contracts: tuple[DispatchContract, ...]
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not validate_id(
            self.dispatch_catalog_id, IdKind.DISPATCH_CONTRACT_CATALOG
        ):
            raise ProductionWorkOrderModelError("dispatch_catalog_id must be a DISPCAT ID")
        if not validate_id(self.phase32_catalog_id, IdKind.CAPABILITY_CATALOG):
            raise ProductionWorkOrderModelError("phase32_catalog_id must be a CAPCAT ID")
        _sha256(self.phase32_catalog_hash, "phase32_catalog_hash")
        if type(self.schema_version) is not int or self.schema_version != _SCHEMA_VERSION:
            raise ProductionWorkOrderModelError(
                "unsupported dispatch contract catalog schema_version"
            )

        contracts = tuple(self.contracts)
        if not contracts or len(contracts) > _MAX_CONTRACTS:
            raise ProductionWorkOrderModelError("dispatch contracts are outside bounds")
        if not all(isinstance(value, DispatchContract) for value in contracts):
            raise ProductionWorkOrderModelError(
                "dispatch catalog requires DispatchContract values"
            )
        contract_ids = [value.contract_id for value in contracts]
        adapter_ids = [value.adapter_id for value in contracts]
        if len(contract_ids) != len(set(contract_ids)):
            raise ProductionWorkOrderModelError(
                "dispatch catalog contains duplicate contract IDs"
            )
        if len(adapter_ids) != len(set(adapter_ids)):
            raise ProductionWorkOrderModelError(
                "dispatch catalog contains multiple v1 contracts for one adapter"
            )
        object.__setattr__(
            self,
            "contracts",
            tuple(sorted(contracts, key=lambda value: value.contract_id)),
        )
        canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        phase32_catalog: CapabilityCatalog,
        contracts: Iterable[DispatchContract],
    ) -> "DispatchContractCatalog":
        if not isinstance(phase32_catalog, CapabilityCatalog):
            raise TypeError("phase32_catalog must be a CapabilityCatalog")
        result = cls(
            dispatch_catalog_id=new_id(IdKind.DISPATCH_CONTRACT_CATALOG),
            phase32_catalog_id=phase32_catalog.catalog_id,
            phase32_catalog_hash=phase32_catalog.content_hash,
            contracts=tuple(contracts),
        )
        result.validate_against(phase32_catalog)
        return result

    @property
    def contract_ids(self) -> tuple[str, ...]:
        return tuple(value.contract_id for value in self.contracts)

    def contract(self, contract_id: str) -> DispatchContract:
        normalized = _token(contract_id, "contract_id")
        for value in self.contracts:
            if value.contract_id == normalized:
                return value
        raise KeyError(normalized)

    def contract_for_adapter(self, adapter_id: str) -> DispatchContract:
        normalized = _token(adapter_id, "adapter_id")
        for value in self.contracts:
            if value.adapter_id == normalized:
                return value
        raise KeyError(normalized)

    def validate_against(self, phase32_catalog: CapabilityCatalog) -> None:
        if not isinstance(phase32_catalog, CapabilityCatalog):
            raise TypeError("phase32_catalog must be a CapabilityCatalog")
        if (
            self.phase32_catalog_id != phase32_catalog.catalog_id
            or self.phase32_catalog_hash != phase32_catalog.content_hash
        ):
            raise ProductionWorkOrderModelError(
                "dispatch catalog Phase-32 catalog binding drifted"
            )
        for contract in self.contracts:
            try:
                adapter = phase32_catalog.adapter(contract.adapter_id)
            except KeyError as exc:
                raise ProductionWorkOrderModelError(
                    f"dispatch contract references unknown adapter: {contract.adapter_id}"
                ) from exc
            if contract.adapter_fingerprint != adapter.implementation_fingerprint:
                raise ProductionWorkOrderModelError(
                    f"dispatch contract adapter fingerprint drifted: {contract.adapter_id}"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "dispatch_catalog_id": self.dispatch_catalog_id,
            "phase32_catalog_id": self.phase32_catalog_id,
            "phase32_catalog_hash": self.phase32_catalog_hash,
            "schema_version": self.schema_version,
            "contracts": [value.to_dict() for value in self.contracts],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
