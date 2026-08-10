from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .dream_models import EvidenceClass, EvidenceRef
from .harness_workshop_evaluation import (
    WorkshopCostTotals,
    WorkshopEvaluationReport,
    WorkshopVerdict,
)
from .harness_workshop_models import (
    HarnessComponentKind,
    HarnessImprovementCandidate,
    HarnessWorkshopModelError,
    WorkshopEvaluationPlan,
    WorkshopEvaluatorFamily,
)
from .runtime_observation_models import content_hash
from .skill_evaluation import SkillBenchmarkReport, SkillComparisonVerdict


PHASE12_SKILL_PROTOCOL = "paired-skill-ab-v1"


_VERDICT_ORDER = {
    WorkshopVerdict.IMPROVED: 0,
    WorkshopVerdict.EQUIVALENT: 1,
    WorkshopVerdict.INCONCLUSIVE: 2,
    WorkshopVerdict.REGRESSED: 3,
}


def _workshop_verdict(value: object) -> WorkshopVerdict:
    raw = value.value if isinstance(value, SkillComparisonVerdict) else value
    try:
        return WorkshopVerdict(str(raw))
    except ValueError as exc:
        raise HarnessWorkshopModelError(
            "Phase-12 Skill report contains an unknown overall verdict"
        ) from exc


def _phase12_overall_verdict(report: SkillBenchmarkReport) -> WorkshopVerdict:
    payload = report.to_dict()
    raw = payload.get("overall_verdict")
    if raw is None:
        raw = payload.get("verdict")
    if raw is None and hasattr(report, "overall_verdict"):
        raw = report.overall_verdict
    if raw is None and hasattr(report, "verdict"):
        raw = report.verdict
    if raw is None:
        raise HarnessWorkshopModelError(
            "Phase-12 Skill report does not expose its overall verdict"
        )
    return _workshop_verdict(raw)


def _more_conservative(
    first: WorkshopVerdict,
    second: WorkshopVerdict,
) -> WorkshopVerdict:
    return first if _VERDICT_ORDER[first] >= _VERDICT_ORDER[second] else second


@dataclass(frozen=True)
class SkillWorkshopEvaluation:
    report: WorkshopEvaluationReport
    phase12_report_hash: str
    phase12_verdict: WorkshopVerdict
    effective_verdict: WorkshopVerdict
    phase12_evidence: EvidenceRef

    @property
    def verdict(self) -> WorkshopVerdict:
        return self.effective_verdict

    def bind(
        self,
        candidate: HarnessImprovementCandidate,
        plan: WorkshopEvaluationPlan,
        phase12_report: SkillBenchmarkReport,
    ) -> None:
        self.report.bind(candidate, plan)
        if candidate.component_kind is not HarnessComponentKind.SKILL:
            raise HarnessWorkshopModelError(
                "Skill workshop evaluation requires a SKILL candidate"
            )
        if plan.evaluator_family is not WorkshopEvaluatorFamily.SKILL_BENCHMARK:
            raise HarnessWorkshopModelError(
                "Skill workshop evaluation requires the Skill evaluator family"
            )
        if plan.evaluator_protocol != PHASE12_SKILL_PROTOCOL:
            raise HarnessWorkshopModelError(
                "Skill workshop evaluation requires the Phase-12 paired protocol"
            )
        actual_hash = phase12_report.content_hash
        actual_verdict = _phase12_overall_verdict(phase12_report)
        if (
            self.phase12_report_hash != actual_hash
            or self.phase12_evidence.content_hash != actual_hash
            or self.phase12_evidence.evidence_class is not EvidenceClass.BENCHMARK
            or self.phase12_verdict is not actual_verdict
        ):
            raise HarnessWorkshopModelError(
                "Skill workshop evidence does not bind the exact Phase-12 report"
            )
        expected = _more_conservative(self.report.verdict, actual_verdict)
        if self.effective_verdict is not expected:
            raise HarnessWorkshopModelError(
                "Skill workshop verdict weakens Phase-12 benchmark evidence"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "workshop_report_id": self.report.report_id,
            "workshop_report_hash": self.report.content_hash,
            "phase12_report_hash": self.phase12_report_hash,
            "phase12_verdict": self.phase12_verdict.value,
            "effective_verdict": self.effective_verdict.value,
            "phase12_evidence": self.phase12_evidence.to_dict(),
            "production_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


def evaluate_skill_benchmark(
    *,
    candidate: HarnessImprovementCandidate,
    plan: WorkshopEvaluationPlan,
    phase12_report: SkillBenchmarkReport,
    phase12_evidence: EvidenceRef,
    baseline_metrics: Mapping[str, int],
    candidate_metrics: Mapping[str, int],
    baseline_cost: WorkshopCostTotals,
    candidate_cost: WorkshopCostTotals,
) -> SkillWorkshopEvaluation:
    if not isinstance(candidate, HarnessImprovementCandidate):
        raise TypeError("candidate must be a HarnessImprovementCandidate")
    if not isinstance(plan, WorkshopEvaluationPlan):
        raise TypeError("plan must be a WorkshopEvaluationPlan")
    if not isinstance(phase12_report, SkillBenchmarkReport):
        raise TypeError("phase12_report must be a SkillBenchmarkReport")
    if not isinstance(phase12_evidence, EvidenceRef):
        raise TypeError("phase12_evidence must be an EvidenceRef")
    if candidate.component_kind is not HarnessComponentKind.SKILL:
        raise HarnessWorkshopModelError("Phase-12 adapter accepts SKILL candidates only")
    if plan.evaluator_family is not WorkshopEvaluatorFamily.SKILL_BENCHMARK:
        raise HarnessWorkshopModelError(
            "Phase-12 adapter requires the Skill evaluator family"
        )
    if plan.evaluator_protocol != PHASE12_SKILL_PROTOCOL:
        raise HarnessWorkshopModelError(
            "Phase-12 adapter requires paired-skill-ab-v1"
        )
    plan.bind_candidate(candidate)

    phase12_hash = phase12_report.content_hash
    if (
        phase12_evidence.evidence_class is not EvidenceClass.BENCHMARK
        or phase12_evidence.content_hash != phase12_hash
    ):
        raise HarnessWorkshopModelError(
            "Phase-12 evidence ref does not bind exact Skill benchmark report"
        )
    phase12_verdict = _phase12_overall_verdict(phase12_report)
    report = WorkshopEvaluationReport.evaluate(
        candidate=candidate,
        plan=plan,
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        baseline_cost=baseline_cost,
        candidate_cost=candidate_cost,
        evaluator_evidence=(phase12_evidence,),
    )
    effective = _more_conservative(report.verdict, phase12_verdict)
    result = SkillWorkshopEvaluation(
        report=report,
        phase12_report_hash=phase12_hash,
        phase12_verdict=phase12_verdict,
        effective_verdict=effective,
        phase12_evidence=phase12_evidence,
    )
    result.bind(candidate, plan, phase12_report)
    return result
