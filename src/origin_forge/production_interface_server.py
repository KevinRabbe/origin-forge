from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from .conversation_service import (
    DEFAULT_TURN_READ_LIMIT,
    ConversationConflict,
    ConversationError,
    ConversationSession,
    ConversationTurn,
    ConversationSessionStatus,
    create_conversation_session,
    list_conversation_sessions,
    list_conversation_turns,
    submit_human_turn,
)
from .ids import IdKind, validate_id
from .production_interface_conversation import decorate_conversation_workspace
from .production_interface_html import (
    ProductionInterfaceRenderError,
    render_detail,
    render_overview,
)
from .production_interface_snapshot import build_production_interface_snapshot
from .runtime import OriginForgeRuntime
from .service import StaleRevision


_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_REQUEST_BYTES = 256 * 1024
_CONVERSATION_TURN_LIMIT = min(48, DEFAULT_TURN_READ_LIMIT)
_SERVER_SNAPSHOT_LIMITS = {
    "max_goals": 16,
    "max_flows": 16,
    "max_tasks": 32,
    "max_runs": 32,
    "max_verifications": 32,
    "max_entities": 16,
    "max_entity_relations": 32,
    "max_entity_bindings": 32,
    "max_design_rules": 16,
    "max_decisions": 16,
    "max_changes": 16,
    "max_artifacts": 16,
    "max_artifact_verifications": 32,
    "max_provenance_manifests": 16,
    "max_dream_manifests": 16,
    "max_dream_candidates": 16,
    "max_dream_audits": 16,
    "max_memory_entries": 16,
    "max_memory_generations": 16,
}
_DETAIL_KINDS = {
    "goal": IdKind.GOAL,
    "flow": IdKind.FLOW,
    "task": IdKind.TASK,
    "run": IdKind.RUN,
    "verification": IdKind.VERIFICATION,
    "decision": IdKind.DECISION,
    "change": IdKind.CHANGE,
    "artifact": IdKind.ARTIFACT,
    "entity": IdKind.ENTITY,
    "rule": IdKind.DESIGN_RULE,
}


@dataclass(frozen=True)
class ProductionInterfaceResponse:
    status: int
    content_type: str
    body: bytes
    headers: tuple[tuple[str, str], ...]


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if headers is None:
        return None
    lowered = name.lower()
    matches = [
        value
        for key, value in headers.items()
        if isinstance(key, str) and key.lower() == lowered
    ]
    if len(matches) != 1 or not isinstance(matches[0], str):
        return None
    value = matches[0]
    if not value or value.strip() != value:
        return None
    return value


