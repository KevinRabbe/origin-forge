from __future__ import annotations

from .config import ProjectConfig
from .podman_sandbox import PodmanSandboxBackend, PodmanSandboxSettings
from .runtime import OriginForgeRuntime
from .sandbox import SandboxBackend, UnconfiguredSandboxBackend


def create_sandbox_backend(
    runtime: OriginForgeRuntime, config: ProjectConfig
) -> SandboxBackend:
    backend = config.sandbox_backend.lower()
    if backend in {"", "unconfigured", "none"}:
        return UnconfiguredSandboxBackend()
    if backend == "podman":
        if not config.sandbox_image:
            raise ValueError("sandbox.backend='podman' requires sandbox.image")
        return PodmanSandboxBackend(
            runtime.state_dir,
            PodmanSandboxSettings(
                image=config.sandbox_image,
                memory=config.sandbox_memory,
                cpus=config.sandbox_cpus,
                pids_limit=config.sandbox_pids_limit,
            ),
        )
    raise ValueError(f"unsupported sandbox backend: {config.sandbox_backend}")
