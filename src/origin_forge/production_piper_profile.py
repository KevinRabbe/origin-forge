from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .audio_models import AudioOperation
from .audio_profiles import AudioProfileKind, GovernedAudioProfile
from .production_work_order_models import content_hash


class ProductionPiperProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class PiperInfrastructure:
    runtime_root: Path
    executable: Path
    espeak_data_path: Path
    model_path: Path
    model_config_path: Path
    license_path: Path

    def __post_init__(self) -> None:
        values = (
            (self.runtime_root, "runtime_root"),
            (self.executable, "executable"),
            (self.espeak_data_path, "espeak_data_path"),
            (self.model_path, "model_path"),
            (self.model_config_path, "model_config_path"),
            (self.license_path, "license_path"),
        )
        for value, label in values:
            if not isinstance(value, Path) or not value.is_absolute():
                raise ProductionPiperProfileError(f"Piper {label} must be an absolute path")

    @property
    def dependency_hash(self) -> str:
        return content_hash({label: str(value) for value, label in (
            (self.runtime_root, "runtime_root"),
            (self.executable, "executable"),
            (self.espeak_data_path, "espeak_data_path"),
            (self.model_path, "model_path"),
            (self.model_config_path, "model_config_path"),
            (self.license_path, "license_path"),
        )})


def _required(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise ProductionPiperProfileError(f"missing explicit Piper configuration: {name}")
    path = Path(value)
    if not path.is_absolute():
        raise ProductionPiperProfileError(f"Piper configuration {name} must be absolute")
    return path


def load_infrastructure_piper_profile() -> PiperInfrastructure:
    return PiperInfrastructure(
        runtime_root=_required("ORIGIN_FORGE_PIPER_RUNTIME_ROOT"),
        executable=_required("ORIGIN_FORGE_PIPER_EXECUTABLE"),
        espeak_data_path=_required("ORIGIN_FORGE_PIPER_ESPEAK_DATA"),
        model_path=_required("ORIGIN_FORGE_PIPER_MODEL"),
        model_config_path=_required("ORIGIN_FORGE_PIPER_MODEL_CONFIG"),
        license_path=_required("ORIGIN_FORGE_PIPER_LICENSE"),
    )


def require_piper_profile(value: object) -> GovernedAudioProfile:
    if not isinstance(value, dict):
        raise ProductionPiperProfileError("Piper AUDIO_PROFILE projection must be an object")
    try:
        profile = GovernedAudioProfile(
            profile_id=value["profile_id"],
            kind=AudioProfileKind(value["kind"]),
            operation=AudioOperation(value["operation"]),
            backend_id=value["backend_id"],
            backend_version=value["backend_version"],
            runtime_hash=value["runtime_hash"],
            target_sample_rate=value["target_sample_rate"],
            target_channels=value["target_channels"],
            model_id=value["model_id"],
            model_hash=value["model_hash"],
            model_config_hash=value["model_config_hash"],
            license_id=value["license_id"],
            license_hash=value["license_hash"],
        )
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise ProductionPiperProfileError("Piper AUDIO_PROFILE projection is invalid") from exc
    if value.get("profile_hash") != profile.profile_hash:
        raise ProductionPiperProfileError("Piper AUDIO_PROFILE projection hash drifted")
    return profile
