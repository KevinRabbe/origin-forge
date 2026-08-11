from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, Sequence, runtime_checkable

from .production_work_order_models import (
    DispatchContract,
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    canonical_bytes,
    content_hash,
)


_FIELD_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_MAX_FIELDS = 128
_MAX_STRING_CHARS = 65_536
_MAX_LIST_ITEMS = 256


class DispatchValidatorError(RuntimeError):
    pass


class PayloadFieldKind(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    STRING_LIST = "STRING_LIST"


def _field_name(value: str) -> str:
    if not isinstance(value, str) or not _FIELD_RE.fullmatch(value):
        raise ValueError(f"invalid payload field name: {value!r}")
    return value


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _exact_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


@dataclass(frozen=True)
class PayloadFieldRule:
    name: str
    kind: PayloadFieldKind
    required: bool = True
    allowed_values: tuple[str, ...] = ()
    max_string_chars: int = 4096
    min_integer: int = -2_147_483_648
    max_integer: int = 2_147_483_647
    max_items: int = 32

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _field_name(self.name))
        if not isinstance(self.kind, PayloadFieldKind):
            raise ValueError("payload field kind must be a PayloadFieldKind")
        if type(self.required) is not bool:
            raise ValueError("payload field required must be boolean")
        allowed = tuple(self.allowed_values)
        if len(allowed) > _MAX_LIST_ITEMS or any(
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_STRING_CHARS
            for value in allowed
        ):
            raise ValueError("payload allowed_values are outside bounds")
        if len(allowed) != len(set(allowed)):
            raise ValueError("payload allowed_values contain duplicates")
        object.__setattr__(self, "allowed_values", tuple(sorted(allowed)))
        _exact_int(
            self.max_string_chars,
            "max_string_chars",
            1,
            _MAX_STRING_CHARS,
        )
        if type(self.min_integer) is not int or type(self.max_integer) is not int:
            raise ValueError("integer bounds must be exact integers")
        if self.min_integer > self.max_integer:
            raise ValueError("integer lower bound exceeds upper bound")
        _exact_int(self.max_items, "max_items", 0, _MAX_LIST_ITEMS)
        if self.allowed_values and self.kind not in {
            PayloadFieldKind.STRING,
            PayloadFieldKind.STRING_LIST,
        }:
            raise ValueError("allowed_values are valid only for string fields")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "required": self.required,
            "allowed_values": list(self.allowed_values),
            "max_string_chars": self.max_string_chars,
            "min_integer": self.min_integer,
            "max_integer": self.max_integer,
            "max_items": self.max_items,
        }


@runtime_checkable
class DispatchPayloadValidator(Protocol):
    @property
    def validator_id(self) -> str: ...

    @property
    def validator_fingerprint(self) -> str: ...

    @property
    def payload_schema_id(self) -> str: ...

    @property
    def payload_schema_hash(self) -> str: ...

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]: ...


class StaticObjectPayloadValidator:
    """Pure exact-object validator for bounded inert work-order payloads.

    It deliberately implements no expression language, callbacks, imports,
    filesystem/process/network access, or dynamic field types.
    """

    _IMPLEMENTATION_ID = "origin-forge-static-object-validator@1"

    def __init__(
        self,
        *,
        validator_id: str,
        payload_schema_id: str,
        fields: Sequence[PayloadFieldRule],
    ):
        self._validator_id = _token(validator_id, "validator_id")
        self._payload_schema_id = _token(payload_schema_id, "payload_schema_id")
        values = tuple(fields)
        if not values or len(values) > _MAX_FIELDS:
            raise ValueError("payload fields are outside bounds")
        if not all(isinstance(value, PayloadFieldRule) for value in values):
            raise TypeError("fields must contain PayloadFieldRule values")
        names = [value.name for value in values]
        if len(names) != len(set(names)):
            raise ValueError("payload schema contains duplicate field names")
        self._fields = tuple(sorted(values, key=lambda value: value.name))
        self._by_name = {value.name: value for value in self._fields}
        self._payload_schema_hash = content_hash(self.schema_dict())
        self._validator_fingerprint = content_hash(
            {
                "implementation_id": self._IMPLEMENTATION_ID,
                "validator_id": self._validator_id,
                "payload_schema_id": self._payload_schema_id,
                "payload_schema_hash": self._payload_schema_hash,
            }
        )

    @property
    def validator_id(self) -> str:
        return self._validator_id

    @property
    def validator_fingerprint(self) -> str:
        return self._validator_fingerprint

    @property
    def payload_schema_id(self) -> str:
        return self._payload_schema_id

    @property
    def payload_schema_hash(self) -> str:
        return self._payload_schema_hash

    @property
    def fields(self) -> tuple[PayloadFieldRule, ...]:
        return self._fields

    def schema_dict(self) -> dict[str, object]:
        return {
            "schema_id": self._payload_schema_id,
            "type": "OBJECT",
            "fields": [value.to_dict() for value in self._fields],
            "additional_fields": False,
        }

    @staticmethod
    def _bounded_string(value: object, rule: PayloadFieldRule) -> str:
        if not isinstance(value, str) or not value or len(value) > rule.max_string_chars:
            raise DispatchValidatorError(f"payload field {rule.name} is invalid text")
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise DispatchValidatorError(
                f"payload field {rule.name} contains control characters"
            )
        if rule.allowed_values and value not in rule.allowed_values:
            raise DispatchValidatorError(
                f"payload field {rule.name} is not an allowed value"
            )
        return value

    @classmethod
    def _validate_field(cls, value: object, rule: PayloadFieldRule) -> object:
        if rule.kind is PayloadFieldKind.STRING:
            return cls._bounded_string(value, rule)
        if rule.kind is PayloadFieldKind.INTEGER:
            if (
                type(value) is not int
                or value < rule.min_integer
                or value > rule.max_integer
            ):
                raise DispatchValidatorError(
                    f"payload field {rule.name} is outside integer bounds"
                )
            return value
        if rule.kind is PayloadFieldKind.BOOLEAN:
            if type(value) is not bool:
                raise DispatchValidatorError(
                    f"payload field {rule.name} must be boolean"
                )
            return value
        if rule.kind is PayloadFieldKind.STRING_LIST:
            if not isinstance(value, list) or len(value) > rule.max_items:
                raise DispatchValidatorError(
                    f"payload field {rule.name} is outside list bounds"
                )
            result = tuple(cls._bounded_string(item, rule) for item in value)
            if len(result) != len(set(result)):
                raise DispatchValidatorError(
                    f"payload field {rule.name} contains duplicate values"
                )
            return list(result)
        raise AssertionError(rule.kind)

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DispatchValidatorError("payload must be an object")
        if any(not isinstance(value, WorkOrderInputRef) for value in input_refs):
            raise DispatchValidatorError("input_refs contain invalid values")
        unknown = sorted(set(payload) - set(self._by_name))
        if unknown:
            raise DispatchValidatorError(
                "payload contains unknown fields: " + ", ".join(unknown)
            )
        missing = sorted(
            rule.name
            for rule in self._fields
            if rule.required and rule.name not in payload
        )
        if missing:
            raise DispatchValidatorError(
                "payload is missing required fields: " + ", ".join(missing)
            )
        normalized: dict[str, Any] = {}
        for rule in self._fields:
            if rule.name in payload:
                normalized[rule.name] = self._validate_field(payload[rule.name], rule)
        canonical_bytes(normalized)
        return normalized


