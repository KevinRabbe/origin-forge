from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.config import load_config
from origin_forge.podman_sandbox import PodmanSandboxBackend
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.sandbox import UnconfiguredSandboxBackend
from origin_forge.sandbox_factory import create_sandbox_backend


class SandboxFactoryTests(unittest.TestCase):
    def test_default_config_selects_non_executable_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("factory")
            backend = create_sandbox_backend(runtime, load_config(root))
            self.assertIsInstance(backend, UnconfiguredSandboxBackend)

    def test_podman_config_constructs_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("factory")
            (root / ".origin-forge" / "config.toml").write_text(
                '''version = 3\n[sandbox]\nbackend = "podman"\nimage = "example/test:local"\nnetwork = false\nmemory = "1g"\ncpus = 1.5\npids_limit = 64\n[commands]\nbuild = []\ntest = []\n''',
                encoding="utf-8",
            )
            config = load_config(root)
            backend = create_sandbox_backend(runtime, config)
            self.assertIsInstance(backend, PodmanSandboxBackend)
            self.assertEqual(backend.settings.image, "example/test:local")
            self.assertEqual(backend.settings.memory, "1g")
            self.assertEqual(backend.settings.cpus, 1.5)
            self.assertEqual(backend.settings.pids_limit, 64)

    def test_podman_requires_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("factory")
            (root / ".origin-forge" / "config.toml").write_text(
                '''version = 3\n[sandbox]\nbackend = "podman"\nimage = ""\n[commands]\nbuild = []\ntest = []\n''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "requires sandbox.image"):
                create_sandbox_backend(runtime, load_config(root))


if __name__ == "__main__":
    unittest.main()
