from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.conversation_blender_task_acceptance_actions import (
    ConversationBlenderTaskAcceptanceActionError,
    project_conversation_blender_task_acceptance_actions_readonly,
)
from origin_forge.conversation_live import read_conversation_live_state
from origin_forge.conversation_operations import (
    ConversationReferenceRelation,
    ConversationReferenceType,
    ensure_conversation_turn_reference,
)
from origin_forge.conversation_service import (
    create_conversation_session,
    submit_human_turn,
)
from origin_forge.ids import IdKind, new_id
from origin_forge.production_blender_dispatch_output_discovery import (
    discover_blender_dispatch_output_executions_for_task_readonly,
)
from origin_forge.production_blender_task_acceptance_currentness import (
    BlenderProductionTaskAcceptanceCurrentnessStatus,
)
from origin_forge.production_interface_server import ProductionInterfaceRouter
from origin_forge.runtime import OriginForgeRuntime
from .test_phase53a_blender_production_task_acceptance import (
    Phase53ABlenderProductionTaskAcceptanceTests,
)


class GUIBlenderAcceptanceActionAReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phase53 = Phase53ABlenderProductionTaskAcceptanceTests(
            methodName=(
                "test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task"
            )
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

    def _conversation_live_state(self, *, reference_task: bool = True):
        session = create_conversation_session(self.runtime)
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            "show the exact Blender production acceptance state",
            new_id(IdKind.CONVERSATION_SUBMISSION),
            expected_revision=0,
        )
        if reference_task:
            ensure_conversation_turn_reference(
                self.runtime,
                receipt.human_turn_id,
                ConversationReferenceType.TASK,
                self.output_binding.task_id,
                ConversationReferenceRelation.RESULT,
            )
        return session, read_conversation_live_state(self.runtime, session.id)

    def _acceptance_counts(self) -> tuple[int, int, int]:
        with self.runtime.store.session() as conn:
            acceptance_count = conn.execute(
                "SELECT COUNT(*) FROM blender_production_task_acceptances"
            ).fetchone()[0]
            verification_count = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?""",
                (self.output_binding.task_id,),
            ).fetchone()[0]
            event_count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?""",
                (self.output_binding.task_id,),
            ).fetchone()[0]
        return acceptance_count, verification_count, event_count

    def test_exact_referenced_task_projects_phase53_status_without_mutation(self) -> None:
        session, live_state = self._conversation_live_state()
        destination = self.runtime.project_root / self.adoption.destination_path
        bytes_before = destination.read_bytes()
        task_before = dict(self.runtime.get_task(self.output_binding.task_id))
        counts_before = self._acceptance_counts()

        self.assertEqual(
            discover_blender_dispatch_output_executions_for_task_readonly(
                self.runtime, self.output_binding.task_id
            ),
            (self.output_binding.execution_id,),
        )
        projected = project_conversation_blender_task_acceptance_actions_readonly(
            self.runtime, live_state
        )

        self.assertEqual(projected.conversation_session_id, session.id)
        self.assertFalse(projected.actions_truncated)
        self.assertFalse(projected.task_references_truncated)
        self.assertEqual(len(projected.actions), 1)
        action = projected.actions[0]
        self.assertEqual(action.task_id, self.output_binding.task_id)
        self.assertEqual(action.execution_id, self.output_binding.execution_id)
        self.assertIs(
            action.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED,
        )
        self.assertTrue(action.acceptance_eligible)
        self.assertFalse(action.accepted)
        self.assertEqual(action.adopted_artifact_id, self.adoption.adopted_artifact_id)
        self.assertEqual(action.adopted_destination_path, self.adoption.destination_path)
        self.assertEqual(
            action.accepted_content_hash,
            "sha256:" + self.output_binding.output_content_hash,
        )
        self.assertEqual(
            action.accepted_byte_count,
            self.output_binding.output_byte_count,
        )
        self.assertEqual(
            action.model3d_request_id,
            self.dispatch_binding.request_projection["model3d_request_id"],
        )
        self.assertIsNone(action.task_verification_id)
        self.assertEqual(action.task_revision, self.task_revision)
        self.assertIsNone(action.detail)

        self.assertEqual(destination.read_bytes(), bytes_before)
        self.assertEqual(dict(self.runtime.get_task(self.output_binding.task_id)), task_before)
        self.assertEqual(self._acceptance_counts(), counts_before)

        restarted = OriginForgeRuntime(self.runtime.project_root)
        rebuilt = project_conversation_blender_task_acceptance_actions_readonly(
            restarted,
            read_conversation_live_state(restarted, session.id),
        )
        self.assertEqual(rebuilt.to_dict(), projected.to_dict())

    def test_unreferenced_blender_execution_never_enters_conversation_action_view(self) -> None:
        _session, live_state = self._conversation_live_state(reference_task=False)
        self.assertEqual(live_state.task_telemetry, ())
        self.assertEqual(
            discover_blender_dispatch_output_executions_for_task_readonly(
                self.runtime, self.output_binding.task_id
            ),
            (self.output_binding.execution_id,),
        )
        projected = project_conversation_blender_task_acceptance_actions_readonly(
            self.runtime, live_state
        )
        self.assertEqual(projected.actions, ())

    def test_ambiguous_task_relation_is_non_actionable_and_never_selects_execution(self) -> None:
        _session, live_state = self._conversation_live_state()
        second_execution = new_id(IdKind.DISPATCH_EXECUTION)
        with patch(
            "origin_forge.conversation_blender_task_acceptance_actions."
            "discover_blender_dispatch_output_executions_for_task_readonly",
            return_value=(self.output_binding.execution_id, second_execution),
        ), patch(
            "origin_forge.conversation_blender_task_acceptance_actions._exact_view"
        ) as exact_view:
            projected = project_conversation_blender_task_acceptance_actions_readonly(
                self.runtime, live_state
            )
        exact_view.assert_not_called()
        self.assertEqual(len(projected.actions), 1)
        action = projected.actions[0]
        self.assertIsNone(action.execution_id)
        self.assertIs(
            action.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        self.assertFalse(action.acceptance_eligible)
        self.assertFalse(action.accepted)
        self.assertIsNone(action.adopted_artifact_id)
        self.assertIsNone(action.adopted_destination_path)
        self.assertIn("Multiple Blender production executions", action.detail or "")

    def test_current_glb_drift_is_visible_only_as_non_actionable_conflict(self) -> None:
        _session, live_state = self._conversation_live_state()
        destination = self.runtime.project_root / self.adoption.destination_path
        destination.write_bytes(destination.read_bytes() + b"drift")

        projected = project_conversation_blender_task_acceptance_actions_readonly(
            self.runtime, live_state
        )
        self.assertEqual(len(projected.actions), 1)
        action = projected.actions[0]
        self.assertEqual(action.execution_id, self.output_binding.execution_id)
        self.assertIs(
            action.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        self.assertFalse(action.acceptance_eligible)
        self.assertFalse(action.accepted)
        self.assertIsNone(action.adopted_destination_path)
        self.assertIsNone(action.accepted_content_hash)
        self.assertIsNone(action.accepted_byte_count)

    def test_projection_rejects_cross_project_conversation_state(self) -> None:
        _session, live_state = self._conversation_live_state()
        other_tempdir = tempfile.TemporaryDirectory()
        try:
            other = OriginForgeRuntime(Path(other_tempdir.name))
            other.initialize("other-gui-action-project")
            with self.assertRaises(ConversationBlenderTaskAcceptanceActionError):
                project_conversation_blender_task_acceptance_actions_readonly(
                    other, live_state
                )
        finally:
            other_tempdir.cleanup()

    def test_workspace_renders_status_only_and_adds_no_acceptance_post_surface(self) -> None:
        _session, _live_state = self._conversation_live_state()
        router = ProductionInterfaceRouter(self.runtime)
        counts_before = self._acceptance_counts()
        destination = self.runtime.project_root / self.adoption.destination_path
        bytes_before = destination.read_bytes()

        response = router.route("GET", "/")
        self.assertEqual(response.status, 200)
        page = response.body.decode("utf-8")
        self.assertIn("data-blender-acceptance-actions", page)
        self.assertIn(self.output_binding.task_id, page)
        self.assertIn(self.output_binding.execution_id, page)
        self.assertIn("NOT_ACCEPTED", page)
        self.assertIn(self.adoption.destination_path, page)
        self.assertIn(
            "Confirmation controls are intentionally unavailable in this read-only gate.",
            page,
        )
        action_markup = page.split("data-blender-acceptance-actions", 1)[1].split(
            "</section>", 1
        )[0]
        self.assertNotIn("<form", action_markup)
        self.assertNotIn("<button", action_markup)
        self.assertNotIn('method="post"', action_markup.lower())
        self.assertNotIn('action="', action_markup.lower())

        guessed_action_route = (
            f"/conversation/action/blender/{self.output_binding.execution_id}/accept"
        )
        self.assertEqual(router.route("POST", guessed_action_route).status, 405)
        self.assertEqual(self._acceptance_counts(), counts_before)
        self.assertEqual(destination.read_bytes(), bytes_before)


if __name__ == "__main__":
    unittest.main()
