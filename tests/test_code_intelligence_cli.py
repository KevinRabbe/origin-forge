from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from origin_forge.code_intelligence_cli import main
from origin_forge.runtime import OriginForgeRuntime


class CodeIntelligenceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        runtime = OriginForgeRuntime(self.root)
        runtime.initialize("cli-test")
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "pyright", backend = "podman", image = "origin-forge/pyright:local", argv = ["pyright-langserver", "--stdio"], network = false }
]
''',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_list_exposes_only_configured_identity_policy(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), "list"])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(
            payload,
            {
                "servers": [
                    {
                        "server_id": "pyright",
                        "backend": "podman",
                        "network_allowed": False,
                    }
                ]
            },
        )
        self.assertNotIn("image", output.getvalue())
        self.assertNotIn("argv", output.getvalue())

    def test_status_probes_configured_backend_only(self) -> None:
        output = io.StringIO()
        with patch(
            "origin_forge.podman_lsp.PodmanLspBackend.available",
            return_value=True,
        ), redirect_stdout(output):
            code = main(
                ["--project-root", str(self.root), "status", "pyright"]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["server_id"], "pyright")
        self.assertEqual(payload["provenance"]["configured_image"], "origin-forge/pyright:local")

    def test_unknown_server_id_fails_without_probe(self) -> None:
        output = io.StringIO()
        with patch(
            "origin_forge.podman_lsp.PodmanLspBackend.available"
        ) as available, redirect_stdout(output):
            code = main(
                ["--project-root", str(self.root), "status", "not-configured"]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(payload["available"])
        available.assert_not_called()


if __name__ == "__main__":
    unittest.main()
