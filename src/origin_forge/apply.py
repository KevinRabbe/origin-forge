from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .lineage import OriginForgeLineage
from .patches import FileOperation, PatchProposal, validate_patch_preconditions
from .proposal_artifacts import load_patch_proposal_artifact
from .repository import RepositoryReader
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import RunStatus, WorkspaceStatus
from .workspaces import GitWorkspaceManager


@dataclass(frozen=True)
class ApplyResult:
    workspace_id: str
    run_id: str
    change_id: str
    diff_artifact_id: str
    diff_text: str


class IsolatedPatchApplier:
    """Deterministically applies a validated proposal only inside a tracked worktree."""

    def __init__(self, runtime: OriginForgeRuntime, workspaces: GitWorkspaceManager | None = None):
        self.runtime = runtime
        self.workspaces = workspaces or GitWorkspaceManager(runtime)
        self.lineage = OriginForgeLineage(runtime)

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".origin-forge-tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)

    def apply_artifact(
        self, workspace_id: str, proposal_artifact_id: str
    ) -> ApplyResult:
        workspace = self.workspaces.get(workspace_id)
        proposal = load_patch_proposal_artifact(
            self.runtime,
            proposal_artifact_id,
            expected_task_id=workspace["task_id"],
        )
        return self.apply(
            workspace_id, proposal, source_artifact_id=proposal_artifact_id
        )

    def apply(
        self,
        workspace_id: str,
        proposal: PatchProposal,
        *,
        source_artifact_id: str | None = None,
    ) -> ApplyResult:
        workspace_row = self.workspaces.get(workspace_id)
        if workspace_row["status"] != WorkspaceStatus.CREATED.value:
            raise RuntimeInvariantError(
                f"workspace must be CREATED before apply; got {workspace_row['status']}"
            )
        task_id = workspace_row["task_id"]
        workspace_path = self.workspaces.path(workspace_id)
        repository = RepositoryReader(workspace_path)
        validate_patch_preconditions(proposal, repository)

        run_id = self.runtime.start_run(task_id, role="APPLIER")
        try:
            for change in proposal.changes:
                target = (workspace_path / change.path).resolve()
                try:
                    target.relative_to(workspace_path)
                except ValueError as exc:
                    raise RuntimeInvariantError("patch target escaped workspace") from exc
                if change.operation in (FileOperation.CREATE, FileOperation.UPDATE):
                    assert change.content is not None
                    self._write(target, change.content)
                elif change.operation == FileOperation.DELETE:
                    target.unlink()

            diff_text = self.workspaces.stage_and_diff(workspace_id)
            if not diff_text and proposal.changes:
                raise RuntimeInvariantError("proposal produced no Git diff")

            evidence_dir = self.runtime.state_dir / "workspace-evidence" / workspace_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            diff_path = evidence_dir / "applied.diff"
            diff_path.write_text(diff_text, encoding="utf-8")

            change_id = self.lineage.create_change(
                task_id,
                summary=proposal.summary,
                change_type="ISOLATED_PATCH",
                run_id=run_id,
                before_ref=workspace_row["base_commit"],
                after_ref=workspace_row["branch_name"],
                status="APPLIED_ISOLATED",
            )
            diff_artifact_id = self.lineage.create_artifact(
                artifact_type="GIT_DIFF",
                path_or_uri=str(diff_path),
                change_id=change_id,
                parent_artifact_id=source_artifact_id,
                created_by_run_id=run_id,
                status="PRODUCED",
            )
            self.workspaces.transition(
                workspace_id,
                WorkspaceStatus.APPLIED,
                expected_revision=int(workspace_row["revision"]),
                event_type="WORKSPACE_PATCH_APPLIED",
                metadata={"proposal_artifact_id": source_artifact_id}
                if source_artifact_id
                else {},
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return ApplyResult(
                workspace_id,
                run_id,
                change_id,
                diff_artifact_id,
                diff_text,
            )
        except Exception as exc:
            try:
                self.workspaces.reset_clean(workspace_id)
                current = self.workspaces.get(workspace_id)
                if current["status"] == WorkspaceStatus.CREATED.value:
                    self.workspaces.transition(
                        workspace_id,
                        WorkspaceStatus.FAILED,
                        expected_revision=int(current["revision"]),
                        event_type="WORKSPACE_APPLY_FAILED",
                    )
            finally:
                try:
                    run = self.runtime.get_run(run_id)
                    if run["status"] == RunStatus.RUNNING.value:
                        self.runtime.finish_run(
                            run_id,
                            RunStatus.FAILED,
                            failure_reason=f"{type(exc).__name__}: {exc}",
                        )
                except Exception:
                    pass
            raise
