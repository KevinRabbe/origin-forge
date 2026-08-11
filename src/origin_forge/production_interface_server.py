from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from .ids import IdKind, validate_id
from .production_interface_html import (
    ProductionInterfaceRenderError,
    render_detail,
    render_overview,
)
from .production_interface_snapshot import build_production_interface_snapshot
from .runtime import OriginForgeRuntime


_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
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


class ProductionInterfaceRouter:
    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    @staticmethod
    def _response(
        status: int, content_type: str, body: bytes
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
            ProductionInterfaceRouter._security_headers(),
        )

    @staticmethod
    def _security_headers() -> tuple[tuple[str, str], ...]:
        return (
            ("Cache-Control", "no-store"),
            (
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'",
            ),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
        )

    def route(self, method: str, target: str) -> ProductionInterfaceResponse:
        if method != "GET":
            return self._response(
                405, "text/plain; charset=utf-8", b"method not allowed\n"
            )
        if not isinstance(target, str) or not target.startswith("/"):
            return self._response(
                400, "text/plain; charset=utf-8", b"invalid request target\n"
            )
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            return self._response(
                400,
                "text/plain; charset=utf-8",
                b"query, fragment and absolute targets are forbidden\n",
            )
        path = parsed.path
        if path == "/healthz":
            return self._response(200, "text/plain; charset=utf-8", b"ok\n")

        try:
            snapshot = build_production_interface_snapshot(
                self.runtime, **_SERVER_SNAPSHOT_LIMITS
            )
        except (KeyError, RuntimeError, TypeError, ValueError, OSError):
            return self._response(
                500, "text/plain; charset=utf-8", b"snapshot unavailable\n"
            )

        if path == "/":
            try:
                body = render_overview(snapshot).encode("utf-8")
            except ProductionInterfaceRenderError:
                return self._response(
                    500,
                    "text/plain; charset=utf-8",
                    b"rendered page exceeds interface byte limit\n",
                )
            return self._response(200, "text/html; charset=utf-8", body)
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
        return self._response(200, "text/html; charset=utf-8", page.encode("utf-8"))


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

        def _dispatch(self, method: str) -> None:
            response = router.route(method, self.path)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for key, value in response.headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return _InterfaceHTTPServer(("127.0.0.1", port), Handler)
