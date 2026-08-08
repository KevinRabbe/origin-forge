from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.code_intelligence import (
    CodeIntelligenceCapabilities,
    CodeLocation,
    CodeSymbol,
    SymbolKind,
    TextPosition,
    TextRange,
)
from origin_forge.code_intelligence_context import (
    CodeIntelligenceContextError,
    CodeIntelligenceContextExpander,
    CodeIntelligenceContextSettings,
)
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def location(path: str) -> CodeLocation:
    return CodeLocation(
        path,
        TextRange(TextPosition(0, 0), TextPosition(0, 1)),
    )


class FakeProvider:
    provider_id = "fake-intelligence"

    def __init__(self, symbols: dict[str, tuple[CodeSymbol, ...]], *, available: bool = True):
        self.symbols = symbols
        self._available = available
        self.capabilities = CodeIntelligenceCapabilities(
            workspace_symbols=True,
            definitions=True,
            references=True,
            diagnostics=True,
        )
        self.queries: list[tuple[str, int]] = []

    def available(self) -> bool:
        return self._available

    def workspace_symbols(self, query: str, *, limit: int = 50):
        self.queries.append((query, limit))
        return self.symbols.get(query, ())[:limit]

    def definitions(self, path, position, *, limit=20):
        return ()

    def references(self, path, position, *, include_declaration=True, limit=100):
        return ()

    def diagnostics(self, paths, *, limit_per_file=100):
        return ()


class CodeIntelligenceContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "service.py").write_text(
            "def run_service():\n    return True\n",
            encoding="utf-8",
        )
        (self.root / "src" / "payments.py").write_text(
            "class PaymentCoordinator:\n"
            "    def refund_invoice(self):\n"
            "        return True\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_payments.py").write_text(
            "def test_refund_invoice():\n    assert True\n",
            encoding="utf-8",
        )
        git(self.root, "add", "src", "tests")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("semantic-context-test")
        goal = self.runtime.create_goal("semantic context")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(
            flow,
            "Fix PaymentCoordinator refund invoice behavior",
            acceptance_criteria=["refund invoice test passes"],
            required_capabilities=["code-edit"],
        )
        self.reader = RepositoryReader(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_task_relevant_workspace_symbol_adds_tracked_file(self) -> None:
        provider = FakeProvider(
            {
                "payment": (
                    CodeSymbol(
                        "PaymentCoordinator",
                        SymbolKind.CLASS,
                        location("src/payments.py"),
                    ),
                ),
                "refund": (
                    CodeSymbol(
                        "refund_invoice",
                        SymbolKind.METHOD,
                        location("src/payments.py"),
                        "PaymentCoordinator",
                    ),
                    CodeSymbol(
                        "test_refund_invoice",
                        SymbolKind.FUNCTION,
                        location("tests/test_payments.py"),
                    ),
                ),
            }
        )
        result = CodeIntelligenceContextExpander(
            self.runtime,
            self.reader,
            provider,
        ).expand(self.task, ["src/service.py"])

        self.assertEqual(result.paths[0], "src/service.py")
        self.assertIn("src/payments.py", result.paths)
        self.assertIn("tests/test_payments.py", result.paths)
        by_path = {item.path: item for item in result.added}
        self.assertGreater(by_path["src/payments.py"].score, 0)
        self.assertTrue(
            any(reason.startswith("symbol:refund:") for reason in by_path["src/payments.py"].reasons)
        )

    def test_untracked_provider_location_is_ignored(self) -> None:
        self.root.joinpath("secret.py").write_text("class PaymentCoordinator: pass\n", encoding="utf-8")
        provider = FakeProvider(
            {
                "payment": (
                    CodeSymbol(
                        "PaymentCoordinator",
                        SymbolKind.CLASS,
                        location("secret.py"),
                    ),
                )
            }
        )
        result = CodeIntelligenceContextExpander(
            self.runtime,
            self.reader,
            provider,
        ).expand(self.task, ["src/service.py"])
        self.assertNotIn("secret.py", result.paths)

    def test_query_and_file_budgets_are_hard(self) -> None:
        provider = FakeProvider(
            {
                "refund": (
                    CodeSymbol(
                        "refund_invoice",
                        SymbolKind.METHOD,
                        location("src/payments.py"),
                    ),
                    CodeSymbol(
                        "test_refund_invoice",
                        SymbolKind.FUNCTION,
                        location("tests/test_payments.py"),
                    ),
                )
            }
        )
        result = CodeIntelligenceContextExpander(
            self.runtime,
            self.reader,
            provider,
            settings=CodeIntelligenceContextSettings(
                max_queries=1,
                max_symbols_per_query=1,
                max_files=2,
                max_total_bytes=4096,
            ),
        ).expand(self.task, ["src/service.py"])
        self.assertEqual(len(provider.queries), 1)
        self.assertEqual(provider.queries[0][1], 1)
        self.assertLessEqual(len(result.paths), 2)

    def test_unavailable_provider_fails_explicitly(self) -> None:
        provider = FakeProvider({}, available=False)
        with self.assertRaisesRegex(CodeIntelligenceContextError, "unavailable"):
            CodeIntelligenceContextExpander(
                self.runtime,
                self.reader,
                provider,
            ).expand(self.task, ["src/service.py"])

    def test_untracked_seed_is_rejected(self) -> None:
        untracked = self.root / "notes.py"
        untracked.write_text("VALUE = 1\n", encoding="utf-8")
        provider = FakeProvider({})
        with self.assertRaisesRegex(CodeIntelligenceContextError, "not tracked"):
            CodeIntelligenceContextExpander(
                self.runtime,
                self.reader,
                provider,
            ).expand(self.task, ["notes.py"])

    def test_repeated_expansion_is_deterministic(self) -> None:
        provider = FakeProvider(
            {
                "payment": (
                    CodeSymbol(
                        "PaymentCoordinator",
                        SymbolKind.CLASS,
                        location("src/payments.py"),
                    ),
                )
            }
        )
        expander = CodeIntelligenceContextExpander(
            self.runtime,
            self.reader,
            provider,
        )
        first = expander.expand(self.task, ["src/service.py"])
        second = expander.expand(self.task, ["src/service.py"])
        self.assertEqual(first.paths, second.paths)
        self.assertEqual(first.added, second.added)


if __name__ == "__main__":
    unittest.main()
