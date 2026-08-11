from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .production_planning_evidence import (
    MaterializedTaskBinding,
    PlanMaterialization,
    ProductionPlanningEvidenceError,
    _audit_from_dict,
    _decode_payload,
    _hash,
    _planning_input_from_dict,
    _proposal_from_dict,
)
from .production_planning_models import (
    PlanAudit,
    PlanAuditStatus,
    PlanProposal,
    PlanningInput,
    ProductionPlanningModelError,
    audit_plan,
)
from .production_read_guard import production_read_connection
from .runtime import OriginForgeRuntime
from .task_dependencies import (
    TaskDependencyGraph,
    flow_dependency_graph_connection,
)
from .task_readiness import (
    TaskDependencyReadiness,
    resolve_task_dependency_readiness_connection,
)


_EVIDENCE_SCHEMA_VERSION = 1
_MAX_STATUS_COUNT = 1_000_000_000


class ProductionPlanningInspectionError(RuntimeError):
    pass


def _project_id(conn: sqlite3.Connection, runtime: OriginForgeRuntime) -> str:
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?",
        (str(runtime.project_root),),
    ).fetchone()
    if row is None:
        raise ProductionPlanningInspectionError("project is not bound to this repository root")
    return row["id"]


def _load_payload_row(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    object_id: str,
) -> tuple[dict[str, Any], str, sqlite3.Row]:
    row = conn.execute(
        f"SELECT * FROM {table} WHERE {id_column} = ?",
        (object_id,),
    ).fetchone()
    if row is None:
        raise KeyError(object_id)
    if row["schema_version"] != _EVIDENCE_SCHEMA_VERSION:
        raise ProductionPlanningInspectionError(f"{table} schema version drifted")
    try:
        payload = _decode_payload(row["payload_json"])
    except ProductionPlanningEvidenceError as exc:
        raise ProductionPlanningInspectionError(f"{table} payload failed validation") from exc
    expected_hash = row["content_hash"]
    if _hash(payload) != expected_hash:
        raise ProductionPlanningInspectionError(f"{table} content hash drifted")
    return payload, expected_hash, row


def _load_input_connection(
    conn: sqlite3.Connection,
    project_id: str,
    planning_input_id: str,
) -> PlanningInput:
    payload, expected_hash, row = _load_payload_row(
        conn,
        table="planning_inputs",
        id_column="planning_input_id",
        object_id=planning_input_id,
    )
    if row["project_id"] != project_id:
        raise KeyError(planning_input_id)
    try:
        value = _planning_input_from_dict(payload)
    except ProductionPlanningEvidenceError as exc:
        raise ProductionPlanningInspectionError("PlanningInput failed typed validation") from exc
    if value.content_hash != expected_hash:
        raise ProductionPlanningInspectionError("PlanningInput canonical hash drifted")
    if (
        value.project_id != row["project_id"]
        or value.goal_id != row["goal_id"]
        or value.goal_revision != row["goal_revision"]
    ):
        raise ProductionPlanningInspectionError("PlanningInput relational binding drifted")
    goal = conn.execute(
        "SELECT project_id FROM goals WHERE id = ?",
        (value.goal_id,),
    ).fetchone()
    if goal is None or goal["project_id"] != project_id:
        raise ProductionPlanningInspectionError("PlanningInput Goal binding is unavailable")
    return value


def _load_proposal_connection(
    conn: sqlite3.Connection,
    project_id: str,
    proposal_id: str,
) -> PlanProposal:
    payload, expected_hash, row = _load_payload_row(
        conn,
        table="plan_proposals",
        id_column="proposal_id",
        object_id=proposal_id,
    )
    planning_input = _load_input_connection(conn, project_id, row["planning_input_id"])
    try:
        value = _proposal_from_dict(payload)
        value.bind(planning_input)
    except (ProductionPlanningEvidenceError, ProductionPlanningModelError) as exc:
        raise ProductionPlanningInspectionError("PlanProposal failed exact input binding") from exc
    if value.content_hash != expected_hash:
        raise ProductionPlanningInspectionError("PlanProposal canonical hash drifted")
    if value.planning_input_id != row["planning_input_id"]:
        raise ProductionPlanningInspectionError("PlanProposal relational binding drifted")
    return value


