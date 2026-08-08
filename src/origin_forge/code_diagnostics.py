from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .code_intelligence import (
    CodeDiagnostic,
    CodeIntelligenceError,
    CodeIntelligenceProvider,
    DiagnosticSeverity,
)


@dataclass(frozen=True)
class CodeDiagnosticsSettings:
    max_diagnostics: int = 200
    max_message_chars: int = 2000
    fail_on_errors: bool = True

    def __post_init__(self) -> None:
        if self.max_diagnostics <= 0:
            raise ValueError("max_diagnostics must be positive")
        if self.max_message_chars <= 0:
            raise ValueError("max_message_chars must be positive")


@dataclass(frozen=True)
class CodeDiagnosticsResult:
    provider_id: str
    passed: bool
    diagnostics: tuple[CodeDiagnostic, ...]
    error_count: int
    warning_count: int
    evidence: tuple[dict[str, object], ...]


class CodeDiagnosticsEvaluator:
    """Convert provider diagnostics into bounded independent evidence.

    This evaluator never changes Task/Workspace state. A caller may persist the
    returned evidence, but compiler/tests/runtime verification remain higher
    authority than diagnostics from a language server or static analyzer.
    """

    def __init__(
        self,
        provider: CodeIntelligenceProvider,
        *,
        settings: CodeDiagnosticsSettings | None = None,
    ):
        self.provider = provider
        self.settings = settings or CodeDiagnosticsSettings()

    @staticmethod
    def _severity_rank(value: DiagnosticSeverity) -> int:
        return {
            DiagnosticSeverity.ERROR: 0,
            DiagnosticSeverity.WARNING: 1,
            DiagnosticSeverity.INFORMATION: 2,
            DiagnosticSeverity.HINT: 3,
        }[value]

    def evaluate(self, paths: Sequence[str]) -> CodeDiagnosticsResult:
        if not self.provider.available():
            raise CodeIntelligenceError(
                f"code-intelligence provider is unavailable: {self.provider.provider_id}"
            )
        if not self.provider.capabilities.diagnostics:
            raise CodeIntelligenceError(
                f"provider {self.provider.provider_id} does not support diagnostics"
            )

        unique_paths = tuple(dict.fromkeys(paths))
        raw = self.provider.diagnostics(
            unique_paths,
            limit_per_file=self.settings.max_diagnostics,
        )
        ordered = sorted(
            raw,
            key=lambda item: (
                self._severity_rank(item.severity),
                item.path,
                item.range.start.line,
                item.range.start.character,
                item.message,
            ),
        )[: self.settings.max_diagnostics]
        diagnostics = tuple(ordered)
        error_count = sum(
            item.severity == DiagnosticSeverity.ERROR for item in diagnostics
        )
        warning_count = sum(
            item.severity == DiagnosticSeverity.WARNING for item in diagnostics
        )
        passed = not (self.settings.fail_on_errors and error_count)

        evidence: list[dict[str, object]] = []
        for item in diagnostics:
            message = item.message
            if len(message) > self.settings.max_message_chars:
                message = message[: self.settings.max_message_chars] + "…"
            evidence.append(
                {
                    "path": item.path,
                    "range": {
                        "start": {
                            "line": item.range.start.line,
                            "character": item.range.start.character,
                        },
                        "end": {
                            "line": item.range.end.line,
                            "character": item.range.end.character,
                        },
                    },
                    "severity": item.severity.value,
                    "message": message,
                    "source": item.source,
                    "code": item.code,
                }
            )

        return CodeDiagnosticsResult(
            self.provider.provider_id,
            passed,
            diagnostics,
            error_count,
            warning_count,
            tuple(evidence),
        )
