from __future__ import annotations

import os
from pathlib import Path

from .blender_adapter import BlenderRuntimeProfile, blender_runner_v1_fingerprint
from .config import load_config
from .production_work_order_models import content_hash


class ProductionBlenderProfileError(RuntimeError):
    pass


_RUNTIME_ROOT_ENV = "ORIGIN_FORGE_BLENDER_RUNTIME_ROOT"
_EXECUTABLE_ENV = "ORIGIN_FORGE_BLENDER_EXECUTABLE"
_RUNTIME_HASH_ENV = "ORIGIN_FORGE_BLENDER_RUNTIME_SHA256"
_VERSION_ENV = "ORIGIN_FORGE_BLENDER_VERSION"


def load_infrastructure_blender_runtime_profile(
    project_root: str | Path | None = None,
) -> BlenderRuntimeProfile:
    """Load one operator-owned Blender profile without reading or launching the runtime."""

    runtime_root = os.environ.get(_RUNTIME_ROOT_ENV)
    executable = os.environ.get(_EXECUTABLE_ENV)
    if project_root is not None:
        configured = load_config(project_root).external_tools.path("blender")
        if configured is not None:
            executable = configured
    runtime_hash = os.environ.get(_RUNTIME_HASH_ENV)
    version = os.environ.get(_VERSION_ENV)
    if not runtime_root or not executable or not runtime_hash or not version:
        raise ProductionBlenderProfileError(
            "trusted Blender production profile environment is incomplete"
        )
    runtime_root_path = Path(runtime_root).expanduser()
    executable_path = Path(executable).expanduser()
    if not runtime_root_path.is_absolute():
        raise ProductionBlenderProfileError(
            "trusted Blender runtime root path must be absolute"
        )
    if not executable_path.is_absolute():
        raise ProductionBlenderProfileError(
            "trusted Blender executable path must be absolute"
        )
    try:
        return BlenderRuntimeProfile(
            runtime_root=runtime_root_path,
            executable=executable_path,
            runtime_hash=runtime_hash,
            expected_blender_version=version,
            runner_fingerprint=blender_runner_v1_fingerprint(),
        )
    except (TypeError, ValueError) as exc:
        raise ProductionBlenderProfileError(
            "trusted Blender production profile is invalid"
        ) from exc


def blender_runtime_profile_dependency_hash(profile: BlenderRuntimeProfile) -> str:
    if not isinstance(profile, BlenderRuntimeProfile):
        raise TypeError("profile must be a BlenderRuntimeProfile")
    return content_hash(
        {
            "kind": "BLENDER_RUNTIME_PROFILE",
            "version": 1,
            "runtime_root": str(profile.runtime_root),
            "executable": str(profile.executable),
            "runtime_hash": profile.runtime_hash,
            "expected_blender_version": profile.expected_blender_version,
            "runner_fingerprint": profile.runner_fingerprint,
            "max_runtime_files": profile.max_runtime_files,
            "max_runtime_bytes": profile.max_runtime_bytes,
        }
    )
