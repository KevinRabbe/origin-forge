from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, Sequence, runtime_checkable


class CodeIntelligenceError(RuntimeError):
    pass


class SymbolKind(StrEnum):
    MODULE = "MODULE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"


class DiagnosticSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFORMATION = "INFORMATION"
    HINT = "HINT"


@dataclass(frozen=True, order=True)
class TextPosition:
    """Zero-based Unicode-codepoint position used inside Origin Forge."""

    line: int
    character: int

    def __post_init__(self) -> None:
        if self.line < 0 or self.character < 0:
            raise ValueError("text positions must be non-negative")


@dataclass(frozen=True)
class TextRange:
    start: TextPosition
    end: TextPosition

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("text range end must not precede start")


@dataclass(frozen=True)
class CodeLocation:
    path: str
    range: TextRange


@dataclass(frozen=True)
class CodeSymbol:
    name: str
    kind: SymbolKind
    location: CodeLocation
    container_name: str | None = None


@dataclass(frozen=True)
class CodeDiagnostic:
    path: str
    range: TextRange
    severity: DiagnosticSeverity
    message: str
    source: str
    code: str | None = None


@dataclass(frozen=True)
class CodeIntelligenceCapabilities:
    workspace_symbols: bool = False
    definitions: bool = False
    references: bool = False
    diagnostics: bool = False


@runtime_checkable
class CodeIntelligenceProvider(Protocol):
    """Read-only bounded code-intelligence surface.

    Providers may use ASTs, Tree-sitter, LSP, or another deterministic source,
    but callers receive one stable Origin Forge representation. Implementations
    must not grant the model direct access to the underlying server/process.
    """

    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> CodeIntelligenceCapabilities: ...

    def available(self) -> bool: ...

    def workspace_symbols(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> Sequence[CodeSymbol]: ...

    def definitions(
        self,
        path: str,
        position: TextPosition,
        *,
        limit: int = 20,
    ) -> Sequence[CodeLocation]: ...

    def references(
        self,
        path: str,
        position: TextPosition,
        *,
        include_declaration: bool = True,
        limit: int = 100,
    ) -> Sequence[CodeLocation]: ...

    def diagnostics(
        self,
        paths: Sequence[str],
        *,
        limit_per_file: int = 100,
    ) -> Sequence[CodeDiagnostic]: ...
