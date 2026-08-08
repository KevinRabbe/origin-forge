from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .model_inspection import inspect_model_policy, inspect_model_registry
from .model_scheduler_factory import create_model_scheduling


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.model_resource_cli",
        description="Inspect configured Origin Forge model/resource scheduling without loading a model.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "status",
        help="show configured process-local capacity, model profiles, and explicit policies",
    )
    return parser


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.project_root)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "enabled": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    if args.command != "status":
        raise AssertionError(args.command)

    resource_models = config.resource_models
    if not resource_models.enabled:
        print(
            json.dumps(
                {
                    "config_version": config.version,
                    "enabled": False,
                    "profiles": [],
                    "policies": [],
                    "resource_status": None,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    try:
        configured = create_model_scheduling(resource_models)
        profiles = inspect_model_registry(configured.registry, configured.resources)
        policies = tuple(
            inspect_model_policy(configured.registry, configured.resources, policy)
            for policy in resource_models.policies
        )
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "config_version": config.version,
                    "enabled": True,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    print(
        json.dumps(
            {
                "config_version": config.version,
                "enabled": True,
                "profiles": [profile.to_dict() for profile in profiles],
                "policies": [policy.to_dict() for policy in policies],
                "resource_status": _resource_status(configured.resources.status()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
