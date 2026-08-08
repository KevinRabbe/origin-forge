from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_generation import (
    DreamGenerationBuilder,
    DreamGenerationError,
    generation_audit_evidence,
)
from origin_forge.dream_models import (
    DreamCandidate,
    DreamCandidateType,
    DreamInputManifest,
    EvidenceClass,
    EvidenceRef,
    MemoryEntry,
    MemoryKind,
)
from origin_forge.dream_store import DreamStore
from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, TaskStatus


def sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def ref(
    ref_id: str,
    value: str,
    evidence_class: EvidenceClass = EvidenceClass.CANONICAL,
    revision: int | None = None,
) -> EvidenceRef:
    return EvidenceRef(ref_id, sha(value), evidence_class, revision)


class DreamGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-generation-test")
        goal = self.runtime.create_goal("Dream consolidation")
        flow = self.runtime.create_flow(goal)
        flow_rev = self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.assertEqual(flow_rev, 1)
        task = self.runtime.create_task(flow, "Consolidate verified experience")
        task_rev = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=task_rev)
        self.run_id = self.runtime.start_run(task, role="DREAM_ANALYZER")
        self.store = DreamStore(self.runtime)
        self.builder = DreamGenerationBuilder(self.runtime, self.store)
        self.decision_ref = ref(new_id(IdKind.DECISION), "decision", revision=1)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _manifest(self, *, parent=None, evidence_refs=None):
        manifest = DreamInputManifest.create(
            parent_memory_generation_id=parent,
            decision_refs=tuple(evidence_refs or (self.decision_ref,)),
        )
        self.store.put_manifest(manifest)
        return manifest

    def _entry(self, claim: str, *, evidence=None, supersedes=()):
        entry = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim=claim,
            evidence_refs=(evidence or self.decision_ref,),
            supersedes=supersedes,
        )
        self.store.put_memory_entry(entry)
        return entry

    def _candidate(self, manifest, *, target=None):
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.SKILL,
            summary="Candidate Skill improvement.",
            proposed_action="Send to governed paired Skill evaluation.",
            evidence_refs=(self.decision_ref,),
            target_memory_generation_id=target,
        )
        self.store.put_candidate(candidate)
        return candidate

    def _audit(
        self,
        manifest,
        *,
        entries=(),
        superseded=(),
        candidates=(),
        status="PASS",
        verification_type="dream-audit",
        evidence_override=None,
        run_id=None,
    ):
        evidence = generation_audit_evidence(
            manifest,
            accepted_entries=entries,
            superseded_entry_ids=superseded,
            deferred_candidates=candidates,
        )
        if evidence_override is not None:
            evidence = evidence_override
        target_run = run_id or self.run_id
        return self.runtime.record_verification(
            "RUN",
            target_run,
            verification_type=verification_type,
            verifier="dream-generation-test",
            status=status,
            evidence=evidence,
            run_id=target_run,
        )

    def test_root_generation_requires_exact_bound_audit_and_persists(self) -> None:
        manifest = self._manifest()
        entry = self._entry("Origin Forge owns verified state.")
        candidate = self._candidate(manifest)
        verification_id = self._audit(
            manifest,
            entries=(entry,),
            candidates=(candidate,),
        )

        generation = self.builder.build(
            parent_generation_id=None,
            dream_run_id=self.run_id,
            manifest_id=manifest.manifest_id,
            accepted_entry_ids=(entry.entry_id,),
            deferred_candidate_ids=(candidate.candidate_id,),
            audit_verification_id=verification_id,
        )

        self.assertEqual(self.store.load_generation(generation.generation_id), generation)
        self.assertEqual(generation.input_manifest_hash, manifest.content_hash)
        self.assertEqual(generation.accepted_entry_refs[0].content_hash, entry.content_hash)
        self.assertEqual(generation.deferred_candidate_ids, (candidate.candidate_id,))
        self.assertEqual(generation.audit_verification_ref.ref_id, verification_id)
        self.assertEqual(generation.audit_verification_ref.evidence_class, EvidenceClass.VERIFICATION)
        active = self.builder.active_memory(generation.generation_id)
        self.assertEqual([item.ref_id for item in active.entries], [entry.entry_id])

    def test_generic_pass_verification_cannot_authorize_generation(self) -> None:
        manifest = self._manifest()
        verification_id = self._audit(manifest, verification_type="unit")
        with self.assertRaisesRegex(DreamGenerationError, "exactly 'dream-audit'"):
            self.builder.build(
                parent_generation_id=None,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                audit_verification_id=verification_id,
            )

    def test_failed_audit_cannot_authorize_generation(self) -> None:
        manifest = self._manifest()
        verification_id = self._audit(manifest, status="FAIL")
        with self.assertRaisesRegex(DreamGenerationError, "PASS status"):
            self.builder.build(
                parent_generation_id=None,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                audit_verification_id=verification_id,
            )

    def test_audit_evidence_must_bind_exact_generation_inputs(self) -> None:
        manifest = self._manifest()
        entry = self._entry("Bound memory.")
        verification_id = self._audit(manifest, entries=())
        with self.assertRaisesRegex(DreamGenerationError, "does not bind the exact generation inputs"):
            self.builder.build(
                parent_generation_id=None,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                accepted_entry_ids=(entry.entry_id,),
                audit_verification_id=verification_id,
            )

    def test_audit_must_target_exact_dream_run(self) -> None:
        goal = self.runtime.create_goal("Other")
        flow = self.runtime.create_flow(goal)
        flow_rev = self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.assertEqual(flow_rev, 1)
        task = self.runtime.create_task(flow, "Other task")
        task_rev = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=task_rev)
        other_run = self.runtime.start_run(task, role="DREAM_ANALYZER")

        manifest = self._manifest()
        verification_id = self._audit(manifest, run_id=other_run)
        with self.assertRaisesRegex(DreamGenerationError, "exact Dream RUN"):
            self.builder.build(
                parent_generation_id=None,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                audit_verification_id=verification_id,
            )

    def test_accepted_memory_may_not_cite_evidence_outside_frozen_manifest(self) -> None:
        manifest = self._manifest()
        outside = ref(new_id(IdKind.DECISION), "outside", revision=1)
        entry = self._entry("Unsupported memory.", evidence=outside)
        verification_id = self._audit(manifest, entries=(entry,))
        with self.assertRaisesRegex(DreamGenerationError, "evidence outside frozen manifest"):
            self.builder.build(
                parent_generation_id=None,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                accepted_entry_ids=(entry.entry_id,),
                audit_verification_id=verification_id,
            )

    def test_parent_manifest_must_match_requested_parent_generation(self) -> None:
        parent = new_id(IdKind.MEMORY_GENERATION)
        manifest = self._manifest(parent=parent)
        verification_id = self._audit(manifest)
        with self.assertRaisesRegex(DreamGenerationError, "parent generation does not match"):
            self.builder.build(
                parent_generation_id=None,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                audit_verification_id=verification_id,
            )

    def test_child_generation_can_supersede_active_parent_memory(self) -> None:
        root_manifest = self._manifest()
        old = self._entry("Config version is four.")
        root_audit = self._audit(root_manifest, entries=(old,))
        root_generation = self.builder.build(
            parent_generation_id=None,
            dream_run_id=self.run_id,
            manifest_id=root_manifest.manifest_id,
            accepted_entry_ids=(old.entry_id,),
            audit_verification_id=root_audit,
        )

        child_manifest = self._manifest(parent=root_generation.generation_id)
        replacement = self._entry(
            "Config version is five.",
            supersedes=(old.entry_id,),
        )
        child_audit = self._audit(
            child_manifest,
            entries=(replacement,),
            superseded=(old.entry_id,),
        )
        child = self.builder.build(
            parent_generation_id=root_generation.generation_id,
            dream_run_id=self.run_id,
            manifest_id=child_manifest.manifest_id,
            accepted_entry_ids=(replacement.entry_id,),
            superseded_entry_ids=(old.entry_id,),
            audit_verification_id=child_audit,
        )
        active = self.builder.active_memory(child.generation_id)
        self.assertEqual([item.ref_id for item in active.entries], [replacement.entry_id])

    def test_cannot_supersede_memory_that_is_not_active(self) -> None:
        manifest = self._manifest()
        missing = new_id(IdKind.MEMORY_ENTRY)
        verification_id = self._audit(manifest, superseded=(missing,))
        with self.assertRaisesRegex(DreamGenerationError, "cannot supersede inactive"):
            self.builder.build(
                parent_generation_id=None,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                superseded_entry_ids=(missing,),
                audit_verification_id=verification_id,
            )

    def test_duplicate_semantic_memory_cannot_be_added_to_active_generation(self) -> None:
        root_manifest = self._manifest()
        first = self._entry("Stable fact.")
        root_audit = self._audit(root_manifest, entries=(first,))
        root_generation = self.builder.build(
            parent_generation_id=None,
            dream_run_id=self.run_id,
            manifest_id=root_manifest.manifest_id,
            accepted_entry_ids=(first.entry_id,),
            audit_verification_id=root_audit,
        )

        child_manifest = self._manifest(parent=root_generation.generation_id)
        duplicate = self._entry("Stable fact.")
        self.assertEqual(first.content_hash, duplicate.content_hash)
        child_audit = self._audit(child_manifest, entries=(duplicate,))
        with self.assertRaisesRegex(DreamGenerationError, "duplicates active semantic memory"):
            self.builder.build(
                parent_generation_id=root_generation.generation_id,
                dream_run_id=self.run_id,
                manifest_id=child_manifest.manifest_id,
                accepted_entry_ids=(duplicate.entry_id,),
                audit_verification_id=child_audit,
            )

    def test_declared_supersession_must_be_recorded_by_generation(self) -> None:
        root_manifest = self._manifest()
        old = self._entry("Old fact.")
        root_audit = self._audit(root_manifest, entries=(old,))
        root_generation = self.builder.build(
            parent_generation_id=None,
            dream_run_id=self.run_id,
            manifest_id=root_manifest.manifest_id,
            accepted_entry_ids=(old.entry_id,),
            audit_verification_id=root_audit,
        )
        child_manifest = self._manifest(parent=root_generation.generation_id)
        replacement = self._entry("New fact.", supersedes=(old.entry_id,))
        child_audit = self._audit(child_manifest, entries=(replacement,))
        with self.assertRaisesRegex(DreamGenerationError, "declares supersession not recorded"):
            self.builder.build(
                parent_generation_id=root_generation.generation_id,
                dream_run_id=self.run_id,
                manifest_id=child_manifest.manifest_id,
                accepted_entry_ids=(replacement.entry_id,),
                audit_verification_id=child_audit,
            )

    def test_deferred_candidate_must_match_frozen_parent_and_manifest_evidence(self) -> None:
        root_manifest = self._manifest()
        root_audit = self._audit(root_manifest)
        parent = self.builder.build(
            parent_generation_id=None,
            dream_run_id=self.run_id,
            manifest_id=root_manifest.manifest_id,
            audit_verification_id=root_audit,
        )

        manifest = self._manifest(parent=parent.generation_id)
        wrong_target = new_id(IdKind.MEMORY_GENERATION)
        candidate = self._candidate(manifest, target=wrong_target)
        verification_id = self._audit(manifest, candidates=(candidate,))
        with self.assertRaisesRegex(DreamGenerationError, "targets a different memory generation"):
            self.builder.build(
                parent_generation_id=parent.generation_id,
                dream_run_id=self.run_id,
                manifest_id=manifest.manifest_id,
                deferred_candidate_ids=(candidate.candidate_id,),
                audit_verification_id=verification_id,
            )

    def test_generation_audit_evidence_is_order_normalized(self) -> None:
        manifest = self._manifest()
        first = self._entry("First.")
        second = self._entry("Second.")
        a = generation_audit_evidence(
            manifest,
            accepted_entries=(second, first),
        )
        b = generation_audit_evidence(
            manifest,
            accepted_entries=(first, second),
        )
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
