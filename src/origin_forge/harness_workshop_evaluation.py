from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping

from .dream_models import EvidenceRef
from .harness_workshop_models import (
    HarnessImprovementCandidate,
    HarnessWorkshopModelError,
    MetricDirection,
    WorkshopEvaluationPlan,
    WorkshopMetricCriterion,
    _evidence_tuple,
    _exact_int,
    _sha256,
)
from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import content_hash


_MAX_METRIC_VALUE = 9_223_372_036_854_775_807
_MAX_REPORT_EVIDENCE = 128


class WorkshopVerdict(StrEnum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    EQUIVALENT = "EQUIVALENT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class WorkshopMetricObservation:
    metric_id: str
    baseline_value: int
    candidate_value: int
    verdict: WorkshopVerdict
    signed_improvement: int

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "baseline_value": self.baseline_value,
            "candidate_value": self.candidate_value,
            "signed_improvement": self.signed_improvement,
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True)
class WorkshopCostTotals:
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

    def delta_from(self, baseline: "WorkshopCostTotals") -> dict[str, int]:
        if not isinstance(baseline, WorkshopCostTotals):
            raise TypeError("baseline must be WorkshopCostTotals")
        return {
            name: getattr(self, name) - getattr(baseline, name)
            for name in (
                "model_calls",
                "input_tokens",
                "output_tokens",
                "wall_time_ms",
                "resource_units",
            )
        }


def _classify_metric(
    criterion: WorkshopMetricCriterion,
    baseline: int,
    candidate: int,
) -> WorkshopMetricObservation:
    _exact_int(baseline, f"{criterion.metric_id} baseline", 0, _MAX_METRIC_VALUE)
    _exact_int(candidate, f"{criterion.metric_id} candidate", 0, _MAX_METRIC_VALUE)

    if criterion.direction is MetricDirection.HIGHER_IS_BETTER:
        improvement = candidate - baseline
    elif criterion.direction is MetricDirection.LOWER_IS_BETTER:
        improvement = baseline - candidate
    else:
        # MUST_NOT_REGRESS is the v1 exact-preservation/lower-harm sentinel.
        # A lower value is accepted as an improvement; any increase regresses.
        improvement = baseline - candidate

    if improvement < -criterion.maximum_regression:
        verdict = WorkshopVerdict.REGRESSED
    elif improvement >= criterion.minimum_improvement and (
        criterion.minimum_improvement > 0 or improvement > 0
    ):
        verdict = WorkshopVerdict.IMPROVED
    else:
        verdict = WorkshopVerdict.EQUIVALENT

    return WorkshopMetricObservation(
        metric_id=criterion.metric_id,
        baseline_value=baseline,
        candidate_value=candidate,
        verdict=verdict,
        signed_improvement=improvement,
    )


def _cost_excesses(
    candidate: WorkshopCostTotals,
    plan: WorkshopEvaluationPlan,
) -> tuple[str, ...]:
    ceilings = plan.cost_ceilings
    exceeded = [
        name
        for name in (
            "model_calls",
            "input_tokens",
            "output_tokens",
            "wall_time_ms",
            "resource_units",
        )
        if getattr(candidate, name) > getattr(ceilings, name)
    ]
    return tuple(exceeded)


