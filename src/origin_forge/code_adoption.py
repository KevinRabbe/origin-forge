from __future__ import annotations

import re
from dataclasses import dataclass

from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import TaskStatus, WorkspaceStatus
from .workspaces import GitWorkspaceError, GitWorkspaceManager


class CodeAdoptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodeAdoptionResult:
    task_id: str
    workspace_id: str
    change_id: str
    artifact_id: str
    adopted_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "change_id": self.change_id,
            "artifact_id": self.artifact_id,
            "adopted_paths": list(self.adopted_paths),
        }


_ACCEPT_CONTEXT = re.compile(r"^task_id=(?P<task_id>[^;]+); task_revision=(?P<revision>[0-9]+)$")


class VerifiedCodeAdopter:
    """Apply one explicitly accepted verified coding workspace to the project.

    Adoption is intentionally separate from execution and verification. It
    refuses dirty or stale project roots and never overwrites an uncertain
    working tree.
    """

    def __init__(self, runtime: OriginForgeRuntime, *, workspaces: GitWorkspaceManager | None = None):
        self.runtime = runtime
        self.workspaces = workspaces or GitWorkspaceManager(runtime)
        self.lineage = OriginForgeLineage(runtime)

    def _accepted_decision(self, task_id: str, revision: int) -> str:
        matches: list[dict[str, object]] = []
        for decision in self.lineage.list_decisions():
            if decision.get("task_id") != task_id or decision.get("decision") != "ACCEPT":
                continue
            context = decision.get("context")
            if not isinstance(context, str):
                continue
            parsed = _ACCEPT_CONTEXT.fullmatch(context)
            if parsed and parsed.group("task_id") == task_id and int(parsed.group("revision")) == revision:
                matches.append(decision)
        if len(matches) != 1:
            raise CodeAdoptionError(
                "code adoption requires exactly one current human ACCEPT decision"
            )
        return str(matches[0]["id"])

    def adopt_new(self, task_id: str, *, expected_revision: int) -> CodeAdoptionResult:
        task = self.runtime.get_task(task_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        if int(task["revision"]) != expected_revision:
            raise CodeAdoptionError(
                f"task revision is stale: expected {expected_revision}; current {task['revision']}"
            )
        if task["status"] != TaskStatus.SUCCEEDED.value:
            raise CodeAdoptionError("code adoption requires a SUCCEEDED Task")
        decision_id = self._accepted_decision(task_id, expected_revision)

        candidates = [
            row
            for row in self.workspaces.list(task_id)
            if row["status"] == WorkspaceStatus.VERIFIED.value
        ]
        if len(candidates) != 1:
            raise CodeAdoptionError(
                "code adoption requires exactly one VERIFIED workspace"
            )
        workspace = candidates[0]
        try:
            current_head = self.workspaces._git(
                "rev-parse", "--verify", "HEAD^{commit}"
            ).stdout.strip()
            if current_head != workspace["base_commit"]:
                raise CodeAdoptionError("project HEAD is stale relative to the verified workspace")
            dirty = self.workspaces._git("status", "--porcelain", "--untracked-files=all").stdout
            if dirty.strip():
                raise CodeAdoptionError("code adoption requires a clean project working tree")
            patch_text = self.workspaces._git(
                "diff", "--cached", "--binary", "--no-ext-diff", "--no-renames", "--",
                cwd=self.workspaces.path(workspace["id"]),
            ).stdout
            if not patch_text.strip():
                raise CodeAdoptionError("verified workspace contains no staged code change")
        except GitWorkspaceError as exc:
            raise CodeAdoptionError(f"cannot inspect Git adoption boundary: {exc}") from exc

        patch_dir = self.runtime.state_dir / "code-adoptions"
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patch_dir / f"{task_id}.patch"
        if patch_path.exists():
            raise CodeAdoptionError("code adoption receipt already exists for this Task")
        patch_path.write_text(patch_text, encoding="utf-8", newline="\n")
        try:
            self.workspaces._git("apply", "--index", str(patch_path))
        except GitWorkspaceError as exc:
            raise CodeAdoptionError(f"cannot apply verified code change: {exc}") from exc

        adopted_paths = tuple(
            line.strip()
            for line in self.workspaces._git(
                "diff", "--cached", "--name-only", "--no-renames", "--"
            ).stdout.splitlines()
            if line.strip()
        )
        if not adopted_paths:
            raise RuntimeInvariantError("code adoption produced no staged paths")
        change_id = self.lineage.create_change(
            task_id,
            summary="Human-adopted verified gameplay code",
            change_type="CODE_ADOPTION",
            decision_id=decision_id,
            before_ref=current_head,
            after_ref="project-index",
            status="ADOPTED",
        )
        artifact_id = self.lineage.create_artifact(
            artifact_type="ADOPTED_CODE_PATCH",
            path_or_uri=str(patch_path),
            change_id=change_id,
            created_by_run_id=None,
            status="ADOPTED",
        )
        return CodeAdoptionResult(task_id, workspace["id"], change_id, artifact_id, adopted_paths)
