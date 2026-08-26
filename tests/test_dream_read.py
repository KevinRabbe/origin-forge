from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.dream_read as read_module
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
from origin_forge.dream_read import DreamReadError, DreamReadService
from origin_forge.dream_roles import DeterministicDreamAuditor
from origin_forge.dream_store import DreamStore
from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime


def _hash(char: str) -> str:
    return "sha256:" + char * 64


class DreamReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-read-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _fixture(self) -> tuple[str, str, str, str, str]:
        store = DreamStore(self.runtime)
        run_id = new_id(IdKind.RUN)
        run_ref = EvidenceRef(run_id, _hash("a"), EvidenceClass.TRAJECTORY, 1)
        manifest = DreamInputManifest.create(run_refs=(run_ref,))
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.PROCESS,
            summary='<script>alert("candidate")</script>',
            proposed_action="Benchmark a governed improvement candidate.",
            evidence_refs=(run_ref,),
        )
        audit = DeterministicDreamAuditor().audit(
            candidate,
            manifest,
            EvidenceSnapshot.create((run_ref,)),
        )
        memory_ref = EvidenceRef(
            new_id(IdKind.DECISION),
            _hash("b"),
            EvidenceClass.CANONICAL,
            2,
        )
        memory = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim='<img src=x onerror="memory">',
            evidence_refs=(memory_ref,),
        )
        verify_ref = EvidenceRef(
            new_id(IdKind.VERIFICATION),
            _hash("c"),
            EvidenceClass.VERIFICATION,
            1,
        )
        generation = MemoryGeneration.create(
            parent_generation_id=None,
            dream_run_id=run_id,
            input_manifest=manifest,
            accepted_entries=(memory,),
            deferred_candidate_ids=(candidate.candidate_id,),
            audit_verification_ref=verify_ref,
        )
        store.put_manifest(manifest)
        store.put_candidate(candidate)
        audit_path = store.put_audit(audit)
        store.put_memory_entry(memory)
        store.put_generation(generation)
        return (
            manifest.manifest_id,
            candidate.candidate_id,
            audit_path.stem,
            memory.entry_id,
            generation.generation_id,
        )

    def test_absent_dream_store_remains_absent_after_inspection(self) -> None:
        dream = self.runtime.state_dir / "dream"
        self.assertFalse(dream.exists())
        reader = DreamReadService(self.runtime)
        self.assertEqual(
            reader.counts(),
            {
                "manifests": 0,
                "candidates": 0,
                "audits": 0,
                "memory_entries": 0,
                "generations": 0,
            },
        )
        self.assertEqual(reader.manifests(), ())
        self.assertEqual(reader.candidates(), ())
        self.assertEqual(reader.audits(), ())
        self.assertEqual(reader.memory_entries(), ())
        self.assertEqual(reader.generations(), ())
        self.assertFalse(dream.exists())

    def test_canonical_dream_objects_are_validated_projected_and_non_mutating(self) -> None:
        manifest_id, candidate_id, audit_id, memory_id, generation_id = self._fixture()
        reader = DreamReadService(self.runtime)
        dream = self.runtime.state_dir / "dream"
        before = sorted(
            (str(path.relative_to(self.runtime.state_dir)), path.stat().st_mtime_ns)
            for path in dream.rglob("*")
        )
        self.assertEqual(
            reader.counts(),
            {
                "manifests": 1,
                "candidates": 1,
                "audits": 1,
                "memory_entries": 1,
                "generations": 1,
            },
        )
        manifest = reader.manifests()[0]
        candidate = reader.candidates()[0]
        audit = reader.audits()[0]
        memory = reader.memory_entries()[0]
        generation = reader.generations()[0]
        after = sorted(
            (str(path.relative_to(self.runtime.state_dir)), path.stat().st_mtime_ns)
            for path in dream.rglob("*")
        )
        self.assertEqual(before, after)
        self.assertEqual(manifest["manifest_id"], manifest_id)
        self.assertEqual(candidate["candidate_id"], candidate_id)
        self.assertEqual(audit["audit_id"], audit_id)
        self.assertEqual(memory["entry_id"], memory_id)
        self.assertEqual(generation["generation_id"], generation_id)
        self.assertFalse(manifest["evidence_refs_disclosed"])
        self.assertFalse(candidate["evidence_refs_disclosed"])
        self.assertFalse(candidate["automatic_promotion_authorized"])
        self.assertFalse(audit["finding_messages_disclosed"])
        self.assertFalse(audit["semantic_truth_verified_by_cockpit"])
        self.assertFalse(memory["evidence_refs_disclosed"])
        self.assertFalse(generation["entry_refs_disclosed"])
        self.assertFalse(generation["candidate_ids_disclosed"])
        self.assertFalse(generation["production_state_mutation_authorized"])

    def test_noncanonical_and_symlinked_dream_state_fail_closed(self) -> None:
        _, candidate_id, _, _, _ = self._fixture()
        candidate_path = (
            self.runtime.state_dir / "dream" / "candidates" / f"{candidate_id}.json"
        )
        candidate_path.write_bytes(candidate_path.read_bytes() + b" ")
        with self.assertRaisesRegex(DreamReadError, "not canonical"):
            DreamReadService(self.runtime).load_candidate(candidate_id)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("dream-read-symlink-test")
            outside = root / "outside"
            outside.mkdir()
            try:
                (runtime.state_dir / "dream").symlink_to(
                    outside, target_is_directory=True
                )
            except OSError as exc:
                self.skipTest(f"symlink capability unavailable: {exc}")
            with self.assertRaises(DreamReadError):
                DreamReadService(runtime).counts()

    def test_reader_source_has_no_creation_execution_or_promotion_surface(self) -> None:
        source = inspect.getsource(read_module)
        for forbidden in (
            "mkdir(",
            ".ensure(",
            "DreamCycleService",
            "ModelAdapter",
            "start_run(",
            "put_manifest(",
            "put_candidate(",
            "put_audit(",
            "put_memory_entry(",
            "put_generation(",
            "promote",
            "transition_task(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
