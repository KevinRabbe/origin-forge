from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.code_intelligence_factory import create_configured_lsp_backend
from origin_forge.runtime import OriginForgeRuntime


class CodeIntelligenceFactoryTests(unittest.TestCase):
    def test_configured_server_id_builds_exact_podman_spec_without_starting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("factory-test")
            (root / ".origin-forge" / "config.toml").write_text(
                '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "pyright", backend = "podman", image = "origin-forge/pyright:local", argv = ["pyright-langserver", "--stdio"], podman_executable = "podman", network = false, memory = "1g", cpus = 1.25, pids_limit = 48, request_timeout_seconds = 3, max_protocol_message_bytes = 32768 }
]
''',
                encoding="utf-8",
            )

            backend = create_configured_lsp_backend(runtime, "pyright")

            self.assertEqual(backend.spec.server_id, "pyright")
            self.assertEqual(backend.spec.image, "origin-forge/pyright:local")
            self.assertEqual(backend.spec.argv, ("pyright-langserver", "--stdio"))
            self.assertFalse(backend.spec.network_allowed)
            self.assertEqual(backend.spec.memory, "1g")
            self.assertEqual(backend.spec.cpus, 1.25)
            self.assertEqual(backend.spec.pids_limit, 48)
            self.assertEqual(backend.spec.request_timeout_seconds, 3.0)
            self.assertEqual(backend.spec.max_protocol_message_bytes, 32768)
            self.assertIsNone(backend.provenance["resolved_image_id"])

    def test_unknown_server_id_is_rejected_before_any_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("factory-test")
            with self.assertRaises(KeyError):
                create_configured_lsp_backend(runtime, "not-configured")


if __name__ == "__main__":
    unittest.main()
