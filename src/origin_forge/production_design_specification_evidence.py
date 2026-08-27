from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .ids import IdKind, validate_id
from .production_capability_store import (
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_design_specification_models import (
    DesignDeliverable,
    DesignAnimationIntent,
    DesignRequirement,
    DesignSpecification,
    DesignSpecificationAudit,
    DesignSpecificationAuditStatus,
    DesignSpecificationInput,
    DesignSpecificationModelError,
    audit_design_specification,
)
from .production_planning_evidence import goal_planning_hash
from .production_planning_models import (
    PlanningEvidenceRef,
    ProductionPlanningModelError,
)
from .runtime import OriginForgeRuntime
from .service import OriginForgeStore, utc_now

_SCHEMA_VERSION = 1
_MAX_PAYLOAD_BYTES = 1024 * 1024
_MAX_SEMANTIC_ROWS = 4096
_MAX_DESIGN_RULES = 128
_MAX_VERIFIED_STATE_REFS = 126  # leaves room for CAPCAT + CAPPOL evidence


class DesignSpecificationEvidenceError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DesignSpecificationEvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_text(value: object) -> str:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError(
            "design specification evidence is not canonical JSON"
        ) from exc
    if not text or len(text.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise DesignSpecificationEvidenceError(
            "design specification evidence is outside byte bounds"
        )
    return text


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_text(value).encode("utf-8")).hexdigest()


def _decode_payload(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise DesignSpecificationEvidenceError("stored design evidence is outside bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except DesignSpecificationEvidenceError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError("stored design evidence is invalid JSON") from exc
    if not isinstance(value, dict) or _canonical_text(value) != raw:
        raise DesignSpecificationEvidenceError("stored design evidence is not canonical")
    return value


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DesignSpecificationEvidenceError(f"{label} schema drifted")
    return value


def _decode_json_field(raw: object, label: str, expected: type) -> Any:
    if not isinstance(raw, str):
        raise DesignSpecificationEvidenceError(f"canonical {label} is not JSON text")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError(f"canonical {label} is invalid JSON") from exc
    if not isinstance(value, expected):
        raise DesignSpecificationEvidenceError(f"canonical {label} has wrong JSON type")
    return value


def _evidence_ref_from_dict(value: object) -> PlanningEvidenceRef:
    raw = _exact_keys(value, {"ref_id", "content_hash", "revision"}, "evidence ref")
    try:
        return PlanningEvidenceRef(
            ref_id=raw["ref_id"],
            content_hash=raw["content_hash"],
            revision=raw["revision"],
        )
    except (ProductionPlanningModelError, TypeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError("evidence ref failed validation") from exc


def _input_from_dict(value: dict[str, Any]) -> DesignSpecificationInput:
    _exact_keys(
        value,
        {
            "design_input_id",
            "project_id",
            "goal_id",
            "goal_revision",
            "goal_content_hash",
            "verified_state_refs",
            "active_design_rule_refs",
            "project_intelligence_hash",
            "capability_catalog_hash",
            "capability_ids",
            "model_policy_hash",
            "resource_policy_hash",
        },
        "DesignSpecificationInput",
    )
    for field in ("verified_state_refs", "active_design_rule_refs", "capability_ids"):
        if not isinstance(value[field], list):
            raise DesignSpecificationEvidenceError(f"DesignSpecificationInput {field} is invalid")
    try:
        return DesignSpecificationInput(
            design_input_id=value["design_input_id"],
            project_id=value["project_id"],
            goal_id=value["goal_id"],
            goal_revision=value["goal_revision"],
            goal_content_hash=value["goal_content_hash"],
            verified_state_refs=tuple(
                _evidence_ref_from_dict(item) for item in value["verified_state_refs"]
            ),
            active_design_rule_refs=tuple(
                _evidence_ref_from_dict(item) for item in value["active_design_rule_refs"]
            ),
            project_intelligence_hash=value["project_intelligence_hash"],
            capability_catalog_hash=value["capability_catalog_hash"],
            capability_ids=tuple(value["capability_ids"]),
            model_policy_hash=value["model_policy_hash"],
            resource_policy_hash=value["resource_policy_hash"],
        )
    except (DesignSpecificationModelError, TypeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError(
            "stored DesignSpecificationInput failed validation"
        ) from exc


def _requirement_from_dict(value: object) -> DesignRequirement:
    raw = _exact_keys(
        value,
        {"key", "statement", "acceptance_criteria", "constraints"},
        "DesignRequirement",
    )
    if not isinstance(raw["acceptance_criteria"], list) or not isinstance(
        raw["constraints"], list
    ):
        raise DesignSpecificationEvidenceError("stored DesignRequirement arrays are invalid")
    try:
        return DesignRequirement(
            key=raw["key"],
            statement=raw["statement"],
            acceptance_criteria=tuple(raw["acceptance_criteria"]),
            constraints=tuple(raw["constraints"]),
        )
    except (DesignSpecificationModelError, TypeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError(
            "stored DesignRequirement failed validation"
        ) from exc


def _deliverable_from_dict(value: object) -> DesignDeliverable:
    required_keys = {
            "key",
            "objective",
            "acceptance_criteria",
            "constraints",
            "required_capabilities",
        }
    if not isinstance(value, dict) or not required_keys <= set(value) or set(value) - required_keys - {"animation_intents"}:
        raise DesignSpecificationEvidenceError("DesignDeliverable schema drifted")
    raw = value
    for field in ("acceptance_criteria", "constraints", "required_capabilities"):
        if not isinstance(raw[field], list):
            raise DesignSpecificationEvidenceError(
                f"stored DesignDeliverable {field} is invalid"
            )
    animation_intents = []
    if "animation_intents" in raw:
        if not isinstance(raw["animation_intents"], list):
            raise DesignSpecificationEvidenceError("stored animation_intents are invalid")
        for animation in raw["animation_intents"]:
            if not isinstance(animation, dict) or set(animation) != {
                "name", "frame_count", "frame_duration_ms", "loop_mode"
            }:
                raise DesignSpecificationEvidenceError("stored animation intent schema drifted")
            try:
                animation_intents.append(DesignAnimationIntent(**animation))
            except (DesignSpecificationModelError, TypeError, ValueError) as exc:
                raise DesignSpecificationEvidenceError("stored animation intent failed validation") from exc
    try:
        return DesignDeliverable(
            key=raw["key"],
            objective=raw["objective"],
            acceptance_criteria=tuple(raw["acceptance_criteria"]),
            constraints=tuple(raw["constraints"]),
            required_capabilities=tuple(raw["required_capabilities"]),
            animation_intents=tuple(animation_intents),
        )
    except (DesignSpecificationModelError, TypeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError(
            "stored DesignDeliverable failed validation"
        ) from exc


def _specification_from_dict(value: dict[str, Any]) -> DesignSpecification:
    raw = _exact_keys(
        value,
        {
            "design_specification_id",
            "design_input_id",
            "design_input_hash",
            "run_id",
            "model_id",
            "model_hash",
            "specification",
        },
        "DesignSpecification",
    )
    payload = _exact_keys(
        raw["specification"],
        {"summary", "requirements", "deliverables"},
        "DesignSpecification payload",
    )
    if not isinstance(payload["requirements"], list) or not isinstance(
        payload["deliverables"], list
    ):
        raise DesignSpecificationEvidenceError("stored specification arrays are invalid")
    try:
        return DesignSpecification(
            design_specification_id=raw["design_specification_id"],
            design_input_id=raw["design_input_id"],
            design_input_hash=raw["design_input_hash"],
            run_id=raw["run_id"],
            model_id=raw["model_id"],
            model_hash=raw["model_hash"],
            summary=payload["summary"],
            requirements=tuple(_requirement_from_dict(item) for item in payload["requirements"]),
            deliverables=tuple(_deliverable_from_dict(item) for item in payload["deliverables"]),
        )
    except (DesignSpecificationModelError, TypeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError(
            "stored DesignSpecification failed validation"
        ) from exc


def _audit_from_dict(value: dict[str, Any]) -> DesignSpecificationAudit:
    raw = _exact_keys(
        value,
        {
            "audit_id",
            "design_input_id",
            "design_input_hash",
            "design_specification_id",
            "design_specification_hash",
            "status",
            "requirement_count",
            "deliverable_count",
            "required_capability_count",
            "canonical_byte_count",
            "failure_reason",
        },
        "DesignSpecificationAudit",
    )
    try:
        return DesignSpecificationAudit(
            audit_id=raw["audit_id"],
            design_input_id=raw["design_input_id"],
            design_input_hash=raw["design_input_hash"],
            design_specification_id=raw["design_specification_id"],
            design_specification_hash=raw["design_specification_hash"],
            status=DesignSpecificationAuditStatus(raw["status"]),
            requirement_count=raw["requirement_count"],
            deliverable_count=raw["deliverable_count"],
            required_capability_count=raw["required_capability_count"],
            canonical_byte_count=raw["canonical_byte_count"],
            failure_reason=raw["failure_reason"],
        )
    except (DesignSpecificationModelError, TypeError, ValueError) as exc:
        raise DesignSpecificationEvidenceError(
            "stored DesignSpecificationAudit failed validation"
        ) from exc


@dataclass(frozen=True)
class DesignSemanticSnapshot:
    project_intelligence_hash: str
    active_design_rule_refs: tuple[PlanningEvidenceRef, ...]
    verified_state_refs: tuple[PlanningEvidenceRef, ...]
    context: dict[str, object]


def _semantic_snapshot(conn: sqlite3.Connection, project_id: str) -> DesignSemanticSnapshot:
    entities = conn.execute(
        """SELECT id, kind, name, description, revision, metadata_json
           FROM entities WHERE project_id = ? AND status = 'ACTIVE' ORDER BY id""",
        (project_id,),
    ).fetchall()
    relations = conn.execute(
        """SELECT id, source_entity_id, relation_type, target_entity_id, revision,
                  rationale, evidence_refs_json
           FROM entity_relations WHERE project_id = ? AND status = 'ACTIVE' ORDER BY id""",
        (project_id,),
    ).fetchall()
    bindings = conn.execute(
        """SELECT id, entity_id, binding_type, target_ref, target_hash, revision, metadata_json
           FROM entity_bindings WHERE project_id = ? AND status = 'ACTIVE' ORDER BY id""",
        (project_id,),
    ).fetchall()
    rules = conn.execute(
        """SELECT id, category, title, statement, rationale, authority,
                  scope_entity_ids_json, revision, supersedes_rule_id
           FROM design_rules WHERE project_id = ? AND status = 'ACTIVE' ORDER BY id""",
        (project_id,),
    ).fetchall()
    if any(len(rows) > _MAX_SEMANTIC_ROWS for rows in (entities, relations, bindings)):
        raise DesignSpecificationEvidenceError("project intelligence exceeds design snapshot bounds")
    if len(rules) > _MAX_DESIGN_RULES:
        raise DesignSpecificationEvidenceError("active Design Rules exceed design snapshot bounds")

    entity_payload = [
        {
            "id": row["id"],
            "kind": row["kind"],
            "name": row["name"],
            "description": row["description"],
            "revision": int(row["revision"]),
            "metadata": _decode_json_field(row["metadata_json"], "Entity metadata", dict),
        }
        for row in entities
    ]
    relation_payload = [
        {
            "id": row["id"],
            "source_entity_id": row["source_entity_id"],
            "relation_type": row["relation_type"],
            "target_entity_id": row["target_entity_id"],
            "revision": int(row["revision"]),
            "rationale": row["rationale"],
            "evidence_refs": _decode_json_field(
                row["evidence_refs_json"], "EntityRelation evidence refs", list
            ),
        }
        for row in relations
    ]
    binding_payload = [
        {
            "id": row["id"],
            "entity_id": row["entity_id"],
            "binding_type": row["binding_type"],
            "target_ref": row["target_ref"],
            "target_hash": row["target_hash"],
            "revision": int(row["revision"]),
            "metadata": _decode_json_field(
                row["metadata_json"], "EntityBinding metadata", dict
            ),
        }
        for row in bindings
    ]
    rule_payload = [
        {
            "id": row["id"],
            "category": row["category"],
            "title": row["title"],
            "statement": row["statement"],
            "rationale": row["rationale"],
            "authority": row["authority"],
            "scope_entity_ids": _decode_json_field(
                row["scope_entity_ids_json"], "DesignRule scope", list
            ),
            "revision": int(row["revision"]),
            "supersedes_rule_id": row["supersedes_rule_id"],
        }
        for row in rules
    ]

    rule_refs = tuple(
        PlanningEvidenceRef(
            ref_id=payload["id"],
            content_hash=_hash(payload),
            revision=payload["revision"],
        )
        for payload in rule_payload
    )

    verification_refs: dict[str, PlanningEvidenceRef] = {}
    for row in bindings:
        if row["binding_type"] != "VERIFICATION":
            continue
        target_ref = row["target_ref"]
        if not validate_id(target_ref, IdKind.VERIFICATION):
            raise DesignSpecificationEvidenceError(
                "active VERIFICATION binding does not target a VERIFY ID"
            )
        verification = conn.execute(
            """SELECT id, target_type, target_id, verification_type, verifier,
                      status, evidence_json, metrics_json, run_id
               FROM verifications WHERE id = ?""",
            (target_ref,),
        ).fetchone()
        if verification is None:
            raise DesignSpecificationEvidenceError(
                "active VERIFICATION binding targets missing evidence"
            )
        if verification["status"] != "PASS":
            continue
        payload = {
            "id": verification["id"],
            "target_type": verification["target_type"],
            "target_id": verification["target_id"],
            "verification_type": verification["verification_type"],
            "verifier": verification["verifier"],
            "status": verification["status"],
            "evidence": _decode_json_field(
                verification["evidence_json"], "Verification evidence", dict
            ),
            "metrics": _decode_json_field(
                verification["metrics_json"], "Verification metrics", dict
            ),
            "run_id": verification["run_id"],
        }
        verification_refs[target_ref] = PlanningEvidenceRef(
            ref_id=target_ref,
            content_hash=_hash(payload),
            revision=None,
        )
    if len(verification_refs) > _MAX_VERIFIED_STATE_REFS:
        raise DesignSpecificationEvidenceError("verified semantic state exceeds input bounds")

    semantic_payload = {
        "entities": entity_payload,
        "relations": relation_payload,
        "bindings": binding_payload,
        "design_rules": rule_payload,
    }
    context: dict[str, object] = {
        "entities": [
            {
                "id": value["id"],
                "kind": value["kind"],
                "name": value["name"],
                "description": value["description"],
                "revision": value["revision"],
            }
            for value in entity_payload
        ],
        "relations": [
            {
                "id": value["id"],
                "source_entity_id": value["source_entity_id"],
                "relation_type": value["relation_type"],
                "target_entity_id": value["target_entity_id"],
                "revision": value["revision"],
            }
            for value in relation_payload
        ],
        "design_rules": rule_payload,
    }
    if len(_canonical_text(context).encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise DesignSpecificationEvidenceError("bounded design semantic context exceeds byte limit")
    return DesignSemanticSnapshot(
        project_intelligence_hash=_hash(semantic_payload),
        active_design_rule_refs=tuple(sorted(rule_refs, key=lambda value: value.key)),
        verified_state_refs=tuple(
            sorted(verification_refs.values(), key=lambda value: value.key)
        ),
        context=context,
    )


class DesignSpecificationEvidenceStore:
    """Immutable Phase-56 design evidence over canonical project state."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.store: OriginForgeStore = runtime.store

    @staticmethod
    def _insert_evidence(
        conn: sqlite3.Connection,
        *,
        table: str,
        id_column: str,
        object_id: str,
        content_hash: str,
        payload: dict[str, object],
        extra_columns: tuple[str, ...],
        extra_values: tuple[object, ...],
    ) -> None:
        payload_json = _canonical_text(payload)
        existing = conn.execute(
            f"SELECT schema_version, content_hash, payload_json FROM {table} WHERE {id_column} = ?",
            (object_id,),
        ).fetchone()
        if existing is not None:
            if (
                existing["schema_version"] == _SCHEMA_VERSION
                and existing["content_hash"] == content_hash
                and existing["payload_json"] == payload_json
            ):
                return
            raise DesignSpecificationEvidenceError(
                f"{table} identity replay disagrees with durable evidence"
            )
        columns = (
            id_column,
            *extra_columns,
            "schema_version",
            "content_hash",
            "payload_json",
            "created_at",
        )
        values = (
            object_id,
            *extra_values,
            _SCHEMA_VERSION,
            content_hash,
            payload_json,
            utc_now(),
        )
        try:
            conn.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise DesignSpecificationEvidenceError(
                f"{table} evidence already exists or is invalid"
            ) from exc

    @staticmethod
    def _load_payload(
        conn: sqlite3.Connection,
        table: str,
        id_column: str,
        object_id: str,
    ) -> tuple[dict[str, Any], str]:
        row = conn.execute(
            f"SELECT schema_version, content_hash, payload_json FROM {table} WHERE {id_column} = ?",
            (object_id,),
        ).fetchone()
        if row is None:
            raise KeyError(object_id)
        if row["schema_version"] != _SCHEMA_VERSION:
            raise DesignSpecificationEvidenceError(f"{table} schema version drifted")
        payload = _decode_payload(row["payload_json"])
        if _hash(payload) != row["content_hash"]:
            raise DesignSpecificationEvidenceError(f"{table} content hash drifted")
        return payload, row["content_hash"]

    @staticmethod
    def _governed_capability_refs(
        value: DesignSpecificationInput,
    ) -> tuple[PlanningEvidenceRef, PlanningEvidenceRef, tuple[PlanningEvidenceRef, ...]]:
        catalogs = tuple(
            ref
            for ref in value.verified_state_refs
            if validate_id(ref.ref_id, IdKind.CAPABILITY_CATALOG)
        )
        policies = tuple(
            ref
            for ref in value.verified_state_refs
            if validate_id(ref.ref_id, IdKind.CAPABILITY_ROUTING_POLICY)
        )
        if len(catalogs) != 1 or len(policies) != 1:
            raise DesignSpecificationEvidenceError(
                "design input requires exactly one CAPCAT and one CAPPOL evidence ref"
            )
        reserved = {catalogs[0].ref_id, policies[0].ref_id}
        semantic_refs = tuple(
            ref for ref in value.verified_state_refs if ref.ref_id not in reserved
        )
        return catalogs[0], policies[0], semantic_refs

    def _assert_capability_binding(
        self,
        value: DesignSpecificationInput,
        capability_store: ProductionCapabilityStore,
    ) -> None:
        if not isinstance(capability_store, ProductionCapabilityStore):
            raise TypeError("capability_store must be a ProductionCapabilityStore")
        if capability_store.runtime.project_root != self.runtime.project_root:
            raise DesignSpecificationEvidenceError(
                "capability authority belongs to a different project root"
            )
        catalog_ref, policy_ref, _ = self._governed_capability_refs(value)
        try:
            catalog = capability_store.load_catalog(catalog_ref.ref_id)
            policy = capability_store.load_policy(policy_ref.ref_id)
        except (ProductionCapabilityStoreError, KeyError) as exc:
            raise DesignSpecificationEvidenceError(
                "design input capability authority could not be revalidated"
            ) from exc
        if catalog.content_hash != catalog_ref.content_hash:
            raise DesignSpecificationEvidenceError("design input catalog hash drifted")
        if policy.content_hash != policy_ref.content_hash:
            raise DesignSpecificationEvidenceError("design input routing policy hash drifted")
        if policy.catalog_id != catalog.catalog_id or policy.catalog_hash != catalog.content_hash:
            raise DesignSpecificationEvidenceError("design input policy/catalog binding drifted")
        if value.capability_catalog_hash != catalog.content_hash:
            raise DesignSpecificationEvidenceError("design input capability_catalog_hash drifted")
        if tuple(value.capability_ids) != tuple(sorted(policy.allowed_capability_ids)):
            raise DesignSpecificationEvidenceError("design input capability IDs drifted")
        if "design.specify" not in value.capability_ids:
            raise DesignSpecificationEvidenceError(
                "design.specify is not allowed by the frozen routing policy"
            )

    def _assert_semantic_binding_conn(
        self,
        conn: sqlite3.Connection,
        value: DesignSpecificationInput,
    ) -> DesignSemanticSnapshot:
        project_id = self.runtime.project_id()
        if value.project_id != project_id:
            raise DesignSpecificationEvidenceError("design input belongs to another project")
        goal = conn.execute(
            "SELECT * FROM goals WHERE id = ? AND project_id = ?",
            (value.goal_id, project_id),
        ).fetchone()
        if goal is None:
            raise KeyError(value.goal_id)
        if (
            int(goal["revision"]) != value.goal_revision
            or goal_planning_hash(goal) != value.goal_content_hash
        ):
            raise DesignSpecificationEvidenceError("design input Goal binding is stale or forged")
        snapshot = _semantic_snapshot(conn, project_id)
        _, _, semantic_refs = self._governed_capability_refs(value)
        if semantic_refs != snapshot.verified_state_refs:
            raise DesignSpecificationEvidenceError("design input verified semantic state drifted")
        if value.active_design_rule_refs != snapshot.active_design_rule_refs:
            raise DesignSpecificationEvidenceError("design input Design Rule binding drifted")
        if value.project_intelligence_hash != snapshot.project_intelligence_hash:
            raise DesignSpecificationEvidenceError("design input Project Intelligence binding drifted")
        return snapshot

    def publish_input(
        self,
        value: DesignSpecificationInput,
        *,
        capability_store: ProductionCapabilityStore,
    ) -> None:
        if not isinstance(value, DesignSpecificationInput):
            raise TypeError("value must be a DesignSpecificationInput")
        self._assert_capability_binding(value, capability_store)
        with self.store.session() as conn:
            self._assert_semantic_binding_conn(conn, value)
            self._insert_evidence(
                conn,
                table="design_specification_inputs",
                id_column="design_input_id",
                object_id=value.design_input_id,
                content_hash=value.content_hash,
                payload=value.to_dict(),
                extra_columns=("project_id", "goal_id", "goal_revision"),
                extra_values=(value.project_id, value.goal_id, value.goal_revision),
            )

    def _load_input_conn(self, conn: sqlite3.Connection, object_id: str) -> DesignSpecificationInput:
        payload, expected_hash = self._load_payload(
            conn, "design_specification_inputs", "design_input_id", object_id
        )
        value = _input_from_dict(payload)
        if value.content_hash != expected_hash:
            raise DesignSpecificationEvidenceError(
                "DesignSpecificationInput canonical hash drifted"
            )
        return value

    def load_input(self, object_id: str) -> DesignSpecificationInput:
        with self.store.session() as conn:
            return self._load_input_conn(conn, object_id)

    def generation_context(self, value: DesignSpecificationInput) -> dict[str, object]:
        with self.store.session() as conn:
            snapshot = self._assert_semantic_binding_conn(conn, value)
            goal = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                (value.goal_id, value.project_id),
            ).fetchone()
            if goal is None:
                raise KeyError(value.goal_id)
            return {
                "design_input": value.to_dict(),
                "goal": {
                    "id": goal["id"],
                    "revision": int(goal["revision"]),
                    "objective": goal["objective"],
                    "success_criteria": _decode_json_field(
                        goal["success_criteria_json"], "Goal success criteria", list
                    ),
                    "constraints": _decode_json_field(
                        goal["constraints_json"], "Goal constraints", list
                    ),
                    "budgets": _decode_json_field(goal["budgets_json"], "Goal budgets", dict),
                    "priority": int(goal["priority"]),
                    "status": goal["status"],
                },
                "project_intelligence": snapshot.context,
            }

    def publish_specification(self, value: DesignSpecification) -> None:
        if not isinstance(value, DesignSpecification):
            raise TypeError("value must be a DesignSpecification")
        with self.store.session() as conn:
            design_input = self._load_input_conn(conn, value.design_input_id)
            try:
                value.bind(design_input)
            except DesignSpecificationModelError as exc:
                raise DesignSpecificationEvidenceError(
                    "DesignSpecification failed exact input binding"
                ) from exc
            run = conn.execute(
                "SELECT task_id, role FROM runs WHERE id = ?",
                (value.run_id,),
            ).fetchone()
            if run is None:
                raise DesignSpecificationEvidenceError(
                    "DesignSpecification references a missing governed Run"
                )
            if run["task_id"] is not None or run["role"] != "DESIGN_SPECIFIER":
                raise DesignSpecificationEvidenceError(
                    "DesignSpecification Run is not the dedicated Task-less design boundary"
                )
            self._insert_evidence(
                conn,
                table="design_specifications",
                id_column="design_specification_id",
                object_id=value.design_specification_id,
                content_hash=value.content_hash,
                payload=value.to_dict(),
                extra_columns=("design_input_id", "run_id"),
                extra_values=(value.design_input_id, value.run_id),
            )

    def _load_specification_conn(
        self, conn: sqlite3.Connection, object_id: str
    ) -> DesignSpecification:
        payload, expected_hash = self._load_payload(
            conn,
            "design_specifications",
            "design_specification_id",
            object_id,
        )
        value = _specification_from_dict(payload)
        if value.content_hash != expected_hash:
            raise DesignSpecificationEvidenceError(
                "DesignSpecification canonical hash drifted"
            )
        design_input = self._load_input_conn(conn, value.design_input_id)
        try:
            value.bind(design_input)
        except DesignSpecificationModelError as exc:
            raise DesignSpecificationEvidenceError(
                "stored DesignSpecification binding drifted"
            ) from exc
        return value

    def load_specification(self, object_id: str) -> DesignSpecification:
        with self.store.session() as conn:
            return self._load_specification_conn(conn, object_id)

    @staticmethod
    def _assert_audit_matches(
        design_input: DesignSpecificationInput,
        specification: DesignSpecification,
        value: DesignSpecificationAudit,
    ) -> None:
        expected = audit_design_specification(design_input, specification)
        fields = (
            "design_input_id",
            "design_input_hash",
            "design_specification_id",
            "design_specification_hash",
            "status",
            "requirement_count",
            "deliverable_count",
            "required_capability_count",
            "canonical_byte_count",
            "failure_reason",
        )
        if any(getattr(value, field) != getattr(expected, field) for field in fields):
            raise DesignSpecificationEvidenceError(
                "DesignSpecificationAudit disagrees with independent recomputation"
            )

    def publish_audit(self, value: DesignSpecificationAudit) -> None:
        if not isinstance(value, DesignSpecificationAudit):
            raise TypeError("value must be a DesignSpecificationAudit")
        with self.store.session() as conn:
            design_input = self._load_input_conn(conn, value.design_input_id)
            specification = self._load_specification_conn(
                conn, value.design_specification_id
            )
            self._assert_audit_matches(design_input, specification, value)
            self._insert_evidence(
                conn,
                table="design_specification_audits",
                id_column="audit_id",
                object_id=value.audit_id,
                content_hash=value.content_hash,
                payload=value.to_dict(),
                extra_columns=("design_input_id", "design_specification_id", "status"),
                extra_values=(
                    value.design_input_id,
                    value.design_specification_id,
                    value.status.value,
                ),
            )

    def _load_audit_conn(
        self, conn: sqlite3.Connection, object_id: str
    ) -> DesignSpecificationAudit:
        payload, expected_hash = self._load_payload(
            conn, "design_specification_audits", "audit_id", object_id
        )
        value = _audit_from_dict(payload)
        if value.content_hash != expected_hash:
            raise DesignSpecificationEvidenceError(
                "DesignSpecificationAudit canonical hash drifted"
            )
        design_input = self._load_input_conn(conn, value.design_input_id)
        specification = self._load_specification_conn(
            conn, value.design_specification_id
        )
        self._assert_audit_matches(design_input, specification, value)
        return value

    def load_audit(self, object_id: str) -> DesignSpecificationAudit:
        with self.store.session() as conn:
            return self._load_audit_conn(conn, object_id)


def build_design_input(
    runtime: OriginForgeRuntime,
    *,
    goal_id: str,
    capability_store: ProductionCapabilityStore,
    catalog_id: str,
    routing_policy_id: str,
    model_policy_hash: str,
    resource_policy_hash: str,
) -> DesignSpecificationInput:
    """Derive one exact pre-planning input; callers cannot supply semantic hashes."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    store = DesignSpecificationEvidenceStore(runtime)
    if not isinstance(capability_store, ProductionCapabilityStore):
        raise TypeError("capability_store must be a ProductionCapabilityStore")
    if capability_store.runtime.project_root != runtime.project_root:
        raise DesignSpecificationEvidenceError(
            "capability authority belongs to a different project root"
        )
    try:
        catalog = capability_store.load_catalog(catalog_id)
        policy = capability_store.load_policy(routing_policy_id)
    except (ProductionCapabilityStoreError, KeyError) as exc:
        raise DesignSpecificationEvidenceError(
            "capability authority could not be loaded and validated"
        ) from exc
    if policy.catalog_id != catalog.catalog_id or policy.catalog_hash != catalog.content_hash:
        raise DesignSpecificationEvidenceError("routing policy/catalog binding drifted")
    if "design.specify" not in policy.allowed_capability_ids:
        raise DesignSpecificationEvidenceError(
            "routing policy does not allow design.specify"
        )

    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        goal = conn.execute(
            "SELECT * FROM goals WHERE id = ? AND project_id = ?",
            (goal_id, project_id),
        ).fetchone()
        if goal is None:
            raise KeyError(goal_id)
        snapshot = _semantic_snapshot(conn, project_id)
    governed_refs = (
        *snapshot.verified_state_refs,
        PlanningEvidenceRef(catalog.catalog_id, catalog.content_hash),
        PlanningEvidenceRef(policy.routing_policy_id, policy.content_hash),
    )
    value = DesignSpecificationInput.create(
        project_id=project_id,
        goal_id=goal_id,
        goal_revision=int(goal["revision"]),
        goal_content_hash=goal_planning_hash(goal),
        verified_state_refs=governed_refs,
        active_design_rule_refs=snapshot.active_design_rule_refs,
        project_intelligence_hash=snapshot.project_intelligence_hash,
        capability_catalog_hash=catalog.content_hash,
        capability_ids=policy.allowed_capability_ids,
        model_policy_hash=model_policy_hash,
        resource_policy_hash=resource_policy_hash,
    )
    store.publish_input(value, capability_store=capability_store)
    return value
