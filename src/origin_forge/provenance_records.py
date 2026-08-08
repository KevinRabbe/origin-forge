from __future__ import annotations

import json
import sqlite3
from typing import Any

from .provenance_models import (
    ProvenanceRecordRef,
    ProvenanceRecordType,
    canonical_hash,
)
from .runtime import OriginForgeRuntime


class ProvenanceRecordError(RuntimeError):
    pass


def _normalized_row(row: sqlite3.Row) -> dict[str, object]:
    value: dict[str, object] = {}
    for key in row.keys():
        item = row[key]
        if key.endswith("_json"):
            if not isinstance(item, str):
                raise ProvenanceRecordError(f"durable JSON field {key} is not text")
            try:
                item = json.loads(item)
            except json.JSONDecodeError as exc:
                raise ProvenanceRecordError(f"durable JSON field {key} is invalid") from exc
        value[key] = item
    return value


class ProvenanceRecordResolver:
    """Read exact project-owned durable records into hash-pinned provenance refs."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.project_id = runtime.project_id()

    def _owned_row(
        self,
        conn: sqlite3.Connection,
        record_type: ProvenanceRecordType,
        record_id: str,
    ) -> sqlite3.Row:
        if record_type == ProvenanceRecordType.PROJECT:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ? AND id = ?",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.ENTITY:
            row = conn.execute(
                "SELECT * FROM entities WHERE id = ? AND project_id = ?",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.DESIGN_RULE:
            row = conn.execute(
                "SELECT * FROM design_rules WHERE id = ? AND project_id = ?",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.GOAL:
            row = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.FLOW:
            row = conn.execute(
                """SELECT f.* FROM flows f JOIN goals g ON g.id = f.goal_id
                   WHERE f.id = ? AND g.project_id = ?""",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.TASK:
            row = conn.execute(
                """SELECT t.* FROM tasks t JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE t.id = ? AND g.project_id = ?""",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.RUN:
            row = conn.execute(
                """SELECT r.* FROM runs r JOIN tasks t ON t.id = r.task_id
                   JOIN flows f ON f.id = t.flow_id JOIN goals g ON g.id = f.goal_id
                   WHERE r.id = ? AND g.project_id = ?""",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.DECISION:
            row = conn.execute(
                "SELECT * FROM decisions WHERE id = ? AND project_id = ?",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.CHANGE:
            row = conn.execute(
                """SELECT c.* FROM changes c JOIN tasks t ON t.id = c.task_id
                   JOIN flows f ON f.id = t.flow_id JOIN goals g ON g.id = f.goal_id
                   WHERE c.id = ? AND g.project_id = ?""",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.ARTIFACT:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
                (record_id, self.project_id),
            ).fetchone()
        elif record_type == ProvenanceRecordType.VERIFICATION:
            row = conn.execute(
                "SELECT * FROM verifications WHERE id = ?", (record_id,)
            ).fetchone()
            if row is not None and not self._verification_owned(conn, row):
                row = None
        else:
            raise ProvenanceRecordError(f"unsupported provenance record type: {record_type}")
        if row is None:
            raise KeyError(record_id)
        return row

    def _verification_owned(self, conn: sqlite3.Connection, verification: sqlite3.Row) -> bool:
        target_type = str(verification["target_type"]).upper()
        target_id = verification["target_id"]
        if target_type == "PROJECT":
            return target_id == self.project_id
        if target_type == "GOAL":
            row = conn.execute("SELECT project_id FROM goals WHERE id = ?", (target_id,)).fetchone()
        elif target_type == "FLOW":
            row = conn.execute(
                "SELECT g.project_id FROM flows f JOIN goals g ON g.id = f.goal_id WHERE f.id = ?",
                (target_id,),
            ).fetchone()
        elif target_type == "TASK":
            row = conn.execute(
                """SELECT g.project_id FROM tasks t JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id WHERE t.id = ?""",
                (target_id,),
            ).fetchone()
        elif target_type == "RUN":
            row = conn.execute(
                """SELECT g.project_id FROM runs r JOIN tasks t ON t.id = r.task_id
                   JOIN flows f ON f.id = t.flow_id JOIN goals g ON g.id = f.goal_id
                   WHERE r.id = ?""",
                (target_id,),
            ).fetchone()
        elif target_type == "ARTIFACT":
            row = conn.execute(
                "SELECT project_id FROM artifacts WHERE id = ?", (target_id,)
            ).fetchone()
        elif target_type == "WORKSPACE":
            row = conn.execute(
                "SELECT project_id FROM workspaces WHERE id = ?", (target_id,)
            ).fetchone()
        elif target_type == "CHANGE":
            row = conn.execute(
                """SELECT g.project_id FROM changes c JOIN tasks t ON t.id = c.task_id
                   JOIN flows f ON f.id = t.flow_id JOIN goals g ON g.id = f.goal_id
                   WHERE c.id = ?""",
                (target_id,),
            ).fetchone()
        else:
            return False
        return row is not None and row["project_id"] == self.project_id

    def resolve(
        self,
        record_type: ProvenanceRecordType,
        record_id: str,
    ) -> ProvenanceRecordRef:
        if not isinstance(record_type, ProvenanceRecordType):
            raise TypeError("record_type must be a ProvenanceRecordType")
        with self.runtime.store.session() as conn:
            row = self._owned_row(conn, record_type, record_id)
            normalized = _normalized_row(row)
        revision = normalized.get("revision")
        if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool)):
            raise ProvenanceRecordError("durable record revision is invalid")
        return ProvenanceRecordRef(
            record_type=record_type,
            record_id=record_id,
            record_hash=canonical_hash(
                {"record_type": record_type.value, "record": normalized}
            ),
            revision=revision,
        )

    def current_matches(self, ref: ProvenanceRecordRef) -> bool:
        if not isinstance(ref, ProvenanceRecordRef):
            raise TypeError("ref must be a ProvenanceRecordRef")
        try:
            current = self.resolve(ref.record_type, ref.record_id)
        except KeyError:
            return False
        return current == ref

    def normalized_snapshot(
        self,
        record_type: ProvenanceRecordType,
        record_id: str,
    ) -> dict[str, Any]:
        with self.runtime.store.session() as conn:
            return _normalized_row(self._owned_row(conn, record_type, record_id))
