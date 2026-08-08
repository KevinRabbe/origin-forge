from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator, Protocol, Sequence

from .resource_scheduler import (
    ResourceLease,
    ResourceRequest,
    ResourceRequestInvalid,
    ResourceScheduler,
)


_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ModelSchedulingError(RuntimeError):
    pass


class ModelProfileError(ModelSchedulingError):
    pass


class ModelCapacityUnavailable(ModelSchedulingError):
    pass


class ModelRole(StrEnum):
    CODER_FAST = "coder_fast"
    CODER_STRONG = "coder_strong"
    VISION = "vision"
    IMAGE_GENERATOR = "image_generator"
    AUDIO_GENERATOR = "audio_generator"
    SPEECH = "speech"


@dataclass(frozen=True)
class ModelResourceProfile:
    profile_id: str
    role: ModelRole
    model_id: str
    runtime_id: str
    resources: ResourceRequest
    model_hash: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.profile_id, "profile_id"),
            (self.model_id, "model_id"),
            (self.runtime_id, "runtime_id"),
        ):
            if not isinstance(value, str) or not _PROFILE_ID_RE.fullmatch(value):
                raise ValueError(f"invalid model profile {name}: {value!r}")
        if not isinstance(self.role, ModelRole):
            raise ValueError("model profile role must be a ModelRole")
        if not isinstance(self.resources, ResourceRequest):
            raise ValueError("model profile resources must be a ResourceRequest")
        if self.model_hash is not None and (
            not isinstance(self.model_hash, str) or not self.model_hash.strip()
        ):
            raise ValueError("model profile model_hash must be a non-empty string or null")

    def to_dict(self) -> dict[str, object]:
        gpu = self.resources.gpu
        return {
            "profile_id": self.profile_id,
            "role": self.role.value,
            "model_id": self.model_id,
            "runtime_id": self.runtime_id,
            "model_hash": self.model_hash,
            "resources": {
                "cpu_slots": self.resources.cpu_slots,
                "ram_mib": self.resources.ram_mib,
                "gpu": None
                if gpu is None
                else {
                    "vram_mib": gpu.vram_mib,
                    "compute_slots": gpu.compute_slots,
                    "device_id": gpu.device_id,
                    "exclusive": gpu.exclusive,
                },
            },
        }


class ModelProfileRegistry:
    """Immutable model profile catalog with no implicit routing policy."""

    def __init__(self, profiles: Sequence[ModelResourceProfile]):
        values = tuple(profiles)
        if any(not isinstance(profile, ModelResourceProfile) for profile in values):
            raise TypeError("model profile registry requires ModelResourceProfile values")
        ids = [profile.profile_id for profile in values]
        if len(ids) != len(set(ids)):
            raise ModelProfileError("model profile registry contains duplicate profile IDs")
        self._profiles = values
        self._by_id = {profile.profile_id: profile for profile in values}

    def profile(self, profile_id: str) -> ModelResourceProfile:
        try:
            return self._by_id[profile_id]
        except KeyError as exc:
            raise ModelProfileError(f"unknown model profile: {profile_id}") from exc

    def profiles_for_role(self, role: ModelRole) -> tuple[ModelResourceProfile, ...]:
        if not isinstance(role, ModelRole):
            raise TypeError("role must be a ModelRole")
        return tuple(
            sorted(
                (profile for profile in self._profiles if profile.role == role),
                key=lambda profile: profile.profile_id,
            )
        )

    def all(self) -> tuple[ModelResourceProfile, ...]:
        return tuple(sorted(self._profiles, key=lambda profile: profile.profile_id))


@dataclass(frozen=True)
class ModelSelectionPolicy:
    role: ModelRole
    primary_profile_id: str
    fallback_profile_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.role, ModelRole):
            raise ValueError("model selection role must be a ModelRole")
        if not isinstance(self.primary_profile_id, str) or not _PROFILE_ID_RE.fullmatch(
            self.primary_profile_id
        ):
            raise ValueError("model selection primary_profile_id is invalid")
        if any(
            not isinstance(profile_id, str) or not _PROFILE_ID_RE.fullmatch(profile_id)
            for profile_id in self.fallback_profile_ids
        ):
            raise ValueError("model selection fallback profile ID is invalid")
        ordered = (self.primary_profile_id, *self.fallback_profile_ids)
        if len(ordered) != len(set(ordered)):
            raise ValueError("model selection policy contains duplicate profile IDs")

    @property
    def ordered_profile_ids(self) -> tuple[str, ...]:
        return (self.primary_profile_id, *self.fallback_profile_ids)


