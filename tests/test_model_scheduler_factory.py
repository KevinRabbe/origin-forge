from __future__ import annotations

import unittest

from origin_forge.model_scheduler import ModelRole
from origin_forge.model_scheduler_factory import (
    ModelSchedulingDisabled,
    create_model_scheduling,
)
from origin_forge.resource_model_config import parse_resource_model_config


class ModelSchedulerFactoryTests(unittest.TestCase):
    def test_disabled_config_refuses_scheduler_construction(self) -> None:
        config = parse_resource_model_config(None, None)
        with self.assertRaisesRegex(ModelSchedulingDisabled, "disabled"):
            create_model_scheduling(config)

    def test_enabled_config_builds_process_local_scheduler_without_allocating(self) -> None:
        config = parse_resource_model_config(
            {
                "enabled": True,
                "cpu_slots": 8,
                "ram_mib": 16384,
                "gpus": [
                    {
                        "device_id": "gpu0",
                        "vram_mib": 8192,
                        "reserve_vram_mib": 1024,
                    }
                ],
            },
            {
                "profiles": [
                    {
                        "profile_id": "strong-small",
                        "role": "coder_strong",
                        "model_id": "Qwen/Qwen3-Coder",
                        "runtime_id": "llamacpp",
                        "resources": {
                            "cpu_slots": 2,
                            "ram_mib": 4096,
                            "gpu": {"vram_mib": 4096},
                        },
                    }
                ],
                "policies": [
                    {
                        "role": "coder_strong",
                        "primary_profile_id": "strong-small",
                    }
                ],
            },
        )

        scheduling = create_model_scheduling(config)
        self.assertEqual(scheduling.resources.status().active_leases, ())
        self.assertEqual(
            scheduling.registry.profile("strong-small").model_id,
            "Qwen/Qwen3-Coder",
        )

        lease = scheduling.scheduler.acquire(
            "RUN-test",
            config.policy(ModelRole.CODER_STRONG),
        )
        self.assertEqual(lease.profile.profile_id, "strong-small")
        scheduling.scheduler.release(lease)
        self.assertEqual(scheduling.resources.status().active_leases, ())

    def test_factory_does_not_require_every_role_policy(self) -> None:
        config = parse_resource_model_config(
            {"enabled": True, "cpu_slots": 4, "ram_mib": 8192},
            {"profiles": [], "policies": []},
        )
        scheduling = create_model_scheduling(config)
        with self.assertRaises(KeyError):
            config.policy(ModelRole.VISION)
        self.assertEqual(scheduling.registry.all(), ())


if __name__ == "__main__":
    unittest.main()
