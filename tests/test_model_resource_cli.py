from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.model_resource_cli import build_parser, main


class ModelResourceCliTests(unittest.TestCase):
    def test_cli_surface_is_read_only_and_has_only_status_operation(self) -> None:
        parser = build_parser()
        subparsers = [
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        ]
        self.assertEqual(len(subparsers), 1)
        self.assertEqual(set(subparsers[0].choices), {"status"})

        option_strings = {
            option
            for action in parser._actions
            for option in getattr(action, "option_strings", ())
        }
        for forbidden in (
            "--load",
            "--start",
            "--download",
            "--lease",
            "--release",
            "--model-path",
            "--argv",
            "--image",
            "--set-policy",
        ):
            self.assertNotIn(forbidden, option_strings)

    def test_default_status_is_safe_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = StringIO()
            with redirect_stdout(output):
                code = main(["--project-root", temp, "status"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["config_version"], 6)
            self.assertFalse(payload["enabled"])
            self.assertEqual(payload["profiles"], [])
            self.assertEqual(payload["policies"], [])
            self.assertIsNone(payload["resource_status"])

    def test_enabled_status_reports_configured_capacity_and_explicit_policy(self) -> None:
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

            output = StringIO()
            with redirect_stdout(output):
                code = main(["--project-root", str(root), "status"])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["enabled"])
            self.assertEqual(payload["resource_status"]["cpu_slots"], 12)
            self.assertEqual(payload["resource_status"]["free_cpu_slots"], 12)
            self.assertEqual(payload["resource_status"]["active_lease_count"], 0)
            self.assertEqual(payload["resource_status"]["gpus"][0]["free_vram_mib"], 15360)
            self.assertEqual(
                [profile["profile_id"] for profile in payload["profiles"]],
                ["small", "strong"],
            )
            self.assertEqual(payload["policies"][0]["requested_profile_id"], "strong")
            self.assertEqual(payload["policies"][0]["fallback_profile_ids"], ["small"])
            self.assertEqual(payload["policies"][0]["selected_profile_id"], "strong")
            self.assertFalse(payload["policies"][0]["fallback_would_be_used"])

    def test_invalid_config_returns_structured_failure_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            state.joinpath("config.toml").write_text(
                '''version = 5
[resources]
enabled = true
cpu_slots = 0
ram_mib = 1024
''',
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                code = main(["--project-root", str(root), "status"])
            self.assertEqual(code, 2)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["enabled"])
            self.assertIn("ValueError", payload["error"])


if __name__ == "__main__":
    unittest.main()
