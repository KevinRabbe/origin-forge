from __future__ import annotations

from dataclasses import dataclass

from .resource_scheduler import ResourceRequest, ResourceScheduler


@dataclass(frozen=True)
class ResourceAdmissionInspection:
    static_compatible: bool
    currently_available: bool
    reason: str | None
    static_gpu_candidates: tuple[str, ...] = ()
    selected_gpu_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "static_compatible": self.static_compatible,
            "currently_available": self.currently_available,
            "reason": self.reason,
            "static_gpu_candidates": list(self.static_gpu_candidates),
            "selected_gpu_id": self.selected_gpu_id,
        }


def inspect_resource_request(
    scheduler: ResourceScheduler,
    request: ResourceRequest,
) -> ResourceAdmissionInspection:
    """Inspect admission without creating a lease or changing scheduler state."""

    if not isinstance(scheduler, ResourceScheduler):
        raise TypeError("scheduler must be a ResourceScheduler")
    if not isinstance(request, ResourceRequest):
        raise TypeError("request must be a ResourceRequest")

    capacity = scheduler.capacity
    if request.cpu_slots > capacity.cpu_slots:
        return ResourceAdmissionInspection(
            False,
            False,
            f"request CPU exceeds capacity ({request.cpu_slots} > {capacity.cpu_slots})",
        )
    if request.ram_mib > capacity.ram_mib:
        return ResourceAdmissionInspection(
            False,
            False,
            f"request RAM exceeds capacity ({request.ram_mib} > {capacity.ram_mib} MiB)",
        )

    static_gpu_candidates = ()
    static_gpus = []
    if request.gpu is not None:
        if request.gpu.device_id is not None:
            try:
                raw_candidates = [capacity.gpu(request.gpu.device_id)]
            except KeyError:
                return ResourceAdmissionInspection(
                    False,
                    False,
                    f"requested GPU is not configured: {request.gpu.device_id}",
                )
        else:
            raw_candidates = list(capacity.gpus)
        if not raw_candidates:
            return ResourceAdmissionInspection(
                False,
                False,
                "GPU resources were requested but no GPU is configured",
            )
        static_gpus = [
            gpu
            for gpu in raw_candidates
            if request.gpu.vram_mib <= gpu.usable_vram_mib
            and request.gpu.compute_slots <= gpu.compute_slots
        ]
        if not static_gpus:
            return ResourceAdmissionInspection(
                False,
                False,
                "GPU request exceeds configured static capacity",
            )
        static_gpu_candidates = tuple(sorted(gpu.device_id for gpu in static_gpus))

    status = scheduler.status()
    if len(status.active_leases) >= status.max_active_leases:
        return ResourceAdmissionInspection(
            True,
            False,
            "maximum active lease count is currently reached",
            static_gpu_candidates,
        )
    if request.cpu_slots > status.free_cpu_slots:
        return ResourceAdmissionInspection(
            True,
            False,
            "requested CPU slots are currently busy",
            static_gpu_candidates,
        )
    if request.ram_mib > status.free_ram_mib:
        return ResourceAdmissionInspection(
            True,
            False,
            "requested RAM is currently busy",
            static_gpu_candidates,
        )

    selected_gpu_id = None
    if request.gpu is not None:
        by_id = {gpu.device_id: gpu for gpu in status.gpus}
        eligible = []
        for capacity_gpu in static_gpus:
            gpu = by_id[capacity_gpu.device_id]
            if gpu.exclusive_active:
                continue
            if request.gpu.exclusive and (
                gpu.used_vram_mib > 0 or gpu.used_compute_slots > 0
            ):
                continue
            if request.gpu.vram_mib > gpu.free_vram_mib:
                continue
            if request.gpu.compute_slots > gpu.free_compute_slots:
                continue
            eligible.append(
                (
                    gpu.free_vram_mib - request.gpu.vram_mib,
                    gpu.free_compute_slots - request.gpu.compute_slots,
                    gpu.device_id,
                )
            )
        if not eligible:
            return ResourceAdmissionInspection(
                True,
                False,
                "requested GPU resources are currently busy",
                static_gpu_candidates,
            )
        eligible.sort()
        selected_gpu_id = eligible[0][2]

    return ResourceAdmissionInspection(
        True,
        True,
        None,
        static_gpu_candidates,
        selected_gpu_id,
    )
