from __future__ import annotations

import threading
import unittest

from origin_forge.resource_scheduler import (
    GpuCapacity,
    GpuResourceRequest,
    ResourceCapacity,
    ResourceRequest,
    ResourceRequestInvalid,
    ResourceScheduler,
    ResourceUnavailable,
)


class ResourceSchedulerTests(unittest.TestCase):
    def test_capacity_and_request_validation_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            GpuCapacity("gpu0", 0)
        with self.assertRaises(ValueError):
            GpuCapacity("gpu0", 1024, reserve_vram_mib=1024)
        with self.assertRaises(ValueError):
            ResourceCapacity(4, 8192, (GpuCapacity("gpu0", 4096), GpuCapacity("gpu0", 4096)))
        with self.assertRaises(ValueError):
            ResourceRequest()
        with self.assertRaises(ValueError):
            GpuResourceRequest(0, compute_slots=0)

    def test_static_overcommit_is_invalid_but_dynamic_contention_is_unavailable(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=4,
                ram_mib=8192,
                gpus=(GpuCapacity("gpu0", 8192, reserve_vram_mib=1024),),
            )
        )

        with self.assertRaises(ResourceRequestInvalid):
            scheduler.acquire("too-much-cpu", ResourceRequest(cpu_slots=5))
        with self.assertRaises(ResourceRequestInvalid):
            scheduler.acquire("too-much-ram", ResourceRequest(ram_mib=8193))
        with self.assertRaises(ResourceRequestInvalid):
            scheduler.acquire(
                "too-much-vram",
                ResourceRequest(gpu=GpuResourceRequest(vram_mib=7169)),
            )

        first = scheduler.acquire("first", ResourceRequest(cpu_slots=4, ram_mib=4096))
        self.assertIsNone(scheduler.try_acquire("waiting", ResourceRequest(cpu_slots=1)))
        with self.assertRaises(ResourceUnavailable):
            scheduler.acquire("waiting", ResourceRequest(cpu_slots=1))
        scheduler.release(first.lease_id)
        self.assertIsNotNone(scheduler.try_acquire("waiting", ResourceRequest(cpu_slots=1)))

    def test_gpu_headroom_is_never_allocated(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=2,
                ram_mib=4096,
                gpus=(GpuCapacity("gpu0", 16384, reserve_vram_mib=2048),),
            )
        )
        lease = scheduler.acquire(
            "model-a",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=14336)),
        )
        status = scheduler.status().gpus[0]
        self.assertEqual(status.total_vram_mib, 16384)
        self.assertEqual(status.reserved_headroom_mib, 2048)
        self.assertEqual(status.usable_vram_mib, 14336)
        self.assertEqual(status.used_vram_mib, 14336)
        self.assertEqual(status.free_vram_mib, 0)
        scheduler.release(lease.lease_id)

    def test_best_fit_gpu_selection_preserves_larger_device(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=8,
                ram_mib=32768,
                gpus=(
                    GpuCapacity("gpu-large", 16384, reserve_vram_mib=1024, compute_slots=2),
                    GpuCapacity("gpu-small", 10240, reserve_vram_mib=1024, compute_slots=2),
                ),
            )
        )
        first = scheduler.acquire(
            "model-small",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=8192)),
        )
        self.assertEqual(first.gpu.device_id, "gpu-small")

        second = scheduler.acquire(
            "model-large",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=12288)),
        )
        self.assertEqual(second.gpu.device_id, "gpu-large")

    def test_best_fit_tie_breaks_by_device_id(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=4,
                ram_mib=8192,
                gpus=(
                    GpuCapacity("gpu-b", 8192),
                    GpuCapacity("gpu-a", 8192),
                ),
            )
        )
        lease = scheduler.acquire(
            "model",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=4096)),
        )
        self.assertEqual(lease.gpu.device_id, "gpu-a")

    def test_requested_gpu_device_is_respected(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=4,
                ram_mib=8192,
                gpus=(GpuCapacity("gpu-a", 8192), GpuCapacity("gpu-b", 8192)),
            )
        )
        lease = scheduler.acquire(
            "pinned",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=2048, device_id="gpu-b")),
        )
        self.assertEqual(lease.gpu.device_id, "gpu-b")

    def test_exclusive_gpu_lease_blocks_and_is_blocked_by_shared_work(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=4,
                ram_mib=8192,
                gpus=(GpuCapacity("gpu0", 8192, compute_slots=2),),
            )
        )
        shared = scheduler.acquire(
            "shared",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=1024, compute_slots=1)),
        )
        self.assertIsNone(
            scheduler.try_acquire(
                "exclusive",
                ResourceRequest(
                    gpu=GpuResourceRequest(vram_mib=1024, compute_slots=1, exclusive=True)
                ),
            )
        )
        scheduler.release(shared.lease_id)

        exclusive = scheduler.acquire(
            "exclusive",
            ResourceRequest(
                gpu=GpuResourceRequest(vram_mib=1024, compute_slots=1, exclusive=True)
            ),
        )
        self.assertTrue(scheduler.status().gpus[0].exclusive_active)
        self.assertIsNone(
            scheduler.try_acquire(
                "shared-2",
                ResourceRequest(gpu=GpuResourceRequest(vram_mib=1, compute_slots=1)),
            )
        )
        scheduler.release(exclusive.lease_id)

    def test_compute_slots_limit_parallel_gpu_work(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=8,
                ram_mib=16384,
                gpus=(GpuCapacity("gpu0", 16384, compute_slots=2),),
            )
        )
        first = scheduler.acquire(
            "one",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=1024, compute_slots=1)),
        )
        second = scheduler.acquire(
            "two",
            ResourceRequest(gpu=GpuResourceRequest(vram_mib=1024, compute_slots=1)),
        )
        self.assertIsNone(
            scheduler.try_acquire(
                "three",
                ResourceRequest(gpu=GpuResourceRequest(vram_mib=1024, compute_slots=1)),
            )
        )
        scheduler.release(first.lease_id)
        scheduler.release(second.lease_id)

    def test_combined_request_is_atomic_when_one_resource_is_busy(self) -> None:
        scheduler = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=2,
                ram_mib=8192,
                gpus=(GpuCapacity("gpu0", 8192),),
            )
        )
        cpu = scheduler.acquire("cpu-owner", ResourceRequest(cpu_slots=2))
        failed = scheduler.try_acquire(
            "combined",
            ResourceRequest(
                cpu_slots=1,
                ram_mib=1024,
                gpu=GpuResourceRequest(vram_mib=4096),
            ),
        )
        self.assertIsNone(failed)
        status = scheduler.status()
        self.assertEqual(status.used_ram_mib, 0)
        self.assertEqual(status.gpus[0].used_vram_mib, 0)
        self.assertEqual(len(status.active_leases), 1)
        scheduler.release(cpu.lease_id)

    def test_max_active_leases_is_hard(self) -> None:
        scheduler = ResourceScheduler(ResourceCapacity(8, 8192, max_active_leases=2))
        first = scheduler.acquire("a", ResourceRequest(cpu_slots=1))
        second = scheduler.acquire("b", ResourceRequest(cpu_slots=1))
        self.assertIsNone(scheduler.try_acquire("c", ResourceRequest(cpu_slots=1)))
        self.assertEqual(len(scheduler.status().active_leases), 2)
        scheduler.release(first.lease_id)
        scheduler.release(second.lease_id)

    def test_context_manager_releases_on_exception(self) -> None:
        scheduler = ResourceScheduler(ResourceCapacity(1, 1024))
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with scheduler.hold("owner", ResourceRequest(cpu_slots=1)):
                self.assertEqual(scheduler.status().used_cpu_slots, 1)
                raise RuntimeError("boom")
        self.assertEqual(scheduler.status().used_cpu_slots, 0)
        self.assertEqual(scheduler.status().active_leases, ())

    def test_release_is_idempotent_and_status_is_deterministic(self) -> None:
        scheduler = ResourceScheduler(ResourceCapacity(4, 4096))
        second = scheduler.acquire("second", ResourceRequest(cpu_slots=1))
        first = scheduler.acquire("first", ResourceRequest(cpu_slots=1))
        status = scheduler.status()
        self.assertEqual(
            [lease.lease_id for lease in status.active_leases],
            sorted([second.lease_id, first.lease_id]),
        )
        self.assertTrue(scheduler.release(first.lease_id))
        self.assertFalse(scheduler.release(first.lease_id))

    def test_concurrent_try_acquire_never_overcommits(self) -> None:
        scheduler = ResourceScheduler(ResourceCapacity(cpu_slots=2, ram_mib=2048))
        worker_count = 12
        barrier = threading.Barrier(worker_count)
        leases = []
        lock = threading.Lock()

        def worker(index: int) -> None:
            barrier.wait(timeout=2.0)
            lease = scheduler.try_acquire(
                f"worker-{index}",
                ResourceRequest(cpu_slots=1, ram_mib=128),
            )
            if lease is not None:
                with lock:
                    leases.append(lease)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3.0)
            self.assertFalse(thread.is_alive())

        self.assertEqual(len(leases), 2)
        status = scheduler.status()
        self.assertEqual(status.used_cpu_slots, 2)
        self.assertEqual(status.used_ram_mib, 256)
        self.assertGreaterEqual(status.free_cpu_slots, 0)
        self.assertGreaterEqual(status.free_ram_mib, 0)


if __name__ == "__main__":
    unittest.main()
