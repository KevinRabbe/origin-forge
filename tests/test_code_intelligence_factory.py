from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.code_intelligence_factory import create_configured_lsp_backend
from origin_forge.runtime import OriginForgeRuntime


class ConfiguredLspFactoryTests(unittest.TestCase):
    def test_factory_uses_protected_config_and_only_configured_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("lsp-factory-test")
            configured_podman = root / "tools" / "podman.exe"
            configured_podman.parent.mkdir()
            configured_podman.write_bytes(b"configured podman")
            config_text = '''version = 4
[commands]
build = []
test = []
[tools]
podman = "__PODMAN_PATH__"
[code_intelligence]
lsp_servers = [
  { server_id = "python", backend = "podman", image = "python-lsp:local", argv = ["python-lsp", "--stdio"], network = false, memory = "1g", cpus = 1.25, pids_limit = 64 }
]
'''.replace("__PODMAN_PATH__", configured_podman.as_posix())
            runtime.state_dir.joinpath("config.toml").write_text(
                config_text,
                encoding="utf-8",
            )

            backend = create_configured_lsp_backend(runtime, "python")

            self.assertEqual(backend.spec.server_id, "python")
            self.assertEqual(backend.spec.image, "python-lsp:local")
            self.assertEqual(backend.spec.argv, ("python-lsp", "--stdio"))
            self.assertFalse(backend.spec.network_allowed)
            self.assertEqual(backend.spec.memory, "1g")
            self.assertEqual(backend.spec.cpus, 1.25)
            self.assertEqual(backend.spec.pids_limit, 64)
            self.assertEqual(backend.spec.podman_executable, str(configured_podman))

            with self.assertRaises(KeyError):
                create_configured_lsp_backend(runtime, "not-configured")


if __name__ == "__main__":
    unittest.main()
