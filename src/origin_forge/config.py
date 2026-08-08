from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .resource_model_config import ResourceModelConfig, parse_resource_model_config

CONFIG_VERSION = 5
DEFAULT_CONFIG = '''# Origin Forge project configuration
version = 5
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "unconfigured"
image = ""
network = false
memory = "2g"
cpus = 2.0
pids_limit = 256

[commands]
build = []
test = []

[code_intelligence]
lsp_servers = []

[resources]
enabled = false
gpus = []

[models]
profiles = []
policies = []
'''

_SERVER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 120.0
    max_output_bytes: int = 1024 * 1024
    required: bool = True


@dataclass(frozen=True)
class LspServerConfig:
    server_id: str
    backend: str
    image: str
    argv: tuple[str, ...]
    podman_executable: str = "podman"
    network: bool = False
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 256
    probe_timeout_seconds: float = 10.0
    initialize_timeout_seconds: float = 15.0
    request_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    max_protocol_message_bytes: int = 4 * 1024 * 1024
    max_pending_notifications: int = 256
    max_stderr_bytes: int = 256 * 1024


@dataclass(frozen=True)
class ProjectConfig:
    version: int
    policy_profile: str
    max_strategy_retries: int
    max_verification_failures: int
    sandbox_network: bool
    sandbox_backend: str
    sandbox_image: str | None
    sandbox_memory: str
    sandbox_cpus: float
    sandbox_pids_limit: int
    approved_build_commands: tuple[CommandSpec, ...]
    approved_test_commands: tuple[CommandSpec, ...]
    lsp_servers: tuple[LspServerConfig, ...] = ()
    resource_models: ResourceModelConfig = field(default_factory=ResourceModelConfig.disabled)

    def command(self, category: Literal["build", "test"], name: str) -> CommandSpec:
        commands = (
            self.approved_build_commands if category == "build" else self.approved_test_commands
        )
        for command in commands:
            if command.name == name:
                return command
        raise KeyError(f"unknown approved {category} command: {name}")

    def lsp_server(self, server_id: str) -> LspServerConfig:
        for server in self.lsp_servers:
            if server.server_id == server_id:
                return server
        raise KeyError(f"unknown configured LSP server: {server_id}")


def config_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".origin-forge" / "config.toml"


def ensure_config(project_root: str | Path) -> Path:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path


def _legacy_commands(raw: object, field: str) -> tuple[CommandSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"commands.{field} must be an array of strings")
    if raw:
        raise ValueError(
            f"config v1 commands.{field} contains shell strings; migrate them to v2 structured argv commands"
        )
    return ()


def _structured_commands(raw: object, field: str) -> tuple[CommandSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError(f"commands.{field} must be an array of command tables")
    result: list[CommandSpec] = []
    names: set[str] = set()
    for index, item in enumerate(raw):
        allowed = {"name", "argv", "timeout_seconds", "max_output_bytes", "required"}
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"commands.{field}[{index}] has unknown fields: {sorted(unknown)}")
        name = item.get("name")
        argv = item.get("argv")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"commands.{field}[{index}].name must be non-empty")
        if name in names:
            raise ValueError(f"duplicate commands.{field} name: {name}")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(arg, str) and arg for arg in argv)
        ):
            raise ValueError(f"commands.{field}[{index}].argv must be a non-empty array of strings")
        timeout = float(item.get("timeout_seconds", 120.0))
        output = int(item.get("max_output_bytes", 1024 * 1024))
        required = item.get("required", True)
        if timeout <= 0:
            raise ValueError(f"commands.{field}[{index}].timeout_seconds must be positive")
        if output <= 0:
            raise ValueError(f"commands.{field}[{index}].max_output_bytes must be positive")
        if not isinstance(required, bool):
            raise ValueError(f"commands.{field}[{index}].required must be boolean")
        names.add(name)
        result.append(CommandSpec(name.strip(), tuple(argv), timeout, output, required))
    return tuple(result)


def _positive_float(item: dict, field: str, default: float, label: str) -> float:
    raw = item.get(field, default)
    if isinstance(raw, bool):
        raise ValueError(f"{label}.{field} must be a positive number")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}.{field} must be a positive number") from exc
    if value <= 0:
        raise ValueError(f"{label}.{field} must be positive")
    return value


