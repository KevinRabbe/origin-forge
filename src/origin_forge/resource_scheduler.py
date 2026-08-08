from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ResourceSchedulerError(RuntimeError):
    pass


class ResourceRequestInvalid(ResourceSchedulerError):
    pass


class ResourceUnavailable(ResourceSchedulerError):
    pass


@dataclass(frozen=True)
class GpuCapacity:
    device_id: str
    vram_mib: int
    reserve_vram_mib: int = 0
    compute_slots: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not _RESOURCE_ID_RE.fullmatch(self.device_id):
            raise ValueError(f"invalid GPU device_id: {self.device_id!r}")
        for value, name in (
            (self.vram_mib, "vram_mib"),
            (self.reserve_vram_mib, "reserve_vram_mib"),
            (self.compute_slots, "compute_slots"),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"GPU {name} must be an integer")
        if self.vram_mib <= 0:
            raise ValueError("GPU vram_mib must be positive")
        if self.reserve_vram_mib < 0 or self.reserve_vram_mib >= self.vram_mib:
            raise ValueError("GPU reserve_vram_mib must be non-negative and below vram_mib")
        if self.compute_slots <= 0:
            raise ValueError("GPU compute_slots must be positive")

    @property
    def usable_vram_mib(self) -> int:
        return self.vram_mib - self.reserve_vram_mib


