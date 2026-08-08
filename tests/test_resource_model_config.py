from __future__ import annotations

import unittest

from origin_forge.model_scheduler import ModelRole
from origin_forge.resource_model_config import (
    MAX_CONFIGURED_GPUS,
    MAX_MODEL_PROFILES,
    parse_resource_model_config,
)


class ResourceModelConfigTests(unittest.TestCase):
    def _resources(self):
        return {
            "enabled": True,
            "cpu_slots": 16,
            "ram_mib": 32768,
            "max_active_leases": 16,
            "gpus": [
                {
                    "device_id": "gpu0",
                    "vram_mib": 16384,
                    "reserve_vram_mib": 1024,
                    "compute_slots": 1,
                }
            ],
        }

    def _models(self):
        return {
            "profiles": [
                {
                    "profile_id": "coder-strong",
                    "role": "coder_strong",
                    "model_id": "qwen-strong",
                    "runtime_id": "llamacpp-strong",
                    "model_hash": "sha256:strong",
                    "resources": {
                        "cpu_slots": 2,
                        "ram_mib": 4096,
                        "gpu": {
                            "vram_mib": 20000,
                            "compute_slots": 1,
                            "exclusive": True,
                        },
                    },
                },
                {
                    "profile_id": "coder-strong-small",
                    "role": "coder_strong",
                    "model_id": "qwen-small",
                    "runtime_id": "llamacpp-small",
                    "resources": {
                        "cpu_slots": 2,
                        "ram_mib": 4096,
                        "gpu": {
                            "vram_mib": 8192,
                            "compute_slots": 1,
                        },
                    },
                },
                {
                    "profile_id": "coder-fast",
                    "role": "coder_fast",
                    "model_id": "qwen-fast",
                    "runtime_id": "llamacpp-fast",
                    "resources": {"cpu_slots": 4, "ram_mib": 8192},
                },
            ],
            "policies": [
                {
                    "role": "coder_strong",
                    "primary_profile_id": "coder-strong",
                    "fallback_profile_ids": ["coder-strong-small"],
                },
                {
                    "role": "coder_fast",
                    "primary_profile_id": "coder-fast",
                    "fallback_profile_ids": [],
                },
            ],
        }

    def test_missing_sections_are_safe_disabled_default(self) -> None:
        config = parse_resource_model_config(None, None)
        self.assertFalse(config.enabled)
        self.assertIsNone(config.capacity)
        self.assertEqual(config.profiles, ())
        self.assertEqual(config.policies, ())

    def test_explicit_disabled_empty_sections_are_allowed(self) -> None:
        config = parse_resource_model_config(
            {"enabled": False, "gpus": []},
            {"profiles": [], "policies": []},
        )
        self.assertFalse(config.enabled)

    def test_disabled_config_cannot_hide_active_capacity_or_models(self) -> None:
        with self.assertRaisesRegex(ValueError, "disabled resources"):
            parse_resource_model_config(
                {"enabled": False, "cpu_slots": 8},
                None,
            )
        with self.assertRaisesRegex(ValueError, "require resources.enabled"):
            parse_resource_model_config(
                {"enabled": False},
                {"profiles": [self._models()["profiles"][0]]},
            )

    def test_enabled_config_builds_capacity_profiles_and_policies(self) -> None:
        config = parse_resource_model_config(self._resources(), self._models())
        self.assertTrue(config.enabled)
        self.assertEqual(config.capacity.cpu_slots, 16)
        self.assertEqual(config.capacity.ram_mib, 32768)
        self.assertEqual(config.capacity.max_active_leases, 16)
        self.assertEqual(config.capacity.gpus[0].usable_vram_mib, 15360)
        self.assertEqual(
            [profile.profile_id for profile in config.registry().all()],
            ["coder-fast", "coder-strong", "coder-strong-small"],
        )
        strong = config.policy(ModelRole.CODER_STRONG)
        self.assertEqual(strong.primary_profile_id, "coder-strong")
        self.assertEqual(strong.fallback_profile_ids, ("coder-strong-small",))

    def test_statically_too_large_primary_is_allowed_for_explicit_fallback(self) -> None:
        config = parse_resource_model_config(self._resources(), self._models())
        strong = config.registry().profile("coder-strong")
        self.assertGreater(
            strong.resources.gpu.vram_mib,
            config.capacity.gpus[0].usable_vram_mib,
        )
        self.assertEqual(
            config.policy(ModelRole.CODER_STRONG).fallback_profile_ids,
            ("coder-strong-small",),
        )

    def test_unknown_fields_fail_closed(self) -> None:
        resources = self._resources()
        resources["mystery"] = True
        with self.assertRaisesRegex(ValueError, "resources has unknown fields"):
            parse_resource_model_config(resources, self._models())

        models = self._models()
        models["download_url"] = "https://example.com/model"
        with self.assertRaisesRegex(ValueError, "models has unknown fields"):
            parse_resource_model_config(self._resources(), models)

    def test_gpu_count_is_bounded_before_capacity_construction(self) -> None:
        resources = self._resources()
        resources["gpus"] = [
            {
                "device_id": f"gpu{index}",
                "vram_mib": 1024,
            }
            for index in range(MAX_CONFIGURED_GPUS + 1)
        ]
        with self.assertRaisesRegex(ValueError, "exceeds count limit"):
            parse_resource_model_config(resources, {"profiles": [], "policies": []})

    def test_profile_count_is_bounded(self) -> None:
        models = {
            "profiles": [
                {
                    "profile_id": f"profile-{index}",
                    "role": "coder_fast",
                    "model_id": f"model-{index}",
                    "runtime_id": "runtime",
                    "resources": {"cpu_slots": 1},
                }
                for index in range(MAX_MODEL_PROFILES + 1)
            ],
            "policies": [],
        }
        with self.assertRaisesRegex(ValueError, "profiles exceeds count limit"):
            parse_resource_model_config(self._resources(), models)

    def test_duplicate_profile_ids_fail_closed(self) -> None:
        models = self._models()
        models["profiles"][1]["profile_id"] = "coder-strong"
        with self.assertRaisesRegex(ValueError, "duplicate profile IDs"):
            parse_resource_model_config(self._resources(), models)

    def test_policy_must_reference_existing_profiles(self) -> None:
        models = self._models()
        models["policies"][0]["fallback_profile_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "unknown model profile"):
            parse_resource_model_config(self._resources(), models)

    def test_policy_cannot_cross_roles(self) -> None:
        models = self._models()
        models["policies"][0]["fallback_profile_ids"] = ["coder-fast"]
        with self.assertRaisesRegex(ValueError, "does not match profiles"):
            parse_resource_model_config(self._resources(), models)

    def test_duplicate_policy_role_is_rejected(self) -> None:
        models = self._models()
        models["policies"].append(
            {
                "role": "coder_strong",
                "primary_profile_id": "coder-strong-small",
                "fallback_profile_ids": [],
            }
        )
        with self.assertRaisesRegex(ValueError, "duplicate model policy role"):
            parse_resource_model_config(self._resources(), models)

    def test_resource_request_unknown_fields_and_invalid_types_fail_closed(self) -> None:
        models = self._models()
        models["profiles"][0]["resources"]["shell"] = "run model"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            parse_resource_model_config(self._resources(), models)

        resources = self._resources()
        resources["cpu_slots"] = True
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            parse_resource_model_config(resources, self._models())

    def test_gpu_request_can_be_pinned_and_exclusive(self) -> None:
        models = self._models()
        models["profiles"][1]["resources"]["gpu"]["device_id"] = "gpu0"
        models["profiles"][1]["resources"]["gpu"]["exclusive"] = True
        config = parse_resource_model_config(self._resources(), models)
        gpu = config.registry().profile("coder-strong-small").resources.gpu
        self.assertEqual(gpu.device_id, "gpu0")
        self.assertTrue(gpu.exclusive)


if __name__ == "__main__":
    unittest.main()
