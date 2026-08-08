from __future__ import annotations

import json
from enum import StrEnum
from typing import BinaryIO


class LspProtocolError(RuntimeError):
    pass


class LspMessageTooLarge(LspProtocolError):
    pass


class LspPositionEncoding(StrEnum):
    UTF8 = "utf-8"
    UTF16 = "utf-16"
    UTF32 = "utf-32"


DEFAULT_MAX_HEADER_BYTES = 16 * 1024
DEFAULT_MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def encode_lsp_message(
    payload: dict,
    *,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> bytes:
    if max_message_bytes <= 0:
        raise ValueError("max_message_bytes must be positive")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > max_message_bytes:
        raise LspMessageTooLarge(
            f"LSP message exceeds limit ({len(body)} > {max_message_bytes} bytes)"
        )
    header = (
        f"Content-Length: {len(body)}\r\n"
        "Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
        "\r\n"
    ).encode("ascii")
    return header + body


def read_lsp_message(
    stream: BinaryIO,
    *,
    max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> dict:
    if max_header_bytes <= 0 or max_message_bytes <= 0:
        raise ValueError("LSP message limits must be positive")

    headers: dict[str, str] = {}
    header_bytes = 0
    while True:
        line = stream.readline(max_header_bytes + 1)
        if not line:
            raise EOFError("LSP stream ended before a complete header")
        header_bytes += len(line)
        if header_bytes > max_header_bytes:
            raise LspMessageTooLarge(
                f"LSP header exceeds limit ({header_bytes} > {max_header_bytes} bytes)"
            )
        if line in {b"\r\n", b"\n"}:
            break
        try:
            text = line.decode("ascii")
        except UnicodeDecodeError as exc:
            raise LspProtocolError("LSP header must be ASCII") from exc
        if not text.endswith(("\r\n", "\n")):
            raise LspProtocolError("unterminated LSP header line")
        text = text.rstrip("\r\n")
        if ":" not in text:
            raise LspProtocolError(f"malformed LSP header line: {text!r}")
        name, value = text.split(":", 1)
        key = name.strip().casefold()
        if not key:
            raise LspProtocolError("empty LSP header name")
        if key in headers:
            raise LspProtocolError(f"duplicate LSP header: {name.strip()}")
        headers[key] = value.strip()

    raw_length = headers.get("content-length")
    if raw_length is None:
        raise LspProtocolError("LSP message is missing Content-Length")
    try:
        content_length = int(raw_length, 10)
    except ValueError as exc:
        raise LspProtocolError("LSP Content-Length must be an integer") from exc
    if content_length < 0:
        raise LspProtocolError("LSP Content-Length must be non-negative")
    if content_length > max_message_bytes:
        raise LspMessageTooLarge(
            f"LSP message exceeds limit ({content_length} > {max_message_bytes} bytes)"
        )

    content_type = headers.get("content-type")
    if content_type is not None:
        normalized = content_type.casefold().replace("utf8", "utf-8")
        if "charset=" in normalized and "charset=utf-8" not in normalized:
            raise LspProtocolError("Origin Forge only accepts UTF-8 LSP content")

    body = stream.read(content_length)
    if len(body) != content_length:
        raise EOFError(
            f"LSP stream ended early ({len(body)} of {content_length} content bytes)"
        )
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LspProtocolError("invalid UTF-8 JSON LSP content") from exc
    if not isinstance(value, dict):
        raise LspProtocolError("LSP JSON-RPC message must be an object")
    return value


def codepoint_to_lsp_character(
    line: str,
    character: int,
    encoding: LspPositionEncoding,
) -> int:
    if character < 0 or character > len(line):
        raise ValueError("codepoint character offset is outside the line")
    prefix = line[:character]
    if encoding == LspPositionEncoding.UTF8:
        return len(prefix.encode("utf-8"))
    if encoding == LspPositionEncoding.UTF16:
        return len(prefix.encode("utf-16-le")) // 2
    if encoding == LspPositionEncoding.UTF32:
        return len(prefix.encode("utf-32-le")) // 4
    raise ValueError(f"unsupported LSP position encoding: {encoding}")


def lsp_character_to_codepoint(
    line: str,
    character: int,
    encoding: LspPositionEncoding,
) -> int:
    if character < 0:
        raise ValueError("LSP character offset must be non-negative")

    if encoding == LspPositionEncoding.UTF8:
        encoded = line.encode("utf-8")
        if character > len(encoded):
            raise ValueError("LSP UTF-8 character offset is outside the line")
        raw = encoded[:character]
        decoder = "utf-8"
        unit = 1
    elif encoding == LspPositionEncoding.UTF16:
        encoded = line.encode("utf-16-le")
        if character * 2 > len(encoded):
            raise ValueError("LSP UTF-16 character offset is outside the line")
        raw = encoded[: character * 2]
        decoder = "utf-16-le"
        unit = 2
    elif encoding == LspPositionEncoding.UTF32:
        encoded = line.encode("utf-32-le")
        if character * 4 > len(encoded):
            raise ValueError("LSP UTF-32 character offset is outside the line")
        raw = encoded[: character * 4]
        decoder = "utf-32-le"
        unit = 4
    else:
        raise ValueError(f"unsupported LSP position encoding: {encoding}")

    try:
        prefix = raw.decode(decoder)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"LSP {encoding.value} character offset splits a Unicode code point"
        ) from exc
    if len(raw) % unit:
        raise ValueError(f"invalid {encoding.value} code-unit boundary")
    return len(prefix)
