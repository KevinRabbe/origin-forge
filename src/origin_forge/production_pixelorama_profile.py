from __future__ import annotations

import os
from pathlib import Path

from .pixelorama_cli_export import PixeloramaCliProfile
from .production_work_order_models import content_hash


class ProductionPixeloramaProfileError(RuntimeError):
    pass


_EXECUTABLE_ENV = "ORIGIN_FORGE_PIXELORAMA_EXECUTABLE"
_FINGERPRINT_ENV = "ORIGIN_FORGE_PIXELORAMA_SHA256"
_VERSION_ENV = "ORIGIN_FORGE_PIXELORAMA_VERSION"


def load_infrastructure_pixelorama_cli_profile() -> PixeloramaCliProfile:
    """Load one operator-owned profile without reading or launching the executable."""

    executable = os.environ.get(_EXECUTABLE_ENV)
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