def _assert_audit_recomputed(
    planning_input: PlanningInput,
    proposal: PlanProposal,
    value: PlanAudit,
) -> None:
    expected = audit_plan(planning_input, proposal)
    for field in (
        "planning_input_id",
        "planning_input_hash",
        "proposal_id",
        "proposal_hash",
        "status",
        "task_count",
        "edge_count",
        "max_depth",
        "topological_step_keys",
        "failure_reason",
    ):
        if getattr(value, field) != getattr(expected, field):
            raise ProductionPlanningInspectionError("PlanAudit disagrees with recomputation")


def _load_audit_connection(
    conn: sqlite3.Connection,
    project_id: str,
    audit_id: str,
) -> PlanAudit:
    payload, expected_hash, row = _load_payload_row(
        conn,
        table="plan_audits",
        id_column="audit_id",
        object_id=audit_id,
    )
    planning_input = _load_input_connection(conn, project_id, row["planning_input_id"])
    proposal = _load_proposal_connection(conn, project_id, row["proposal_id"])
    try:
        value = _audit_from_dict(payload)
    except ProductionPlanningEvidenceError as exc:
        raise ProductionPlanningInspectionError("PlanAudit failed typed validation") from exc
    if value.content_hash != expected_hash:
        raise ProductionPlanningInspectionError("PlanAudit canonical hash drifted")
    if (
        value.planning_input_id != row["planning_input_id"]
        or value.proposal_id != row["proposal_id"]
        or value.status.value != row["status"]
    ):
        raise ProductionPlanningInspectionError("PlanAudit relational binding drifted")
    _assert_audit_recomputed(planning_input, proposal, value)
    return value


def _materialization_from_dict(value: dict[str, Any]) -> PlanMaterialization:
    expected = {
        "materialization_id",
        "planning_input_id",
        "planning_input_hash",
        "proposal_id",
        "proposal_hash",
        "audit_id",
        "audit_hash",
        "goal_id",
        "goal_revision",
        "flow_id",
        "task_bindings",
    }
    if set(value) != expected or not isinstance(value["task_bindings"], list):
        raise ProductionPlanningInspectionError("PlanMaterialization schema drifted")
    bindings: list[MaterializedTaskBinding] = []
    try:
        for item in value["task_bindings"]:
            if not isinstance(item, dict) or set(item) != {"step_key", "task_id"}:
                raise ProductionPlanningInspectionError("materialization task binding drifted")
            bindings.append(MaterializedTaskBinding(item["step_key"], item["task_id"]))
        return PlanMaterialization(
            materialization_id=value["materialization_id"],
            planning_input_id=value["planning_input_id"],
            planning_input_hash=value["planning_input_hash"],
            proposal_id=value["proposal_id"],
            proposal_hash=value["proposal_hash"],
            audit_id=value["audit_id"],
            audit_hash=value["audit_hash"],
            goal_id=value["goal_id"],
            goal_revision=value["goal_revision"],
            flow_id=value["flow_id"],
            task_bindings=tuple(bindings),
        )
    except (ProductionPlanningEvidenceError, TypeError, ValueError) as exc:
        raise ProductionPlanningInspectionError("PlanMaterialization failed typed validation") from exc


def _load_json_list(raw: str, label: str) -> list[object]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProductionPlanningInspectionError(f"{label} JSON is invalid") from exc
    if not isinstance(value, list):
        raise ProductionPlanningInspectionError(f"{label} JSON is not a list")
    return value


