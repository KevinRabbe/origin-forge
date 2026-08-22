from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.conversation_live import read_conversation_live_state
from origin_forge.conversation_operations import (
    ConversationReferenceRelation,
    ConversationReferenceType,
    ensure_conversation_turn_reference,
)
from origin_forge.conversation_processing import (
    ConversationReadOnlyInspection,
    claim_conversation_submission,
    process_read_only_submission,
)
from origin_forge.conversation_service import (
    ConversationSubmissionStatus,
    create_conversation_session,
    list_conversation_turns,
    submit_human_turn,
)
from origin_forge.ids import IdKind, new_id
from origin_forge.production_interface_live import CONVERSATION_LIVE_SCRIPT
from origin_forge.production_interface_server import ProductionInterfaceRouter
from origin_forge.runs import finish_run
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus


class ProductionInterfaceGateELiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-gate-e-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _submission_with_referenced_task(self):
        session = create_conversation_session(self.runtime)
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            "inspect durable activity",
            "gate-e-submission",
            expected_revision=0,
        )

        goal_id = self.runtime.create_goal("gate-e goal")
        flow_id = self.runtime.create_flow(goal_id)
        task_id = self.runtime.create_task(flow_id, "gate-e task")
        self.runtime.transition_task(task_id, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task_id, TaskStatus.RUNNING, expected_revision=1)

        first_run = self.runtime.start_run(
            task_id,
            role="Executor",
            model_profile="local-test",
        )
        finish_run(
            self.runtime.store,
            first_run,
            RunStatus.SUCCEEDED,
            input_token_count=120,
            output_token_count=30,
        )
        second_run = self.runtime.start_run(
            task_id,
            role="Verifier",
            model_profile="local-test",
        )
        finish_run(
            self.runtime.store,
            second_run,
            RunStatus.SUCCEEDED,
            input_token_count=None,
            output_token_count=20,
        )
        ensure_conversation_turn_reference(
            self.runtime,
            receipt.human_turn_id,
            ConversationReferenceType.TASK,
            task_id,
            ConversationReferenceRelation.RESULT,
        )
        return session, receipt, task_id, first_run, second_run

    def test_live_projection_rebuilds_processing_turns_and_exact_run_tokens(self) -> None:
        session, receipt, task_id, first_run, second_run = (
            self._submission_with_referenced_task()
        )

        claimed = claim_conversation_submission(self.runtime, receipt.id)
        self.assertIs(claimed.status, ConversationSubmissionStatus.PROCESSING)
        processing = read_conversation_live_state(self.runtime, session.id)
        self.assertEqual(tuple(item.status for item in processing.submissions), (
            ConversationSubmissionStatus.PROCESSING,
        ))
        self.assertEqual(tuple(turn.content for turn in processing.turns), (
            "inspect durable activity",
        ))
        self.assertEqual(len(processing.task_telemetry), 1)
        task = processing.task_telemetry[0]
        self.assertEqual(task.task_id, task_id)
        self.assertEqual(task.total_run_count, 2)
        self.assertFalse(task.runs_truncated)
        self.assertEqual(tuple(run.id for run in task.runs), (first_run, second_run))
        self.assertEqual(task.reported_input_tokens, 120)
        self.assertEqual(task.reported_output_tokens, 50)
        self.assertEqual(task.reported_tokens, 170)
        self.assertEqual(task.fully_reported_runs, 1)
        self.assertEqual(task.missing_token_counters, 1)

        result = process_read_only_submission(
            self.runtime,
            receipt.id,
            ConversationReadOnlyInspection.PROJECT_COUNTS,
        )
        self.assertIs(result.submission.status, ConversationSubmissionStatus.RESPONDED)
        responded = read_conversation_live_state(self.runtime, session.id)
        self.assertEqual(responded.session.revision, 2)
        self.assertEqual(
            tuple(turn.actor_type.value for turn in responded.turns),
            ("HUMAN", "FORGE"),
        )
        self.assertEqual(
            tuple(item.status for item in responded.submissions),
            (ConversationSubmissionStatus.RESPONDED,),
        )
        self.assertEqual(responded.submissions[0].response_turn_id, result.response_turn.id)

    def test_live_run_window_is_bounded_without_imputing_missing_counters(self) -> None:
        session, _receipt, task_id, _first_run, second_run = (
            self._submission_with_referenced_task()
        )
        state = read_conversation_live_state(self.runtime, session.id, run_limit=1)
        self.assertEqual(len(state.task_telemetry), 1)
        task = state.task_telemetry[0]
        self.assertEqual(task.task_id, task_id)
        self.assertEqual(task.total_run_count, 2)
        self.assertEqual(len(task.runs), 1)
        self.assertTrue(task.runs_truncated)
        self.assertEqual(task.runs[0].id, second_run)
        self.assertIsNone(task.runs[0].input_token_count)
        self.assertEqual(task.runs[0].output_token_count, 20)
        self.assertEqual(task.reported_input_tokens, 0)
        self.assertEqual(task.reported_output_tokens, 20)
        self.assertEqual(task.missing_token_counters, 1)

    def test_live_state_is_project_scoped_and_reconnects_from_durable_records(self) -> None:
        session, receipt, _task_id, _first_run, _second_run = (
            self._submission_with_referenced_task()
        )
        before = read_conversation_live_state(self.runtime, session.id)
        restarted = OriginForgeRuntime(self.root)
        after = read_conversation_live_state(restarted, session.id)
        self.assertEqual(after.session, before.session)
        self.assertEqual(after.turns, before.turns)
        self.assertEqual(after.submissions, before.submissions)
        self.assertEqual(after.task_telemetry, before.task_telemetry)
        self.assertEqual(after.submissions[0].id, receipt.id)

        other_tempdir = tempfile.TemporaryDirectory()
        try:
            other = OriginForgeRuntime(Path(other_tempdir.name))
            other.initialize("other-project")
            with self.assertRaises(KeyError):
                read_conversation_live_state(other, session.id)
        finally:
            other_tempdir.cleanup()

    def test_live_http_surface_is_get_only_bounded_and_script_uses_safe_dom_updates(self) -> None:
        session, _receipt, _task_id, _first_run, _second_run = (
            self._submission_with_referenced_task()
        )
        router = ProductionInterfaceRouter(self.runtime)
        before_turns = list_conversation_turns(self.runtime, session.id)

        page_response = router.route("GET", "/")
        self.assertEqual(page_response.status, 200)
        page = page_response.body.decode("utf-8")
        self.assertIn(
            f'data-conversation-live-url="/api/conversation/live/{session.id}"',
            page,
        )
        self.assertIn('<script src="/assets/conversation-live.js" defer></script>', page)
        csp = dict(page_response.headers)["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("form-action 'self'", csp)
        self.assertNotIn("'unsafe-inline'", csp.split("script-src", 1)[1].split(";", 1)[0])

        script_response = router.route("GET", "/assets/conversation-live.js")
        self.assertEqual(script_response.status, 200)
        self.assertEqual(script_response.content_type, "application/javascript; charset=utf-8")
        script = script_response.body.decode("utf-8")
        self.assertEqual(script, CONVERSATION_LIVE_SCRIPT)
        self.assertIn('method: "GET"', script)
        self.assertIn("fetch(url", script)
        self.assertIn("replaceChildren", script)
        self.assertIn("textContent", script)
        for forbidden in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "WebSocket",
            "EventSource",
            'method: "POST"',
            "eval(",
            "new Function",
        ):
            self.assertNotIn(forbidden, script)

        endpoint = f"/api/conversation/live/{session.id}"
        first = router.route("GET", endpoint)
        second = router.route("GET", endpoint)
        self.assertEqual(first.status, 200)
        self.assertEqual(first.content_type, "application/json; charset=utf-8")
        payload = json.loads(first.body)
        replay = json.loads(second.body)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["session"]["id"], session.id)
        self.assertEqual(payload["content_hash"], replay["content_hash"])
        self.assertEqual(payload["task_telemetry"][0]["reported_tokens"], 170)

        self.assertEqual(router.route("POST", endpoint).status, 405)
        self.assertEqual(router.route("POST", "/assets/conversation-live.js").status, 405)
        unknown = new_id(IdKind.CONVERSATION_SESSION)
        self.assertEqual(
            router.route("GET", f"/api/conversation/live/{unknown}").status,
            404,
        )
        self.assertEqual(
            router.route("GET", "/api/conversation/live/not-a-conv-id").status,
            404,
        )
        self.assertEqual(list_conversation_turns(self.runtime, session.id), before_turns)


if __name__ == "__main__":
    unittest.main()
