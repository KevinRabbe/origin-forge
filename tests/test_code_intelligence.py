from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.code_intelligence import (
    CodeIntelligenceProvider,
    DiagnosticSeverity,
    SymbolKind,
    TextPosition,
)
from origin_forge.python_code_intelligence import (
    PythonAstCodeIntelligence,
    PythonIntelligenceSettings,
)
from origin_forge.repository import RepositoryReader


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class PythonCodeIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")

        package = self.root / "src" / "pkg"
        package.mkdir(parents=True)
        package.joinpath("__init__.py").write_text("", encoding="utf-8")
        package.joinpath("models.py").write_text(
            "class WidgetParser:\n"
            "    def parse(self, value):\n"
            "        def normalize(item):\n"
            "            return item.strip()\n"
            "        return normalize(value)\n",
            encoding="utf-8",
        )
        package.joinpath("service.py").write_text(
            "from pkg.models import WidgetParser\n\n"
            "def build_widget(value):\n"
            "    parser = WidgetParser()\n"
            "    return parser.parse(value)\n",
            encoding="utf-8",
        )
        git(self.root, "add", "src")
        git(self.root, "commit", "-qm", "initial")

        self.reader = RepositoryReader(self.root)
        self.provider = PythonAstCodeIntelligence(self.reader)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_provider_contract_and_capabilities(self) -> None:
        self.assertIsInstance(self.provider, CodeIntelligenceProvider)
        self.assertTrue(self.provider.available())
        self.assertTrue(self.provider.capabilities.workspace_symbols)
        self.assertTrue(self.provider.capabilities.definitions)
        self.assertTrue(self.provider.capabilities.references)
        self.assertTrue(self.provider.capabilities.diagnostics)

    def test_workspace_symbols_are_bounded_and_scope_aware(self) -> None:
        symbols = self.provider.workspace_symbols("", limit=20)
        by_name = {symbol.name: symbol for symbol in symbols}

        self.assertEqual(by_name["WidgetParser"].kind, SymbolKind.CLASS)
        self.assertEqual(by_name["parse"].kind, SymbolKind.METHOD)
        self.assertEqual(by_name["parse"].container_name, "WidgetParser")
        self.assertEqual(by_name["normalize"].kind, SymbolKind.FUNCTION)
        self.assertEqual(by_name["normalize"].container_name, "parse")
        self.assertEqual(by_name["build_widget"].kind, SymbolKind.FUNCTION)
        self.assertLessEqual(len(self.provider.workspace_symbols("", limit=2)), 2)

    def test_definition_resolves_symbol_from_usage(self) -> None:
        line = "    parser = WidgetParser()"
        position = TextPosition(3, line.index("WidgetParser") + 2)
        definitions = self.provider.definitions(
            "src/pkg/service.py",
            position,
        )

        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].path, "src/pkg/models.py")
        self.assertEqual(definitions[0].range.start.line, 0)

    def test_references_include_declaration_and_usage(self) -> None:
        position = TextPosition(0, len("class Wid"))
        references = self.provider.references(
            "src/pkg/models.py",
            position,
            include_declaration=True,
        )
        paths = [location.path for location in references]
        self.assertIn("src/pkg/models.py", paths)
        self.assertIn("src/pkg/service.py", paths)

        without_declaration = self.provider.references(
            "src/pkg/models.py",
            position,
            include_declaration=False,
        )
        self.assertTrue(without_declaration)
        self.assertNotIn(
            ("src/pkg/models.py", 0),
            [(location.path, location.range.start.line) for location in without_declaration],
        )

    def test_syntax_diagnostic_is_read_only_and_normalized(self) -> None:
        broken = self.root / "src" / "pkg" / "broken.py"
        broken.write_text("def broken(:\n", encoding="utf-8")
        git(self.root, "add", "src/pkg/broken.py")
        git(self.root, "commit", "-qm", "add broken fixture")

        diagnostics = self.provider.diagnostics(["src/pkg/broken.py"])
        self.assertEqual(len(diagnostics), 1)
        diagnostic = diagnostics[0]
        self.assertEqual(diagnostic.path, "src/pkg/broken.py")
        self.assertEqual(diagnostic.severity, DiagnosticSeverity.ERROR)
        self.assertEqual(diagnostic.source, "python-ast")
        self.assertEqual(diagnostic.code, "SyntaxError")

    def test_untracked_python_is_not_in_workspace_symbols(self) -> None:
        self.root.joinpath("secret.py").write_text(
            "class SecretWidgetParser:\n    pass\n",
            encoding="utf-8",
        )
        symbols = self.provider.workspace_symbols("SecretWidgetParser")
        self.assertEqual(symbols, ())

    def test_tracked_symlink_is_not_followed(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        outside = self.root.parent / f"{self.root.name}-outside-intelligence.py"
        outside.write_text("class ExternalParser:\n    pass\n", encoding="utf-8")
        link = self.root / "src" / "pkg" / "linked.py"
        try:
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            git(self.root, "add", "src/pkg/linked.py")
            git(self.root, "commit", "-qm", "track symlink")
            self.assertEqual(self.provider.workspace_symbols("ExternalParser"), ())
        finally:
            outside.unlink(missing_ok=True)

    def test_scan_file_budget_is_hard_and_deterministic(self) -> None:
        provider = PythonAstCodeIntelligence(
            self.reader,
            settings=PythonIntelligenceSettings(
                max_scan_files=2,
                max_scan_bytes=1024 * 1024,
            ),
        )
        first = provider.workspace_symbols("")
        second = provider.workspace_symbols("")
        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertEqual(
            {symbol.location.path for symbol in first},
            {"src/pkg/models.py"},
        )


if __name__ == "__main__":
    unittest.main()
