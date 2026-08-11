from __future__ import annotations

import json
from typing import Any

from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime


_MAX_READ_LIMIT = 10_000
_MAX_SCOPES = 256


class ProjectIntelligenceReadError(RuntimeError):
    pass


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_READ_LIMIT:
        raise ValueError(f"Project Intelligence read limit must be 1..{_MAX_READ_LIMIT}")
    return value


def _scope_ids(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, str):
        raise ProjectIntelligenceReadError("Design Rule scope evidence is not JSON text")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectIntelligenceReadError("Design Rule scope evidence is invalid JSON") from exc
    if (
        not isinstance(value, list)
        or len(value) > _MAX_SCOPES
        or not all(isinstance(item, str) and validate_id(item, IdKind.ENTITY) for item in value)
        or len(value) != len(set(value))
    ):
        raise ProjectIntelligenceReadError("Design Rule scope evidence is malformed")
    return tuple(value)


class ProjectIntelligenceReadService:
    """SELECT-only bounded Phase-17 projection for human inspection.

    The mutable ProjectIntelligenceService remains the canonical write surface.
    This facade intentionally exposes no create/update/retire/supersede methods.
    """

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    @property
    def project_id(self) -> str:
        return self.runtime.project_id()

    def counts(self) -> dict[str, int]:
        project_id = self.project_id
        with self.runtime.store.session() as conn:
            return {
                "entities": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM entities WHERE project_id = ?",
                        (project_id,),
                    ).fetchone()[0]
                ),
                "relations": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM entity_relations WHERE project_id = ?",
                        (project_id,),
                    ).fetchone()[0]
                ),
                "bindings": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM entity_bindings WHERE project_id = ?",
                        (project_id,),
                    ).fetchone()[0]
                ),
                "design_rules": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM design_rules WHERE project_id = ?",
                        (project_id,),
                    ).fetchone()[0]
                ),
            }

    def list_entities(self, *, limit: int = 256) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT id, kind, name, description, status, revision,
                          created_at, updated_at
                   FROM entities WHERE project_id = ?
                   ORDER BY kind, name, id LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(
            {
                "id": row["id"],
                "kind": row["kind"],
                "name": row["name"],
                "description": row["description"],
                "status": row["status"],
                "revision": int(row["revision"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        )

    def get_entity(self, entity_id: str) -> dict[str, object]:
        if not validate_id(entity_id, IdKind.ENTITY):
            raise KeyError(entity_id)
        with self.runtime.store.session() as conn:
            row = conn.execute(
                """SELECT id, kind, name, description, status, revision,
                          created_at, updated_at
                   FROM entities WHERE id = ? AND project_id = ?""",
                (entity_id, self.project_id),
            ).fetchone()
        if row is None:
            raise KeyError(entity_id)
        return {
            "id": row["id"],
            "kind": row["kind"],
            "name": row["name"],
            "description": row["description"],
            "status": row["status"],
            "revision": int(row["revision"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_relations(self, *, limit: int = 512) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT id, source_entity_id, relation_type, target_entity_id,
                          status, revision, rationale, created_at, updated_at
                   FROM entity_relations WHERE project_id = ?
                   ORDER BY relation_type, source_entity_id, target_entity_id, id LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(
            {
                "id": row["id"],
                "source_entity_id": row["source_entity_id"],
                "relation_type": row["relation_type"],
                "target_entity_id": row["target_entity_id"],
                "status": row["status"],
                "revision": int(row["revision"]),
                "rationale": row["rationale"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "evidence_refs_disclosed": False,
            }
            for row in rows
        )

    def list_bindings(self, *, limit: int = 512) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT id, entity_id, binding_type, target_ref, target_hash,
                          status, revision, created_at, updated_at
                   FROM entity_bindings WHERE project_id = ?
                   ORDER BY entity_id, binding_type, target_ref, id LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(
            {
                "id": row["id"],
                "entity_id": row["entity_id"],
                "binding_type": row["binding_type"],
                "target_ref": row["target_ref"],
                "target_hash": row["target_hash"],
                "status": row["status"],
                "revision": int(row["revision"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metadata_disclosed": False,
            }
            for row in rows
        )

    def list_design_rules(self, *, limit: int = 256) -> tuple[dict[str, object], ...]:
        limit = _limit(limit)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT id, category, title, statement, rationale, authority,
                          scope_entity_ids_json, status, revision, supersedes_rule_id,
                          created_at, updated_at
                   FROM design_rules WHERE project_id = ?
                   ORDER BY category, title, id LIMIT ?""",
                (self.project_id, limit),
            ).fetchall()
        return tuple(
            {
                "id": row["id"],
                "category": row["category"],
                "title": row["title"],
                "statement": row["statement"],
                "rationale": row["rationale"],
                "authority": row["authority"],
                "scope_entity_ids": _scope_ids(row["scope_entity_ids_json"]),
                "status": row["status"],
                "revision": int(row["revision"]),
                "supersedes_rule_id": row["supersedes_rule_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        )

    def get_design_rule(self, rule_id: str) -> dict[str, object]:
        if not validate_id(rule_id, IdKind.DESIGN_RULE):
            raise KeyError(rule_id)
        with self.runtime.store.session() as conn:
            row = conn.execute(
                """SELECT id, category, title, statement, rationale, authority,
                          scope_entity_ids_json, status, revision, supersedes_rule_id,
                          created_at, updated_at
                   FROM design_rules WHERE id = ? AND project_id = ?""",
                (rule_id, self.project_id),
            ).fetchone()
        if row is None:
            raise KeyError(rule_id)
        return {
            "id": row["id"],
            "category": row["category"],
            "title": row["title"],
            "statement": row["statement"],
            "rationale": row["rationale"],
            "authority": row["authority"],
            "scope_entity_ids": _scope_ids(row["scope_entity_ids_json"]),
            "status": row["status"],
            "revision": int(row["revision"]),
            "supersedes_rule_id": row["supersedes_rule_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
