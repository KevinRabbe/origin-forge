from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_evidence import (
    DreamEvidenceError,
    DreamEvidenceRecord,
    RuntimeDreamEvidenceCollector,
    canonical_verification_record,
    verification_evidence_ref,
)
from origin_forge.dream_models import DreamBudget, EvidenceClass, EvidenceRef
from origin_forge.ids import IdKind, new_id
from origin_forge.records import create_decision
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class DreamEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dream-evidence-test")
        self.collector = RuntimeDreamEvidenceCollector(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _running_task(self, objective="Do verified work"):
        goal = self.runtime.create_goal("Goal")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(
            flow,
            objective,
            acceptance_criteria=("verification passes",),
            required_capabilities=("code",),
            budget={"attempts": 2},
        )
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        return goal, flow, task

    def _complete_successful_task_with_failed_attempt(self):
        goal, flow, task = self._running_task()
        first = self.runtime.start_run(task, role="EXECUTOR", model_profile="small")
        self.runtime.finish_run(
            first,
            RunStatus.FAILED,
            failure_reason="tests failed",
            input_token_count=100,
            output_token_count=20,
            resource_metrics={"duration_ms": 1000},
        )
        second = self.runtime.start_run(task, role="EXECUTOR", model_profile="strong")
        run_verification = self.runtime.record_verification(
            "RUN",
            second,
            verification_type="sandbox",
            verifier="tests",
            status="PASS",
            evidence={"command": "python -m unittest"},
            metrics={"duration_ms": 250},
            run_id=second,
        )
        self.runtime.finish_run(
            second,
            RunStatus.SUCCEEDED,
            input_token_count=140,
            output_token_count=30,
            resource_metrics={"duration_ms": 1300},
        )
        self.runtime.record_verification(
            "TASK",
            task,
            verification_type="acceptance",
            verifier="tests",
            status="PASS",
            evidence={"sandbox_run": second},
            run_id=second,
        )
        task_row = self.runtime.get_task(task)
        self.runtime.transition_task(
            task,
            TaskStatus.SUCCEEDED,
            expected_revision=int(task_row["revision"]),
        )
        decision = create_decision(
            self.runtime.store,
            self.runtime.project_id(),
            title="Use bounded retry",
            decision="Escalate only after verified failure",
            rationale="Avoid hidden retry loops",
            goal_id=goal,
            task_id=task,
        )
        return task, first, second, decision, run_verification

    def test_collects_failed_and_successful_runs_from_same_completed_task(self) -> None:
        task, first, second, decision, run_verification = (
            self._complete_successful_task_with_failed_attempt()
        )
        bundle = self.collector.collect((second, first))

        self.assertEqual(len(bundle.manifest.run_refs), 2)
        self.assertEqual(len(bundle.manifest.task_refs), 1)
        self.assertEqual(len(bundle.manifest.decision_refs), 1)
        self.assertGreaterEqual(len(bundle.manifest.verification_refs), 2)
        self.assertIn(first, [item.ref_id for item in bundle.manifest.run_refs])
        self.assertIn(second, [item.ref_id for item in bundle.manifest.run_refs])
        self.assertEqual(bundle.manifest.task_refs[0].ref_id, task)
        self.assertEqual(bundle.manifest.decision_refs[0].ref_id, decision)
        self.assertIn(
            run_verification,
            [item.ref_id for item in bundle.manifest.verification_refs],
        )

        failed_payload = bundle.record(first).payload
        successful_payload = bundle.record(second).payload
        self.assertEqual(failed_payload["status"], RunStatus.FAILED.value)
        self.assertEqual(failed_payload["failure_reason"], "tests failed")
        self.assertEqual(successful_payload["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(successful_payload["input_token_count"], 140)
        self.assertGreater(bundle.total_evidence_bytes, 0)

    def test_repeated_collection_is_semantically_deterministic(self) -> None:
        _, first, second, _, _ = self._complete_successful_task_with_failed_attempt()
        a = self.collector.collect((first, second))
        b = self.collector.collect((second, first))
        self.assertNotEqual(a.manifest.manifest_id, b.manifest.manifest_id)
        self.assertEqual(a.manifest.content_hash, b.manifest.content_hash)
        self.assertEqual(
            [(item.record_type, item.ref, item.payload) for item in a.records],
            [(item.record_type, item.ref, item.payload) for item in b.records],
        )
        self.assertEqual(a.total_evidence_bytes, b.total_evidence_bytes)

    def test_active_run_is_rejected(self) -> None:
        _, _, task = self._running_task()
        run = self.runtime.start_run(task, role="EXECUTOR")
        with self.assertRaisesRegex(DreamEvidenceError, "RUN is still active"):
            self.collector.collect((run,))

    def test_terminal_run_on_nonterminal_task_is_rejected(self) -> None:
        _, _, task = self._running_task()
        run = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(run, RunStatus.FAILED, failure_reason="known failure")
        with self.assertRaisesRegex(DreamEvidenceError, "nonterminal Task"):
            self.collector.collect((run,))

    def test_terminal_failed_task_and_failed_run_are_valid_learning_evidence(self) -> None:
        _, _, task = self._running_task()
        run = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(run, RunStatus.FAILED, failure_reason="reproducible failure")
        task_row = self.runtime.get_task(task)
        self.runtime.transition_task(
            task,
            TaskStatus.FAILED,
            expected_revision=int(task_row["revision"]),
        )
        bundle = self.collector.collect((run,))
        self.assertEqual(bundle.manifest.run_refs[0].ref_id, run)
        self.assertEqual(bundle.record(run).payload["failure_reason"], "reproducible failure")

    def test_run_count_and_total_evidence_bytes_are_hard_bounded(self) -> None:
        _, first, second, _, _ = self._complete_successful_task_with_failed_attempt()
        with self.assertRaisesRegex(DreamEvidenceError, "run selection exceeds budget"):
            self.collector.collect((first, second), budget=DreamBudget(max_runs=1))
        with self.assertRaisesRegex(DreamEvidenceError, "exceeds byte budget"):
            self.collector.collect(
                (first,),
                budget=DreamBudget(max_total_evidence_bytes=1),
            )

    def test_duplicate_and_invalid_run_ids_fail_before_collection(self) -> None:
        _, first, _, _, _ = self._complete_successful_task_with_failed_attempt()
        with self.assertRaisesRegex(DreamEvidenceError, "duplicate IDs"):
            self.collector.collect((first, first))
        with self.assertRaisesRegex(DreamEvidenceError, "invalid RUN IDs"):
            self.collector.collect(("not-a-run",))

    def test_durable_json_corruption_fails_closed(self) -> None:
        _, first, _, _, _ = self._complete_successful_task_with_failed_attempt()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE runs SET resource_metrics_json = ? WHERE id = ?",
                ("{not-json", first),
            )
        with self.assertRaisesRegex(DreamEvidenceError, "contains invalid JSON"):
            self.collector.collect((first,))

    def test_verification_ref_hashes_exact_canonical_durable_record(self) -> None:
        _, _, second, _, verification_id = self._complete_successful_task_with_failed_attempt()
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (verification_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        row_dict = dict(row)
        ref_value = verification_evidence_ref(row_dict)
        record = canonical_verification_record(row_dict)
        self.assertEqual(ref_value.ref_id, verification_id)
        self.assertEqual(ref_value.evidence_class, EvidenceClass.VERIFICATION)
        DreamEvidenceRecord(ref_value, "VERIFICATION", record)

    def test_record_rejects_mismatched_hash(self) -> None:
        bad = EvidenceRef(
            new_id(IdKind.RUN),
            "sha256:" + "0" * 64,
            EvidenceClass.TRAJECTORY,
        )
        with self.assertRaisesRegex(DreamEvidenceError, "hash does not match"):
            DreamEvidenceRecord(bad, "RUN", {"id": bad.ref_id, "status": "FAILED"})


if __name__ == "__main__":
    unittest.main()
