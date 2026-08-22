from __future__ import annotations

import unittest
from unittest.mock import patch

from origin_forge.conversation_blender_task_acceptance_service import (
    LOCAL_GUI_BLENDER_ACCEPTANCE_ACTOR_ID,
    ConversationBlenderTaskAcceptanceFailureCode,
    ConversationBlenderTaskAcceptanceOutcome,
    ConversationBlenderTaskAcceptanceRejected,
    accept_conversation_blender_task,
)
from origin_forge.conversation_operations import (
    ConversationReferenceRelation,
    ConversationReferenceType,
    ensure_conversation_turn_reference,
)
from origin_forge.conversation_service import (
    create_conversation_session,
    list_conversation_turns,
    read_conversation_submission,
    submit_human_turn,
)
from origin_forge.ids import IdKind, new_id
from origin_forge.production_blender_task_acceptance import (
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    read_blender_production_task_acceptance,
)
from origin_forge.production_blender_task_acceptance_currentness import (
    BlenderProductionTaskAcceptanceCurrentnessStatus,
    inspect_blender_production_task_acceptance_currentness_readonly,
)
from origin_forge.production_blender_task_acceptor import GovernedBlenderProductionTaskAcceptor
from test_phase53a_blender_production_task_acceptance import (
    Phase53ABlenderProductionTaskAcceptanceTests,
)


class GUIBlenderAcceptanceActionBServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phase53 = Phase53ABlenderProductionTaskAcceptanceTests(
            methodName="test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task"
        )
        self.phase53.setUp()
        (
            self.runtime,
            self.output_binding,
            self.adoption,
            self.dispatch_binding,
            self.task_revision,
        ) = self.phase53._published_inputs()

    def tearDown(self) -> None:
        self.phase53.tearDown()

    def _conversation(self, *, reference_task: bool = True):
        session = create_conversation_session(self.runtime)
        submission = submit_human_turn(
            self.runtime,
            session.id,
            "accept the exact governed Blender production result",
            new_id(IdKind.CONVERSATION_SUBMISSION),
            expected_revision=0,
        )
        if reference_task:
            ensure_conversation_turn_reference(
                self.runtime,
                submission.human_turn_id,
                ConversationReferenceType.TASK,
                self.output_binding.task_id,
                ConversationReferenceRelation.RESULT,
            )
        return session, submission

    def _production_counts(self) -> tuple[int, int, int, int]:
        with self.runtime.store.session() as conn:
            acceptance_count = conn.execute(
                "SELECT COUNT(*) FROM blender_production_task_acceptances"
            ).fetchone()[0]
            verification_count = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?
                     AND verification_type = ?""",
                (
                    self.output_binding.task_id,
                    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                ),
            ).fetchone()[0]
            transition_count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                     AND event_type = 'TASK_STATUS_CHANGED'
                     AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'""",
                (self.output_binding.task_id,),
            ).fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return acceptance_count, verification_count, transition_count, run_count

    def test_exact_linked_execution_accepts_once_with_code_owned_operator_identity(self) -> None:
        session, submission = self._conversation()
        destination = self.runtime.project_root / self.adoption.destination_path
        bytes_before = destination.read_bytes()
        turns_before = list_conversation_turns(self.runtime, session.id)
        submission_before = read_conversation_submission(self.runtime, submission.id)
        counts_before = self._production_counts()

        result = accept_conversation_blender_task(
            self.runtime,
            session.id,
            self.output_binding.execution_id,
        )

        self.assertIs(result.outcome, ConversationBlenderTaskAcceptanceOutcome.ACCEPTED)
        self.assertEqual(result.conversation_session_id, session.id)
        self.assertEqual(result.execution_id, self.output_binding.execution_id)
        self.assertEqual(result.task_id, self.output_binding.task_id)
        self.assertEqual(result.adopted_artifact_id, self.adoption.adopted_artifact_id)
        self.assertEqual(result.accepted_destination_path, self.adoption.destination_path)
        self.assertEqual(
            result.accepted_content_hash,
            "sha256:" + self.output_binding.output_content_hash,
        )
        self.assertEqual(result.accepted_byte_count, self.output_binding.output_byte_count)
        self.assertEqual(result.task_revision_at_acceptance, self.task_revision)
        self.assertEqual(result.task_revision, self.task_revision + 1)
        self.assertEqual(result.task_status, "SUCCEEDED")
        self.assertTrue(result.production_task_verified)
        self.assertTrue(result.semantic_geometry_verified)
        self.assertTrue(result.canonical_asset_adopted)
        self.assertFalse(result.provenance_signed)
        self.assertFalse(result.release_authorized)

        after = self._production_counts()
        self.assertEqual(after[0], counts_before[0] + 1)
        self.assertEqual(after[1], counts_before[1] + 1)
        self.assertEqual(after[2], counts_before[2] + 1)
        self.assertEqual(after[3], counts_before[3])
        self.assertEqual(destination.read_bytes(), bytes_before)
        self.assertEqual(list_conversation_turns(self.runtime, session.id), turns_before)
        self.assertEqual(
            read_conversation_submission(self.runtime, submission.id), submission_before
        )

        with self.runtime.store.session() as conn:
            event = conn.execute(
                """SELECT actor_type, actor_id FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                     AND event_type = 'VERIFICATION_RECORDED'
                   ORDER BY rowid DESC LIMIT 1""",
                (self.output_binding.task_id,),
            ).fetchone()
        self.assertEqual(event["actor_type"], "HUMAN")
        self.assertEqual(event["actor_id"], LOCAL_GUI_BLENDER_ACCEPTANCE_ACTOR_ID)

    def test_exact_replay_is_typed_and_creates_no_duplicate_acceptance(self) -> None:
        session, _submission = self._conversation()
        first = accept_conversation_blender_task(
            self.runtime,
            session.id,
            self.output_binding.execution_id,
        )
        counts_after_first = self._production_counts()
        second = accept_conversation_blender_task(
            self.runtime,
            session.id,
            self.output_binding.execution_id,
        )

        self.assertIs(first.outcome, ConversationBlenderTaskAcceptanceOutcome.ACCEPTED)
        self.assertIs(second.outcome, ConversationBlenderTaskAcceptanceOutcome.REPLAYED)
        self.assertEqual(second.execution_id, first.execution_id)
        self.assertEqual(second.task_id, first.task_id)
        self.assertEqual(second.task_verification_id, first.task_verification_id)
        self.assertEqual(second.accepted_at, first.accepted_at)
        self.assertEqual(self._production_counts(), counts_after_first)

    def test_unlinked_project_execution_is_rejected_before_acceptor_mutation(self) -> None:
        session, _submission = self._conversation(reference_task=False)
        counts_before = self._production_counts()
        task_before = dict(self.runtime.get_task(self.output_binding.task_id))

        with self.assertRaises(ConversationBlenderTaskAcceptanceRejected) as raised:
            accept_conversation_blender_task(
                self.runtime,
                session.id,
                self.output_binding.execution_id,
            )

        self.assertIs(
            raised.exception.code,
            ConversationBlenderTaskAcceptanceFailureCode.EXECUTION_NOT_LINKED,
        )
        self.assertEqual(self._production_counts(), counts_before)
        self.assertEqual(dict(self.runtime.get_task(self.output_binding.task_id)), task_before)


if __name__ == "__main__":
    unittest.main()
