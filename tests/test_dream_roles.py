from __future__ import annotations

import hashlib
import unittest

from origin_forge.dream_models import (
    DreamCandidate,
    DreamCandidateType,
    DreamInputManifest,
    EvidenceClass,
    EvidenceRef,
    MemoryEntry,
    MemoryKind,
)
from origin_forge.dream_preprocess import EvidenceSnapshot, preprocess_memory
from origin_forge.dream_roles import (
    DeterministicDreamAuditor,
    DreamAnalysisPackage,
    DreamAuditFindingCode,
    DreamAuditStatus,
    DreamRoleError,
)
from origin_forge.ids import IdKind, new_id


def sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def ref(
    ref_id: str,
    value: str,
    evidence_class: EvidenceClass,
    revision: int | None = None,
) -> EvidenceRef:
    return EvidenceRef(ref_id, sha(value), evidence_class, revision)


class DreamRoleTests(unittest.TestCase):
    def _run_ref(self, *, revision: int = 1, value: str = "run") -> EvidenceRef:
        return ref(new_id(IdKind.RUN), value, EvidenceClass.TRAJECTORY, revision)

    def test_analysis_package_is_order_normalized_and_pins_preprocess_report(self) -> None:
        decision = ref(
            new_id(IdKind.DECISION),
            "decision",
            EvidenceClass.CANONICAL,
            2,
        )
        first = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="First derived fact.",
            evidence_refs=(decision,),
        )
        second = MemoryEntry.create(
            kind=MemoryKind.PROJECT_CONVENTION,
            claim="Second derived fact.",
            evidence_refs=(decision,),
        )
        snapshot = EvidenceSnapshot.create((decision,))
        report = preprocess_memory((first, second), snapshot)
        manifest = DreamInputManifest.create(memory_refs=(first.as_evidence_ref(), second.as_evidence_ref()))

        package_a = DreamAnalysisPackage(manifest, report, (second, first))
        package_b = DreamAnalysisPackage(manifest, report, (first, second))
        self.assertEqual(package_a.memory_entries, package_b.memory_entries)
        self.assertEqual(package_a.content_hash, package_b.content_hash)
        self.assertTrue(package_a.content_hash.startswith("sha256:"))

    def test_analysis_package_requires_preprocess_count_to_match_memory_entries(self) -> None:
        decision = ref(new_id(IdKind.DECISION), "decision", EvidenceClass.CANONICAL)
        entry = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Derived fact.",
            evidence_refs=(decision,),
        )
        report = preprocess_memory((entry,), EvidenceSnapshot.create((decision,)))
        with self.assertRaisesRegex(DreamRoleError, "do not match preprocessing report count"):
            DreamAnalysisPackage(DreamInputManifest.create(), report, ())

    def test_exact_current_manifest_evidence_is_structurally_valid_but_semantic_review_required(self) -> None:
        run = self._run_ref()
        manifest = DreamInputManifest.create(run_refs=(run,))
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.PROCESS,
            summary="Inspect failing tests before editing implementation.",
            proposed_action="Propose a debugging Skill benchmark.",
            evidence_refs=(run,),
        )
        report = DeterministicDreamAuditor().audit(
            candidate,
            manifest,
            EvidenceSnapshot.create((run,)),
        )
        self.assertEqual(report.status, DreamAuditStatus.STRUCTURALLY_VALID)
        self.assertTrue(report.semantic_review_required)
        self.assertEqual(report.findings, ())
        self.assertEqual(report.required_gate, candidate.required_gate.value)

    def test_data_quality_candidate_can_be_structurally_valid_without_semantic_review(self) -> None:
        run = self._run_ref()
        manifest = DreamInputManifest.create(run_refs=(run,))
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.DATA_QUALITY,
            summary="Rebuild a stale derived index.",
            proposed_action="Run deterministic index reconstruction.",
            evidence_refs=(run,),
        )
        report = DeterministicDreamAuditor().audit(
            candidate,
            manifest,
            EvidenceSnapshot.create((run,)),
        )
        self.assertEqual(report.status, DreamAuditStatus.STRUCTURALLY_VALID)
        self.assertFalse(report.semantic_review_required)

    def test_evidence_outside_frozen_manifest_is_rejected(self) -> None:
        manifest_run = self._run_ref(value="manifest")
        outsider = self._run_ref(value="outsider")
        manifest = DreamInputManifest.create(run_refs=(manifest_run,))
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.PROCESS,
            summary="Unsupported candidate.",
            proposed_action="Do not apply.",
            evidence_refs=(outsider,),
        )
        report = DeterministicDreamAuditor().audit(
            candidate,
            manifest,
            EvidenceSnapshot.create((manifest_run, outsider)),
        )
        self.assertEqual(report.status, DreamAuditStatus.REJECTED)
        self.assertEqual(
            [finding.code for finding in report.findings],
            [DreamAuditFindingCode.EVIDENCE_OUTSIDE_MANIFEST],
        )

    def test_missing_current_evidence_defers_instead_of_guessing(self) -> None:
        run = self._run_ref()
        manifest = DreamInputManifest.create(run_refs=(run,))
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.MEMORY,
            summary="Derived memory candidate.",
            proposed_action="Add only after audit.",
            evidence_refs=(run,),
        )
        report = DeterministicDreamAuditor().audit(
            candidate,
            manifest,
            EvidenceSnapshot.create(()),
        )
        self.assertEqual(report.status, DreamAuditStatus.DEFERRED)
        self.assertEqual(report.findings[0].code, DreamAuditFindingCode.EVIDENCE_NOT_CURRENT)

    def test_hash_revision_and_class_drift_are_all_visible_and_deferred(self) -> None:
        run_id = new_id(IdKind.RUN)
        frozen = ref(run_id, "v1", EvidenceClass.TRAJECTORY, 1)
        current = ref(run_id, "v2", EvidenceClass.CANONICAL, 2)
        manifest = DreamInputManifest.create(run_refs=(frozen,))
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.ROUTING,
            summary="Routing candidate.",
            proposed_action="Benchmark before policy change.",
            evidence_refs=(frozen,),
        )
        report = DeterministicDreamAuditor().audit(
            candidate,
            manifest,
            EvidenceSnapshot.create((current,)),
        )
        self.assertEqual(report.status, DreamAuditStatus.DEFERRED)
        self.assertEqual(
            {finding.code for finding in report.findings},
            {
                DreamAuditFindingCode.EVIDENCE_HASH_CHANGED,
                DreamAuditFindingCode.EVIDENCE_REVISION_CHANGED,
                DreamAuditFindingCode.EVIDENCE_CLASS_CHANGED,
            },
        )

    def test_target_memory_generation_mismatch_is_rejected(self) -> None:
        run = self._run_ref()
        parent = new_id(IdKind.MEMORY_GENERATION)
        other = new_id(IdKind.MEMORY_GENERATION)
        manifest = DreamInputManifest.create(
            parent_memory_generation_id=parent,
            run_refs=(run,),
        )
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.MEMORY,
            summary="Targeted memory update.",
            proposed_action="Supersede old derived memory.",
            evidence_refs=(run,),
            target_memory_generation_id=other,
        )
        report = DeterministicDreamAuditor().audit(
            candidate,
            manifest,
            EvidenceSnapshot.create((run,)),
        )
        self.assertEqual(report.status, DreamAuditStatus.REJECTED)
        self.assertIn(
            DreamAuditFindingCode.TARGET_GENERATION_MISMATCH,
            [finding.code for finding in report.findings],
        )

    def test_audit_report_is_deterministic_and_pins_candidate_manifest_snapshot(self) -> None:
        run = self._run_ref()
        manifest = DreamInputManifest.create(run_refs=(run,))
        snapshot = EvidenceSnapshot.create((run,))
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.SKILL,
            summary="Skill candidate.",
            proposed_action="Send to paired Skill evaluation.",
            evidence_refs=(run,),
        )
        auditor = DeterministicDreamAuditor()
        first = auditor.audit(candidate, manifest, snapshot)
        second = auditor.audit(candidate, manifest, snapshot)
        self.assertEqual(first, second)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.candidate_hash, candidate.content_hash)
        self.assertEqual(first.manifest_hash, manifest.content_hash)
        self.assertEqual(first.evidence_snapshot_hash, snapshot.content_hash)

    def test_auditor_exposes_no_promotion_or_mutation_operation(self) -> None:
        auditor = DeterministicDreamAuditor()
        for forbidden in ("promote", "apply", "write", "merge", "change_policy"):
            self.assertFalse(hasattr(auditor, forbidden))


if __name__ == "__main__":
    unittest.main()
