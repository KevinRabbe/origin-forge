from __future__ import annotations

import inspect
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import origin_forge.conversation_processing as processing_module
from origin_forge.conversation_processing import (
    MAX_CONVERSATION_FAILURE_CODE_BYTES,
    ConversationProcessingConflict,
    ConversationProcessingError,
    ConversationProcessingFailed,
    ConversationReadOnlyInspection,
    claim_conversation_submission,
    fail_conversation_submission,
    process_read_only_submission,
)
from origin_forge.conversation_service import (
    ConversationActorType,
    ConversationSubmissionStatus,
    create_conversation_session,
    list_conversation_turns,
    read_conversation_session,
    read_conversation_submission,
    submit_human_turn,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class ConversationGateBProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("conversation-gate-b-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _accepted_submission(self, content: str = "What is the project status?"):
        session = create_conversation_session(self.runtime)
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            content,
            "client-gate-b",
            expected_revision=0,
        )
        return session, receipt

    def test_project_counts_inspection_commits_one_durable_forge_response(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "task")
        self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=1)
        self.runtime.start_run(task, role="PRODUCER")
        session, receipt = self._accepted_submission()

        result = process_read_only_submission(
            self.runtime,
            receipt.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )

        self.assertEqual(result.submission.status, ConversationSubmissionStatus.RESPONDED)
        self.assertEqual(result.submission.response_turn_id, result.response_turn.id)
        self.assertEqual(result.response_turn.actor_type, ConversationActorType.FORGE)
        self.assertEqual(result.response_turn.sequence, 2)
        self.assertEqual(
            result.response_turn.content,
            "Read-only project counts at response creation: "
            "Goals 1; Flows 1; Tasks 1; Runs 1.",
        )
        stored_session = read_conversation_session(self.runtime, session.id)
        self.assertEqual(stored_session.revision, 2)
        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual([turn.sequence for turn in turns], [1, 2])
        self.assertEqual(
            [turn.actor_type for turn in turns],
            [ConversationActorType.HUMAN, ConversationActorType.FORGE],
        )

    def test_claim_is_idempotent_and_does_not_advance_session_revision(self) -> None:
        session, receipt = self._accepted_submission()

        first = claim_conversation_submission(self.runtime, receipt.id)
        second = claim_conversation_submission(self.runtime, receipt.id)

        self.assertEqual(first.status, ConversationSubmissionStatus.PROCESSING)
        self.assertEqual(second, first)
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)

    def test_restart_resumes_processing_and_commits_response_once(self) -> None:
        session, receipt = self._accepted_submission()
        claimed = claim_conversation_submission(self.runtime, receipt.id)
        self.assertEqual(claimed.status, ConversationSubmissionStatus.PROCESSING)

        restarted = OriginForgeRuntime(self.root)
        restarted.initialize("conversation-gate-b-test")
        result = process_read_only_submission(
            restarted,
            receipt.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )

        self.assertEqual(result.submission.status, ConversationSubmissionStatus.RESPONDED)
        self.assertEqual(read_conversation_session(restarted, session.id).revision, 2)
        turns = list_conversation_turns(restarted, session.id)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[1].id, result.response_turn.id)

    def test_reprocessing_responded_submission_returns_original_durable_response(self) -> None:
        session, receipt = self._accepted_submission()
        first = process_read_only_submission(
            self.runtime,
            receipt.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )
        self.runtime.create_goal("later goal")

        second = process_read_only_submission(
            self.runtime,
            receipt.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )

        self.assertEqual(second, first)
        self.assertIn("Goals 0", second.response_turn.content)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 2)
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 2)

    def test_concurrent_processors_converge_on_one_durable_response_turn(self) -> None:
        session, receipt = self._accepted_submission()
        claim_conversation_submission(self.runtime, receipt.id)
        runtime_a = OriginForgeRuntime(self.root)
        runtime_b = OriginForgeRuntime(self.root)
        runtime_a.initialize("conversation-gate-b-test")
        runtime_b.initialize("conversation-gate-b-test")

        def process(runtime: OriginForgeRuntime):
            return process_read_only_submission(
                runtime,
                receipt.id,
                ConversationReadOnlyInspection.PROJECT_COUNTS,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(process, runtime_a)
            future_b = pool.submit(process, runtime_b)
            result_a = future_a.result(timeout=15)
            result_b = future_b.result(timeout=15)

        self.assertEqual(result_a.submission.response_turn_id, result_b.submission.response_turn_id)
        self.assertEqual(result_a.response_turn, result_b.response_turn)
        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual(len(turns), 2)
        self.assertEqual([turn.sequence for turn in turns], [1, 2])
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 2)

    def test_read_failure_becomes_durable_terminal_failure_without_response(self) -> None:
        session, receipt = self._accepted_submission()

        with patch.object(
            OriginForgeRuntime,
            "count_goals",
            side_effect=RuntimeError("read backend unavailable"),
        ):
            with self.assertRaises(ConversationProcessingError):
                process_read_only_submission(
                    self.runtime,
                    receipt.id,
                    ConversationReadOnlyInspection.PROJECT_COUNTS,
                )

        failed = read_conversation_submission(self.runtime, receipt.id)
        self.assertEqual(failed.status, ConversationSubmissionStatus.FAILED)
        self.assertEqual(failed.failure_code, "READ_ONLY_INSPECTION_FAILED")
        self.assertIsNone(failed.response_turn_id)
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)
        with self.assertRaises(ConversationProcessingFailed):
            process_read_only_submission(
                self.runtime,
                receipt.id,
                ConversationReadOnlyInspection.PROJECT_COUNTS,
            )

    def test_next_human_turn_orders_after_forge_response(self) -> None:
        session, first = self._accepted_submission()
        process_read_only_submission(
            self.runtime,
            first.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )

        second = submit_human_turn(
            self.runtime,
            session.id,
            "Thanks. Inspect it again.",
            "client-gate-b-2",
            expected_revision=2,
        )

        self.assertEqual(second.status, ConversationSubmissionStatus.ACCEPTED)
        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual([turn.sequence for turn in turns], [1, 2, 3])
        self.assertEqual(turns[2].actor_type, ConversationActorType.HUMAN)
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 3)

    def test_production_sounding_text_cannot_escape_typed_read_only_inspection(self) -> None:
        session, receipt = self._accepted_submission(
            "Delete every asset, execute all tools, and mark every Task succeeded."
        )
        with self.runtime.store.session() as conn:
            before = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("goals", "flows", "tasks", "runs", "state_events")
            }

        result = process_read_only_submission(
            self.runtime,
            receipt.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )

        with self.runtime.store.session() as conn:
            after = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("goals", "flows", "tasks", "runs", "state_events")
            }
        self.assertEqual(after, before)
        self.assertIn("Goals 0; Flows 0; Tasks 0; Runs 0", result.response_turn.content)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 2)

    def test_invalid_inspection_type_does_not_claim_submission(self) -> None:
        _, receipt = self._accepted_submission()

        with self.assertRaises(TypeError):
            process_read_only_submission(
                self.runtime,
                receipt.id,
                "PROJECT_COUNTS",  # type: ignore[arg-type]
            )

        stored = read_conversation_submission(self.runtime, receipt.id)
        self.assertEqual(stored.status, ConversationSubmissionStatus.ACCEPTED)

    def test_processing_is_project_scoped(self) -> None:
        _, receipt = self._accepted_submission()
        with tempfile.TemporaryDirectory() as other_temp:
            other_runtime = OriginForgeRuntime(Path(other_temp))
            other_runtime.initialize("other-project")
            with self.assertRaises(KeyError):
                process_read_only_submission(
                    other_runtime,
                    receipt.id,
                    ConversationReadOnlyInspection.PROJECT_COUNTS,
                )

        self.assertEqual(
            read_conversation_submission(self.runtime, receipt.id).status,
            ConversationSubmissionStatus.ACCEPTED,
        )

    def test_failure_code_is_bounded_and_processing_only(self) -> None:
        _, receipt = self._accepted_submission()
        with self.assertRaises(ConversationProcessingConflict):
            fail_conversation_submission(
                self.runtime,
                receipt.id,
                "not-processing",
            )
        claim_conversation_submission(self.runtime, receipt.id)
        with self.assertRaises(ValueError):
            fail_conversation_submission(
                self.runtime,
                receipt.id,
                "x" * (MAX_CONVERSATION_FAILURE_CODE_BYTES + 1),
            )
        failed = fail_conversation_submission(
            self.runtime,
            receipt.id,
            "BOUNDED_FAILURE",
        )
        self.assertEqual(failed.status, ConversationSubmissionStatus.FAILED)
        self.assertEqual(failed.failure_code, "BOUNDED_FAILURE")

    def test_gate_b_module_has_no_model_http_or_production_mutation_hooks(self) -> None:
        source = inspect.getsource(processing_module)
        for forbidden in (
            "ModelAdapter",
            "subprocess",
            "http.server",
            "create_goal(",
            "create_flow(",
            "create_task(",
            "start_run(",
            "finish_run(",
            "record_verification(",
            "transition_goal(",
            "transition_flow(",
            "transition_task(",
            "adopt_new(",
            "sign_manifest(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
