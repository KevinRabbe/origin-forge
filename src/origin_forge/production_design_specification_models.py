from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .production_planning_models import PlanningEvidenceRef


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
_LOCAL_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT_CHARS = 4096
_MAX_ITEM_TEXT_CHARS = 2048
_MAX_EVIDENCE_REFS = 128
_MAX_CAPABILITIES = 64
_MAX_REQUIREMENTS = 64
_MAX_DELIVERABLES = 64
_MAX_ACCEPTANCE = 32
_MAX_CONSTRAINTS = 32
_MAX_ITEM_CAPABILITIES = 16
_MAX_PROPOSAL_BYTES = 256 * 1024


class DesignSpecificationModelError(ValueError):
    pass


class DesignSpecificationAuditStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


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
        raise DesignSpecificationModelError(
            "design specification data is not canonical JSON"
        ) from exc
    return data


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise DesignSpecificationModelError(
            f"{label} must be a lowercase SHA-256 hex digest"
        )
    return value


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise DesignSpecificationModelError(f"{label} must be a bounded identity token")
    return value


def _local_key(value: str, label: str) -> str:
    if not isinstance(value, str) or not _LOCAL_KEY_RE.fullmatch(value):
        raise DesignSpecificationModelError(f"{label} must be a bounded local key")
    return value