@dataclass(frozen=True)
class ScheduledModel:
    requested_profile_id: str
    profile: ModelResourceProfile
    lease: ResourceLease
    attempted_profile_ids: tuple[str, ...]

    @property
    def fallback_used(self) -> bool:
        return self.profile.profile_id != self.requested_profile_id

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_profile_id": self.requested_profile_id,
            "selected_profile": self.profile.to_dict(),
            "lease": self.lease.to_dict(),
            "attempted_profile_ids": list(self.attempted_profile_ids),
            "fallback_used": self.fallback_used,
        }


class ManagedModelLoader(Protocol):
    """Runtime-specific lifecycle adapter used only after a resource lease exists."""

    def load(self, profile: ModelResourceProfile, lease: ResourceLease) -> object: ...

    def unload(self, instance: object) -> None: ...


@dataclass(frozen=True)
class ManagedModelSession:
    scheduled: ScheduledModel
    instance: object


class ModelScheduler:
    """Select explicit model profiles and hold their hardware resources atomically.

    The registry is inventory, not policy. Only the primary profile and fallback
    profiles explicitly named by ModelSelectionPolicy may be considered.
    Resource contention or static hardware mismatch never authorizes an
    unlisted downgrade.
    """

    def __init__(
        self,
        registry: ModelProfileRegistry,
        resources: ResourceScheduler,
    ):
        if not isinstance(registry, ModelProfileRegistry):
            raise TypeError("registry must be a ModelProfileRegistry")
        if not isinstance(resources, ResourceScheduler):
            raise TypeError("resources must be a ResourceScheduler")
        self.registry = registry
        self.resources = resources

    def _validated_chain(
        self, policy: ModelSelectionPolicy
    ) -> tuple[ModelResourceProfile, ...]:
        if not isinstance(policy, ModelSelectionPolicy):
            raise TypeError("policy must be a ModelSelectionPolicy")
        profiles = tuple(
            self.registry.profile(profile_id) for profile_id in policy.ordered_profile_ids
        )
        mismatched = [
            profile.profile_id for profile in profiles if profile.role != policy.role
        ]
        if mismatched:
            raise ModelProfileError(
                f"model selection policy role {policy.role.value} does not match profiles: {', '.join(mismatched)}"
            )
        return profiles

    def try_acquire(
        self,
        owner_id: str,
        policy: ModelSelectionPolicy,
    ) -> ScheduledModel | None:
        profiles = self._validated_chain(policy)
        attempted: list[str] = []
        for profile in profiles:
            attempted.append(profile.profile_id)
            try:
                lease = self.resources.try_acquire(owner_id, profile.resources)
            except ResourceRequestInvalid:
                # A profile may legitimately describe hardware not present on
                # this machine. Continue only because every later profile was
                # explicitly authorized by the caller's fallback chain.
                lease = None
            if lease is not None:
                return ScheduledModel(
                    requested_profile_id=policy.primary_profile_id,
                    profile=profile,
                    lease=lease,
                    attempted_profile_ids=tuple(attempted),
                )
        return None

    def acquire(
        self,
        owner_id: str,
        policy: ModelSelectionPolicy,
    ) -> ScheduledModel:
        scheduled = self.try_acquire(owner_id, policy)
        if scheduled is None:
            raise ModelCapacityUnavailable(
                "no explicitly allowed model profile currently fits available resources: "
                + ", ".join(policy.ordered_profile_ids)
            )
        return scheduled

    def release(self, scheduled: ScheduledModel) -> bool:
        if not isinstance(scheduled, ScheduledModel):
            raise TypeError("scheduled must be a ScheduledModel")
        return self.resources.release(scheduled.lease.lease_id)

    @contextmanager
    def hold(
        self,
        owner_id: str,
        policy: ModelSelectionPolicy,
    ) -> Iterator[ScheduledModel]:
        scheduled = self.acquire(owner_id, policy)
        try:
            yield scheduled
        finally:
            self.release(scheduled)

    @contextmanager
    def use(
        self,
        owner_id: str,
        policy: ModelSelectionPolicy,
        loader: ManagedModelLoader,
    ) -> Iterator[ManagedModelSession]:
        scheduled = self.acquire(owner_id, policy)
        instance: object | None = None
        body_error: BaseException | None = None
        try:
            instance = loader.load(scheduled.profile, scheduled.lease)
            try:
                yield ManagedModelSession(scheduled, instance)
            except BaseException as exc:
                body_error = exc
                raise
            finally:
                if instance is not None:
                    try:
                        loader.unload(instance)
                    except BaseException:
                        # Never hide the original task failure with a cleanup
                        # error. If the body succeeded, cleanup failure remains
                        # visible to the caller.
                        if body_error is None:
                            raise
        finally:
            self.release(scheduled)
