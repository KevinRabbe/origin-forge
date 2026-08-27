from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id


_MAX_TEXT = 16 * 1024
_MAX_ROOTS = 64
_MAX_METADATA_BYTES = 64 * 1024
_SHA256_PREFIX = "sha256:"


class EntityKind(StrEnum):
    FEATURE = "FEATURE"
    SYSTEM = "SYSTEM"
    COMPONENT = "COMPONENT"
    CODE_SYMBOL = "CODE_SYMBOL"
    TEST = "TEST"
    CONFIG = "CONFIG"
    DATA = "DATA"
    ASSET = "ASSET"
    IMAGE = "IMAGE"
    MODEL = "MODEL"
    AUDIO = "AUDIO"
    UI = "UI"
    SCENE = "SCENE"
    DOCUMENT = "DOCUMENT"
    OTHER = "OTHER"


class EntityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"


class RelationType(StrEnum):
    CONTAINS = "CONTAINS"
    DEPENDS_ON = "DEPENDS_ON"
    IMPLEMENTS = "IMPLEMENTS"
    TESTS = "TESTS"
    CONFIGURES = "CONFIGURES"
    USES = "USES"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    REFERENCES = "REFERENCES"
    DERIVED_FROM = "DERIVED_FROM"
    AFFECTS = "AFFECTS"


class RelationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BindingType(StrEnum):
    ARTIFACT = "ARTIFACT"
    DECISION = "DECISION"
    TASK = "TASK"
    VERIFICATION = "VERIFICATION"
    FILE = "FILE"
    SYMBOL = "SYMBOL"
    EXTERNAL_REF = "EXTERNAL_REF"


class BindingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DesignRuleCategory(StrEnum):
    VISUAL = "VISUAL"
    GAMEPLAY = "GAMEPLAY"
    TECHNICAL = "TECHNICAL"
    PERFORMANCE = "PERFORMANCE"
    AUDIO = "AUDIO"
    UI = "UI"
    WORLD = "WORLD"
    NAMING = "NAMING"
    ACCESSIBILITY = "ACCESSIBILITY"
    PROCESS = "PROCESS"
    OTHER = "OTHER"


class DesignRuleAuthority(StrEnum):
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    PRINCIPLE = "PRINCIPLE"
    CONVENTION = "CONVENTION"
    TARGET = "TARGET"


class DesignRuleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ImpactDirection(StrEnum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"
    BOTH = "BOTH"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_sha256(value: str | None, *, field: str = "content hash") -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[len(_SHA256_PREFIX) :])
    ):
        raise ValueError(f"{field} must be a lowercase sha256: digest or null")
    return value


