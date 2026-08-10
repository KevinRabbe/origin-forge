from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock

from origin_forge.dream_models import EvidenceClass, EvidenceRef
from origin_forge.harness_workshop_audit import (
    WorkshopAuditStatus,
    WorkshopDecision,
    WorkshopDecisionOutcome,
    audit_workshop_evaluation,
)
from origin_forge.harness_workshop_evaluation import (
    WorkshopCostTotals,
    WorkshopEvaluationReport,
    WorkshopVerdict,
)
from origin_forge.harness_workshop_models import (
    HarnessComponentKind,
    HarnessImprovementCandidate,
    HarnessWorkshopModelError,
    MetricDirection,
    WorkshopCostCeilings,
    WorkshopEvaluationPlan,
    WorkshopMetricCriterion,
)
from origin_forge.harness_workshop_skill_adapter import (
    PHASE12_SKILL_PROTOCOL,
    evaluate_skill_benchmark,
)
from origin_forge.ids import IdKind, new_id
from origin_forge.skill_evaluation import SkillBenchmarkReport


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _evidence(kind: EvidenceClass = EvidenceClass.BENCHMARK) -> EvidenceRef:
    return EvidenceRef(
        ref_id=new_id(IdKind.ARTIFACT),
        content_hash=HASH_C,
        evidence_class=kind,
    )


def _costs() -> WorkshopCostTotals:
    return WorkshopCostTotals(10, 1000, 200, 1000, 10)


