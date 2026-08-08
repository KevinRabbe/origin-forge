from __future__ import annotations

import json
import tempfile
import unicodedata
import unittest
from pathlib import Path

from origin_forge.patches import (
    FileChange,
    FileOperation,
    PatchProposal,
    PatchValidationError,
    parse_patch_proposal,
    validate_patch_preconditions,
)
from origin_forge.path_policy import (
    is_protected_root,
    portable_path_key,
    portable_relative_path,
)
from origin_forge.repository import RepositoryAccessError, RepositoryReader


def create_proposal(*paths: str) -> str:
    return json.dumps(
        {
            "summary": "path security test",
            "changes": [
                {
                    "operation": "CREATE",
                    "path": path,
                    "expected_hash": None,
                    "content": "value = 1\n",
                }
                for path in paths
            ],
            "notes": [],
        }
    )


class PortablePathPolicyTests(unittest.TestCase):
    def test_protected_root_matching_is_case_insensitive(self) -> None:
        for value in (".git", ".GIT", ".Git", ".origin-forge", ".ORIGIN-FORGE"):
            self.assertTrue(is_protected_root(value))
        self.assertFalse(is_protected_root("origin-forge"))

    def test_portable_paths_reject_host_dependent_syntax(self) -> None:
        non_nfc = unicodedata.normalize("NFD", "é") + ".py"
        rejected = (
            r"src\file.py",
            "C:/Windows/system.ini",
            "C:relative.py",
            "//server/share/file.py",
            "/absolute/file.py",
            "src/../file.py",
            "src/./file.py",
            "src//file.py",
            ".GIT/config",
            ".Origin-Forge/config.toml",
            "src/file.py:metadata",
            "NUL.txt",
            "con",
            "COM1.log",
            "lpt9",
            "src/bad?.py",
            "src/trailing.",
            "src/trailing ",
            f"src/{non_nfc}",
        )
        for raw in rejected:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                portable_relative_path(raw)

    def test_portable_path_key_is_case_insensitive(self) -> None:
        self.assertEqual(
            portable_path_key("Src/Widget.py"),
            portable_path_key("src/widget.py"),
        )

    def test_normal_nfc_unicode_path_is_accepted(self) -> None:
        path = portable_relative_path("src/Grüße-猫.py")
        self.assertEqual(path.as_posix(), "src/Grüße-猫.py")


class RepositoryPathSecurityTests(unittest.TestCase):
    def test_repository_reader_rejects_mixed_case_protected_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reader = RepositoryReader(root)
            for raw in (".GIT/config", ".Git/config", ".ORIGIN-FORGE/config.toml"):
                with self.subTest(raw=raw), self.assertRaises(RepositoryAccessError):
                    reader.exists(raw)

    def test_repository_reader_rejects_windows_syntax_on_linux_too(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            reader = RepositoryReader(temp)
            for raw in (
                r"src\file.py",
                "C:/outside.py",
                "C:relative.py",
                "src/file.py:metadata",
                "NUL.txt",
            ):
                with self.subTest(raw=raw), self.assertRaises(RepositoryAccessError):
                    reader.exists(raw)

    def test_symlink_into_mixed_case_protected_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protected = root / ".ORIGIN-FORGE"
            protected.mkdir()
            protected.joinpath("secret.txt").write_text("secret", encoding="utf-8")
            alias = root / "normal"
            try:
                alias.symlink_to(protected, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")

            reader = RepositoryReader(root)
            with self.assertRaises(RepositoryAccessError):
                reader.read_text("normal/secret.txt")

    def test_normal_portable_path_still_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src" / "hello.py"
            source.parent.mkdir()
            source.write_text("print('ok')\n", encoding="utf-8")
            result = RepositoryReader(root).read_text("src/hello.py")
            self.assertEqual(result.path, "src/hello.py")
            self.assertEqual(result.content, "print('ok')\n")


class PatchPathSecurityTests(unittest.TestCase):
    def test_parser_rejects_mixed_case_protected_roots(self) -> None:
        for raw in (".GIT/config", ".Git/config", ".ORIGIN-FORGE/config.toml"):
            with self.subTest(raw=raw), self.assertRaises(PatchValidationError):
                parse_patch_proposal(create_proposal(raw))

    def test_parser_rejects_nonportable_path_syntax(self) -> None:
        for raw in (
            r"src\file.py",
            "C:/outside.py",
            "src/../file.py",
            "src//file.py",
            "src/file.py:metadata",
            "NUL.txt",
        ):
            with self.subTest(raw=raw), self.assertRaises(PatchValidationError):
                parse_patch_proposal(create_proposal(raw))

    def test_parser_rejects_case_colliding_changes(self) -> None:
        with self.assertRaisesRegex(PatchValidationError, "case-colliding"):
            parse_patch_proposal(create_proposal("Src/Widget.py", "src/widget.py"))

    def test_preconditions_revalidate_manually_constructed_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = RepositoryReader(temp)
            proposal = PatchProposal(
                "manual collision",
                (
                    FileChange(FileOperation.CREATE, "Foo.py", None, "a = 1\n"),
                    FileChange(FileOperation.CREATE, "foo.py", None, "b = 2\n"),
                ),
            )
            with self.assertRaisesRegex(PatchValidationError, "case-colliding"):
                validate_patch_preconditions(proposal, repository)

    def test_preconditions_reject_manual_protected_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            proposal = PatchProposal(
                "manual protected target",
                (
                    FileChange(
                        FileOperation.CREATE,
                        ".ORIGIN-FORGE/owned.txt",
                        None,
                        "owned\n",
                    ),
                ),
            )
            with self.assertRaises(PatchValidationError):
                validate_patch_preconditions(proposal, RepositoryReader(temp))


if __name__ == "__main__":
    unittest.main()
