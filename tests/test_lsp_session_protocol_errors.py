from __future__ import annotations

import io
import unittest

from origin_forge.lsp_protocol import LspProtocolError, encode_lsp_message
from origin_forge.lsp_session import LspJsonRpcSession


class LspSessionProtocolErrorTests(unittest.TestCase):
    def test_wrong_jsonrpc_version_is_terminal(self) -> None:
        reader = io.BytesIO(
            encode_lsp_message(
                {
                    "jsonrpc": "1.0",
                    "id": 1,
                    "result": None,
                }
            )
        )
        writer = io.BytesIO()
        session = LspJsonRpcSession(reader, writer)
        try:
            with self.assertRaisesRegex(LspProtocolError, "jsonrpc='2.0'"):
                session.request("workspace/symbol", {"query": ""}, timeout_seconds=1.0)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
