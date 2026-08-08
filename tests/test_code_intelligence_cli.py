from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from origin_forge.code_intelligence_cli import build_parser, main
from origin_forge.runtime import OriginForgeRuntime


class CodeIntelligenceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("code-intelligence-cli-test")
        self.runtime.state_dir.joinpath("config.toml").write_text(
            '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "python", backend = "podman", image = "python-lsp:local", argv = ["python-lsp", "--stdio"], network = false }
]
''',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_cli_surface_has_no_raw_image_argv_or_method_options(self) -> None:
        parser = build_parser()
        text = parser.format_help()
        self.assertNotIn("--image", text)
        self.assertNotIn("--argv", text)
        self.assertNotIn("--method", text)
        self.assertNotIn("--query", text)

    def test_list_exposes_only_safe_server_metadata(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), "list"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(
            payload["servers"],
            [
                {
                    "server_id": "python",
                    "backend": "podman",
                    "network_allowed": False,
                }
            ],
        )
        self.assertNotIn("image", payload["servers"][0])
        self.assertNotIn("argv", payload["servers"][0])

    def test_status_probes_configured_backend_only(self) -> None:
        backend = Mock()
        backend.available.return_value = True
        backend.provenance = {
            "backend": "podman-lsp",
            "server_id": "python",
            "resolved_image_id": "sha256:test",
        }
        output = StringIO()
        with patch(
            "origin_forge.code_intelligence_cli.create_configured_lsp_backend",
            return_value=backend,
        ) as factory, redirect_stdout(output):
            code = main(
                ["--project-root", str(self.root), "status", "python"]
            )
        self.assertEqual(code, 0)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.args[1], "python")
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["available"])
        self.assertEqual(payload["server_id"], "python")

    def test_unknown_server_is_safe_failure(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                ["--project-root", str(self.root), "status", "missing"]
            )
        self.assertEqual(code, 2)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["available"])
        self.assertIn("unknown configured LSP server", payload["error"])


if __name__ == "__main__":
    unittest.main()
