from __future__ import annotations

import hashlib
import unittest

from origin_forge.dream_models import EvidenceClass, EvidenceRef, MemoryEntry, MemoryKind
from origin_forge.dream_preprocess import (
    DreamFindingType,
    DreamPreprocessError,
    EvidenceSnapshot,
    preprocess_memory,
)
from origin_forge.ids import IdKind, new_id


def sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def evidence(
    ref_id: str,
    value: str,
    *,
    revision: int | None = None,
) -> EvidenceRef:
    return EvidenceRef(ref_id, sha(value), EvidenceClass.CANONICAL, revision)


def memory(claim: str, evidence_ref: EvidenceRef) -> MemoryEntry:
    return MemoryEntry.create(
        kind=MemoryKind.ARCHITECTURAL_FACT,
        claim=claim,
        evidence_refs=(evidence_ref,),
    )


class DreamPreprocessTests(unittest.TestCase):
    def test_unchanged_pinned_evidence_produces_no_staleness_finding(self) -> None:
        decision_id = new_id(IdKind.DECISION)
        pinned = evidence(decision_id, "decision-v1", revision=1)
        entry = memory("Config is version five.", pinned)
        report = preprocess_memory((entry,), EvidenceSnapshot.create((pinned,)))
        self.assertEqual(report.findings, ())
        self.assertEqual(report.memory_entry_count, 1)
        self.assertTrue(report.content_hash.startswith("sha256:"))

    def test_duplicate_memory_is_detected_by_semantic_hash_not_opaque_id(self) -> None:
        decision_id = new_id(IdKind.DECISION)
        pinned = evidence(decision_id, "decision", revision=1)
        first = memory("Use verified state as truth.", pinned)
        second = memory("Use verified state as truth.", pinned)
        self.assertNotEqual(first.entry_id, second.entry_id)
        self.assertEqual(first.content_hash, second.content_hash)

        report = preprocess_memory((second, first), EvidenceSnapshot.create((pinned,)))
        duplicate = [
            finding
            for finding in report.findings
            if finding.finding_type == DreamFindingType.DUPLICATE_MEMORY
        ]
        self.assertEqual(len(duplicate), 1)
        retained, removed = sorted((first.entry_id, second.entry_id))
        self.assertEqual(duplicate[0].memory_entry_id, removed)
        self.assertEqual(duplicate[0].related_entry_ids, (retained,))

    def test_missing_evidence_is_detected_without_rewriting_memory(self) -> None:
        pinned = evidence(new_id(IdKind.DECISION), "decision", revision=1)
        entry = memory("A derived fact.", pinned)
        before = entry.to_dict()
        report = preprocess_memory((entry,), EvidenceSnapshot.create(()))
        self.assertEqual(
            [finding.finding_type for finding in report.findings],
            [DreamFindingType.MISSING_EVIDENCE],
        )
        self.assertEqual(entry.to_dict(), before)

    def test_changed_hash_and_revision_are_reported_as_separate_exact_facts(self) -> None:
        decision_id = new_id(IdKind.DECISION)
        pinned = evidence(decision_id, "decision-v1", revision=1)
        current = evidence(decision_id, "decision-v2", revision=2)
        entry = memory("Old derived interpretation.", pinned)

        report = preprocess_memory((entry,), EvidenceSnapshot.create((current,)))
        self.assertEqual(
            [finding.finding_type for finding in report.findings],
            [
                DreamFindingType.EVIDENCE_HASH_CHANGED,
                DreamFindingType.EVIDENCE_REVISION_CHANGED,
            ],
        )
        hash_finding = report.findings[0]
        self.assertEqual(hash_finding.expected_hash, pinned.content_hash)
        self.assertEqual(hash_finding.current_hash, current.content_hash)
        self.assertEqual(hash_finding.expected_revision, 1)
        self.assertEqual(hash_finding.current_revision, 2)

    def test_explicitly_superseded_source_is_detected_even_when_hash_is_unchanged(self) -> None:
        decision_id = new_id(IdKind.DECISION)
        pinned = evidence(decision_id, "decision-v1", revision=1)
        entry = memory("Derived from an older decision.", pinned)
        report = preprocess_memory(
            (entry,),
            EvidenceSnapshot.create((pinned,), superseded_ref_ids=(decision_id,)),
        )
        self.assertEqual(
            [finding.finding_type for finding in report.findings],
            [DreamFindingType.SOURCE_SUPERSEDED],
        )

    def test_preprocessing_is_deterministic_across_input_order(self) -> None:
        first_id = new_id(IdKind.DECISION)
        second_id = new_id(IdKind.DECISION)
        old_first = evidence(first_id, "one-old", revision=1)
        new_first = evidence(first_id, "one-new", revision=2)
        stable_second = evidence(second_id, "two", revision=1)
        one = memory("First fact.", old_first)
        two = memory("Second fact.", stable_second)

        snapshot_a = EvidenceSnapshot.create((new_first, stable_second))
        snapshot_b = EvidenceSnapshot.create((stable_second, new_first))
        report_a = preprocess_memory((one, two), snapshot_a)
        report_b = preprocess_memory((two, one), snapshot_b)
        self.assertEqual(snapshot_a.content_hash, snapshot_b.content_hash)
        self.assertEqual(report_a.to_dict(), report_b.to_dict())

    def test_evidence_snapshot_rejects_ambiguous_current_ref_ids(self) -> None:
        decision_id = new_id(IdKind.DECISION)
        with self.assertRaisesRegex(DreamPreprocessError, "duplicate ref IDs"):
            EvidenceSnapshot.create(
                (
                    evidence(decision_id, "v1", revision=1),
                    evidence(decision_id, "v2", revision=2),
                )
            )

    def test_preprocessing_entry_count_is_hard_bounded(self) -> None:
        pinned = evidence(new_id(IdKind.DECISION), "decision")
        entry = memory("bounded", pinned)
        with self.assertRaisesRegex(DreamPreprocessError, "memory entry count exceeds"):
            preprocess_memory((entry,) * 2049, EvidenceSnapshot.create((pinned,)))


if __name__ == "__main__":
    unittest.main()
