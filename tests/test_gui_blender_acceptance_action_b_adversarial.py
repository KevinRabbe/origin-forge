from __future__ import annotations

import unittest
from unittest.mock import patch

from origin_forge.conversation_blender_task_acceptance_service import (
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
from origin_forge.conversation_service import create_conversation_session, submit_human_turn
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
from .test_phase53a_blender_production_task_acceptance import (
    Phase53ABlenderProductionTaskAcceptanceTests,
)


class GUIBlenderAcceptanceActionBAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phase53 = Phase53ABlenderProductionTaskAcceptanceTests(
            methodName="test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task"
        )
        self.phase53.setUp()
        (
            self.runtime,
            self.output_binding,
            self.adoption,
            _dispatch_binding,
            self.task_revision,
        ) = self.phase53._published_inputs()

    def tearDown(self) -> None:
        self.phase53.tearDown()

    def _conversation(self, *, reference_task: bool = True):
        session = create_conversation_session(self.runtime)
        submission = submit_human_turn(
            self.runtime,
            session.id,
            "explicit Blender acceptance action",
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
        return session

    def _counts(self) -> tuple[int, int, int, int]:
        with self.runtime.store.session() as conn:
            acceptances = conn.execute(
                "SELECT COUNT(*) FROM blender_production_task_acceptances"
            ).fetchone()[0]
            verifications = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?
                     AND verification_type = ?""",
                (
                    self.output_binding.task_id,
                    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                ),
            ).fetchone()[0]
            transitions = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                     AND event_type = 'TASK_STATUS_CHANGED'
                     AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'""",
                (self.output_binding.task_id,),
            ).fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return acceptances, verifications, transitions, runs

    def test_pending_acceptance_requires_explicit_service_call_to_recover(self) -> None:
        session = self._conversation()
        acceptor = GovernedBlenderProductionTaskAcceptor(self.runtime)
        with patch.object(
            self.runtime,
            "transition_task",
            side_effect=RuntimeError("simulated crash after durable acceptance"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                acceptor.accept(
                    self.output_binding.execution_id,
                    actor_id="operator.phase53b.pending-fixture",
                )

        pending = inspect_blender_production_task_acceptance_currentness_readonly(
            self.runtime,
            self.output_binding.execution_id,
        )
        self.assertIs(
            pending.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
        )
        receipt = read_blender_production_task_acceptance(
            self.runtime,
            self.output_binding.execution_id,
        )
        before = self._counts()

        result = accept_conversation_blender_task(
            self.runtime,
            session.id,
            self.output_binding.execution_id,
        )

        self.assertIs(result.outcome, ConversationBlenderTaskAcceptanceOutcome.RECOVERED)
        self.assertEqual(result.task_verification_id, receipt.task_verification_id)
        after = self._counts()
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1], before[1])
        self.assertEqual(after[2], before[2] + 1)
        self.assertEqual(after[3], before[3])

    def test_execution_linked_only_to_another_conversation_cannot_be_substituted(self) -> None:
        linked = self._conversation()
        selected = self._conversation(reference_task=False)
        self.assertNotEqual(linked.id, selected.id)
        before = self._counts()

        with self.assertRaises(ConversationBlenderTaskAcceptanceRejected) as raised:
            accept_conversation_blender_task(
                self.runtime,
                selected.id,
                self.output_binding.execution_id,
            )

        self.assertIs(
            raised.exception.code,
            ConversationBlenderTaskAcceptanceFailureCode.EXECUTION_NOT_LINKED,
        )
        self.assertEqual(self._counts(), before)

    def test_ambiguous_task_execution_relation_is_rejected_without_selection(self) -> None:
        session = self._conversation()
        before = self._counts()
        second_execution = new_id(IdKind.DISPATCH_EXECUTION)

        with patch(
            "origin_forge.conversation_blender_task_acceptance_actions."
            "discover_blender_dispatch_output_executions_for_task_readonly",
            return_value=(self.output_binding.execution_id, second_execution),
        ):
            with self.assertRaises(ConversationBlenderTaskAcceptanceRejected) as raised:
                accept_conversation_blender_task(
                    self.runtime,
                    session.id,
                    self.output_binding.execution_id,
                )

        self.assertIs(
            raised.exception.code,
            ConversationBlenderTaskAcceptanceFailureCode.STALE_OR_CONFLICTING,
        )
        self.assertEqual(self._counts(), before)

    def test_stale_canonical_bytes_are_bounded_failure_without_acceptance(self) -> None:
        session = self._conversation()
        destination = self.runtime.project_root / self.adoption.destination_path
        destination.write_bytes(destination.read_bytes() + b"drift")
        before = self._counts()

        with self.assertRaises(ConversationBlenderTaskAcceptanceRejected) as raised:
            accept_conversation_blender_task(
                self.runtime,
                session.id,
                self.output_binding.execution_id,
            )

        self.assertIs(
            raised.exception.code,
            ConversationBlenderTaskAcceptanceFailureCode.STALE_OR_CONFLICTING,
        )
        self.assertLessEqual(len(raised.exception.detail), 240)
        self.assertNotIn(str(self.runtime.project_root), raised.exception.detail)
        self.assertEqual(self._counts(), before)

    def test_invalid_ids_fail_before_any_production_action(self) -> None:
        before = self._counts()
        with self.assertRaises(ConversationBlenderTaskAcceptanceRejected) as bad_conversation:
            accept_conversation_blender_task(
                self.runtime,
                "not-a-conversation",
                self.output_binding.execution_id,
            )
        self.assertIs(
            bad_conversation.exception.code,
            ConversationBlenderTaskAcceptanceFailureCode.INVALID_CONVERSATION_ID,
        )

        with self.assertRaises(ConversationBlenderTaskAcceptanceRejected) as bad_execution:
            accept_conversation_blender_task(
                self.runtime,
                new_id(IdKind.CONVERSATION_SESSION),
                "not-an-execution",
            )
        self.assertIs(
            bad_execution.exception.code,
            ConversationBlenderTaskAcceptanceFailureCode.INVALID_EXECUTION_ID,
        )
        self.assertEqual(self._counts(), before)


if __name__ == "__main__":
    unittest.main()
