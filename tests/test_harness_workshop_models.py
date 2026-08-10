from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.dream_models import DreamDownstreamGate, EvidenceClass, EvidenceRef
from origin_forge.harness_workshop_models import (
    DreamOriginRef,
    ExpectedEffectDirection,
    ExpectedMetricEffect,
    HarnessComponentKind,
    HarnessImprovementCandidate,
    HarnessWorkshopModelError,
    MetricDirection,
    WorkshopCostCeilings,
    WorkshopEvaluationPlan,
    WorkshopEvaluatorFamily,
    WorkshopMetricCriterion,
    canonical_payload_json,
)
from origin_forge.ids import IdKind, new_id, validate_id


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _evidence(index: int = 1) -> EvidenceRef:
    return EvidenceRef(
        ref_id=new_id(IdKind.RUN),
        content_hash="sha256:" + f"{index:064x}",
        evidence_class=EvidenceClass.TRAJECTORY,
    )


class HarnessWorkshopModelTests(unittest.TestCase):
    def _candidate(
        self,
        *,
        kind: HarnessComponentKind = HarnessComponentKind.SKILL,
        dream_origin: DreamOriginRef | None = None,
    ) -> HarnessImprovementCandidate:
        return HarnessImprovementCandidate.create(
            component_kind=kind,
            target_component_id="skill.python-tests",
            target_version="1.2.0",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={
                "instructions": ["inspect failures first", "make one bounded edit"],
                "max_retries": 2,
            },
            hypothesis="A narrower repair procedure should reduce repeated failed attempts.",
            source_evidence=(_evidence(1), _evidence(2)),
            expected_effects=(
                ExpectedMetricEffect(
                    "success-rate",
                    ExpectedEffectDirection.INCREASE,
                    "Fewer repeated repair loops should improve completion rate.",
                ),
            ),
            known_risks=("May under-explore ambiguous failures.",),
            dream_origin=dream_origin,
        )

    @staticmethod
    def _costs() -> WorkshopCostCeilings:
        return WorkshopCostCeilings(
            model_calls=100,
            input_tokens=1_000_000,
            output_tokens=250_000,
            wall_time_ms=3_600_000,
            resource_units=10_000,
        )

    def test_candidate_uses_infrastructure_owned_identity_and_content_hash(self) -> None:
        candidate = self._candidate()
        self.assertTrue(
            validate_id(candidate.candidate_id, IdKind.IMPROVEMENT_CANDIDATE)
        )
        self.assertTrue(candidate.content_hash.startswith("sha256:"))
        self.assertTrue(candidate.candidate_payload_hash.startswith("sha256:"))
        self.assertNotEqual(candidate.candidate_payload_hash, candidate.baseline_payload_hash)
        self.assertFalse(candidate.to_dict()["production_activation_authorized"])

    def test_candidate_payload_is_canonical_exact_json_data(self) -> None:
        first = canonical_payload_json({"b": [2, 1], "a": {"enabled": True}})
        second = canonical_payload_json({"a": {"enabled": True}, "b": [2, 1]})
        self.assertEqual(first, second)
        with self.assertRaisesRegex(HarnessWorkshopModelError, "floating-point"):
            canonical_payload_json({"temperature": 0.5})
        with self.assertRaisesRegex(HarnessWorkshopModelError, "exact JSON"):
            canonical_payload_json({"callback": lambda: None})
        with self.assertRaisesRegex(HarnessWorkshopModelError, "JSON object"):
            canonical_payload_json(["not", "an", "object"])

    def test_candidate_payload_must_change_from_baseline(self) -> None:
        payload = canonical_payload_json({"instructions": ["same"]})
        import hashlib

        baseline_hash = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.assertRaisesRegex(HarnessWorkshopModelError, "differ from baseline"):
            HarnessImprovementCandidate.create(
                component_kind=HarnessComponentKind.SKILL,
                target_component_id="skill.same",
                target_version="1",
                target_hash=HASH_A,
                baseline_payload_hash=baseline_hash,
                candidate_payload={"instructions": ["same"]},
                hypothesis="This intentionally fails because nothing actually changed.",
                source_evidence=(_evidence(),),
            )

    def test_candidate_evaluator_family_is_fixed_by_component_kind(self) -> None:
        candidate = self._candidate(kind=HarnessComponentKind.SKILL)
        self.assertIs(
            candidate.evaluator_family, WorkshopEvaluatorFamily.SKILL_BENCHMARK
        )
        with self.assertRaisesRegex(HarnessWorkshopModelError, "evaluator family"):
            replace(
                candidate,
                evaluator_family=WorkshopEvaluatorFamily.ROUTING_BENCHMARK,
            )

    def test_candidate_may_not_use_itself_as_source_evidence(self) -> None:
        candidate = self._candidate()
        self_ref = EvidenceRef(
            ref_id=candidate.candidate_id,
            content_hash=candidate.content_hash,
            evidence_class=EvidenceClass.DERIVED_MEMORY,
        )
        with self.assertRaisesRegex(HarnessWorkshopModelError, "self-reference"):
            replace(candidate, source_evidence=(self_ref,))

    def test_dream_origin_preserves_required_downstream_gate(self) -> None:
        origin = DreamOriginRef(
            candidate_id=new_id(IdKind.DREAM_CANDIDATE),
            candidate_hash=HASH_C,
            required_gate=DreamDownstreamGate.SKILL_EVALUATION,
        )
        candidate = self._candidate(dream_origin=origin)
        self.assertEqual(
            candidate.to_dict()["dream_origin"]["required_gate"],
            DreamDownstreamGate.SKILL_EVALUATION.value,
        )
        wrong = DreamOriginRef(
            candidate_id=new_id(IdKind.DREAM_CANDIDATE),
            candidate_hash=HASH_C,
            required_gate=DreamDownstreamGate.ROUTING_BENCHMARK,
        )
        with self.assertRaisesRegex(HarnessWorkshopModelError, "downstream gate"):
            self._candidate(dream_origin=wrong)

    def test_plan_is_independently_identified_and_bound_to_exact_candidate_hash(self) -> None:
        candidate = self._candidate()
        plan = WorkshopEvaluationPlan.create(
            candidate=candidate,
            evaluator_protocol="paired-skill-ab-v1",
            evaluation_evidence=(
                EvidenceRef(
                    ref_id=new_id(IdKind.ARTIFACT),
                    content_hash=HASH_C,
                    evidence_class=EvidenceClass.BENCHMARK,
                ),
            ),
            criteria=(
                WorkshopMetricCriterion(
                    "correctness-score",
                    MetricDirection.HIGHER_IS_BETTER,
                    minimum_improvement=1,
                    maximum_regression=0,
                ),
            ),
            cost_ceilings=self._costs(),
        )
        self.assertTrue(validate_id(plan.plan_id, IdKind.WORKSHOP_EVALUATION_PLAN))
        self.assertEqual(plan.candidate_hash, candidate.content_hash)
        self.assertEqual(
            plan.to_dict()["candidate_controls_acceptance_gate"], False
        )
        plan.bind_candidate(candidate)

        changed_candidate = replace(
            candidate,
            hypothesis="A different hypothesis creates a different immutable candidate hash.",
        )
        with self.assertRaisesRegex(HarnessWorkshopModelError, "exact improvement candidate"):
            plan.bind_candidate(changed_candidate)

    def test_plan_acceptance_metrics_are_not_candidate_expected_effects(self) -> None:
        candidate = self._candidate()
        self.assertEqual(candidate.expected_effects[0].metric_id, "success-rate")
        plan = WorkshopEvaluationPlan.create(
            candidate=candidate,
            evaluator_protocol="paired-skill-ab-v1",
            evaluation_evidence=(
                EvidenceRef(
                    ref_id=new_id(IdKind.ARTIFACT),
                    content_hash=HASH_C,
                    evidence_class=EvidenceClass.BENCHMARK,
                ),
            ),
            criteria=(
                WorkshopMetricCriterion(
                    "critical-regressions",
                    MetricDirection.MUST_NOT_REGRESS,
                    minimum_improvement=0,
                    maximum_regression=0,
                ),
            ),
            cost_ceilings=self._costs(),
        )
        self.assertEqual(plan.criteria[0].metric_id, "critical-regressions")

    def test_plan_may_not_use_candidate_as_acceptance_evidence(self) -> None:
        candidate = self._candidate()
        with self.assertRaisesRegex(HarnessWorkshopModelError, "self-reference"):
            WorkshopEvaluationPlan.create(
                candidate=candidate,
                evaluator_protocol="paired-skill-ab-v1",
                evaluation_evidence=(
                    EvidenceRef(
                        ref_id=candidate.candidate_id,
                        content_hash=candidate.content_hash,
                        evidence_class=EvidenceClass.BENCHMARK,
                    ),
                ),
                criteria=(
                    WorkshopMetricCriterion(
                        "success-rate",
                        MetricDirection.HIGHER_IS_BETTER,
                        minimum_improvement=1,
                        maximum_regression=0,
                    ),
                ),
                cost_ceilings=self._costs(),
            )

    def test_must_not_regress_criterion_forbids_nonzero_regression_budget(self) -> None:
        with self.assertRaisesRegex(HarnessWorkshopModelError, "zero maximum_regression"):
            WorkshopMetricCriterion(
                "safety-regressions",
                MetricDirection.MUST_NOT_REGRESS,
                minimum_improvement=0,
                maximum_regression=1,
            )


if __name__ == "__main__":
    unittest.main()
