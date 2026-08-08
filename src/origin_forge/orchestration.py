from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .apply import IsolatedPatchApplier
from .audit import WorkspaceAuditor
from .config import load_config
from .context import ContextBuilder
from .context_selection import WorkspaceContextSelector
from .model import ModelAdapter
from .repository import RepositoryReader
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
    WORKSPACE = "WORKSPACE"
    CONTEXT = "CONTEXT"
    EXECUTOR = "EXECUTOR"
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
    context_paths: tuple[str, ...] = ()


class BoundedTaskOrchestrator:
    """Run exactly one Task attempt over one immutable Git snapshot.

    The Workspace is created before the Executor sees repository content. The
    model therefore reads and proposes against the exact snapshot that the
    deterministic applier later mutates. Manual, lexical, structural, and
    semantic context selection all execute inside that same Workspace snapshot.
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
        flow = self.runtime.get_flow(task["flow_id"])
        if flow["status"] != FlowStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"bounded orchestration requires RUNNING flow; flow {flow['id']} is {flow['status']}"
            )

        active = [
            workspace
            for workspace in self.workspaces.list(task_id)
            if workspace["status"] != WorkspaceStatus.ABANDONED.value
        ]
        if active:
            workspace = active[0]
            raise RuntimeInvariantError(
                f"task {task_id} already has active workspace {workspace['id']} ({workspace['status']}); resume or abandon it explicitly"
            )

        config = load_config(self.runtime.project_root)
        required = [
            *[command for command in config.approved_build_commands if command.required],
            *[command for command in config.approved_test_commands if command.required],
        ]
        if not required:
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

    def _abandon_if_unused(self, workspace_id: str | None) -> None:
        if workspace_id is None:
            return
        try:
            workspace = self.workspaces.get(workspace_id)
            if workspace["status"] == WorkspaceStatus.CREATED.value:
                self.workspaces.abandon(workspace_id)
        except Exception:
            pass

    def _fail_workspace_if_open(self, workspace_id: str | None, event_type: str) -> None:
        if workspace_id is None:
            return
        try:
            workspace = self.workspaces.get(workspace_id)
            if workspace["status"] in {
                WorkspaceStatus.CREATED.value,
                WorkspaceStatus.APPLIED.value,
            }:
                self.workspaces.transition(
                    workspace_id,
                    WorkspaceStatus.FAILED,
                    expected_revision=int(workspace["revision"]),
                    event_type=event_type,
                )
        except Exception:
            pass

    def execute(
        self,
        task_id: str,
        *,
        selected_paths: Iterable[str] | None = None,
        auto_context: bool = False,
        context_seed_paths: Iterable[str] = (),
        structural_context: bool = False,
        semantic_context: bool = False,
        model_profile: str | None = None,
        require_changes: bool = True,
    ) -> OrchestrationResult:
        selected = tuple(selected_paths or ())
        seeds = tuple(context_seed_paths)
        if auto_context and selected:
            raise ValueError("auto_context cannot be combined with selected_paths")
        if not auto_context and not selected:
            raise ValueError(
                "bounded orchestration requires selected context files or auto_context=True"
            )
        if seeds and not auto_context:
            raise ValueError("context_seed_paths require auto_context=True")

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

        workspace_id: str | None = None
        proposal_artifact_id: str | None = None
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
                evidence={},
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.WORKSPACE,
                reason=reason,
                task_verification_id=verification_id,
            )

        workspace_path = self.workspaces.path(workspace_id)
        repository = RepositoryReader(workspace_path)
        try:
            selection = WorkspaceContextSelector(
                self.runtime,
                repository,
            ).select(
                task_id,
                selected_paths=selected,
                auto_context=auto_context,
                seed_paths=seeds,
                structural_context=structural_context,
                semantic_context=semantic_context,
            )
            context_paths = selection.paths
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._abandon_if_unused(workspace_id)
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.BLOCKED,
                reason=reason,
                verification_status="BLOCKED",
                stage=AttemptStage.CONTEXT,
                evidence={"workspace_id": workspace_id},
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.BLOCKED,
                AttemptStage.CONTEXT,
                reason=reason,
                workspace_id=workspace_id,
                task_verification_id=verification_id,
            )

        if not context_paths:
            reason = "context selection found no relevant tracked files"
            self._abandon_if_unused(workspace_id)
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.BLOCKED,
                reason=reason,
                verification_status="INCONCLUSIVE",
                stage=AttemptStage.CONTEXT,
                evidence={
                    "workspace_id": workspace_id,
                    "context_mode": selection.mode,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.BLOCKED,
                AttemptStage.CONTEXT,
                reason=reason,
                workspace_id=workspace_id,
                task_verification_id=verification_id,
            )

        try:
            context_builder = ContextBuilder(
                self.runtime,
                repository,
            )
            worker_result = LocalPatchWorker(
                self.runtime,
                self.model,
                repository=repository,
                context_builder=context_builder,
            ).execute(
                task_id,
                selected_paths=context_paths,
                model_profile=model_profile or self.model.model_id,
            )
            proposal_artifact_id = worker_result.proposal_artifact_id
            if require_changes and not worker_result.proposal.changes:
                reason = "executor returned no changes for a change-required Task"
                self._abandon_if_unused(workspace_id)
                verification_id = self._finish_task(
                    task_id,
                    target=TaskStatus.BLOCKED,
                    reason=reason,
                    verification_status="INCONCLUSIVE",
                    stage=AttemptStage.EXECUTOR,
                    evidence={
                        "proposal_artifact_id": proposal_artifact_id,
                        "workspace_id": workspace_id,
                        "context_paths": list(context_paths),
                        "context_mode": selection.mode,
                    },
                )
                return OrchestrationResult(
                    task_id,
                    AttemptOutcome.BLOCKED,
                    AttemptStage.EXECUTOR,
                    reason,
                    proposal_artifact_id,
                    workspace_id,
                    verification_id,
                    context_paths,
                )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._abandon_if_unused(workspace_id)
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.EXECUTOR,
                evidence={
                    "workspace_id": workspace_id,
                    "context_paths": list(context_paths),
                    "context_mode": selection.mode,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.EXECUTOR,
                reason,
                workspace_id=workspace_id,
                task_verification_id=verification_id,
                context_paths=context_paths,
            )

        try:
            apply_result = IsolatedPatchApplier(
                self.runtime, self.workspaces
            ).apply_artifact(workspace_id, proposal_artifact_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._fail_workspace_if_open(workspace_id, "WORKSPACE_APPLY_ERROR")
            verification_id = self._finish_task(
                task_id,
                target=TaskStatus.FAILED,
                reason=reason,
                verification_status="FAIL",
                stage=AttemptStage.APPLY,
                evidence={
                    "proposal_artifact_id": proposal_artifact_id,
                    "workspace_id": workspace_id,
                    "context_paths": list(context_paths),
                    "context_mode": selection.mode,
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
                context_paths,
            )

        try:
            audit_result = WorkspaceAuditor(
                self.runtime, self.workspaces
            ).audit_artifact(workspace_id, proposal_artifact_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._fail_workspace_if_open(workspace_id, "WORKSPACE_AUDIT_ERROR")
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
                    "context_paths": list(context_paths),
                    "context_mode": selection.mode,
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
                context_paths,
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
                    "context_paths": list(context_paths),
                    "context_mode": selection.mode,
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
                context_paths,
            )

        try:
            sandbox_result = SandboxedWorkspaceVerifier(
                self.runtime,
                self.sandbox_backend,
                self.workspaces,
            ).verify(workspace_id)
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
                    "context_paths": list(context_paths),
                    "context_mode": selection.mode,
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
                context_paths,
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
                    "context_paths": list(context_paths),
                    "context_mode": selection.mode,
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
                context_paths,
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
                evidence={
                    "workspace_id": workspace_id,
                    "context_paths": list(context_paths),
                    "context_mode": selection.mode,
                },
            )
            return OrchestrationResult(
                task_id,
                AttemptOutcome.FAILED,
                AttemptStage.SANDBOX,
                reason,
                proposal_artifact_id,
                workspace_id,
                verification_id,
                context_paths,
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
                "context_paths": list(context_paths),
                "context_mode": selection.mode,
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
            context_paths=context_paths,
        )
