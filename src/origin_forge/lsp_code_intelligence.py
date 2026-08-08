from __future__ import annotations

from typing import Sequence

from .code_intelligence import (
    CodeDiagnostic,
    CodeIntelligenceCapabilities,
    CodeIntelligenceError,
    CodeLocation,
    CodeSymbol,
    DiagnosticSeverity,
    SymbolKind,
    TextPosition,
    TextRange,
)
from .lsp_client import (
    LspRequestSession,
    LspServerCapabilities,
    LspWorkspaceError,
    LspWorkspaceMapper,
)
from .lsp_protocol import (
    LspProtocolError,
    codepoint_to_lsp_character,
    lsp_character_to_codepoint,
)
from .repository import RepositoryAccessError, RepositoryReader


_SYMBOL_KINDS = {
    2: SymbolKind.MODULE,
    3: SymbolKind.MODULE,
    4: SymbolKind.MODULE,
    5: SymbolKind.CLASS,
    6: SymbolKind.METHOD,
    7: SymbolKind.VARIABLE,
    8: SymbolKind.VARIABLE,
    9: SymbolKind.METHOD,
    12: SymbolKind.FUNCTION,
    13: SymbolKind.VARIABLE,
    14: SymbolKind.VARIABLE,
}

_DIAGNOSTIC_SEVERITIES = {
    1: DiagnosticSeverity.ERROR,
    2: DiagnosticSeverity.WARNING,
    3: DiagnosticSeverity.INFORMATION,
    4: DiagnosticSeverity.HINT,
}

_MAX_DIAGNOSTIC_MESSAGE_CHARS = 16 * 1024
_MAX_DIAGNOSTIC_SOURCE_CHARS = 512
_MAX_DIAGNOSTIC_CODE_CHARS = 512


def _limit(value: int, *, maximum: int = 1000) -> int:
    if value <= 0:
        raise ValueError("limit must be positive")
    return min(value, maximum)


def _bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


