from __future__ import annotations

import unittest
from unittest.mock import Mock

from origin_forge.dream_models import EvidenceClass, EvidenceRef
from origin_forge.harness_workshop_evaluation import WorkshopCostTotals, WorkshopVerdict
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


class HarnessWorkshopSkillAdapterTests(unittest.TestCase):
    def _candidate(self) -> HarnessImprovementCandidate:
        return HarnessImprovementCandidate.create(
            component_kind=HarnessComponentKind.SKILL,
            target_component_id="skill.review",
            target_version="1",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={"instructions": ["check exact evidence first"]},
            hypothesis="The candidate should improve measured Skill outcomes.",
            source_evidence=(
                EvidenceRef(
                    ref_id=new_id(IdKind.RUN),
                    content_hash=HASH_C,
                    evidence_class=EvidenceClass.TRAJECTORY,
                ),
            ),
        )

    def _plan(self, candidate: HarnessImprovementCandidate) -> WorkshopEvaluationPlan:
        return WorkshopEvaluationPlan.create(
            candidate=candidate,
            evaluator_protocol=PHASE12_SKILL_PROTOCOL,
            evaluation_evidence=(
                EvidenceRef(
                    ref_id=new_id(IdKind.ARTIFACT),
                    content_hash=HASH_C,
                    evidence_class=EvidenceClass.BENCHMARK,
                ),
            ),
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
    def _costs() -> WorkshopCostTotals:
        return WorkshopCostTotals(10, 1000, 200, 1000, 10)

    @staticmethod
    def _phase12_report(verdict: str) -> SkillBenchmarkReport:
        report = Mock(spec=SkillBenchmarkReport)
        report.content_hash = HASH_C
        report.to_dict.return_value = {"overall_verdict": verdict}
        return report

    @staticmethod
    def _phase12_ref(content_hash: str = HASH_C) -> EvidenceRef:
        return EvidenceRef(
            ref_id=new_id(IdKind.ARTIFACT),
            content_hash=content_hash,
            evidence_class=EvidenceClass.BENCHMARK,
        )

    def test_phase12_regression_cannot_be_reinterpreted_as_workshop_improvement(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        result = evaluate_skill_benchmark(
            candidate=candidate,
            plan=plan,
            phase12_report=self._phase12_report("REGRESSED"),
            phase12_evidence=self._phase12_ref(),
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 95},
            baseline_cost=self._costs(),
            candidate_cost=self._costs(),
        )
        self.assertIs(result.report.verdict, WorkshopVerdict.IMPROVED)
        self.assertIs(result.phase12_verdict, WorkshopVerdict.REGRESSED)
        self.assertIs(result.effective_verdict, WorkshopVerdict.REGRESSED)
        self.assertFalse(result.to_dict()["production_activation_authorized"])

    def test_phase12_equivalent_caps_workshop_improvement_at_equivalent(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        result = evaluate_skill_benchmark(
            candidate=candidate,
            plan=plan,
            phase12_report=self._phase12_report("EQUIVALENT"),
            phase12_evidence=self._phase12_ref(),
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 95},
            baseline_cost=self._costs(),
            candidate_cost=self._costs(),
        )
        self.assertIs(result.effective_verdict, WorkshopVerdict.EQUIVALENT)

    def test_workshop_regression_remains_regression_even_if_phase12_improved(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        result = evaluate_skill_benchmark(
            candidate=candidate,
            plan=plan,
            phase12_report=self._phase12_report("IMPROVED"),
            phase12_evidence=self._phase12_ref(),
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 79},
            baseline_cost=self._costs(),
            candidate_cost=self._costs(),
        )
        self.assertIs(result.report.verdict, WorkshopVerdict.REGRESSED)
        self.assertIs(result.effective_verdict, WorkshopVerdict.REGRESSED)

    def test_exact_phase12_report_hash_is_required(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        with self.assertRaisesRegex(HarnessWorkshopModelError, "exact Skill benchmark"):
            evaluate_skill_benchmark(
                candidate=candidate,
                plan=plan,
                phase12_report=self._phase12_report("IMPROVED"),
                phase12_evidence=self._phase12_ref(HASH_B),
                baseline_metrics={"success": 80},
                candidate_metrics={"success": 90},
                baseline_cost=self._costs(),
                candidate_cost=self._costs(),
            )

    def test_phase12_adapter_rejects_non_phase12_protocol(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        plan = type(plan)(
            plan_id=plan.plan_id,
            candidate_id=plan.candidate_id,
            candidate_hash=plan.candidate_hash,
            evaluator_family=plan.evaluator_family,
            evaluator_protocol="candidate-chosen-evaluator",
            evaluation_evidence=plan.evaluation_evidence,
            criteria=plan.criteria,
            cost_ceilings=plan.cost_ceilings,
            regression_policy=plan.regression_policy,
        )
        with self.assertRaisesRegex(HarnessWorkshopModelError, "paired-skill-ab-v1"):
            evaluate_skill_benchmark(
                candidate=candidate,
                plan=plan,
                phase12_report=self._phase12_report("IMPROVED"),
                phase12_evidence=self._phase12_ref(),
                baseline_metrics={"success": 80},
                candidate_metrics={"success": 90},
                baseline_cost=self._costs(),
                candidate_cost=self._costs(),
            )


if __name__ == "__main__":
    unittest.main()
