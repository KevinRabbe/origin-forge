from __future__ import annotations

from .config import LspServerConfig, load_config
from .podman_lsp import PodmanLspBackend, PodmanLspServerSpec
from .runtime import OriginForgeRuntime


def podman_lsp_spec_from_config(config: LspServerConfig) -> PodmanLspServerSpec:
    if config.backend != "podman":
        raise ValueError(f"unsupported LSP backend: {config.backend}")
    return PodmanLspServerSpec(
        server_id=config.server_id,
        image=config.image,
        argv=config.argv,
        podman_executable=config.podman_executable,
        memory=config.memory,
        cpus=config.cpus,
        pids_limit=config.pids_limit,
        network_allowed=config.network,
        probe_timeout_seconds=config.probe_timeout_seconds,
        initialize_timeout_seconds=config.initialize_timeout_seconds,
        request_timeout_seconds=config.request_timeout_seconds,
        shutdown_timeout_seconds=config.shutdown_timeout_seconds,
        max_protocol_message_bytes=config.max_protocol_message_bytes,
        max_pending_notifications=config.max_pending_notifications,
        max_stderr_bytes=config.max_stderr_bytes,
    )


def create_configured_lsp_backend(
    runtime: OriginForgeRuntime,
    server_id: str,
) -> PodmanLspBackend:
    """Create but do not start one operator-approved LSP backend."""

    config = load_config(runtime.project_root)
    server = config.lsp_server(server_id)
    return PodmanLspBackend(
        runtime.state_dir,
        podman_lsp_spec_from_config(server),
    )
