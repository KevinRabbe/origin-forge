from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Sequence

from .audit import WorkspaceAuditor
from .config import load_config
from .model import ModelAdapter
from .orchestration import (
    AttemptOutcome,
    AttemptStage,
    BoundedTaskOrchestrator,
    OrchestrationResult,
)
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .sandbox import SandboxBackend
from .sandbox_factory import create_sandbox_backend
from .sandbox_verification import SandboxedWorkspaceVerifier
from .state import TaskStatus, WorkspaceStatus
from .workspaces import GitWorkspaceManager


class PolicyOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class PolicyAction(StrEnum):
    ATTEMPT = "ATTEMPT"
    RETRY = "RETRY"
    RESUME_AUDIT = "RESUME_AUDIT"
    RESUME_SANDBOX = "RESUME_SANDBOX"
    FINALIZE_VERIFIED = "FINALIZE_VERIFIED"
    STOP = "STOP"


@dataclass(frozen=True)
class PolicyResult:
    task_id: str
    outcome: PolicyOutcome
    action: PolicyAction
    reason: str | None
    executor_attempts: int
    attempts_started: int
    workspace_id: str | None = None
    last_attempt: OrchestrationResult | None = None


class BoundedRetryPolicy:
    """Bounded resume/retry/escalation policy above one-shot orchestration."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        models: Sequence[ModelAdapter],
        sandbox_backend: SandboxBackend | None = None,
        *,
        workspaces: GitWorkspaceManager | None = None,
    ):
        if not models:
            raise ValueError("bounded retry policy requires at least one model")
        self.runtime = runtime
        self.models = tuple(models)
        self.workspaces = workspaces or GitWorkspaceManager(runtime)
        self.sandbox_backend = sandbox_backend or create_sandbox_backend(
            runtime, load_config(runtime.project_root)
        )

    def _executor_runs(self, task_id: str) -> list[dict]:
        return [
            run
            for run in self.runtime.list_runs(task_id)
            if run["role"] == "EXECUTOR"
        ]

    def _proposal_hashes(self, task_id: str) -> list[str]:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT a.content_hash
                   FROM artifacts a
                   JOIN runs r ON r.id = a.created_by_run_id
                   WHERE r.task_id = ? AND a.type = 'PATCH_PROPOSAL'
                     AND a.content_hash IS NOT NULL
                   ORDER BY a.created_at, a.rowid""",
                (task_id,),
            ).fetchall()
        return [row["content_hash"] for row in rows]

    def _sandbox_failure_count(self, task_id: str) -> int:
        with self.runtime.store.session() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS count
                   FROM verifications v
                   JOIN workspaces w
                     ON v.target_type = 'WORKSPACE' AND v.target_id = w.id
                   WHERE w.task_id = ?
                     AND v.status = 'FAIL'
                     AND v.verification_type LIKE 'sandbox-%'""",
                (task_id,),
            ).fetchone()
        return int(row["count"])

    def _active_workspace(self, task_id: str) -> dict | None:
        active = [
            workspace
            for workspace in self.workspaces.list(task_id)
            if workspace["status"] != WorkspaceStatus.ABANDONED.value
        ]
        if len(active) > 1:
            raise RuntimeInvariantError(
                f"task {task_id} has multiple active workspaces"
            )
        return active[0] if active else None

    def _proposal_for_workspace(self, workspace_id: str) -> str | None:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT metadata_json FROM state_events
                   WHERE aggregate_type = 'WORKSPACE'
                     AND aggregate_id = ?
                     AND event_type = 'WORKSPACE_PATCH_APPLIED'
                   ORDER BY created_at DESC, rowid DESC""",
                (workspace_id,),
            ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            proposal_id = metadata.get("proposal_artifact_id")
            if isinstance(proposal_id, str) and proposal_id:
                return proposal_id
        return None

    def _record_policy_verification(
        self,
        task_id: str,
        *,
        status: str,
        reason: str,
        action: PolicyAction,
        evidence: dict | None = None,
    ) -> str:
        return self.runtime.record_verification(
            "TASK",
            task_id,
            verification_type="bounded-retry-policy",
            verifier="OriginForge.BoundedRetryPolicy",
            status=status,
            evidence={
                "reason": reason,
                "action": action.value,
                **(evidence or {}),
            },
        )

    def _transition_to_running(self, task_id: str) -> None:
        task = self.runtime.get_task(task_id)
        if task["status"] == TaskStatus.RUNNING.value:
            return
        if task["status"] not in {
            TaskStatus.READY.value,
            TaskStatus.BLOCKED.value,
            TaskStatus.FAILED.value,
        }:
            raise RuntimeInvariantError(
                f"cannot resume task {task_id} from {task['status']}"
            )
        self.runtime.transition_task(
            task_id,
            TaskStatus.RUNNING,
            expected_revision=int(task["revision"]),
        )

    def _finish_resumed_task(
        self,
        task_id: str,
        *,
        workspace_id: str,
        sandbox_verification_ids: list[str],
    ) -> str:
        verification_id = self._record_policy_verification(
            task_id,
            status="PASS",
            reason="resumed verified workspace completed required verification",
            action=PolicyAction.FINALIZE_VERIFIED,
            evidence={
                "workspace_id": workspace_id,
                "sandbox_verification_ids": sandbox_verification_ids,
            },
        )
        task = self.runtime.get_task(task_id)
        self.runtime.transition_task(
            task_id,
            TaskStatus.SUCCEEDED,
            expected_revision=int(task["revision"]),
        )
        return verification_id

    def _block_resumed_task(
        self,
        task_id: str,
        *,
        reason: str,
        workspace_id: str,
        action: PolicyAction,
    ) -> None:
        self._record_policy_verification(
            task_id,
            status="BLOCKED",
            reason=reason,
            action=action,
            evidence={"workspace_id": workspace_id},
        )
        task = self.runtime.get_task(task_id)
        if task["status"] == TaskStatus.RUNNING.value:
            self.runtime.transition_task(
                task_id,
                TaskStatus.BLOCKED,
                expected_revision=int(task["revision"]),
            )

    def _resume_sandbox(self, task_id: str, workspace: dict) -> PolicyResult:
        workspace_id = workspace["id"]
        self._transition_to_running(task_id)
        try:
            result = SandboxedWorkspaceVerifier(
                self.runtime,
                self.sandbox_backend,
                self.workspaces,
            ).verify(workspace_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._block_resumed_task(
                task_id,
                reason=reason,
                workspace_id=workspace_id,
                action=PolicyAction.RESUME_SANDBOX,
            )
            return PolicyResult(
                task_id,
                PolicyOutcome.BLOCKED,
                PolicyAction.RESUME_SANDBOX,
                reason,
                len(self._executor_runs(task_id)),
                0,
                workspace_id,
            )

        if result.passed:
            self._finish_resumed_task(
                task_id,
                workspace_id=workspace_id,
                sandbox_verification_ids=[item.verification_id for item in result.results],
            )
            return PolicyResult(
                task_id,
                PolicyOutcome.SUCCEEDED,
                PolicyAction.RESUME_SANDBOX,
                None,
                len(self._executor_runs(task_id)),
                0,
                workspace_id,
            )

        current = self.workspaces.get(workspace_id)
        if current["status"] == WorkspaceStatus.AUDITED.value:
            reason = "sandbox verification infrastructure remains blocked"
            self._block_resumed_task(
                task_id,
                reason=reason,
                workspace_id=workspace_id,
                action=PolicyAction.RESUME_SANDBOX,
            )
            return PolicyResult(
                task_id,
                PolicyOutcome.BLOCKED,
                PolicyAction.RESUME_SANDBOX,
                reason,
                len(self._executor_runs(task_id)),
                0,
                workspace_id,
            )

        task = self.runtime.get_task(task_id)
        if task["status"] == TaskStatus.RUNNING.value:
            self.runtime.transition_task(
                task_id,
                TaskStatus.FAILED,
                expected_revision=int(task["revision"]),
            )
        return PolicyResult(
            task_id,
            PolicyOutcome.FAILED,
            PolicyAction.RESUME_SANDBOX,
            "required sandbox verification command failed during resume",
            len(self._executor_runs(task_id)),
            0,
            workspace_id,
        )

    def _resume_applied(self, task_id: str, workspace: dict) -> PolicyResult:
        workspace_id = workspace["id"]
        proposal_id = self._proposal_for_workspace(workspace_id)
        if proposal_id is None:
            reason = "applied workspace has no durable proposal linkage"
            return self._quarantine(task_id, reason, workspace_id=workspace_id)

        self._transition_to_running(task_id)
        try:
            audit = WorkspaceAuditor(
                self.runtime, self.workspaces
            ).audit_artifact(workspace_id, proposal_id)
        except Exception as exc:
            current = self.workspaces.get(workspace_id)
            if current["status"] == WorkspaceStatus.APPLIED.value:
                self.workspaces.transition(
                    workspace_id,
                    WorkspaceStatus.FAILED,
                    expected_revision=int(current["revision"]),
                    event_type="WORKSPACE_RESUME_AUDIT_ERROR",
                )
            task = self.runtime.get_task(task_id)
            if task["status"] == TaskStatus.RUNNING.value:
                self.runtime.transition_task(
                    task_id,
                    TaskStatus.FAILED,
                    expected_revision=int(task["revision"]),
                )
            return PolicyResult(
                task_id,
                PolicyOutcome.FAILED,
                PolicyAction.RESUME_AUDIT,
                f"{type(exc).__name__}: {exc}",
                len(self._executor_runs(task_id)),
                0,
                workspace_id,
            )

        if not audit.passed:
            task = self.runtime.get_task(task_id)
            if task["status"] == TaskStatus.RUNNING.value:
                self.runtime.transition_task(
                    task_id,
                    TaskStatus.FAILED,
                    expected_revision=int(task["revision"]),
                )
            return PolicyResult(
                task_id,
                PolicyOutcome.FAILED,
                PolicyAction.RESUME_AUDIT,
                "; ".join(audit.findings) or "resumed audit failed",
                len(self._executor_runs(task_id)),
                0,
                workspace_id,
            )
        return self._resume_sandbox(task_id, self.workspaces.get(workspace_id))

    def _finalize_verified(self, task_id: str, workspace: dict) -> PolicyResult:
        self._transition_to_running(task_id)
        self._finish_resumed_task(
            task_id,
            workspace_id=workspace["id"],
            sandbox_verification_ids=[],
        )
        return PolicyResult(
            task_id,
            PolicyOutcome.SUCCEEDED,
            PolicyAction.FINALIZE_VERIFIED,
            None,
            len(self._executor_runs(task_id)),
            0,
            workspace["id"],
        )

    def _loop_detected(self, task_id: str) -> bool:
        hashes = self._proposal_hashes(task_id)
        return len(hashes) >= 2 and hashes[-1] == hashes[-2]

    def _budget_exhausted(self, task_id: str) -> str | None:
        config = load_config(self.runtime.project_root)
        executor_attempts = len(self._executor_runs(task_id))
        if executor_attempts >= 1 + config.max_strategy_retries:
            return (
                f"strategy retry budget exhausted: {executor_attempts} executor attempts "
                f"with max_strategy_retries={config.max_strategy_retries}"
            )
        verification_failures = self._sandbox_failure_count(task_id)
        if verification_failures > 0 and verification_failures >= config.max_verification_failures:
            return (
                f"verification failure budget exhausted: {verification_failures} failures "
                f"with max_verification_failures={config.max_verification_failures}"
            )
        return None

    def _quarantine(
        self, task_id: str, reason: str, *, workspace_id: str | None = None
    ) -> PolicyResult:
        self._record_policy_verification(
            task_id,
            status="BLOCKED",
            reason=reason,
            action=PolicyAction.STOP,
            evidence={"workspace_id": workspace_id} if workspace_id else {},
        )
        task = self.runtime.get_task(task_id)
        if task["status"] == TaskStatus.READY.value:
            revision = self.runtime.transition_task(
                task_id,
                TaskStatus.BLOCKED,
                expected_revision=int(task["revision"]),
            )
            self.runtime.transition_task(
                task_id,
                TaskStatus.QUARANTINED,
                expected_revision=revision,
            )
        elif task["status"] in {
            TaskStatus.BLOCKED.value,
            TaskStatus.FAILED.value,
            TaskStatus.RUNNING.value,
        }:
            self.runtime.transition_task(
                task_id,
                TaskStatus.QUARANTINED,
                expected_revision=int(task["revision"]),
            )
        return PolicyResult(
            task_id,
            PolicyOutcome.QUARANTINED,
            PolicyAction.STOP,
            reason,
            len(self._executor_runs(task_id)),
            0,
            workspace_id,
        )

    def _prepare_fresh_attempt(self, task_id: str) -> None:
        workspace = self._active_workspace(task_id)
        if workspace is not None:
            status = WorkspaceStatus(workspace["status"])
            if status == WorkspaceStatus.FAILED:
                self.workspaces.abandon(workspace["id"])
            elif status == WorkspaceStatus.CREATED:
                changed = self.workspaces.changed_paths(workspace["id"])
                if changed:
                    raise RuntimeInvariantError(
                        f"created workspace {workspace['id']} contains partial changes; recover it before retry"
                    )
                self.workspaces.abandon(workspace["id"])
            else:
                raise RuntimeInvariantError(
                    f"workspace {workspace['id']} is {status.value} and must be resumed, not replaced"
                )

        task = self.runtime.get_task(task_id)
        if task["status"] == TaskStatus.RUNNING.value:
            revision = self.runtime.transition_task(
                task_id,
                TaskStatus.FAILED,
                expected_revision=int(task["revision"]),
            )
            self.runtime.transition_task(
                task_id,
                TaskStatus.READY,
                expected_revision=revision,
            )
        elif task["status"] in {TaskStatus.FAILED.value, TaskStatus.BLOCKED.value}:
            self.runtime.transition_task(
                task_id,
                TaskStatus.READY,
                expected_revision=int(task["revision"]),
            )
        elif task["status"] != TaskStatus.READY.value:
            raise RuntimeInvariantError(
                f"cannot prepare fresh attempt from task state {task['status']}"
            )

    def _select_model(self, task_id: str) -> ModelAdapter:
        attempt_index = len(self._executor_runs(task_id))
        return self.models[min(attempt_index, len(self.models) - 1)]

    def drive(
        self,
        task_id: str,
        *,
        selected_paths: Iterable[str],
    ) -> PolicyResult:
        selected = tuple(selected_paths)
        if not selected:
            raise ValueError("bounded retry policy requires explicit context files")
        attempts_started = 0
        last_attempt: OrchestrationResult | None = None

        while True:
            task = self.runtime.get_task(task_id)
            if task["status"] == TaskStatus.SUCCEEDED.value:
                return PolicyResult(
                    task_id,
                    PolicyOutcome.SUCCEEDED,
                    PolicyAction.STOP,
                    None,
                    len(self._executor_runs(task_id)),
                    attempts_started,
                    self._active_workspace(task_id)["id"]
                    if self._active_workspace(task_id)
                    else None,
                    last_attempt,
                )
            if task["status"] == TaskStatus.CANCELLED.value:
                return PolicyResult(
                    task_id,
                    PolicyOutcome.BLOCKED,
                    PolicyAction.STOP,
                    "task is cancelled",
                    len(self._executor_runs(task_id)),
                    attempts_started,
                    last_attempt=last_attempt,
                )
            if task["status"] == TaskStatus.QUARANTINED.value:
                return PolicyResult(
                    task_id,
                    PolicyOutcome.QUARANTINED,
                    PolicyAction.STOP,
                    "task is quarantined",
                    len(self._executor_runs(task_id)),
                    attempts_started,
                    self._active_workspace(task_id)["id"]
                    if self._active_workspace(task_id)
                    else None,
                    last_attempt,
                )

            workspace = self._active_workspace(task_id)
            if workspace is not None:
                status = WorkspaceStatus(workspace["status"])
                if status == WorkspaceStatus.VERIFIED:
                    return self._finalize_verified(task_id, workspace)
                if status == WorkspaceStatus.AUDITED:
                    resumed = self._resume_sandbox(task_id, workspace)
                    if resumed.outcome != PolicyOutcome.FAILED:
                        return resumed
                elif status == WorkspaceStatus.APPLIED:
                    resumed = self._resume_applied(task_id, workspace)
                    if resumed.outcome != PolicyOutcome.FAILED:
                        return resumed
                elif status == WorkspaceStatus.CREATED:
                    changed = self.workspaces.changed_paths(workspace["id"])
                    if changed:
                        return self._quarantine(
                            task_id,
                            "created workspace contains unexplained partial changes",
                            workspace_id=workspace["id"],
                        )

            if self._loop_detected(task_id):
                return self._quarantine(
                    task_id,
                    "exact Patch Proposal repeated on consecutive model attempts",
                    workspace_id=workspace["id"] if workspace else None,
                )

            exhausted = self._budget_exhausted(task_id)
            if exhausted is not None:
                return self._quarantine(
                    task_id,
                    exhausted,
                    workspace_id=workspace["id"] if workspace else None,
                )

            self._prepare_fresh_attempt(task_id)
            model = self._select_model(task_id)
            action = PolicyAction.ATTEMPT if not self._executor_runs(task_id) else PolicyAction.RETRY
            last_attempt = BoundedTaskOrchestrator(
                self.runtime,
                model,
                self.sandbox_backend,
                workspaces=self.workspaces,
            ).execute(
                task_id,
                selected_paths=selected,
                model_profile=model.model_id,
            )
            attempts_started += 1

            if last_attempt.outcome == AttemptOutcome.SUCCEEDED:
                return PolicyResult(
                    task_id,
                    PolicyOutcome.SUCCEEDED,
                    action,
                    None,
                    len(self._executor_runs(task_id)),
                    attempts_started,
                    last_attempt.workspace_id,
                    last_attempt,
                )
            if last_attempt.outcome == AttemptOutcome.BLOCKED and last_attempt.stage in {
                AttemptStage.PREFLIGHT,
                AttemptStage.SANDBOX,
            }:
                return PolicyResult(
                    task_id,
                    PolicyOutcome.BLOCKED,
                    action,
                    last_attempt.reason,
                    len(self._executor_runs(task_id)),
                    attempts_started,
                    last_attempt.workspace_id,
                    last_attempt,
                )
            # Executor blocking and deterministic failures are strategy outcomes.
            # The loop continues only while explicit budgets allow another attempt.
