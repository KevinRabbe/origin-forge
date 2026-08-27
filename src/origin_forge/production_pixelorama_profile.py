from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from .config import load_config
from .pixelorama_cli_export import PixeloramaCliProfile
from .pixelorama_bridge import PixeloramaBridgeProfile
from .pixelorama_models import BridgeOperation
from .production_work_order_models import content_hash


class ProductionPixeloramaProfileError(RuntimeError):
    pass


_EXECUTABLE_ENV = "ORIGIN_FORGE_PIXELORAMA_EXECUTABLE"
_FINGERPRINT_ENV = "ORIGIN_FORGE_PIXELORAMA_SHA256"
_VERSION_ENV = "ORIGIN_FORGE_PIXELORAMA_VERSION"
_BRIDGE_ID_ENV = "ORIGIN_FORGE_PIXELORAMA_BRIDGE_ID"
_BRIDGE_VERSION_ENV = "ORIGIN_FORGE_PIXELORAMA_BRIDGE_VERSION"
_BRIDGE_FINGERPRINT_ENV = "ORIGIN_FORGE_PIXELORAMA_BRIDGE_SHA256"
_BRIDGE_PACKAGE_ENV = "ORIGIN_FORGE_PIXELORAMA_BRIDGE_PACKAGE"
_BRIDGE_ARGS_ENV = "ORIGIN_FORGE_PIXELORAMA_BRIDGE_ARGS_JSON"


def load_infrastructure_pixelorama_cli_profile(
    project_root: str | Path | None = None,
) -> PixeloramaCliProfile:
    """Load one operator-owned profile without reading or launching the executable."""

    executable = os.environ.get(_EXECUTABLE_ENV)
    if project_root is not None:
        configured = load_config(project_root).external_tools.path("pixelorama")
        if configured is not None:
            executable = configured
    fingerprint = os.environ.get(_FINGERPRINT_ENV)
    version = os.environ.get(_VERSION_ENV)
    if not executable or not fingerprint or not version:
        raise ProductionPixeloramaProfileError(
            "trusted Pixelorama production profile environment is incomplete"
        )
    path = Path(executable)
    if not path.is_absolute():
        raise ProductionPixeloramaProfileError(
            "trusted Pixelorama executable path must be absolute"
        )
    try:
        return PixeloramaCliProfile(
            pixelorama_executable=path,
            pixelorama_fingerprint=fingerprint,
            expected_pixelorama_version=version,
        )
    except (TypeError, ValueError) as exc:
        raise ProductionPixeloramaProfileError(
            "trusted Pixelorama production profile is invalid"
        ) from exc


def pixelorama_cli_profile_dependency_hash(profile: PixeloramaCliProfile) -> str:
    if not isinstance(profile, PixeloramaCliProfile):
        raise TypeError("profile must be a PixeloramaCliProfile")
    return content_hash(
        {
            "kind": "PIXELORAMA_CLI_PROFILE",
            "version": 1,
            "pixelorama_executable": str(profile.pixelorama_executable),
            "pixelorama_fingerprint": profile.pixelorama_fingerprint,
            "expected_pixelorama_version": profile.expected_pixelorama_version,
            "allowed_operations": [value.value for value in profile.allowed_operations],
            "timeout_seconds": profile.timeout_seconds,
            "max_stdout_bytes": profile.max_stdout_bytes,
            "max_stderr_bytes": profile.max_stderr_bytes,
            "max_executable_bytes": profile.max_executable_bytes,
            "max_runtime_bytes": profile.max_runtime_bytes,
        }
    )


def load_infrastructure_pixelorama_bridge_profile(
    project_root: str | Path | None = None,
) -> PixeloramaBridgeProfile:
    """Load the explicit bridge profile required by source/animation creation."""

    executable = os.environ.get(_EXECUTABLE_ENV)
    if project_root is not None:
        configured = load_config(project_root).external_tools.path("pixelorama")
        if configured is not None:
            executable = configured
    values = {
        "bridge_id": os.environ.get(_BRIDGE_ID_ENV),
        "bridge_version": os.environ.get(_BRIDGE_VERSION_ENV),
        "bridge_fingerprint": os.environ.get(_BRIDGE_FINGERPRINT_ENV),
        "bridge_package": os.environ.get(_BRIDGE_PACKAGE_ENV),
    }
    if not executable or any(
        not isinstance(value, str) or not value for value in values.values()
    ):
        raise ProductionPixeloramaProfileError(
            "trusted Pixelorama bridge profile environment is incomplete"
        )
    try:
        bridge_id = cast(str, values["bridge_id"])
        bridge_version = cast(str, values["bridge_version"])
        bridge_fingerprint = cast(str, values["bridge_fingerprint"])
        bridge_package = cast(str, values["bridge_package"])
        if not Path(cast(str, executable)).is_absolute() or not Path(bridge_package).is_absolute():
            raise ValueError("Pixelorama executable and bridge package paths must be absolute")
        launcher_args_raw = os.environ.get(_BRIDGE_ARGS_ENV, "[]")
        launcher_args = json.loads(launcher_args_raw)
        if not isinstance(launcher_args, list) or any(
            not isinstance(value, str) for value in launcher_args
        ):
            raise ValueError("bridge launcher args must be a string array")
        return PixeloramaBridgeProfile(
            bridge_id=bridge_id,
            bridge_version=bridge_version,
            bridge_fingerprint=bridge_fingerprint,
            pixelorama_executable=Path(cast(str, executable)),
            bridge_package=Path(bridge_package),
            allowed_operations=(BridgeOperation.CREATE_SPRITE_PROJECT,),
            launcher_args=tuple(launcher_args),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProductionPixeloramaProfileError(
            "trusted Pixelorama bridge profile is invalid"
        ) from exc


def pixelorama_bridge_profile_dependency_hash(profile: PixeloramaBridgeProfile) -> str:
    if not isinstance(profile, PixeloramaBridgeProfile):
        raise TypeError("profile must be a PixeloramaBridgeProfile")
    return content_hash(
        {
            "kind": "PIXELORAMA_BRIDGE_PROFILE",
            "bridge_id": profile.bridge_id,
            "bridge_version": profile.bridge_version,
            "bridge_fingerprint": profile.bridge_fingerprint,
            "pixelorama_executable": str(profile.pixelorama_executable),
            "bridge_package": str(profile.bridge_package),
            "allowed_operations": [value.value for value in profile.allowed_operations],
            "launcher_args": list(profile.launcher_args),
            "protocol_version": profile.protocol_version,
            "timeout_seconds": profile.timeout_seconds,
            "max_stdout_bytes": profile.max_stdout_bytes,
            "max_stderr_bytes": profile.max_stderr_bytes,
        }
    )
