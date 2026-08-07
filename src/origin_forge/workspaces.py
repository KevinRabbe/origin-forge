from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ids import IdKind, new_id
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .service import utc_now
from .state import TaskStatus, WorkspaceStatus


class GitWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str


@dataclass(frozen=True)
class WorkspaceRecoveryFinding:
    workspace_id: str
    status: str
    reason: str


class GitWorkspaceManager:
    """Creates and tracks disposable Git worktrees for isolated task mutation."""

    def __init__(self, runtime: OriginForgeRuntime, *, timeout_seconds: float = 30.0):
        self.runtime = runtime
        self.store = runtime.store
        self.project_root = runtime.project_root
        self.timeout_seconds = timeout_seconds
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _git(self, *args: str, cwd: Path | None = None) -> GitResult:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd or self.project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitWorkspaceError(f"git command failed to start/finish: {exc}") from exc
        if result.returncode != 0:
            raise GitWorkspaceError(
                f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()[:2000]}"
            )
        return GitResult(result.stdout, result.stderr)

    def require_repository_root(self) -> None:
        top = Path(self._git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
        if top != self.project_root:
            raise RuntimeInvariantError(
                f"Phase 3 requires project root to equal Git toplevel: {top}"
            )

    def _ensure_state_excluded(self) -> None:
        exclude_path = Path(
            self._git("rev-parse", "--git-path", "info/exclude").stdout.strip()
        )
        if not exclude_path.is_absolute():
            exclude_path = self.project_root / exclude_path
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        line = "/.origin-forge/"
        if line not in {item.strip() for item in existing.splitlines()}:
            with exclude_path.open("a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write(line + "\n")

    def create(self, task_id: str, *, base_ref: str = "HEAD") -> str:
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"workspace requires RUNNING task; task {task_id} is {task['status']}"
            )
        self.require_repository_root()
        self._ensure_state_excluded()
        with self.store.session() as conn:
            active = conn.execute(
                "SELECT id, status FROM workspaces WHERE task_id = ? AND status != ? LIMIT 1",
                (task_id, WorkspaceStatus.ABANDONED.value),
            ).fetchone()
        if active is not None:
            raise RuntimeInvariantError(
                f"task {task_id} already has active workspace {active['id']} ({active['status']})"
            )

        workspace_id = new_id(IdKind.WORKSPACE)
        suffix = workspace_id.split("-", 1)[1].replace("-", "")[:12]
        task_tag = task_id.split("-", 1)[1].replace("-", "")[:12]
        branch_name = f"origin-forge/{task_tag}/{suffix}"
        workspace_rel = Path(".origin-forge") / "workspaces" / workspace_id
        workspace_path = (self.project_root / workspace_rel).resolve()
        if workspace_path.exists():
            raise GitWorkspaceError(f"workspace path already exists: {workspace_path}")

        base_commit = self._git("rev-parse", "--verify", f"{base_ref}^{{commit}}").stdout.strip()
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        self._git(
            "worktree",
            "add",
            "--no-track",
            "-b",
            branch_name,
            str(workspace_path),
            base_commit,
        )

        now = utc_now()
        try:
            with self.store.session() as conn:
                conn.execute(
                    """INSERT INTO workspaces(
                           id, project_id, task_id, branch_name, path, base_commit,
                           status, revision, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                    (
                        workspace_id,
                        self.runtime.project_id(),
                        task_id,
                        branch_name,
                        workspace_rel.as_posix(),
                        base_commit,
                        WorkspaceStatus.CREATED.value,
                        now,
                        now,
                    ),
                )
                self.store._append_event(
                    conn,
                    "WORKSPACE",
                    workspace_id,
                    "WORKSPACE_CREATED",
                    None,
                    WorkspaceStatus.CREATED.value,
                    0,
                    "SYSTEM",
                    None,
                    {
                        "task_id": task_id,
                        "branch": branch_name,
                        "base_commit": base_commit,
                    },
                    now,
                )
        except Exception:
            try:
                self._git("worktree", "remove", "--force", str(workspace_path))
                self._git("branch", "-D", branch_name)
            except Exception:
                pass
            raise
        return workspace_id

    def get(self, workspace_id: str) -> dict:
        with self.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id = ? AND project_id = ?",
                (workspace_id, self.runtime.project_id()),
            ).fetchone()
            if row is None:
                raise KeyError(workspace_id)
            return dict(row)

    def path(self, workspace_id: str) -> Path:
        row = self.get(workspace_id)
        resolved = (self.project_root / row["path"]).resolve()
        workspace_root = (self.project_root / ".origin-forge" / "workspaces").resolve()
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise RuntimeInvariantError("stored workspace path escaped workspace root") from exc
        return resolved

    def list(self, task_id: str | None = None) -> list[dict]:
        params: list[str] = [self.runtime.project_id()]
        sql = "SELECT * FROM workspaces WHERE project_id = ?"
        if task_id is not None:
            self.runtime.get_task(task_id)
            sql += " AND task_id = ?"
            params.append(task_id)
        sql += " ORDER BY created_at, rowid"
        with self.store.session() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def transition(
        self,
        workspace_id: str,
        target: WorkspaceStatus,
        *,
        expected_revision: int,
        event_type: str,
        metadata: dict | None = None,
    ) -> int:
        row = self.get(workspace_id)
        actual = int(row["revision"])
        if actual != expected_revision:
            raise RuntimeInvariantError(
                f"workspace {workspace_id} revision {actual} != expected {expected_revision}"
            )
        current = WorkspaceStatus(row["status"])
        allowed = {
            WorkspaceStatus.CREATED: {
                WorkspaceStatus.APPLIED,
                WorkspaceStatus.FAILED,
                WorkspaceStatus.ABANDONED,
            },
            WorkspaceStatus.APPLIED: {
                WorkspaceStatus.VERIFIED,
                WorkspaceStatus.FAILED,
                WorkspaceStatus.ABANDONED,
            },
            WorkspaceStatus.VERIFIED: {WorkspaceStatus.ABANDONED},
            WorkspaceStatus.FAILED: {WorkspaceStatus.ABANDONED},
            WorkspaceStatus.ABANDONED: set(),
        }
        if target not in allowed[current]:
            raise RuntimeInvariantError(
                f"invalid workspace transition: {current.value} -> {target.value}"
            )
        new_revision = actual + 1
        now = utc_now()
        with self.store.session() as conn:
            cursor = conn.execute(
                """UPDATE workspaces SET status = ?, revision = ?, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (target.value, new_revision, now, workspace_id, actual),
            )
            if cursor.rowcount != 1:
                raise RuntimeInvariantError("workspace changed concurrently")
            self.store._append_event(
                conn,
                "WORKSPACE",
                workspace_id,
                event_type,
                current.value,
                target.value,
                new_revision,
                "SYSTEM",
                None,
                metadata or {},
                now,
            )
        return new_revision

    def stage_and_diff(self, workspace_id: str) -> str:
        path = self.path(workspace_id)
        self._git("add", "-A", "--", ".", cwd=path)
        return self._git(
            "diff",
            "--cached",
            "--no-ext-diff",
            "--no-renames",
            "--binary",
            "--",
            cwd=path,
        ).stdout

    @staticmethod
    def _nul_paths(raw: str) -> set[str]:
        return {item for item in raw.split("\0") if item}

    def changed_paths(self, workspace_id: str) -> set[str]:
        path = self.path(workspace_id)
        staged = self._git(
            "diff", "--cached", "--no-renames", "--name-only", "-z", "--", cwd=path
        ).stdout
        unstaged = self._git(
            "diff", "--no-renames", "--name-only", "-z", "--", cwd=path
        ).stdout
        untracked = self._git(
            "ls-files", "--others", "--exclude-standard", "-z", cwd=path
        ).stdout
        return self._nul_paths(staged) | self._nul_paths(unstaged) | self._nul_paths(untracked)

    def reset_clean(self, workspace_id: str) -> None:
        path = self.path(workspace_id)
        self._git("reset", "--hard", "HEAD", cwd=path)
        self._git("clean", "-fdx", cwd=path)

    def record_verification(
        self,
        workspace_id: str,
        *,
        verification_type: str,
        verifier: str,
        status: str,
        evidence: dict | None = None,
    ) -> str:
        self.get(workspace_id)
        return self.store.record_verification(
            target_type="WORKSPACE",
            target_id=workspace_id,
            verification_type=verification_type,
            verifier=verifier,
            status=status,
            evidence=evidence or {},
        )

    def recovery_findings(self) -> list[WorkspaceRecoveryFinding]:
        findings: list[WorkspaceRecoveryFinding] = []
        for row in self.list():
            status = WorkspaceStatus(row["status"])
            path = self.path(row["id"])
            if status == WorkspaceStatus.CREATED:
                if not path.exists():
                    findings.append(
                        WorkspaceRecoveryFinding(
                            row["id"], status.value, "created workspace path is missing"
                        )
                    )
                    continue
                try:
                    changed = self.changed_paths(row["id"])
                except GitWorkspaceError:
                    findings.append(
                        WorkspaceRecoveryFinding(
                            row["id"], status.value, "created workspace cannot be inspected"
                        )
                    )
                    continue
                if changed:
                    findings.append(
                        WorkspaceRecoveryFinding(
                            row["id"],
                            status.value,
                            "created workspace contains uncommitted partial changes",
                        )
                    )
        return findings

    def recover(self) -> list[WorkspaceRecoveryFinding]:
        findings = self.recovery_findings()
        for finding in findings:
            row = self.get(finding.workspace_id)
            if row["status"] != WorkspaceStatus.CREATED.value:
                continue
            path = (self.project_root / row["path"]).resolve()
            if path.exists():
                try:
                    self.reset_clean(finding.workspace_id)
                except Exception:
                    pass
            current = self.get(finding.workspace_id)
            if current["status"] == WorkspaceStatus.CREATED.value:
                self.transition(
                    finding.workspace_id,
                    WorkspaceStatus.FAILED,
                    expected_revision=int(current["revision"]),
                    event_type="WORKSPACE_RECOVERED_AS_FAILED",
                )
        return findings

    def abandon(self, workspace_id: str) -> None:
        row = self.get(workspace_id)
        if row["status"] == WorkspaceStatus.ABANDONED.value:
            return
        path = self.path(workspace_id)
        if path.exists():
            self._git("worktree", "remove", "--force", str(path))
        else:
            self._git("worktree", "prune")
        self.transition(
            workspace_id,
            WorkspaceStatus.ABANDONED,
            expected_revision=int(row["revision"]),
            event_type="WORKSPACE_ABANDONED",
        )
