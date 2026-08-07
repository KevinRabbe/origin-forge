from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .apply import IsolatedPatchApplier
from .audit import WorkspaceAuditor
from .config import load_config
from .model import ModelAdapter
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .sandbox import SandboxBackend, SandboxPolicyError, SandboxUnavailable
from .sandbox_factory import create_sandbox_backend
from .sandbox_verification import SandboxedWorkspaceVerifier
from .state import FlowStatus, TaskStatus, WorkspaceStatus
from .worker import LocalPatchWorker
from .workspaces import GitWorkspaceManager


class AttemptOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class AttemptStage(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    EXECUTOR = "EXECUTOR"
    WORKSPACE = "WORKSPACE"
    APPLY = "APPLY"
    AUDIT = "AUDIT"
    SANDBOX = "SANDBOX"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class OrchestrationResult:
    task_id: str
    outcome: AttemptOutcome
    stage: AttemptStage
    reason: str | None = None
    proposal_artifact_id: str | None = None
    workspace_id: str | None = None
    task_verification_id: str | None = None


class BoundedTaskOrchestrator:
    """Run exactly one bounded Task attempt through the verified pipeline.

    This first Manager is deterministic. It coordinates existing components but
    does not plan new Tasks, retry itself, or merge a verified Workspace.
    """

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        model: ModelAdapter,
        sandbox_backend: SandboxBackend | None = None,
        *,
        workspaces: GitWorkspaceManager | None = None,
    ):
        self.runtime = runtime
        self.model = model
        self.workspaces = workspaces or GitWorkspaceManager(runtime)
        self.sandbox_backend = sandbox_backend or create_sandbox_backend(
            runtime, load_config(runtime.project_root)
        )

    def _task_flow(self, task: dict) -> dict:
        return self.runtime.get_flow(task["flow_id"])

    def _record_task_verification(
        self,
        task_id: str,
        *,
        status: str,
        stage: AttemptStage,
        evidence: dict,
    ) -> str:
        return self.runtime.record_verification(
            "TASK",
            task_id,
            verification_type="bounded-orchestration-attempt",
            verifier="OriginForge.BoundedTaskOrchestrator",
            status=status,
            evidence={"stage": stage.value, **evidence},
        )

    def _finish_task(
        self,
        task_id: str,
        *,
        target: TaskStatus,
        reason: str,
        verification_status: str,
        stage: AttemptStage,
        evidence: dict,
    ) -> str:
        verification_id = self._record_task_verification(
            task_id,
            status=verification_status,
            stage=stage,
            evidence={"reason": reason, **evidence},
        )
        task = self.runtime.get_task(task_id)
        if task["status"] == TaskStatus.RUNNING.value:
            self.runtime.transition_task(
                task_id,
                target,
                expected_revision=int(task["revision"]),
            )
        return verification_id

    def _preflight(self, task_id: str) -> dict:
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.READY.value:
            raise RuntimeInvariantError(
                f"bounded orchestration requires READY task; task {task_id} is {task['status']}"
            )
        flow = self._task_flow(task)
        if flow["status"] != FlowStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"bounded orchestration requires RUNNING flow; flow {flow['id']} is {flow['status']}"
            )
        active_workspaces = [
            workspace
            for workspace in self.workspaces.list(task_id)
            if workspace["status"] != WorkspaceStatus.ABANDONED.value
        ]
        if active_workspaces:
            workspace = active_workspaces[0]
            raise RuntimeInvariantError(
                f"task {task_id} already has active workspace {workspace['id']} ({workspace['status']}); resume or abandon it explicitly"
            )

        config = load_config(self.runtime.project_root)
        required_commands = [
            *[command for command in config.approved_build_commands if command.required],
            *[command for command in config.approved_test_commands if command.required],
        ]
        if not required_commands:
            raise RuntimeInvariantError(
                "bounded orchestration requires at least one required sandbox verification command"
            )
        if not self.sandbox_backend.available():
            raise SandboxUnavailable(
                f"sandbox backend is unavailable: {self.sandbox_backend.backend_id}"
            )
        if not self.sandbox_backend.guarantees.satisfies(
            network_allowed=config.sandbox_network
        ):
            raise SandboxPolicyError(
                f"sandbox backend {self.sandbox_backend.backend_id} does not satisfy required isolation guarantees"
            )
        return task

    def execute(
        self,
        task_id: str,
        *,
        selected_paths: Iterable[str],
        model_profile: str | None = None,
        require_changes: bool = True,
    ) -> OrchestrationResult:
        selected = tuple(selected_paths)
        if not selected:
            raise ValueError("bounded orchestration requires at least one selected context file")

        try:
            task = self._preflight(task_id)
        except (SandboxUnavailable, SandboxPolicyError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            verification_id = self._record_task_verification(
                task_id,
                status="BLOCKED",
                stage=AttemptStage.PREFLIGHT,
                evidence={"reason": reason},
            )
            task = self.runtime.get_task(task_id)
            if task["status"] == TaskStatus.READY.value:
                self.runtime.transition_task(
                    task_id,
                    TaskStatus.BLOCKED,
                    expected_revision=int(task["revision"]),
                )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.BLOCKED,
                AttemptStage.PREFLIGHT,
                reason=reason,
                task_verification_id=verification_id,
            )

        self.runtime.transition_task(
            task_id,
            TaskStatus.RUNNING,
            expected_revision=int(task["revision"]),
        )
        proposal_artifact_id: str | None = None
        workspace_id: str | None = None

        try:
            worker_result = LocalPatchWorker(self.runtime, self.model).execute(
                task_id,
                selected_paths=selected,
                model_profile=model_profile or self.model.model_id,
            )
            proposal_artifact_id = worker_result.proposal_artifact_id
            if require_changes and not worker_result.proposal.changes:
                reason = "executor returned no changes for a change-required Task"
                verification_id = self._finish_task(
                    task_id,
                    target=TaskStatus.BLOCKED,
                    reason=reason,
                    verification_status="INCONCLUSIVE",
                    stage=AttemptStage.EXECUTOR,
                    evidence={"proposal_artifact_id": proposal_artifact_id},
                )
                return OrchestrationResult(
                    task_id,
                    AttemptOutcome.BLOCKED,
                    AttemptStage.EXECUTOR,
                    reason,
                    proposal_artifact_id,
                    None,
                    verification_id,
                )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.EXECUTOR,
                evidence={},
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.EXECUTOR,
                reason,
                task_verification_id=verification_id,
            )

        try:
            workspace_id = self.workspaces.create(task_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.WORKSPACE,
                evidence={"proposal_artifact_id": proposal_artifact_id},
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.WORKSPACE,
                reason,
                proposal_artifact_id,
                task_verification_id=verification_id,
            )

        try:
            apply_result = IsolatedPatchApplier(
                self.runtime, self.workspaces
            ).apply_artifact(workspace_id, proposal_artifact_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.APPLY,
                evidence={
                    "proposal_artifact_id": proposal_artifact_id,
                    "workspace_id": workspace_id,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.APPLY,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
            )

        try:
            audit_result = WorkspaceAuditor(
                self.runtime, self.workspaces
            ).audit_artifact(workspace_id, proposal_artifact_id)
        except Exception as exc:
            current_workspace = self.workspaces.get(workspace_id)
            if current_workspace["status"] == WorkspaceStatus.APPLIED.value:
                self.workspaces.transition(
                    workspace_id,
                    WorkspaceStatus.FAILED,
                    expected_revision=int(current_workspace["revision"]),
                    event_type="WORKSPACE_AUDIT_ERROR",
                )
            reason = f"{type(exc).__name__}: {exc}"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.AUDIT,
                evidence={
                    "proposal_artifact_id": proposal_artifact_id,
                    "workspace_id": workspace_id,
                    "diff_artifact_id": apply_result.diff_artifact_id,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.AUDIT,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
            )
        if not audit_result.passed:
            reason = "; ".join(audit_result.findings) or "workspace audit failed"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.AUDIT,
                evidence={
                    "proposal_artifact_id": proposal_artifact_id,
                    "workspace_id": workspace_id,
                    "audit_verification_id": audit_result.verification_id,
                    "diff_artifact_id": apply_result.diff_artifact_id,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.AUDIT,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
            )

        try:
            sandbox_result = SandboxedWorkspaceVerifier(
                self.runtime,
                self.sandbox_backend,
                self.workspaces,
            ).verify(workspace_id)
        except (SandboxUnavailable, SandboxPolicyError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.BLOCKED,
                reason=reason,
                verification_status="BLOCKED",
                stage=AttemptStage.SANDBOX,
                evidence={
                    "proposal_artifact_id": proposal_artifact_id,
                    "workspace_id": workspace_id,
                    "audit_verification_id": audit_result.verification_id,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.BLOCKED,
                AttemptStage.SANDBOX,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.BLOCKED,
                reason=reason,
                verification_status="BLOCKED",
                stage=AttemptStage.SANDBOX,
                evidence={
                    "proposal_artifact_id": proposal_artifact_id,
                    "workspace_id": workspace_id,
                    "audit_verification_id": audit_result.verification_id,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.BLOCKED,
                AttemptStage.SANDBOX,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
            )

        if not sandbox_result.passed:
            workspace = self.workspaces.get(workspace_id)
            blocked = workspace["status"] == WorkspaceStatus.AUDITED.value
            target = TaskStatus.BLOCKED if blocked else TaskStatus.FAILED
            outcome = AttemptOutcome.BLOCKED if blocked else AttemptOutcome.FAILED
            verification_status = "BLOCKED" if blocked else "FAIL"
            reason = (
                "sandbox verification infrastructure was blocked"
                if blocked
                else "required sandbox verification command failed"
            )
            verification_id = self._finish_task(
                task_id,
                target=target,
                reason=reason,
                verification_status=verification_status,
                stage=AttemptStage.SANDBOX,
                evidence={
                    "proposal_artifact_id": proposal_artifact_id,
                    "workspace_id": workspace_id,
                    "audit_verification_id": audit_result.verification_id,
                    "sandbox_verification_ids": [
                        item.verification_id for item in sandbox_result.results
                    ],
                },
            )
            return OrchestrationResult(
                task_id,
                outcome,
                AttemptStage.SANDBOX,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
            )

        workspace = self.workspaces.get(workspace_id)
        if workspace["status"] != WorkspaceStatus.VERIFIED.value:
            reason = f"sandbox reported pass but workspace is {workspace['status']}"
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.SANDBOX,
                evidence={"workspace_id": workspace_id},
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.SANDBOX,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
            )

        verification_id = self._record_task_verification(
            task_id,
            status="PASS",
            stage=AttemptStage.COMPLETE,
            evidence={
                "proposal_artifact_id": proposal_artifact_id,
                "workspace_id": workspace_id,
                "diff_artifact_id": apply_result.diff_artifact_id,
                "audit_verification_id": audit_result.verification_id,
                "sandbox_verification_ids": [
                    item.verification_id for item in sandbox_result.results
                ],
            },
        )
        task = self.runtime.get_task(task_id)
        self.runtime.transition_task(
            task_id,
            TaskStatus.SUCCEEDED,
            expected_revision=int(task["revision"]),
        )
        return OrchestrationResult(
            task_id,
            AttemptOutcome.SUCCEEDED,
            AttemptStage.COMPLETE,
            proposal_artifact_id=proposal_artifact_id,
            workspace_id=workspace_id,
            task_verification_id=verification_id,
        )
