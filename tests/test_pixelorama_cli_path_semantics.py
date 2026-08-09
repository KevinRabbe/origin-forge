from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from origin_forge.pixelorama_cli_export import (
    PixeloramaCliExportAdapter,
    PixeloramaCliExportRequest,
    PixeloramaCliIntegrityError,
    PixeloramaCliProfile,
)
from origin_forge.runtime import OriginForgeRuntime


class PixeloramaCliPathSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-cli-path-semantics")
        self.executable = self.root / "Pixelorama"
        self.executable.write_bytes(b"fixture executable")
        executable_hash = "sha256:" + hashlib.sha256(
            self.executable.read_bytes()
        ).hexdigest()
        self.profile = PixeloramaCliProfile(
            pixelorama_executable=self.executable,
            pixelorama_fingerprint=executable_hash,
            expected_pixelorama_version="v1.2-stable",
        )
        self.adapter = PixeloramaCliExportAdapter(self.runtime, self.profile)
        self.source = self.root / "source.pxo"
        self.source.write_bytes(b"opaque project")
        self.source_hash = "sha256:" + hashlib.sha256(
            self.source.read_bytes()
        ).hexdigest()
        self.request = PixeloramaCliExportRequest.create(
            source_hash=self.source_hash,
            source_byte_count=self.source.stat().st_size,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_isolated_environment_pins_pwd_to_exact_media_workspace(self) -> None:
        workspace = self.adapter._workspace(self.request)
        env = self.adapter._isolated_environment(workspace)
        self.assertEqual(env["PWD"], str(workspace))
        self.assertEqual(Path(env["HOME"]).parent, workspace / "runtime")

    def test_missing_declared_output_is_not_misclassified_as_escape(self) -> None:
        workspace = self.adapter._workspace(self.request)
        self.adapter._stage_source(self.request, self.source, workspace)
        self.adapter._validate_workspace_containment(workspace, self.request)
        output = workspace / self.request.output_relative_path
        self.assertFalse(output.exists())

    def test_declared_output_symlink_still_fails_closed(self) -> None:
        workspace = self.adapter._workspace(self.request)
        self.adapter._stage_source(self.request, self.source, workspace)
        target = workspace / "runtime" / "redirect.png"
        target.write_bytes(b"not an export")
        output = workspace / self.request.output_relative_path
        output.symlink_to(target)
        with self.assertRaisesRegex(PixeloramaCliIntegrityError, "may not be a symlink"):
            self.adapter._validate_workspace_containment(workspace, self.request)


if __name__ == "__main__":
    unittest.main()
