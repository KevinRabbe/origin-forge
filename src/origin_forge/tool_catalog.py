from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping


_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_MAX_DESCRIPTION_CHARS = 2048
_MAX_LIST_ITEMS = 32
_MAX_ITEM_CHARS = 256
_MAX_SCHEMA_BYTES = 64 * 1024
_MAX_SCHEMA_DEPTH = 16
_MAX_SCHEMA_NODES = 2048


class ToolCatalogError(RuntimeError):
    pass


class ToolEffect(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    NETWORK = "NETWORK"


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ToolCatalogError("tool schema must be finite JSON data") from exc
    size = len(encoded.encode("utf-8"))
    if size > _MAX_SCHEMA_BYTES:
        raise ToolCatalogError(
            f"tool schema exceeds byte limit ({size} > {_MAX_SCHEMA_BYTES})"
        )
    return encoded


def _validate_json_shape(value: object) -> None:
    nodes = 0

    def walk(item: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_SCHEMA_NODES:
            raise ToolCatalogError(
                f"tool schema exceeds node limit ({nodes} > {_MAX_SCHEMA_NODES})"
            )
        if depth > _MAX_SCHEMA_DEPTH:
            raise ToolCatalogError(
                f"tool schema exceeds depth limit ({depth} > {_MAX_SCHEMA_DEPTH})"
            )
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ToolCatalogError("tool schema contains non-finite number")
            return
        if isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ToolCatalogError("tool schema object keys must be strings")
                walk(child, depth + 1)
            return
        raise ToolCatalogError(
            f"tool schema contains unsupported value: {type(item).__name__}"
        )

    walk(value, 0)


def _bounded_strings(
    values: Iterable[str],
    *,
    field: str,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) > _MAX_LIST_ITEMS:
        raise ToolCatalogError(
            f"tool {field} exceeds item limit ({len(result)} > {_MAX_LIST_ITEMS})"
        )
    for value in result:
        if not isinstance(value, str) or not value.strip():
            raise ToolCatalogError(f"tool {field} must contain non-empty strings")
        if len(value) > _MAX_ITEM_CHARS:
            raise ToolCatalogError(
                f"tool {field} item exceeds character limit ({len(value)} > {_MAX_ITEM_CHARS})"
            )
        if pattern is not None and not pattern.fullmatch(value):
            raise ToolCatalogError(f"invalid tool {field} item: {value!r}")
    if len(result) != len(set(result)):
        raise ToolCatalogError(f"tool {field} contains duplicates")
    return result


@dataclass(frozen=True)
class ToolDescriptor:
    tool_id: str
    description: str
    capabilities: tuple[str, ...]
    keywords: tuple[str, ...]
    effects: tuple[ToolEffect, ...]
    deterministic: bool
    reversible: bool
    input_schema_json: str
    output_schema_json: str
    permissions: tuple[str, ...] = ()
    required_resources: tuple[str, ...] = ()
    timeout_seconds: float | None = None
    verification_method: str | None = None

    @classmethod
    def create(
        cls,
        *,
        tool_id: str,
        description: str,
        capabilities: Iterable[str] = (),
        keywords: Iterable[str] = (),
        effects: Iterable[ToolEffect | str] = (),
        deterministic: bool,
        reversible: bool,
        input_schema: Mapping[str, object] | object,
        output_schema: Mapping[str, object] | object,
        permissions: Iterable[str] = (),
        required_resources: Iterable[str] = (),
        timeout_seconds: float | None = None,
        verification_method: str | None = None,
    ) -> "ToolDescriptor":
        if not isinstance(tool_id, str) or not _TOOL_ID_RE.fullmatch(tool_id):
            raise ToolCatalogError(f"invalid tool_id: {tool_id!r}")
        if not isinstance(description, str) or not description.strip():
            raise ToolCatalogError("tool description must be a non-empty string")
        if len(description) > _MAX_DESCRIPTION_CHARS:
            raise ToolCatalogError(
                f"tool description exceeds character limit ({len(description)} > {_MAX_DESCRIPTION_CHARS})"
            )
        if not isinstance(deterministic, bool) or not isinstance(reversible, bool):
            raise ToolCatalogError("tool deterministic/reversible flags must be boolean")
        if timeout_seconds is not None:
            if (
                not isinstance(timeout_seconds, (int, float))
                or isinstance(timeout_seconds, bool)
                or not math.isfinite(float(timeout_seconds))
                or timeout_seconds <= 0
            ):
                raise ToolCatalogError("tool timeout_seconds must be finite and positive")
        if verification_method is not None:
            if not isinstance(verification_method, str) or not verification_method.strip():
                raise ToolCatalogError("tool verification_method must be a non-empty string or null")
            if len(verification_method) > _MAX_ITEM_CHARS:
                raise ToolCatalogError("tool verification_method exceeds character limit")

        capability_values = _bounded_strings(
            capabilities,
            field="capabilities",
            pattern=_CAPABILITY_RE,
        )
        keyword_values = _bounded_strings(keywords, field="keywords")
        permission_values = _bounded_strings(permissions, field="permissions")
        resource_values = _bounded_strings(
            required_resources,
            field="required_resources",
        )

        effect_values: list[ToolEffect] = []
        for raw in effects:
            try:
                effect = raw if isinstance(raw, ToolEffect) else ToolEffect(raw)
            except (TypeError, ValueError) as exc:
                raise ToolCatalogError(f"invalid tool effect: {raw!r}") from exc
            if effect in effect_values:
                raise ToolCatalogError(f"duplicate tool effect: {effect.value}")
            effect_values.append(effect)

        _validate_json_shape(input_schema)
        _validate_json_shape(output_schema)
        return cls(
            tool_id=tool_id,
            description=description.strip(),
            capabilities=capability_values,
            keywords=keyword_values,
            effects=tuple(sorted(effect_values, key=lambda item: item.value)),
            deterministic=deterministic,
            reversible=reversible,
            input_schema_json=_canonical_json(input_schema),
            output_schema_json=_canonical_json(output_schema),
            permissions=permission_values,
            required_resources=resource_values,
            timeout_seconds=float(timeout_seconds) if timeout_seconds is not None else None,
            verification_method=verification_method.strip()
            if verification_method is not None
            else None,
        )

    @property
    def input_schema(self) -> object:
        return json.loads(self.input_schema_json)

    @property
    def output_schema(self) -> object:
        return json.loads(self.output_schema_json)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "keywords": list(self.keywords),
            "effects": [effect.value for effect in self.effects],
            "deterministic": self.deterministic,
            "reversible": self.reversible,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "permissions": list(self.permissions),
            "required_resources": list(self.required_resources),
            "timeout_seconds": self.timeout_seconds,
            "verification_method": self.verification_method,
        }

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    @property
    def ref(self) -> str:
        return f"{self.tool_id}#{self.content_hash.removeprefix('sha256:')[:12]}"

    def compact_dict(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id,
            "ref": self.ref,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "effects": [effect.value for effect in self.effects],
            "deterministic": self.deterministic,
        }


@dataclass(frozen=True)
class ToolCatalogSnapshot:
    descriptors: tuple[ToolDescriptor, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        descriptors: Iterable[ToolDescriptor],
        *,
        max_tools: int = 512,
    ) -> "ToolCatalogSnapshot":
        if max_tools <= 0:
            raise ValueError("max_tools must be positive")
        raw = tuple(descriptors)
        if any(not isinstance(item, ToolDescriptor) for item in raw):
            raise ToolCatalogError("tool catalog entries must be ToolDescriptor values")
        values = tuple(sorted(raw, key=lambda item: item.tool_id))
        if len(values) > max_tools:
            raise ToolCatalogError(
                f"tool catalog exceeds limit ({len(values)} > {max_tools})"
            )
        ids = [item.tool_id for item in values]
        if len(ids) != len(set(ids)):
            raise ToolCatalogError("tool catalog contains duplicate tool IDs")
        refs = [item.ref for item in values]
        payload = json.dumps(
            refs,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            descriptors=values,
            content_hash=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        )

    def get(self, tool_id: str) -> ToolDescriptor:
        for descriptor in self.descriptors:
            if descriptor.tool_id == tool_id:
                return descriptor
        raise KeyError(tool_id)

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(descriptor.ref for descriptor in self.descriptors)


@dataclass(frozen=True)
class AuthorizedToolView:
    catalog_hash: str
    descriptors: tuple[ToolDescriptor, ...]
    authority_hash: str

    @classmethod
    def create(
        cls,
        catalog: ToolCatalogSnapshot,
        allowed_tool_ids: Iterable[str],
        *,
        max_allowed_tools: int = 256,
    ) -> "AuthorizedToolView":
        if max_allowed_tools <= 0:
            raise ValueError("max_allowed_tools must be positive")
        ids = tuple(allowed_tool_ids)
        if len(ids) > max_allowed_tools:
            raise ToolCatalogError(
                f"authorized tool view exceeds limit ({len(ids)} > {max_allowed_tools})"
            )
        for tool_id in ids:
            if not isinstance(tool_id, str) or not _TOOL_ID_RE.fullmatch(tool_id):
                raise ToolCatalogError(f"invalid authorized tool ID: {tool_id!r}")
        if len(ids) != len(set(ids)):
            raise ToolCatalogError("authorized tool view contains duplicate tool IDs")

        descriptors: list[ToolDescriptor] = []
        for tool_id in ids:
            try:
                descriptors.append(catalog.get(tool_id))
            except KeyError as exc:
                raise ToolCatalogError(
                    f"authority references unknown tool: {tool_id}"
                ) from exc
        descriptors.sort(key=lambda item: item.tool_id)
        refs = [item.ref for item in descriptors]
        payload = json.dumps(
            {"catalog": catalog.content_hash, "refs": refs},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            catalog_hash=catalog.content_hash,
            descriptors=tuple(descriptors),
            authority_hash=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        )

    def get(self, tool_id: str) -> ToolDescriptor:
        for descriptor in self.descriptors:
            if descriptor.tool_id == tool_id:
                return descriptor
        raise KeyError(tool_id)

    @property
    def tool_ids(self) -> tuple[str, ...]:
        return tuple(descriptor.tool_id for descriptor in self.descriptors)