def _loopback_authority(value: str | None) -> tuple[str, int | None] | None:
    if value is None:
        return None
    try:
        parsed = urlsplit("//" + value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        return None
    hostname = parsed.hostname.lower()
    if hostname not in {"127.0.0.1", "localhost"}:
        return None
    if port is not None and not 1 <= port <= 65535:
        return None
    return hostname, port


def _same_origin_post(headers: Mapping[str, str] | None) -> bool:
    host = _loopback_authority(_header(headers, "Host"))
    origin_value = _header(headers, "Origin")
    if host is None or origin_value is None:
        return False
    try:
        origin = urlsplit(origin_value)
        origin_port = origin.port
    except ValueError:
        return False
    if (
        origin.scheme != "http"
        or origin.username is not None
        or origin.password is not None
        or origin.hostname is None
        or origin.path
        or origin.query
        or origin.fragment
    ):
        return False
    origin_host = origin.hostname.lower()
    if origin_host not in {"127.0.0.1", "localhost"}:
        return False
    return (origin_host, origin_port) == host


def _form_content_type_is_utf8(headers: Mapping[str, str] | None) -> bool:
    value = _header(headers, "Content-Type")
    if value is None:
        return False
    parts = [part.strip() for part in value.split(";")]
    if parts[0].lower() != "application/x-www-form-urlencoded":
        return False
    for parameter in parts[1:]:
        if parameter.lower() != "charset=utf-8":
            return False
    return True


def _form_text(body: bytes) -> str:
    if len(body) > _MAX_REQUEST_BYTES:
        raise OverflowError("request body exceeds byte limit")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("form body must use ASCII percent encoding") from exc
    hex_bytes = frozenset("0123456789abcdefABCDEF")
    index = 0
    while True:
        index = text.find("%", index)
        if index < 0:
            break
        if (
            index + 2 >= len(text)
            or text[index + 1] not in hex_bytes
            or text[index + 2] not in hex_bytes
        ):
            raise ValueError("form body contains invalid percent encoding")
        index += 3
    return text


def _parse_turn_form(body: bytes) -> tuple[str, str, int]:
    text = _form_text(body)
    try:
        fields = parse_qs(
            text,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=3,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid conversation submission form") from exc
    expected_fields = {"content", "client_submission_id", "expected_revision"}
    if set(fields) != expected_fields or any(len(values) != 1 for values in fields.values()):
        raise ValueError("conversation submission form fields are invalid")
    content = fields["content"][0]
    client_submission_id = fields["client_submission_id"][0]
    revision_text = fields["expected_revision"][0]
    if (
        not revision_text
        or any(character not in "0123456789" for character in revision_text)
        or (len(revision_text) > 1 and revision_text.startswith("0"))
    ):
        raise ValueError("expected_revision must be canonical decimal text")
    expected_revision = int(revision_text)
    if expected_revision > 9_223_372_036_854_775_807:
        raise ValueError("expected_revision exceeds SQLite integer range")
    if any(
        ord(character) < 0x20 and character not in "\t\n\r"
        for character in content
    ):
        raise ValueError("content contains forbidden control characters")
    return content, client_submission_id, expected_revision


def _conversation_turn_session_id(path: str) -> str | None:
    parts = path.split("/")
    if (
        len(parts) != 4
        or parts[0] != ""
        or parts[1] != "conversation"
        or parts[3] != "turn"
        or not validate_id(parts[2], IdKind.CONVERSATION_SESSION)
    ):
        return None
    return parts[2]


class ProductionInterfaceRouter:
    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    @staticmethod
    def _response(
        status: int,
        content_type: str,
        body: bytes,
        *,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> ProductionInterfaceResponse:
        if len(body) > _MAX_RESPONSE_BYTES:
            return ProductionInterfaceResponse(
                500,
                "text/plain; charset=utf-8",
                b"response exceeds interface byte limit\n",
                ProductionInterfaceRouter._security_headers(),
            )
        return ProductionInterfaceResponse(
            status,
            content_type,
            body,
            ProductionInterfaceRouter._security_headers() + extra_headers,
        )

    @staticmethod
    def _security_headers() -> tuple[tuple[str, str], ...]:
        return (
            ("Cache-Control", "no-store"),
            (
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; connect-src 'none'; frame-src 'none'; form-action 'self'; base-uri 'none'; object-src 'none'",
            ),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
        )

    @classmethod
    def _redirect_to_workspace(cls) -> ProductionInterfaceResponse:
        return cls._response(
            303,
            "text/plain; charset=utf-8",
            b"see other\n",
            extra_headers=(("Location", "/#workspace"),),
        )

    def _selected_conversation(
        self,
    ) -> tuple[ConversationSession | None, tuple[ConversationTurn, ...]]:
        sessions = list_conversation_sessions(self.runtime, limit=16)
        if not sessions:
            return None, ()
        selected = next(
            (
                session
                for session in sessions
                if session.status is ConversationSessionStatus.OPEN
            ),
            sessions[0],
        )
        after_sequence = max(0, selected.revision - _CONVERSATION_TURN_LIMIT)
        turns = list_conversation_turns(
            self.runtime,
            selected.id,
            after_sequence=after_sequence,
            limit=_CONVERSATION_TURN_LIMIT,
        )
        return selected, turns

    def _render_overview(self, snapshot) -> ProductionInterfaceResponse:
        try:
            page = render_overview(snapshot)
            session, turns = self._selected_conversation()
            client_submission_id = (
                secrets.token_urlsafe(24)
                if session is not None
                and session.status is ConversationSessionStatus.OPEN
                else None
            )
            page = decorate_conversation_workspace(
                page,
                session=session,
                turns=turns,
                client_submission_id=client_submission_id,
            )
        except ProductionInterfaceRenderError:
            return self._response(
                500,
                "text/plain; charset=utf-8",
                b"rendered page exceeds interface byte limit\n",
            )
        except (ConversationError, KeyError, TypeError, ValueError, OSError):
            return self._response(
                500,
                "text/plain; charset=utf-8",
                b"conversation workspace unavailable\n",
            )
        return self._response(
            200,
            "text/html; charset=utf-8",
            page.encode("utf-8"),
        )

    def _route_post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None,
        body: bytes,
    ) -> ProductionInterfaceResponse:
        session_id = None
        if path != "/conversation/session":
            session_id = _conversation_turn_session_id(path)
            if session_id is None:
                return self._response(
                    405,
                    "text/plain; charset=utf-8",
                    b"method not allowed\n",
                )
        if not isinstance(body, bytes):
            return self._response(
                400,
                "text/plain; charset=utf-8",
                b"invalid request body\n",
            )
        if not _same_origin_post(headers):
            return self._response(
                403,
                "text/plain; charset=utf-8",
                b"forbidden origin\n",
            )
        if len(body) > _MAX_REQUEST_BYTES:
            return self._response(
                413,
                "text/plain; charset=utf-8",
                b"request body exceeds interface byte limit\n",
            )
        if path == "/conversation/session":
            if body:
                return self._response(
                    400,
                    "text/plain; charset=utf-8",
                    b"conversation session request must be empty\n",
                )
            try:
                create_conversation_session(self.runtime)
            except (ConversationError, TypeError, ValueError, OSError):
                return self._response(
                    500,
                    "text/plain; charset=utf-8",
                    b"conversation session unavailable\n",
                )
            return self._redirect_to_workspace()

        if session_id is None:
            raise AssertionError("conversation turn route lost validated session id")
        if not _form_content_type_is_utf8(headers):
            return self._response(
                415,
                "text/plain; charset=utf-8",
                b"unsupported media type\n",
            )
        try:
            content, client_submission_id, expected_revision = _parse_turn_form(body)
            submit_human_turn(
                self.runtime,
                session_id,
                content,
                client_submission_id,
                expected_revision=expected_revision,
            )
        except KeyError:
            return self._response(
                404,
                "text/plain; charset=utf-8",
                b"conversation session not found\n",
            )
        except (ConversationConflict, StaleRevision):
            return self._response(
                409,
                "text/plain; charset=utf-8",
                b"conversation submission conflict\n",
            )
        except (TypeError, ValueError):
            return self._response(
                400,
                "text/plain; charset=utf-8",
                b"invalid conversation submission\n",
            )
        except (ConversationError, OSError):
            return self._response(
                500,
                "text/plain; charset=utf-8",
                b"conversation submission unavailable\n",
            )
        return self._redirect_to_workspace()

    def route(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> ProductionInterfaceResponse:
        if not isinstance(target, str) or not target.startswith("/"):
            return self._response(
                400,
                "text/plain; charset=utf-8",
                b"invalid request target\n",
            )
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            return self._response(
                400,
                "text/plain; charset=utf-8",
                b"query, fragment and absolute targets are forbidden\n",
            )
        path = parsed.path

        if method == "POST":
            return self._route_post(path, headers=headers, body=body)
        if method != "GET":
            return self._response(
                405,
                "text/plain; charset=utf-8",
                b"method not allowed\n",
            )
        if path == "/healthz":
            return self._response(200, "text/plain; charset=utf-8", b"ok\n")

        try:
            snapshot = build_production_interface_snapshot(
                self.runtime, **_SERVER_SNAPSHOT_LIMITS
            )
        except (KeyError, RuntimeError, TypeError, ValueError, OSError):
            return self._response(
                500,
                "text/plain; charset=utf-8",
                b"snapshot unavailable\n",
            )

        if path == "/":
            return self._render_overview(snapshot)
        if path == "/api/snapshot":
            payload = dict(snapshot.to_dict())
            payload["content_hash"] = snapshot.content_hash
            return self._response(
                200,
                "application/json; charset=utf-8",
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8"),
            )

        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "" or not parts[1] or not parts[2]:
            return self._response(404, "text/plain; charset=utf-8", b"not found\n")
        kind, object_id = parts[1], parts[2]
        id_kind = _DETAIL_KINDS.get(kind)
        if id_kind is None or not validate_id(object_id, id_kind):
            return self._response(404, "text/plain; charset=utf-8", b"not found\n")
        try:
            page = render_detail(snapshot, kind, object_id)
        except KeyError:
            return self._response(404, "text/plain; charset=utf-8", b"not found\n")
        except ProductionInterfaceRenderError:
            return self._response(
                500,
                "text/plain; charset=utf-8",
                b"rendered page exceeds interface byte limit\n",
            )
        return self._response(
            200,
            "text/html; charset=utf-8",
            page.encode("utf-8"),
        )


class _InterfaceHTTPServer(HTTPServer):
    allow_reuse_address = False


def create_production_interface_server(
    runtime: OriginForgeRuntime, *, port: int = 0
) -> HTTPServer:
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be an integer from 0 to 65535")
    router = ProductionInterfaceRouter(runtime)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._dispatch("PUT")

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch("DELETE")

        def _send(self, response: ProductionInterfaceResponse) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for key, value in response.headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response.body)

        def _dispatch(self, method: str) -> None:
            body = b""
            if method == "POST":
                transfer_encoding = self.headers.get("Transfer-Encoding")
                content_length = self.headers.get("Content-Length")
                if transfer_encoding is not None or content_length is None:
                    self.close_connection = True
                    self._send(
                        router._response(
                            411,
                            "text/plain; charset=utf-8",
                            b"content length required\n",
                        )
                    )
                    return
                if not content_length.isascii() or not content_length.isdecimal():
                    self.close_connection = True
                    self._send(
                        router._response(
                            400,
                            "text/plain; charset=utf-8",
                            b"invalid content length\n",
                        )
                    )
                    return
                body_length = int(content_length)
                if body_length > _MAX_REQUEST_BYTES:
                    self.close_connection = True
                    self._send(
                        router._response(
                            413,
                            "text/plain; charset=utf-8",
                            b"request body exceeds interface byte limit\n",
                        )
                    )
                    return
                body = self.rfile.read(body_length)

            response = router.route(
                method,
                self.path,
                headers=self.headers,
                body=body,
            )
            self._send(response)

        def log_message(self, format: str, *args: object) -> None:
            return

    return _InterfaceHTTPServer(("127.0.0.1", port), Handler)
