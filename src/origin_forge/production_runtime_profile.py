from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .production_work_order_models import content_hash
from .runtime_observer import sha256_file


class RuntimeInfrastructureError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeObservationInfrastructure:
    executable: Path
    executable_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path) or not self.executable.is_absolute():
            raise RuntimeInfrastructureError("runtime executable must be an absolute path")
        if not isinstance(self.executable_hash, str) or not self.executable_hash.startswith("sha256:"):
            raise RuntimeInfrastructureError("runtime executable hash is invalid")

    @property
    def dependency_hash(self) -> str:
        return content_hash({"executable": str(self.executable), "executable_hash": self.executable_hash})


def load_runtime_observation_infrastructure() -> RuntimeObservationInfrastructure:
    value = os.environ.get("ORIGIN_FORGE_RUNTIME_EXECUTABLE")
    if not value:
        raise RuntimeInfrastructureError(
            "missing explicit runtime observation configuration: ORIGIN_FORGE_RUNTIME_EXECUTABLE"
        )
    executable = Path(value)
    if not executable.is_absolute():
        raise RuntimeInfrastructureError("ORIGIN_FORGE_RUNTIME_EXECUTABLE must be absolute")
    try:
        executable_hash = sha256_file(executable)
    except (OSError, RuntimeError) as exc:
        raise RuntimeInfrastructureError("configured runtime executable cannot be fingerprinted") from exc
    return RuntimeObservationInfrastructure(executable, executable_hash)
