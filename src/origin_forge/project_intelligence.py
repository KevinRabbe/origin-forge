from __future__ import annotations

import json
import sqlite3
from collections import deque
from typing import Any, Iterable

from .ids import IdKind, new_id, validate_id
from .path_policy import portable_relative_path
from .project_models import (
    BindingStatus,
    BindingType,
    DesignRuleAuthority,
    DesignRuleCategory,
    DesignRuleStatus,
    EntityKind,
    EntityStatus,
    ImpactDirection,
    ImpactEntity,
    ImpactQuery,
    ImpactReport,
    RelationStatus,
    RelationType,
    bounded_metadata,
    bounded_text,
    validate_sha256,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


class ProjectIntelligenceError(RuntimeError):
    pass


_EVIDENCE_KINDS = (
    IdKind.DECISION,
    IdKind.ARTIFACT,
    IdKind.TASK,
    IdKind.VERIFICATION,
    IdKind.RUN,
)
_MAX_EVIDENCE_REFS = 256
_MAX_SCOPES = 256


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _require_enum(value, enum_type, field: str):
    if not isinstance(value, enum_type):
        raise ValueError(f"{field} must be a {enum_type.__name__}")
    return value


class ProjectIntelligenceService:
    """Governed semantic project state over the existing Origin Forge database.

    This service contains no model adapter, source mutation, Task completion, or
    merge authority. Models may consume its read-only results elsewhere, but
    canonical project intelligence is created through this infrastructure API.
    """

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    @property
    def project_id(self) -> str:
        return self.runtime.project_id()

    def _append_event(
        self,
        conn: sqlite3.Connection,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        old_state: str | None,
        new_state: str | None,
        revision: int | None,
        metadata: dict[str, Any],
        now: str,
        *,
        actor_type: str,
        actor_id: str | None,
    ) -> None:
        self.runtime.store._append_event(
            conn,
            aggregate_type,
            aggregate_id,
            event_type,
            old_state,
            new_state,
            revision,
            actor_type,
            actor_id,
            metadata,
            now,
        )

    def _entity_row(self, conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row:
        if not validate_id(entity_id, IdKind.ENTITY):
            raise ValueError(f"invalid Entity ID: {entity_id}")
        row = conn.execute(
            "SELECT * FROM entities WHERE id = ? AND project_id = ?",
            (entity_id, self.project_id),
        ).fetchone()
        if row is None:
            raise KeyError(entity_id)
        return row

    def get_entity(self, entity_id: str) -> dict[str, Any]:
        with self.runtime.store.session() as conn:
            return _row(self._entity_row(conn, entity_id))

    def list_entities(
        self,
        *,
        kind: EntityKind | None = None,
        status: EntityStatus | None = None,
    ) -> list[dict[str, Any]]:
        params: list[object] = [self.project_id]
        sql = "SELECT * FROM entities WHERE project_id = ?"
        if kind is not None:
            _require_enum(kind, EntityKind, "kind")
            sql += " AND kind = ?"
            params.append(kind.value)
        if status is not None:
            _require_enum(status, EntityStatus, "status")
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY kind, name, id"
        with self.runtime.store.session() as conn:
            return [_row(row) for row in conn.execute(sql, params)]

    def create_entity(
        self,
        kind: EntityKind,
        name: str,
        *,
        description: str = "",
        metadata: dict[str, object] | None = None,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> str:
        _require_enum(kind, EntityKind, "kind")
        name = bounded_text(name, field="Entity name", maximum=512)
        description = bounded_text(
            description,
            field="Entity description",
            allow_empty=True,
        )
        metadata_value = bounded_metadata(metadata)
        entity_id = new_id(IdKind.ENTITY)
        now = utc_now()
        with self.runtime.store.session() as conn:
            conn.execute(
                """INSERT INTO entities(
                       id, project_id, kind, name, description, status, revision,
                       metadata_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?, ?)""",
                (
                    entity_id,
                    self.project_id,
                    kind.value,
                    name,
                    description,
                    _json(metadata_value),
                    now,
                    now,
                ),
            )
            self._append_event(
                conn,
                "ENTITY",
                entity_id,
                "ENTITY_CREATED",
                None,
                EntityStatus.ACTIVE.value,
                0,
                {"kind": kind.value, "name": name},
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        return entity_id

    def update_entity(
        self,
        entity_id: str,
        *,
        expected_revision: int,
        kind: EntityKind | None = None,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, object] | None = None,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> int:
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        if kind is not None:
            _require_enum(kind, EntityKind, "kind")
        if name is not None:
            name = bounded_text(name, field="Entity name", maximum=512)
        if description is not None:
            description = bounded_text(
                description,
                field="Entity description",
                allow_empty=True,
            )
        metadata_value = None if metadata is None else bounded_metadata(metadata)
        if kind is None and name is None and description is None and metadata_value is None:
            raise ValueError("Entity update requires at least one changed field")
        now = utc_now()
        with self.runtime.store.session() as conn:
            current = self._entity_row(conn, entity_id)
            actual = int(current["revision"])
            if actual != expected_revision:
                raise StaleRevision(
                    f"entity {entity_id} revision {actual} != expected {expected_revision}"
                )
            new_revision = actual + 1
            cursor = conn.execute(
                """UPDATE entities SET
                       kind = ?, name = ?, description = ?, metadata_json = ?,
                       revision = ?, updated_at = ?
                   WHERE id = ? AND project_id = ? AND revision = ?""",
                (
                    kind.value if kind is not None else current["kind"],
                    name if name is not None else current["name"],
                    description if description is not None else current["description"],
                    _json(metadata_value) if metadata_value is not None else current["metadata_json"],
                    new_revision,
                    now,
                    entity_id,
                    self.project_id,
                    actual,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(f"entity {entity_id} changed concurrently")
            self._append_event(
                conn,
                "ENTITY",
                entity_id,
                "ENTITY_UPDATED",
                current["status"],
                current["status"],
                new_revision,
                {
                    "kind": kind.value if kind is not None else current["kind"],
                    "name": name if name is not None else current["name"],
                },
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            return new_revision

    def set_entity_status(
        self,
        entity_id: str,
        status: EntityStatus,
        *,
        expected_revision: int,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> int:
        _require_enum(status, EntityStatus, "status")
        now = utc_now()
        with self.runtime.store.session() as conn:
            current = self._entity_row(conn, entity_id)
            actual = int(current["revision"])
            if actual != expected_revision:
                raise StaleRevision(
                    f"entity {entity_id} revision {actual} != expected {expected_revision}"
                )
            if current["status"] == status.value:
                raise ValueError("Entity already has requested status")
            new_revision = actual + 1
            cursor = conn.execute(
                "UPDATE entities SET status = ?, revision = ?, updated_at = ? WHERE id = ? AND project_id = ? AND revision = ?",
                (status.value, new_revision, now, entity_id, self.project_id, actual),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(f"entity {entity_id} changed concurrently")
            self._append_event(
                conn,
                "ENTITY",
                entity_id,
                "ENTITY_STATUS_CHANGED",
                current["status"],
                status.value,
                new_revision,
                {},
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            return new_revision

    def _validate_owned_ref(self, conn: sqlite3.Connection, target_ref: str, binding_type: BindingType) -> None:
        if binding_type == BindingType.ARTIFACT:
            if not validate_id(target_ref, IdKind.ARTIFACT):
                raise ValueError("ARTIFACT binding target must be an ART ID")
            row = conn.execute(
                "SELECT project_id FROM artifacts WHERE id = ?", (target_ref,)
            ).fetchone()
            if row is None or row["project_id"] != self.project_id:
                raise ProjectIntelligenceError("ARTIFACT binding target is unavailable in this project")
            return
        if binding_type == BindingType.DECISION:
            if not validate_id(target_ref, IdKind.DECISION):
                raise ValueError("DECISION binding target must be a DEC ID")
            row = conn.execute(
                "SELECT project_id FROM decisions WHERE id = ?", (target_ref,)
            ).fetchone()
            if row is None or row["project_id"] != self.project_id:
                raise ProjectIntelligenceError("DECISION binding target is unavailable in this project")
            return
        if binding_type == BindingType.TASK:
            if not validate_id(target_ref, IdKind.TASK):
                raise ValueError("TASK binding target must be a TASK ID")
            row = conn.execute(
                """SELECT g.project_id FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE t.id = ?""",
                (target_ref,),
            ).fetchone()
            if row is None or row["project_id"] != self.project_id:
                raise ProjectIntelligenceError("TASK binding target is unavailable in this project")
            return
        if binding_type == BindingType.VERIFICATION:
            if not validate_id(target_ref, IdKind.VERIFICATION):
                raise ValueError("VERIFICATION binding target must be a VERIFY ID")
            verification = conn.execute(
                "SELECT target_type, target_id FROM verifications WHERE id = ?",
                (target_ref,),
            ).fetchone()
            if verification is None:
                raise ProjectIntelligenceError("VERIFICATION binding target is unavailable")
            self._validate_verification_owner(conn, verification["target_type"], verification["target_id"])
            return
        raise AssertionError(binding_type)

    def _validate_verification_owner(self, conn: sqlite3.Connection, target_type: str, target_id: str) -> None:
        kind = target_type.upper()
        if kind == "GOAL":
            row = conn.execute("SELECT project_id FROM goals WHERE id = ?", (target_id,)).fetchone()
        elif kind == "FLOW":
            row = conn.execute(
                "SELECT g.project_id FROM flows f JOIN goals g ON g.id = f.goal_id WHERE f.id = ?",
                (target_id,),
            ).fetchone()
        elif kind == "TASK":
            row = conn.execute(
                """SELECT g.project_id FROM tasks t JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id WHERE t.id = ?""",
                (target_id,),
            ).fetchone()
        elif kind == "RUN":
            row = conn.execute(
                """SELECT g.project_id FROM runs r JOIN tasks t ON t.id = r.task_id
                   JOIN flows f ON f.id = t.flow_id JOIN goals g ON g.id = f.goal_id
                   WHERE r.id = ?""",
                (target_id,),
            ).fetchone()
        else:
            raise ProjectIntelligenceError(
                f"VERIFICATION target type cannot be project-scoped: {target_type}"
            )
        if row is None or row["project_id"] != self.project_id:
            raise ProjectIntelligenceError("VERIFICATION binding target belongs to another project")

    def _validate_evidence_refs(self, conn: sqlite3.Connection, refs: Iterable[str]) -> tuple[str, ...]:
        values = tuple(refs)
        if len(values) > _MAX_EVIDENCE_REFS or len(values) != len(set(values)):
            raise ValueError("relation evidence refs are duplicate or exceed item limit")
        for ref in values:
            matched = next((kind for kind in _EVIDENCE_KINDS if validate_id(ref, kind)), None)
            if matched is None:
                raise ValueError(f"unsupported relation evidence ref: {ref}")
            if matched == IdKind.DECISION:
                self._validate_owned_ref(conn, ref, BindingType.DECISION)
            elif matched == IdKind.ARTIFACT:
                self._validate_owned_ref(conn, ref, BindingType.ARTIFACT)
            elif matched == IdKind.TASK:
                self._validate_owned_ref(conn, ref, BindingType.TASK)
            elif matched == IdKind.VERIFICATION:
                self._validate_owned_ref(conn, ref, BindingType.VERIFICATION)
            elif matched == IdKind.RUN:
                row = conn.execute(
                    """SELECT g.project_id FROM runs r JOIN tasks t ON t.id = r.task_id
                       JOIN flows f ON f.id = t.flow_id JOIN goals g ON g.id = f.goal_id
                       WHERE r.id = ?""",
                    (ref,),
                ).fetchone()
                if row is None or row["project_id"] != self.project_id:
                    raise ProjectIntelligenceError("RUN evidence ref is unavailable in this project")
        return tuple(sorted(values))

    def create_relation(
        self,
        source_entity_id: str,
        relation_type: RelationType,
        target_entity_id: str,
        *,
        rationale: str = "",
        evidence_refs: Iterable[str] = (),
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> str:
        _require_enum(relation_type, RelationType, "relation_type")
        if source_entity_id == target_entity_id:
            raise ValueError("self Entity relations are not supported in Phase 17 v0")
        rationale = bounded_text(rationale, field="relation rationale", allow_empty=True)
        relation_id = new_id(IdKind.ENTITY_RELATION)
        now = utc_now()
        with self.runtime.store.session() as conn:
            self._entity_row(conn, source_entity_id)
            self._entity_row(conn, target_entity_id)
            refs = self._validate_evidence_refs(conn, evidence_refs)
            try:
                conn.execute(
                    """INSERT INTO entity_relations(
                           id, project_id, source_entity_id, relation_type,
                           target_entity_id, status, revision, rationale,
                           evidence_refs_json, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?, ?, ?)""",
                    (
                        relation_id,
                        self.project_id,
                        source_entity_id,
                        relation_type.value,
                        target_entity_id,
                        rationale,
                        _json(list(refs)),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectIntelligenceError(
                    "duplicate or invalid active Entity relation"
                ) from exc
            self._append_event(
                conn,
                "ENTITY_RELATION",
                relation_id,
                "ENTITY_RELATION_CREATED",
                None,
                RelationStatus.ACTIVE.value,
                0,
                {
                    "source_entity_id": source_entity_id,
                    "relation_type": relation_type.value,
                    "target_entity_id": target_entity_id,
                },
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        return relation_id

    def _relation_row(self, conn: sqlite3.Connection, relation_id: str) -> sqlite3.Row:
        if not validate_id(relation_id, IdKind.ENTITY_RELATION):
            raise ValueError(f"invalid Entity relation ID: {relation_id}")
        row = conn.execute(
            "SELECT * FROM entity_relations WHERE id = ? AND project_id = ?",
            (relation_id, self.project_id),
        ).fetchone()
        if row is None:
            raise KeyError(relation_id)
        return row

    def get_relation(self, relation_id: str) -> dict[str, Any]:
        with self.runtime.store.session() as conn:
            return _row(self._relation_row(conn, relation_id))

    def list_relations(
        self,
        *,
        entity_id: str | None = None,
        status: RelationStatus | None = None,
    ) -> list[dict[str, Any]]:
        params: list[object] = [self.project_id]
        sql = "SELECT * FROM entity_relations WHERE project_id = ?"
        if entity_id is not None:
            self.get_entity(entity_id)
            sql += " AND (source_entity_id = ? OR target_entity_id = ?)"
            params.extend((entity_id, entity_id))
        if status is not None:
            _require_enum(status, RelationStatus, "status")
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY relation_type, source_entity_id, target_entity_id, id"
        with self.runtime.store.session() as conn:
            return [_row(row) for row in conn.execute(sql, params)]

    def retire_relation(
        self,
        relation_id: str,
        *,
        expected_revision: int,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> int:
        return self._retire_simple(
            table="entity_relations",
            aggregate_type="ENTITY_RELATION",
            aggregate_id=relation_id,
            id_kind=IdKind.ENTITY_RELATION,
            expected_revision=expected_revision,
            event_type="ENTITY_RELATION_RETIRED",
            actor_type=actor_type,
            actor_id=actor_id,
        )

    def create_binding(
        self,
        entity_id: str,
        binding_type: BindingType,
        target_ref: str,
        *,
        target_hash: str | None = None,
        metadata: dict[str, object] | None = None,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> str:
        _require_enum(binding_type, BindingType, "binding_type")
        target_ref = bounded_text(target_ref, field="binding target_ref", maximum=4096)
        target_hash = validate_sha256(target_hash, field="binding target_hash")
        metadata_value = bounded_metadata(metadata)
        if binding_type == BindingType.FILE:
            target_ref = portable_relative_path(target_ref).as_posix()
        binding_id = new_id(IdKind.ENTITY_BINDING)
        now = utc_now()
        with self.runtime.store.session() as conn:
            self._entity_row(conn, entity_id)
            if binding_type in {
                BindingType.ARTIFACT,
                BindingType.DECISION,
                BindingType.TASK,
                BindingType.VERIFICATION,
            }:
                self._validate_owned_ref(conn, target_ref, binding_type)
            try:
                conn.execute(
                    """INSERT INTO entity_bindings(
                           id, project_id, entity_id, binding_type, target_ref,
                           target_hash, metadata_json, status, revision,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?)""",
                    (
                        binding_id,
                        self.project_id,
                        entity_id,
                        binding_type.value,
                        target_ref,
                        target_hash,
                        _json(metadata_value),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectIntelligenceError(
                    "duplicate or invalid active Entity binding"
                ) from exc
            self._append_event(
                conn,
                "ENTITY_BINDING",
                binding_id,
                "ENTITY_BINDING_CREATED",
                None,
                BindingStatus.ACTIVE.value,
                0,
                {
                    "entity_id": entity_id,
                    "binding_type": binding_type.value,
                    "target_ref": target_ref,
                },
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        return binding_id

    def _binding_row(self, conn: sqlite3.Connection, binding_id: str) -> sqlite3.Row:
        if not validate_id(binding_id, IdKind.ENTITY_BINDING):
            raise ValueError(f"invalid Entity binding ID: {binding_id}")
        row = conn.execute(
            "SELECT * FROM entity_bindings WHERE id = ? AND project_id = ?",
            (binding_id, self.project_id),
        ).fetchone()
        if row is None:
            raise KeyError(binding_id)
        return row

    def get_binding(self, binding_id: str) -> dict[str, Any]:
        with self.runtime.store.session() as conn:
            return _row(self._binding_row(conn, binding_id))

    def list_bindings(
        self,
        *,
        entity_id: str | None = None,
        status: BindingStatus | None = None,
    ) -> list[dict[str, Any]]:
        params: list[object] = [self.project_id]
        sql = "SELECT * FROM entity_bindings WHERE project_id = ?"
        if entity_id is not None:
            self.get_entity(entity_id)
            sql += " AND entity_id = ?"
            params.append(entity_id)
        if status is not None:
            _require_enum(status, BindingStatus, "status")
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY entity_id, binding_type, target_ref, id"
        with self.runtime.store.session() as conn:
            return [_row(row) for row in conn.execute(sql, params)]

    def retire_binding(
        self,
        binding_id: str,
        *,
        expected_revision: int,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> int:
        return self._retire_simple(
            table="entity_bindings",
            aggregate_type="ENTITY_BINDING",
            aggregate_id=binding_id,
            id_kind=IdKind.ENTITY_BINDING,
            expected_revision=expected_revision,
            event_type="ENTITY_BINDING_RETIRED",
            actor_type=actor_type,
            actor_id=actor_id,
        )

    def create_design_rule(
        self,
        category: DesignRuleCategory,
        title: str,
        statement: str,
        authority: DesignRuleAuthority,
        *,
        rationale: str = "",
        scope_entity_ids: Iterable[str] = (),
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> str:
        return self._insert_design_rule(
            category,
            title,
            statement,
            authority,
            rationale=rationale,
            scope_entity_ids=scope_entity_ids,
            supersedes_rule_id=None,
            actor_type=actor_type,
            actor_id=actor_id,
        )

    def _validated_scopes(self, conn: sqlite3.Connection, scope_entity_ids: Iterable[str]) -> tuple[str, ...]:
        scopes = tuple(scope_entity_ids)
        if len(scopes) > _MAX_SCOPES or len(scopes) != len(set(scopes)):
            raise ValueError("Design Rule scopes are duplicate or exceed item limit")
        for entity_id in scopes:
            self._entity_row(conn, entity_id)
        return tuple(sorted(scopes))

    def _insert_design_rule(
        self,
        category: DesignRuleCategory,
        title: str,
        statement: str,
        authority: DesignRuleAuthority,
        *,
        rationale: str,
        scope_entity_ids: Iterable[str],
        supersedes_rule_id: str | None,
        actor_type: str,
        actor_id: str | None,
    ) -> str:
        _require_enum(category, DesignRuleCategory, "category")
        _require_enum(authority, DesignRuleAuthority, "authority")
        title = bounded_text(title, field="Design Rule title", maximum=512)
        statement = bounded_text(statement, field="Design Rule statement")
        rationale = bounded_text(rationale, field="Design Rule rationale", allow_empty=True)
        rule_id = new_id(IdKind.DESIGN_RULE)
        now = utc_now()
        with self.runtime.store.session() as conn:
            scopes = self._validated_scopes(conn, scope_entity_ids)
            conn.execute(
                """INSERT INTO design_rules(
                       id, project_id, category, title, statement, rationale,
                       authority, scope_entity_ids_json, status, revision,
                       supersedes_rule_id, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?, ?)""",
                (
                    rule_id,
                    self.project_id,
                    category.value,
                    title,
                    statement,
                    rationale,
                    authority.value,
                    _json(list(scopes)),
                    supersedes_rule_id,
                    now,
                    now,
                ),
            )
            self._append_event(
                conn,
                "DESIGN_RULE",
                rule_id,
                "DESIGN_RULE_CREATED",
                None,
                DesignRuleStatus.ACTIVE.value,
                0,
                {
                    "category": category.value,
                    "authority": authority.value,
                    "scope_entity_ids": list(scopes),
                    "supersedes_rule_id": supersedes_rule_id,
                },
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        return rule_id

    def _rule_row(self, conn: sqlite3.Connection, rule_id: str) -> sqlite3.Row:
        if not validate_id(rule_id, IdKind.DESIGN_RULE):
            raise ValueError(f"invalid Design Rule ID: {rule_id}")
        row = conn.execute(
            "SELECT * FROM design_rules WHERE id = ? AND project_id = ?",
            (rule_id, self.project_id),
        ).fetchone()
        if row is None:
            raise KeyError(rule_id)
        return row

    def get_design_rule(self, rule_id: str) -> dict[str, Any]:
        with self.runtime.store.session() as conn:
            return _row(self._rule_row(conn, rule_id))

    def list_design_rules(
        self,
        *,
        status: DesignRuleStatus | None = None,
        category: DesignRuleCategory | None = None,
    ) -> list[dict[str, Any]]:
        params: list[object] = [self.project_id]
        sql = "SELECT * FROM design_rules WHERE project_id = ?"
        if status is not None:
            _require_enum(status, DesignRuleStatus, "status")
            sql += " AND status = ?"
            params.append(status.value)
        if category is not None:
            _require_enum(category, DesignRuleCategory, "category")
            sql += " AND category = ?"
            params.append(category.value)
        sql += " ORDER BY category, title, id"
        with self.runtime.store.session() as conn:
            return [_row(row) for row in conn.execute(sql, params)]

    def supersede_design_rule(
        self,
        rule_id: str,
        *,
        expected_revision: int,
        category: DesignRuleCategory,
        title: str,
        statement: str,
        authority: DesignRuleAuthority,
        rationale: str = "",
        scope_entity_ids: Iterable[str] = (),
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> str:
        _require_enum(category, DesignRuleCategory, "category")
        _require_enum(authority, DesignRuleAuthority, "authority")
        title = bounded_text(title, field="Design Rule title", maximum=512)
        statement = bounded_text(statement, field="Design Rule statement")
        rationale = bounded_text(rationale, field="Design Rule rationale", allow_empty=True)
        new_rule_id = new_id(IdKind.DESIGN_RULE)
        now = utc_now()
        with self.runtime.store.session() as conn:
            current = self._rule_row(conn, rule_id)
            actual = int(current["revision"])
            if actual != expected_revision:
                raise StaleRevision(
                    f"Design Rule {rule_id} revision {actual} != expected {expected_revision}"
                )
            if current["status"] != DesignRuleStatus.ACTIVE.value:
                raise ProjectIntelligenceError("only an ACTIVE Design Rule may be superseded")
            scopes = self._validated_scopes(conn, scope_entity_ids)
            conn.execute(
                """INSERT INTO design_rules(
                       id, project_id, category, title, statement, rationale,
                       authority, scope_entity_ids_json, status, revision,
                       supersedes_rule_id, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?, ?)""",
                (
                    new_rule_id,
                    self.project_id,
                    category.value,
                    title,
                    statement,
                    rationale,
                    authority.value,
                    _json(list(scopes)),
                    rule_id,
                    now,
                    now,
                ),
            )
            new_revision = actual + 1
            cursor = conn.execute(
                """UPDATE design_rules SET status = 'SUPERSEDED', revision = ?, updated_at = ?
                   WHERE id = ? AND project_id = ? AND revision = ?""",
                (new_revision, now, rule_id, self.project_id, actual),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(f"Design Rule {rule_id} changed concurrently")
            self._append_event(
                conn,
                "DESIGN_RULE",
                rule_id,
                "DESIGN_RULE_SUPERSEDED",
                DesignRuleStatus.ACTIVE.value,
                DesignRuleStatus.SUPERSEDED.value,
                new_revision,
                {"superseded_by_rule_id": new_rule_id},
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            self._append_event(
                conn,
                "DESIGN_RULE",
                new_rule_id,
                "DESIGN_RULE_CREATED",
                None,
                DesignRuleStatus.ACTIVE.value,
                0,
                {
                    "category": category.value,
                    "authority": authority.value,
                    "scope_entity_ids": list(scopes),
                    "supersedes_rule_id": rule_id,
                },
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        return new_rule_id

    def retire_design_rule(
        self,
        rule_id: str,
        *,
        expected_revision: int,
        actor_type: str = "HUMAN",
        actor_id: str | None = None,
    ) -> int:
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        now = utc_now()
        with self.runtime.store.session() as conn:
            current = self._rule_row(conn, rule_id)
            actual = int(current["revision"])
            if actual != expected_revision:
                raise StaleRevision(
                    f"Design Rule {rule_id} revision {actual} != expected {expected_revision}"
                )
            if current["status"] != DesignRuleStatus.ACTIVE.value:
                raise ProjectIntelligenceError("only an ACTIVE Design Rule may be retired")
            new_revision = actual + 1
            cursor = conn.execute(
                "UPDATE design_rules SET status = 'RETIRED', revision = ?, updated_at = ? WHERE id = ? AND project_id = ? AND revision = ?",
                (new_revision, now, rule_id, self.project_id, actual),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(f"Design Rule {rule_id} changed concurrently")
            self._append_event(
                conn,
                "DESIGN_RULE",
                rule_id,
                "DESIGN_RULE_RETIRED",
                current["status"],
                DesignRuleStatus.RETIRED.value,
                new_revision,
                {},
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            return new_revision

    def _retire_simple(
        self,
        *,
        table: str,
        aggregate_type: str,
        aggregate_id: str,
        id_kind: IdKind,
        expected_revision: int,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
    ) -> int:
        if table not in {"entity_relations", "entity_bindings"}:
            raise AssertionError(table)
        if not validate_id(aggregate_id, id_kind):
            raise ValueError(f"invalid {aggregate_type} ID: {aggregate_id}")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        now = utc_now()
        with self.runtime.store.session() as conn:
            current = conn.execute(
                f"SELECT status, revision FROM {table} WHERE id = ? AND project_id = ?",
                (aggregate_id, self.project_id),
            ).fetchone()
            if current is None:
                raise KeyError(aggregate_id)
            actual = int(current["revision"])
            if actual != expected_revision:
                raise StaleRevision(
                    f"{aggregate_type} {aggregate_id} revision {actual} != expected {expected_revision}"
                )
            if current["status"] != "ACTIVE":
                raise ProjectIntelligenceError(f"{aggregate_type} is not ACTIVE")
            new_revision = actual + 1
            cursor = conn.execute(
                f"UPDATE {table} SET status = 'RETIRED', revision = ?, updated_at = ? WHERE id = ? AND project_id = ? AND revision = ?",
                (new_revision, now, aggregate_id, self.project_id, actual),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(f"{aggregate_type} {aggregate_id} changed concurrently")
            self._append_event(
                conn,
                aggregate_type,
                aggregate_id,
                event_type,
                "ACTIVE",
                "RETIRED",
                new_revision,
                {},
                now,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            return new_revision

    def impact(self, query: ImpactQuery) -> ImpactReport:
        if not isinstance(query, ImpactQuery):
            raise TypeError("query must be an ImpactQuery")
        if len(query.root_entity_ids) > query.max_entities:
            raise ValueError("impact max_entities is smaller than root count")
        relation_values = tuple(value.value for value in query.relation_types)
        placeholders = ",".join("?" for _ in relation_values)
        with self.runtime.store.session() as conn:
            for entity_id in query.root_entity_ids:
                self._entity_row(conn, entity_id)
            relations = list(
                conn.execute(
                    f"""SELECT * FROM entity_relations
                        WHERE project_id = ? AND status = 'ACTIVE'
                          AND relation_type IN ({placeholders})
                        ORDER BY relation_type, source_entity_id, target_entity_id, id""",
                    (self.project_id, *relation_values),
                )
            )

            outbound: dict[str, list[sqlite3.Row]] = {}
            inbound: dict[str, list[sqlite3.Row]] = {}
            for relation in relations:
                outbound.setdefault(relation["source_entity_id"], []).append(relation)
                inbound.setdefault(relation["target_entity_id"], []).append(relation)

            depth_by_entity = {entity_id: 0 for entity_id in query.root_entity_ids}
            queue = deque(query.root_entity_ids)
            relation_ids: set[str] = set()
            truncated_entities = False
            truncated_relations = False
            cycle_edges_observed = False

            while queue:
                current = queue.popleft()
                current_depth = depth_by_entity[current]
                if current_depth >= query.max_depth:
                    continue
                candidates: list[tuple[str, str, sqlite3.Row]] = []
                if query.direction in {ImpactDirection.OUTBOUND, ImpactDirection.BOTH}:
                    for relation in outbound.get(current, ()): 
                        candidates.append((relation["relation_type"], relation["target_entity_id"], relation))
                if query.direction in {ImpactDirection.INBOUND, ImpactDirection.BOTH}:
                    for relation in inbound.get(current, ()): 
                        candidates.append((relation["relation_type"], relation["source_entity_id"], relation))
                candidates.sort(key=lambda item: (item[0], item[1], item[2]["id"]))

                for _, neighbor, relation in candidates:
                    if relation["id"] not in relation_ids:
                        if len(relation_ids) >= query.max_relations:
                            truncated_relations = True
                            continue
                        relation_ids.add(relation["id"])
                    if neighbor in depth_by_entity:
                        cycle_edges_observed = True
                        continue
                    if len(depth_by_entity) >= query.max_entities:
                        truncated_entities = True
                        continue
                    depth_by_entity[neighbor] = current_depth + 1
                    queue.append(neighbor)

            visited_ids = tuple(sorted(depth_by_entity))
            impact_entities = tuple(
                ImpactEntity(entity_id, depth_by_entity[entity_id]) for entity_id in visited_ids
            )

            binding_ids: list[str] = []
            truncated_bindings = False
            if query.include_bindings and visited_ids:
                entity_placeholders = ",".join("?" for _ in visited_ids)
                binding_rows = conn.execute(
                    f"""SELECT id FROM entity_bindings
                        WHERE project_id = ? AND status = 'ACTIVE'
                          AND entity_id IN ({entity_placeholders})
                        ORDER BY entity_id, binding_type, target_ref, id""",
                    (self.project_id, *visited_ids),
                )
                for row in binding_rows:
                    if len(binding_ids) >= query.max_bindings:
                        truncated_bindings = True
                        break
                    binding_ids.append(row["id"])

            design_rule_ids: list[str] = []
            truncated_rules = False
            if query.include_design_rules:
                visited = set(visited_ids)
                for row in conn.execute(
                    """SELECT id, scope_entity_ids_json FROM design_rules
                       WHERE project_id = ? AND status = 'ACTIVE'
                       ORDER BY category, title, id""",
                    (self.project_id,),
                ):
                    try:
                        scopes = json.loads(row["scope_entity_ids_json"])
                    except json.JSONDecodeError as exc:
                        raise ProjectIntelligenceError("stored Design Rule scope JSON is invalid") from exc
                    if not isinstance(scopes, list) or any(not isinstance(value, str) for value in scopes):
                        raise ProjectIntelligenceError("stored Design Rule scopes are invalid")
                    if scopes and not visited.intersection(scopes):
                        continue
                    if len(design_rule_ids) >= query.max_rules:
                        truncated_rules = True
                        break
                    design_rule_ids.append(row["id"])

        return ImpactReport(
            query=query,
            entities=impact_entities,
            relation_ids=tuple(relation_ids),
            binding_ids=tuple(binding_ids),
            design_rule_ids=tuple(design_rule_ids),
            truncated_entities=truncated_entities,
            truncated_relations=truncated_relations,
            truncated_bindings=truncated_bindings,
            truncated_rules=truncated_rules,
            cycle_edges_observed=cycle_edges_observed,
        )
