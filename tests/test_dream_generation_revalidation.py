from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_generation import (
    DreamGenerationBuilder,
    DreamGenerationError,
    generation_audit_evidence,
)
from origin_forge.dream_models import DreamInputManifest, EvidenceClass, EvidenceRef, MemoryEntry, MemoryKind
from origin_forge.dream_store import DreamStore
from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


def hash64() -> str:
    return "sha256:" + "1" * 64


class DreamGenerationRevalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-generation-revalidation")
        self.store = DreamStore(self.runtime)
        self.builder = DreamGenerationBuilder(self.runtime, self.store)

        goal = self.runtime.create_goal("Dream")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Dream run")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        self.run_id = self.runtime.start_run(task, role="DREAM_ANALYZER")
        self.runtime.finish_run(self.run_id, RunStatus.SUCCEEDED)
        self.task = task

        decision = EvidenceRef(
            new_id(IdKind.DECISION),
            hash64(),
            EvidenceClass.CANONICAL,
        )
        self.manifest = DreamInputManifest.create(decision_refs=(decision,))
        self.store.put_manifest(self.manifest)
        self.entry = MemoryEntry.create(
            kind=MemoryKind.ARCHITECTURAL_FACT,
            claim="Verified derived fact.",
            evidence_refs=(decision,),
        )
        self.store.put_memory_entry(self.entry)
        evidence = generation_audit_evidence(
            self.manifest,
            accepted_entries=(self.entry,),
        )
        self.verification_id = self.runtime.record_verification(
            "RUN",
            self.run_id,
            verification_type="dream-audit",
            verifier="revalidation-test",
            status="PASS",
            evidence=evidence,
            metrics={"checked": 1},
            run_id=self.run_id,
        )
        self.generation = self.builder.build(
            parent_generation_id=None,
            dream_run_id=self.run_id,
            manifest_id=self.manifest.manifest_id,
            accepted_entry_ids=(self.entry.entry_id,),
            audit_verification_id=self.verification_id,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_untampered_generation_reconstructs_active_memory(self) -> None:
        active = self.builder.active_memory(self.generation.generation_id)
        self.assertEqual([item.ref_id for item in active.entries], [self.entry.entry_id])

    def test_later_audit_status_tampering_invalidates_active_memory(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE verifications SET status = 'FAIL' WHERE id = ?",
                (self.verification_id,),
            )
        with self.assertRaisesRegex(DreamGenerationError, "PASS status"):
            self.builder.active_memory(self.generation.generation_id)

    def test_later_audit_evidence_tampering_invalidates_active_memory(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE verifications SET evidence_json = ? WHERE id = ?",
                ('{"tampered":true}', self.verification_id),
            )
        with self.assertRaisesRegex(DreamGenerationError, "does not bind the exact generation inputs"):
            self.builder.active_memory(self.generation.generation_id)

    def test_later_audit_metrics_tampering_changes_pinned_verification_hash(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE verifications SET metrics_json = ? WHERE id = ?",
                ('{"checked":2}', self.verification_id),
            )
        with self.assertRaisesRegex(DreamGenerationError, "changed after generation creation"):
            self.builder.active_memory(self.generation.generation_id)

    def test_missing_audit_verification_invalidates_active_memory(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute("DELETE FROM verifications WHERE id = ?", (self.verification_id,))
        with self.assertRaisesRegex(DreamGenerationError, "does not exist"):
            self.builder.active_memory(self.generation.generation_id)


if __name__ == "__main__":
    unittest.main()
