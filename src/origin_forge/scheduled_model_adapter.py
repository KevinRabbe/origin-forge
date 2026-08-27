from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import ModelAdapter, ModelRequest, ModelResponse
from .model_scheduler import (
    ManagedModelLoader,
    ModelProfileError,
    ModelScheduler,
    ModelSelectionPolicy,
    ScheduledModel,
)
from .runtime import OriginForgeRuntime


class ModelScheduleRecorder(Protocol):
    def record(self, run_id: str, scheduled: ScheduledModel) -> str | None: ...


@dataclass(frozen=True)
class RuntimeModelScheduleRecorder:
    runtime: OriginForgeRuntime

    def record(self, run_id: str, scheduled: ScheduledModel) -> str:
        gpu = scheduled.lease.gpu
        return self.runtime.record_verification(
            "RUN",
            run_id,
            verification_type="model-resource-selection",
            verifier="OriginForge.RuntimeModelScheduleRecorder",
            status="PASS",
            evidence={
                "requested_profile_id": scheduled.requested_profile_id,
                "selected_profile_id": scheduled.profile.profile_id,
                "role": scheduled.profile.role.value,
                "model_id": scheduled.profile.model_id,
                "model_hash": scheduled.profile.model_hash,
                "runtime_id": scheduled.profile.runtime_id,
                "attempted_profile_ids": list(scheduled.attempted_profile_ids),
                "fallback_used": scheduled.fallback_used,
                "lease_id": scheduled.lease.lease_id,
                "gpu_device_id": gpu.device_id if gpu is not None else None,
                "gpu_exclusive": gpu.exclusive if gpu is not None else False,
            },
            metrics={
                "cpu_slots": scheduled.lease.cpu_slots,
                "ram_mib": scheduled.lease.ram_mib,
                "vram_mib": gpu.vram_mib if gpu is not None else 0,
                "gpu_compute_slots": gpu.compute_slots if gpu is not None else 0,
            },
            run_id=run_id,
        )


class ScheduledModelAdapter:
    """ModelAdapter bridge that leases resources before runtime model loading.

    Existing Worker/Retry code may treat this as a normal ModelAdapter. The
    wrapped runtime-specific loader is invoked only after an atomic model
    resource lease exists. The selected profile is recorded before generation.
    """

    def __init__(
        self,
        scheduler: ModelScheduler,
        policy: ModelSelectionPolicy,
        loader: ManagedModelLoader,
        *,
        recorder: ModelScheduleRecorder | None = None,
    ):
        if not isinstance(scheduler, ModelScheduler):
            raise TypeError("scheduler must be a ModelScheduler")
        if not isinstance(policy, ModelSelectionPolicy):
            raise TypeError("policy must be a ModelSelectionPolicy")
        self.scheduler = scheduler
        self.policy = policy
        self.loader = loader
        self.recorder = recorder
        # Validate the entire explicit chain at construction, before any Run.
        self._profiles = tuple(
            scheduler.registry.profile(profile_id)
            for profile_id in policy.ordered_profile_ids
        )
        mismatched = [
            profile.profile_id for profile in self._profiles if profile.role != policy.role
        ]
        if mismatched:
            raise ModelProfileError(
                f"model selection policy role {policy.role.value} does not match profiles: {', '.join(mismatched)}"
            )

    @property
    def model_id(self) -> str:
        # Preserve the existing ModelAdapter API: before a request is scheduled,
        # the only truthful model identity is the requested primary model.
        return self._profiles[0].model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise TypeError("request must be a ModelRequest")
        with self.scheduler.use(request.run_id, self.policy, self.loader) as session:
            instance = session.instance
            if not isinstance(instance, ModelAdapter):
                raise ModelProfileError(
                    f"runtime {session.scheduled.profile.runtime_id} did not load a ModelAdapter"
                )
            if instance.model_id != session.scheduled.profile.model_id:
                raise ModelProfileError(
                    "loaded model identity does not match selected profile: "
                    f"{instance.model_id!r} != {session.scheduled.profile.model_id!r}"
                )
            if self.recorder is not None:
                self.recorder.record(request.run_id, session.scheduled)
            return instance.generate(request)
