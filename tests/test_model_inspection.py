from __future__ import annotations

import unittest

from origin_forge.model_inspection import (
    inspect_model_policy,
    inspect_model_registry,
)
from origin_forge.model_scheduler import (
    ModelProfileRegistry,
    ModelResourceProfile,
    ModelRole,
    ModelSelectionPolicy,
)
from origin_forge.resource_scheduler import (
    GpuCapacity,
    GpuResourceRequest,
    ResourceCapacity,
    ResourceRequest,
    ResourceScheduler,
)


class ModelInspectionTests(unittest.TestCase):
    def _setup(self, *, gpu_vram: int = 8192):
        resources = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=8,
                ram_mib=32768,
                gpus=(GpuCapacity("gpu0", gpu_vram, reserve_vram_mib=1024),),
            )
        )
        registry = ModelProfileRegistry(
            (
                ModelResourceProfile(
                    "fast",
                    ModelRole.CODER_FAST,
                    "fast-model",
                    "llamacpp",
                    ResourceRequest(cpu_slots=2, ram_mib=4096),
                ),
                ModelResourceProfile(
                    "strong",
                    ModelRole.CODER_STRONG,
                    "strong-model",
                    "llamacpp",
                    ResourceRequest(
                        cpu_slots=2,
                        ram_mib=4096,
                        gpu=GpuResourceRequest(vram_mib=12288),
                    ),
                ),
                ModelResourceProfile(
                    "strong-small",
                    ModelRole.CODER_STRONG,
                    "strong-small-model",
                    "llamacpp",
                    ResourceRequest(
                        cpu_slots=2,
                        ram_mib=4096,
                        gpu=GpuResourceRequest(vram_mib=4096),
                    ),
                ),
            )
        )
        return registry, resources

    def test_registry_inspection_is_deterministic_and_non_allocating(self) -> None:
        registry, resources = self._setup()
        first = inspect_model_registry(registry, resources)
        second = inspect_model_registry(registry, resources)
        self.assertEqual(first, second)
        self.assertEqual(
            [profile.profile_id for profile in first],
            ["fast", "strong", "strong-small"],
        )
        self.assertEqual(resources.status().active_leases, ())

    def test_policy_inspection_predicts_explicit_static_fallback(self) -> None:
        registry, resources = self._setup(gpu_vram=8192)
        result = inspect_model_policy(
            registry,
            resources,
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
        )
        self.assertTrue(result.currently_schedulable)
        self.assertEqual(result.selected_profile_id, "strong-small")
        self.assertTrue(result.fallback_would_be_used)
        self.assertFalse(result.profiles[0].resource.static_compatible)
        self.assertTrue(result.profiles[1].resource.currently_available)
        self.assertEqual(resources.status().active_leases, ())

    def test_policy_inspection_predicts_dynamic_fallback_without_leasing(self) -> None:
        registry, resources = self._setup(gpu_vram=16384)
        busy = resources.acquire(
            "busy",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=10000)),
        )
        result = inspect_model_policy(
            registry,
            resources,
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
        )
        self.assertEqual(result.selected_profile_id, "strong-small")
        self.assertTrue(result.fallback_would_be_used)
        self.assertTrue(result.profiles[0].resource.static_compatible)
        self.assertFalse(result.profiles[0].resource.currently_available)
        self.assertEqual(len(resources.status().active_leases), 1)
        resources.release(busy.lease_id)

    def test_policy_inspection_never_searches_unlisted_registry_profiles(self) -> None:
        registry, resources = self._setup(gpu_vram=8192)
        result = inspect_model_policy(
            registry,
            resources,
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong"),
        )
        self.assertFalse(result.currently_schedulable)
        self.assertIsNone(result.selected_profile_id)
        self.assertFalse(result.fallback_would_be_used)
        self.assertEqual([item.profile_id for item in result.profiles], ["strong"])

    def test_role_filtered_registry_inspection(self) -> None:
        registry, resources = self._setup()
        result = inspect_model_registry(
            registry,
            resources,
            role=ModelRole.CODER_STRONG,
        )
        self.assertEqual(
            [profile.profile_id for profile in result],
            ["strong", "strong-small"],
        )

    def test_policy_role_mismatch_fails_before_allocation(self) -> None:
        registry, resources = self._setup()
        with self.assertRaisesRegex(ValueError, "does not match"):
            inspect_model_policy(
                registry,
                resources,
                ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("fast",)),
            )
        self.assertEqual(resources.status().active_leases, ())


if __name__ == "__main__":
    unittest.main()
