from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from origin_forge.conversation_service import list_conversation_sessions, list_conversation_turns
from origin_forge.production_interface_server import (
    ProductionInterfaceRouter,
    create_production_interface_server,
)
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceGateDHTTPTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-gate-d-http-transport-test")
        router = ProductionInterfaceRouter(self.runtime)
        response = router.route(
            "POST",
            "/conversation/session",
            headers={
                "Host": "127.0.0.1:8765",
                "Origin": "http://127.0.0.1:8765",
            },
            body=b"",
        )
        self.assertEqual(response.status, 303)
        self.session = list_conversation_sessions(self.runtime)[0]
        self.server = create_production_interface_server(self.runtime, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tempdir.cleanup()

    def _body(self) -> bytes:
        return urlencode(
            {
                "content": "must not persist",
                "client_submission_id": "gate-d-framing-key",
                "expected_revision": "0",
            }
        ).encode("ascii")

    def _raw_post(self, *, body: bytes, content_lengths: tuple[int, ...]) -> bytes:
        port = self.server.server_port
        lines = [
            f"POST /conversation/{self.session.id}/turn HTTP/1.1",
            f"Host: 127.0.0.1:{port}",
            f"Origin: http://127.0.0.1:{port}",
            "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
            *(f"Content-Length: {length}" for length in content_lengths),
            "Connection: close",
            "",
            "",
        ]
        request = "\r\n".join(lines).encode("ascii") + body
        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        return b"".join(chunks)

    def test_truncated_body_is_rejected_before_router_submission(self) -> None:
        body = self._body()
        response = self._raw_post(body=body, content_lengths=(len(body) + 1,))

        self.assertTrue(response.startswith(b"HTTP/1.1 400 "))
        self.assertIn(b"incomplete request body\n", response)
        self.assertEqual(list_conversation_turns(self.runtime, self.session.id), ())

    def test_duplicate_content_length_is_rejected_before_body_read(self) -> None:
        body = self._body()
        response = self._raw_post(
            body=body,
            content_lengths=(len(body), len(body)),
        )

        self.assertTrue(response.startswith(b"HTTP/1.1 400 "))
        self.assertIn(b"invalid content length\n", response)
        self.assertEqual(list_conversation_turns(self.runtime, self.session.id), ())


if __name__ == "__main__":
    unittest.main()