def _exact_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise DesignSpecificationModelError(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


def _text(value: str, label: str, *, maximum: int = _MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DesignSpecificationModelError(f"{label} must be non-empty text")
    normalized = value.strip()
    if "\x00" in normalized or len(normalized) > maximum:
        raise DesignSpecificationModelError(f"{label} is outside text bounds")
    return normalized


def _text_items(
    values: Iterable[str],
    label: str,
    *,
    maximum_items: int,
    require_one: bool = False,
) -> tuple[str, ...]:
    items = tuple(values)
    if len(items) > maximum_items or (require_one and not items):
        raise DesignSpecificationModelError(f"{label} are outside bounds")
    normalized = tuple(
        _text(item, label, maximum=_MAX_ITEM_TEXT_CHARS) for item in items
    )
    if len(normalized) != len(set(normalized)):
        raise DesignSpecificationModelError(f"{label} contain duplicates")
    return normalized


def _evidence_refs(
    values: Iterable[PlanningEvidenceRef],
    label: str,
) -> tuple[PlanningEvidenceRef, ...]:
    refs = tuple(values)
    if len(refs) > _MAX_EVIDENCE_REFS or not all(
        isinstance(value, PlanningEvidenceRef) for value in refs
    ):
        raise DesignSpecificationModelError(f"{label} are outside bounds")
    keys = [value.key for value in refs]
    if len(keys) != len(set(keys)):
        raise DesignSpecificationModelError(f"{label} contain duplicates")
    return tuple(sorted(refs, key=lambda value: value.key))


@dataclass(frozen=True)
class DesignSpecificationInput:
    design_input_id: str
    project_id: str
    goal_id: str
    goal_revision: int
    goal_content_hash: str
    verified_state_refs: tuple[PlanningEvidenceRef, ...]
    active_design_rule_refs: tuple[PlanningEvidenceRef, ...]
    project_intelligence_hash: str
    capability_catalog_hash: str
    capability_ids: tuple[str, ...]
    model_policy_hash: str
    resource_policy_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.design_input_id, IdKind.DESIGN_SPECIFICATION_INPUT):
            raise DesignSpecificationModelError("design_input_id must be a DESIGNIN ID")
        if not validate_id(self.project_id, IdKind.PROJECT):
            raise DesignSpecificationModelError("project_id must be a PROJECT ID")
        if not validate_id(self.goal_id, IdKind.GOAL):
            raise DesignSpecificationModelError("goal_id must be a GOAL ID")
        _exact_int(self.goal_revision, "goal_revision", 0, 2_147_483_647)
        for field in (
            "goal_content_hash",
            "project_intelligence_hash",
            "capability_catalog_hash",
            "model_policy_hash",
            "resource_policy_hash",
        ):
            _sha256(getattr(self, field), field)
        object.__setattr__(
            self,
            "verified_state_refs",
            _evidence_refs(self.verified_state_refs, "verified_state_refs"),
        )
        object.__setattr__(
            self,
            "active_design_rule_refs",
            _evidence_refs(self.active_design_rule_refs, "active_design_rule_refs"),
        )
        capabilities = tuple(_token(value, "capability_id") for value in self.capability_ids)
        if not capabilities or len(capabilities) > _MAX_CAPABILITIES:
            raise DesignSpecificationModelError("capability_ids are outside bounds")
        if len(capabilities) != len(set(capabilities)):
            raise DesignSpecificationModelError("capability_ids contain duplicates")
        object.__setattr__(self, "capability_ids", tuple(sorted(capabilities)))

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        goal_id: str,
        goal_revision: int,
        goal_content_hash: str,
        verified_state_refs: Iterable[PlanningEvidenceRef],
        active_design_rule_refs: Iterable[PlanningEvidenceRef],
        project_intelligence_hash: str,
        capability_catalog_hash: str,
        capability_ids: Iterable[str],
        model_policy_hash: str,
        resource_policy_hash: str,
    ) -> "DesignSpecificationInput":
        return cls(
            design_input_id=new_id(IdKind.DESIGN_SPECIFICATION_INPUT),
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            goal_content_hash=goal_content_hash,
            verified_state_refs=tuple(verified_state_refs),
            active_design_rule_refs=tuple(active_design_rule_refs),
            project_intelligence_hash=project_intelligence_hash,
            capability_catalog_hash=capability_catalog_hash,
            capability_ids=tuple(capability_ids),
            model_policy_hash=model_policy_hash,
            resource_policy_hash=resource_policy_hash,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "design_input_id": self.design_input_id,
            "project_id": self.project_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_content_hash": self.goal_content_hash,
            "verified_state_refs": [value.to_dict() for value in self.verified_state_refs],
            "active_design_rule_refs": [value.to_dict() for value in self.active_design_rule_refs],
            "project_intelligence_hash": self.project_intelligence_hash,
            "capability_catalog_hash": self.capability_catalog_hash,
            "capability_ids": list(self.capability_ids),
            "model_policy_hash": self.model_policy_hash,
            "resource_policy_hash": self.resource_policy_hash,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class DesignRequirement:
    key: str
    statement: str
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _local_key(self.key, "requirement key"))
        object.__setattr__(self, "statement", _text(self.statement, "requirement statement"))
        object.__setattr__(
            self,
            "acceptance_criteria",
            _text_items(
                self.acceptance_criteria,
                "requirement acceptance_criteria",
                maximum_items=_MAX_ACCEPTANCE,
                require_one=True,
            ),
        )
        object.__setattr__(
            self,
            "constraints",
            _text_items(
                self.constraints,
                "requirement constraints",
                maximum_items=_MAX_CONSTRAINTS,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "statement": self.statement,
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
        }


@dataclass(frozen=True)
class DesignAnimationIntent:
    """Bounded semantic animation input authored by the accepted design."""

    name: str
    frame_count: int
    frame_duration_ms: int = 100
    loop_mode: str = "LOOP"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "animation name", maximum=256))
        object.__setattr__(self, "frame_count", _exact_int(self.frame_count, "animation frame_count", 1, 1024))
        object.__setattr__(
            self,
            "frame_duration_ms",
            _exact_int(self.frame_duration_ms, "animation frame_duration_ms", 1, 60_000),
        )
        if self.loop_mode not in {"ONCE", "LOOP", "PING_PONG"}:
            raise DesignSpecificationModelError("animation loop_mode is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "frame_count": self.frame_count,
            "frame_duration_ms": self.frame_duration_ms,
            "loop_mode": self.loop_mode,
        }


@dataclass(frozen=True)
class DesignDeliverable:
    key: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    animation_intents: tuple[DesignAnimationIntent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _local_key(self.key, "deliverable key"))
        object.__setattr__(self, "objective", _text(self.objective, "deliverable objective"))
        object.__setattr__(
            self,
            "acceptance_criteria",
            _text_items(
                self.acceptance_criteria,
                "deliverable acceptance_criteria",
                maximum_items=_MAX_ACCEPTANCE,
                require_one=True,
            ),
        )
        object.__setattr__(
            self,
            "constraints",
            _text_items(
                self.constraints,
                "deliverable constraints",
                maximum_items=_MAX_CONSTRAINTS,
            ),
        )
        capabilities = tuple(
            _token(value, "required_capability") for value in self.required_capabilities
        )
        if len(capabilities) > _MAX_ITEM_CAPABILITIES:
            raise DesignSpecificationModelError("required_capabilities are outside bounds")
        if len(capabilities) != len(set(capabilities)):
            raise DesignSpecificationModelError("required_capabilities contain duplicates")
        object.__setattr__(self, "required_capabilities", tuple(sorted(capabilities)))
        animations = tuple(self.animation_intents)
        if len(animations) > 256 or not all(
            isinstance(value, DesignAnimationIntent) for value in animations
        ):
            raise DesignSpecificationModelError("animation_intents are outside bounds")
        names = [value.name for value in animations]
        if len(names) != len(set(names)):
            raise DesignSpecificationModelError("animation_intents contain duplicate names")
        object.__setattr__(self, "animation_intents", tuple(sorted(animations, key=lambda value: value.name)))

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "key": self.key,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
            "required_capabilities": list(self.required_capabilities),
        }
        if self.animation_intents:
            result["animation_intents"] = [value.to_dict() for value in self.animation_intents]
        return result


