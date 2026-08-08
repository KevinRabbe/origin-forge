from __future__ import annotations

import hashlib
import unittest

from origin_forge.dream_deterministic_analyzer import DeterministicDreamAnalyzer
from origin_forge.dream_models import (
    DreamBudget,
    DreamCandidateType,
    DreamDownstreamGate,
    DreamInputManifest,
    EvidenceClass,
    EvidenceRef,
    MemoryEntry,
    MemoryKind,
)
from origin_forge.dream_preprocess import EvidenceSnapshot, preprocess_memory
from origin_forge.dream_roles import DreamAnalysisPackage, DreamRoleError
from origin_forge.ids import IdKind, new_id


def sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def decision_ref(value="decision-v1", revision=1):
    return EvidenceRef(
        new_id(IdKind.DECISION),
        sha(value),
        EvidenceClass.CANONICAL,
        revision,
    )


class DeterministicDreamAnalyzerTests(unittest.TestCase):
    def test_duplicate_memory_becomes_data_quality_candidate_only(self) -> None:
        decision = decision_ref()
        first = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Origin Forge owns verified state.",
            evidence_refs=(decision,),
        )
        second = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Origin Forge owns verified state.",
            evidence_refs=(decision,),
        )
        report = preprocess_memory(
            (second, first),
            EvidenceSnapshot.create((decision,)),
        )
        manifest = DreamInputManifest.create(
            decision_refs=(decision,),
            memory_refs=(first.as_evidence_ref(), second.as_evidence_ref()),
        )
        package = DreamAnalysisPackage(manifest, report, (second, first))
        candidates = DeterministicDreamAnalyzer().analyze(package)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.candidate_type, DreamCandidateType.DATA_QUALITY)
        self.assertEqual(candidate.required_gate, DreamDownstreamGate.DETERMINISTIC_VALIDATION)
        self.assertIn("DUPLICATE_MEMORY", candidate.summary)
        self.assertEqual(
            {item.ref_id for item in candidate.evidence_refs},
            {first.entry_id, second.entry_id},
        )

    def test_changed_evidence_candidate_pins_memory_and_frozen_source(self) -> None:
        decision_id = new_id(IdKind.DECISION)
        old = EvidenceRef(decision_id, sha("old"), EvidenceClass.CANONICAL, 1)
        current = EvidenceRef(decision_id, sha("new"), EvidenceClass.CANONICAL, 2)
        entry = MemoryEntry.create(
            kind=MemoryKind.PROJECT_CONVENTION,
            claim="Use config version four.",
            evidence_refs=(old,),
        )
        report = preprocess_memory((entry,), EvidenceSnapshot.create((current,)))
        manifest = DreamInputManifest.create(
            decision_refs=(old,),
            memory_refs=(entry.as_evidence_ref(),),
        )
        package = DreamAnalysisPackage(manifest, report, (entry,))
        candidates = DeterministicDreamAnalyzer().analyze(package)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            {item.candidate_type for item in candidates},
            {DreamCandidateType.DATA_QUALITY},
        )
        for candidate in candidates:
            self.assertEqual(
                {item.ref_id for item in candidate.evidence_refs},
                {entry.entry_id, decision_id},
            )
            self.assertEqual(candidate.required_gate, DreamDownstreamGate.DETERMINISTIC_VALIDATION)

    def test_no_findings_means_no_candidates(self) -> None:
        decision = decision_ref()
        entry = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Stable fact.",
            evidence_refs=(decision,),
        )
        report = preprocess_memory((entry,), EvidenceSnapshot.create((decision,)))
        manifest = DreamInputManifest.create(
            decision_refs=(decision,),
            memory_refs=(entry.as_evidence_ref(),),
        )
        package = DreamAnalysisPackage(manifest, report, (entry,))
        self.assertEqual(DeterministicDreamAnalyzer().analyze(package), ())

    def test_memory_entry_must_be_pinned_by_frozen_manifest(self) -> None:
        decision = decision_ref()
        entry = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Derived fact.",
            evidence_refs=(decision,),
        )
        report = preprocess_memory((entry,), EvidenceSnapshot.create(()))
        manifest = DreamInputManifest.create(decision_refs=(decision,))
        package = DreamAnalysisPackage(manifest, report, (entry,))
        with self.assertRaisesRegex(DreamRoleError, "not pinned"):
            DeterministicDreamAnalyzer().analyze(package)

    def test_candidate_budget_is_enforced_after_each_candidate(self) -> None:
        decision = decision_ref()
        entries = tuple(
            MemoryEntry.create(
                kind=MemoryKind.ARCHITECTURAL_FACT,
                claim=f"Duplicate {index // 2}",
                evidence_refs=(decision,),
            )
            for index in range(4)
        )
        # Force two semantic duplicate pairs by constructing pairwise-identical claims.
        paired = (
            MemoryEntry.create(
                kind=MemoryKind.ARCHITECTURAL_FACT,
                claim="A",
                evidence_refs=(decision,),
            ),
            MemoryEntry.create(
                kind=MemoryKind.ARCHITECTURAL_FACT,
                claim="A",
                evidence_refs=(decision,),
            ),
            MemoryEntry.create(
                kind=MemoryKind.ARCHITECTURAL_FACT,
                claim="B",
                evidence_refs=(decision,),
            ),
            MemoryEntry.create(
                kind=MemoryKind.ARCHITECTURAL_FACT,
                claim="B",
                evidence_refs=(decision,),
            ),
        )
        del entries
        report = preprocess_memory(paired, EvidenceSnapshot.create((decision,)))
        manifest = DreamInputManifest.create(
            decision_refs=(decision,),
            memory_refs=tuple(item.as_evidence_ref() for item in paired),
            budget=DreamBudget(max_candidates=1),
        )
        package = DreamAnalysisPackage(manifest, report, paired)
        with self.assertRaisesRegex(DreamRoleError, "exceed frozen manifest budget"):
            DeterministicDreamAnalyzer().analyze(package)

    def test_analyzer_has_no_mutation_or_promotion_surface(self) -> None:
        analyzer = DeterministicDreamAnalyzer()
        for forbidden in ("apply", "promote", "write", "merge", "change_policy"):
            self.assertFalse(hasattr(analyzer, forbidden))


if __name__ == "__main__":
    unittest.main()
