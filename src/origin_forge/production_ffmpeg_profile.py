from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig, load_config
from .production_work_order_models import content_hash
from .runtime import OriginForgeRuntime


class FfmpegInfrastructureError(RuntimeError):
    pass


@dataclass(frozen=True)
class FfmpegInfrastructure:
    executable: Path
    executable_hash: str
    dependency_hash: str


def load_infrastructure_ffmpeg_profile(
    runtime: OriginForgeRuntime,
    profile_runtime_hash: str,
) -> FfmpegInfrastructure:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(profile_runtime_hash, str) or not profile_runtime_hash.startswith("sha256:"):
        raise FfmpegInfrastructureError("FFmpeg profile executable hash is invalid")
    config: ProjectConfig = load_config(runtime.project_root)
    configured = config.external_tools.path("ffmpeg")
    if configured is None:
        raise FfmpegInfrastructureError(
            "FFmpeg is not configured; set [tools].ffmpeg to an absolute executable path"
        )
    executable = Path(configured)
    if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        raise FfmpegInfrastructureError(
            "configured FFmpeg path must be an accessible absolute regular file"
        )
    actual_hash = "sha256:" + hashlib.sha256(executable.read_bytes()).hexdigest()
    if actual_hash != profile_runtime_hash:
        raise FfmpegInfrastructureError("configured FFmpeg executable hash does not match governed profile")
    return FfmpegInfrastructure(
        executable=executable,
        executable_hash=actual_hash,
        dependency_hash=content_hash({
            "executable": str(executable),
            "executable_hash": actual_hash,
            "configuration": "explicit-absolute-path@1",
        }),
    )
