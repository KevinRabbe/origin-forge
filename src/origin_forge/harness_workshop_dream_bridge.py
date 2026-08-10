from __future__ import annotations

from typing import Iterable

from .dream_models import (
    DreamCandidateType,
    DreamDownstreamGate,
    EvidenceClass,
    EvidenceRef,
)
from .harness_workshop_models import (
    DreamOriginRef,
    ExpectedMetricEffect,
    HarnessComponentKind,
    HarnessImprovementCandidate,
    HarnessWorkshopModelError,
)


_DIRECT_KIND_MAP = {
    DreamCandidateType.SKILL: HarnessComponentKind.SKILL,
    DreamCandidateType.ROUTING: HarnessComponentKind.ROUTING_POLICY,
    DreamCandidateType.CONTEXT: HarnessComponentKind.CONTEXT_STRATEGY,
}

_EXPECTED_DREAM_GATE = {
    DreamCandidateType.SKILL: DreamDownstreamGate.SKILL_EVALUATION,
    DreamCandidateType.ROUTING: DreamDownstreamGate.ROUTING_BENCHMARK,
    DreamCandidateType.CONTEXT: DreamDownstreamGate.CONTEXT_BENCHMARK,
    DreamCandidateType.PROCESS: DreamDownstreamGate.ENGINEERING_REVIEW,
}

_PROCESS_TARGETS = {
    HarnessComponentKind.PROMPT,
    HarnessComponentKind.SPECIALIST_CONTRACT,
    HarnessComponentKind.MINI_WORKFLOW,
}


def bridge_dream_candidate(
    *,
    dream_candidate_type: DreamCandidateType,
    dream_origin: DreamOriginRef,
    target_component_id: str,
    target_version: str,
    target_hash: str,
    baseline_payload_hash: str,
    candidate_payload: object,
    hypothesis: str,
    process_target_kind: HarnessComponentKind | None = None,
    expected_effects: Iterable[ExpectedMetricEffect] = (),
    known_risks: Iterable[str] = (),
) -> HarnessImprovementCandidate:
    """Convert an exact Dream proposal reference into workshop proposal evidence.

    This bridge does not satisfy the Dream candidate's required downstream gate.
    It only binds the exact Dream ID/hash/type/gate as source evidence for a new
    independently evaluated workshop candidate.
    """

    if not isinstance(dream_candidate_type, DreamCandidateType):
        raise HarnessWorkshopModelError("dream_candidate_type is invalid")
    if not isinstance(dream_origin, DreamOriginRef):
        raise TypeError("dream_origin must be a DreamOriginRef")
    expected_gate = _EXPECTED_DREAM_GATE.get(dream_candidate_type)
    if expected_gate is None:
        raise HarnessWorkshopModelError(
            "Dream MEMORY and DATA_QUALITY candidates keep their Phase-15 downstream gates"
        )
    if dream_origin.required_gate is not expected_gate:
        raise HarnessWorkshopModelError(
            "Dream origin gate does not match the declared Dream candidate type"
        )

    if dream_candidate_type is DreamCandidateType.PROCESS:
        if process_target_kind not in _PROCESS_TARGETS:
            raise HarnessWorkshopModelError(
                "Dream PROCESS bridge requires explicit PROMPT, SPECIALIST_CONTRACT, or MINI_WORKFLOW target"
            )
        component_kind = process_target_kind
    else:
        if process_target_kind is not None:
            raise HarnessWorkshopModelError(
                "process_target_kind is valid only for Dream PROCESS candidates"
            )
        component_kind = _DIRECT_KIND_MAP[dream_candidate_type]

    dream_ref = EvidenceRef(
        ref_id=dream_origin.candidate_id,
        content_hash=dream_origin.candidate_hash,
        evidence_class=EvidenceClass.DERIVED_MEMORY,
    )
    candidate = HarnessImprovementCandidate.create(
        component_kind=component_kind,
        target_component_id=target_component_id,
        target_version=target_version,
        target_hash=target_hash,
        baseline_payload_hash=baseline_payload_hash,
        candidate_payload=candidate_payload,
        hypothesis=hypothesis,
        source_evidence=(dream_ref,),
        expected_effects=tuple(expected_effects),
        known_risks=tuple(known_risks),
        dream_origin=dream_origin,
    )
    if candidate.dream_origin != dream_origin:
        raise HarnessWorkshopModelError("Dream bridge lost exact origin binding")
    return candidate