@dataclass(frozen=True)
class DesignSpecification:
    design_specification_id: str
    design_input_id: str
    design_input_hash: str
    run_id: str
    model_id: str
    model_hash: str | None
    summary: str
    requirements: tuple[DesignRequirement, ...]
    deliverables: tuple[DesignDeliverable, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.design_specification_id, IdKind.DESIGN_SPECIFICATION):
            raise DesignSpecificationModelError(
                "design_specification_id must be a DESIGNSPEC ID"
            )
        if not validate_id(self.design_input_id, IdKind.DESIGN_SPECIFICATION_INPUT):
            raise DesignSpecificationModelError("design_input_id must be a DESIGNIN ID")
        if not validate_id(self.run_id, IdKind.RUN):
            raise DesignSpecificationModelError("run_id must be a RUN ID")
        _sha256(self.design_input_hash, "design_input_hash")
        object.__setattr__(self, "model_id", _text(self.model_id, "model_id", maximum=256))
        if self.model_hash is not None:
            object.__setattr__(
                self,
                "model_hash",
                _text(self.model_hash, "model_hash", maximum=512),
            )
        object.__setattr__(self, "summary", _text(self.summary, "summary"))

        requirements = tuple(self.requirements)
        deliverables = tuple(self.deliverables)
        if not 1 <= len(requirements) <= _MAX_REQUIREMENTS or not all(
            isinstance(value, DesignRequirement) for value in requirements
        ):
            raise DesignSpecificationModelError("requirements are outside bounds")
        if not 1 <= len(deliverables) <= _MAX_DELIVERABLES or not all(
            isinstance(value, DesignDeliverable) for value in deliverables
        ):
            raise DesignSpecificationModelError("deliverables are outside bounds")
        for values, label in ((requirements, "requirements"), (deliverables, "deliverables")):
            keys = [value.key for value in values]
            if len(keys) != len(set(keys)):
                raise DesignSpecificationModelError(f"{label} contain duplicate local keys")
        object.__setattr__(self, "requirements", tuple(sorted(requirements, key=lambda value: value.key)))
        object.__setattr__(self, "deliverables", tuple(sorted(deliverables, key=lambda value: value.key)))
        if len(canonical_bytes(self.to_dict())) > _MAX_PROPOSAL_BYTES:
            raise DesignSpecificationModelError("canonical design specification exceeds byte limit")

    @classmethod
    def create(
        cls,
        *,
        design_input: DesignSpecificationInput,
        run_id: str,
        model_id: str,
        model_hash: str | None,
        summary: str,
        requirements: Iterable[DesignRequirement],
        deliverables: Iterable[DesignDeliverable],
    ) -> "DesignSpecification":
        if not isinstance(design_input, DesignSpecificationInput):
            raise TypeError("design_input must be a DesignSpecificationInput")
        value = cls(
            design_specification_id=new_id(IdKind.DESIGN_SPECIFICATION),
            design_input_id=design_input.design_input_id,
            design_input_hash=design_input.content_hash,
            run_id=run_id,
            model_id=model_id,
            model_hash=model_hash,
            summary=summary,
            requirements=tuple(requirements),
            deliverables=tuple(deliverables),
        )
        value.bind(design_input)
        return value

    def bind(self, design_input: DesignSpecificationInput) -> None:
        if not isinstance(design_input, DesignSpecificationInput):
            raise TypeError("design_input must be a DesignSpecificationInput")
        if self.design_input_id != design_input.design_input_id:
            raise DesignSpecificationModelError("specification design_input_id does not match")
        if self.design_input_hash != design_input.content_hash:
            raise DesignSpecificationModelError("specification design_input_hash does not match")
        allowed = set(design_input.capability_ids)
        unknown = sorted(
            {
                capability
                for deliverable in self.deliverables
                for capability in deliverable.required_capabilities
            }
            - allowed
        )
        if unknown:
            raise DesignSpecificationModelError(
                "specification requests unknown capabilities: " + ", ".join(unknown)
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "design_specification_id": self.design_specification_id,
            "design_input_id": self.design_input_id,
            "design_input_hash": self.design_input_hash,
            "run_id": self.run_id,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "specification": {
                "summary": self.summary,
                "requirements": [value.to_dict() for value in self.requirements],
                "deliverables": [value.to_dict() for value in self.deliverables],
            },
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class DesignSpecificationAudit:
    audit_id: str
    design_input_id: str
    design_input_hash: str
    design_specification_id: str
    design_specification_hash: str
    status: DesignSpecificationAuditStatus
    requirement_count: int
    deliverable_count: int
    required_capability_count: int
    canonical_byte_count: int
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.audit_id, IdKind.DESIGN_SPECIFICATION_AUDIT):
            raise DesignSpecificationModelError("audit_id must be a DESIGNAUD ID")
        if not validate_id(self.design_input_id, IdKind.DESIGN_SPECIFICATION_INPUT):
            raise DesignSpecificationModelError("audit design_input_id must be a DESIGNIN ID")
        if not validate_id(self.design_specification_id, IdKind.DESIGN_SPECIFICATION):
            raise DesignSpecificationModelError(
                "audit design_specification_id must be a DESIGNSPEC ID"
            )
        _sha256(self.design_input_hash, "audit design_input_hash")
        _sha256(self.design_specification_hash, "audit design_specification_hash")
        if not isinstance(self.status, DesignSpecificationAuditStatus):
            raise DesignSpecificationModelError("audit status is invalid")
        _exact_int(self.requirement_count, "requirement_count", 0, _MAX_REQUIREMENTS)
        _exact_int(self.deliverable_count, "deliverable_count", 0, _MAX_DELIVERABLES)
        _exact_int(
            self.required_capability_count,
            "required_capability_count",
            0,
            _MAX_DELIVERABLES * _MAX_ITEM_CAPABILITIES,
        )
        _exact_int(self.canonical_byte_count, "canonical_byte_count", 1, _MAX_PROPOSAL_BYTES)
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _text(self.failure_reason, "failure_reason", maximum=1000),
            )
        if self.status is DesignSpecificationAuditStatus.PASS and self.failure_reason is not None:
            raise DesignSpecificationModelError("passing audit cannot have failure_reason")
        if self.status is DesignSpecificationAuditStatus.FAIL and self.failure_reason is None:
            raise DesignSpecificationModelError("failing audit requires failure_reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_id": self.audit_id,
            "design_input_id": self.design_input_id,
            "design_input_hash": self.design_input_hash,
            "design_specification_id": self.design_specification_id,
            "design_specification_hash": self.design_specification_hash,
            "status": self.status.value,
            "requirement_count": self.requirement_count,
            "deliverable_count": self.deliverable_count,
            "required_capability_count": self.required_capability_count,
            "canonical_byte_count": self.canonical_byte_count,
            "failure_reason": self.failure_reason,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


def audit_design_specification(
    design_input: DesignSpecificationInput,
    specification: DesignSpecification,
) -> DesignSpecificationAudit:
    if not isinstance(design_input, DesignSpecificationInput):
        raise TypeError("design_input must be a DesignSpecificationInput")
    if not isinstance(specification, DesignSpecification):
        raise TypeError("specification must be a DesignSpecification")
    specification.bind(design_input)
    capabilities = {
        capability
        for deliverable in specification.deliverables
        for capability in deliverable.required_capabilities
    }
    return DesignSpecificationAudit(
        audit_id=new_id(IdKind.DESIGN_SPECIFICATION_AUDIT),
        design_input_id=design_input.design_input_id,
        design_input_hash=design_input.content_hash,
        design_specification_id=specification.design_specification_id,
        design_specification_hash=specification.content_hash,
        status=DesignSpecificationAuditStatus.PASS,
        requirement_count=len(specification.requirements),
        deliverable_count=len(specification.deliverables),
        required_capability_count=len(capabilities),
        canonical_byte_count=len(canonical_bytes(specification.to_dict())),
        failure_reason=None,
    )
