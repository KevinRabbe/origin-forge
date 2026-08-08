from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.repository import RepositoryAccessError, RepositoryReader


class RepositorySnapshotPortabilityTests(unittest.TestCase):
    def test_snapshot_rejects_case_colliding_files_when_host_can_represent_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upper = root / "Widget.py"
            lower = root / "widget.py"
            upper.write_text("UPPER = True\n", encoding="utf-8")

            # On case-insensitive filesystems the second spelling already names
            # the first file, so the host itself prevents constructing this
            # non-portable repository fixture.
            if lower.exists():
                self.skipTest("filesystem is case-insensitive")

            lower.write_text("LOWER = True\n", encoding="utf-8")
            reader = RepositoryReader(root)
            with self.assertRaisesRegex(RepositoryAccessError, "case-colliding"):
                reader.snapshot(["Widget.py", "widget.py"])

    def test_snapshot_deduplicates_identical_path_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "hello.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            result = RepositoryReader(root).snapshot(["hello.py", "hello.py"])
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].path, "hello.py")


if __name__ == "__main__":
    unittest.main()
