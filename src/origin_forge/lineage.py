from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from .records import create_artifact, create_change, create_decision
from .runtime import OriginForgeRuntime, RuntimeInvariantError


def _row_dict(row) -> dict[str, Any]:
    return dict(row)


class OriginForgeLineage:
    """Causal history and artifact lineage service.

    This service sits beside OriginForgeRuntime so persistence details remain
    hidden while provenance-specific invariants stay isolated from scheduling
    and lifecycle logic.
    """

    def __init__(self, runtime: OriginForgeRuntime):
        self.runtime = runtime
        self.store = runtime.store
        self.project_root = runtime.project_root

    def create_decision(
        self,
        *,
        title: str,
        decision: str,
        context: str | None = None,
        rationale: str | None = None,
        alternatives: Iterable[str] = (),
        goal_id: str | None = None,
        task_id: str | None = None,
        supersedes_decision_id: str | None = None,
    ) -> str:
        project_id = self.runtime.project_id()
        if goal_id is not None:
            self.runtime.get_goal(goal_id)
        if task_id is not None:
            self.runtime.get_task(task_id)
            if goal_id is not None:
                with self.store.session() as conn:
                    task_goal = conn.execute(
                        """SELECT f.goal_id FROM tasks t
                           JOIN flows f ON f.id = t.flow_id
                           WHERE t.id = ?""",
                        (task_id,),
                    ).fetchone()["goal_id"]
                if task_goal != goal_id:
                    raise RuntimeInvariantError(
                        "decision goal_id must match the task's goal"
                    )
        if supersedes_decision_id is not None:
            self.get_decision(supersedes_decision_id)
        return create_decision(
            self.store,
            project_id,
            title=title,
            decision=decision,
            context=context,
            rationale=rationale,
            alternatives=alternatives,
            goal_id=goal_id,
            task_id=task_id,
            supersedes_decision_id=supersedes_decision_id,
        )

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        with self.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE id = ? AND project_id = ?",
                (decision_id, self.runtime.project_id()),
            ).fetchone()
            if row is None:
                raise KeyError(decision_id)
            return _row_dict(row)

    def list_decisions(self) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            return [
                _row_dict(row)
                for row in conn.execute(
                    "SELECT * FROM decisions WHERE project_id = ? ORDER BY created_at, rowid",
                    (self.runtime.project_id(),),
                )
            ]

    def create_change(
        self,
        task_id: str,
        *,
        summary: str,
        change_type: str,
        decision_id: str | None = None,
        run_id: str | None = None,
        before_ref: str | None = None,
        after_ref: str | None = None,
        status: str = "RECORDED",
    ) -> str:
        self.runtime.get_task(task_id)
        if decision_id is not None:
            self.get_decision(decision_id)
        if run_id is not None:
            run = self.runtime.get_run(run_id)
            if run["task_id"] != task_id:
                raise RuntimeInvariantError(
                    "change run_id must belong to the same task"
                )
        return create_change(
            self.store,
            task_id,
            summary=summary,
            change_type=change_type,
            decision_id=decision_id,
            run_id=run_id,
            before_ref=before_ref,
            after_ref=after_ref,
            status=status,
        )

    def get_change(self, change_id: str) -> dict[str, Any]:
        project_id = self.runtime.project_id()
        with self.store.session() as conn:
            row = conn.execute(
                """SELECT c.* FROM changes c
                   JOIN tasks t ON t.id = c.task_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE c.id = ? AND g.project_id = ?""",
                (change_id, project_id),
            ).fetchone()
            if row is None:
                raise KeyError(change_id)
            return _row_dict(row)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def _artifact_location(self, path_or_uri: str) -> tuple[str, str | None]:
        if "://" in path_or_uri:
            return path_or_uri, None
        candidate = Path(path_or_uri)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.project_root / candidate).resolve()
        )
        try:
            relative = resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise RuntimeInvariantError(
                "local artifact paths must stay inside the project root"
            ) from exc
        content_hash = self._sha256(resolved) if resolved.is_file() else None
        return relative.as_posix(), content_hash

    def create_artifact(
        self,
        *,
        artifact_type: str,
        path_or_uri: str,
        change_id: str | None = None,
        parent_artifact_id: str | None = None,
        created_by_run_id: str | None = None,
        model_id: str | None = None,
        skill_versions: Iterable[str] = (),
        tool_versions: Iterable[str] = (),
        status: str = "PRODUCED",
    ) -> str:
        project_id = self.runtime.project_id()
        if change_id is not None:
            self.get_change(change_id)
        if parent_artifact_id is not None:
            self.get_artifact(parent_artifact_id)
        if created_by_run_id is not None:
            self.runtime.get_run(created_by_run_id)
        stored_location, content_hash = self._artifact_location(path_or_uri)
        return create_artifact(
            self.store,
            project_id,
            artifact_type=artifact_type,
            path_or_uri=stored_location,
            content_hash=content_hash,
            change_id=change_id,
            parent_artifact_id=parent_artifact_id,
            created_by_run_id=created_by_run_id,
            model_id=model_id,
            skill_versions=skill_versions,
            tool_versions=tool_versions,
            status=status,
        )

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
                (artifact_id, self.runtime.project_id()),
            ).fetchone()
            if row is None:
                raise KeyError(artifact_id)
            return _row_dict(row)

    def local_artifact_path(self, artifact_id: str) -> Path:
        artifact = self.get_artifact(artifact_id)
        location = artifact["path_or_uri"]
        if "://" in location:
            raise RuntimeInvariantError("artifact is not a local file")
        resolved = (self.project_root / location).resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise RuntimeInvariantError("stored artifact path escaped project root") from exc
        if not resolved.is_file():
            raise RuntimeInvariantError(f"artifact file is missing: {location}")
        expected = artifact["content_hash"]
        if expected is not None:
            actual = self._sha256(resolved)
            if actual != expected:
                raise RuntimeInvariantError(
                    f"artifact integrity mismatch for {artifact_id}: {actual} != {expected}"
                )
        return resolved

    def read_artifact_text(self, artifact_id: str) -> str:
        path = self.local_artifact_path(artifact_id)
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeInvariantError("artifact is not UTF-8 text") from exc

    def list_artifacts(self) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            return [
                _row_dict(row)
                for row in conn.execute(
                    "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at, rowid",
                    (self.runtime.project_id(),),
                )
            ]

    def record_artifact_verification(
        self,
        artifact_id: str,
        *,
        verification_type: str,
        verifier: str,
        status: str,
    ) -> str:
        self.get_artifact(artifact_id)
        return self.store.record_verification(
            target_type="ARTIFACT",
            target_id=artifact_id,
            verification_type=verification_type,
            verifier=verifier,
            status=status,
        )

    def list_artifact_verifications(self, artifact_id: str) -> list[dict[str, Any]]:
        self.get_artifact(artifact_id)
        with self.store.session() as conn:
            return [
                _row_dict(row)
                for row in conn.execute(
                    """SELECT * FROM verifications
                       WHERE target_type = 'ARTIFACT' AND target_id = ?
                       ORDER BY created_at, rowid""",
                    (artifact_id,),
                )
            ]
