from __future__ import annotations

from dataclasses import dataclass

from .model_scheduler import (
    ModelProfileRegistry,
    ModelScheduler,
    ModelSelectionPolicy,
)
from .resource_model_config import ResourceModelConfig
from .resource_scheduler import ResourceScheduler


class ModelSchedulingDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfiguredModelScheduling:
    resources: ResourceScheduler
    registry: ModelProfileRegistry
    scheduler: ModelScheduler


def create_model_scheduling(config: ResourceModelConfig) -> ConfiguredModelScheduling:
    """Construct process-local scheduling state without loading any model."""

    if not isinstance(config, ResourceModelConfig):
        raise TypeError("config must be a ResourceModelConfig")
    if not config.enabled or config.capacity is None:
        if config.profiles or config.policies:
            raise ValueError(
                "disabled resource scheduling cannot contain model profiles or policies"
            )
        raise ModelSchedulingDisabled(
            "resource-aware model scheduling is disabled in protected project configuration"
        )

    registry = config.registry()
    seen_roles = set()
    for policy in config.policies:
        if not isinstance(policy, ModelSelectionPolicy):
            raise TypeError("resource model config policies must contain ModelSelectionPolicy values")
        if policy.role in seen_roles:
            raise ValueError(f"duplicate configured model policy role: {policy.role.value}")
        seen_roles.add(policy.role)
        profiles = tuple(
            registry.profile(profile_id) for profile_id in policy.ordered_profile_ids
        )
        mismatched = [
            profile.profile_id for profile in profiles if profile.role != policy.role
        ]
        if mismatched:
            raise ValueError(
                f"configured model policy role {policy.role.value} does not match profiles: {', '.join(mismatched)}"
            )

    resources = ResourceScheduler(config.capacity)
    scheduler = ModelScheduler(registry, resources)
    return ConfiguredModelScheduling(resources, registry, scheduler)
