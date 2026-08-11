from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.model_resource_read as read_module
from origin_forge.model_resource_read import inspect_model_resources
from origin_forge.runtime import OriginForgeRuntime


class ModelResourceReadTests(unittest.TestCase):
    def test_default_project_is_safe_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            OriginForgeRuntime(root).initialize("model-resource-read-disabled")
            payload = inspect_model_resources(root)
            self.assertFalse(payload["enabled"])
            self.assertEqual(payload["profiles"], [])
            self.assertEqual(payload["policies"], [])
            self.assertIsNone(payload["resource_status"])
            self.assertTrue(payload["inspection_state_is_fresh"])
            self.assertFalse(payload["model_loading_authorized"])
            self.assertFalse(payload["resource_leasing_authorized"])
            self.assertFalse(payload["routing_mutation_authorized"])

    def test_enabled_inspection_reports_capacity_with_zero_leases(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            state.joinpath("config.toml").write_text(
                '''version = 5
[commands]
build = []
test = []
[resources]
enabled = true
cpu_slots = 12
ram_mib = 49152
max_active_leases = 4
gpus = [
  { device_id = "gpu0", vram_mib = 16384, reserve_vram_mib = 1024, compute_slots = 2 }
]
[models]
profiles = [
  { profile_id = "strong", role = "coder_strong", model_id = "Qwen/Qwen3-Coder-30B-A3B", runtime_id = "llamacpp", resources = { cpu_slots = 4, ram_mib = 8192, gpu = { vram_mib = 12288, compute_slots = 1 } } },
  { profile_id = "small", role = "coder_strong", model_id = "Qwen/Qwen3-Coder-14B", runtime_id = "llamacpp", resources = { cpu_slots = 3, ram_mib = 6144, gpu = { vram_mib = 7168, compute_slots = 1 } } }
]
policies = [
  { role = "coder_strong", primary_profile_id = "strong", fallback_profile_ids = ["small"] }
]
''',
                encoding="utf-8",
            )
            payload = inspect_model_resources(root)
            self.assertTrue(payload["enabled"])
            self.assertEqual(payload["resource_status"]["cpu_slots"], 12)  # type: ignore[index]
            self.assertEqual(payload["resource_status"]["active_lease_count"], 0)  # type: ignore[index]
            self.assertEqual(
                [value["profile_id"] for value in payload["profiles"]],  # type: ignore[index]
                ["small", "strong"],
            )
            self.assertEqual(payload["policies"][0]["selected_profile_id"], "strong")  # type: ignore[index]
            self.assertTrue(payload["inspection_state_is_fresh"])
            self.assertFalse(payload["model_loading_authorized"])
            self.assertFalse(payload["resource_leasing_authorized"])

    def test_facade_has_no_loader_use_or_resource_acquisition_surface(self) -> None:
        source = inspect.getsource(read_module)
        for forbidden in (
            "ModelAdapter",
            "runtime_loader",
            ".acquire(",
            ".release(",
            ".load(",
            ".use(",
            "subprocess",
            "download",
            "set_policy",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
