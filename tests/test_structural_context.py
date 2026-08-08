from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.structural_context import (
    PythonStructuralContext,
    StructuralContextError,
    StructuralSettings,
)


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class StructuralContextTests(unittest.TestCase):
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
            "class WidgetParser:\n"
            "    def parse(self, value):\n"
            "        return value\n",
            encoding="utf-8",
        )
        package.joinpath("service.py").write_text(
            "from .models import WidgetParser\n\n"
            "class WidgetService:\n"
            "    def __init__(self):\n"
            "        self.parser = WidgetParser()\n",
            encoding="utf-8",
        )
        package.joinpath("unrelated.py").write_text(
            "class InventoryWriter:\n    pass\n",
            encoding="utf-8",
        )
        tests.joinpath("test_service.py").write_text(
            "from pkg.service import WidgetService\n\n"
            "def test_service():\n"
            "    assert WidgetService()\n",
            encoding="utf-8",
        )
        git(self.root, "add", "src", "tests")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("structural-context-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task(self, objective: str) -> str:
        goal = self.runtime.create_goal("structural context")
        flow = self.runtime.create_flow(goal)
        return self.runtime.create_task(flow, objective)

    def _expander(self, **settings) -> PythonStructuralContext:
        return PythonStructuralContext(
            self.runtime,
            RepositoryReader(self.root),
            settings=StructuralSettings(**settings) if settings else None,
        )

    def test_seed_expands_to_test_and_direct_dependency(self) -> None:
        task = self._task("Fix WidgetService parsing")
        result = self._expander().expand(task, ["src/pkg/service.py"])

        self.assertEqual(result.paths[0], "src/pkg/service.py")
        self.assertIn("tests/test_service.py", result.paths)
        self.assertIn("src/pkg/models.py", result.paths)
        by_path = {candidate.path: candidate for candidate in result.added}
        self.assertTrue(
            any(reason.startswith("test-pair:") for reason in by_path["tests/test_service.py"].reasons)
        )
        self.assertTrue(
            any(reason.startswith("imported-by:") for reason in by_path["src/pkg/models.py"].reasons)
        )

    def test_reverse_import_expands_to_importer(self) -> None:
        task = self._task("Change WidgetParser")
        result = self._expander().expand(task, ["src/pkg/models.py"])
        by_path = {candidate.path: candidate for candidate in result.added}
        self.assertIn("src/pkg/service.py", by_path)
        self.assertTrue(
            any(reason.startswith("imports:") for reason in by_path["src/pkg/service.py"].reasons)
        )

    def test_task_symbol_can_add_definition_file(self) -> None:
        task = self._task("Repair WidgetParser behavior")
        result = self._expander().expand(task, ["src/pkg/unrelated.py"])
        by_path = {candidate.path: candidate for candidate in result.added}
        self.assertIn("src/pkg/models.py", by_path)
        self.assertTrue(
            any(reason.startswith("task-symbol:") for reason in by_path["src/pkg/models.py"].reasons)
        )

    def test_untracked_python_file_is_not_indexed(self) -> None:
        self.root.joinpath("secret.py").write_text(
            "class WidgetParser:\n    pass\n", encoding="utf-8"
        )
        task = self._task("Repair WidgetParser")
        result = self._expander().expand(task, ["src/pkg/unrelated.py"])
        self.assertNotIn("secret.py", result.paths)

    def test_syntax_error_is_skipped_counted_and_bounded(self) -> None:
        broken = self.root / "src" / "pkg" / "broken.py"
        broken.write_text("def nope(:\n", encoding="utf-8")
        git(self.root, "add", "src/pkg/broken.py")
        git(self.root, "commit", "-qm", "broken fixture")

        task = self._task("Fix WidgetService")
        result = self._expander().expand(task, ["src/pkg/service.py"])
        self.assertEqual(result.parse_failures, 1)
        self.assertNotIn("src/pkg/broken.py", result.paths)

        bounded = self._expander(
            max_scan_files=100,
            max_scan_bytes=40,
            max_files=10,
            max_total_bytes=4096,
        ).expand(task, ["src/pkg/service.py"])
        self.assertLessEqual(bounded.indexed_bytes, 40)

    def test_tracked_symlink_is_not_followed(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        outside = self.root.parent / f"{self.root.name}-outside-structural.py"
        outside.write_text("class WidgetParser:\n    pass\n", encoding="utf-8")
        link = self.root / "src" / "pkg" / "linked.py"
        try:
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            git(self.root, "add", "src/pkg/linked.py")
            git(self.root, "commit", "-qm", "track symlink")
            task = self._task("WidgetParser")
            result = self._expander().expand(task, ["src/pkg/unrelated.py"])
            self.assertNotIn("src/pkg/linked.py", result.paths)
        finally:
            outside.unlink(missing_ok=True)

    def test_file_budget_keeps_seed_and_limits_additions(self) -> None:
        task = self._task("WidgetService WidgetParser")
        result = self._expander(max_files=2, max_total_bytes=4096).expand(
            task,
            ["src/pkg/service.py"],
        )
        self.assertEqual(len(result.paths), 2)
        self.assertEqual(result.paths[0], "src/pkg/service.py")

    def test_seed_budget_failure_is_explicit(self) -> None:
        task = self._task("anything")
        with self.assertRaisesRegex(StructuralContextError, "file budget"):
            self._expander(max_files=1).expand(
                task,
                ["src/pkg/service.py", "src/pkg/models.py"],
            )

    def test_expansion_is_deterministic(self) -> None:
        task = self._task("Fix WidgetService parsing")
        expander = self._expander()
        first = expander.expand(task, ["src/pkg/service.py"])
        second = expander.expand(task, ["src/pkg/service.py"])
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
