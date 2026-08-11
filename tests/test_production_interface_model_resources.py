from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.production_interface_html import render_overview
from origin_forge.production_interface_server import ProductionInterfaceRouter
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


_ENABLED_CONFIG = '''version = 5
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
'''


class ProductionInterfaceModelResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        state = self.root / ".origin-forge"
        state.mkdir()
        state.joinpath("config.toml").write_text(_ENABLED_CONFIG, encoding="utf-8")
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-model-resource-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_snapshot_exposes_fresh_non_loading_admission_state(self) -> None:
        before = self.runtime.status()
        snapshot = build_production_interface_snapshot(self.runtime)
        after = self.runtime.status()
        self.assertEqual(before, after)
        status = snapshot.model_resources
        self.assertTrue(status["enabled"])
        self.assertTrue(status["inspection_state_is_fresh"])
        self.assertFalse(status["model_loading_authorized"])
        self.assertFalse(status["resource_leasing_authorized"])
        self.assertFalse(status["routing_mutation_authorized"])
        self.assertEqual(status["resource_status"]["active_lease_count"], 0)  # type: ignore[index]
        self.assertEqual(status["policies"][0]["selected_profile_id"], "strong")  # type: ignore[index]
        authority = snapshot.to_dict()["authority"]
        self.assertFalse(authority["model_loading"])
        self.assertFalse(authority["resource_leasing"])
        self.assertFalse(authority["routing_mutation"])

    def test_html_and_json_label_configuration_without_claiming_loaded_state(self) -> None:
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_overview(snapshot)
        self.assertIn("Model / Resource Monitor", page)
        self.assertIn("strong", page)
        self.assertIn("Fresh inspection state", page)
        self.assertIn("does not mean any model is loaded", page)

        response = ProductionInterfaceRouter(self.runtime).route("GET", "/api/snapshot")
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload["model_resources"]["resource_status"]["active_lease_count"], 0)
        self.assertFalse(payload["model_resources"]["model_loading_authorized"])


if __name__ == "__main__":
    unittest.main()
