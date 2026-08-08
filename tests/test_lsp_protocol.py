from __future__ import annotations

import io
import json
import unittest

from origin_forge.lsp_protocol import (
    LspMessageTooLarge,
    LspPositionEncoding,
    LspProtocolError,
    codepoint_to_lsp_character,
    encode_lsp_message,
    lsp_character_to_codepoint,
    read_lsp_message,
)


class LspProtocolTests(unittest.TestCase):
    def test_message_round_trip_uses_byte_content_length(self) -> None:
        payload = {"jsonrpc": "2.0", "id": 7, "result": {"label": "Grüße 🐈"}}
        encoded = encode_lsp_message(payload)
        header, body = encoded.split(b"\r\n\r\n", 1)
        content_length = next(
            line
            for line in header.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
        declared = int(content_length.split(b":", 1)[1].strip())
        self.assertEqual(declared, len(body))
        self.assertEqual(read_lsp_message(io.BytesIO(encoded)), payload)

    def test_missing_and_duplicate_content_length_are_rejected(self) -> None:
        missing = b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n\r\n{}"
        with self.assertRaisesRegex(LspProtocolError, "missing Content-Length"):
            read_lsp_message(io.BytesIO(missing))

        duplicate = b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}"
        with self.assertRaisesRegex(LspProtocolError, "duplicate"):
            read_lsp_message(io.BytesIO(duplicate))

    def test_message_size_limit_is_checked_before_body_read(self) -> None:
        with self.assertRaises(LspMessageTooLarge):
            read_lsp_message(
                io.BytesIO(b"Content-Length: 999\r\n\r\n"),
                max_message_bytes=16,
            )
        with self.assertRaises(LspMessageTooLarge):
            encode_lsp_message({"value": "x" * 100}, max_message_bytes=16)

    def test_non_utf8_content_type_is_rejected(self) -> None:
        body = json.dumps({"jsonrpc": "2.0"}).encode("utf-8")
        stream = io.BytesIO(
            f"Content-Length: {len(body)}\r\nContent-Type: application/vscode-jsonrpc; charset=utf-16\r\n\r\n".encode(
                "ascii"
            )
            + body
        )
        with self.assertRaisesRegex(LspProtocolError, "UTF-8"):
            read_lsp_message(stream)

    def test_position_conversion_handles_non_ascii_and_surrogate_pairs(self) -> None:
        line = "aé🐈z"
        cat_codepoint = 2
        self.assertEqual(
            codepoint_to_lsp_character(line, cat_codepoint, LspPositionEncoding.UTF8),
            len("aé".encode("utf-8")),
        )
        self.assertEqual(
            codepoint_to_lsp_character(line, cat_codepoint, LspPositionEncoding.UTF16),
            2,
        )
        after_cat = 3
        utf16_after_cat = codepoint_to_lsp_character(
            line, after_cat, LspPositionEncoding.UTF16
        )
        self.assertEqual(utf16_after_cat, 4)
        self.assertEqual(
            lsp_character_to_codepoint(
                line, utf16_after_cat, LspPositionEncoding.UTF16
            ),
            after_cat,
        )

    def test_position_conversion_rejects_split_unicode_units(self) -> None:
        line = "🐈"
        with self.assertRaisesRegex(ValueError, "splits a Unicode code point"):
            lsp_character_to_codepoint(line, 1, LspPositionEncoding.UTF16)
        with self.assertRaisesRegex(ValueError, "splits a Unicode code point"):
            lsp_character_to_codepoint(line, 1, LspPositionEncoding.UTF8)


if __name__ == "__main__":
    unittest.main()