def bounded_text(value: str, *, field: str, maximum: int = _MAX_TEXT, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds character limit ({len(value)} > {maximum})")
    if "\x00" in value:
        raise ValueError(f"{field} may not contain NUL")
    return value


def bounded_metadata(value: dict[str, object] | None) -> dict[str, object]:
    metadata = {} if value is None else value
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    size = len(canonical_bytes(metadata))
    if size > _MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds byte limit ({size} > {_MAX_METADATA_BYTES})")
    return json.loads(canonical_bytes(metadata).decode("utf-8"))


@dataclass(frozen=True)
class ImpactQuery:
    root_entity_ids: tuple[str, ...]
    relation_types: tuple[RelationType, ...] = tuple(RelationType)
    direction: ImpactDirection = ImpactDirection.BOTH
    max_depth: int = 4
    max_entities: int = 256
    max_relations: int = 1024
    max_bindings: int = 1024
    max_rules: int = 256
    include_bindings: bool = True
    include_design_rules: bool = True

    def __post_init__(self) -> None:
        roots = tuple(self.root_entity_ids)
        if not roots or len(roots) > _MAX_ROOTS:
            raise ValueError(f"impact query requires 1..{_MAX_ROOTS} roots")
        if len(roots) != len(set(roots)):
            raise ValueError("impact query contains duplicate roots")
        if any(not validate_id(value, IdKind.ENTITY) for value in roots):
            raise ValueError("impact query roots must be ENTITY IDs")
        relation_types = tuple(self.relation_types)
        if not relation_types:
            raise ValueError("impact query requires at least one relation type")
        if any(not isinstance(value, RelationType) for value in relation_types):
            raise ValueError("impact query relation_types must contain RelationType values")
        if len(relation_types) != len(set(relation_types)):
            raise ValueError("impact query contains duplicate relation types")
        if not isinstance(self.direction, ImpactDirection):
            raise ValueError("impact query direction must be an ImpactDirection")
        for value, name, maximum in (
            (self.max_depth, "max_depth", 32),
            (self.max_entities, "max_entities", 10000),
            (self.max_relations, "max_relations", 50000),
            (self.max_bindings, "max_bindings", 50000),
            (self.max_rules, "max_rules", 10000),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
                raise ValueError(f"impact query {name} must be between 1 and {maximum}")
        for value, name in (
            (self.include_bindings, "include_bindings"),
            (self.include_design_rules, "include_design_rules"),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"impact query {name} must be boolean")
        object.__setattr__(self, "root_entity_ids", tuple(sorted(roots)))
        object.__setattr__(self, "relation_types", tuple(sorted(relation_types, key=lambda item: item.value)))

    def to_dict(self) -> dict[str, object]:
        return {
            "root_entity_ids": list(self.root_entity_ids),
            "relation_types": [value.value for value in self.relation_types],
            "direction": self.direction.value,
            "max_depth": self.max_depth,
            "max_entities": self.max_entities,
            "max_relations": self.max_relations,
            "max_bindings": self.max_bindings,
            "max_rules": self.max_rules,
            "include_bindings": self.include_bindings,
            "include_design_rules": self.include_design_rules,
        }


@dataclass(frozen=True)
class ImpactEntity:
    entity_id: str
    depth: int

    def __post_init__(self) -> None:
        if not validate_id(self.entity_id, IdKind.ENTITY):
            raise ValueError("impact entity_id must be an ENTITY ID")
        if not isinstance(self.depth, int) or isinstance(self.depth, bool) or self.depth < 0:
            raise ValueError("impact entity depth must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return {"entity_id": self.entity_id, "depth": self.depth}


@dataclass(frozen=True)
class ImpactReport:
    query: ImpactQuery
    entities: tuple[ImpactEntity, ...]
    relation_ids: tuple[str, ...]
    binding_ids: tuple[str, ...]
    design_rule_ids: tuple[str, ...]
    truncated_entities: bool = False
    truncated_relations: bool = False
    truncated_bindings: bool = False
    truncated_rules: bool = False
    cycle_edges_observed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.query, ImpactQuery):
            raise ValueError("impact report query must be an ImpactQuery")
        entities = tuple(sorted(self.entities, key=lambda value: (value.depth, value.entity_id)))
        if len({value.entity_id for value in entities}) != len(entities):
            raise ValueError("impact report contains duplicate entities")
        for values, kind, field in (
            (self.relation_ids, IdKind.ENTITY_RELATION, "relation_ids"),
            (self.binding_ids, IdKind.ENTITY_BINDING, "binding_ids"),
            (self.design_rule_ids, IdKind.DESIGN_RULE, "design_rule_ids"),
        ):
            if len(values) != len(set(values)) or any(not validate_id(value, kind) for value in values):
                raise ValueError(f"impact report {field} are invalid or duplicate")
        flags = (
            self.truncated_entities,
            self.truncated_relations,
            self.truncated_bindings,
            self.truncated_rules,
            self.cycle_edges_observed,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise ValueError("impact report flags must be boolean")
        object.__setattr__(self, "entities", entities)
        object.__setattr__(self, "relation_ids", tuple(sorted(self.relation_ids)))
        object.__setattr__(self, "binding_ids", tuple(sorted(self.binding_ids)))
        object.__setattr__(self, "design_rule_ids", tuple(sorted(self.design_rule_ids)))

    def _content_dict(self) -> dict[str, object]:
        return {
            "query": self.query.to_dict(),
            "entities": [value.to_dict() for value in self.entities],
            "relation_ids": list(self.relation_ids),
            "binding_ids": list(self.binding_ids),
            "design_rule_ids": list(self.design_rule_ids),
            "truncated_entities": self.truncated_entities,
            "truncated_relations": self.truncated_relations,
            "truncated_bindings": self.truncated_bindings,
            "truncated_rules": self.truncated_rules,
            "cycle_edges_observed": self.cycle_edges_observed,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}
