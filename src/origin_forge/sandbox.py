from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable


class SandboxUnavailable(RuntimeError):
    pass


class SandboxPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxGuarantees:
    filesystem_isolated: bool
    process_isolated: bool
    host_secrets_isolated: bool
    network_controlled: bool

    def satisfies(self, *, network_allowed: bool) -> bool:
        if not (self.filesystem_isolated and self.process_isolated and self.host_secrets_isolated):
            return False
        if not network_allowed and not self.network_controlled:
            return False
        return True


@dataclass(frozen=True)
class SandboxJob:
    workspace_path: Path
    argv: tuple[str, ...]
    timeout_seconds: float
    max_output_bytes: int
    network_allowed: bool = False
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.argv or any(not isinstance(arg, str) or not arg for arg in self.argv):
            raise ValueError("sandbox argv must be a non-empty tuple of strings")
        if self.timeout_seconds <= 0:
            raise ValueError("sandbox timeout must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("sandbox max_output_bytes must be positive")


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False


@runtime_checkable
class SandboxBackend(Protocol):
    @property
    def backend_id(self) -> str: ...

    @property
    def guarantees(self) -> SandboxGuarantees: ...

    def available(self) -> bool: ...

    def run(self, job: SandboxJob) -> SandboxResult: ...


class UnconfiguredSandboxBackend:
    """Safe default: verification cannot execute until a real sandbox is configured."""

    backend_id = "unconfigured"
    guarantees = SandboxGuarantees(False, False, False, False)

    def available(self) -> bool:
        return False

    def run(self, job: SandboxJob) -> SandboxResult:
        raise SandboxUnavailable("no sandbox execution backend is configured")
