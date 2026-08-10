from __future__ import annotations

import ast
import unittest
from pathlib import Path

from origin_forge.blender_adapter import blender_runner_v1_bytes, blender_runner_v1_fingerprint


class BlenderRunnerV1SourceTests(unittest.TestCase):
    def test_runner_is_content_addressed_and_has_bounded_import_surface(self) -> None:
        raw = blender_runner_v1_bytes()
        self.assertTrue(raw)
        self.assertTrue(blender_runner_v1_fingerprint().startswith("sha256:"))
        tree = ast.parse(raw.decode("utf-8", errors="strict"))
        imported: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
        self.assertEqual(
            imported,
            {"argparse", "bpy", "hashlib", "json", "math", "pathlib", "sys", "__future__"},
        )
        self.assertTrue({"exec", "eval", "compile", "__import__"}.isdisjoint(calls))

    def test_runner_contains_no_process_network_or_dynamic_loader_imports(self) -> None:
        text = blender_runner_v1_bytes().decode("utf-8", errors="strict")
        for forbidden in (
            "import subprocess",
            "import socket",
            "import urllib",
            "import requests",
            "import importlib",
            "--python-expr",
            "--addons",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
