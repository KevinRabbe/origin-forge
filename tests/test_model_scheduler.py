from __future__ import annotations

import unittest

from origin_forge.model_scheduler import (
    ManagedModelSession,
    ModelCapacityUnavailable,
    ModelProfileError,
    ModelProfileRegistry,
    ModelRequestInvalid,
    ModelResourceProfile,
    ModelRole,
    ModelScheduler,
    ModelSelectionPolicy,
)
from origin_forge.resource_scheduler import (
    GpuCapacity,
    GpuResourceRequest,
    ResourceCapacity,
    ResourceRequest,
    ResourceScheduler,
)


class RecordingLoader:
    def __init__(self, *, fail_load: bool = False, fail_unload: bool = False):
        self.fail_load = fail_load
        self.fail_unload = fail_unload
        self.loaded = []
        self.unloaded = []

    def load(self, profile, lease):
        self.loaded.append((profile, lease))
        if self.fail_load:
            raise RuntimeError("load failed")
        return {"profile_id": profile.profile_id, "lease_id": lease.lease_id}

    def unload(self, instance):
        self.unloaded.append(instance)
        if self.fail_unload:
            raise RuntimeError("unload failed")


class ModelSchedulerTests(unittest.TestCase):
    def _profiles(self):
        return (
            ModelResourceProfile(
                "fast",
                ModelRole.CODER_FAST,
                "qwen-fast",
                "llamacpp",
                ResourceRequest(cpu_slots=2, ram_mib=4096),
            ),
            ModelResourceProfile(
                "strong",
                ModelRole.CODER_STRONG,
                "qwen-strong",
                "llamacpp",
                ResourceRequest(
                    cpu_slots=2,
                    ram_mib=4096,
                    gpu=GpuResourceRequest(vram_mib=12288, compute_slots=1),
                ),
            ),
            ModelResourceProfile(
                "strong-small",
                ModelRole.CODER_STRONG,
                "qwen-strong-small",
                "llamacpp",
                ResourceRequest(
                    cpu_slots=2,
                    ram_mib=4096,
                    gpu=GpuResourceRequest(vram_mib=4096, compute_slots=1),
                ),
            ),
            ModelResourceProfile(
                "vision",
                ModelRole.VISION,
                "vision-model",
                "vision-runtime",
                ResourceRequest(
                    cpu_slots=1,
                    ram_mib=2048,
                    gpu=GpuResourceRequest(vram_mib=2048, compute_slots=1),
                ),
            ),
        )

    def _scheduler(self, *, gpu_vram: int = 16384, compute_slots: int = 1):
        resources = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=8,
                ram_mib=32768,
                gpus=(GpuCapacity("gpu0", gpu_vram, reserve_vram_mib=1024, compute_slots=compute_slots),),
            )
        )
        return ModelScheduler(ModelProfileRegistry(self._profiles()), resources), resources

    def test_registry_is_inventory_only_and_deterministic(self) -> None:
        registry = ModelProfileRegistry(self._profiles())
        self.assertEqual(
            [profile.profile_id for profile in registry.all()],
            ["fast", "strong", "strong-small", "vision"],
        )
        self.assertEqual(
            [profile.profile_id for profile in registry.profiles_for_role(ModelRole.CODER_STRONG)],
            ["strong", "strong-small"],
        )
        with self.assertRaises(ModelProfileError):
            ModelProfileRegistry((self._profiles()[0], self._profiles()[0]))

    def test_primary_profile_is_selected_when_capacity_is_available(self) -> None:
        scheduler, resources = self._scheduler()
        selected = scheduler.acquire(
            "task-1",
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
        )
        self.assertEqual(selected.profile.profile_id, "strong")
        self.assertFalse(selected.fallback_used)
        self.assertEqual(selected.attempted_profile_ids, ("strong",))
        self.assertEqual(resources.status().gpus[0].used_vram_mib, 12288)
        scheduler.release(selected)

    def test_explicit_fallback_handles_static_hardware_mismatch(self) -> None:
        scheduler, resources = self._scheduler(gpu_vram=8192)
        selected = scheduler.acquire(
            "task-2",
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
        )
        self.assertEqual(selected.profile.profile_id, "strong-small")
        self.assertTrue(selected.fallback_used)
        self.assertEqual(selected.attempted_profile_ids, ("strong", "strong-small"))
        self.assertEqual(resources.status().gpus[0].used_vram_mib, 4096)

    def test_no_implicit_fallback_to_other_installed_profile(self) -> None:
        scheduler, resources = self._scheduler(gpu_vram=8192)
        with self.assertRaises(ModelCapacityUnavailable):
            scheduler.acquire(
                "task-3",
                ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong"),
            )
        self.assertEqual(resources.status().active_leases, ())

    def test_dynamic_contention_uses_only_explicit_fallback_chain(self) -> None:
        scheduler, resources = self._scheduler(compute_slots=2)
        occupying = resources.acquire(
            "other-job",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=10000, compute_slots=1)),
        )
        selected = scheduler.acquire(
            "task-4",
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
        )
        self.assertEqual(selected.profile.profile_id, "strong-small")
        self.assertEqual(selected.attempted_profile_ids, ("strong", "strong-small"))
        scheduler.release(selected)
        resources.release(occupying.lease_id)

    def test_role_mismatch_is_rejected_before_any_lease(self) -> None:
        scheduler, resources = self._scheduler()
        with self.assertRaisesRegex(ModelProfileError, "does not match"):
            scheduler.acquire(
                "task-5",
                ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("vision",)),
            )
        self.assertEqual(resources.status().active_leases, ())

    def test_unknown_profile_is_rejected_before_any_lease(self) -> None:
        scheduler, resources = self._scheduler()
        with self.assertRaisesRegex(ModelProfileError, "unknown model profile"):
            scheduler.acquire(
                "task-6",
                ModelSelectionPolicy(ModelRole.CODER_STRONG, "missing"),
            )
        self.assertEqual(resources.status().active_leases, ())

    def test_invalid_owner_is_not_swallowed_as_capacity_fallback(self) -> None:
        scheduler, resources = self._scheduler(gpu_vram=8192)
        with self.assertRaises(ModelRequestInvalid):
            scheduler.acquire(
                "bad owner",
                ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
            )
        self.assertEqual(resources.status().active_leases, ())

    def test_hold_releases_model_resources(self) -> None:
        scheduler, resources = self._scheduler()
        policy = ModelSelectionPolicy(ModelRole.CODER_FAST, "fast")
        with scheduler.hold("task-7", policy) as scheduled:
            self.assertEqual(scheduled.profile.profile_id, "fast")
            self.assertEqual(resources.status().used_cpu_slots, 2)
        self.assertEqual(resources.status().active_leases, ())

    def test_use_loads_only_after_lease_and_unloads_before_release(self) -> None:
        scheduler, resources = self._scheduler()
        loader = RecordingLoader()
        policy = ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong")

        with scheduler.use("task-8", policy, loader) as session:
            self.assertIsInstance(session, ManagedModelSession)
            self.assertEqual(session.instance["profile_id"], "strong")
            self.assertEqual(len(loader.loaded), 1)
            self.assertEqual(resources.status().gpus[0].used_vram_mib, 12288)
            self.assertEqual(loader.unloaded, [])

        self.assertEqual(len(loader.unloaded), 1)
        self.assertEqual(resources.status().active_leases, ())

    def test_load_failure_releases_lease(self) -> None:
        scheduler, resources = self._scheduler()
        loader = RecordingLoader(fail_load=True)
        with self.assertRaisesRegex(RuntimeError, "load failed"):
            with scheduler.use(
                "task-9",
                ModelSelectionPolicy(ModelRole.CODER_FAST, "fast"),
                loader,
            ):
                self.fail("session body must not run")
        self.assertEqual(resources.status().active_leases, ())
        self.assertEqual(loader.unloaded, [])

    def test_unload_failure_is_visible_and_still_releases_lease(self) -> None:
        scheduler, resources = self._scheduler()
        loader = RecordingLoader(fail_unload=True)
        with self.assertRaisesRegex(RuntimeError, "unload failed"):
            with scheduler.use(
                "task-10",
                ModelSelectionPolicy(ModelRole.CODER_FAST, "fast"),
                loader,
            ):
                pass
        self.assertEqual(resources.status().active_leases, ())

    def test_cleanup_failure_does_not_hide_original_body_failure(self) -> None:
        scheduler, resources = self._scheduler()
        loader = RecordingLoader(fail_unload=True)
        with self.assertRaisesRegex(ValueError, "task failed"):
            with scheduler.use(
                "task-11",
                ModelSelectionPolicy(ModelRole.CODER_FAST, "fast"),
                loader,
            ):
                raise ValueError("task failed")
        self.assertEqual(resources.status().active_leases, ())
        self.assertEqual(len(loader.unloaded), 1)


if __name__ == "__main__":
    unittest.main()
