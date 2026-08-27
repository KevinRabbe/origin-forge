from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import origin_forge.conversation_production as production_module
from origin_forge.conversation_operations import (
    ConversationOperation,
    read_conversation_submission_operation,
)
from origin_forge.conversation_processing import (
    ConversationProcessingConflict,
    ConversationReadOnlyInspection,
    claim_conversation_submission,
    process_read_only_submission,
)
from origin_forge.conversation_production import (
    ConversationProductionConflict,
    admit_conversation_goal,
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
from origin_forge.db import SCHEMA_VERSION
from origin_forge.runtime import OriginForgeRuntime


class ConversationGateC1ProductionAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("conversation-gate-c1-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _accepted_submission(
        self,
        content: str = "Create a durable production goal from this exact request.",
        *,
        client_submission_id: str = "client-gate-c1",
    ):
        session = create_conversation_session(self.runtime)
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            content,
            client_submission_id,
            expected_revision=0,
        )
        return session, receipt

    def _count(self, table: str) -> int:
        with self.runtime.store.session() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def test_production_submission_admits_one_exact_goal_and_result_reference(self) -> None:
        content = "Build the player controller — preserve UTF-8 ✓ and exact punctuation!"
        session, receipt = self._accepted_submission(content)

        result = admit_conversation_goal(self.runtime, receipt.id)

        self.assertEqual(result.submission.status, ConversationSubmissionStatus.PROCESSING)
        self.assertEqual(result.human_turn.actor_type, ConversationActorType.HUMAN)
        self.assertEqual(result.human_turn.content, content)
        self.assertEqual(self.runtime.get_goal(result.goal_id)["objective"], content)
        self.assertEqual(
            read_conversation_submission_operation(self.runtime, receipt.id),
            ConversationOperation.PRODUCTION_CREATE_GOAL,
        )
        with self.runtime.store.session() as conn:
            event = conn.execute(
                """SELECT aggregate_id, actor_type, actor_id
                   FROM state_events
                   WHERE event_type = 'GOAL_CREATED'
                     AND actor_type = 'CONVERSATION'
                     AND actor_id = ?""",
                (receipt.id,),
            ).fetchone()
            reference = conn.execute(
                """SELECT reference_type, reference_id, relation
                   FROM conversation_turn_references
                   WHERE turn_id = ?""",
                (receipt.human_turn_id,),
            ).fetchone()
        self.assertIsNotNone(event)
        self.assertEqual(event["aggregate_id"], result.goal_id)
        self.assertEqual(event["actor_type"], "CONVERSATION")
        self.assertEqual(event["actor_id"], receipt.id)
        self.assertIsNotNone(reference)
        self.assertEqual(
            dict(reference),
            {
                "reference_type": "GOAL",
                "reference_id": result.goal_id,
                "relation": "RESULT",
            },
        )
        self.assertEqual(self.runtime.count_goals(), 1)
        self.assertEqual(self.runtime.count_flows(), 0)
        self.assertEqual(self.runtime.count_tasks(), 0)
        self.assertEqual(self.runtime.count_runs(), 0)
        self.assertEqual(self._count("goal_bootstraps"), 0)
        self.assertEqual(self._count("task_preparations"), 0)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)
        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].actor_type, ConversationActorType.HUMAN)

    def test_retry_returns_same_goal_without_duplicate_authority(self) -> None:
        _, receipt = self._accepted_submission()

        first = admit_conversation_goal(self.runtime, receipt.id)
        second = admit_conversation_goal(self.runtime, receipt.id)

        self.assertEqual(second.goal_id, first.goal_id)
        self.assertEqual(self.runtime.count_goals(), 1)
        with self.runtime.store.session() as conn:
            events = int(
                conn.execute(
                    """SELECT COUNT(*) FROM state_events
                       WHERE event_type = 'GOAL_CREATED'
                         AND actor_type = 'CONVERSATION'
                         AND actor_id = ?""",
                    (receipt.id,),
                ).fetchone()[0]
            )
            references = int(
                conn.execute(
                    """SELECT COUNT(*) FROM conversation_turn_references
                       WHERE turn_id = ? AND reference_type = 'GOAL'
                         AND reference_id = ? AND relation = 'RESULT'""",
                    (receipt.human_turn_id, first.goal_id),
                ).fetchone()[0]
            )
        self.assertEqual(events, 1)
        self.assertEqual(references, 1)

    def test_restart_recovers_goal_after_post_creation_interruption(self) -> None:
        _, receipt = self._accepted_submission()

        with patch.object(
            production_module,
            "ensure_conversation_turn_reference",
            side_effect=RuntimeError("simulated interruption after Goal commit"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                admit_conversation_goal(self.runtime, receipt.id)

        goals_after_interruption = self.runtime.list_goals()
        self.assertEqual(len(goals_after_interruption), 1)
        original_goal_id = goals_after_interruption[0]["id"]
        self.assertEqual(
            read_conversation_submission(self.runtime, receipt.id).status,
            ConversationSubmissionStatus.PROCESSING,
        )

        restarted = OriginForgeRuntime(self.root)
        restarted.initialize("conversation-gate-c1-test")
        recovered = admit_conversation_goal(restarted, receipt.id)

        self.assertEqual(recovered.goal_id, original_goal_id)
        self.assertEqual(restarted.count_goals(), 1)
        with restarted.store.session() as conn:
            self.assertEqual(
                int(
                    conn.execute(
                        """SELECT COUNT(*) FROM state_events
                           WHERE event_type = 'GOAL_CREATED'
                             AND actor_type = 'CONVERSATION'
                             AND actor_id = ?""",
                        (receipt.id,),
                    ).fetchone()[0]
                ),
                1,
            )
            self.assertEqual(
                int(
                    conn.execute(
                        """SELECT COUNT(*) FROM conversation_turn_references
                           WHERE turn_id = ? AND reference_type = 'GOAL'
                             AND reference_id = ? AND relation = 'RESULT'""",
                        (receipt.human_turn_id, original_goal_id),
                    ).fetchone()[0]
                ),
                1,
            )

    def test_concurrent_processors_converge_on_one_goal(self) -> None:
        _, receipt = self._accepted_submission()
        runtime_a = OriginForgeRuntime(self.root)
        runtime_b = OriginForgeRuntime(self.root)
        runtime_a.initialize("conversation-gate-c1-test")
        runtime_b.initialize("conversation-gate-c1-test")

        def admit(runtime: OriginForgeRuntime):
            return admit_conversation_goal(runtime, receipt.id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(admit, runtime_a)
            future_b = pool.submit(admit, runtime_b)
            result_a = future_a.result(timeout=15)
            result_b = future_b.result(timeout=15)

        self.assertEqual(result_a.goal_id, result_b.goal_id)
        self.assertEqual(self.runtime.count_goals(), 1)
        with self.runtime.store.session() as conn:
            self.assertEqual(
                int(
                    conn.execute(
                        """SELECT COUNT(*) FROM state_events
                           WHERE event_type = 'GOAL_CREATED'
                             AND actor_type = 'CONVERSATION'
                             AND actor_id = ?""",
                        (receipt.id,),
                    ).fetchone()[0]
                ),
                1,
            )

    def test_read_only_binding_prevents_production_reclassification(self) -> None:
        _, receipt = self._accepted_submission("Inspect status only.")
        process_read_only_submission(
            self.runtime,
            receipt.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )

        with self.assertRaises(ConversationProductionConflict):
            admit_conversation_goal(self.runtime, receipt.id)

        self.assertEqual(self.runtime.count_goals(), 0)
        self.assertEqual(
            read_conversation_submission_operation(self.runtime, receipt.id),
            ConversationOperation.READ_ONLY_PROJECT_COUNTS,
        )

    def test_production_binding_prevents_read_only_reclassification(self) -> None:
        session, receipt = self._accepted_submission()
        admitted = admit_conversation_goal(self.runtime, receipt.id)

        with self.assertRaises(ConversationProcessingConflict):
            process_read_only_submission(
                self.runtime,
                receipt.id,
                ConversationReadOnlyInspection.PROJECT_COUNTS,
            )

        self.assertEqual(self.runtime.count_goals(), 1)
        self.assertEqual(
            read_conversation_submission_operation(self.runtime, receipt.id),
            ConversationOperation.PRODUCTION_CREATE_GOAL,
        )
        self.assertEqual(
            read_conversation_submission(self.runtime, receipt.id).status,
            ConversationSubmissionStatus.PROCESSING,
        )
        self.assertEqual(read_conversation_session(self.runtime, session.id).revision, 1)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)
        self.assertEqual(self.runtime.get_goal(admitted.goal_id)["status"], "OPEN")

    def test_preclaimed_processing_can_bind_on_restart_without_reclassification_gap(self) -> None:
        _, receipt = self._accepted_submission()
        claimed = claim_conversation_submission(self.runtime, receipt.id)
        self.assertEqual(claimed.status, ConversationSubmissionStatus.PROCESSING)
        self.assertIsNone(
            read_conversation_submission_operation(self.runtime, receipt.id)
        )

        restarted = OriginForgeRuntime(self.root)
        restarted.initialize("conversation-gate-c1-test")
        result = admit_conversation_goal(restarted, receipt.id)

        self.assertEqual(restarted.count_goals(), 1)
        self.assertEqual(
            read_conversation_submission_operation(restarted, receipt.id),
            ConversationOperation.PRODUCTION_CREATE_GOAL,
        )
        self.assertEqual(result.submission.status, ConversationSubmissionStatus.PROCESSING)
        with self.assertRaises(ConversationProcessingConflict):
            process_read_only_submission(
                restarted,
                receipt.id,
                ConversationReadOnlyInspection.PROJECT_COUNTS,
            )

    def test_production_admission_is_project_scoped(self) -> None:
        _, receipt = self._accepted_submission()
        with tempfile.TemporaryDirectory() as other_temp:
            other_runtime = OriginForgeRuntime(Path(other_temp))
            other_runtime.initialize("other-project")
            with self.assertRaises(KeyError):
                admit_conversation_goal(other_runtime, receipt.id)
            self.assertEqual(other_runtime.count_goals(), 0)

        self.assertEqual(
            read_conversation_submission(self.runtime, receipt.id).status,
            ConversationSubmissionStatus.ACCEPTED,
        )
        self.assertEqual(self.runtime.count_goals(), 0)

    def test_db_unique_authority_rolls_back_second_goal_for_same_submission(self) -> None:
        _, receipt = self._accepted_submission()
        admitted = admit_conversation_goal(self.runtime, receipt.id)
        project_id = self.runtime.project_id()

        with self.assertRaises(sqlite3.IntegrityError):
            self.runtime.store.create_goal(
                project_id,
                "a duplicate Goal that must roll back",
                actor_type="CONVERSATION",
                actor_id=receipt.id,
            )

        self.assertEqual(self.runtime.count_goals(), 1)
        self.assertEqual(self.runtime.list_goals()[0]["id"], admitted.goal_id)

    def test_gate_c1_handoff_constraints_are_preserved_in_current_schema(self) -> None:
        self.assertGreaterEqual(SCHEMA_VERSION, 27)
        with self.runtime.store.session() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            indexes = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        self.assertIn("conversation_submission_operations", tables)
        self.assertIn("conversation_turn_references", tables)
        self.assertIn("idx_conversation_goal_created_once_per_submission", indexes)

    def test_gate_c1_has_no_bootstrap_manager_dispatch_model_or_http_hooks(self) -> None:
        source = inspect.getsource(production_module)
        for forbidden in (
            "advance_production_manager",
            "bootstrap_goal_once",
            "recover_goal_once",
            "create_flow(",
            "create_task(",
            "transition_goal(",
            "transition_flow(",
            "transition_task(",
            "start_run(",
            "record_verification(",
            "ModelAdapter",
            "http.server",
            "subprocess",
            "INSERT INTO goals",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
