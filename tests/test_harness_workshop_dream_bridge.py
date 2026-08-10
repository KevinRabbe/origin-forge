from __future__ import annotations

import unittest

from origin_forge.dream_models import DreamCandidateType, DreamDownstreamGate
from origin_forge.harness_workshop_dream_bridge import bridge_dream_candidate
from origin_forge.harness_workshop_models import (
    DreamOriginRef,
    HarnessComponentKind,
    HarnessWorkshopModelError,
)
from origin_forge.ids import IdKind, new_id


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _origin(gate: DreamDownstreamGate) -> DreamOriginRef:
    return DreamOriginRef(
        candidate_id=new_id(IdKind.DREAM_CANDIDATE),
        candidate_hash=HASH_C,
        required_gate=gate,
    )


class HarnessWorkshopDreamBridgeTests(unittest.TestCase):
    def _bridge(
        self,
        dream_type: DreamCandidateType,
        gate: DreamDownstreamGate,
        *,
        process_target_kind: HarnessComponentKind | None = None,
    ):
        return bridge_dream_candidate(
            dream_candidate_type=dream_type,
            dream_origin=_origin(gate),
            target_component_id="component.target",
            target_version="1",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={"instructions": ["one bounded proposal"]},
            hypothesis="The Dream proposal is only source evidence for independent evaluation.",
            process_target_kind=process_target_kind,
        )

    def test_skill_dream_maps_to_skill_and_preserves_exact_origin(self) -> None:
        candidate = self._bridge(
            DreamCandidateType.SKILL,
            DreamDownstreamGate.SKILL_EVALUATION,
        )
        self.assertIs(candidate.component_kind, HarnessComponentKind.SKILL)
        self.assertIs(
            candidate.dream_origin.required_gate,
            DreamDownstreamGate.SKILL_EVALUATION,
        )
        self.assertEqual(candidate.source_evidence[0].ref_id, candidate.dream_origin.candidate_id)
        self.assertEqual(
            candidate.source_evidence[0].content_hash,
            candidate.dream_origin.candidate_hash,
        )
        self.assertFalse(candidate.to_dict()["production_activation_authorized"])

    def test_routing_and_context_dreams_keep_their_gate_semantics(self) -> None:
        routing = self._bridge(
            DreamCandidateType.ROUTING,
            DreamDownstreamGate.ROUTING_BENCHMARK,
        )
        context = self._bridge(
            DreamCandidateType.CONTEXT,
            DreamDownstreamGate.CONTEXT_BENCHMARK,
        )
        self.assertIs(routing.component_kind, HarnessComponentKind.ROUTING_POLICY)
        self.assertIs(context.component_kind, HarnessComponentKind.CONTEXT_STRATEGY)

    def test_process_dream_requires_explicit_bounded_target_mapping(self) -> None:
        for kind in (
            HarnessComponentKind.PROMPT,
            HarnessComponentKind.SPECIALIST_CONTRACT,
            HarnessComponentKind.MINI_WORKFLOW,
        ):
            with self.subTest(kind=kind):
                candidate = self._bridge(
                    DreamCandidateType.PROCESS,
                    DreamDownstreamGate.ENGINEERING_REVIEW,
                    process_target_kind=kind,
                )
                self.assertIs(candidate.component_kind, kind)
        with self.assertRaisesRegex(HarnessWorkshopModelError, "requires explicit"):
            self._bridge(
                DreamCandidateType.PROCESS,
                DreamDownstreamGate.ENGINEERING_REVIEW,
            )
        with self.assertRaisesRegex(HarnessWorkshopModelError, "requires explicit"):
            self._bridge(
                DreamCandidateType.PROCESS,
                DreamDownstreamGate.ENGINEERING_REVIEW,
                process_target_kind=HarnessComponentKind.ROUTING_POLICY,
            )

    def test_memory_and_data_quality_do_not_silently_enter_workshop(self) -> None:
        for dream_type, gate in (
            (DreamCandidateType.MEMORY, DreamDownstreamGate.DREAM_AUDIT),
            (DreamCandidateType.DATA_QUALITY, DreamDownstreamGate.DETERMINISTIC_VALIDATION),
        ):
            with self.subTest(dream_type=dream_type):
                with self.assertRaisesRegex(HarnessWorkshopModelError, "keep their Phase-15"):
                    self._bridge(dream_type, gate)

    def test_mismatched_dream_type_and_downstream_gate_is_rejected(self) -> None:
        with self.assertRaisesRegex(HarnessWorkshopModelError, "does not match"):
            self._bridge(
                DreamCandidateType.SKILL,
                DreamDownstreamGate.ROUTING_BENCHMARK,
            )

    def test_non_process_dream_cannot_choose_an_arbitrary_workshop_target_kind(self) -> None:
        with self.assertRaisesRegex(HarnessWorkshopModelError, "valid only"):
            self._bridge(
                DreamCandidateType.SKILL,
                DreamDownstreamGate.SKILL_EVALUATION,
                process_target_kind=HarnessComponentKind.PROMPT,
            )


if __name__ == "__main__":
    unittest.main()
