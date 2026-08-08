from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.code_intelligence import (
    CodeIntelligenceError,
    DiagnosticSeverity,
    SymbolKind,
    TextPosition,
)
from origin_forge.lsp_client import LspServerCapabilities, LspWorkspaceMapper
from origin_forge.lsp_code_intelligence import LspCodeIntelligenceProvider
from origin_forge.lsp_protocol import LspPositionEncoding, codepoint_to_lsp_character
from origin_forge.repository import RepositoryReader


class FakeSession:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.requests: list[tuple[str, object, float]] = []

    def request(self, method: str, params: object | None = None, *, timeout_seconds: float = 10.0) -> object | None:
        self.requests.append((method, params, timeout_seconds))
        return self.responses.get(method)

    def notify(self, method: str, params: object | None = None) -> None:
        pass


class LspCodeIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "src").mkdir()
        self.a = self.root / "src" / "a.py"
        self.b = self.root / "src" / "b.py"
        self.a.write_text("prefix🐈Widget\n", encoding="utf-8")
        self.b.write_text("é🐈Widget = 1\n", encoding="utf-8")
        self.reader = RepositoryReader(self.root)
        self.mapper = LspWorkspaceMapper(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _capabilities(self, **overrides) -> LspServerCapabilities:
        values = {
            "position_encoding": LspPositionEncoding.UTF16,
            "workspace_symbols": True,
            "definitions": True,
            "references": True,
            "diagnostics": True,
        }
        values.update(overrides)
        return LspServerCapabilities(**values)

    def test_definition_query_and_result_translate_utf16_positions(self) -> None:
        target_line = self.b.read_text(encoding="utf-8").splitlines()[0]
        start = codepoint_to_lsp_character(target_line, 2, LspPositionEncoding.UTF16)
        end = codepoint_to_lsp_character(target_line, 8, LspPositionEncoding.UTF16)
        session = FakeSession({"textDocument/definition": {"uri": self.mapper.path_to_uri("src/b.py"), "range": {"start": {"line": 0, "character": start}, "end": {"line": 0, "character": end}}}})
        provider = LspCodeIntelligenceProvider(self.reader, session, self._capabilities(), mapper=self.mapper)

        query_line = self.a.read_text(encoding="utf-8").splitlines()[0]
        query_position = TextPosition(0, len("prefix🐈"))
        result = provider.definitions("src/a.py", query_position)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path, "src/b.py")
        self.assertEqual(result[0].range.start, TextPosition(0, 2))
        self.assertEqual(result[0].range.end, TextPosition(0, 8))
        sent = session.requests[0][1]
        self.assertEqual(sent["position"]["character"], codepoint_to_lsp_character(query_line, query_position.character, LspPositionEncoding.UTF16))

    def test_external_definition_uri_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "outside.py"
            external.write_text("VALUE = 1\n", encoding="utf-8")
            session = FakeSession({"textDocument/definition": {"uri": external.resolve().as_uri(), "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}}})
            provider = LspCodeIntelligenceProvider(self.reader, session, self._capabilities(), mapper=self.mapper)
            with self.assertRaisesRegex(CodeIntelligenceError, "unsafe LSP location"):
                provider.definitions("src/a.py", TextPosition(0, 1))

    def test_workspace_symbols_are_normalized_and_limited(self) -> None:
        location = {"uri": self.mapper.path_to_uri("src/b.py"), "range": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 9}}}
        session = FakeSession({"workspace/symbol": [{"name": "Widget", "kind": 5, "location": location}, {"name": "helper", "kind": 12, "location": location}]})
        provider = LspCodeIntelligenceProvider(self.reader, session, self._capabilities(), mapper=self.mapper)
        result = provider.workspace_symbols("", limit=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Widget")
        self.assertEqual(result[0].kind, SymbolKind.CLASS)

    def test_references_send_include_declaration_policy(self) -> None:
        location = {"uri": self.mapper.path_to_uri("src/a.py"), "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}}
        session = FakeSession({"textDocument/references": [location]})
        provider = LspCodeIntelligenceProvider(self.reader, session, self._capabilities(position_encoding=LspPositionEncoding.UTF8), mapper=self.mapper)
        result = provider.references("src/a.py", TextPosition(0, 1), include_declaration=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(session.requests[0][1]["context"], {"includeDeclaration": False})

    def test_pull_diagnostics_are_normalized(self) -> None:
        line = self.b.read_text(encoding="utf-8").splitlines()[0]
        start = codepoint_to_lsp_character(line, 2, LspPositionEncoding.UTF16)
        end = codepoint_to_lsp_character(line, 8, LspPositionEncoding.UTF16)
        session = FakeSession({"textDocument/diagnostic": {"kind": "full", "items": [{"range": {"start": {"line": 0, "character": start}, "end": {"line": 0, "character": end}}, "severity": 2, "message": "example warning", "source": "fake-lsp", "code": 42}]}})
        provider = LspCodeIntelligenceProvider(self.reader, session, self._capabilities(), mapper=self.mapper)
        result = provider.diagnostics(["src/b.py"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].severity, DiagnosticSeverity.WARNING)
        self.assertEqual(result[0].range.start, TextPosition(0, 2))
        self.assertEqual(result[0].code, "42")

    def test_pull_diagnostic_text_fields_are_bounded_during_normalization(self) -> None:
        session = FakeSession({"textDocument/diagnostic": {"kind": "full", "items": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "severity": 1, "message": "m" * 20000, "source": "s" * 1000, "code": "c" * 1000}]}})
        provider = LspCodeIntelligenceProvider(self.reader, session, self._capabilities(), mapper=self.mapper)
        result = provider.diagnostics(["src/b.py"])
        self.assertEqual(len(result[0].message), 16 * 1024 + 1)
        self.assertEqual(len(result[0].source), 513)
        self.assertEqual(len(result[0].code or ""), 513)
        self.assertTrue(result[0].message.endswith("…"))
        self.assertTrue(result[0].source.endswith("…"))
        self.assertTrue((result[0].code or "").endswith("…"))

    def test_unadvertised_capability_is_not_queried(self) -> None:
        session = FakeSession({})
        provider = LspCodeIntelligenceProvider(self.reader, session, self._capabilities(definitions=False), mapper=self.mapper)
        with self.assertRaisesRegex(CodeIntelligenceError, "does not advertise"):
            provider.definitions("src/a.py", TextPosition(0, 1))
        self.assertEqual(session.requests, [])


if __name__ == "__main__":
    unittest.main()
