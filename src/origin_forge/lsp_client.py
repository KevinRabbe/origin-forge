from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import url2pathname

from .lsp_protocol import LspPositionEncoding, LspProtocolError


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


class LspWorkspaceMapper:
    """Convert between repository-relative paths and contained file URIs."""

    _BLOCKED_ROOTS = frozenset({".git", ".origin-forge"})

    def __init__(self, workspace_root: str | Path):
        try:
            self.workspace_root = Path(workspace_root).resolve()
        except (OSError, RuntimeError) as exc:
            raise LspWorkspaceError("cannot resolve LSP Workspace root") from exc
        if not self.workspace_root.is_dir():
            raise LspWorkspaceError("LSP Workspace root must be an existing directory")

    def _contained(self, candidate: Path) -> Path:
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise LspWorkspaceError("cannot resolve LSP location") from exc
        try:
            relative = resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise LspWorkspaceError("LSP location escapes Workspace root") from exc
        if relative.parts and relative.parts[0].casefold() in self._BLOCKED_ROOTS:
            raise LspWorkspaceError(
                f"LSP location enters protected root: {relative.parts[0]}"
            )
        return resolved

    def path_to_uri(self, path: str | Path) -> str:
        try:
            candidate = Path(path)
        except (TypeError, ValueError) as exc:
            raise LspWorkspaceError("LSP repository path is invalid") from exc
        if candidate.is_absolute():
            raise LspWorkspaceError("LSP repository paths must be relative")
        if not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
            raise LspWorkspaceError("LSP repository path is invalid")
        if candidate.parts[0].casefold() in self._BLOCKED_ROOTS:
            raise LspWorkspaceError(
                f"LSP repository path enters protected root: {candidate.parts[0]}"
            )
        resolved = self._contained(self.workspace_root / candidate)
        return resolved.as_uri()

    def uri_to_path(self, uri: str) -> str:
        if not isinstance(uri, str) or not uri:
            raise LspWorkspaceError("LSP location URI must be a non-empty string")
        parsed = urlparse(uri)
        if parsed.scheme.casefold() != "file":
            raise LspWorkspaceError(
                f"unsupported LSP location URI scheme: {parsed.scheme or '<none>'}"
            )
        if parsed.netloc.casefold() not in {"", "localhost"}:
            raise LspWorkspaceError("remote-host file URIs are not allowed")
        if parsed.params or parsed.query or parsed.fragment:
            raise LspWorkspaceError("LSP file URI may not contain params, query, or fragment")
        try:
            native = Path(url2pathname(parsed.path))
        except (TypeError, ValueError) as exc:
            raise LspWorkspaceError("invalid LSP file URI path") from exc
        resolved = self._contained(native)
        return resolved.relative_to(self.workspace_root).as_posix()


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
        "clientInfo": {
            "name": "Origin Forge",
            "version": "phase-11",
        },
        "rootUri": mapper.workspace_root.as_uri(),
        "capabilities": {
            "general": {
                "positionEncodings": ["utf-8", "utf-16", "utf-32"],
            },
            "workspace": {
                "symbol": {},
            },
            "textDocument": {
                "definition": {},
                "references": {},
                "diagnostic": {},
            },
        },
        "workspaceFolders": [
            {
                "uri": mapper.workspace_root.as_uri(),
                "name": mapper.workspace_root.name,
            }
        ],
        "trace": "off",
    }
    result = session.request(
        "initialize",
        params,
        timeout_seconds=timeout_seconds,
    )
    capabilities = parse_server_capabilities(result)
    session.notify("initialized", {})
    return capabilities
