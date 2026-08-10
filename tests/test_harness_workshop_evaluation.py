from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.dream_models import EvidenceClass, EvidenceRef
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
from origin_forge.ids import IdKind, new_id


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _evidence(evidence_class: EvidenceClass = EvidenceClass.BENCHMARK) -> EvidenceRef:
    return EvidenceRef(
        ref_id=new_id(IdKind.ARTIFACT),
        content_hash=HASH_C,
        evidence_class=evidence_class,
    )


class HarnessWorkshopEvaluationTests(unittest.TestCase):
    def _candidate(self) -> HarnessImprovementCandidate:
        return HarnessImprovementCandidate.create(
            component_kind=HarnessComponentKind.SKILL,
            target_component_id="skill.repair",
            target_version="1",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={"instructions": ["inspect failure", "make bounded repair"]},
            hypothesis="The candidate should improve success without increasing critical misses.",
            source_evidence=(_evidence(EvidenceClass.TRAJECTORY),),
        )

    def _plan(self, candidate: HarnessImprovementCandidate) -> WorkshopEvaluationPlan:
        return WorkshopEvaluationPlan.create(
            candidate=candidate,
            evaluator_protocol="paired-skill-ab-v1",
            evaluation_evidence=(_evidence(),),
            criteria=(
                WorkshopMetricCriterion(
                    "success",
                    MetricDirection.HIGHER_IS_BETTER,
                    minimum_improvement=5,
                    maximum_regression=0,
                ),
                WorkshopMetricCriterion(
                    "critical-misses",
                    MetricDirection.MUST_NOT_REGRESS,
                    minimum_improvement=0,
                    maximum_regression=0,
                ),
            ),
            cost_ceilings=WorkshopCostCeilings(
                model_calls=100,
                input_tokens=1_000_000,
                output_tokens=500_000,
                wall_time_ms=1_000_000,
                resource_units=10_000,
            ),
        )

    @staticmethod
    def _baseline_cost() -> WorkshopCostTotals:
        return WorkshopCostTotals(10, 1000, 200, 1000, 10)

    @staticmethod
    def _candidate_cost() -> WorkshopCostTotals:
        return WorkshopCostTotals(12, 1100, 250, 1100, 12)

    def test_required_improvement_with_no_regression_is_improved(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80, "critical-misses": 0},
            candidate_metrics={"success": 86, "critical-misses": 0},
            baseline_cost=self._baseline_cost(),
            candidate_cost=self._candidate_cost(),
            evaluator_evidence=(_evidence(),),
        )
        self.assertIs(report.verdict, WorkshopVerdict.IMPROVED)
        report.bind(candidate, plan)
        self.assertFalse(report.to_dict()["production_activation_authorized"])
        self.assertEqual(report.to_dict()["cost_delta"]["model_calls"], 2)

    def test_any_required_metric_regression_dominates_other_improvement(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80, "critical-misses": 0},
            candidate_metrics={"success": 95, "critical-misses": 1},
            baseline_cost=self._baseline_cost(),
            candidate_cost=self._candidate_cost(),
            evaluator_evidence=(_evidence(),),
        )
        self.assertIs(report.verdict, WorkshopVerdict.REGRESSED)
        by_metric = {value.metric_id: value for value in report.metrics}
        self.assertIs(by_metric["success"].verdict, WorkshopVerdict.IMPROVED)
        self.assertIs(
            by_metric["critical-misses"].verdict, WorkshopVerdict.REGRESSED
        )

    def test_cost_ceiling_regression_dominates_metric_gain(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80, "critical-misses": 0},
            candidate_metrics={"success": 90, "critical-misses": 0},
            baseline_cost=self._baseline_cost(),
            candidate_cost=WorkshopCostTotals(101, 1100, 250, 1100, 12),
            evaluator_evidence=(_evidence(),),
        )
        self.assertIs(report.verdict, WorkshopVerdict.REGRESSED)
        self.assertEqual(report.cost_ceiling_exceeded, ("model_calls",))

    def test_below_required_gain_without_regression_is_equivalent(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80, "critical-misses": 0},
            candidate_metrics={"success": 83, "critical-misses": 0},
            baseline_cost=self._baseline_cost(),
            candidate_cost=self._candidate_cost(),
            evaluator_evidence=(_evidence(),),
        )
        self.assertIs(report.verdict, WorkshopVerdict.EQUIVALENT)

    def test_metric_keys_must_exactly_match_frozen_plan(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        with self.assertRaisesRegex(HarnessWorkshopModelError, "exactly match"):
            WorkshopEvaluationReport.evaluate(
                candidate=candidate,
                plan=plan,
                baseline_metrics={"success": 80, "critical-misses": 0},
                candidate_metrics={
                    "success": 90,
                    "critical-misses": 0,
                    "candidate-chosen-extra": 999,
                },
                baseline_cost=self._baseline_cost(),
                candidate_cost=self._candidate_cost(),
                evaluator_evidence=(_evidence(),),
            )

    def test_bind_rejects_forged_report_verdict(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80, "critical-misses": 0},
            candidate_metrics={"success": 95, "critical-misses": 1},
            baseline_cost=self._baseline_cost(),
            candidate_cost=self._candidate_cost(),
            evaluator_evidence=(_evidence(),),
        )
        forged = replace(report, verdict=WorkshopVerdict.IMPROVED)
        with self.assertRaisesRegex(HarnessWorkshopModelError, "verdict is inconsistent"):
            forged.bind(candidate, plan)

    def test_bind_rejects_report_after_plan_threshold_changes(self) -> None:
        candidate = self._candidate()
        plan = self._plan(candidate)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80, "critical-misses": 0},
            candidate_metrics={"success": 86, "critical-misses": 0},
            baseline_cost=self._baseline_cost(),
            candidate_cost=self._candidate_cost(),
            evaluator_evidence=(_evidence(),),
        )
        changed_plan = replace(
            plan,
            criteria=(
                WorkshopMetricCriterion(
                    "success",
                    MetricDirection.HIGHER_IS_BETTER,
                    minimum_improvement=20,
                    maximum_regression=0,
                ),
                plan.criteria[0]
                if plan.criteria[0].metric_id == "critical-misses"
                else plan.criteria[1],
            ),
        )
        with self.assertRaisesRegex(HarnessWorkshopModelError, "exact candidate and plan"):
            report.bind(candidate, changed_plan)


if __name__ == "__main__":
    unittest.main()
