from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote, unquote, urlparse

from .lsp_protocol import LspPositionEncoding, LspProtocolError
from .path_policy import portable_relative_path


class LspWorkspaceError(LspProtocolError):
    pass


class LspInitializationError(LspProtocolError):
    pass


class LspRequestSession(Protocol):
    def request(
        self,
        method: str,
        params: object | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> object | None: ...

    def notify(self, method: str, params: object | None = None) -> None: ...


@dataclass(frozen=True)
class LspServerCapabilities:
    position_encoding: LspPositionEncoding
    workspace_symbols: bool
    definitions: bool
    references: bool
    diagnostics: bool


def _local_netloc(value: str) -> str:
    folded = value.casefold()
    if folded in {"", "localhost"}:
        return ""
    raise LspWorkspaceError("remote-host file URIs are not allowed")


def _parse_file_uri(uri: str) -> tuple[str, PurePosixPath]:
    parsed = urlparse(uri)
    if parsed.scheme.casefold() != "file":
        raise LspWorkspaceError(
            f"unsupported LSP location URI scheme: {parsed.scheme or '<none>'}"
        )
    netloc = _local_netloc(parsed.netloc)
    if parsed.params or parsed.query or parsed.fragment:
        raise LspWorkspaceError("LSP file URI may not contain params, query, or fragment")
    try:
        decoded = unquote(parsed.path, errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise LspWorkspaceError("invalid percent-encoding in LSP file URI") from exc
    path = PurePosixPath(decoded)
    if not path.is_absolute():
        raise LspWorkspaceError("LSP file URI path must be absolute")
    return netloc, path


def _render_file_uri(netloc: str, path: PurePosixPath) -> str:
    if not path.is_absolute():
        raise LspWorkspaceError("LSP server root path must be absolute")
    encoded = quote(path.as_posix(), safe="/:")
    return f"file://{netloc}{encoded}"


class LspWorkspaceMapper:
    """Map local Workspace paths to the root URI visible to an LSP server."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        server_root_uri: str | None = None,
    ):
        try:
            self.workspace_root = Path(workspace_root).resolve()
        except (OSError, RuntimeError) as exc:
            raise LspWorkspaceError("cannot resolve LSP Workspace root") from exc
        if not self.workspace_root.is_dir():
            raise LspWorkspaceError("LSP Workspace root must be an existing directory")

        root_uri = server_root_uri or self.workspace_root.as_uri()
        self._server_netloc, self._server_root_path = _parse_file_uri(root_uri)
        if any(part in {".", ".."} for part in self._server_root_path.parts):
            raise LspWorkspaceError("LSP server root URI may not contain dot segments")
        self.server_root_uri = _render_file_uri(
            self._server_netloc,
            self._server_root_path,
        )

    def _contained(self, candidate: Path) -> Path:
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise LspWorkspaceError("cannot resolve LSP location") from exc
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise LspWorkspaceError("LSP location escapes Workspace root") from exc
        return resolved

    @staticmethod
    def _portable(raw: str) -> PurePosixPath:
        try:
            return portable_relative_path(raw)
        except ValueError as exc:
            raise LspWorkspaceError(f"unsafe LSP repository path: {exc}") from exc

    def path_to_uri(self, path: str | Path) -> str:
        raw = path.as_posix() if isinstance(path, Path) else path
        if not isinstance(raw, str):
            raise LspWorkspaceError("LSP repository path is invalid")
        portable = self._portable(raw)
        resolved = self._contained(self.workspace_root.joinpath(*portable.parts))
        relative = resolved.relative_to(self.workspace_root).as_posix()
        portable_relative = self._portable(relative)
        server_path = self._server_root_path.joinpath(*portable_relative.parts)
        return _render_file_uri(self._server_netloc, server_path)

    def uri_to_path(self, uri: str) -> str:
        if not isinstance(uri, str) or not uri:
            raise LspWorkspaceError("LSP location URI must be a non-empty string")
        netloc, server_path = _parse_file_uri(uri)
        if netloc != self._server_netloc:
            raise LspWorkspaceError("LSP location URI host does not match server root")
        try:
            relative = server_path.relative_to(self._server_root_path)
        except ValueError as exc:
            raise LspWorkspaceError("LSP location escapes server-visible Workspace root") from exc
        if not relative.parts:
            raise LspWorkspaceError("LSP location refers to Workspace root, not a file")
        portable = self._portable(relative.as_posix())
        resolved = self._contained(self.workspace_root.joinpath(*portable.parts))
        return self._portable(
            resolved.relative_to(self.workspace_root).as_posix()
        ).as_posix()


_POSITION_ENCODINGS = {
    "utf-8": LspPositionEncoding.UTF8,
    "utf-16": LspPositionEncoding.UTF16,
    "utf-32": LspPositionEncoding.UTF32,
}


def _provider_enabled(value: object) -> bool:
    return value is True or isinstance(value, dict)


def parse_server_capabilities(result: object) -> LspServerCapabilities:
    if not isinstance(result, dict):
        raise LspInitializationError("LSP initialize result must be an object")
    raw = result.get("capabilities")
    if not isinstance(raw, dict):
        raise LspInitializationError("LSP initialize result is missing capabilities")

    raw_encoding = raw.get("positionEncoding", "utf-16")
    if not isinstance(raw_encoding, str):
        raise LspInitializationError("LSP positionEncoding must be a string")
    encoding = _POSITION_ENCODINGS.get(raw_encoding.casefold())
    if encoding is None:
        raise LspInitializationError(
            f"unsupported LSP position encoding: {raw_encoding}"
        )

    return LspServerCapabilities(
        position_encoding=encoding,
        workspace_symbols=_provider_enabled(raw.get("workspaceSymbolProvider")),
        definitions=_provider_enabled(raw.get("definitionProvider")),
        references=_provider_enabled(raw.get("referencesProvider")),
        diagnostics=_provider_enabled(raw.get("diagnosticProvider")),
    )


def initialize_lsp_session(
    session: LspRequestSession,
    mapper: LspWorkspaceMapper,
    *,
    timeout_seconds: float = 10.0,
) -> LspServerCapabilities:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    params = {
        "processId": None,
        "clientInfo": {"name": "Origin Forge", "version": "phase-11"},
        "rootUri": mapper.server_root_uri,
        "capabilities": {
            "general": {"positionEncodings": ["utf-8", "utf-16", "utf-32"]},
            "workspace": {"symbol": {}},
            "textDocument": {
                "definition": {},
                "references": {},
                "diagnostic": {},
            },
        },
        "workspaceFolders": None,
        "trace": "off",
    }
    result = session.request("initialize", params, timeout_seconds=timeout_seconds)
    capabilities = parse_server_capabilities(result)
    session.notify("initialized", {})
    return capabilities
