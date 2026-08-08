from __future__ import annotations

from dataclasses import dataclass

from .model_scheduler import (
    ModelProfileError,
    ModelProfileRegistry,
    ModelResourceProfile,
    ModelRole,
    ModelSelectionPolicy,
)
from .resource_inspection import ResourceAdmissionInspection, inspect_resource_request
from .resource_scheduler import ResourceScheduler


@dataclass(frozen=True)
class ModelProfileInspection:
    profile_id: str
    role: str
    model_id: str
    runtime_id: str
    model_hash: str | None
    resource: ResourceAdmissionInspection

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "role": self.role,
            "model_id": self.model_id,
            "runtime_id": self.runtime_id,
            "model_hash": self.model_hash,
            "resource": self.resource.to_dict(),
        }


@dataclass(frozen=True)
class ModelPolicyInspection:
    role: str
    requested_profile_id: str
    fallback_profile_ids: tuple[str, ...]
    profiles: tuple[ModelProfileInspection, ...]
    selected_profile_id: str | None
    fallback_would_be_used: bool

    @property
    def currently_schedulable(self) -> bool:
        return self.selected_profile_id is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "requested_profile_id": self.requested_profile_id,
            "fallback_profile_ids": list(self.fallback_profile_ids),
            "selected_profile_id": self.selected_profile_id,
            "fallback_would_be_used": self.fallback_would_be_used,
            "currently_schedulable": self.currently_schedulable,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }


def inspect_model_profile(
    profile: ModelResourceProfile,
    resources: ResourceScheduler,
) -> ModelProfileInspection:
    if not isinstance(profile, ModelResourceProfile):
        raise TypeError("profile must be a ModelResourceProfile")
    if not isinstance(resources, ResourceScheduler):
        raise TypeError("resources must be a ResourceScheduler")
    return ModelProfileInspection(
        profile_id=profile.profile_id,
        role=profile.role.value,
        model_id=profile.model_id,
        runtime_id=profile.runtime_id,
        model_hash=profile.model_hash,
        resource=inspect_resource_request(resources, profile.resources),
    )


def inspect_model_registry(
    registry: ModelProfileRegistry,
    resources: ResourceScheduler,
    *,
    role: ModelRole | None = None,
) -> tuple[ModelProfileInspection, ...]:
    if not isinstance(registry, ModelProfileRegistry):
        raise TypeError("registry must be a ModelProfileRegistry")
    if role is not None and not isinstance(role, ModelRole):
        raise TypeError("role must be a ModelRole or null")
    profiles = registry.all() if role is None else registry.profiles_for_role(role)
    return tuple(inspect_model_profile(profile, resources) for profile in profiles)


def inspect_model_policy(
    registry: ModelProfileRegistry,
    resources: ResourceScheduler,
    policy: ModelSelectionPolicy,
) -> ModelPolicyInspection:
    if not isinstance(policy, ModelSelectionPolicy):
        raise TypeError("policy must be a ModelSelectionPolicy")

    profiles = tuple(
        registry.profile(profile_id) for profile_id in policy.ordered_profile_ids
    )
    mismatched = [profile.profile_id for profile in profiles if profile.role != policy.role]
    if mismatched:
        raise ModelProfileError(
            f"model selection policy role {policy.role.value} does not match profiles: {', '.join(mismatched)}"
        )

    inspections = tuple(inspect_model_profile(profile, resources) for profile in profiles)
    selected = next(
        (
            inspection.profile_id
            for inspection in inspections
            if inspection.resource.static_compatible
            and inspection.resource.currently_available
        ),
        None,
    )
    return ModelPolicyInspection(
        role=policy.role.value,
        requested_profile_id=policy.primary_profile_id,
        fallback_profile_ids=policy.fallback_profile_ids,
        profiles=inspections,
        selected_profile_id=selected,
        fallback_would_be_used=(
            selected is not None and selected != policy.primary_profile_id
        ),
    )
