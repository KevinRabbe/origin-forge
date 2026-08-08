from __future__ import annotations

import unittest

from origin_forge.dream_models import (
    DreamBudget,
    DreamCandidate,
    DreamCandidateType,
    DreamDownstreamGate,
    DreamInputManifest,
    DreamModelError,
    EvidenceClass,
    EvidenceRef,
    MemoryEntry,
    MemoryGeneration,
    MemoryKind,
)
from origin_forge.ids import IdKind, new_id, validate_id


def sha(value: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def ref(
    ref_id: str,
    value: str,
    evidence_class: EvidenceClass = EvidenceClass.CANONICAL,
    revision: int | None = None,
) -> EvidenceRef:
    return EvidenceRef(ref_id, sha(value), evidence_class, revision)


class DreamModelTests(unittest.TestCase):
    def test_phase15_id_kinds_use_existing_opaque_id_contract(self) -> None:
        for kind in (
            IdKind.DREAM_MANIFEST,
            IdKind.DREAM_CANDIDATE,
            IdKind.MEMORY_ENTRY,
            IdKind.MEMORY_GENERATION,
        ):
            value = new_id(kind)
            self.assertTrue(validate_id(value, kind))

    def test_evidence_ref_requires_exact_hash_and_revision(self) -> None:
        item = ref(new_id(IdKind.RUN), "run", EvidenceClass.TRAJECTORY, 3)
        self.assertEqual(item.revision, 3)
        self.assertEqual(item.content_hash, sha("run"))
        with self.assertRaisesRegex(DreamModelError, "sha256"):
            EvidenceRef("RUN-x", "not-a-hash", EvidenceClass.TRAJECTORY)
        with self.assertRaisesRegex(DreamModelError, "revision"):
            EvidenceRef(new_id(IdKind.RUN), sha("run"), EvidenceClass.TRAJECTORY, -1)

    def test_manifest_is_order_normalized_and_semantically_content_addressed(self) -> None:
        run_a = ref(new_id(IdKind.RUN), "run-a", EvidenceClass.TRAJECTORY, 1)
        run_b = ref(new_id(IdKind.RUN), "run-b", EvidenceClass.TRAJECTORY, 2)
        task = ref(new_id(IdKind.TASK), "task", EvidenceClass.CANONICAL, 4)

        first = DreamInputManifest.create(
            run_refs=(run_b, run_a),
            task_refs=(task,),
            window_start="2026-08-07T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
        )
        second = DreamInputManifest.create(
            run_refs=(run_a, run_b),
            task_refs=(task,),
            window_start="2026-08-07T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
        )

        self.assertNotEqual(first.manifest_id, second.manifest_id)
        self.assertEqual(first.run_refs, second.run_refs)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertTrue(first.content_hash.startswith("sha256:"))

    def test_manifest_budget_and_time_window_fail_closed(self) -> None:
        runs = tuple(
            ref(new_id(IdKind.RUN), f"run-{index}", EvidenceClass.TRAJECTORY)
            for index in range(3)
        )
        with self.assertRaisesRegex(DreamModelError, "run_refs exceeds Dream budget"):
            DreamInputManifest.create(
                run_refs=runs,
                budget=DreamBudget(max_runs=2),
            )
        with self.assertRaisesRegex(DreamModelError, "both start and end"):
            DreamInputManifest.create(window_start="2026-08-07T00:00:00Z")
        with self.assertRaisesRegex(DreamModelError, "must not be after"):
            DreamInputManifest.create(
                window_start="2026-08-08T00:00:00Z",
                window_end="2026-08-07T00:00:00Z",
            )
        with self.assertRaisesRegex(DreamModelError, "include a timezone"):
            DreamInputManifest.create(
                window_start="2026-08-07T00:00:00",
                window_end="2026-08-08T00:00:00",
            )

    def test_budget_has_conservative_defaults_and_hard_ceilings(self) -> None:
        budget = DreamBudget()
        self.assertEqual(budget.max_runs, 100)
        self.assertEqual(budget.max_model_calls, 4)
        self.assertEqual(budget.max_candidates, 128)
        with self.assertRaisesRegex(DreamModelError, "max_runs"):
            DreamBudget(max_runs=1001)
        with self.assertRaisesRegex(DreamModelError, "max_model_calls"):
            DreamBudget(max_model_calls=33)
        with self.assertRaisesRegex(DreamModelError, "max_retries"):
            DreamBudget(max_retries=9)

    def test_memory_entry_hash_ignores_opaque_id_and_normalizes_evidence_order(self) -> None:
        decision = ref(new_id(IdKind.DECISION), "decision", EvidenceClass.CANONICAL, 2)
        verification = ref(
            new_id(IdKind.VERIFICATION),
            "verify",
            EvidenceClass.VERIFICATION,
            1,
        )
        first = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="All configured language servers run through sandboxed Podman.",
            evidence_refs=(verification, decision),
            valid_from="2026-08-08T00:00:00Z",
        )
        second = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="All configured language servers run through sandboxed Podman.",
            evidence_refs=(decision, verification),
            valid_from="2026-08-08T00:00:00Z",
        )
        self.assertNotEqual(first.entry_id, second.entry_id)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.evidence_refs, second.evidence_refs)
        self.assertEqual(first.as_evidence_ref().evidence_class, EvidenceClass.DERIVED_MEMORY)

    def test_memory_entry_requires_evidence_and_cannot_self_supersede(self) -> None:
        with self.assertRaisesRegex(DreamModelError, "may not be empty"):
            MemoryEntry.create(
                kind=MemoryKind.PROJECT_CONVENTION,
                claim="Use deterministic selection.",
                evidence_refs=(),
            )
        entry_id = new_id(IdKind.MEMORY_ENTRY)
        evidence = ref(new_id(IdKind.DECISION), "decision")
        with self.assertRaisesRegex(DreamModelError, "cannot supersede itself"):
            MemoryEntry(
                entry_id=entry_id,
                kind=MemoryKind.PROJECT_CONVENTION,
                claim="Use deterministic selection.",
                evidence_refs=(evidence,),
                supersedes=(entry_id,),
            )

    def test_candidate_type_owns_non_bypassable_downstream_gate(self) -> None:
        evidence = ref(new_id(IdKind.RUN), "run", EvidenceClass.TRAJECTORY)
        expected = {
            DreamCandidateType.MEMORY: DreamDownstreamGate.DREAM_AUDIT,
            DreamCandidateType.SKILL: DreamDownstreamGate.SKILL_EVALUATION,
            DreamCandidateType.ROUTING: DreamDownstreamGate.ROUTING_BENCHMARK,
            DreamCandidateType.CONTEXT: DreamDownstreamGate.CONTEXT_BENCHMARK,
            DreamCandidateType.PROCESS: DreamDownstreamGate.ENGINEERING_REVIEW,
            DreamCandidateType.DATA_QUALITY: DreamDownstreamGate.DETERMINISTIC_VALIDATION,
        }
        for candidate_type, gate in expected.items():
            candidate = DreamCandidate.create(
                candidate_type=candidate_type,
                summary=f"candidate {candidate_type.value}",
                proposed_action="propose only",
                evidence_refs=(evidence,),
            )
            self.assertEqual(candidate.required_gate, gate)
            self.assertEqual(candidate.to_dict()["required_gate"], gate.value)

    def test_candidate_hash_is_semantic_and_requires_evidence(self) -> None:
        run = ref(new_id(IdKind.RUN), "run", EvidenceClass.TRAJECTORY)
        first = DreamCandidate.create(
            candidate_type=DreamCandidateType.PROCESS,
            summary="Inspect failing tests before implementation edits.",
            proposed_action="Benchmark a debugging Skill change.",
            evidence_refs=(run,),
        )
        second = DreamCandidate.create(
            candidate_type=DreamCandidateType.PROCESS,
            summary="Inspect failing tests before implementation edits.",
            proposed_action="Benchmark a debugging Skill change.",
            evidence_refs=(run,),
        )
        self.assertNotEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(first.content_hash, second.content_hash)
        with self.assertRaisesRegex(DreamModelError, "may not be empty"):
            DreamCandidate.create(
                candidate_type=DreamCandidateType.PROCESS,
                summary="unsupported",
                proposed_action="do something",
                evidence_refs=(),
            )

    def test_memory_generation_requires_audit_verification_and_exact_manifest_hash(self) -> None:
        run_id = new_id(IdKind.RUN)
        manifest = DreamInputManifest.create(
            run_refs=(ref(run_id, "run", EvidenceClass.TRAJECTORY),)
        )
        memory = MemoryEntry.create(
            kind=MemoryKind.PROCEDURAL_OBSERVATION,
            claim="Semantic context helped this task class.",
            evidence_refs=(ref(run_id, "run", EvidenceClass.TRAJECTORY),),
        )
        audit = ref(
            new_id(IdKind.VERIFICATION),
            "audit",
            EvidenceClass.VERIFICATION,
        )
        generation = MemoryGeneration.create(
            parent_generation_id=None,
            dream_run_id=run_id,
            input_manifest=manifest,
            accepted_entries=(memory,),
            audit_verification_ref=audit,
        )
        self.assertTrue(validate_id(generation.generation_id, IdKind.MEMORY_GENERATION))
        self.assertEqual(generation.input_manifest_hash, manifest.content_hash)
        self.assertEqual(generation.accepted_entry_refs[0].ref_id, memory.entry_id)
        self.assertEqual(generation.audit_verification_ref, audit)

        wrong_class = ref(
            new_id(IdKind.VERIFICATION),
            "audit-2",
            EvidenceClass.CANONICAL,
        )
        with self.assertRaisesRegex(DreamModelError, "VERIFICATION evidence class"):
            MemoryGeneration.create(
                parent_generation_id=None,
                dream_run_id=run_id,
                input_manifest=manifest,
                accepted_entries=(memory,),
                audit_verification_ref=wrong_class,
            )

    def test_generation_hash_changes_with_parent_and_deferral_lineage(self) -> None:
        run_id = new_id(IdKind.RUN)
        manifest = DreamInputManifest.create()
        audit = ref(
            new_id(IdKind.VERIFICATION),
            "audit",
            EvidenceClass.VERIFICATION,
        )
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.SKILL,
            summary="candidate skill",
            proposed_action="benchmark candidate",
            evidence_refs=(ref(run_id, "run", EvidenceClass.TRAJECTORY),),
        )
        first = MemoryGeneration.create(
            parent_generation_id=None,
            dream_run_id=run_id,
            input_manifest=manifest,
            accepted_entries=(),
            audit_verification_ref=audit,
        )
        second = MemoryGeneration.create(
            parent_generation_id=first.generation_id,
            dream_run_id=run_id,
            input_manifest=manifest,
            accepted_entries=(),
            deferred_candidate_ids=(candidate.candidate_id,),
            audit_verification_ref=audit,
        )
        self.assertNotEqual(first.content_hash, second.content_hash)
        self.assertEqual(second.parent_generation_id, first.generation_id)
        self.assertEqual(second.deferred_candidate_ids, (candidate.candidate_id,))

    def test_generation_cannot_accept_and_supersede_same_entry(self) -> None:
        run_id = new_id(IdKind.RUN)
        manifest = DreamInputManifest.create()
        memory = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Config version is five.",
            evidence_refs=(ref(new_id(IdKind.DECISION), "decision"),),
        )
        audit = ref(
            new_id(IdKind.VERIFICATION),
            "audit",
            EvidenceClass.VERIFICATION,
        )
        with self.assertRaisesRegex(DreamModelError, "both accept and supersede"):
            MemoryGeneration.create(
                parent_generation_id=None,
                dream_run_id=run_id,
                input_manifest=manifest,
                accepted_entries=(memory,),
                superseded_entry_ids=(memory.entry_id,),
                audit_verification_ref=audit,
            )


if __name__ == "__main__":
    unittest.main()
