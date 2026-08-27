from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .production_work_order_models import content_hash
from .runtime_observer import sha256_file


class PlaytestInfrastructureError(RuntimeError):
    pass


@dataclass(frozen=True)
class CooperativePlaytestInfrastructure:
    executable: Path
    executable_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path) or not self.executable.is_absolute():
            raise PlaytestInfrastructureError(
                "playtest harness executable must be absolute"
            )
        if not isinstance(
            self.executable_hash, str
        ) or not self.executable_hash.startswith("sha256:"):
            raise PlaytestInfrastructureError(
                "playtest harness executable hash is invalid"
            )

    @property
    def dependency_hash(self) -> str:
        return content_hash(
            {
                "executable": str(self.executable),
                "executable_hash": self.executable_hash,
            }
        )


def load_cooperative_playtest_infrastructure() -> CooperativePlaytestInfrastructure:
    value = os.environ.get("ORIGIN_FORGE_PLAYTEST_EXECUTABLE")
    if not value:
        raise PlaytestInfrastructureError(
            "missing explicit playtest configuration: ORIGIN_FORGE_PLAYTEST_EXECUTABLE"
        )
    executable = Path(value)
    if not executable.is_absolute():
        raise PlaytestInfrastructureError(
            "ORIGIN_FORGE_PLAYTEST_EXECUTABLE must be absolute"
        )
    try:
        executable_hash = sha256_file(executable)
    except (OSError, RuntimeError) as exc:
        raise PlaytestInfrastructureError(
            "configured playtest harness cannot be fingerprinted"
        ) from exc
    return CooperativePlaytestInfrastructure(executable, executable_hash)
