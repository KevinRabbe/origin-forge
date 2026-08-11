from __future__ import annotations

from .ids import IdKind, validate_id
from .production_read_guard import ensure_production_runtime_readable
from .runtime import OriginForgeRuntime


_MAX_READ_LIMIT = 10_000


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_READ_LIMIT:
        raise ValueError(f"production evidence read limit must be 1..{_MAX_READ_LIMIT}")
    return value


def _decision(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "goal_id": row["goal_id"],
        "task_id": row["task_id"],
        "title": row["title"],
        "decision": row["decision"],
        "rationale": row["rationale"],
        "status": row["status"],
        "supersedes_decision_id": row["supersedes_decision_id"],
        "created_at": row["created_at"],
        "context_disclosed": False,
        "alternatives_disclosed": False,
    }


def _change(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "decision_id": row["decision_id"],
        "run_id": row["run_id"],
        "summary": row["summary"],
        "change_type": row["change_type"],
        "before_ref": row["before_ref"],
        "after_ref": row["after_ref"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _artifact(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "change_id": row["change_id"],
        "type": row["type"],
        "path_or_uri": row["path_or_uri"],
        "content_hash": row["content_hash"],
        "parent_artifact_id": row["parent_artifact_id"],
        "created_by_run_id": row["created_by_run_id"],
        "model_id": row["model_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "artifact_bytes_disclosed": False,
        "skill_versions_disclosed": False,
        "tool_versions_disclosed": False,
    }


class ProductionEvidenceReadService:
    """SELECT-only bounded causal-history projection for the production cockpit."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        ensure_production_runtime_readable(runtime)
        self.runtime = runtime

    @property
    def project_id(self) -> str:
        return self.runtime.project_id()

    def counts(self) -> dict[str, int]:
        project_id = self.project_id
        with self.runtime.store.session() as conn:
            decisions = int(
                conn.execute(
                    "SELECT COUNT(*) FROM decisions WHERE project_id = ?", (project_id,)
                ).fetchone()[0]
            )
            changes = int(
                conn.execute(
                    """SELECT COUNT(*) FROM changes c
                       JOIN tasks t ON t.id = c.task_id
                       JOIN flows f ON f.id = t.flow_id
                       JOIN goals g ON g.id = f.goal_id
                       WHERE g.project_id = ?""",
                    (project_id,),
                ).fetchone()[0]
            )
            artifacts = int(
                conn.execute(
                    "SELECT COUNT(*) FROM artifacts WHERE project_id = ?", (project_id,)
                ).fetchone()[0]
            )
            artifact_verifications = int(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications v
                       JOIN artifacts a ON a.id = v.target_id
                       WHERE v.target_type = 'ARTIFACT' AND a.project_id = ?""",
                    (project_id,),
                ).fetchone()[0]
            )
        return {
            "decisions": decisions,
            "changes": changes,
            "artifacts": artifacts,
            "artifact_verifications": artifact_verifications,
        }

    def list_decisions(self, *, limit: int = 256) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT id, goal_id, task_id, title, decision, rationale, status,
                          supersedes_decision_id, created_at
                   FROM decisions WHERE project_id = ?
                   ORDER BY created_at, rowid LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(_decision(row) for row in rows)

    def list_changes(self, *, limit: int = 512) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT c.id, c.task_id, c.decision_id, c.run_id, c.summary,
                          c.change_type, c.before_ref, c.after_ref, c.status, c.created_at
                   FROM changes c
                   JOIN tasks t ON t.id = c.task_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE g.project_id = ?
                   ORDER BY c.created_at, c.rowid LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(_change(row) for row in rows)

    def list_artifacts(self, *, limit: int = 512) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT id, change_id, type, path_or_uri, content_hash,
                          parent_artifact_id, created_by_run_id, model_id, status, created_at
                   FROM artifacts WHERE project_id = ?
                   ORDER BY created_at, rowid LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(_artifact(row) for row in rows)

    def list_artifact_verifications(
        self, *, limit: int = 1024
    ) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT v.id, v.target_id, v.verification_type, v.verifier,
                          v.status, v.run_id, v.created_at
                   FROM verifications v
                   JOIN artifacts a ON a.id = v.target_id
                   WHERE v.target_type = 'ARTIFACT' AND a.project_id = ?
                   ORDER BY v.created_at, v.rowid LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(
            {
                "id": row["id"],
                "target_type": "ARTIFACT",
                "target_id": row["target_id"],
                "verification_type": row["verification_type"],
                "verifier": row["verifier"],
                "status": row["status"],
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "evidence_disclosed": False,
                "metrics_disclosed": False,
            }
            for row in rows
        )

    def get_decision(self, decision_id: str) -> dict[str, object]:
        if not validate_id(decision_id, IdKind.DECISION):
            raise KeyError(decision_id)
        with self.runtime.store.session() as conn:
            row = conn.execute(
                """SELECT id, goal_id, task_id, title, decision, rationale, status,
                          supersedes_decision_id, created_at
                   FROM decisions WHERE id = ? AND project_id = ?""",
                (decision_id, self.project_id),
            ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return _decision(row)

    def get_change(self, change_id: str) -> dict[str, object]:
        if not validate_id(change_id, IdKind.CHANGE):
            raise KeyError(change_id)
        with self.runtime.store.session() as conn:
            row = conn.execute(
                """SELECT c.id, c.task_id, c.decision_id, c.run_id, c.summary,
                          c.change_type, c.before_ref, c.after_ref, c.status, c.created_at
                   FROM changes c
                   JOIN tasks t ON t.id = c.task_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE c.id = ? AND g.project_id = ?""",
                (change_id, self.project_id),
            ).fetchone()
        if row is None:
            raise KeyError(change_id)
        return _change(row)

    def get_artifact(self, artifact_id: str) -> dict[str, object]:
        if not validate_id(artifact_id, IdKind.ARTIFACT):
            raise KeyError(artifact_id)
        with self.runtime.store.session() as conn:
            row = conn.execute(
                """SELECT id, change_id, type, path_or_uri, content_hash,
                          parent_artifact_id, created_by_run_id, model_id, status, created_at
                   FROM artifacts WHERE id = ? AND project_id = ?""",
                (artifact_id, self.project_id),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return _artifact(row)
