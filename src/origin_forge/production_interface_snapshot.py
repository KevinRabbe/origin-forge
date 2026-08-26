from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .dream_read import DreamReadService
from .model_resource_read import inspect_model_resources
from .production_evidence_read import ProductionEvidenceReadService
from .production_read_guard import ensure_production_runtime_readable
from .production_runtime_read import ProductionRuntimeReadService
from .production_trace import inspect_task_production_trace
from .project_intelligence_read import ProjectIntelligenceReadService
from .provenance_read import ProvenanceReadService
from .runtime import OriginForgeRuntime
from .runtime_observation_models import content_hash

_MAX_TEXT_CHARS = 4096
_MAX_SECTION_ROWS = 10_000


class ProductionInterfaceSnapshotError(ValueError):
    pass


def _bounded_text(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= _MAX_TEXT_CHARS:
        return value, False
    return value[:_MAX_TEXT_CHARS], True


def _section_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= _MAX_SECTION_ROWS:
        raise ProductionInterfaceSnapshotError(
            f"interface section limit must be 1..{_MAX_SECTION_ROWS}"
        )
    return limit


def _catalog_limit(limit: int, maximum: int, label: str) -> int:
    normalized = _section_limit(limit)
    if normalized > maximum:
        raise ProductionInterfaceSnapshotError(
            f"{label} limit must be 1..{maximum}"
        )
    return normalized


def _limit_rows(
    rows: Iterable[dict[str, Any]], limit: int
) -> tuple[tuple[dict[str, Any], ...], bool]:
    normalized = _section_limit(limit)
    values = tuple(rows)
    if len(values) <= normalized:
        return values, False
    return values[:normalized], True


def _text_field(row: dict[str, object], name: str) -> tuple[str | None, bool]:
    return _bounded_text(row.get(name))


def _goal_projection(row: dict[str, Any]) -> dict[str, object]:
    objective, truncated = _bounded_text(row.get("objective"))
    return {
        "id": row["id"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "priority": int(row["priority"]),
        "objective": objective,
        "objective_truncated": truncated,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _flow_projection(row: dict[str, Any]) -> dict[str, object]:
    controller, controller_truncated = _bounded_text(row.get("controller"))
    blocked_reason, blocked_truncated = _bounded_text(row.get("blocked_reason"))
    return {
        "id": row["id"],
        "goal_id": row["goal_id"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "controller": controller,
        "controller_truncated": controller_truncated,
        "blocked_reason": blocked_reason,
        "blocked_reason_truncated": blocked_truncated,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_projection(row: dict[str, Any]) -> dict[str, object]:
    objective, truncated = _bounded_text(row.get("objective"))
    return {
        "id": row["id"],
        "flow_id": row["flow_id"],
        "parent_task_id": row["parent_task_id"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "attempt_count": int(row["attempt_count"]),
        "priority": int(row["priority"]),
        "objective": objective,
        "objective_truncated": truncated,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _run_projection(row: dict[str, Any]) -> dict[str, object]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "role": row["role"],
        "model_profile": row["model_profile"],
        "model_hash": row["model_hash"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "input_token_count": row["input_token_count"],
        "output_token_count": row["output_token_count"],
    }


def _verification_projection(row: dict[str, Any]) -> dict[str, object]:
    verifier, verifier_truncated = _bounded_text(row.get("verifier"))
    verification_type, type_truncated = _bounded_text(row.get("verification_type"))
    return {
        "id": row["id"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "verification_type": verification_type,
        "verification_type_truncated": type_truncated,
        "verifier": verifier,
        "verifier_truncated": verifier_truncated,
        "status": row["status"],
        "run_id": row["run_id"],
        "created_at": row["created_at"],
    }


def _entity_projection(row: dict[str, object]) -> dict[str, object]:
    name, name_truncated = _text_field(row, "name")
    description, description_truncated = _text_field(row, "description")
    return {
        "id": row["id"],
        "kind": row["kind"],
        "name": name,
        "name_truncated": name_truncated,
        "description": description,
        "description_truncated": description_truncated,
        "status": row["status"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _relation_projection(row: dict[str, object]) -> dict[str, object]:
    rationale, rationale_truncated = _text_field(row, "rationale")
    return {
        "id": row["id"],
        "source_entity_id": row["source_entity_id"],
        "relation_type": row["relation_type"],
        "target_entity_id": row["target_entity_id"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "rationale": rationale,
        "rationale_truncated": rationale_truncated,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "evidence_refs_disclosed": False,
    }


def _binding_projection(row: dict[str, object]) -> dict[str, object]:
    target_ref, target_ref_truncated = _text_field(row, "target_ref")
    return {
        "id": row["id"],
        "entity_id": row["entity_id"],
        "binding_type": row["binding_type"],
        "target_ref": target_ref,
        "target_ref_truncated": target_ref_truncated,
        "target_hash": row["target_hash"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata_disclosed": False,
    }


def _design_rule_projection(row: dict[str, object]) -> dict[str, object]:
    title, title_truncated = _text_field(row, "title")
    statement, statement_truncated = _text_field(row, "statement")
    rationale, rationale_truncated = _text_field(row, "rationale")
    scopes = row.get("scope_entity_ids")
    if not isinstance(scopes, tuple):
        raise ProductionInterfaceSnapshotError("Design Rule scopes are not normalized")
    return {
        "id": row["id"],
        "category": row["category"],
        "title": title,
        "title_truncated": title_truncated,
        "statement": statement,
        "statement_truncated": statement_truncated,
        "rationale": rationale,
        "rationale_truncated": rationale_truncated,
        "authority": row["authority"],
        "scope_entity_ids": scopes,
        "status": row["status"],
        "revision": int(row["revision"]),
        "supersedes_rule_id": row["supersedes_rule_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _decision_projection(row: dict[str, object]) -> dict[str, object]:
    title, title_truncated = _text_field(row, "title")
    decision, decision_truncated = _text_field(row, "decision")
    rationale, rationale_truncated = _text_field(row, "rationale")
    return {
        "id": row["id"],
        "goal_id": row["goal_id"],
        "task_id": row["task_id"],
        "title": title,
        "title_truncated": title_truncated,
        "decision": decision,
        "decision_truncated": decision_truncated,
        "rationale": rationale,
        "rationale_truncated": rationale_truncated,
        "status": row["status"],
        "supersedes_decision_id": row["supersedes_decision_id"],
        "created_at": row["created_at"],
        "context_disclosed": False,
        "alternatives_disclosed": False,
    }


def _change_projection(row: dict[str, object]) -> dict[str, object]:
    summary, summary_truncated = _text_field(row, "summary")
    change_type, change_type_truncated = _text_field(row, "change_type")
    before_ref, before_ref_truncated = _text_field(row, "before_ref")
    after_ref, after_ref_truncated = _text_field(row, "after_ref")
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "decision_id": row["decision_id"],
        "run_id": row["run_id"],
        "summary": summary,
        "summary_truncated": summary_truncated,
        "change_type": change_type,
        "change_type_truncated": change_type_truncated,
        "before_ref": before_ref,
        "before_ref_truncated": before_ref_truncated,
        "after_ref": after_ref,
        "after_ref_truncated": after_ref_truncated,
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _artifact_projection(row: dict[str, object]) -> dict[str, object]:
    artifact_type, type_truncated = _text_field(row, "type")
    path_or_uri, path_truncated = _text_field(row, "path_or_uri")
    model_id, model_id_truncated = _text_field(row, "model_id")
    return {
        "id": row["id"],
        "change_id": row["change_id"],
        "type": artifact_type,
        "type_truncated": type_truncated,
        "path_or_uri": path_or_uri,
        "path_or_uri_truncated": path_truncated,
        "content_hash": row["content_hash"],
        "parent_artifact_id": row["parent_artifact_id"],
        "created_by_run_id": row["created_by_run_id"],
        "model_id": model_id,
        "model_id_truncated": model_id_truncated,
        "status": row["status"],
        "created_at": row["created_at"],
        "artifact_bytes_disclosed": False,
        "skill_versions_disclosed": False,
        "tool_versions_disclosed": False,
    }


def _artifact_verification_projection(row: dict[str, object]) -> dict[str, object]:
    verification_type, type_truncated = _text_field(row, "verification_type")
    verifier, verifier_truncated = _text_field(row, "verifier")
    return {
        "id": row["id"],
        "target_type": "ARTIFACT",
        "target_id": row["target_id"],
        "verification_type": verification_type,
        "verification_type_truncated": type_truncated,
        "verifier": verifier,
        "verifier_truncated": verifier_truncated,
        "status": row["status"],
        "run_id": row["run_id"],
        "created_at": row["created_at"],
        "evidence_disclosed": False,
        "metrics_disclosed": False,
    }


def _bounded_projection(
    row: dict[str, object], text_fields: tuple[str, ...]
) -> dict[str, object]:
    result = dict(row)
    for field in text_fields:
        value, truncated = _text_field(row, field)
        result[field] = value
        result[f"{field}_truncated"] = truncated
    return result


@dataclass(frozen=True)
class ProductionInterfaceSnapshot:
    project_id: str
    goals: tuple[dict[str, object], ...]
    flows: tuple[dict[str, object], ...]
    tasks: tuple[dict[str, object], ...]
    runs: tuple[dict[str, object], ...]
    task_verifications: tuple[dict[str, object], ...]
    entities: tuple[dict[str, object], ...]
    entity_relations: tuple[dict[str, object], ...]
    entity_bindings: tuple[dict[str, object], ...]
    design_rules: tuple[dict[str, object], ...]
    decisions: tuple[dict[str, object], ...]
    changes: tuple[dict[str, object], ...]
    artifacts: tuple[dict[str, object], ...]
    artifact_verifications: tuple[dict[str, object], ...]
    model_resources: dict[str, object]
    provenance: dict[str, object]
    dream_memory: dict[str, object]
    total_counts: dict[str, int]
    truncated: dict[str, bool]
    production_trace: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "project_id": self.project_id,
            "goals": list(self.goals),
            "flows": list(self.flows),
            "tasks": list(self.tasks),
            "runs": list(self.runs),
            "task_verifications": list(self.task_verifications),
            "entities": list(self.entities),
            "entity_relations": list(self.entity_relations),
            "entity_bindings": list(self.entity_bindings),
            "design_rules": list(self.design_rules),
            "decisions": list(self.decisions),
            "changes": list(self.changes),
            "artifacts": list(self.artifacts),
            "artifact_verifications": list(self.artifact_verifications),
            "model_resources": self.model_resources,
            "provenance": self.provenance,
            "dream_memory": self.dream_memory,
            "total_counts": dict(sorted(self.total_counts.items())),
            "truncated": dict(sorted(self.truncated.items())),
            "production_trace": list(self.production_trace),
            "authority": {
                "read_only": True,
                "task_mutation": False,
                "project_intelligence_mutation": False,
                "lineage_mutation": False,
                "artifact_bytes_read": False,
                "verification_payload_read": False,
                "model_execution": False,
                "model_loading": False,
                "resource_leasing": False,
                "routing_mutation": False,
                "tool_execution": False,
                "artifact_adoption": False,
                "provenance_signing": False,
                "provenance_trust_verification": False,
                "artifact_currentness_verification": False,
                "dream_execution": False,
                "automatic_memory_promotion": False,
                "merge_release": False,
            },
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


def build_production_interface_snapshot(
    runtime: OriginForgeRuntime,
    *,
    max_goals: int = 128,
    max_flows: int = 256,
    max_tasks: int = 512,
    max_runs: int = 512,
    max_verifications: int = 1024,
    max_entities: int = 256,
    max_entity_relations: int = 512,
    max_entity_bindings: int = 512,
    max_design_rules: int = 256,
    max_decisions: int = 256,
    max_changes: int = 512,
    max_artifacts: int = 512,
    max_artifact_verifications: int = 1024,
    max_provenance_manifests: int = 128,
    max_dream_manifests: int = 128,
    max_dream_candidates: int = 256,
    max_dream_audits: int = 256,
    max_memory_entries: int = 256,
    max_memory_generations: int = 128,
) -> ProductionInterfaceSnapshot:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    ensure_production_runtime_readable(runtime)
    core = ProductionRuntimeReadService(runtime)

    max_goals = _section_limit(max_goals)
    max_flows = _section_limit(max_flows)
    max_tasks = _section_limit(max_tasks)
    max_runs = _section_limit(max_runs)
    max_verifications = _section_limit(max_verifications)
    max_entities = _section_limit(max_entities)
    max_entity_relations = _section_limit(max_entity_relations)
    max_entity_bindings = _section_limit(max_entity_bindings)
    max_design_rules = _section_limit(max_design_rules)
    max_decisions = _section_limit(max_decisions)
    max_changes = _section_limit(max_changes)
    max_artifacts = _section_limit(max_artifacts)
    max_artifact_verifications = _section_limit(max_artifact_verifications)
    max_provenance_manifests = _catalog_limit(
        max_provenance_manifests, 8192, "provenance manifest"
    )
    max_dream_manifests = _catalog_limit(max_dream_manifests, 1024, "Dream manifest")
    max_dream_candidates = _catalog_limit(max_dream_candidates, 8192, "Dream candidate")
    max_dream_audits = _catalog_limit(max_dream_audits, 10_000, "Dream audit")
    max_memory_entries = _catalog_limit(max_memory_entries, 4096, "memory entry")
    max_memory_generations = _catalog_limit(
        max_memory_generations, 2048, "memory generation"
    )

    raw_goals = core.list_goals(limit=max_goals + 1)
    raw_flows = core.list_flows(limit=max_flows + 1)
    raw_tasks = core.list_tasks(limit=max_tasks + 1)
    raw_runs = core.list_runs(limit=max_runs + 1)
    goals, goals_truncated = _limit_rows(raw_goals, max_goals)
    flows, flows_truncated = _limit_rows(raw_flows, max_flows)
    tasks, tasks_truncated = _limit_rows(raw_tasks, max_tasks)
    production_trace = tuple(
        {
            "task_id": task["id"],
            "claims": len(trace["dispatch"]["claims"]),
            "executions": len(trace["dispatch"]["executions"]),
            "output_bindings": {
                table: len(rows)
                for table, rows in trace["dispatch"]["output_bindings"].items()
            },
            "read_only": True,
        }
        for task in tasks
        for trace in (inspect_task_production_trace(runtime, str(task["id"])),)
    )
    runs, runs_truncated = _limit_rows(raw_runs, max_runs)

    verification_rows: list[dict[str, Any]] = []
    for task in tasks:
        remaining = max_verifications - len(verification_rows)
        if remaining <= 0:
            break
        values = core.list_task_verifications(
            str(task["id"]), limit=remaining + 1
        )
        verification_rows.extend(values[:remaining])
        if len(values) > remaining:
            break

    intelligence = ProjectIntelligenceReadService(runtime)
    pi_counts = intelligence.counts()
    entities = intelligence.list_entities(limit=max_entities)
    relations = intelligence.list_relations(limit=max_entity_relations)
    bindings = intelligence.list_bindings(limit=max_entity_bindings)
    rules = intelligence.list_design_rules(limit=max_design_rules)

    evidence = ProductionEvidenceReadService(runtime)
    evidence_counts = evidence.counts()
    decisions = evidence.list_decisions(limit=max_decisions)
    changes = evidence.list_changes(limit=max_changes)
    artifacts = evidence.list_artifacts(limit=max_artifacts)
    artifact_verifications = evidence.list_artifact_verifications(
        limit=max_artifact_verifications
    )

    provenance_reader = ProvenanceReadService(runtime)
    provenance_counts = provenance_reader.counts()
    provenance_roots = tuple(
        _bounded_projection(value, ("display_name",))
        for value in provenance_reader.roots()
    )
    provenance_certificates = provenance_reader.certificates()
    provenance_revocations = tuple(
        _bounded_projection(value, ("reason",))
        for value in provenance_reader.revocations()
    )
    provenance_manifests = tuple(
        _bounded_projection(
            value,
            ("artifact_type", "artifact_location", "model_id", "model_profile"),
        )
        for value in provenance_reader.manifests(limit=max_provenance_manifests)
    )
    provenance = {
        "roots": list(provenance_roots),
        "certificates": list(provenance_certificates),
        "revocations": list(provenance_revocations),
        "manifests": list(provenance_manifests),
        "counts": provenance_counts,
        "manifest_truncated": provenance_counts["manifests"] > len(provenance_manifests),
        "structural_validation_performed": True,
        "cryptographic_trust_verified_by_cockpit": False,
        "artifact_currentness_verified_by_cockpit": False,
        "artifact_bytes_read": False,
        "secret_key_material_read": False,
    }

    dream_reader = DreamReadService(runtime)
    dream_counts = dream_reader.counts()
    dream_manifests = dream_reader.manifests(limit=max_dream_manifests)
    dream_candidates = tuple(
        _bounded_projection(value, ("summary", "proposed_action"))
        for value in dream_reader.candidates(limit=max_dream_candidates)
    )
    dream_audits = dream_reader.audits(limit=max_dream_audits)
    memory_entries = tuple(
        _bounded_projection(value, ("claim",))
        for value in dream_reader.memory_entries(limit=max_memory_entries)
    )
    memory_generations = dream_reader.generations(limit=max_memory_generations)
    dream_memory = {
        "manifests": list(dream_manifests),
        "candidates": list(dream_candidates),
        "audits": list(dream_audits),
        "memory_entries": list(memory_entries),
        "generations": list(memory_generations),
        "counts": dream_counts,
        "truncated": {
            "manifests": dream_counts["manifests"] > len(dream_manifests),
            "candidates": dream_counts["candidates"] > len(dream_candidates),
            "audits": dream_counts["audits"] > len(dream_audits),
            "memory_entries": dream_counts["memory_entries"] > len(memory_entries),
            "generations": dream_counts["generations"] > len(memory_generations),
        },
        "evidence_refs_disclosed": False,
        "finding_messages_disclosed": False,
        "dream_execution_authorized": False,
        "automatic_memory_promotion_authorized": False,
        "production_state_mutation_authorized": False,
    }

    model_resources = inspect_model_resources(runtime.project_root)

    total_counts = {
        "goals": core.count_goals(),
        "flows": core.count_flows(),
        "tasks": core.count_tasks(),
        "runs": core.count_runs(),
        "task_verifications": core.count_task_verifications(),
        "entities": pi_counts["entities"],
        "entity_relations": pi_counts["relations"],
        "entity_bindings": pi_counts["bindings"],
        "design_rules": pi_counts["design_rules"],
        "decisions": evidence_counts["decisions"],
        "changes": evidence_counts["changes"],
        "artifacts": evidence_counts["artifacts"],
        "artifact_verifications": evidence_counts["artifact_verifications"],
        "provenance_roots": provenance_counts["roots"],
        "provenance_certificates": provenance_counts["certificates"],
        "provenance_revocations": provenance_counts["revocations"],
        "provenance_manifests": provenance_counts["manifests"],
        "dream_manifests": dream_counts["manifests"],
        "dream_candidates": dream_counts["candidates"],
        "dream_audits": dream_counts["audits"],
        "memory_entries": dream_counts["memory_entries"],
        "memory_generations": dream_counts["generations"],
    }

    return ProductionInterfaceSnapshot(
        project_id=core.project_id(),
        goals=tuple(_goal_projection(value) for value in goals),
        flows=tuple(_flow_projection(value) for value in flows),
        tasks=tuple(_task_projection(value) for value in tasks),
        runs=tuple(_run_projection(value) for value in runs),
        task_verifications=tuple(
            _verification_projection(value) for value in verification_rows
        ),
        entities=tuple(_entity_projection(value) for value in entities),
        entity_relations=tuple(_relation_projection(value) for value in relations),
        entity_bindings=tuple(_binding_projection(value) for value in bindings),
        design_rules=tuple(_design_rule_projection(value) for value in rules),
        decisions=tuple(_decision_projection(value) for value in decisions),
        changes=tuple(_change_projection(value) for value in changes),
        artifacts=tuple(_artifact_projection(value) for value in artifacts),
        artifact_verifications=tuple(
            _artifact_verification_projection(value) for value in artifact_verifications
        ),
        model_resources=model_resources,
        provenance=provenance,
        dream_memory=dream_memory,
        total_counts=total_counts,
        truncated={
            "goals": goals_truncated,
            "flows": flows_truncated,
            "tasks": tasks_truncated,
            "runs": runs_truncated,
            "task_verifications": total_counts["task_verifications"] > len(verification_rows),
            "entities": pi_counts["entities"] > len(entities),
            "entity_relations": pi_counts["relations"] > len(relations),
            "entity_bindings": pi_counts["bindings"] > len(bindings),
            "design_rules": pi_counts["design_rules"] > len(rules),
            "decisions": evidence_counts["decisions"] > len(decisions),
            "changes": evidence_counts["changes"] > len(changes),
            "artifacts": evidence_counts["artifacts"] > len(artifacts),
            "artifact_verifications": evidence_counts["artifact_verifications"]
            > len(artifact_verifications),
            "provenance_manifests": provenance_counts["manifests"]
            > len(provenance_manifests),
            "dream_manifests": dream_counts["manifests"] > len(dream_manifests),
            "dream_candidates": dream_counts["candidates"] > len(dream_candidates),
            "dream_audits": dream_counts["audits"] > len(dream_audits),
            "memory_entries": dream_counts["memory_entries"] > len(memory_entries),
            "memory_generations": dream_counts["generations"] > len(memory_generations),
        },
        production_trace=production_trace,
    )
