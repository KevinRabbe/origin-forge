from __future__ import annotations

import unittest

from origin_forge.resource_scheduler import (
    GpuCapacity,
    GpuResourceRequest,
    ResourceCapacity,
    ResourceRequest,
    ResourceRequestInvalid,
    ResourceScheduler,
)


class ResourceSchedulerEdgeTests(unittest.TestCase):
    def test_unknown_pinned_gpu_is_normalized_as_invalid_request(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=4,
                ram_mib=8192,
                gpus=(GpuCapacity("gpu0", 8192),),
            )
        )
        with self.assertRaisesRegex(ResourceRequestInvalid, "not configured"):
            scheduler.acquire(
                "model",
                ResourceRequest(
                    gpu=GpuResourceRequest(vram_mib=1024, device_id="missing-gpu")
                ),
            )

    def test_invalid_owner_is_rejected_before_allocation(self) -> None:
        scheduler = ResourceScheduler(ResourceCapacity(cpu_slots=2, ram_mib=2048))
        with self.assertRaises(ResourceRequestInvalid):
            scheduler.acquire("bad owner", ResourceRequest(cpu_slots=1))
        self.assertEqual(scheduler.status().active_leases, ())

    def test_wrong_request_type_is_rejected_without_mutation(self) -> None:
        scheduler = ResourceScheduler(ResourceCapacity(cpu_slots=2, ram_mib=2048))
        with self.assertRaisesRegex(ResourceRequestInvalid, "ResourceRequest"):
            scheduler.try_acquire("owner", object())  # type: ignore[arg-type]
        self.assertEqual(scheduler.status().active_leases, ())


if __name__ == "__main__":
    unittest.main()