def _load_json_object(raw: str, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProductionPlanningInspectionError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ProductionPlanningInspectionError(f"{label} JSON is not an object")
    return value


def _validate_materialized_graph(
    conn: sqlite3.Connection,
    project_id: str,
    materialization: PlanMaterialization,
    proposal: PlanProposal,
) -> None:
    flow = conn.execute(
        """SELECT f.id, f.goal_id, g.project_id
           FROM flows f JOIN goals g ON g.id = f.goal_id
           WHERE f.id = ?""",
        (materialization.flow_id,),
    ).fetchone()
    if (
        flow is None
        or flow["project_id"] != project_id
        or flow["goal_id"] != materialization.goal_id
    ):
        raise ProductionPlanningInspectionError("materialized Flow binding drifted")

    binding_by_key = {binding.step_key: binding.task_id for binding in materialization.task_bindings}
    step_by_key = {step.step_key: step for step in proposal.steps}
    if set(binding_by_key) != set(step_by_key):
        raise ProductionPlanningInspectionError("materialized Task binding set drifted")

    for step_key, task_id in sorted(binding_by_key.items()):
        step = step_by_key[step_key]
        task = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if task is None or task["flow_id"] != materialization.flow_id:
            raise ProductionPlanningInspectionError("materialized Task Flow binding drifted")
        if task["parent_task_id"] is not None or task["objective"] != step.objective:
            raise ProductionPlanningInspectionError("materialized Task objective/parent drifted")
        if _load_json_list(task["acceptance_criteria_json"], "Task acceptance") != list(
            step.acceptance_criteria
        ):
            raise ProductionPlanningInspectionError("materialized Task acceptance drifted")
        if _load_json_list(task["constraints_json"], "Task constraints") != list(step.constraints):
            raise ProductionPlanningInspectionError("materialized Task constraints drifted")
        if _load_json_list(task["required_capabilities_json"], "Task capabilities") != list(
            step.required_capabilities
        ):
            raise ProductionPlanningInspectionError("materialized Task capabilities drifted")
        if _load_json_object(task["budget_json"], "Task budget") != {"attempts": step.max_attempts}:
            raise ProductionPlanningInspectionError("materialized Task budget drifted")
        if int(task["priority"]) != step.priority:
            raise ProductionPlanningInspectionError("materialized Task priority drifted")

    expected_edges = {
        (binding_by_key[step.step_key], binding_by_key[required])
        for step in proposal.steps
        for required in step.depends_on
    }
    rows = conn.execute(
        """SELECT td.task_id, td.required_task_id, td.dependency_type
           FROM task_dependencies td
           JOIN tasks t ON t.id = td.task_id
           WHERE t.flow_id = ?""",
        (materialization.flow_id,),
    ).fetchall()
    actual_edges = {(row["task_id"], row["required_task_id"]) for row in rows}
    if any(row["dependency_type"] != "REQUIRES_SUCCESS" for row in rows):
        raise ProductionPlanningInspectionError("materialized dependency type drifted")
    if actual_edges != expected_edges:
        raise ProductionPlanningInspectionError("materialized dependency graph drifted")


def _load_materialization_connection(
    conn: sqlite3.Connection,
    project_id: str,
    materialization_id: str,
) -> PlanMaterialization:
    payload, expected_hash, row = _load_payload_row(
        conn,
        table="plan_materializations",
        id_column="materialization_id",
        object_id=materialization_id,
    )
    planning_input = _load_input_connection(conn, project_id, row["planning_input_id"])
    proposal = _load_proposal_connection(conn, project_id, row["proposal_id"])
    audit = _load_audit_connection(conn, project_id, row["audit_id"])
    materialization = _materialization_from_dict(payload)
    if materialization.content_hash != expected_hash:
        raise ProductionPlanningInspectionError("PlanMaterialization canonical hash drifted")
    if (
        materialization.planning_input_id != row["planning_input_id"]
        or materialization.proposal_id != row["proposal_id"]
        or materialization.audit_id != row["audit_id"]
        or materialization.goal_id != row["goal_id"]
        or materialization.flow_id != row["flow_id"]
    ):
        raise ProductionPlanningInspectionError("PlanMaterialization relational binding drifted")
    if (
        materialization.planning_input_hash != planning_input.content_hash
        or materialization.proposal_hash != proposal.content_hash
        or materialization.audit_hash != audit.content_hash
        or materialization.goal_id != planning_input.goal_id
        or materialization.goal_revision != planning_input.goal_revision
        or audit.status is not PlanAuditStatus.PASS
    ):
        raise ProductionPlanningInspectionError("PlanMaterialization evidence binding drifted")
    _validate_materialized_graph(conn, project_id, materialization, proposal)
    return materialization


@dataclass(frozen=True)
class ProductionPlanningStatus:
    project_id: str
    planning_input_count: int
    proposal_count: int
    audit_count: int
    materialization_count: int
    dependency_edge_count: int

    def __post_init__(self) -> None:
        for name in (
            "planning_input_count",
            "proposal_count",
            "audit_count",
            "materialization_count",
            "dependency_edge_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= _MAX_STATUS_COUNT:
                raise ProductionPlanningInspectionError(f"{name} is outside bounds")

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "planning_input_count": self.planning_input_count,
            "proposal_count": self.proposal_count,
            "audit_count": self.audit_count,
            "materialization_count": self.materialization_count,
            "dependency_edge_count": self.dependency_edge_count,
        }


def inspect_production_planning_status(runtime: OriginForgeRuntime) -> ProductionPlanningStatus:
    with production_read_connection(runtime) as conn:
        project_id = _project_id(conn, runtime)
        counts = {
            "planning_input_count": conn.execute(
                "SELECT COUNT(*) AS n FROM planning_inputs WHERE project_id = ?",
                (project_id,),
            ).fetchone()["n"],
            "proposal_count": conn.execute(
                """SELECT COUNT(*) AS n FROM plan_proposals p
                   JOIN planning_inputs i ON i.planning_input_id = p.planning_input_id
                   WHERE i.project_id = ?""",
                (project_id,),
            ).fetchone()["n"],
            "audit_count": conn.execute(
                """SELECT COUNT(*) AS n FROM plan_audits a
                   JOIN planning_inputs i ON i.planning_input_id = a.planning_input_id
                   WHERE i.project_id = ?""",
                (project_id,),
            ).fetchone()["n"],
            "materialization_count": conn.execute(
                """SELECT COUNT(*) AS n FROM plan_materializations m
                   JOIN planning_inputs i ON i.planning_input_id = m.planning_input_id
                   WHERE i.project_id = ?""",
                (project_id,),
            ).fetchone()["n"],
            "dependency_edge_count": conn.execute(
                """SELECT COUNT(*) AS n FROM task_dependencies d
                   JOIN tasks t ON t.id = d.task_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE g.project_id = ?""",
                (project_id,),
            ).fetchone()["n"],
        }
        return ProductionPlanningStatus(project_id=project_id, **counts)


def inspect_planning_input(runtime: OriginForgeRuntime, planning_input_id: str) -> PlanningInput:
    with production_read_connection(runtime) as conn:
        return _load_input_connection(conn, _project_id(conn, runtime), planning_input_id)


def inspect_plan_proposal(runtime: OriginForgeRuntime, proposal_id: str) -> PlanProposal:
    with production_read_connection(runtime) as conn:
        return _load_proposal_connection(conn, _project_id(conn, runtime), proposal_id)


def inspect_plan_audit(runtime: OriginForgeRuntime, audit_id: str) -> PlanAudit:
    with production_read_connection(runtime) as conn:
        return _load_audit_connection(conn, _project_id(conn, runtime), audit_id)


def inspect_plan_materialization(
    runtime: OriginForgeRuntime,
    materialization_id: str,
) -> PlanMaterialization:
    with production_read_connection(runtime) as conn:
        return _load_materialization_connection(
            conn,
            _project_id(conn, runtime),
            materialization_id,
        )


def inspect_flow_dependency_graph(
    runtime: OriginForgeRuntime,
    flow_id: str,
) -> TaskDependencyGraph:
    with production_read_connection(runtime) as conn:
        project_id = _project_id(conn, runtime)
        owner = conn.execute(
            """SELECT g.project_id FROM flows f
               JOIN goals g ON g.id = f.goal_id
               WHERE f.id = ?""",
            (flow_id,),
        ).fetchone()
        if owner is None or owner["project_id"] != project_id:
            raise KeyError(flow_id)
        return flow_dependency_graph_connection(conn, flow_id)


def inspect_task_dependency_readiness(
    runtime: OriginForgeRuntime,
    task_id: str,
) -> TaskDependencyReadiness:
    with production_read_connection(runtime) as conn:
        project_id = _project_id(conn, runtime)
        owner = conn.execute(
            """SELECT g.project_id FROM tasks t
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               WHERE t.id = ?""",
            (task_id,),
        ).fetchone()
        if owner is None or owner["project_id"] != project_id:
            raise KeyError(task_id)
        return resolve_task_dependency_readiness_connection(conn, task_id)
