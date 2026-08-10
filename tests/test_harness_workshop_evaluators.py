from __future__ import annotations

import unittest

from origin_forge.dream_models import EvidenceClass, EvidenceRef
from origin_forge.harness_workshop_evaluators import (
    is_trusted_workshop_evaluator,
    require_trusted_workshop_evaluator,
    trusted_workshop_protocols,
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
from origin_forge.harness_workshop_skill_adapter import PHASE12_SKILL_PROTOCOL
from origin_forge.ids import IdKind, new_id


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _evidence(kind: EvidenceClass) -> EvidenceRef:
    return EvidenceRef(
        ref_id=new_id(IdKind.ARTIFACT),
        content_hash=HASH_C,
        evidence_class=kind,
    )


class HarnessWorkshopEvaluatorTests(unittest.TestCase):
    def _plan(self, kind: HarnessComponentKind, protocol: str) -> WorkshopEvaluationPlan:
        candidate = HarnessImprovementCandidate.create(
            component_kind=kind,
            target_component_id=f"component.{kind.value.lower()}",
            target_version="1",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={"instructions": ["one bounded candidate"]},
            hypothesis="The frozen single-target candidate should improve measured outcomes.",
            source_evidence=(_evidence(EvidenceClass.TRAJECTORY),),
        )
        return WorkshopEvaluationPlan.create(
            candidate=candidate,
            evaluator_protocol=protocol,
            evaluation_evidence=(_evidence(EvidenceClass.BENCHMARK),),
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

    def test_v1_trust_registry_contains_only_phase12_skill_protocol(self) -> None:
        snapshot = trusted_workshop_protocols()
        self.assertEqual(snapshot["SKILL_BENCHMARK"], (PHASE12_SKILL_PROTOCOL,))
        for family, protocols in snapshot.items():
            if family != "SKILL_BENCHMARK":
                self.assertEqual(protocols, ())

    def test_phase12_skill_protocol_is_trusted(self) -> None:
        plan = self._plan(HarnessComponentKind.SKILL, PHASE12_SKILL_PROTOCOL)
        self.assertTrue(is_trusted_workshop_evaluator(plan))
        require_trusted_workshop_evaluator(plan)

    def test_arbitrary_skill_protocol_is_not_trusted(self) -> None:
        plan = self._plan(HarnessComponentKind.SKILL, "candidate-selected-scorer")
        self.assertFalse(is_trusted_workshop_evaluator(plan))
        with self.assertRaisesRegex(HarnessWorkshopModelError, "no promotion-capable trusted"):
            require_trusted_workshop_evaluator(plan)

    def test_non_skill_protocols_fail_closed_until_governed_adapter_exists(self) -> None:
        for kind, protocol in (
            (HarnessComponentKind.PROMPT, "prompt-benchmark-v1"),
            (HarnessComponentKind.CONTEXT_STRATEGY, "context-benchmark-v1"),
            (HarnessComponentKind.ROUTING_POLICY, "routing-benchmark-v1"),
            (HarnessComponentKind.SPECIALIST_CONTRACT, "specialist-benchmark-v1"),
            (HarnessComponentKind.MINI_WORKFLOW, "mini-workflow-benchmark-v1"),
        ):
            with self.subTest(kind=kind):
                plan = self._plan(kind, protocol)
                self.assertFalse(is_trusted_workshop_evaluator(plan))
                with self.assertRaises(HarnessWorkshopModelError):
                    require_trusted_workshop_evaluator(plan)


if __name__ == "__main__":
    unittest.main()
