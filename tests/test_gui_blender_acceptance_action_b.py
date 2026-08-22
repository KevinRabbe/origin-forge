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
                "SELECT COUNT(*) FROM verifications WHERE target_type = 'TASK' AND target_id = ? AND verification_type = ?",
                (self.output_binding.task_id, BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE),
            ).fetchone()[0]
            transition_count = conn.execute(
                "SELECT COUNT(*) FROM state_events WHERE aggregate_type = 'TASK' AND aggregate_id = ? AND event_type = 'TASK_STATUS_CHANGED' AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'",
                (self.output_binding.task_id,),
            ).fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return acceptance_count, verification_count, transition_count, run_count


if __name__ == "__main__":
    unittest.main()
