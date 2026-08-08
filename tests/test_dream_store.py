from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_models import (
    DreamCandidate,
    DreamCandidateType,
    DreamInputManifest,
    EvidenceClass,
    EvidenceRef,
    MemoryEntry,
    MemoryGeneration,
    MemoryKind,
)
from origin_forge.dream_preprocess import EvidenceSnapshot
from origin_forge.dream_roles import DeterministicDreamAuditor
from origin_forge.dream_store import DreamStore, DreamStoreError
from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime


def sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def ref(
    ref_id: str,
    value: str,
    evidence_class: EvidenceClass,
    revision: int | None = None,
) -> EvidenceRef:
    return EvidenceRef(ref_id, sha(value), evidence_class, revision)


class DreamStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-store-test")
        self.store = DreamStore(self.runtime)
        self.run_id = new_id(IdKind.RUN)
        self.run_ref = ref(self.run_id, "run", EvidenceClass.TRAJECTORY, 1)
        self.manifest = DreamInputManifest.create(run_refs=(self.run_ref,))
        self.candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.PROCESS,
            summary="Inspect failing tests before implementation edits.",
            proposed_action="Benchmark a governed debugging Skill candidate.",
            evidence_refs=(self.run_ref,),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _audit(self):
        return DeterministicDreamAuditor().audit(
            self.candidate,
            self.manifest,
            EvidenceSnapshot.create((self.run_ref,)),
        )

    def test_manifest_candidate_and_audit_round_trip_are_hash_verified(self) -> None:
        self.store.put_manifest(self.manifest)
        self.store.put_candidate(self.candidate)
        audit = self._audit()
        audit_path = self.store.put_audit(audit)
        audit_id = audit_path.stem

        self.assertEqual(self.store.load_manifest(self.manifest.manifest_id), self.manifest)
        self.assertEqual(self.store.load_candidate(self.candidate.candidate_id), self.candidate)
        self.assertEqual(self.store.load_audit(audit_id), audit)
        self.assertEqual(self.store.list_manifest_ids(), (self.manifest.manifest_id,))
        self.assertEqual(self.store.list_candidate_ids(), (self.candidate.candidate_id,))
        self.assertEqual(self.store.list_audit_ids(), (audit_id,))
        self.assertEqual(audit_id, self.store.audit_report_id(audit))

    def test_same_id_is_idempotent_only_for_identical_bytes(self) -> None:
        first_path = self.store.put_candidate(self.candidate)
        second_path = self.store.put_candidate(self.candidate)
        self.assertEqual(first_path, second_path)

        changed = DreamCandidate(
            candidate_id=self.candidate.candidate_id,
            candidate_type=self.candidate.candidate_type,
            summary="Different semantic content.",
            proposed_action=self.candidate.proposed_action,
            evidence_refs=self.candidate.evidence_refs,
            contradiction_refs=self.candidate.contradiction_refs,
            target_memory_generation_id=self.candidate.target_memory_generation_id,
        )
        with self.assertRaisesRegex(DreamStoreError, "immutable and already exists"):
            self.store.put_candidate(changed)

    def test_candidate_tampering_is_detected_by_semantic_hash(self) -> None:
        path = self.store.put_candidate(self.candidate)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["summary"] = "tampered"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(DreamStoreError, "content hash mismatch"):
            self.store.load_candidate(self.candidate.candidate_id)

    def test_candidate_gate_tampering_is_rejected_even_if_content_hash_is_unchanged(self) -> None:
        path = self.store.put_candidate(self.candidate)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["required_gate"] = "DETERMINISTIC_VALIDATION"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(DreamStoreError, "downstream gate mismatch"):
            self.store.load_candidate(self.candidate.candidate_id)

    def test_memory_entry_and_generation_round_trip_preserve_lineage(self) -> None:
        decision = ref(
            new_id(IdKind.DECISION),
            "decision",
            EvidenceClass.CANONICAL,
            4,
        )
        entry = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Origin Forge owns verified state.",
            evidence_refs=(decision,),
        )
        verify = ref(
            new_id(IdKind.VERIFICATION),
            "dream-audit-verification",
            EvidenceClass.VERIFICATION,
            1,
        )
        generation = MemoryGeneration.create(
            parent_generation_id=None,
            dream_run_id=self.run_id,
            input_manifest=self.manifest,
            accepted_entries=(entry,),
            deferred_candidate_ids=(self.candidate.candidate_id,),
            audit_verification_ref=verify,
        )

        self.store.put_memory_entry(entry)
        self.store.put_generation(generation)
        self.assertEqual(self.store.load_memory_entry(entry.entry_id), entry)
        self.assertEqual(self.store.load_generation(generation.generation_id), generation)
        self.assertEqual(self.store.list_memory_entry_ids(), (entry.entry_id,))
        self.assertEqual(self.store.list_generation_ids(), (generation.generation_id,))

    def test_audit_reports_are_content_addressed_so_reaudit_never_overwrites_history(self) -> None:
        first = self._audit()
        first_path = self.store.put_audit(first)

        changed_snapshot = EvidenceSnapshot.create(
            (
                ref(
                    self.run_id,
                    "run changed",
                    EvidenceClass.TRAJECTORY,
                    2,
                ),
            )
        )
        second = DeterministicDreamAuditor().audit(
            self.candidate,
            self.manifest,
            changed_snapshot,
        )
        second_path = self.store.put_audit(second)

        self.assertNotEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first_path.name, second_path.name)
        self.assertEqual(len(self.store.list_audit_ids()), 2)
        self.assertEqual(self.store.load_audit(first_path.stem), first)
        self.assertEqual(self.store.load_audit(second_path.stem), second)

    def test_store_paths_are_contained_under_protected_project_state(self) -> None:
        self.store.ensure()
        state = self.runtime.state_dir.resolve()
        for path in (
            self.store.root,
            self.store.manifests_dir,
            self.store.candidates_dir,
            self.store.audits_dir,
            self.store.memory_entries_dir,
            self.store.generations_dir,
        ):
            path.resolve().relative_to(state)

    def test_symlinked_store_root_fails_closed(self) -> None:
        target = self.root / "outside-dream"
        target.mkdir()
        dream_root = self.runtime.state_dir / "dream"
        try:
            dream_root.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(DreamStoreError, "may not be a symlink"):
            self.store.ensure()

    def test_symlinked_object_file_is_never_followed(self) -> None:
        self.store.ensure()
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        candidate_path = self.store.candidates_dir / f"{self.candidate.candidate_id}.json"
        try:
            candidate_path.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(DreamStoreError, "invalid Dream candidate path"):
            self.store.load_candidate(self.candidate.candidate_id)

    def test_count_limit_fails_before_second_candidate_is_persisted(self) -> None:
        limited = DreamStore(self.runtime, max_candidates=1)
        limited.put_candidate(self.candidate)
        second = DreamCandidate.create(
            candidate_type=DreamCandidateType.DATA_QUALITY,
            summary="Second candidate.",
            proposed_action="Validate deterministically.",
            evidence_refs=(self.run_ref,),
        )
        with self.assertRaisesRegex(DreamStoreError, "catalog exceeds limit"):
            limited.put_candidate(second)
        self.assertFalse(
            limited.candidates_dir.joinpath(f"{second.candidate_id}.json").exists()
        )

    def test_byte_limit_fails_before_candidate_is_persisted(self) -> None:
        limited = DreamStore(self.runtime, max_candidate_bytes=64)
        with self.assertRaisesRegex(DreamStoreError, "exceeds byte limit"):
            limited.put_candidate(self.candidate)
        self.assertFalse(
            limited.candidates_dir.joinpath(f"{self.candidate.candidate_id}.json").exists()
        )

    def test_store_has_no_source_skill_policy_or_merge_mutation_surface(self) -> None:
        for forbidden in (
            "write_source",
            "apply_skill",
            "promote_skill",
            "change_policy",
            "merge",
            "mark_verified",
        ):
            self.assertFalse(hasattr(self.store, forbidden))


if __name__ == "__main__":
    unittest.main()
