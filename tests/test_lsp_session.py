from __future__ import annotations

import os
import threading
import unittest

from origin_forge.lsp_protocol import encode_lsp_message, read_lsp_message
from origin_forge.lsp_session import (
    LspJsonRpcSession,
    LspProtocolError,
    LspRemoteError,
    LspRequestTimeout,
)


class _PipePair:
    def __init__(self) -> None:
        client_to_server_read, client_to_server_write = os.pipe()
        server_to_client_read, server_to_client_write = os.pipe()
        self.client_reader = os.fdopen(server_to_client_read, "rb", buffering=0)
        self.client_writer = os.fdopen(client_to_server_write, "wb", buffering=0)
        self.server_reader = os.fdopen(client_to_server_read, "rb", buffering=0)
        self.server_writer = os.fdopen(server_to_client_write, "wb", buffering=0)

    def close(self) -> None:
        for stream in (
            self.client_reader,
            self.client_writer,
            self.server_reader,
            self.server_writer,
        ):
            try:
                stream.close()
            except OSError:
                pass


class LspSessionTests(unittest.TestCase):
    def test_request_correlates_response_and_buffers_notification(self) -> None:
        pipes = _PipePair()
        session = LspJsonRpcSession(pipes.client_reader, pipes.client_writer)

        def server() -> None:
            request = read_lsp_message(pipes.server_reader)
            pipes.server_writer.write(
                encode_lsp_message(
                    {
                        "jsonrpc": "2.0",
                        "method": "textDocument/publishDiagnostics",
                        "params": {"uri": "file:///workspace/a.py", "diagnostics": []},
                    }
                )
            )
            pipes.server_writer.write(
                encode_lsp_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": {"ok": True},
                    }
                )
            )
            pipes.server_writer.flush()

        thread = threading.Thread(target=server)
        thread.start()
        try:
            result = session.request("workspace/symbol", {"query": "Widget"})
            self.assertEqual(result, {"ok": True})
            notifications = session.take_notifications()
            self.assertEqual(len(notifications), 1)
            self.assertEqual(
                notifications[0].method,
                "textDocument/publishDiagnostics",
            )
        finally:
            session.close()
            pipes.close()
            thread.join(timeout=1)

    def test_remote_error_is_normalized(self) -> None:
        pipes = _PipePair()
        session = LspJsonRpcSession(pipes.client_reader, pipes.client_writer)

        def server() -> None:
            request = read_lsp_message(pipes.server_reader)
            pipes.server_writer.write(
                encode_lsp_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "error": {
                            "code": -32001,
                            "message": "server failed",
                            "data": {"detail": "x"},
                        },
                    }
                )
            )
            pipes.server_writer.flush()

        thread = threading.Thread(target=server)
        thread.start()
        try:
            with self.assertRaises(LspRemoteError) as raised:
                session.request("textDocument/definition", {})
            self.assertEqual(raised.exception.code, -32001)
            self.assertEqual(raised.exception.data, {"detail": "x"})
        finally:
            session.close()
            pipes.close()
            thread.join(timeout=1)

    def test_server_request_is_rejected_before_client_response_continues(self) -> None:
        pipes = _PipePair()
        session = LspJsonRpcSession(pipes.client_reader, pipes.client_writer)
        observed: list[dict] = []

        def server() -> None:
            request = read_lsp_message(pipes.server_reader)
            pipes.server_writer.write(
                encode_lsp_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 99,
                        "method": "workspace/configuration",
                        "params": {"items": []},
                    }
                )
            )
            pipes.server_writer.flush()
            observed.append(read_lsp_message(pipes.server_reader))
            pipes.server_writer.write(
                encode_lsp_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": [],
                    }
                )
            )
            pipes.server_writer.flush()

        thread = threading.Thread(target=server)
        thread.start()
        try:
            self.assertEqual(session.request("workspace/symbol", {"query": ""}), [])
            self.assertEqual(observed[0]["id"], 99)
            self.assertEqual(observed[0]["error"]["code"], -32601)
        finally:
            session.close()
            pipes.close()
            thread.join(timeout=1)

    def test_request_timeout_is_bounded(self) -> None:
        pipes = _PipePair()
        session = LspJsonRpcSession(pipes.client_reader, pipes.client_writer)
        try:
            with self.assertRaises(LspRequestTimeout):
                session.request("workspace/symbol", {"query": ""}, timeout_seconds=0.02)
        finally:
            session.close()
            pipes.close()

    def test_notification_limit_fails_closed(self) -> None:
        pipes = _PipePair()
        session = LspJsonRpcSession(
            pipes.client_reader,
            pipes.client_writer,
            max_pending_notifications=1,
        )

        def server() -> None:
            read_lsp_message(pipes.server_reader)
            for index in range(2):
                pipes.server_writer.write(
                    encode_lsp_message(
                        {
                            "jsonrpc": "2.0",
                            "method": "window/logMessage",
                            "params": {"message": str(index)},
                        }
                    )
                )
            pipes.server_writer.flush()

        thread = threading.Thread(target=server)
        thread.start()
        try:
            with self.assertRaisesRegex(
                LspProtocolError,
                "pending notification limit",
            ):
                session.request("workspace/symbol", {"query": ""})
        finally:
            session.close()
            pipes.close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
