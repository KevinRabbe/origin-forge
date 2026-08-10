from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .dream_models import DreamDownstreamGate, EvidenceRef
from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import content_hash


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PAYLOAD_BYTES = 32 * 1024
_MAX_JSON_DEPTH = 8
_MAX_JSON_NODES = 512
_MAX_SOURCE_EVIDENCE = 64
_MAX_PLAN_EVIDENCE = 128
_MAX_METRICS = 32
_MAX_RISKS = 16
_MAX_EXPECTATIONS = 16
_MAX_TEXT = 4096
_MAX_THRESHOLD = 1_000_000_000_000


class HarnessWorkshopModelError(ValueError):
    pass


class HarnessComponentKind(StrEnum):
    SKILL = "SKILL"
    PROMPT = "PROMPT"
    CONTEXT_STRATEGY = "CONTEXT_STRATEGY"
    ROUTING_POLICY = "ROUTING_POLICY"
    SPECIALIST_CONTRACT = "SPECIALIST_CONTRACT"
    MINI_WORKFLOW = "MINI_WORKFLOW"


class WorkshopEvaluatorFamily(StrEnum):
    SKILL_BENCHMARK = "SKILL_BENCHMARK"
    PROMPT_BENCHMARK = "PROMPT_BENCHMARK"
    CONTEXT_BENCHMARK = "CONTEXT_BENCHMARK"
    ROUTING_BENCHMARK = "ROUTING_BENCHMARK"
    SPECIALIST_BENCHMARK = "SPECIALIST_BENCHMARK"
    MINI_WORKFLOW_BENCHMARK = "MINI_WORKFLOW_BENCHMARK"