@dataclass(frozen=True)
class ResourceCapacity:
    cpu_slots: int
    ram_mib: int
    gpus: tuple[GpuCapacity, ...] = ()
    max_active_leases: int = 64

    def __post_init__(self) -> None:
        for value, name in (
            (self.cpu_slots, "cpu_slots"),
            (self.ram_mib, "ram_mib"),
            (self.max_active_leases, "max_active_leases"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"capacity {name} must be a positive integer")
        if any(not isinstance(gpu, GpuCapacity) for gpu in self.gpus):
            raise ValueError("capacity gpus must contain GpuCapacity values")
        ids = [gpu.device_id for gpu in self.gpus]
        if len(ids) != len(set(ids)):
            raise ValueError("capacity contains duplicate GPU device IDs")

    def gpu(self, device_id: str) -> GpuCapacity:
        for gpu in self.gpus:
            if gpu.device_id == device_id:
                return gpu
        raise KeyError(device_id)


@dataclass(frozen=True)
class GpuResourceRequest:
    vram_mib: int
    compute_slots: int = 1
    device_id: str | None = None
    exclusive: bool = False

    def __post_init__(self) -> None:
        for value, name in (
            (self.vram_mib, "vram_mib"),
            (self.compute_slots, "compute_slots"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"GPU request {name} must be a non-negative integer")
        if self.vram_mib == 0 and self.compute_slots == 0:
            raise ValueError("GPU request must reserve VRAM or compute")
        if self.device_id is not None and (
            not isinstance(self.device_id, str)
            or not _RESOURCE_ID_RE.fullmatch(self.device_id)
        ):
            raise ValueError(f"invalid requested GPU device_id: {self.device_id!r}")
        if not isinstance(self.exclusive, bool):
            raise ValueError("GPU request exclusive must be boolean")


@dataclass(frozen=True)
class ResourceRequest:
    cpu_slots: int = 0
    ram_mib: int = 0
    gpu: GpuResourceRequest | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.cpu_slots, "cpu_slots"),
            (self.ram_mib, "ram_mib"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"resource request {name} must be a non-negative integer")
        if self.gpu is not None and not isinstance(self.gpu, GpuResourceRequest):
            raise ValueError("resource request gpu must be a GpuResourceRequest or null")
        if self.cpu_slots == 0 and self.ram_mib == 0 and self.gpu is None:
            raise ValueError("resource request must reserve at least one resource")


@dataclass(frozen=True)
class AssignedGpuResources:
    device_id: str
    vram_mib: int
    compute_slots: int
    exclusive: bool


@dataclass(frozen=True)
class ResourceLease:
    lease_id: str
    owner_id: str
    cpu_slots: int
    ram_mib: int
    gpu: AssignedGpuResources | None

    def to_dict(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "owner_id": self.owner_id,
            "cpu_slots": self.cpu_slots,
            "ram_mib": self.ram_mib,
            "gpu": None
            if self.gpu is None
            else {
                "device_id": self.gpu.device_id,
                "vram_mib": self.gpu.vram_mib,
                "compute_slots": self.gpu.compute_slots,
                "exclusive": self.gpu.exclusive,
            },
        }


@dataclass(frozen=True)
class GpuResourceStatus:
    device_id: str
    total_vram_mib: int
    reserved_headroom_mib: int
    usable_vram_mib: int
    used_vram_mib: int
    free_vram_mib: int
    compute_slots: int
    used_compute_slots: int
    free_compute_slots: int
    exclusive_active: bool


@dataclass(frozen=True)
class ResourceSchedulerStatus:
    cpu_slots: int
    used_cpu_slots: int
    free_cpu_slots: int
    ram_mib: int
    used_ram_mib: int
    free_ram_mib: int
    gpus: tuple[GpuResourceStatus, ...]
    active_leases: tuple[ResourceLease, ...]
    max_active_leases: int


class ResourceScheduler:
    """Thread-safe atomic resource arbiter for one Origin Forge process.

    Leases are intentionally process-local. Durable Task/Flow state survives a
    crash; CPU/RAM/VRAM reservations should not. A model/tool owner must hold a
    lease from before resource acquisition/load through unload/cleanup.
    """

    def __init__(self, capacity: ResourceCapacity):
        if not isinstance(capacity, ResourceCapacity):
            raise TypeError("capacity must be a ResourceCapacity")
        self.capacity = capacity
        self._leases: dict[str, ResourceLease] = {}
        self._next_lease = 1
        self._lock = threading.RLock()

    @staticmethod
    def _validate_owner(owner_id: str) -> None:
        if not isinstance(owner_id, str) or not _RESOURCE_ID_RE.fullmatch(owner_id):
            raise ResourceRequestInvalid(f"invalid resource owner_id: {owner_id!r}")

    def _usage(self) -> tuple[int, int, dict[str, tuple[int, int, bool]]]:
        used_cpu = 0
        used_ram = 0
        gpu_usage: dict[str, list[int | bool]] = {
            gpu.device_id: [0, 0, False] for gpu in self.capacity.gpus
        }
        for lease in self._leases.values():
            used_cpu += lease.cpu_slots
            used_ram += lease.ram_mib
            if lease.gpu is not None:
                usage = gpu_usage[lease.gpu.device_id]
                usage[0] = int(usage[0]) + lease.gpu.vram_mib
                usage[1] = int(usage[1]) + lease.gpu.compute_slots
                usage[2] = bool(usage[2]) or lease.gpu.exclusive
        return (
            used_cpu,
            used_ram,
            {
                device_id: (int(values[0]), int(values[1]), bool(values[2]))
                for device_id, values in gpu_usage.items()
            },
        )

    def _gpu_candidates(self, request: GpuResourceRequest) -> list[GpuCapacity]:
        if request.device_id is None:
            return list(self.capacity.gpus)
        try:
            return [self.capacity.gpu(request.device_id)]
        except KeyError as exc:
            raise ResourceRequestInvalid(
                f"requested GPU is not configured: {request.device_id}"
            ) from exc

    def _validate_static_fit(self, request: ResourceRequest) -> None:
        if request.cpu_slots > self.capacity.cpu_slots:
            raise ResourceRequestInvalid(
                f"request CPU exceeds capacity ({request.cpu_slots} > {self.capacity.cpu_slots})"
            )
        if request.ram_mib > self.capacity.ram_mib:
            raise ResourceRequestInvalid(
                f"request RAM exceeds capacity ({request.ram_mib} > {self.capacity.ram_mib} MiB)"
            )
        if request.gpu is None:
            return
        candidates = self._gpu_candidates(request.gpu)
        if not candidates:
            raise ResourceRequestInvalid("GPU resources were requested but no GPU is configured")
        if not any(
            request.gpu.vram_mib <= gpu.usable_vram_mib
            and request.gpu.compute_slots <= gpu.compute_slots
            for gpu in candidates
        ):
            raise ResourceRequestInvalid("GPU request exceeds configured static capacity")

    def _select_gpu(
        self,
        request: GpuResourceRequest,
        usage: dict[str, tuple[int, int, bool]],
    ) -> GpuCapacity | None:
        candidates = self._gpu_candidates(request)
        eligible: list[tuple[int, int, str, GpuCapacity]] = []
        for gpu in candidates:
            used_vram, used_compute, exclusive_active = usage[gpu.device_id]
            if exclusive_active:
                continue
            if request.exclusive and (used_vram > 0 or used_compute > 0):
                continue
            free_vram = gpu.usable_vram_mib - used_vram
            free_compute = gpu.compute_slots - used_compute
            if request.vram_mib > free_vram or request.compute_slots > free_compute:
                continue
            # Best-fit preserves larger/more-free devices for requests that need
            # them. device_id is the final deterministic tie-breaker.
            eligible.append(
                (
                    free_vram - request.vram_mib,
                    free_compute - request.compute_slots,
                    gpu.device_id,
                    gpu,
                )
            )
        if not eligible:
            return None
        eligible.sort(key=lambda item: (item[0], item[1], item[2]))
        return eligible[0][3]

    def try_acquire(
        self,
        owner_id: str,
        request: ResourceRequest,
    ) -> ResourceLease | None:
        self._validate_owner(owner_id)
        if not isinstance(request, ResourceRequest):
            raise ResourceRequestInvalid("request must be a ResourceRequest")
        self._validate_static_fit(request)
        with self._lock:
            if len(self._leases) >= self.capacity.max_active_leases:
                return None
            used_cpu, used_ram, gpu_usage = self._usage()
            if used_cpu + request.cpu_slots > self.capacity.cpu_slots:
                return None
            if used_ram + request.ram_mib > self.capacity.ram_mib:
                return None

            assigned_gpu: AssignedGpuResources | None = None
            if request.gpu is not None:
                gpu = self._select_gpu(request.gpu, gpu_usage)
                if gpu is None:
                    return None
                assigned_gpu = AssignedGpuResources(
                    device_id=gpu.device_id,
                    vram_mib=request.gpu.vram_mib,
                    compute_slots=request.gpu.compute_slots,
                    exclusive=request.gpu.exclusive,
                )

            lease_id = f"LEASE-{self._next_lease:08d}"
            self._next_lease += 1
            lease = ResourceLease(
                lease_id=lease_id,
                owner_id=owner_id,
                cpu_slots=request.cpu_slots,
                ram_mib=request.ram_mib,
                gpu=assigned_gpu,
            )
            self._leases[lease_id] = lease
            return lease

    def acquire(self, owner_id: str, request: ResourceRequest) -> ResourceLease:
        lease = self.try_acquire(owner_id, request)
        if lease is None:
            raise ResourceUnavailable(f"resources are currently unavailable for {owner_id}")
        return lease

    def release(self, lease_id: str) -> bool:
        if not isinstance(lease_id, str) or not lease_id:
            raise ValueError("lease_id must be a non-empty string")
        with self._lock:
            return self._leases.pop(lease_id, None) is not None

    def lease(self, lease_id: str) -> ResourceLease:
        with self._lock:
            try:
                return self._leases[lease_id]
            except KeyError as exc:
                raise KeyError(lease_id) from exc

    @contextmanager
    def hold(self, owner_id: str, request: ResourceRequest) -> Iterator[ResourceLease]:
        lease = self.acquire(owner_id, request)
        try:
            yield lease
        finally:
            self.release(lease.lease_id)

    def status(self) -> ResourceSchedulerStatus:
        with self._lock:
            used_cpu, used_ram, gpu_usage = self._usage()
            gpu_status: list[GpuResourceStatus] = []
            for gpu in sorted(self.capacity.gpus, key=lambda item: item.device_id):
                used_vram, used_compute, exclusive = gpu_usage[gpu.device_id]
                gpu_status.append(
                    GpuResourceStatus(
                        device_id=gpu.device_id,
                        total_vram_mib=gpu.vram_mib,
                        reserved_headroom_mib=gpu.reserve_vram_mib,
                        usable_vram_mib=gpu.usable_vram_mib,
                        used_vram_mib=used_vram,
                        free_vram_mib=gpu.usable_vram_mib - used_vram,
                        compute_slots=gpu.compute_slots,
                        used_compute_slots=used_compute,
                        free_compute_slots=gpu.compute_slots - used_compute,
                        exclusive_active=exclusive,
                    )
                )
            return ResourceSchedulerStatus(
                cpu_slots=self.capacity.cpu_slots,
                used_cpu_slots=used_cpu,
                free_cpu_slots=self.capacity.cpu_slots - used_cpu,
                ram_mib=self.capacity.ram_mib,
                used_ram_mib=used_ram,
                free_ram_mib=self.capacity.ram_mib - used_ram,
                gpus=tuple(gpu_status),
                active_leases=tuple(
                    sorted(self._leases.values(), key=lambda item: item.lease_id)
                ),
                max_active_leases=self.capacity.max_active_leases,
            )
