from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.context_selection import ContextSelectionError, WorkspaceContextSelector
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


class WorkspaceContextSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")

        package = self.root / "src" / "pkg"
        tests = self.root / "tests"
        package.mkdir(parents=True)
        tests.mkdir()
        package.joinpath("__init__.py").write_text("", encoding="utf-8")
        package.joinpath("models.py").write_text(
            "class WidgetParser:\n    pass\n",
            encoding="utf-8",
        )
        package.joinpath("service.py").write_text(
            "from .models import WidgetParser\n\n"
            "class WidgetService:\n"
            "    parser = WidgetParser()\n",
            encoding="utf-8",
        )
        tests.joinpath("test_service.py").write_text(
            "from pkg.service import WidgetService\n\n"
            "def test_service():\n    assert WidgetService\n",
            encoding="utf-8",
        )
        git(self.root, "add", "src", "tests")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("context-selection-test")
        self.selector = WorkspaceContextSelector(
            self.runtime,
            RepositoryReader(self.root),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task(self, objective: str) -> str:
        goal = self.runtime.create_goal("context selection")
        flow = self.runtime.create_flow(goal)
        return self.runtime.create_task(flow, objective)

    def test_manual_selection_is_unchanged_without_expansion(self) -> None:
        task = self._task("Fix WidgetService")
        result = self.selector.select(
            task,
            selected_paths=["src/pkg/service.py"],
        )
        self.assertEqual(result.mode, "MANUAL")
        self.assertEqual(result.paths, ("src/pkg/service.py",))
        self.assertIsNone(result.lexical)
        self.assertIsNone(result.structural)
        self.assertIsNone(result.semantic)

    def test_auto_selection_uses_existing_lexical_discovery(self) -> None:
        task = self._task("Fix WidgetService")
        result = self.selector.select(task, auto_context=True)
        self.assertEqual(result.mode, "AUTO")
        self.assertIn("src/pkg/service.py", result.paths)
        self.assertIsNotNone(result.lexical)
        self.assertIsNone(result.structural)
        self.assertIsNone(result.semantic)

    def test_structural_expansion_composes_with_manual_seed(self) -> None:
        task = self._task("Fix WidgetService parsing")
        result = self.selector.select(
            task,
            selected_paths=["src/pkg/service.py"],
            structural_context=True,
        )
        self.assertEqual(result.mode, "MANUAL+STRUCTURAL")
        self.assertEqual(result.paths[0], "src/pkg/service.py")
        self.assertIn("src/pkg/models.py", result.paths)
        self.assertIn("tests/test_service.py", result.paths)
        self.assertIsNotNone(result.structural)
        self.assertIsNone(result.semantic)

    def test_structural_expansion_composes_with_auto_selection(self) -> None:
        task = self._task("Fix WidgetService parsing")
        result = self.selector.select(
            task,
            auto_context=True,
            structural_context=True,
        )
        self.assertEqual(result.mode, "AUTO+STRUCTURAL")
        self.assertIn("src/pkg/service.py", result.paths)
        self.assertIn("src/pkg/models.py", result.paths)
        self.assertIsNotNone(result.lexical)
        self.assertIsNotNone(result.structural)
        self.assertIsNone(result.semantic)

    def test_semantic_expansion_uses_deterministic_ast_provider_by_default(self) -> None:
        task = self._task("Repair WidgetParser parse failure")
        result = self.selector.select(
            task,
            selected_paths=["src/pkg/service.py"],
            semantic_context=True,
        )
        self.assertEqual(result.mode, "MANUAL+SEMANTIC")
        self.assertEqual(result.paths[0], "src/pkg/service.py")
        self.assertIn("src/pkg/models.py", result.paths)
        self.assertIsNotNone(result.semantic)
        self.assertIn("widgetparser", result.semantic.query_terms)

    def test_structural_and_semantic_share_one_selection_pipeline(self) -> None:
        task = self._task("Repair WidgetParser in WidgetService")
        result = self.selector.select(
            task,
            selected_paths=["src/pkg/service.py"],
            structural_context=True,
            semantic_context=True,
        )
        self.assertEqual(result.mode, "MANUAL+STRUCTURAL+SEMANTIC")
        self.assertIsNotNone(result.structural)
        self.assertIsNotNone(result.semantic)
        self.assertIn("src/pkg/models.py", result.paths)

    def test_auto_and_manual_are_mutually_exclusive(self) -> None:
        task = self._task("Fix WidgetService")
        with self.assertRaisesRegex(ContextSelectionError, "cannot be combined"):
            self.selector.select(
                task,
                selected_paths=["src/pkg/service.py"],
                auto_context=True,
            )

    def test_seed_paths_require_auto_context(self) -> None:
        task = self._task("Fix WidgetService")
        with self.assertRaisesRegex(ContextSelectionError, "require auto_context"):
            self.selector.select(
                task,
                selected_paths=["src/pkg/service.py"],
                seed_paths=["tests/test_service.py"],
            )

    def test_auto_no_match_remains_empty_even_with_all_expansion_enabled(self) -> None:
        task = self._task("Implement quantum banana telemetry")
        result = self.selector.select(
            task,
            auto_context=True,
            structural_context=True,
            semantic_context=True,
        )
        self.assertEqual(result.paths, ())
        self.assertIsNotNone(result.lexical)
        self.assertIsNone(result.structural)
        self.assertIsNone(result.semantic)


if __name__ == "__main__":
    unittest.main()