class LspCodeIntelligenceProvider:
    """Normalize an initialized bounded LSP session into Origin Forge evidence."""

    def __init__(
        self,
        repository: RepositoryReader,
        session: LspRequestSession,
        server_capabilities: LspServerCapabilities,
        *,
        mapper: LspWorkspaceMapper | None = None,
        provider_id: str = "lsp",
        request_timeout_seconds: float = 5.0,
    ):
        if not provider_id:
            raise ValueError("provider_id may not be empty")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self.repository = repository
        self.session = session
        self.server_capabilities = server_capabilities
        self.mapper = mapper or LspWorkspaceMapper(repository.project_root)
        if self.mapper.workspace_root != repository.project_root:
            raise CodeIntelligenceError("LSP mapper root must match RepositoryReader root")
        self._provider_id = provider_id
        self.request_timeout_seconds = request_timeout_seconds

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> CodeIntelligenceCapabilities:
        return CodeIntelligenceCapabilities(
            workspace_symbols=self.server_capabilities.workspace_symbols,
            definitions=self.server_capabilities.definitions,
            references=self.server_capabilities.references,
            diagnostics=self.server_capabilities.diagnostics,
        )

    def available(self) -> bool:
        return True

    def _require(self, enabled: bool, capability: str) -> None:
        if not enabled:
            raise CodeIntelligenceError(
                f"LSP server does not advertise {capability} capability"
            )

    def _source_lines(self, path: str) -> tuple[str, ...]:
        try:
            source = self.repository.read_text(path)
        except RepositoryAccessError as exc:
            raise CodeIntelligenceError(f"cannot read LSP source {path}: {exc}") from exc
        lines = source.content.split("\n")
        return tuple(line[:-1] if line.endswith("\r") else line for line in lines)

    def _query_position(self, path: str, position: TextPosition) -> dict:
        lines = self._source_lines(path)
        if position.line >= len(lines):
            raise CodeIntelligenceError(f"LSP query line is outside {path}: {position.line}")
        try:
            character = codepoint_to_lsp_character(
                lines[position.line],
                position.character,
                self.server_capabilities.position_encoding,
            )
            uri = self.mapper.path_to_uri(path)
        except (ValueError, LspWorkspaceError) as exc:
            raise CodeIntelligenceError(f"invalid LSP query location: {exc}") from exc
        return {
            "textDocument": {"uri": uri},
            "position": {"line": position.line, "character": character},
        }

    def _position(self, path: str, raw: object) -> TextPosition:
        if not isinstance(raw, dict):
            raise CodeIntelligenceError("LSP position must be an object")
        line = raw.get("line")
        character = raw.get("character")
        if not isinstance(line, int) or isinstance(line, bool) or line < 0:
            raise CodeIntelligenceError("LSP position line must be a non-negative integer")
        if not isinstance(character, int) or isinstance(character, bool) or character < 0:
            raise CodeIntelligenceError(
                "LSP position character must be a non-negative integer"
            )
        lines = self._source_lines(path)
        if line >= len(lines):
            raise CodeIntelligenceError(f"LSP result line is outside {path}: {line}")
        try:
            decoded = lsp_character_to_codepoint(
                lines[line], character, self.server_capabilities.position_encoding
            )
        except ValueError as exc:
            raise CodeIntelligenceError(
                f"invalid LSP result character offset for {path}: {exc}"
            ) from exc
        return TextPosition(line, decoded)

    def _range(self, path: str, raw: object) -> TextRange:
        if not isinstance(raw, dict):
            raise CodeIntelligenceError("LSP range must be an object")
        return TextRange(
            self._position(path, raw.get("start")),
            self._position(path, raw.get("end")),
        )

    def _location(self, raw: object) -> CodeLocation:
        if not isinstance(raw, dict):
            raise CodeIntelligenceError("LSP location must be an object")
        uri = raw.get("uri")
        if not isinstance(uri, str):
            raise CodeIntelligenceError("LSP location is missing URI")
        try:
            path = self.mapper.uri_to_path(uri)
        except LspWorkspaceError as exc:
            raise CodeIntelligenceError(f"unsafe LSP location: {exc}") from exc
        return CodeLocation(path, self._range(path, raw.get("range")))

    def _definition_location(self, raw: object) -> CodeLocation:
        if not isinstance(raw, dict):
            raise CodeIntelligenceError("LSP definition result must be an object")
        if "uri" in raw:
            return self._location(raw)
        uri = raw.get("targetUri")
        target_range = raw.get("targetSelectionRange", raw.get("targetRange"))
        if not isinstance(uri, str) or target_range is None:
            raise CodeIntelligenceError("malformed LSP LocationLink")
        return self._location({"uri": uri, "range": target_range})

    def _request(self, method: str, params: object) -> object | None:
        try:
            return self.session.request(
                method, params, timeout_seconds=self.request_timeout_seconds
            )
        except (LspProtocolError, TimeoutError, OSError) as exc:
            raise CodeIntelligenceError(f"LSP request {method} failed: {exc}") from exc

    def workspace_symbols(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> Sequence[CodeSymbol]:
        self._require(self.capabilities.workspace_symbols, "workspace symbols")
        limit = _limit(limit)
        raw = self._request("workspace/symbol", {"query": query})
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise CodeIntelligenceError("LSP workspace/symbol result must be an array")
        result: list[CodeSymbol] = []
        for item in raw:
            if len(result) >= limit:
                break
            if not isinstance(item, dict):
                raise CodeIntelligenceError("LSP workspace symbol must be an object")
            name = item.get("name")
            kind = item.get("kind")
            location = item.get("location")
            if not isinstance(name, str) or not isinstance(kind, int) or isinstance(kind, bool):
                raise CodeIntelligenceError("malformed LSP workspace symbol")
            if not isinstance(location, dict) or "range" not in location:
                continue
            result.append(
                CodeSymbol(
                    name,
                    _SYMBOL_KINDS.get(kind, SymbolKind.VARIABLE),
                    self._location(location),
                    item.get("containerName") if isinstance(item.get("containerName"), str) else None,
                )
            )
        return tuple(result)

    def definitions(
        self,
        path: str,
        position: TextPosition,
        *,
        limit: int = 20,
    ) -> Sequence[CodeLocation]:
        self._require(self.capabilities.definitions, "definition")
        limit = _limit(limit)
        raw = self._request("textDocument/definition", self._query_position(path, position))
        if raw is None:
            return ()
        values = raw if isinstance(raw, list) else [raw]
        return tuple(self._definition_location(item) for item in values[:limit])

    def references(
        self,
        path: str,
        position: TextPosition,
        *,
        include_declaration: bool = True,
        limit: int = 100,
    ) -> Sequence[CodeLocation]:
        self._require(self.capabilities.references, "references")
        limit = _limit(limit)
        params = self._query_position(path, position)
        params["context"] = {"includeDeclaration": bool(include_declaration)}
        raw = self._request("textDocument/references", params)
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise CodeIntelligenceError("LSP references result must be an array")
        return tuple(self._location(item) for item in raw[:limit])

    def diagnostics(
        self,
        paths: Sequence[str],
        *,
        limit_per_file: int = 100,
    ) -> Sequence[CodeDiagnostic]:
        self._require(self.capabilities.diagnostics, "pull diagnostics")
        limit_per_file = _limit(limit_per_file)
        result: list[CodeDiagnostic] = []
        for path in dict.fromkeys(paths):
            try:
                uri = self.mapper.path_to_uri(path)
            except LspWorkspaceError as exc:
                raise CodeIntelligenceError(f"invalid diagnostic path: {exc}") from exc
            raw = self._request(
                "textDocument/diagnostic",
                {"textDocument": {"uri": uri}},
            )
            if not isinstance(raw, dict):
                raise CodeIntelligenceError(
                    "LSP textDocument/diagnostic result must be an object"
                )
            kind = raw.get("kind")
            if kind == "unchanged":
                continue
            if kind != "full" or not isinstance(raw.get("items"), list):
                raise CodeIntelligenceError("malformed LSP diagnostic report")
            for item in raw["items"][:limit_per_file]:
                if not isinstance(item, dict):
                    raise CodeIntelligenceError("LSP diagnostic must be an object")
                message = item.get("message")
                if not isinstance(message, str):
                    raise CodeIntelligenceError("LSP diagnostic message must be a string")
                severity = item.get("severity", 3)
                if not isinstance(severity, int) or isinstance(severity, bool):
                    raise CodeIntelligenceError("LSP diagnostic severity must be an integer")
                raw_code = item.get("code")
                code = (
                    str(raw_code)
                    if isinstance(raw_code, (str, int)) and not isinstance(raw_code, bool)
                    else None
                )
                source = item.get("source")
                bounded_source = (
                    _bounded_text(source, _MAX_DIAGNOSTIC_SOURCE_CHARS)
                    if isinstance(source, str)
                    else self.provider_id
                )
                result.append(
                    CodeDiagnostic(
                        path,
                        self._range(path, item.get("range")),
                        _DIAGNOSTIC_SEVERITIES.get(
                            severity, DiagnosticSeverity.INFORMATION
                        ),
                        _bounded_text(message, _MAX_DIAGNOSTIC_MESSAGE_CHARS),
                        bounded_source,
                        _bounded_text(code, _MAX_DIAGNOSTIC_CODE_CHARS)
                        if code is not None
                        else None,
                    )
                )
        return tuple(result)