class DispatchContractValidatorRegistry:
    """Code-owned mapping of exact validator IDs to already-loaded pure validators."""

    def __init__(self, validators: Sequence[DispatchPayloadValidator]):
        values = tuple(validators)
        if not values:
            raise ValueError("validator registry must not be empty")
        if not all(isinstance(value, DispatchPayloadValidator) for value in values):
            raise TypeError("registry values must implement DispatchPayloadValidator")
        ids = [value.validator_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("validator registry contains duplicate validator IDs")
        for value in values:
            _token(value.validator_id, "validator_id")
            _token(value.payload_schema_id, "payload_schema_id")
            if len(value.validator_fingerprint) != 64 or len(value.payload_schema_hash) != 64:
                raise ValueError("validator fingerprints must be SHA-256 digests")
            int(value.validator_fingerprint, 16)
            int(value.payload_schema_hash, 16)
        self._by_id = {value.validator_id: value for value in values}

    def validator(self, validator_id: str) -> DispatchPayloadValidator:
        normalized = _token(validator_id, "validator_id")
        try:
            return self._by_id[normalized]
        except KeyError as exc:
            raise DispatchValidatorError(f"unknown dispatch validator: {normalized}") from exc

    def validate_contract(self, contract: DispatchContract) -> DispatchPayloadValidator:
        if not isinstance(contract, DispatchContract):
            raise TypeError("contract must be a DispatchContract")
        validator = self.validator(contract.validator_id)
        if validator.validator_fingerprint != contract.validator_fingerprint:
            raise DispatchValidatorError("dispatch validator fingerprint drifted")
        if validator.payload_schema_id != contract.payload_schema_id:
            raise DispatchValidatorError("dispatch payload schema identity drifted")
        if validator.payload_schema_hash != contract.payload_schema_hash:
            raise DispatchValidatorError("dispatch payload schema hash drifted")
        return validator

    def validate_payload(
        self,
        contract: DispatchContract,
        payload: dict[str, Any],
        input_refs: Sequence[WorkOrderInputRef],
    ) -> dict[str, Any]:
        validator = self.validate_contract(contract)
        refs = tuple(input_refs)
        if len(refs) > contract.max_input_refs:
            raise DispatchValidatorError("work-order input ref count exceeds contract")
        if not all(isinstance(value, WorkOrderInputRef) for value in refs):
            raise DispatchValidatorError("work-order input refs are invalid")
        duplicates = [
            (value.ref_type.value, value.ref_id, value.content_hash, value.revision, value.role)
            for value in refs
        ]
        if len(duplicates) != len(set(duplicates)):
            raise DispatchValidatorError("work-order input refs contain duplicates")
        allowed = set(contract.allowed_input_ref_types)
        disallowed = sorted(
            {value.ref_type.value for value in refs if value.ref_type not in allowed}
        )
        if disallowed:
            raise DispatchValidatorError(
                "work-order input ref type is not allowed by contract: "
                + ", ".join(disallowed)
            )
        try:
            raw = canonical_bytes(payload)
        except ProductionWorkOrderModelError as exc:
            raise DispatchValidatorError("payload is not bounded canonical data") from exc
        if len(raw) > contract.max_payload_bytes:
            raise DispatchValidatorError("payload byte size exceeds dispatch contract")
        normalized = validator.validate(payload, refs)
        try:
            normalized_bytes = canonical_bytes(normalized)
        except ProductionWorkOrderModelError as exc:
            raise DispatchValidatorError("validator returned invalid canonical payload") from exc
        if len(normalized_bytes) > contract.max_payload_bytes:
            raise DispatchValidatorError("normalized payload exceeds dispatch contract")
        return normalized
