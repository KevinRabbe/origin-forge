from __future__ import annotations

from pathlib import Path

from .config import load_config
from .model_inspection import inspect_model_policy, inspect_model_registry
from .model_scheduler_factory import create_model_scheduling
from .production_read_guard import existing_config_path


class ModelResourceReadError(RuntimeError):
    pass


def _resource_status(status) -> dict[str, object]:
    return {
        "cpu_slots": status.cpu_slots,
        "used_cpu_slots": status.used_cpu_slots,
        "free_cpu_slots": status.free_cpu_slots,
        "ram_mib": status.ram_mib,
        "used_ram_mib": status.used_ram_mib,
        "free_ram_mib": status.free_ram_mib,
        "max_active_leases": status.max_active_leases,
        "active_lease_count": len(status.active_leases),
        "gpus": [
            {
                "device_id": gpu.device_id,
                "total_vram_mib": gpu.total_vram_mib,
                "reserved_headroom_mib": gpu.reserved_headroom_mib,
                "usable_vram_mib": gpu.usable_vram_mib,
                "used_vram_mib": gpu.used_vram_mib,
                "free_vram_mib": gpu.free_vram_mib,
                "compute_slots": gpu.compute_slots,
                "used_compute_slots": gpu.used_compute_slots,
                "free_compute_slots": gpu.free_compute_slots,
                "exclusive_active": gpu.exclusive_active,
            }
            for gpu in status.gpus
        ],
    }


def inspect_model_resources(project_root: str | Path) -> dict[str, object]:
    """Inspect configured model/resource admission without loading a model.

    The scheduler constructed here is fresh process-local inspection state. It owns
    no active leases and is never passed to a runtime loader or model adapter.
    """

    root = Path(project_root).resolve()
    existing_config_path(root)
    config = load_config(root)
    resource_models = config.resource_models
    if not resource_models.enabled:
        return {
            "config_version": config.version,
            "enabled": False,
            "profiles": [],
            "policies": [],
            "resource_status": None,
            "inspection_state_is_fresh": True,
            "model_loading_authorized": False,
            "resource_leasing_authorized": False,
            "routing_mutation_authorized": False,
        }

    try:
        configured = create_model_scheduling(resource_models)
        profiles = inspect_model_registry(configured.registry, configured.resources)
        policies = tuple(
            inspect_model_policy(configured.registry, configured.resources, policy)
            for policy in resource_models.policies
        )
        status = configured.resources.status()
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise ModelResourceReadError(
            f"configured model/resource state is invalid: {type(exc).__name__}: {exc}"
        ) from exc

    if status.active_leases:
        raise ModelResourceReadError("fresh inspection scheduler unexpectedly owns leases")

    return {
        "config_version": config.version,
        "enabled": True,
        "profiles": [value.to_dict() for value in profiles],
        "policies": [value.to_dict() for value in policies],
        "resource_status": _resource_status(status),
        "inspection_state_is_fresh": True,
        "model_loading_authorized": False,
        "resource_leasing_authorized": False,
        "routing_mutation_authorized": False,
    }
