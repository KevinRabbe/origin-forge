from __future__ import annotations

import unittest

from origin_forge.resource_inspection import inspect_resource_request
from origin_forge.resource_scheduler import (
    GpuCapacity,
    GpuResourceRequest,
    ResourceCapacity,
    ResourceRequest,
    ResourceScheduler,
)


class ResourceInspectionTests(unittest.TestCase):
    def _scheduler(self) -> ResourceScheduler:
        return ResourceScheduler(
            ResourceCapacity(
                cpu_slots=8,
                ram_mib=16384,
                gpus=(
                    GpuCapacity("gpu-large", 16384, reserve_vram_mib=1024, compute_slots=2),
                    GpuCapacity("gpu-small", 8192, reserve_vram_mib=1024, compute_slots=2),
                ),
                max_active_leases=8,
            )
        )

    def test_static_incompatibility_is_distinct_from_contention(self) -> None:
        scheduler = self._scheduler()
        result = inspect_resource_request(
            scheduler,
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=16000)),
        )
        self.assertFalse(result.static_compatible)
        self.assertFalse(result.currently_available)
        self.assertIn("static capacity", result.reason or "")
        self.assertEqual(scheduler.status().active_leases, ())

    def test_inspection_matches_deterministic_best_fit_without_allocating(self) -> None:
        scheduler = self._scheduler()
        request = ResourceRequest(
            cpu_slots=1,
            ram_mib=1024,
            gpu=GpuResourceRequest(vram_mib=4096),
        )
        result = inspect_resource_request(scheduler, request)
        self.assertTrue(result.static_compatible)
        self.assertTrue(result.currently_available)
        self.assertEqual(result.static_gpu_candidates, ("gpu-large", "gpu-small"))
        self.assertEqual(result.selected_gpu_id, "gpu-small")
        self.assertEqual(scheduler.status().active_leases, ())

        lease = scheduler.acquire("owner", request)
        self.assertEqual(lease.gpu.device_id, result.selected_gpu_id)

    def test_current_gpu_contention_keeps_static_compatibility_true(self) -> None:
        scheduler = self._scheduler()
        lease = scheduler.acquire(
            "busy",
            ResourceRequest(
                gpu=GpuResourceRequest(
                    vram_mib=7168,
                    compute_slots=2,
                    device_id="gpu-small",
                    exclusive=True,
                )
            ),
        )
        result = inspect_resource_request(
            scheduler,
            ResourceRequest(
                gpu=GpuResourceRequest(vram_mib=1024, device_id="gpu-small")
            ),
        )
        self.assertTrue(result.static_compatible)
        self.assertFalse(result.currently_available)
        self.assertIn("currently busy", result.reason or "")
        self.assertEqual(result.static_gpu_candidates, ("gpu-small",))
        scheduler.release(lease.lease_id)

    def test_cpu_and_ram_contention_are_reported_without_mutation(self) -> None:
        scheduler = self._scheduler()
        lease = scheduler.acquire("busy", ResourceRequest(cpu_slots=8, ram_mib=16000))
        cpu = inspect_resource_request(scheduler, ResourceRequest(cpu_slots=1))
        ram = inspect_resource_request(scheduler, ResourceRequest(ram_mib=1000))
        self.assertTrue(cpu.static_compatible)
        self.assertFalse(cpu.currently_available)
        self.assertIn("CPU", cpu.reason or "")
        self.assertTrue(ram.static_compatible)
        self.assertFalse(ram.currently_available)
        self.assertIn("RAM", ram.reason or "")
        self.assertEqual(len(scheduler.status().active_leases), 1)
        scheduler.release(lease.lease_id)

    def test_unknown_pinned_gpu_is_static_incompatibility(self) -> None:
        scheduler = self._scheduler()
        result = inspect_resource_request(
            scheduler,
            ResourceRequest(
                gpu=GpuResourceRequest(vram_mib=1024, device_id="missing")
            ),
        )
        self.assertFalse(result.static_compatible)
        self.assertFalse(result.currently_available)
        self.assertIn("not configured", result.reason or "")

    def test_exclusive_request_reports_shared_usage_as_contention(self) -> None:
        scheduler = self._scheduler()
        lease = scheduler.acquire(
            "shared",
            ResourceRequest(
                gpu=GpuResourceRequest(vram_mib=1024, device_id="gpu-small")
            ),
        )
        result = inspect_resource_request(
            scheduler,
            ResourceRequest(
                gpu=GpuResourceRequest(
                    vram_mib=1024,
                    device_id="gpu-small",
                    exclusive=True,
                )
            ),
        )
        self.assertTrue(result.static_compatible)
        self.assertFalse(result.currently_available)
        scheduler.release(lease.lease_id)


if __name__ == "__main__":
    unittest.main()
