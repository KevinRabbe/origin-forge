from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .project_intelligence_read import ProjectIntelligenceReadService
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


def _limit_rows(rows: Iterable[dict[str, Any]], limit: int) -> tuple[tuple[dict[str, Any], ...], bool]:
    normalized = _section_limit(limit)
    values = tuple(rows)
    if len(values) <= normalized:
        return values, False
    return values[:normalized], True


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
    name, name_truncated = _bounded_text(row.get("name"))
    description, description_truncated = _bounded_text(row.get("description"))
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
    rationale, rationale_truncated = _bounded_text(row.get("rationale"))
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
    target_ref, target_ref_truncated = _bounded_text(row.get("target_ref"))
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
    title, title_truncated = _bounded_text(row.get("title"))
    statement, statement_truncated = _bounded_text(row.get("statement"))
    rationale, rationale_truncated = _bounded_text(row.get("rationale"))
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
    total_counts: dict[str, int]
    truncated: dict[str, bool]

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
            "total_counts": dict(sorted(self.total_counts.items())),
            "truncated": dict(sorted(self.truncated.items())),
            "authority": {
                "read_only": True,
                "task_mutation": False,
                "project_intelligence_mutation": False,
                "model_execution": False,
                "tool_execution": False,
                "artifact_adoption": False,
                "provenance_signing": False,
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
) -> ProductionInterfaceSnapshot:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    max_goals = _section_limit(max_goals)
    max_flows = _section_limit(max_flows)
    max_tasks = _section_limit(max_tasks)
    max_runs = _section_limit(max_runs)
    max_verifications = _section_limit(max_verifications)
    max_entities = _section_limit(max_entities)
    max_entity_relations = _section_limit(max_entity_relations)
    max_entity_bindings = _section_limit(max_entity_bindings)
    max_design_rules = _section_limit(max_design_rules)

    raw_goals = tuple(runtime.list_goals(limit=max_goals + 1))
    raw_flows = tuple(runtime.list_flows(limit=max_flows + 1))
    raw_tasks = tuple(runtime.list_tasks(limit=max_tasks + 1))
    raw_runs = tuple(runtime.list_runs(limit=max_runs + 1))

    goals, goals_truncated = _limit_rows(raw_goals, max_goals)
    flows, flows_truncated = _limit_rows(raw_flows, max_flows)
    tasks, tasks_truncated = _limit_rows(raw_tasks, max_tasks)
    runs, runs_truncated = _limit_rows(raw_runs, max_runs)

    verification_rows: list[dict[str, Any]] = []
    for task in tasks:
        remaining = max_verifications - len(verification_rows)
        if remaining <= 0:
            break
        values = runtime.list_verifications(
            "TASK",
            str(task["id"]),
            limit=remaining + 1,
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

    total_counts = {
        "goals": runtime.count_goals(),
        "flows": runtime.count_flows(),
        "tasks": runtime.count_tasks(),
        "runs": runtime.count_runs(),
        "task_verifications": runtime.count_task_verifications(),
        "entities": pi_counts["entities"],
        "entity_relations": pi_counts["relations"],
        "entity_bindings": pi_counts["bindings"],
        "design_rules": pi_counts["design_rules"],
    }
    verification_truncated = total_counts["task_verifications"] > len(verification_rows)

    return ProductionInterfaceSnapshot(
        project_id=runtime.project_id(),
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
        total_counts=total_counts,
        truncated={
            "goals": goals_truncated,
            "flows": flows_truncated,
            "tasks": tasks_truncated,
            "runs": runs_truncated,
            "task_verifications": verification_truncated,
            "entities": pi_counts["entities"] > len(entities),
            "entity_relations": pi_counts["relations"] > len(relations),
            "entity_bindings": pi_counts["bindings"] > len(bindings),
            "design_rules": pi_counts["design_rules"] > len(rules),
        },
    )