@dataclass(frozen=True)
class WorkshopEvaluationReport:
    report_id: str
    candidate_id: str
    candidate_hash: str
    plan_id: str
    plan_hash: str
    baseline_target_hash: str
    candidate_payload_hash: str
    evaluator_family: str
    evaluator_protocol: str
    evaluator_evidence: tuple[EvidenceRef, ...]
    metrics: tuple[WorkshopMetricObservation, ...]
    baseline_cost: WorkshopCostTotals
    candidate_cost: WorkshopCostTotals
    cost_ceiling_exceeded: tuple[str, ...]
    verdict: WorkshopVerdict

    def __post_init__(self) -> None:
        if not validate_id(self.report_id, IdKind.WORKSHOP_EVALUATION_REPORT):
            raise HarnessWorkshopModelError("report_id must be a HREP ID")
        if not validate_id(self.candidate_id, IdKind.IMPROVEMENT_CANDIDATE):
            raise HarnessWorkshopModelError("candidate_id must be a HIC ID")
        if not validate_id(self.plan_id, IdKind.WORKSHOP_EVALUATION_PLAN):
            raise HarnessWorkshopModelError("plan_id must be a HPLAN ID")
        for field_name in (
            "candidate_hash",
            "plan_hash",
            "baseline_target_hash",
            "candidate_payload_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field_name),
            )
        if not isinstance(self.evaluator_family, str) or not self.evaluator_family:
            raise HarnessWorkshopModelError("evaluator_family must be text")
        if not isinstance(self.evaluator_protocol, str) or not self.evaluator_protocol:
            raise HarnessWorkshopModelError("evaluator_protocol must be text")
        object.__setattr__(
            self,
            "evaluator_evidence",
            _evidence_tuple(
                self.evaluator_evidence,
                label="evaluator_evidence",
                maximum=_MAX_REPORT_EVIDENCE,
                allow_empty=False,
                forbidden_ref_id=self.candidate_id,
            ),
        )
        metrics = tuple(self.metrics)
        if not metrics or not all(
            isinstance(value, WorkshopMetricObservation) for value in metrics
        ):
            raise HarnessWorkshopModelError("report metrics are invalid")
        if len({value.metric_id for value in metrics}) != len(metrics):
            raise HarnessWorkshopModelError("report metrics contain duplicate metric IDs")
        object.__setattr__(
            self, "metrics", tuple(sorted(metrics, key=lambda value: value.metric_id))
        )
        if not isinstance(self.baseline_cost, WorkshopCostTotals) or not isinstance(
            self.candidate_cost, WorkshopCostTotals
        ):
            raise HarnessWorkshopModelError("report costs are invalid")
        allowed_cost_names = {
            "model_calls",
            "input_tokens",
            "output_tokens",
            "wall_time_ms",
            "resource_units",
        }
        if set(self.cost_ceiling_exceeded) - allowed_cost_names:
            raise HarnessWorkshopModelError("report contains unknown cost ceiling names")
        object.__setattr__(
            self, "cost_ceiling_exceeded", tuple(sorted(set(self.cost_ceiling_exceeded)))
        )
        if not isinstance(self.verdict, WorkshopVerdict):
            raise HarnessWorkshopModelError("report verdict is invalid")

    @classmethod
    def evaluate(
        cls,
        *,
        candidate: HarnessImprovementCandidate,
        plan: WorkshopEvaluationPlan,
        baseline_metrics: Mapping[str, int],
        candidate_metrics: Mapping[str, int],
        baseline_cost: WorkshopCostTotals,
        candidate_cost: WorkshopCostTotals,
        evaluator_evidence: Iterable[EvidenceRef],
    ) -> "WorkshopEvaluationReport":
        if not isinstance(candidate, HarnessImprovementCandidate):
            raise TypeError("candidate must be a HarnessImprovementCandidate")
        if not isinstance(plan, WorkshopEvaluationPlan):
            raise TypeError("plan must be a WorkshopEvaluationPlan")
        plan.bind_candidate(candidate)
        if not isinstance(baseline_cost, WorkshopCostTotals) or not isinstance(
            candidate_cost, WorkshopCostTotals
        ):
            raise TypeError("cost inputs must be WorkshopCostTotals")

        expected = {criterion.metric_id for criterion in plan.criteria}
        if set(baseline_metrics) != expected or set(candidate_metrics) != expected:
            raise HarnessWorkshopModelError(
                "evaluation metric keys must exactly match the frozen plan"
            )
        observations = tuple(
            _classify_metric(
                criterion,
                baseline_metrics[criterion.metric_id],
                candidate_metrics[criterion.metric_id],
            )
            for criterion in plan.criteria
        )
        cost_excesses = _cost_excesses(candidate_cost, plan)
        metric_verdicts = {value.verdict for value in observations}
        if WorkshopVerdict.REGRESSED in metric_verdicts or cost_excesses:
            verdict = WorkshopVerdict.REGRESSED
        elif WorkshopVerdict.INCONCLUSIVE in metric_verdicts:
            verdict = WorkshopVerdict.INCONCLUSIVE
        elif WorkshopVerdict.IMPROVED in metric_verdicts:
            verdict = WorkshopVerdict.IMPROVED
        else:
            verdict = WorkshopVerdict.EQUIVALENT

        evidence = _evidence_tuple(
            evaluator_evidence,
            label="evaluator_evidence",
            maximum=_MAX_REPORT_EVIDENCE,
            allow_empty=False,
            forbidden_ref_id=candidate.candidate_id,
        )
        return cls(
            report_id=new_id(IdKind.WORKSHOP_EVALUATION_REPORT),
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.content_hash,
            plan_id=plan.plan_id,
            plan_hash=plan.content_hash,
            baseline_target_hash=candidate.target_hash,
            candidate_payload_hash=candidate.candidate_payload_hash,
            evaluator_family=plan.evaluator_family.value,
            evaluator_protocol=plan.evaluator_protocol,
            evaluator_evidence=evidence,
            metrics=observations,
            baseline_cost=baseline_cost,
            candidate_cost=candidate_cost,
            cost_ceiling_exceeded=cost_excesses,
            verdict=verdict,
        )

    def bind(
        self,
        candidate: HarnessImprovementCandidate,
        plan: WorkshopEvaluationPlan,
    ) -> None:
        plan.bind_candidate(candidate)
        if (
            self.candidate_id != candidate.candidate_id
            or self.candidate_hash != candidate.content_hash
            or self.plan_id != plan.plan_id
            or self.plan_hash != plan.content_hash
            or self.baseline_target_hash != candidate.target_hash
            or self.candidate_payload_hash != candidate.candidate_payload_hash
            or self.evaluator_family != plan.evaluator_family.value
            or self.evaluator_protocol != plan.evaluator_protocol
        ):
            raise HarnessWorkshopModelError(
                "evaluation report does not bind exact candidate and plan"
            )
        expected_metric_ids = tuple(value.metric_id for value in plan.criteria)
        if tuple(value.metric_id for value in self.metrics) != expected_metric_ids:
            raise HarnessWorkshopModelError(
                "evaluation report metrics differ from frozen plan"
            )
        expected_excesses = _cost_excesses(self.candidate_cost, plan)
        if self.cost_ceiling_exceeded != expected_excesses:
            raise HarnessWorkshopModelError(
                "evaluation report cost ceiling state is inconsistent"
            )
        recomputed = tuple(
            _classify_metric(
                criterion,
                next(
                    value.baseline_value
                    for value in self.metrics
                    if value.metric_id == criterion.metric_id
                ),
                next(
                    value.candidate_value
                    for value in self.metrics
                    if value.metric_id == criterion.metric_id
                ),
            )
            for criterion in plan.criteria
        )
        if recomputed != self.metrics:
            raise HarnessWorkshopModelError(
                "evaluation report metric verdicts are inconsistent"
            )
        verdicts = {value.verdict for value in self.metrics}
        if WorkshopVerdict.REGRESSED in verdicts or expected_excesses:
            expected_verdict = WorkshopVerdict.REGRESSED
        elif WorkshopVerdict.INCONCLUSIVE in verdicts:
            expected_verdict = WorkshopVerdict.INCONCLUSIVE
        elif WorkshopVerdict.IMPROVED in verdicts:
            expected_verdict = WorkshopVerdict.IMPROVED
        else:
            expected_verdict = WorkshopVerdict.EQUIVALENT
        if self.verdict is not expected_verdict:
            raise HarnessWorkshopModelError("evaluation report verdict is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "baseline_target_hash": self.baseline_target_hash,
            "candidate_payload_hash": self.candidate_payload_hash,
            "evaluator_family": self.evaluator_family,
            "evaluator_protocol": self.evaluator_protocol,
            "evaluator_evidence": [value.to_dict() for value in self.evaluator_evidence],
            "metrics": [value.to_dict() for value in self.metrics],
            "baseline_cost": self.baseline_cost.to_dict(),
            "candidate_cost": self.candidate_cost.to_dict(),
            "cost_delta": self.candidate_cost.delta_from(self.baseline_cost),
            "cost_ceiling_exceeded": list(self.cost_ceiling_exceeded),
            "verdict": self.verdict.value,
            "production_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