def _positive_int(item: dict, field: str, default: int, label: str) -> int:
    raw = item.get(field, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{label}.{field} must be a positive integer")
    if raw <= 0:
        raise ValueError(f"{label}.{field} must be positive")
    return raw


def _lsp_servers(raw: object) -> tuple[LspServerConfig, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError("code_intelligence.lsp_servers must be an array of server tables")

    allowed = {
        "server_id", "backend", "image", "argv", "podman_executable", "network",
        "memory", "cpus", "pids_limit", "probe_timeout_seconds",
        "initialize_timeout_seconds", "request_timeout_seconds", "shutdown_timeout_seconds",
        "max_protocol_message_bytes", "max_pending_notifications", "max_stderr_bytes",
    }
    result: list[LspServerConfig] = []
    ids: set[str] = set()
    for index, item in enumerate(raw):
        label = f"code_intelligence.lsp_servers[{index}]"
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")
        server_id = item.get("server_id")
        if not isinstance(server_id, str) or not _SERVER_ID_RE.fullmatch(server_id):
            raise ValueError(f"{label}.server_id is invalid")
        if server_id in ids:
            raise ValueError(f"duplicate LSP server_id: {server_id}")
        backend = item.get("backend", "podman")
        if backend != "podman":
            raise ValueError(f"{label}.backend must be 'podman'")
        image = item.get("image")
        if not isinstance(image, str) or not image.strip():
            raise ValueError(f"{label}.image must be a non-empty string")
        argv = item.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg for arg in argv):
            raise ValueError(f"{label}.argv must be a non-empty array of strings")
        podman_executable = item.get("podman_executable", "podman")
        if not isinstance(podman_executable, str) or not podman_executable.strip():
            raise ValueError(f"{label}.podman_executable must be a non-empty string")
        network = item.get("network", False)
        if not isinstance(network, bool):
            raise ValueError(f"{label}.network must be boolean")
        memory = item.get("memory", "2g")
        if not isinstance(memory, str) or not memory.strip():
            raise ValueError(f"{label}.memory must be a non-empty string")
        ids.add(server_id)
        result.append(
            LspServerConfig(
                server_id=server_id,
                backend=backend,
                image=image.strip(),
                argv=tuple(argv),
                podman_executable=podman_executable.strip(),
                network=network,
                memory=memory.strip(),
                cpus=_positive_float(item, "cpus", 2.0, label),
                pids_limit=_positive_int(item, "pids_limit", 256, label),
                probe_timeout_seconds=_positive_float(item, "probe_timeout_seconds", 10.0, label),
                initialize_timeout_seconds=_positive_float(item, "initialize_timeout_seconds", 15.0, label),
                request_timeout_seconds=_positive_float(item, "request_timeout_seconds", 5.0, label),
                shutdown_timeout_seconds=_positive_float(item, "shutdown_timeout_seconds", 5.0, label),
                max_protocol_message_bytes=_positive_int(item, "max_protocol_message_bytes", 4 * 1024 * 1024, label),
                max_pending_notifications=_positive_int(item, "max_pending_notifications", 256, label),
                max_stderr_bytes=_positive_int(item, "max_stderr_bytes", 256 * 1024, label),
            )
        )
    return tuple(result)


def load_config(project_root: str | Path) -> ProjectConfig:
    path = ensure_config(project_root)
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    version = int(raw.get("version", 0))
    if version not in {1, 2, 3, 4, CONFIG_VERSION}:
        raise ValueError(
            f"unsupported config version {version}; expected 1, 2, 3, 4, or {CONFIG_VERSION}"
        )

    limits = raw.get("limits", {})
    if not isinstance(limits, dict):
        raise ValueError("limits must be a TOML table")
    strategy = int(limits.get("max_strategy_retries", 2))
    verification = int(limits.get("max_verification_failures", 3))
    if strategy < 0 or verification < 0:
        raise ValueError("retry limits must be non-negative")

    commands = raw.get("commands", {})
    if not isinstance(commands, dict):
        raise ValueError("commands must be a TOML table")

    sandbox = raw.get("sandbox", {})
    if sandbox is None:
        sandbox = {}
    if not isinstance(sandbox, dict):
        raise ValueError("sandbox must be a TOML table")
    network = sandbox.get("network", False)
    if not isinstance(network, bool):
        raise ValueError("sandbox.network must be boolean")
    backend = str(sandbox.get("backend", "unconfigured"))
    image_raw = sandbox.get("image", "")
    if not isinstance(image_raw, str):
        raise ValueError("sandbox.image must be a string")
    image = image_raw.strip() or None
    memory = str(sandbox.get("memory", "2g"))
    cpus = float(sandbox.get("cpus", 2.0))
    pids_limit = int(sandbox.get("pids_limit", 256))
    if cpus <= 0 or pids_limit <= 0:
        raise ValueError("sandbox resource limits must be positive")

    code_intelligence = raw.get("code_intelligence", {})
    if code_intelligence is None:
        code_intelligence = {}
    if not isinstance(code_intelligence, dict):
        raise ValueError("code_intelligence must be a TOML table")
    if version < 4 and code_intelligence.get("lsp_servers"):
        raise ValueError("configured LSP servers require config version 4")

    resources_raw = raw.get("resources")
    models_raw = raw.get("models")
    if version < 5 and (
        resources_raw not in (None, {}) or models_raw not in (None, {})
    ):
        raise ValueError("resource/model scheduling requires config version 5")
    resource_models = (
        parse_resource_model_config(resources_raw, models_raw)
        if version >= 5
        else ResourceModelConfig.disabled()
    )

    parser = _legacy_commands if version == 1 else _structured_commands
    return ProjectConfig(
        version=version,
        policy_profile=str(raw.get("policy_profile", "local-default")),
        max_strategy_retries=strategy,
        max_verification_failures=verification,
        sandbox_network=network,
        sandbox_backend=backend,
        sandbox_image=image,
        sandbox_memory=memory,
        sandbox_cpus=cpus,
        sandbox_pids_limit=pids_limit,
        approved_build_commands=parser(commands.get("build"), "build"),
        approved_test_commands=parser(commands.get("test"), "test"),
        lsp_servers=_lsp_servers(code_intelligence.get("lsp_servers")),
        resource_models=resource_models,
    )
