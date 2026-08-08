from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.config import load_config
from origin_forge.model_scheduler import ModelRole


class ConfigV5ResourceModelTests(unittest.TestCase):
    def _write(self, root: Path, content: str) -> None:
        state = root / ".origin-forge"
        state.mkdir()
        state.joinpath("config.toml").write_text(content, encoding="utf-8")

    def test_v4_remains_readable_with_resource_scheduling_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(
                root,
                '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = []
''',
            )
            config = load_config(root)
            self.assertEqual(config.version, 4)
            self.assertFalse(config.resource_models.enabled)
            self.assertIsNone(config.resource_models.capacity)
            self.assertEqual(config.resource_models.profiles, ())
            self.assertEqual(config.resource_models.policies, ())

    def test_resource_sections_require_config_v5_even_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(
                root,
                '''version = 4
[commands]
build = []
test = []
[resources]
enabled = false
''',
            )
            with self.assertRaisesRegex(ValueError, "requires config version 5"):
                load_config(root)

    def test_v5_parses_enabled_capacity_profiles_and_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(
                root,
                '''version = 5
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = []
[resources]
enabled = true
cpu_slots = 16
ram_mib = 65536
max_active_leases = 8
gpus = [
  { device_id = "gpu0", vram_mib = 16384, reserve_vram_mib = 1024, compute_slots = 2 }
]
[models]
profiles = [
  { profile_id = "coder-strong", role = "coder_strong", model_id = "Qwen/Qwen3-Coder-30B-A3B", model_hash = "sha256:abc123", runtime_id = "llamacpp", resources = { cpu_slots = 4, ram_mib = 8192, gpu = { vram_mib = 12288, compute_slots = 1 } } },
  { profile_id = "coder-small", role = "coder_strong", model_id = "Qwen/Qwen3-Coder-14B", runtime_id = "llamacpp", resources = { cpu_slots = 4, ram_mib = 6144, gpu = { vram_mib = 7168, compute_slots = 1 } } }
]
policies = [
  { role = "coder_strong", primary_profile_id = "coder-strong", fallback_profile_ids = ["coder-small"] }
]
''',
            )
            config = load_config(root)
            resource_models = config.resource_models
            self.assertTrue(resource_models.enabled)
            self.assertIsNotNone(resource_models.capacity)
            self.assertEqual(resource_models.capacity.cpu_slots, 16)
            self.assertEqual(resource_models.capacity.ram_mib, 65536)
            self.assertEqual(resource_models.capacity.max_active_leases, 8)
            self.assertEqual(resource_models.capacity.gpus[0].device_id, "gpu0")
            self.assertEqual(resource_models.capacity.gpus[0].usable_vram_mib, 15360)
            self.assertEqual(
                [profile.profile_id for profile in resource_models.profiles],
                ["coder-strong", "coder-small"],
            )
            policy = resource_models.policy(ModelRole.CODER_STRONG)
            self.assertEqual(policy.primary_profile_id, "coder-strong")
            self.assertEqual(policy.fallback_profile_ids, ("coder-small",))

    def test_v5_can_combine_lsp_and_resource_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(
                root,
                '''version = 5
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "python", backend = "podman", image = "python-lsp:local", argv = ["python-lsp", "--stdio"] }
]
[resources]
enabled = true
cpu_slots = 8
ram_mib = 32768
gpus = []
[models]
profiles = [
  { profile_id = "fast", role = "coder_fast", model_id = "local-fast", runtime_id = "llamacpp", resources = { cpu_slots = 2, ram_mib = 4096 } }
]
policies = [
  { role = "coder_fast", primary_profile_id = "fast", fallback_profile_ids = [] }
]
''',
            )
            config = load_config(root)
            self.assertEqual(config.lsp_server("python").backend, "podman")
            self.assertTrue(config.resource_models.enabled)
            self.assertEqual(
                config.resource_models.policy(ModelRole.CODER_FAST).primary_profile_id,
                "fast",
            )


if __name__ == "__main__":
    unittest.main()
