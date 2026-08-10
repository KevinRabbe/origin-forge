from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .harness_workshop_evaluation import WorkshopEvaluationReport, WorkshopVerdict
from .harness_workshop_evaluators import require_trusted_workshop_evaluator
from .harness_workshop_models import (
    HarnessComponentKind,
    HarnessImprovementCandidate,
    HarnessWorkshopModelError,
    WorkshopEvaluationPlan,
    _text,
)
from .harness_workshop_skill_adapter import SkillWorkshopEvaluation
from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import content_hash

if TYPE_CHECKING:
    from .skill_evaluation import SkillBenchmarkReport


class WorkshopAuditStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class WorkshopDecisionOutcome(StrEnum):
    APPROVE_FOR_PROMOTION = "APPROVE_FOR_PROMOTION"
    REJECT = "REJECT"
    DEFER = "DEFER"


@dataclass(frozen=True)
class WorkshopEvaluationAudit:
    audit_id: str
    candidate_id: str
    candidate_hash: str
    plan_id: str
    plan_hash: str
    report_id: str
    evaluation_hash: str
    effective_verdict: WorkshopVerdict
    status: WorkshopAuditStatus
    findings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.audit_id, IdKind.WORKSHOP_EVALUATION_AUDIT):
            raise HarnessWorkshopModelError("audit_id must be a HAUD ID")
        if not validate_id(self.candidate_id, IdKind.IMPROVEMENT_CANDIDATE):
            raise HarnessWorkshopModelError("audit candidate_id must be a HIC ID")
        if not validate_id(self.plan_id, IdKind.WORKSHOP_EVALUATION_PLAN):
            raise HarnessWorkshopModelError("audit plan_id must be a HPLAN ID")
        if not validate_id(self.report_id, IdKind.WORKSHOP_EVALUATION_REPORT):
            raise HarnessWorkshopModelError("audit report_id must be a HREP ID")
        if not isinstance(self.effective_verdict, WorkshopVerdict):
            raise HarnessWorkshopModelError("audit effective_verdict is invalid")
        if not isinstance(self.status, WorkshopAuditStatus):
            raise HarnessWorkshopModelError("audit status is invalid")
        findings = tuple(_text(value, "audit finding", maximum=2000) for value in self.findings)
        if len(findings) > 32:
            raise HarnessWorkshopModelError("audit findings exceed limit")
        if self.status is WorkshopAuditStatus.PASS and findings:
            raise HarnessWorkshopModelError("passing audit may not contain findings")
        if self.status is WorkshopAuditStatus.FAIL and not findings:
            raise HarnessWorkshopModelError("failing audit requires at least one finding")
        object.__setattr__(self, "findings", findings)

    def bind(
        self,
        candidate: HarnessImprovementCandidate,
        plan: WorkshopEvaluationPlan,
        evaluation: WorkshopEvaluationReport | SkillWorkshopEvaluation,
    ) -> None:
        base_report = (
            evaluation.report if isinstance(evaluation, SkillWorkshopEvaluation) else evaluation
        )
        evaluation_hash = evaluation.content_hash
        verdict = evaluation.verdict
        if (
            self.candidate_id != candidate.candidate_id
            or self.candidate_hash != candidate.content_hash
            or self.plan_id != plan.plan_id
            or self.plan_hash != plan.content_hash
            or self.report_id != base_report.report_id
            or self.evaluation_hash != evaluation_hash
            or self.effective_verdict is not verdict
        ):
            raise HarnessWorkshopModelError(
                "workshop audit does not bind exact candidate/plan/evaluation"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_id": self.audit_id,
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "report_id": self.report_id,
            "evaluation_hash": self.evaluation_hash,
            "effective_verdict": self.effective_verdict.value,
            "status": self.status.value,
            "findings": list(self.findings),
            "semantic_correctness_verified": False,
            "production_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


def audit_workshop_evaluation(
    *,
    candidate: HarnessImprovementCandidate,
    plan: WorkshopEvaluationPlan,
    evaluation: WorkshopEvaluationReport | SkillWorkshopEvaluation,
    phase12_report: "SkillBenchmarkReport | None" = None,
) -> WorkshopEvaluationAudit:
    if not isinstance(candidate, HarnessImprovementCandidate):
        raise TypeError("candidate must be a HarnessImprovementCandidate")
    if not isinstance(plan, WorkshopEvaluationPlan):
        raise TypeError("plan must be a WorkshopEvaluationPlan")
    if not isinstance(evaluation, (WorkshopEvaluationReport, SkillWorkshopEvaluation)):
        raise TypeError("evaluation has unsupported type")

    findings: list[str] = []
    base_report = (
        evaluation.report if isinstance(evaluation, SkillWorkshopEvaluation) else evaluation
    )
    try:
        plan.bind_candidate(candidate)
        require_trusted_workshop_evaluator(plan)
        if candidate.component_kind is HarnessComponentKind.SKILL:
            if not isinstance(evaluation, SkillWorkshopEvaluation):
                raise HarnessWorkshopModelError(
                    "SKILL candidate requires the Phase-12 Skill workshop adapter"
                )
            if phase12_report is None:
                raise HarnessWorkshopModelError(
                    "SKILL audit requires the exact Phase-12 benchmark report"
                )
            evaluation.bind(candidate, plan, phase12_report)
        else:
            if isinstance(evaluation, SkillWorkshopEvaluation):
                raise HarnessWorkshopModelError(
                    "non-SKILL candidate may not use Skill workshop evidence"
                )
            evaluation.bind(candidate, plan)
    except (HarnessWorkshopModelError, TypeError, ValueError) as exc:
        findings.append(f"{type(exc).__name__}: {str(exc)[:1800]}")

    status = WorkshopAuditStatus.FAIL if findings else WorkshopAuditStatus.PASS
    evaluation_hash = evaluation.content_hash
    verdict = evaluation.verdict
    audit = WorkshopEvaluationAudit(
        audit_id=new_id(IdKind.WORKSHOP_EVALUATION_AUDIT),
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate.content_hash,
        plan_id=plan.plan_id,
        plan_hash=plan.content_hash,
        report_id=base_report.report_id,
        evaluation_hash=evaluation_hash,
        effective_verdict=verdict,
        status=status,
        findings=tuple(findings),
    )
    audit.bind(candidate, plan, evaluation)
    return audit


@dataclass(frozen=True)
class WorkshopDecision:
    decision_id: str
    audit_id: str
    audit_hash: str
    report_id: str
    evaluation_hash: str
    effective_verdict: WorkshopVerdict
    outcome: WorkshopDecisionOutcome
    rationale: str

    def __post_init__(self) -> None:
        if not validate_id(self.decision_id, IdKind.WORKSHOP_DECISION):
            raise HarnessWorkshopModelError("decision_id must be a HDEC ID")
        if not validate_id(self.audit_id, IdKind.WORKSHOP_EVALUATION_AUDIT):
            raise HarnessWorkshopModelError("decision audit_id must be a HAUD ID")
        if not validate_id(self.report_id, IdKind.WORKSHOP_EVALUATION_REPORT):
            raise HarnessWorkshopModelError("decision report_id must be a HREP ID")
        if not isinstance(self.effective_verdict, WorkshopVerdict):
            raise HarnessWorkshopModelError("decision effective_verdict is invalid")
        if not isinstance(self.outcome, WorkshopDecisionOutcome):
            raise HarnessWorkshopModelError("decision outcome is invalid")
        object.__setattr__(
            self, "rationale", _text(self.rationale, "decision rationale", maximum=2000)
        )

    @classmethod
    def create(
        cls,
        *,
        audit: WorkshopEvaluationAudit,
        evaluation: WorkshopEvaluationReport | SkillWorkshopEvaluation,
        outcome: WorkshopDecisionOutcome,
        rationale: str,
    ) -> "WorkshopDecision":
        if not isinstance(audit, WorkshopEvaluationAudit):
            raise TypeError("audit must be a WorkshopEvaluationAudit")
        if not isinstance(evaluation, (WorkshopEvaluationReport, SkillWorkshopEvaluation)):
            raise TypeError("evaluation has unsupported type")
        base_report = (
            evaluation.report if isinstance(evaluation, SkillWorkshopEvaluation) else evaluation
        )
        if (
            audit.report_id != base_report.report_id
            or audit.evaluation_hash != evaluation.content_hash
            or audit.effective_verdict is not evaluation.verdict
        ):
            raise HarnessWorkshopModelError(
                "decision inputs do not bind the exact audited evaluation"
            )
        if outcome is WorkshopDecisionOutcome.APPROVE_FOR_PROMOTION:
            if audit.status is not WorkshopAuditStatus.PASS:
                raise HarnessWorkshopModelError(
                    "promotion eligibility requires a passing workshop audit"
                )
            if evaluation.verdict is not WorkshopVerdict.IMPROVED:
                raise HarnessWorkshopModelError(
                    "promotion eligibility requires an IMPROVED effective verdict"
                )
        return cls(
            decision_id=new_id(IdKind.WORKSHOP_DECISION),
            audit_id=audit.audit_id,
            audit_hash=audit.content_hash,
            report_id=base_report.report_id,
            evaluation_hash=evaluation.content_hash,
            effective_verdict=evaluation.verdict,
            outcome=outcome,
            rationale=rationale,
        )

    def bind(
        self,
        audit: WorkshopEvaluationAudit,
        evaluation: WorkshopEvaluationReport | SkillWorkshopEvaluation,
    ) -> None:
        base_report = (
            evaluation.report if isinstance(evaluation, SkillWorkshopEvaluation) else evaluation
        )
        if (
            self.audit_id != audit.audit_id
            or self.audit_hash != audit.content_hash
            or self.report_id != base_report.report_id
            or self.evaluation_hash != evaluation.content_hash
            or self.effective_verdict is not evaluation.verdict
        ):
            raise HarnessWorkshopModelError(
                "workshop decision does not bind exact audit/evaluation"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "audit_id": self.audit_id,
            "audit_hash": self.audit_hash,
            "report_id": self.report_id,
            "evaluation_hash": self.evaluation_hash,
            "effective_verdict": self.effective_verdict.value,
            "outcome": self.outcome.value,
            "rationale": self.rationale,
            "promotion_eligible": self.outcome is WorkshopDecisionOutcome.APPROVE_FOR_PROMOTION,
            "production_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
