from __future__ import annotations

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
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class StructuralGitEnumerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("structural-git-enumeration")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _expander(self, **settings) -> PythonStructuralContext:
        return PythonStructuralContext(
            self.runtime,
            RepositoryReader(self.root),
            settings=StructuralSettings(**settings),
        )

    def test_git_enumeration_requests_only_python_and_caps_retained_paths(self) -> None:
        self.root.joinpath("a.py").write_text("A = 1\n", encoding="utf-8")
        self.root.joinpath("b.py").write_text("B = 1\n", encoding="utf-8")
        self.root.joinpath("large-not-python.txt").write_text(
            "x" * 10000,
            encoding="utf-8",
        )
        git(self.root, "add", "a.py", "b.py", "large-not-python.txt")
        git(self.root, "commit", "-qm", "fixtures")

        paths = self._expander(
            max_scan_files=1,
            max_scan_bytes=1024,
            max_files=4,
            max_total_bytes=4096,
            max_git_output_bytes=1024,
        )._tracked_python_paths()

        self.assertEqual(paths, ("a.py",))

    def test_git_enumeration_output_overflow_fails_closed(self) -> None:
        path = "this_is_a_deliberately_long_python_filename.py"
        self.root.joinpath(path).write_text("VALUE = 1\n", encoding="utf-8")
        git(self.root, "add", path)
        git(self.root, "commit", "-qm", "long path")

        with self.assertRaisesRegex(
            StructuralContextError,
            "enumeration byte limit",
        ):
            self._expander(
                max_scan_files=100,
                max_scan_bytes=1024,
                max_files=4,
                max_total_bytes=4096,
                max_git_output_bytes=8,
            )._tracked_python_paths()

    def test_structural_git_limits_validate_positive_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_git_output_bytes"):
            StructuralSettings(max_git_output_bytes=0)
        with self.assertRaisesRegex(ValueError, "max_git_stderr_bytes"):
            StructuralSettings(max_git_stderr_bytes=0)


if __name__ == "__main__":
    unittest.main()
