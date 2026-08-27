from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_evidence_resolver import RuntimeDreamEvidenceResolver
from origin_forge.dream_generation import DreamGenerationBuilder, generation_audit_evidence
from origin_forge.dream_models import (
    DreamBudget,
    DreamCandidateType,
    DreamInputManifest,
    EvidenceClass,
    EvidenceRef,
    MemoryEntry,
    MemoryKind,
)
from origin_forge.dream_planner import DreamPlanningCoordinator
from origin_forge.dream_roles import DreamAuditStatus
from origin_forge.dream_store import DreamStore
from origin_forge.records import create_decision
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class DreamPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-planner-test")
        self.store = DreamStore(self.runtime)
        self.builder = DreamGenerationBuilder(self.runtime, self.store)
        self.resolver = RuntimeDreamEvidenceResolver(self.runtime)
        self.planner = DreamPlanningCoordinator(self.runtime, self.store)

        goal = self.runtime.create_goal("Completed work")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Perform bounded work")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        self.run = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(self.run, RunStatus.FAILED, failure_reason="known terminal evidence")
        task_row = self.runtime.get_task(task)
        self.runtime.transition_task(
            task,
            TaskStatus.FAILED,
            expected_revision=int(task_row["revision"]),
        )
        self.goal = goal
        self.task = task
        self.old_decision = create_decision(
            self.runtime.store,
            self.runtime.project_id(),
            title="Old decision",
            decision="Use config version four",
            rationale="Historical state",
            goal_id=goal,
            task_id=task,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _current_decision_ref(self, decision_id: str) -> EvidenceRef:
        placeholder = EvidenceRef(
            decision_id,
            "sha256:" + "0" * 64,
            EvidenceClass.CANONICAL,
        )
        result = self.resolver.resolve((placeholder,))
        self.assertEqual(len(result.records), 1)
        return result.records[0].ref

    def _root_generation_with_old_memory(self):
        old_ref = self._current_decision_ref(self.old_decision)
        manifest = DreamInputManifest.create(decision_refs=(old_ref,))
        self.store.put_manifest(manifest)
        entry = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Config version is four.",
            evidence_refs=(old_ref,),
        )
        self.store.put_memory_entry(entry)
        audit_evidence = generation_audit_evidence(
            manifest,
            accepted_entries=(entry,),
        )
        verification = self.runtime.record_verification(
            "RUN",
            self.run,
            verification_type="dream-audit",
            verifier="dream-planner-test",
            status="PASS",
            evidence=audit_evidence,
            run_id=self.run,
        )
        generation = self.builder.build(
            parent_generation_id=None,
            dream_run_id=self.run,
            manifest_id=manifest.manifest_id,
            accepted_entry_ids=(entry.entry_id,),
            audit_verification_id=verification,
        )
        return generation, entry

    def test_plan_without_active_memory_persists_manifest_and_no_candidates(self) -> None:
        before_generations = self.store.list_generation_ids()
        result = self.planner.plan((self.run,))
        self.assertEqual(result.active_memory_entries, ())
        self.assertEqual(result.preprocess_report.findings, ())
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.audits, ())
        self.assertEqual(self.store.load_manifest(result.manifest.manifest_id), result.manifest)
        self.assertEqual(self.store.list_generation_ids(), before_generations)
        self.assertTrue(result.content_hash.startswith("sha256:"))

    def test_superseded_decision_emits_audited_data_quality_proposal_only(self) -> None:
        generation, entry = self._root_generation_with_old_memory()
        replacement = create_decision(
            self.runtime.store,
            self.runtime.project_id(),
            title="New decision",
            decision="Use config version five",
            rationale="Current verified architecture",
            goal_id=self.goal,
            task_id=self.task,
            supersedes_decision_id=self.old_decision,
        )
        self.assertTrue(replacement.startswith("DEC-"))
        before_generations = self.store.list_generation_ids()

        result = self.planner.plan(
            (self.run,),
            parent_generation_id=generation.generation_id,
        )

        self.assertEqual([item.entry_id for item in result.active_memory_entries], [entry.entry_id])
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        audit = result.audits[0]
        self.assertEqual(candidate.candidate_type, DreamCandidateType.DATA_QUALITY)
        self.assertIn("SOURCE_SUPERSEDED", candidate.summary)
        self.assertEqual(candidate.target_memory_generation_id, generation.generation_id)
        self.assertEqual(audit.status, DreamAuditStatus.STRUCTURALLY_VALID)
        self.assertFalse(audit.semantic_review_required)
        self.assertEqual(audit.candidate_id, candidate.candidate_id)
        self.assertIn(entry.entry_id, [item.ref_id for item in candidate.evidence_refs])
        self.assertIn(self.old_decision, [item.ref_id for item in candidate.evidence_refs])

        self.assertEqual(self.store.load_candidate(candidate.candidate_id), candidate)
        audit_id = self.store.audit_report_id(audit)
        self.assertEqual(self.store.load_audit(audit_id), audit)
        self.assertEqual(self.store.list_generation_ids(), before_generations)

    def test_repeated_plan_has_same_semantic_manifest_and_candidate_hashes(self) -> None:
        generation, _ = self._root_generation_with_old_memory()
        create_decision(
            self.runtime.store,
            self.runtime.project_id(),
            title="New decision",
            decision="Use config version five",
            rationale="Current verified architecture",
            goal_id=self.goal,
            task_id=self.task,
            supersedes_decision_id=self.old_decision,
        )
        first = self.planner.plan((self.run,), parent_generation_id=generation.generation_id)
        second = self.planner.plan((self.run,), parent_generation_id=generation.generation_id)
        self.assertNotEqual(first.manifest.manifest_id, second.manifest.manifest_id)
        self.assertEqual(first.manifest.content_hash, second.manifest.content_hash)
        self.assertEqual(
            [item.content_hash for item in first.candidates],
            [item.content_hash for item in second.candidates],
        )

    def test_plan_obeys_frozen_candidate_budget(self) -> None:
        generation, entry = self._root_generation_with_old_memory()
        # One supersession finding is still valid with a one-candidate budget.
        create_decision(
            self.runtime.store,
            self.runtime.project_id(),
            title="New decision",
            decision="Use config version five",
            rationale="Current verified architecture",
            goal_id=self.goal,
            task_id=self.task,
            supersedes_decision_id=self.old_decision,
        )
        result = self.planner.plan(
            (self.run,),
            parent_generation_id=generation.generation_id,
            budget=DreamBudget(max_candidates=1),
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.active_memory_entries[0].entry_id, entry.entry_id)

    def test_active_run_is_rejected_before_any_plan_persistence(self) -> None:
        goal = self.runtime.create_goal("Active")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Still active")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        active_run = self.runtime.start_run(task, role="EXECUTOR")
        before = self.store.list_manifest_ids()
        with self.assertRaisesRegex(RuntimeError, "RUN is still active"):
            self.planner.plan((active_run,))
        self.assertEqual(self.store.list_manifest_ids(), before)

    def test_planner_exposes_no_generation_promotion_or_project_mutation_operation(self) -> None:
        for forbidden in (
            "build_generation",
            "promote",
            "apply",
            "write_source",
            "change_policy",
            "merge",
        ):
            self.assertFalse(hasattr(self.planner, forbidden))


if __name__ == "__main__":
    unittest.main()
