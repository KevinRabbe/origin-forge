from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_evidence_resolver import (
    DreamEvidenceResolutionError,
    RuntimeDreamEvidenceResolver,
)
from origin_forge.dream_models import EvidenceClass, EvidenceRef
from origin_forge.ids import IdKind, new_id
from origin_forge.records import create_decision
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class DreamEvidenceResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-resolver-test")
        self.resolver = RuntimeDreamEvidenceResolver(self.runtime)

        self.goal = self.runtime.create_goal("Goal")
        self.flow = self.runtime.create_flow(self.goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "Task")
        revision = self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(self.task, TaskStatus.RUNNING, expected_revision=revision)
        self.run = self.runtime.start_run(self.task, role="EXECUTOR")
        self.runtime.finish_run(self.run, RunStatus.FAILED, failure_reason="expected")
        task_row = self.runtime.get_task(self.task)
        self.runtime.transition_task(
            self.task,
            TaskStatus.FAILED,
            expected_revision=int(task_row["revision"]),
        )
        self.decision = create_decision(
            self.runtime.store,
            self.runtime.project_id(),
            title="Decision",
            decision="Use bounded evidence",
            rationale="Determinism",
            goal_id=self.goal,
            task_id=self.task,
        )
        self.verification = self.runtime.record_verification(
            "RUN",
            self.run,
            verification_type="evidence",
            verifier="resolver-test",
            status="FAIL",
            evidence={"reason": "expected"},
            run_id=self.run,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _placeholder(self, ref_id: str, evidence_class: EvidenceClass) -> EvidenceRef:
        return EvidenceRef(
            ref_id,
            "sha256:" + "0" * 64,
            evidence_class,
        )

    def test_resolves_current_run_task_decision_and_verification_records(self) -> None:
        result = self.resolver.resolve(
            (
                self._placeholder(self.run, EvidenceClass.TRAJECTORY),
                self._placeholder(self.task, EvidenceClass.CANONICAL),
                self._placeholder(self.decision, EvidenceClass.CANONICAL),
                self._placeholder(self.verification, EvidenceClass.VERIFICATION),
            )
        )
        self.assertEqual(result.missing_ref_ids, ())
        self.assertEqual(
            {item.ref.ref_id for item in result.records},
            {self.run, self.task, self.decision, self.verification},
        )
        by_id = {item.ref.ref_id: item for item in result.records}
        self.assertEqual(by_id[self.run].record_type, "RUN")
        self.assertEqual(by_id[self.run].ref.evidence_class, EvidenceClass.TRAJECTORY)
        self.assertEqual(by_id[self.task].record_type, "TASK")
        self.assertEqual(by_id[self.task].ref.revision, self.runtime.get_task(self.task)["revision"])
        self.assertEqual(by_id[self.decision].record_type, "DECISION")
        self.assertEqual(by_id[self.verification].record_type, "VERIFICATION")

    def test_missing_ref_is_reported_without_inventing_record(self) -> None:
        missing = new_id(IdKind.DECISION)
        result = self.resolver.resolve(
            (self._placeholder(missing, EvidenceClass.CANONICAL),)
        )
        self.assertEqual(result.records, ())
        self.assertEqual(result.missing_ref_ids, (missing,))

    def test_explicit_decision_supersession_marks_old_ref(self) -> None:
        replacement = create_decision(
            self.runtime.store,
            self.runtime.project_id(),
            title="Replacement",
            decision="Use new rule",
            rationale="Updated evidence",
            goal_id=self.goal,
            task_id=self.task,
            supersedes_decision_id=self.decision,
        )
        self.assertTrue(replacement.startswith("DEC-"))
        result = self.resolver.resolve(
            (self._placeholder(self.decision, EvidenceClass.CANONICAL),)
        )
        self.assertEqual(result.superseded_ref_ids, (self.decision,))
        self.assertEqual(result.records[0].ref.ref_id, self.decision)

    def test_resolved_task_ref_tracks_current_revision_and_hash(self) -> None:
        current = self.resolver.resolve(
            (self._placeholder(self.task, EvidenceClass.CANONICAL),)
        ).records[0].ref
        self.assertEqual(current.revision, self.runtime.get_task(self.task)["revision"])
        self.assertNotEqual(current.content_hash, "sha256:" + "0" * 64)

    def test_duplicate_requested_ref_ids_fail_closed(self) -> None:
        item = self._placeholder(self.decision, EvidenceClass.CANONICAL)
        with self.assertRaisesRegex(DreamEvidenceResolutionError, "unique ref IDs"):
            self.resolver.resolve((item, item))

    def test_unsupported_evidence_kind_is_rejected(self) -> None:
        goal_ref = self._placeholder(self.goal, EvidenceClass.CANONICAL)
        with self.assertRaisesRegex(DreamEvidenceResolutionError, "unsupported durable evidence ID"):
            self.resolver.resolve((goal_ref,))


if __name__ == "__main__":
    unittest.main()
