from __future__ import annotations

from dataclasses import dataclass

from .model_scheduler import ModelProfileRegistry, ModelScheduler
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
        raise ModelSchedulingDisabled(
            "resource-aware model scheduling is disabled in protected project configuration"
        )
    resources = ResourceScheduler(config.capacity)
    registry = config.registry()
    scheduler = ModelScheduler(registry, resources)
    return ConfiguredModelScheduling(resources, registry, scheduler)
