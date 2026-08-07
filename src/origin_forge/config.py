from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CONFIG_VERSION = 2
DEFAULT_CONFIG = """# Origin Forge project configuration
version = 2
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
network = false

[commands]
build = []
test = []
"""


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 120.0
    max_output_bytes: int = 1024 * 1024
    required: bool = True


@dataclass(frozen=True)
class ProjectConfig:
    version: int
    policy_profile: str
    max_strategy_retries: int
    max_verification_failures: int
    sandbox_network: bool
    approved_build_commands: tuple[CommandSpec, ...]
    approved_test_commands: tuple[CommandSpec, ...]

    def command(self, category: Literal["build", "test"], name: str) -> CommandSpec:
        commands = (
            self.approved_build_commands if category == "build" else self.approved_test_commands
        )
        for command in commands:
            if command.name == name:
                return command
        raise KeyError(f"unknown approved {category} command: {name}")


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


def load_config(project_root: str | Path) -> ProjectConfig:
    path = ensure_config(project_root)
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    version = int(raw.get("version", 0))
    if version not in {1, CONFIG_VERSION}:
        raise ValueError(
            f"unsupported config version {version}; expected 1 or {CONFIG_VERSION}"
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

    parser = _legacy_commands if version == 1 else _structured_commands
    return ProjectConfig(
        version=version,
        policy_profile=str(raw.get("policy_profile", "local-default")),
        max_strategy_retries=strategy,
        max_verification_failures=verification,
        sandbox_network=network,
        approved_build_commands=parser(commands.get("build"), "build"),
        approved_test_commands=parser(commands.get("test"), "test"),
    )
