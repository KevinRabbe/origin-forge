from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_VERSION = 1
DEFAULT_CONFIG = """# Origin Forge project configuration
version = 1
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[commands]
build = []
test = []
"""


@dataclass(frozen=True)
class ProjectConfig:
    version: int
    policy_profile: str
    max_strategy_retries: int
    max_verification_failures: int
    approved_build_commands: tuple[str, ...]
    approved_test_commands: tuple[str, ...]


def config_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".origin-forge" / "config.toml"


def ensure_config(project_root: str | Path) -> Path:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path


def _commands(raw: object, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"commands.{field} must be an array of strings")
    return tuple(raw)


def load_config(project_root: str | Path) -> ProjectConfig:
    path = ensure_config(project_root)
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    version = int(raw.get("version", 0))
    if version != CONFIG_VERSION:
        raise ValueError(
            f"unsupported config version {version}; expected {CONFIG_VERSION}"
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

    return ProjectConfig(
        version=version,
        policy_profile=str(raw.get("policy_profile", "local-default")),
        max_strategy_retries=strategy,
        max_verification_failures=verification,
        approved_build_commands=_commands(commands.get("build"), "build"),
        approved_test_commands=_commands(commands.get("test"), "test"),
    )
