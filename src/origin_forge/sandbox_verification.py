from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .config import CommandSpec, load_config
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .sandbox import (
    SandboxBackend,
    SandboxJob,
    SandboxPolicyError,
    SandboxResult,
    SandboxUnavailable,
)
from .state import WorkspaceStatus
from .workspaces import GitWorkspaceManager


@dataclass(frozen=True)
class CommandVerificationResult:
    category: str
    command_name: str
    verification_id: str
    passed: bool
    sandbox_result: SandboxResult | None


@dataclass(frozen=True)
class WorkspaceVerificationResult:
    workspace_id: str
    passed: bool
    results: tuple[CommandVerificationResult, ...]


class SandboxedWorkspaceVerifier:
    """Runs project-approved commands only through a sandbox backend."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        backend: SandboxBackend,
        workspaces: GitWorkspaceManager | None = None,
    ):
        self.runtime = runtime
        self.backend = backend
        self.workspaces = workspaces or GitWorkspaceManager(runtime)

    def _check_backend(self, *, network_allowed: bool) -> None:
        if not self.backend.available():
            raise SandboxUnavailable(f"sandbox backend is unavailable: {self.backend.backend_id}")
        if not self.backend.guarantees.satisfies(network_allowed=network_allowed):
            raise SandboxPolicyError(
                f"sandbox backend {self.backend.backend_id} does not satisfy required isolation guarantees"
            )

    def _run_command(
        self,
        workspace_id: str,
        category: Literal["build", "test"],
        command: CommandSpec,
        *,
        network_allowed: bool,
    ) -> CommandVerificationResult:
        workspace_path = self.workspaces.path(workspace_id)
        job = SandboxJob(
            workspace_path=workspace_path,
            argv=command.argv,
            timeout_seconds=command.timeout_seconds,
            max_output_bytes=command.max_output_bytes,
            network_allowed=network_allowed,
            environment={"ORIGIN_FORGE_SANDBOX": "1"},
        )
        try:
            result = self.backend.run(job)
        except Exception as exc:
            verification_id = self.workspaces.record_verification(
                workspace_id,
                verification_type=f"sandbox-{category}:{command.name}",
                verifier=f"OriginForge.Sandbox:{self.backend.backend_id}",
                status="BLOCKED",
                evidence={"error": f"{type(exc).__name__}: {exc}"},
            )
            return CommandVerificationResult(
                category, command.name, verification_id, False, None
            )

        passed = (
            not result.timed_out
            and result.exit_code == 0
            and not result.stdout_truncated
            and not result.stderr_truncated
        )
        verification_id = self.workspaces.record_verification(
            workspace_id,
            verification_type=f"sandbox-{category}:{command.name}",
            verifier=f"OriginForge.Sandbox:{self.backend.backend_id}",
            status="PASS" if passed else "FAIL",
            evidence={
                "backend_id": self.backend.backend_id,
                "argv": list(command.argv),
                "result": asdict(result),
            },
        )
        return CommandVerificationResult(
            category, command.name, verification_id, passed, result
        )

    def verify(self, workspace_id: str) -> WorkspaceVerificationResult:
        workspace = self.workspaces.get(workspace_id)
        if workspace["status"] != WorkspaceStatus.AUDITED.value:
            raise RuntimeInvariantError(
                f"sandbox verification requires AUDITED workspace; got {workspace['status']}"
            )

        config = load_config(self.runtime.project_root)
        self._check_backend(network_allowed=config.sandbox_network)
        scheduled: list[tuple[Literal["build", "test"], CommandSpec]] = [
            *(("build", command) for command in config.approved_build_commands if command.required),
            *(("test", command) for command in config.approved_test_commands if command.required),
        ]
        if not scheduled:
            raise RuntimeInvariantError(
                "workspace cannot become VERIFIED without at least one required sandbox command"
            )

        results: list[CommandVerificationResult] = []
        for category, command in scheduled:
            result = self._run_command(
                workspace_id,
                category,
                command,
                network_allowed=config.sandbox_network,
            )
            results.append(result)
            if not result.passed:
                current = self.workspaces.get(workspace_id)
                with self.runtime.store.session() as conn:
                    row = conn.execute(
                        "SELECT status FROM verifications WHERE id = ?",
                        (result.verification_id,),
                    ).fetchone()
                if row["status"] == "FAIL" and current["status"] == WorkspaceStatus.AUDITED.value:
                    self.workspaces.transition(
                        workspace_id,
                        WorkspaceStatus.FAILED,
                        expected_revision=int(current["revision"]),
                        event_type="WORKSPACE_SANDBOX_VERIFICATION_FAILED",
                    )
                return WorkspaceVerificationResult(workspace_id, False, tuple(results))

        current = self.workspaces.get(workspace_id)
        self.workspaces.transition(
            workspace_id,
            WorkspaceStatus.VERIFIED,
            expected_revision=int(current["revision"]),
            event_type="WORKSPACE_SANDBOX_VERIFICATION_PASSED",
            metadata={"backend_id": self.backend.backend_id},
        )
        return WorkspaceVerificationResult(workspace_id, True, tuple(results))
