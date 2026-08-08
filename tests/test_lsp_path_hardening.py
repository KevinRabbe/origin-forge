from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.lsp_client import LspWorkspaceError, LspWorkspaceMapper


class LspPathHardeningTests(unittest.TestCase):
    def test_mixed_case_protected_roots_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mapper = LspWorkspaceMapper(root)
            for raw in (".GIT/config", ".Git/config", ".ORIGIN-FORGE/project.db"):
                with self.subTest(raw=raw), self.assertRaises(LspWorkspaceError):
                    mapper.path_to_uri(raw)

    def test_localhost_file_uri_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "hello.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            mapper = LspWorkspaceMapper(root)

            uri = source.as_uri()
            self.assertTrue(uri.startswith("file:///"))
            localhost_uri = "file://LOCALHOST" + uri[len("file://") :]
            self.assertEqual(mapper.uri_to_path(localhost_uri), "hello.py")

    def test_symlink_into_mixed_case_protected_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protected = root / ".ORIGIN-FORGE"
            protected.mkdir()
            protected.joinpath("secret.py").write_text("SECRET = 1\n", encoding="utf-8")
            alias = root / "normal.py"
            try:
                alias.symlink_to(protected / "secret.py")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")

            mapper = LspWorkspaceMapper(root)
            with self.assertRaises(LspWorkspaceError):
                mapper.path_to_uri("normal.py")


if __name__ == "__main__":
    unittest.main()