class ExpectedEffectDirection(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    PRESERVE = "PRESERVE"


class MetricDirection(StrEnum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"
    MUST_NOT_REGRESS = "MUST_NOT_REGRESS"


class RegressionPolicy(StrEnum):
    REGRESSION_DOMINANT = "REGRESSION_DOMINANT"


_EVALUATOR_BY_COMPONENT = {
    HarnessComponentKind.SKILL: WorkshopEvaluatorFamily.SKILL_BENCHMARK,
    HarnessComponentKind.PROMPT: WorkshopEvaluatorFamily.PROMPT_BENCHMARK,
    HarnessComponentKind.CONTEXT_STRATEGY: WorkshopEvaluatorFamily.CONTEXT_BENCHMARK,
    HarnessComponentKind.ROUTING_POLICY: WorkshopEvaluatorFamily.ROUTING_BENCHMARK,
    HarnessComponentKind.SPECIALIST_CONTRACT: WorkshopEvaluatorFamily.SPECIALIST_BENCHMARK,
    HarnessComponentKind.MINI_WORKFLOW: WorkshopEvaluatorFamily.MINI_WORKFLOW_BENCHMARK,
}

_DREAM_GATE_BY_COMPONENT = {
    HarnessComponentKind.SKILL: DreamDownstreamGate.SKILL_EVALUATION,
    HarnessComponentKind.CONTEXT_STRATEGY: DreamDownstreamGate.CONTEXT_BENCHMARK,
    HarnessComponentKind.ROUTING_POLICY: DreamDownstreamGate.ROUTING_BENCHMARK,
    HarnessComponentKind.PROMPT: DreamDownstreamGate.ENGINEERING_REVIEW,
    HarnessComponentKind.SPECIALIST_CONTRACT: DreamDownstreamGate.ENGINEERING_REVIEW,
    HarnessComponentKind.MINI_WORKFLOW: DreamDownstreamGate.ENGINEERING_REVIEW,
}


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise HarnessWorkshopModelError(f"{label} must be a bounded identity token")
    return value


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise HarnessWorkshopModelError(f"{label} must be a lowercase sha256 hash")
    return value


def _text(value: str, label: str, *, minimum: int = 1, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise HarnessWorkshopModelError(f"{label} must be text")
    normalized = value.strip()
    if not minimum <= len(normalized) <= maximum:
        raise HarnessWorkshopModelError(
            f"{label} must contain from {minimum} to {maximum} characters"
        )
    return normalized


def _exact_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise HarnessWorkshopModelError(f"{label} must be from {minimum} to {maximum}")
    return value


def _evidence_tuple(
    values: Iterable[EvidenceRef],
    *,
    label: str,
    maximum: int,
    allow_empty: bool,
    forbidden_ref_id: str | None = None,
) -> tuple[EvidenceRef, ...]:
    refs = tuple(values)
    if not allow_empty and not refs:
        raise HarnessWorkshopModelError(f"{label} may not be empty")
    if len(refs) > maximum:
        raise HarnessWorkshopModelError(f"{label} exceeds limit")
    if not all(isinstance(value, EvidenceRef) for value in refs):
        raise HarnessWorkshopModelError(f"{label} must contain EvidenceRef objects")
    keys = [value.key for value in refs]
    if len(set(keys)) != len(keys):
        raise HarnessWorkshopModelError(f"{label} contains duplicate evidence")
    if forbidden_ref_id is not None and any(
        value.ref_id == forbidden_ref_id for value in refs
    ):
        raise HarnessWorkshopModelError(f"{label} may not self-reference the candidate")
    return tuple(sorted(refs, key=lambda value: value.key))


def _validate_json_value(value: object, *, depth: int = 0, nodes: list[int]) -> None:
    nodes[0] += 1
    if nodes[0] > _MAX_JSON_NODES:
        raise HarnessWorkshopModelError("candidate payload exceeds JSON node limit")
    if depth > _MAX_JSON_DEPTH:
        raise HarnessWorkshopModelError("candidate payload exceeds JSON depth limit")
    if value is None or type(value) in (bool, int):
        return
    if isinstance(value, float):
        raise HarnessWorkshopModelError("candidate payload may not contain floating-point values")
    if isinstance(value, str):
        if len(value) > _MAX_TEXT:
            raise HarnessWorkshopModelError("candidate payload string exceeds limit")
        return
    if isinstance(value, list):
        if len(value) > 128:
            raise HarnessWorkshopModelError("candidate payload list exceeds limit")
        for item in value:
            _validate_json_value(item, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, dict):
        if len(value) > 128:
            raise HarnessWorkshopModelError("candidate payload object exceeds key limit")
        for key, item in value.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 128:
                raise HarnessWorkshopModelError(
                    "candidate payload keys must be bounded non-empty strings"
                )
            _validate_json_value(item, depth=depth + 1, nodes=nodes)
        return
    raise HarnessWorkshopModelError(
        "candidate payload must contain only exact JSON data types"
    )


def canonical_payload_json(value: object) -> str:
    if not isinstance(value, dict):
        raise HarnessWorkshopModelError("candidate payload must be a JSON object")
    _validate_json_value(value, nodes=[0])
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise HarnessWorkshopModelError("candidate payload is not canonical JSON data") from exc
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise HarnessWorkshopModelError("candidate payload exceeds byte limit")
    return encoded


def payload_hash(payload_json: str) -> str:
    if not isinstance(payload_json, str):
        raise TypeError("payload_json must be text")
    return "sha256:" + hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExpectedMetricEffect:
    metric_id: str
    direction: ExpectedEffectDirection
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _token(self.metric_id, "metric_id"))
        if not isinstance(self.direction, ExpectedEffectDirection):
            raise HarnessWorkshopModelError("expected metric direction is invalid")
        object.__setattr__(
            self,
            "rationale",
            _text(self.rationale, "expected metric rationale", maximum=1000),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "direction": self.direction.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class DreamOriginRef:
    candidate_id: str
    candidate_hash: str
    required_gate: DreamDownstreamGate

    def __post_init__(self) -> None:
        if not validate_id(self.candidate_id, IdKind.DREAM_CANDIDATE):
            raise HarnessWorkshopModelError("Dream origin must reference a DREAM candidate ID")
        object.__setattr__(
            self, "candidate_hash", _sha256(self.candidate_hash, "Dream candidate hash")
        )
        if not isinstance(self.required_gate, DreamDownstreamGate):
            raise HarnessWorkshopModelError("Dream origin required_gate is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "required_gate": self.required_gate.value,
        }


@dataclass(frozen=True)
class HarnessImprovementCandidate:
    candidate_id: str
    component_kind: HarnessComponentKind
    target_component_id: str
    target_version: str
    target_hash: str
    baseline_payload_hash: str
    candidate_payload_json: str
    hypothesis: str
    source_evidence: tuple[EvidenceRef, ...]
    expected_effects: tuple[ExpectedMetricEffect, ...]
    known_risks: tuple[str, ...]
    evaluator_family: WorkshopEvaluatorFamily
    dream_origin: DreamOriginRef | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.candidate_id, IdKind.IMPROVEMENT_CANDIDATE):
            raise HarnessWorkshopModelError("candidate_id must be a HIC ID")
        if not isinstance(self.component_kind, HarnessComponentKind):
            raise HarnessWorkshopModelError("component_kind is invalid")
        object.__setattr__(
            self,
            "target_component_id",
            _token(self.target_component_id, "target_component_id"),
        )
        object.__setattr__(self, "target_version", _token(self.target_version, "target_version"))
        object.__setattr__(self, "target_hash", _sha256(self.target_hash, "target_hash"))
        object.__setattr__(
            self,
            "baseline_payload_hash",
            _sha256(self.baseline_payload_hash, "baseline_payload_hash"),
        )
        try:
            decoded_payload = json.loads(self.candidate_payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise HarnessWorkshopModelError("candidate_payload_json is invalid JSON") from exc
        canonical = canonical_payload_json(decoded_payload)
        if canonical != self.candidate_payload_json:
            raise HarnessWorkshopModelError("candidate_payload_json must be canonical JSON")
        if payload_hash(canonical) == self.baseline_payload_hash:
            raise HarnessWorkshopModelError("candidate payload must differ from baseline payload")
        object.__setattr__(self, "hypothesis", _text(self.hypothesis, "hypothesis", minimum=8, maximum=2000))
        object.__setattr__(
            self,
            "source_evidence",
            _evidence_tuple(
                self.source_evidence,
                label="source_evidence",
                maximum=_MAX_SOURCE_EVIDENCE,
                allow_empty=False,
                forbidden_ref_id=self.candidate_id,
            ),
        )
        effects = tuple(self.expected_effects)
        if len(effects) > _MAX_EXPECTATIONS or not all(
            isinstance(value, ExpectedMetricEffect) for value in effects
        ):
            raise HarnessWorkshopModelError("expected_effects are outside bounds")
        if len({value.metric_id for value in effects}) != len(effects):
            raise HarnessWorkshopModelError("expected_effects contain duplicate metric IDs")
        object.__setattr__(
            self, "expected_effects", tuple(sorted(effects, key=lambda value: value.metric_id))
        )
        risks = tuple(_text(value, "known risk", maximum=1000) for value in self.known_risks)
        if len(risks) > _MAX_RISKS:
            raise HarnessWorkshopModelError("known_risks exceed limit")
        if len(set(risks)) != len(risks):
            raise HarnessWorkshopModelError("known_risks contain duplicates")
        object.__setattr__(self, "known_risks", tuple(sorted(risks)))
        expected_evaluator = _EVALUATOR_BY_COMPONENT[self.component_kind]
        if self.evaluator_family is not expected_evaluator:
            raise HarnessWorkshopModelError(
                "candidate evaluator family does not match component kind"
            )
        if self.dream_origin is not None:
            if not isinstance(self.dream_origin, DreamOriginRef):
                raise HarnessWorkshopModelError("dream_origin must be a DreamOriginRef")
            expected_gate = _DREAM_GATE_BY_COMPONENT[self.component_kind]
            if self.dream_origin.required_gate is not expected_gate:
                raise HarnessWorkshopModelError(
                    "Dream downstream gate does not match workshop component kind"
                )

    @classmethod
    def create(
        cls,
        *,
        component_kind: HarnessComponentKind,
        target_component_id: str,
        target_version: str,
        target_hash: str,
        baseline_payload_hash: str,
        candidate_payload: object,
        hypothesis: str,
        source_evidence: Iterable[EvidenceRef],
        expected_effects: Iterable[ExpectedMetricEffect] = (),
        known_risks: Iterable[str] = (),
        dream_origin: DreamOriginRef | None = None,
    ) -> "HarnessImprovementCandidate":
        if not isinstance(component_kind, HarnessComponentKind):
            raise HarnessWorkshopModelError("component_kind is invalid")
        return cls(
            candidate_id=new_id(IdKind.IMPROVEMENT_CANDIDATE),
            component_kind=component_kind,
            target_component_id=target_component_id,
            target_version=target_version,
            target_hash=target_hash,
            baseline_payload_hash=baseline_payload_hash,
            candidate_payload_json=canonical_payload_json(candidate_payload),
            hypothesis=hypothesis,
            source_evidence=tuple(source_evidence),
            expected_effects=tuple(expected_effects),
            known_risks=tuple(known_risks),
            evaluator_family=_EVALUATOR_BY_COMPONENT[component_kind],
            dream_origin=dream_origin,
        )

    @property
    def candidate_payload_hash(self) -> str:
        return payload_hash(self.candidate_payload_json)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "component_kind": self.component_kind.value,
            "target_component_id": self.target_component_id,
            "target_version": self.target_version,
            "target_hash": self.target_hash,
            "baseline_payload_hash": self.baseline_payload_hash,
            "candidate_payload": json.loads(self.candidate_payload_json),
            "candidate_payload_hash": self.candidate_payload_hash,
            "hypothesis": self.hypothesis,
            "source_evidence": [value.to_dict() for value in self.source_evidence],
            "expected_effects": [value.to_dict() for value in self.expected_effects],
            "known_risks": list(self.known_risks),
            "evaluator_family": self.evaluator_family.value,
            "dream_origin": self.dream_origin.to_dict() if self.dream_origin else None,
            "production_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class WorkshopMetricCriterion:
    metric_id: str
    direction: MetricDirection
    minimum_improvement: int
    maximum_regression: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _token(self.metric_id, "metric_id"))
        if not isinstance(self.direction, MetricDirection):
            raise HarnessWorkshopModelError("metric direction is invalid")
        _exact_int(
            self.minimum_improvement,
            "minimum_improvement",
            0,
            _MAX_THRESHOLD,
        )
        _exact_int(
            self.maximum_regression,
            "maximum_regression",
            0,
            _MAX_THRESHOLD,
        )
        if (
            self.direction is MetricDirection.MUST_NOT_REGRESS
            and self.maximum_regression != 0
        ):
            raise HarnessWorkshopModelError(
                "MUST_NOT_REGRESS metric must use zero maximum_regression"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "direction": self.direction.value,
            "minimum_improvement": self.minimum_improvement,
            "maximum_regression": self.maximum_regression,
        }


@dataclass(frozen=True)
class WorkshopCostCeilings:
    model_calls: int
    input_tokens: int
    output_tokens: int
    wall_time_ms: int
    resource_units: int

    def __post_init__(self) -> None:
        for name, maximum in (
            ("model_calls", 1_000_000),
            ("input_tokens", 10_000_000_000),
            ("output_tokens", 10_000_000_000),
            ("wall_time_ms", 31_536_000_000),
            ("resource_units", 10_000_000_000),
        ):
            _exact_int(getattr(self, name), name, 0, maximum)

    def to_dict(self) -> dict[str, int]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_time_ms": self.wall_time_ms,
            "resource_units": self.resource_units,
        }


@dataclass(frozen=True)
class WorkshopEvaluationPlan:
    plan_id: str
    candidate_id: str
    candidate_hash: str
    evaluator_family: WorkshopEvaluatorFamily
    evaluator_protocol: str
    evaluation_evidence: tuple[EvidenceRef, ...]
    criteria: tuple[WorkshopMetricCriterion, ...]
    cost_ceilings: WorkshopCostCeilings
    regression_policy: RegressionPolicy = RegressionPolicy.REGRESSION_DOMINANT

    def __post_init__(self) -> None:
        if not validate_id(self.plan_id, IdKind.WORKSHOP_EVALUATION_PLAN):
            raise HarnessWorkshopModelError("plan_id must be a HPLAN ID")
        if not validate_id(self.candidate_id, IdKind.IMPROVEMENT_CANDIDATE):
            raise HarnessWorkshopModelError("candidate_id must be a HIC ID")
        object.__setattr__(
            self, "candidate_hash", _sha256(self.candidate_hash, "candidate_hash")
        )
        if not isinstance(self.evaluator_family, WorkshopEvaluatorFamily):
            raise HarnessWorkshopModelError("evaluator_family is invalid")
        object.__setattr__(
            self,
            "evaluator_protocol",
            _token(self.evaluator_protocol, "evaluator_protocol"),
        )
        object.__setattr__(
            self,
            "evaluation_evidence",
            _evidence_tuple(
                self.evaluation_evidence,
                label="evaluation_evidence",
                maximum=_MAX_PLAN_EVIDENCE,
                allow_empty=False,
                forbidden_ref_id=self.candidate_id,
            ),
        )
        criteria = tuple(self.criteria)
        if not criteria or len(criteria) > _MAX_METRICS or not all(
            isinstance(value, WorkshopMetricCriterion) for value in criteria
        ):
            raise HarnessWorkshopModelError("criteria must contain bounded metric criteria")
        if len({value.metric_id for value in criteria}) != len(criteria):
            raise HarnessWorkshopModelError("criteria contain duplicate metric IDs")
        object.__setattr__(
            self, "criteria", tuple(sorted(criteria, key=lambda value: value.metric_id))
        )
        if not isinstance(self.cost_ceilings, WorkshopCostCeilings):
            raise HarnessWorkshopModelError("cost_ceilings must be WorkshopCostCeilings")
        if self.regression_policy is not RegressionPolicy.REGRESSION_DOMINANT:
            raise HarnessWorkshopModelError("v1 supports regression-dominant policy only")

    @classmethod
    def create(
        cls,
        *,
        candidate: HarnessImprovementCandidate,
        evaluator_protocol: str,
        evaluation_evidence: Iterable[EvidenceRef],
        criteria: Iterable[WorkshopMetricCriterion],
        cost_ceilings: WorkshopCostCeilings,
    ) -> "WorkshopEvaluationPlan":
        if not isinstance(candidate, HarnessImprovementCandidate):
            raise TypeError("candidate must be a HarnessImprovementCandidate")
        return cls(
            plan_id=new_id(IdKind.WORKSHOP_EVALUATION_PLAN),
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.content_hash,
            evaluator_family=candidate.evaluator_family,
            evaluator_protocol=evaluator_protocol,
            evaluation_evidence=tuple(evaluation_evidence),
            criteria=tuple(criteria),
            cost_ceilings=cost_ceilings,
        )

    def bind_candidate(self, candidate: HarnessImprovementCandidate) -> None:
        if not isinstance(candidate, HarnessImprovementCandidate):
            raise TypeError("candidate must be a HarnessImprovementCandidate")
        if (
            self.candidate_id != candidate.candidate_id
            or self.candidate_hash != candidate.content_hash
            or self.evaluator_family is not candidate.evaluator_family
        ):
            raise HarnessWorkshopModelError(
                "evaluation plan does not bind exact improvement candidate"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "evaluator_family": self.evaluator_family.value,
            "evaluator_protocol": self.evaluator_protocol,
            "evaluation_evidence": [value.to_dict() for value in self.evaluation_evidence],
            "criteria": [value.to_dict() for value in self.criteria],
            "cost_ceilings": self.cost_ceilings.to_dict(),
            "regression_policy": self.regression_policy.value,
            "candidate_controls_acceptance_gate": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