class HarnessWorkshopAuditTests(unittest.TestCase):
    def _candidate(self, kind: HarnessComponentKind) -> HarnessImprovementCandidate:
        return HarnessImprovementCandidate.create(
            component_kind=kind,
            target_component_id=f"component.{kind.value.lower()}",
            target_version="1",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={"instructions": ["one bounded change"]},
            hypothesis="This single-target candidate should improve the frozen evaluation.",
            source_evidence=(_evidence(EvidenceClass.TRAJECTORY),),
        )

    def _plan(
        self,
        candidate: HarnessImprovementCandidate,
        protocol: str,
    ) -> WorkshopEvaluationPlan:
        return WorkshopEvaluationPlan.create(
            candidate=candidate,
            evaluator_protocol=protocol,
            evaluation_evidence=(_evidence(),),
            criteria=(
                WorkshopMetricCriterion(
                    "success",
                    MetricDirection.HIGHER_IS_BETTER,
                    minimum_improvement=1,
                    maximum_regression=0,
                ),
            ),
            cost_ceilings=WorkshopCostCeilings(100, 100000, 100000, 100000, 1000),
        )

    @staticmethod
    def _phase12(verdict: str) -> SkillBenchmarkReport:
        report = Mock(spec=SkillBenchmarkReport)
        report.content_hash = HASH_C
        report.to_dict.return_value = {"overall_verdict": verdict}
        return report

    def test_skill_audit_and_approval_require_exact_phase12_evidence(self) -> None:
        candidate = self._candidate(HarnessComponentKind.SKILL)
        plan = self._plan(candidate, PHASE12_SKILL_PROTOCOL)
        phase12 = self._phase12("IMPROVED")
        evaluation = evaluate_skill_benchmark(
            candidate=candidate,
            plan=plan,
            phase12_report=phase12,
            phase12_evidence=_evidence(),
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 90},
            baseline_cost=_costs(),
            candidate_cost=_costs(),
        )
        audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=evaluation,
            phase12_report=phase12,
        )
        self.assertIs(audit.status, WorkshopAuditStatus.PASS)
        self.assertEqual(audit.findings, ())
        self.assertFalse(audit.to_dict()["semantic_correctness_verified"])
        decision = WorkshopDecision.create(
            candidate=candidate,
            plan=plan,
            audit=audit,
            evaluation=evaluation,
            outcome=WorkshopDecisionOutcome.APPROVE_FOR_PROMOTION,
            rationale="The frozen evaluation and structural audit passed.",
            phase12_report=phase12,
        )
        self.assertTrue(decision.to_dict()["promotion_eligible"])
        self.assertFalse(decision.to_dict()["production_activation_authorized"])
        decision.bind(audit, evaluation)

    def test_skill_candidate_cannot_bypass_phase12_adapter_with_generic_report(self) -> None:
        candidate = self._candidate(HarnessComponentKind.SKILL)
        plan = self._plan(candidate, PHASE12_SKILL_PROTOCOL)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 90},
            baseline_cost=_costs(),
            candidate_cost=_costs(),
            evaluator_evidence=(_evidence(),),
        )
        audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=report,
        )
        self.assertIs(audit.status, WorkshopAuditStatus.FAIL)
        self.assertIn("Phase-12 Skill workshop adapter", audit.findings[0])
        with self.assertRaisesRegex(HarnessWorkshopModelError, "passing workshop audit"):
            WorkshopDecision.create(
                candidate=candidate,
                plan=plan,
                audit=audit,
                evaluation=report,
                outcome=WorkshopDecisionOutcome.APPROVE_FOR_PROMOTION,
                rationale="This must not be accepted.",
            )

    def test_phase12_regression_can_pass_structural_audit_but_not_gain_promotion_eligibility(self) -> None:
        candidate = self._candidate(HarnessComponentKind.SKILL)
        plan = self._plan(candidate, PHASE12_SKILL_PROTOCOL)
        phase12 = self._phase12("REGRESSED")
        evaluation = evaluate_skill_benchmark(
            candidate=candidate,
            plan=plan,
            phase12_report=phase12,
            phase12_evidence=_evidence(),
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 95},
            baseline_cost=_costs(),
            candidate_cost=_costs(),
        )
        audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=evaluation,
            phase12_report=phase12,
        )
        self.assertIs(audit.status, WorkshopAuditStatus.PASS)
        self.assertIs(audit.effective_verdict, WorkshopVerdict.REGRESSED)
        with self.assertRaisesRegex(HarnessWorkshopModelError, "IMPROVED"):
            WorkshopDecision.create(
                candidate=candidate,
                plan=plan,
                audit=audit,
                evaluation=evaluation,
                outcome=WorkshopDecisionOutcome.APPROVE_FOR_PROMOTION,
                rationale="A regression may not be promoted.",
                phase12_report=phase12,
            )
        rejected = WorkshopDecision.create(
            candidate=candidate,
            plan=plan,
            audit=audit,
            evaluation=evaluation,
            outcome=WorkshopDecisionOutcome.REJECT,
            rationale="Phase-12 regression remains authoritative evidence.",
            phase12_report=phase12,
        )
        self.assertFalse(rejected.to_dict()["promotion_eligible"])

    def test_non_skill_candidate_fails_closed_without_trusted_evaluator_adapter(self) -> None:
        candidate = self._candidate(HarnessComponentKind.PROMPT)
        plan = self._plan(candidate, "prompt-benchmark-v1")
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 90},
            baseline_cost=_costs(),
            candidate_cost=_costs(),
            evaluator_evidence=(_evidence(),),
        )
        audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=report,
        )
        self.assertIs(audit.status, WorkshopAuditStatus.FAIL)
        self.assertIn("no promotion-capable trusted evaluator", audit.findings[0])
        deferred = WorkshopDecision.create(
            candidate=candidate,
            plan=plan,
            audit=audit,
            evaluation=report,
            outcome=WorkshopDecisionOutcome.DEFER,
            rationale="No governed evaluator adapter exists for this target kind yet.",
        )
        self.assertFalse(deferred.to_dict()["promotion_eligible"])
        with self.assertRaisesRegex(HarnessWorkshopModelError, "passing workshop audit"):
            WorkshopDecision.create(
                candidate=candidate,
                plan=plan,
                audit=audit,
                evaluation=report,
                outcome=WorkshopDecisionOutcome.APPROVE_FOR_PROMOTION,
                rationale="An untrusted evaluator may not create promotion eligibility.",
            )

    def test_forged_passing_audit_cannot_bypass_decision_time_trust_check(self) -> None:
        candidate = self._candidate(HarnessComponentKind.PROMPT)
        plan = self._plan(candidate, "prompt-benchmark-v1")
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 90},
            baseline_cost=_costs(),
            candidate_cost=_costs(),
            evaluator_evidence=(_evidence(),),
        )
        failed_audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=report,
        )
        forged = replace(failed_audit, status=WorkshopAuditStatus.PASS, findings=())
        with self.assertRaisesRegex(HarnessWorkshopModelError, "no promotion-capable trusted evaluator"):
            WorkshopDecision.create(
                candidate=candidate,
                plan=plan,
                audit=forged,
                evaluation=report,
                outcome=WorkshopDecisionOutcome.APPROVE_FOR_PROMOTION,
                rationale="A forged PASS audit must not amplify authority.",
            )

    def test_arbitrary_skill_evaluator_protocol_fails_structural_audit(self) -> None:
        candidate = self._candidate(HarnessComponentKind.SKILL)
        plan = self._plan(candidate, "candidate-selected-scorer")
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 99},
            baseline_cost=_costs(),
            candidate_cost=_costs(),
            evaluator_evidence=(_evidence(),),
        )
        audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=report,
        )
        self.assertIs(audit.status, WorkshopAuditStatus.FAIL)
        self.assertIn("no promotion-capable trusted evaluator", audit.findings[0])

    def test_forged_skill_effective_verdict_fails_audit(self) -> None:
        candidate = self._candidate(HarnessComponentKind.SKILL)
        plan = self._plan(candidate, PHASE12_SKILL_PROTOCOL)
        phase12 = self._phase12("REGRESSED")
        evaluation = evaluate_skill_benchmark(
            candidate=candidate,
            plan=plan,
            phase12_report=phase12,
            phase12_evidence=_evidence(),
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 95},
            baseline_cost=_costs(),
            candidate_cost=_costs(),
        )
        forged = replace(evaluation, effective_verdict=WorkshopVerdict.IMPROVED)
        audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=forged,
            phase12_report=phase12,
        )
        self.assertIs(audit.status, WorkshopAuditStatus.FAIL)
        self.assertIn("weakens Phase-12", audit.findings[0])


if __name__ == "__main__":
    unittest.main()
