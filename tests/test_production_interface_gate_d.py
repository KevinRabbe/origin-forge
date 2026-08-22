from __future__ import annotations

import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from origin_forge.conversation_service import (
    ConversationActorType,
    ConversationSubmissionStatus,
    list_conversation_sessions,
    list_conversation_turns,
    read_conversation_submission,
)
from origin_forge.ids import IdKind, new_id
from origin_forge.production_interface_server import (
    ProductionInterfaceRouter,
    create_production_interface_server,
)
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceGateDTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-gate-d-test")
        self.router = ProductionInterfaceRouter(self.runtime)
        self.headers = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _form_fields(page: str) -> tuple[str, int]:
        key_match = re.search(
            r'name="client_submission_id" value="([^"]+)"',
            page,
        )
        revision_match = re.search(
            r'name="expected_revision" value="([0-9]+)"',
            page,
        )
        if key_match is None or revision_match is None:
            raise AssertionError("conversation form fields are missing")
        return key_match.group(1), int(revision_match.group(1))

    @staticmethod
    def _encoded_form(
        *,
        content: str,
        client_submission_id: str,
        expected_revision: int,
        extra: tuple[tuple[str, str], ...] = (),
    ) -> bytes:
        values = [
            ("content", content),
            ("client_submission_id", client_submission_id),
            ("expected_revision", str(expected_revision)),
            *extra,
        ]
        return urlencode(values).encode("ascii")

    def _turn_headers(self) -> dict[str, str]:
        return {
            **self.headers,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

    def test_server_workspace_starts_and_renders_durable_conversation(self) -> None:
        before = build_production_interface_snapshot(self.runtime).total_counts

        initial = self.router.route("GET", "/")
        self.assertEqual(initial.status, 200)
        initial_page = initial.body.decode("utf-8")
        self.assertIn('action="/conversation/session"', initial_page)
        self.assertIn(">Start conversation</button>", initial_page)
        csp = dict(initial.headers)["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("form-action 'self'", csp)
        self.assertNotIn("form-action 'none'", csp)

        started = self.router.route(
            "POST",
            "/conversation/session",
            headers=self.headers,
            body=b"",
        )
        self.assertEqual(started.status, 303)
        self.assertEqual(dict(started.headers)["Location"], "/#workspace")
        sessions = list_conversation_sessions(self.runtime)
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.revision, 0)

        page_response = self.router.route("GET", "/")
        self.assertEqual(page_response.status, 200)
        page = page_response.body.decode("utf-8")
        self.assertIn(f'action="/conversation/{session.id}/turn"', page)
        self.assertIn(f"Session <code>{session.id}</code>", page)
        key, revision = self._form_fields(page)
        self.assertEqual(revision, 0)

        hostile = '<script>alert("x")</script> café\nnext'
        body = self._encoded_form(
            content=hostile,
            client_submission_id=key,
            expected_revision=revision,
        )
        accepted = self.router.route(
            "POST",
            f"/conversation/{session.id}/turn",
            headers=self._turn_headers(),
            body=body,
        )
        self.assertEqual(accepted.status, 303)

        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual(len(turns), 1)
        self.assertIs(turns[0].actor_type, ConversationActorType.HUMAN)
        self.assertEqual(turns[0].content, hostile)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT id FROM conversation_submissions WHERE session_id = ?",
                (session.id,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        receipt = read_conversation_submission(self.runtime, rows[0]["id"])
        self.assertIs(receipt.status, ConversationSubmissionStatus.ACCEPTED)

        after = build_production_interface_snapshot(self.runtime).total_counts
        self.assertEqual(after, before)

        rendered = self.router.route("GET", "/").body.decode("utf-8")
        self.assertNotIn(hostile, rendered)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; café", rendered)
        self.assertIn("durable human intent only", rendered.lower())

    def test_turn_submission_is_idempotent_before_stale_revision_rejection(self) -> None:
        self.assertEqual(
            self.router.route(
                "POST",
                "/conversation/session",
                headers=self.headers,
                body=b"",
            ).status,
            303,
        )
        session = list_conversation_sessions(self.runtime)[0]
        page = self.router.route("GET", "/").body.decode("utf-8")
        key, revision = self._form_fields(page)
        body = self._encoded_form(
            content="change the project",
            client_submission_id=key,
            expected_revision=revision,
        )
        path = f"/conversation/{session.id}/turn"
        headers = self._turn_headers()

        first = self.router.route("POST", path, headers=headers, body=body)
        replay = self.router.route("POST", path, headers=headers, body=body)
        self.assertEqual(first.status, 303)
        self.assertEqual(replay.status, 303)
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)

        changed_same_key = self._encoded_form(
            content="different content",
            client_submission_id=key,
            expected_revision=revision,
        )
        self.assertEqual(
            self.router.route(
                "POST",
                path,
                headers=headers,
                body=changed_same_key,
            ).status,
            409,
        )
        stale_new_key = self._encoded_form(
            content="fresh intent",
            client_submission_id="gate-d-fresh-key",
            expected_revision=revision,
        )
        self.assertEqual(
            self.router.route(
                "POST",
                path,
                headers=headers,
                body=stale_new_key,
            ).status,
            409,
        )
        self.assertEqual(len(list_conversation_turns(self.runtime, session.id)), 1)

    def test_post_transport_and_form_validation_fail_closed(self) -> None:
        self.assertEqual(self.router.route("POST", "/").status, 405)
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(self.router.route(method, "/conversation/session").status, 405)

        started = self.router.route(
            "POST",
            "/conversation/session",
            headers=self.headers,
            body=b"",
        )
        self.assertEqual(started.status, 303)
        session = list_conversation_sessions(self.runtime)[0]
        path = f"/conversation/{session.id}/turn"
        valid_body = self._encoded_form(
            content="hello",
            client_submission_id="gate-d-key",
            expected_revision=0,
        )

        self.assertEqual(
            self.router.route("POST", path, headers={}, body=valid_body).status,
            403,
        )
        self.assertEqual(
            self.router.route(
                "POST",
                path,
                headers={
                    "Host": "127.0.0.1:8765",
                    "Origin": "http://example.com",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body=valid_body,
            ).status,
            403,
        )
        self.assertEqual(
            self.router.route(
                "POST",
                path,
                headers=self.headers,
                body=valid_body,
            ).status,
            415,
        )
        self.assertEqual(
            self.router.route(
                "POST",
                path,
                headers=self._turn_headers(),
                body=b"x" * (256 * 1024 + 1),
            ).status,
            413,
        )
        malformed = self._encoded_form(
            content="hello",
            client_submission_id="gate-d-key",
            expected_revision=0,
            extra=(("unexpected", "value"),),
        )
        self.assertEqual(
            self.router.route(
                "POST",
                path,
                headers=self._turn_headers(),
                body=malformed,
            ).status,
            400,
        )

        unknown = new_id(IdKind.CONVERSATION_SESSION)
        self.assertEqual(
            self.router.route(
                "POST",
                f"/conversation/{unknown}/turn",
                headers=self._turn_headers(),
                body=valid_body,
            ).status,
            404,
        )

    def test_real_loopback_server_accepts_only_bounded_same_origin_conversation_post(self) -> None:
        server = create_production_interface_server(self.runtime, port=0)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            connection.request(
                "POST",
                "/conversation/session",
                body=b"",
                headers={"Origin": origin},
            )
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 303)
            connection.close()

            session = list_conversation_sessions(self.runtime)[0]
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            connection.request("GET", "/")
            response = connection.getresponse()
            page = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            key, revision = self._form_fields(page)
            connection.close()

            body = self._encoded_form(
                content="from browser transport",
                client_submission_id=key,
                expected_revision=revision,
            )
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            connection.request(
                "POST",
                f"/conversation/{session.id}/turn",
                body=body,
                headers={
                    "Origin": origin,
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
            )
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 303)
            connection.close()
            turns = list_conversation_turns(self.runtime, session.id)
            self.assertEqual(tuple(turn.content for turn in turns), ("from browser transport",))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
