from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from .ids import IdKind, new_id, validate_id
from .production_planning_models import (
    PlanAudit,
    PlanAuditStatus,
    PlanProposal,
    PlanStep,
    PlanningEvidenceRef,
    PlanningInput,
    ProductionPlanningModelError,
    audit_plan,
)
from .runtime import OriginForgeRuntime
from .service import OriginForgeStore, utc_now
from .state import FlowStatus, TaskDependencyType, TaskStatus


_SCHEMA_VERSION = 1
_MAX_PAYLOAD_BYTES = 1024 * 1024


class ProductionPlanningEvidenceError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionPlanningEvidenceError(f"duplicate JSON key: {key}")
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
        raise ProductionPlanningEvidenceError("planning evidence is not canonical JSON") from exc
    if len(text.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ProductionPlanningEvidenceError("planning evidence exceeds byte limit")
    return text


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_text(value).encode("utf-8")).hexdigest()


def _decode_payload(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ProductionPlanningEvidenceError("stored planning payload is outside bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except ProductionPlanningEvidenceError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProductionPlanningEvidenceError("stored planning payload is invalid JSON") from exc
    if not isinstance(value, dict) or _canonical_text(value) != raw:
        raise ProductionPlanningEvidenceError("stored planning payload is not canonical")
    return value


def _exact_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise ProductionPlanningEvidenceError(f"{label} schema drifted")


def _evidence_ref_from_dict(value: object) -> PlanningEvidenceRef:
    if not isinstance(value, dict):
        raise ProductionPlanningEvidenceError("planning evidence ref is invalid")
    _exact_keys(value, {"ref_id", "content_hash", "revision"}, "planning evidence ref")
    try:
        return PlanningEvidenceRef(
            ref_id=value["ref_id"],
            content_hash=value["content_hash"],
            revision=value["revision"],
        )
    except (ProductionPlanningModelError, TypeError, ValueError) as exc:
        raise ProductionPlanningEvidenceError("planning evidence ref failed validation") from exc


def _planning_input_from_dict(value: dict[str, Any]) -> PlanningInput:
    _exact_keys(
        value,
        {
            "planning_input_id",
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
        "PlanningInput",
    )
    for field in ("verified_state_refs", "active_design_rule_refs", "capability_ids"):
        if not isinstance(value[field], list):
            raise ProductionPlanningEvidenceError(f"PlanningInput {field} is invalid")
    try:
        return PlanningInput(
            planning_input_id=value["planning_input_id"],
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
    except (ProductionPlanningModelError, TypeError, ValueError) as exc:
        raise ProductionPlanningEvidenceError("PlanningInput failed validation") from exc


def _plan_step_from_dict(value: object) -> PlanStep:
    if not isinstance(value, dict):
        raise ProductionPlanningEvidenceError("PlanStep is invalid")
    _exact_keys(
        value,
        {
            "step_key",
            "objective",
            "acceptance_criteria",
            "constraints",
            "required_capabilities",
            "priority",
            "budget_hint",
            "depends_on",
        },
        "PlanStep",
    )
    for field in ("acceptance_criteria", "constraints", "required_capabilities", "depends_on"):
        if not isinstance(value[field], list):
            raise ProductionPlanningEvidenceError(f"PlanStep {field} is invalid")
    budget = value["budget_hint"]
    if not isinstance(budget, dict) or set(budget) != {"attempts"}:
        raise ProductionPlanningEvidenceError("PlanStep budget_hint is invalid")
    try:
        return PlanStep(
            step_key=value["step_key"],
            objective=value["objective"],
            acceptance_criteria=tuple(value["acceptance_criteria"]),
            constraints=tuple(value["constraints"]),
            required_capabilities=tuple(value["required_capabilities"]),
            priority=value["priority"],
            max_attempts=budget["attempts"],
            depends_on=tuple(value["depends_on"]),
        )
    except (ProductionPlanningModelError, TypeError, ValueError) as exc:
        raise ProductionPlanningEvidenceError("PlanStep failed validation") from exc


def _proposal_from_dict(value: dict[str, Any]) -> PlanProposal:
    _exact_keys(
        value,
        {"proposal_id", "planning_input_id", "planning_input_hash", "summary", "steps"},
        "PlanProposal",
    )
    if not isinstance(value["steps"], list):
        raise ProductionPlanningEvidenceError("PlanProposal steps are invalid")
    try:
        return PlanProposal(
            proposal_id=value["proposal_id"],
            planning_input_id=value["planning_input_id"],
            planning_input_hash=value["planning_input_hash"],
            summary=value["summary"],
            steps=tuple(_plan_step_from_dict(item) for item in value["steps"]),
        )
    except (ProductionPlanningModelError, TypeError, ValueError) as exc:
        raise ProductionPlanningEvidenceError("PlanProposal failed validation") from exc


def _audit_from_dict(value: dict[str, Any]) -> PlanAudit:
    _exact_keys(
        value,
        {
            "audit_id",
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
        },
        "PlanAudit",
    )
    if not isinstance(value["topological_step_keys"], list):
        raise ProductionPlanningEvidenceError("PlanAudit topological_step_keys are invalid")
    try:
        return PlanAudit(
            audit_id=value["audit_id"],
            planning_input_id=value["planning_input_id"],
            planning_input_hash=value["planning_input_hash"],
            proposal_id=value["proposal_id"],
            proposal_hash=value["proposal_hash"],
            status=PlanAuditStatus(value["status"]),
            task_count=value["task_count"],
            edge_count=value["edge_count"],
            max_depth=value["max_depth"],
            topological_step_keys=tuple(value["topological_step_keys"]),
            failure_reason=value["failure_reason"],
        )
    except (ProductionPlanningModelError, TypeError, ValueError) as exc:
        raise ProductionPlanningEvidenceError("PlanAudit failed validation") from exc


def _goal_payload(row: sqlite3.Row) -> dict[str, object]:
    try:
        success = json.loads(row["success_criteria_json"])
        constraints = json.loads(row["constraints_json"])
        budgets = json.loads(row["budgets_json"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProductionPlanningEvidenceError("canonical Goal JSON is invalid") from exc
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "objective": row["objective"],
        "success_criteria": success,
        "constraints": constraints,
        "budgets": budgets,
        "priority": row["priority"],
        "status": row["status"],
        "revision": row["revision"],
    }


def goal_planning_hash(row: sqlite3.Row) -> str:
    return _hash(_goal_payload(row))


def freeze_planning_input(
    runtime: OriginForgeRuntime,
    goal_id: str,
    *,
    verified_state_refs: Iterable[PlanningEvidenceRef] = (),
    active_design_rule_refs: Iterable[PlanningEvidenceRef] = (),
    project_intelligence_hash: str,
    capability_catalog_hash: str,
    capability_ids: Iterable[str],
    model_policy_hash: str,
    resource_policy_hash: str,
) -> PlanningInput:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        row = conn.execute(
            "SELECT * FROM goals WHERE id = ? AND project_id = ?",
            (goal_id, project_id),
        ).fetchone()
        if row is None:
            raise KeyError(goal_id)
        return PlanningInput.create(
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=int(row["revision"]),
            goal_content_hash=goal_planning_hash(row),
            verified_state_refs=verified_state_refs,
            active_design_rule_refs=active_design_rule_refs,
            project_intelligence_hash=project_intelligence_hash,
            capability_catalog_hash=capability_catalog_hash,
            capability_ids=capability_ids,
            model_policy_hash=model_policy_hash,
            resource_policy_hash=resource_policy_hash,
        )


@dataclass(frozen=True)
class MaterializedTaskBinding:
    step_key: str
    task_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.step_key, str) or not self.step_key:
            raise ProductionPlanningEvidenceError("materialized step_key is invalid")
        if not validate_id(self.task_id, IdKind.TASK):
            raise ProductionPlanningEvidenceError("materialized task_id must be a TASK ID")

    def to_dict(self) -> dict[str, str]:
        return {"step_key": self.step_key, "task_id": self.task_id}


@dataclass(frozen=True)
class PlanMaterialization:
    materialization_id: str
    planning_input_id: str
    planning_input_hash: str
    proposal_id: str
    proposal_hash: str
    audit_id: str
    audit_hash: str
    goal_id: str
    goal_revision: int
    flow_id: str
    task_bindings: tuple[MaterializedTaskBinding, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.materialization_id, IdKind.PLAN_MATERIALIZATION):
            raise ProductionPlanningEvidenceError("materialization_id must be a PLMAT ID")
        if not validate_id(self.planning_input_id, IdKind.PLANNING_INPUT):
            raise ProductionPlanningEvidenceError("planning_input_id must be a PLINPUT ID")
        if not validate_id(self.proposal_id, IdKind.PLAN_PROPOSAL):
            raise ProductionPlanningEvidenceError("proposal_id must be a PLPROP ID")
        if not validate_id(self.audit_id, IdKind.PLAN_AUDIT):
            raise ProductionPlanningEvidenceError("audit_id must be a PLAUD ID")
        if not validate_id(self.goal_id, IdKind.GOAL):
            raise ProductionPlanningEvidenceError("goal_id must be a GOAL ID")
        if not validate_id(self.flow_id, IdKind.FLOW):
            raise ProductionPlanningEvidenceError("flow_id must be a FLOW ID")
        if type(self.goal_revision) is not int or self.goal_revision < 0:
            raise ProductionPlanningEvidenceError("goal_revision is invalid")
        for field in ("planning_input_hash", "proposal_hash", "audit_hash"):
            value = getattr(self, field)
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ProductionPlanningEvidenceError(f"{field} is invalid")
        bindings = tuple(self.task_bindings)
        if not bindings or not all(isinstance(v, MaterializedTaskBinding) for v in bindings):
            raise ProductionPlanningEvidenceError("task_bindings are invalid")
        step_keys = [v.step_key for v in bindings]
        task_ids = [v.task_id for v in bindings]
        if len(step_keys) != len(set(step_keys)) or len(task_ids) != len(set(task_ids)):
            raise ProductionPlanningEvidenceError("task_bindings contain duplicates")
        object.__setattr__(self, "task_bindings", tuple(sorted(bindings, key=lambda v: v.step_key)))

    def to_dict(self) -> dict[str, object]:
        return {
            "materialization_id": self.materialization_id,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "audit_id": self.audit_id,
            "audit_hash": self.audit_hash,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "flow_id": self.flow_id,
            "task_bindings": [v.to_dict() for v in self.task_bindings],
        }

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())


class ProductionPlanningEvidenceStore:
    """Immutable Phase-31 evidence over the canonical Origin Forge SQLite store."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.store: OriginForgeStore = runtime.store

    @staticmethod
    def _insert_evidence(
        conn: sqlite3.Connection,
        table: str,
        id_column: str,
        object_id: str,
        content_hash: str,
        payload: dict[str, object],
        extra_columns: tuple[str, ...],
        extra_values: tuple[object, ...],
    ) -> None:
        payload_json = _canonical_text(payload)
        columns = (id_column, *extra_columns, "schema_version", "content_hash", "payload_json", "created_at")
        values = (object_id, *extra_values, _SCHEMA_VERSION, content_hash, payload_json, utc_now())
        placeholders = ",".join("?" for _ in columns)
        try:
            conn.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise ProductionPlanningEvidenceError(f"{table} evidence already exists or is invalid") from exc

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
            raise ProductionPlanningEvidenceError(f"{table} schema version drifted")
        payload = _decode_payload(row["payload_json"])
        if _hash(payload) != row["content_hash"]:
            raise ProductionPlanningEvidenceError(f"{table} content hash drifted")
        return payload, row["content_hash"]

    def publish_input(self, value: PlanningInput) -> None:
        if not isinstance(value, PlanningInput):
            raise TypeError("value must be a PlanningInput")
        project_id = self.runtime.project_id()
        if value.project_id != project_id:
            raise ProductionPlanningEvidenceError("PlanningInput belongs to another project")
        with self.store.session() as conn:
            goal = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                (value.goal_id, project_id),
            ).fetchone()
            if goal is None:
                raise KeyError(value.goal_id)
            if int(goal["revision"]) != value.goal_revision or goal_planning_hash(goal) != value.goal_content_hash:
                raise ProductionPlanningEvidenceError("PlanningInput Goal binding is stale or forged")
            self._insert_evidence(
                conn,
                "planning_inputs",
                "planning_input_id",
                value.planning_input_id,
                value.content_hash,
                value.to_dict(),
                ("project_id", "goal_id", "goal_revision"),
                (value.project_id, value.goal_id, value.goal_revision),
            )

    def _load_input_conn(self, conn: sqlite3.Connection, object_id: str) -> PlanningInput:
        payload, expected_hash = self._load_payload(conn, "planning_inputs", "planning_input_id", object_id)
        value = _planning_input_from_dict(payload)
        if value.content_hash != expected_hash:
            raise ProductionPlanningEvidenceError("PlanningInput canonical hash drifted")
        return value

    def load_input(self, object_id: str) -> PlanningInput:
        with self.store.session() as conn:
            return self._load_input_conn(conn, object_id)

    def publish_proposal(self, value: PlanProposal) -> None:
        if not isinstance(value, PlanProposal):
            raise TypeError("value must be a PlanProposal")
        with self.store.session() as conn:
            planning_input = self._load_input_conn(conn, value.planning_input_id)
            try:
                value.bind(planning_input)
            except ProductionPlanningModelError as exc:
                raise ProductionPlanningEvidenceError("PlanProposal failed exact PlanningInput binding") from exc
            self._insert_evidence(
                conn,
                "plan_proposals",
                "proposal_id",
                value.proposal_id,
                value.content_hash,
                value.to_dict(),
                ("planning_input_id",),
                (value.planning_input_id,),
            )

    def _load_proposal_conn(self, conn: sqlite3.Connection, object_id: str) -> PlanProposal:
        payload, expected_hash = self._load_payload(conn, "plan_proposals", "proposal_id", object_id)
        value = _proposal_from_dict(payload)
        if value.content_hash != expected_hash:
            raise ProductionPlanningEvidenceError("PlanProposal canonical hash drifted")
        planning_input = self._load_input_conn(conn, value.planning_input_id)
        try:
            value.bind(planning_input)
        except ProductionPlanningModelError as exc:
            raise ProductionPlanningEvidenceError("stored PlanProposal binding drifted") from exc
        return value

    def load_proposal(self, object_id: str) -> PlanProposal:
        with self.store.session() as conn:
            return self._load_proposal_conn(conn, object_id)

    @staticmethod
    def _assert_audit_matches(
        planning_input: PlanningInput,
        proposal: PlanProposal,
        value: PlanAudit,
    ) -> None:
        expected = audit_plan(planning_input, proposal)
        fields = (
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
        )
        if any(getattr(value, field) != getattr(expected, field) for field in fields):
            raise ProductionPlanningEvidenceError("PlanAudit disagrees with independent recomputation")

    def publish_audit(self, value: PlanAudit) -> None:
        if not isinstance(value, PlanAudit):
            raise TypeError("value must be a PlanAudit")
        with self.store.session() as conn:
            planning_input = self._load_input_conn(conn, value.planning_input_id)
            proposal = self._load_proposal_conn(conn, value.proposal_id)
            self._assert_audit_matches(planning_input, proposal, value)
            self._insert_evidence(
                conn,
                "plan_audits",
                "audit_id",
                value.audit_id,
                value.content_hash,
                value.to_dict(),
                ("planning_input_id", "proposal_id", "status"),
                (value.planning_input_id, value.proposal_id, value.status.value),
            )

    def _load_audit_conn(self, conn: sqlite3.Connection, object_id: str) -> PlanAudit:
        payload, expected_hash = self._load_payload(conn, "plan_audits", "audit_id", object_id)
        value = _audit_from_dict(payload)
        if value.content_hash != expected_hash:
            raise ProductionPlanningEvidenceError("PlanAudit canonical hash drifted")
        planning_input = self._load_input_conn(conn, value.planning_input_id)
        proposal = self._load_proposal_conn(conn, value.proposal_id)
        self._assert_audit_matches(planning_input, proposal, value)
        return value

    def load_audit(self, object_id: str) -> PlanAudit:
        with self.store.session() as conn:
            return self._load_audit_conn(conn, object_id)

    def materialize(
        self,
        *,
        planning_input_id: str,
        proposal_id: str,
        audit_id: str,
    ) -> PlanMaterialization:
        project_id = self.runtime.project_id()
        try:
            with self.store.session() as conn:
                planning_input = self._load_input_conn(conn, planning_input_id)
                proposal = self._load_proposal_conn(conn, proposal_id)
                audit = self._load_audit_conn(conn, audit_id)
                if proposal.planning_input_id != planning_input.planning_input_id:
                    raise ProductionPlanningEvidenceError("proposal/input identity mismatch")
                if audit.planning_input_id != planning_input.planning_input_id or audit.proposal_id != proposal.proposal_id:
                    raise ProductionPlanningEvidenceError("audit does not bind the requested plan")
                if audit.status is not PlanAuditStatus.PASS:
                    raise ProductionPlanningEvidenceError("only a passing structural audit may materialize")
                goal = conn.execute(
                    "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                    (planning_input.goal_id, project_id),
                ).fetchone()
                if goal is None:
                    raise KeyError(planning_input.goal_id)
                if (
                    int(goal["revision"]) != planning_input.goal_revision
                    or goal_planning_hash(goal) != planning_input.goal_content_hash
                ):
                    raise ProductionPlanningEvidenceError("planning input became stale before materialization")
                if conn.execute(
                    "SELECT 1 FROM plan_materializations WHERE proposal_id = ?",
                    (proposal.proposal_id,),
                ).fetchone() is not None:
                    raise ProductionPlanningEvidenceError("plan proposal was already materialized")

                now = utc_now()
                materialization_id = new_id(IdKind.PLAN_MATERIALIZATION)
                flow_id = new_id(IdKind.FLOW)
                task_ids = {step.step_key: new_id(IdKind.TASK) for step in proposal.steps}

                conn.execute(
                    """INSERT INTO flows(
                           id, goal_id, status, revision, controller, state_json,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, 0, 'production-planning-v1', '{}', ?, ?)""",
                    (flow_id, planning_input.goal_id, FlowStatus.QUEUED.value, now, now),
                )
                self._append_event(
                    conn,
                    aggregate_type="FLOW",
                    aggregate_id=flow_id,
                    event_type="FLOW_CREATED",
                    new_state=FlowStatus.QUEUED.value,
                    metadata={"planning_proposal_id": proposal.proposal_id},
                    created_at=now,
                )

                for step in proposal.steps:
                    task_id = task_ids[step.step_key]
                    conn.execute(
                        """INSERT INTO tasks(
                               id, flow_id, parent_task_id, objective,
                               acceptance_criteria_json, constraints_json,
                               required_capabilities_json, budget_json, priority,
                               status, revision, attempt_count, created_at, updated_at
                           ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                        (
                            task_id,
                            flow_id,
                            step.objective,
                            _canonical_text(list(step.acceptance_criteria)),
                            _canonical_text(list(step.constraints)),
                            _canonical_text(list(step.required_capabilities)),
                            _canonical_text({"attempts": step.max_attempts}),
                            step.priority,
                            TaskStatus.QUEUED.value,
                            now,
                            now,
                        ),
                    )
                    self._append_event(
                        conn,
                        aggregate_type="TASK",
                        aggregate_id=task_id,
                        event_type="TASK_CREATED",
                        new_state=TaskStatus.QUEUED.value,
                        metadata={
                            "objective": step.objective,
                            "planning_proposal_id": proposal.proposal_id,
                            "planning_step_key": step.step_key,
                        },
                        created_at=now,
                    )

                for step in proposal.steps:
                    task_id = task_ids[step.step_key]
                    for dependency_key in step.depends_on:
                        required_task_id = task_ids[dependency_key]
                        conn.execute(
                            """INSERT INTO task_dependencies(
                                   task_id, required_task_id, dependency_type, created_at
                               ) VALUES (?, ?, ?, ?)""",
                            (
                                task_id,
                                required_task_id,
                                TaskDependencyType.REQUIRES_SUCCESS.value,
                                now,
                            ),
                        )
                        self._append_event(
                            conn,
                            aggregate_type="TASK_DEPENDENCY",
                            aggregate_id=f"{task_id}|{required_task_id}",
                            event_type="TASK_DEPENDENCY_CREATED",
                            new_state=TaskDependencyType.REQUIRES_SUCCESS.value,
                            metadata={
                                "task_id": task_id,
                                "required_task_id": required_task_id,
                                "dependency_type": TaskDependencyType.REQUIRES_SUCCESS.value,
                                "planning_proposal_id": proposal.proposal_id,
                            },
                            created_at=now,
                        )

                materialization = PlanMaterialization(
                    materialization_id=materialization_id,
                    planning_input_id=planning_input.planning_input_id,
                    planning_input_hash=planning_input.content_hash,
                    proposal_id=proposal.proposal_id,
                    proposal_hash=proposal.content_hash,
                    audit_id=audit.audit_id,
                    audit_hash=audit.content_hash,
                    goal_id=planning_input.goal_id,
                    goal_revision=planning_input.goal_revision,
                    flow_id=flow_id,
                    task_bindings=tuple(
                        MaterializedTaskBinding(step.step_key, task_ids[step.step_key])
                        for step in proposal.steps
                    ),
                )
                conn.execute(
                    """INSERT INTO plan_materializations(
                           materialization_id, planning_input_id, proposal_id, audit_id,
                           goal_id, flow_id, schema_version, content_hash, payload_json,
                           created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        materialization.materialization_id,
                        materialization.planning_input_id,
                        materialization.proposal_id,
                        materialization.audit_id,
                        materialization.goal_id,
                        materialization.flow_id,
                        _SCHEMA_VERSION,
                        materialization.content_hash,
                        _canonical_text(materialization.to_dict()),
                        now,
                    ),
                )
                return materialization
        except sqlite3.IntegrityError as exc:
            raise ProductionPlanningEvidenceError("atomic plan materialization failed") from exc

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        new_state: str,
        metadata: dict[str, object],
        created_at: str,
    ) -> None:
        conn.execute(
            """INSERT INTO state_events(
                   id, aggregate_type, aggregate_id, event_type, old_state,
                   new_state, revision, actor_type, actor_id, metadata_json,
                   created_at
               ) VALUES (?, ?, ?, ?, NULL, ?, NULL, 'SYSTEM', NULL, ?, ?)""",
            (
                new_id(IdKind.EVENT),
                aggregate_type,
                aggregate_id,
                event_type,
                new_state,
                _canonical_text(metadata),
                created_at,
            ),
        )
