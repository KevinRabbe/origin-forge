from __future__ import annotations

from dataclasses import dataclass

from .patches import FileOperation, PatchProposal
from .proposal_artifacts import load_patch_proposal_artifact
from .repository import RepositoryReader
from .runtime import OriginForgeRuntime
from .state import WorkspaceStatus
from .workspaces import GitWorkspaceManager


@dataclass(frozen=True)
class AuditResult:
    workspace_id: str
    passed: bool
    verification_id: str
    findings: tuple[str, ...]


class WorkspaceAuditor:
    """Read-only deterministic audit of an isolated applied proposal."""

    def __init__(self, runtime: OriginForgeRuntime, workspaces: GitWorkspaceManager | None = None):
        self.runtime = runtime
        self.workspaces = workspaces or GitWorkspaceManager(runtime)

    def audit_artifact(
        self, workspace_id: str, proposal_artifact_id: str
    ) -> AuditResult:
        workspace = self.workspaces.get(workspace_id)
        proposal = load_patch_proposal_artifact(
            self.runtime,
            proposal_artifact_id,
            expected_task_id=workspace["task_id"],
        )
        return self._audit(workspace_id, proposal)

    def _audit(self, workspace_id: str, proposal: PatchProposal) -> AuditResult:
        row = self.workspaces.get(workspace_id)
        findings: list[str] = []
        if row["status"] != WorkspaceStatus.APPLIED.value:
            findings.append(f"workspace status is {row['status']}, expected APPLIED")

        workspace_path = self.workspaces.path(workspace_id)
        reader = RepositoryReader(workspace_path)
        actual_paths = self.workspaces.changed_paths(workspace_id)

        expected_paths = {change.path for change in proposal.changes}
        if actual_paths != expected_paths:
            findings.append(
                f"changed paths differ: actual={sorted(actual_paths)} expected={sorted(expected_paths)}"
            )

        for change in proposal.changes:
            if change.operation == FileOperation.DELETE:
                if reader.exists(change.path):
                    findings.append(f"DELETE target still exists: {change.path}")
                continue
            try:
                source = reader.read_text(change.path)
            except Exception as exc:
                findings.append(f"cannot read {change.path}: {exc}")
                continue
            if source.content != change.content:
                findings.append(f"content mismatch: {change.path}")

        passed = not findings
        verification_id = self.workspaces.record_verification(
            workspace_id,
            verification_type="isolated-patch-audit",
            verifier="OriginForge.WorkspaceAuditor",
            status="PASS" if passed else "FAIL",
            evidence={"findings": findings, "expected_paths": sorted(expected_paths)},
        )

        current = self.workspaces.get(workspace_id)
        if current["status"] == WorkspaceStatus.APPLIED.value:
            self.workspaces.transition(
                workspace_id,
                WorkspaceStatus.VERIFIED if passed else WorkspaceStatus.FAILED,
                expected_revision=int(current["revision"]),
                event_type="WORKSPACE_AUDIT_PASSED" if passed else "WORKSPACE_AUDIT_FAILED",
            )
        return AuditResult(workspace_id, passed, verification_id, tuple(findings))
