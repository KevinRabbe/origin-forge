from __future__ import annotations

import unittest

from origin_forge.code_diagnostics import (
    CodeDiagnosticsEvaluator,
    CodeDiagnosticsSettings,
)
from origin_forge.code_intelligence import (
    CodeDiagnostic,
    CodeIntelligenceCapabilities,
    CodeIntelligenceError,
    DiagnosticSeverity,
    TextPosition,
    TextRange,
)


def diagnostic(
    path: str,
    severity: DiagnosticSeverity,
    message: str,
    *,
    line: int = 0,
) -> CodeDiagnostic:
    return CodeDiagnostic(
        path,
        TextRange(TextPosition(line, 0), TextPosition(line, 1)),
        severity,
        message,
        "fake-provider",
        None,
    )


class FakeDiagnosticsProvider:
    provider_id = "fake-diagnostics"

    def __init__(self, values=(), *, available=True, diagnostics=True):
        self.values = tuple(values)
        self._available = available
        self.capabilities = CodeIntelligenceCapabilities(
            workspace_symbols=False,
            definitions=False,
            references=False,
            diagnostics=diagnostics,
        )
        self.calls: list[tuple[tuple[str, ...], int]] = []

    def available(self) -> bool:
        return self._available

    def diagnostics(self, paths, *, limit_per_file=100):
        self.calls.append((tuple(paths), limit_per_file))
        return self.values

    def workspace_symbols(self, query, *, limit=50):
        return ()

    def definitions(self, path, position, *, limit=20):
        return ()

    def references(self, path, position, *, include_declaration=True, limit=100):
        return ()


class CodeDiagnosticsEvaluatorTests(unittest.TestCase):
    def test_errors_fail_but_warnings_do_not_replace_runtime_verification(self) -> None:
        provider = FakeDiagnosticsProvider(
            (
                diagnostic("src/a.py", DiagnosticSeverity.WARNING, "warning"),
                diagnostic("src/b.py", DiagnosticSeverity.ERROR, "error"),
            )
        )
        result = CodeDiagnosticsEvaluator(provider).evaluate(
            ["src/a.py", "src/b.py"]
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.warning_count, 1)
        self.assertEqual(result.diagnostics[0].severity, DiagnosticSeverity.ERROR)
        self.assertEqual(provider.calls[0][0], ("src/a.py", "src/b.py"))

    def test_warning_only_result_passes(self) -> None:
        provider = FakeDiagnosticsProvider(
            (diagnostic("src/a.py", DiagnosticSeverity.WARNING, "warning"),)
        )
        result = CodeDiagnosticsEvaluator(provider).evaluate(["src/a.py"])
        self.assertTrue(result.passed)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.warning_count, 1)

    def test_diagnostics_and_messages_are_bounded(self) -> None:
        provider = FakeDiagnosticsProvider(
            tuple(
                diagnostic(
                    f"src/{index}.py",
                    DiagnosticSeverity.INFORMATION,
                    "x" * 100,
                    line=index,
                )
                for index in range(10)
            )
        )
        result = CodeDiagnosticsEvaluator(
            provider,
            settings=CodeDiagnosticsSettings(
                max_diagnostics=3,
                max_message_chars=8,
            ),
        ).evaluate(["src/a.py", "src/a.py"])

        self.assertEqual(len(result.diagnostics), 3)
        self.assertEqual(len(result.evidence), 3)
        self.assertEqual(result.evidence[0]["message"], "xxxxxxxx…")
        self.assertEqual(provider.calls[0], (("src/a.py",), 3))

    def test_unavailable_or_unsupported_provider_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(CodeIntelligenceError, "unavailable"):
            CodeDiagnosticsEvaluator(
                FakeDiagnosticsProvider(available=False)
            ).evaluate(["src/a.py"])

        with self.assertRaisesRegex(CodeIntelligenceError, "does not support"):
            CodeDiagnosticsEvaluator(
                FakeDiagnosticsProvider(diagnostics=False)
            ).evaluate(["src/a.py"])

    def test_error_policy_can_be_evidence_only(self) -> None:
        provider = FakeDiagnosticsProvider(
            (diagnostic("src/a.py", DiagnosticSeverity.ERROR, "error"),)
        )
        result = CodeDiagnosticsEvaluator(
            provider,
            settings=CodeDiagnosticsSettings(fail_on_errors=False),
        ).evaluate(["src/a.py"])
        self.assertTrue(result.passed)
        self.assertEqual(result.error_count, 1)


if __name__ == "__main__":
    unittest.main()
