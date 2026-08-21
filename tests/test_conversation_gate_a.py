from __future__ import annotations

import inspect
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import origin_forge.conversation_service as conversation_module
from origin_forge.conversation_service import (
    MAX_CONVERSATION_CONTENT_BYTES,
    MAX_CONVERSATION_READ_LIMIT,
    ConversationActorType,
    ConversationConflict,
    ConversationSessionStatus,
    ConversationSubmissionStatus,
    create_conversation_session,
    list_conversation_sessions,
    list_conversation_turns,
    read_conversation_session,
    read_conversation_submission,
    submit_human_turn,
)
from origin_forge.ids import IdKind, validate_id
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import StaleRevision


class ConversationGateATests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("conversation-gate-a-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_session_and_human_submission_are_durable_and_ordered(self) -> None:
        session = create_conversation_session(self.runtime)
        first = submit_human_turn(
            self.runtime,
            session.id,
            "Inspect the current project state.",
            "client-001",
            expected_revision=0,
        )
        second = submit_human_turn(
            self.runtime,
            session.id,
            "Continue with the next bounded step.",
            "client-002",
            expected_revision=1,
        )

        stored_session = read_conversation_session(self.runtime, session.id)
        turns = list_conversation_turns(self.runtime, session.id)

        self.assertTrue(validate_id(session.id, IdKind.CONVERSATION_SESSION))
        self.assertTrue(validate_id(first.id, IdKind.CONVERSATION_SUBMISSION))
        self.assertTrue(validate_id(second.id, IdKind.CONVERSATION_SUBMISSION))
        self.assertEqual(stored_session.status, ConversationSessionStatus.OPEN)
        self.assertEqual(stored_session.revision, 2)
        self.assertEqual([turn.sequence for turn in turns], [1, 2])
        self.assertEqual(
            [turn.actor_type for turn in turns],
            [ConversationActorType.HUMAN, ConversationActorType.HUMAN],
        )
        self.assertTrue(
            all(validate_id(turn.id, IdKind.CONVERSATION_TURN) for turn in turns)
        )
        self.assertEqual(first.human_turn_id, turns[0].id)
        self.assertEqual(second.human_turn_id, turns[1].id)
        self.assertEqual(first.status, ConversationSubmissionStatus.ACCEPTED)
        self.assertEqual(second.status, ConversationSubmissionStatus.ACCEPTED)
        self.assertEqual(first.expected_session_revision, 0)
        self.assertEqual(second.expected_session_revision, 1)

    def test_duplicate_submission_key_returns_existing_receipt_after_revision_advance(self) -> None:
        session = create_conversation_session(self.runtime)
        original = submit_human_turn(
            self.runtime,
            session.id,
            "Same durable intent",
            "retry-key",
            expected_revision=0,
        )

        retry = submit_human_turn(
            self.runtime,
            session.id,
            "Same durable intent",
            "retry-key",
            expected_revision=0,
        )

        self.assertEqual(retry, original)
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)
        self.assertEqual(read_conversation_submission(self.runtime, original.id), original)

    def test_duplicate_submission_key_with_different_content_fails_closed(self) -> None:
        session = create_conversation_session(self.runtime)
        submit_human_turn(
            self.runtime,
            session.id,
            "First content",
            "conflict-key",
            expected_revision=0,
        )

        with self.assertRaises(ConversationConflict):
            submit_human_turn(
                self.runtime,
                session.id,
                "Different content",
                "conflict-key",
                expected_revision=1,
            )

        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)

    def test_stale_revision_cannot_append_a_distinct_turn(self) -> None:
        session = create_conversation_session(self.runtime)
        submit_human_turn(
            self.runtime,
            session.id,
            "First",
            "first-key",
            expected_revision=0,
        )

        with self.assertRaises(StaleRevision):
            submit_human_turn(
                self.runtime,
                session.id,
                "Stale second",
                "stale-key",
                expected_revision=0,
            )

        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)

    def test_concurrent_distinct_clients_cannot_claim_the_same_sequence(self) -> None:
        session = create_conversation_session(self.runtime)
        runtime_a = OriginForgeRuntime(self.root)
        runtime_b = OriginForgeRuntime(self.root)
        runtime_a.initialize("conversation-gate-a-test")
        runtime_b.initialize("conversation-gate-a-test")
        barrier = threading.Barrier(2)

        def submit(runtime: OriginForgeRuntime, key: str) -> str:
            barrier.wait(timeout=5)
            try:
                submit_human_turn(
                    runtime,
                    session.id,
                    f"content-{key}",
                    key,
                    expected_revision=0,
                )
            except StaleRevision:
                return "STALE"
            return "ACCEPTED"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(
                (
                    pool.submit(submit, runtime_a, "client-a").result(timeout=10),
                    pool.submit(submit, runtime_b, "client-b").result(timeout=10),
                )
            )

        self.assertEqual(results, ["ACCEPTED", "STALE"])
        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].sequence, 1)
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)

    def test_restart_reconstructs_committed_history_without_model_context(self) -> None:
        session = create_conversation_session(self.runtime)
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            "Persist across restart",
            "restart-key",
            expected_revision=0,
        )

        restarted = OriginForgeRuntime(self.root)
        restarted.initialize("conversation-gate-a-test")

        self.assertEqual(read_conversation_session(restarted, session.id).revision, 1)
        turns = list_conversation_turns(restarted, session.id)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].content, "Persist across restart")
        self.assertEqual(read_conversation_submission(restarted, receipt.id), receipt)

    def test_committed_turns_are_database_immutable(self) -> None:
        session = create_conversation_session(self.runtime)
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            "Immutable history",
            "immutable-key",
            expected_revision=0,
        )

        with self.runtime.store.session() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE conversation_turns SET content = ? WHERE id = ?",
                    ("rewritten", receipt.human_turn_id),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "DELETE FROM conversation_turns WHERE id = ?",
                    (receipt.human_turn_id,),
                )

        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual([turn.content for turn in turns], ["Immutable history"])

    def test_human_submission_does_not_mutate_production_or_use_state_events_as_chat(self) -> None:
        with self.runtime.store.session() as conn:
            before = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("goals", "flows", "tasks", "runs", "state_events")
            }

        session = create_conversation_session(self.runtime)
        submit_human_turn(
            self.runtime,
            session.id,
            "Record intent only",
            "intent-only-key",
            expected_revision=0,
        )

        with self.runtime.store.session() as conn:
            after = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("goals", "flows", "tasks", "runs", "state_events")
            }
        self.assertEqual(after, before)

    def test_reads_are_bounded_and_turn_pagination_is_sequence_based(self) -> None:
        session = create_conversation_session(self.runtime)
        for index in range(3):
            submit_human_turn(
                self.runtime,
                session.id,
                f"turn-{index + 1}",
                f"key-{index + 1}",
                expected_revision=index,
            )

        sessions = list_conversation_sessions(self.runtime, limit=1)
        turns = list_conversation_turns(
            self.runtime,
            session.id,
            after_sequence=1,
            limit=1,
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual([turn.sequence for turn in turns], [2])
        with self.assertRaises(ValueError):
            list_conversation_sessions(self.runtime, limit=0)
        with self.assertRaises(ValueError):
            list_conversation_turns(
                self.runtime,
                session.id,
                limit=MAX_CONVERSATION_READ_LIMIT + 1,
            )
        with self.assertRaises(ValueError):
            list_conversation_turns(
                self.runtime,
                session.id,
                after_sequence=-1,
            )

    def test_submission_input_is_bounded_without_rewriting_content(self) -> None:
        session = create_conversation_session(self.runtime)
        content = "  preserve exact operator text  "
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            content,
            "exact-content-key",
            expected_revision=0,
        )
        turn = list_conversation_turns(self.runtime, session.id)[0]
        self.assertEqual(turn.content, content)
        self.assertEqual(turn.id, receipt.human_turn_id)

        with self.assertRaises(ValueError):
            submit_human_turn(
                self.runtime,
                session.id,
                "x" * (MAX_CONVERSATION_CONTENT_BYTES + 1),
                "too-large",
                expected_revision=1,
            )
        with self.assertRaises(ValueError):
            submit_human_turn(
                self.runtime,
                session.id,
                "valid",
                " padded-key ",
                expected_revision=1,
            )

    def test_gate_a_service_has_no_model_http_or_production_mutation_hooks(self) -> None:
        source = inspect.getsource(conversation_module)
        for forbidden in (
            "ModelAdapter",
            "subprocess",
            "http.server",
            "create_goal(",
            "create_flow(",
            "create_task(",
            "start_run(",
            "record_verification(",
            "adopt_new(",
            "sign_manifest(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
