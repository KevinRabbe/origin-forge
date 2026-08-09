from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_cli import build_parser, main
from origin_forge.runtime import OriginForgeRuntime


class PixeloramaCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-cli-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.bridge = self.root / "trusted-bridge.gdextension"
        self.bridge.write_bytes(b"governed bridge package")
        self.fingerprint = "sha256:" + hashlib.sha256(self.bridge.read_bytes()).hexdigest()
        self.executable = Path(sys.executable).resolve()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_cli_surface_is_status_only(self) -> None:
        parser = build_parser()
        subparsers = [
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        self.assertEqual(len(subparsers), 1)
        self.assertEqual(set(subparsers[0].choices), {"status"})

    def test_status_verifies_profile_without_launch_or_state_mutation(self) -> None:
        before_runs = self.runtime.list_runs()
        before_artifacts = self.lineage.list_artifacts()
        with patch(
            "origin_forge.pixelorama_bridge.subprocess.Popen",
            side_effect=AssertionError("status must never launch Pixelorama"),
        ):
            code, payload = self._call(
                "status",
                "--bridge-id",
                "origin-forge-pixelorama",
                "--bridge-version",
                "0.1.0",
                "--bridge-fingerprint",
                self.fingerprint,
                "--pixelorama-executable",
                str(self.executable),
                "--bridge-package",
                str(self.bridge),
                "--allow-operation",
                "CREATE_SPRITE_PROJECT",
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "AVAILABLE")
        self.assertEqual(payload["allowed_operations"], ["CREATE_SPRITE_PROJECT"])
        self.assertFalse(payload["editor_launched"])
        self.assertFalse(payload["media_workspace_created"])
        self.assertFalse(payload["project_state_changed"])
        self.assertFalse(payload["model_execution_enabled"])
        self.assertFalse(payload["plugin_install_enabled"])
        self.assertEqual(self.runtime.list_runs(), before_runs)
        self.assertEqual(self.lineage.list_artifacts(), before_artifacts)
        self.assertFalse((self.runtime.state_dir / "media-workspaces").exists())

    def test_fingerprint_mismatch_is_structured_unavailable(self) -> None:
        code, payload = self._call(
            "status",
            "--bridge-id",
            "origin-forge-pixelorama",
            "--bridge-version",
            "0.1.0",
            "--bridge-fingerprint",
            "sha256:" + "0" * 64,
            "--pixelorama-executable",
            str(self.executable),
            "--bridge-package",
            str(self.bridge),
            "--allow-operation",
            "CREATE_SPRITE_PROJECT",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "UNAVAILABLE")
        self.assertIn("fingerprint mismatch", payload["detail"])

    def test_no_mutation_or_install_commands_exist(self) -> None:
        commands = set(
            next(
                action
                for action in build_parser()._actions
                if isinstance(action, argparse._SubParsersAction)
            ).choices
        )
        for forbidden in (
            "run",
            "create",
            "export",
            "adopt",
            "install",
            "download",
            "script",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)


if __name__ == "__main__":
    unittest.main()
