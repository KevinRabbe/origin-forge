from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge import __version__
from origin_forge.doctor import inspect_project
from origin_forge.runtime import OriginForgeRuntime


class DoctorTests(unittest.TestCase):
    def test_package_version_matches_v05_release(self) -> None:
        self.assertEqual(__version__, "0.5.0")

    def test_uninitialized_project_is_diagnosed_without_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = inspect_project(root)
            self.assertFalse(result["ready"])
            self.assertFalse((root / ".origin-forge").exists())

    def test_initialized_project_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            OriginForgeRuntime(root).initialize("doctor-test")
            result = inspect_project(root)
            self.assertTrue(result["ready"])
            self.assertEqual(result["schema_version"], result["expected_schema_version"])

