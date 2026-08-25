from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .ids import IdKind, validate_id
from .model3d_requests import Model3DRequestError, _project
from .production_capability_routing import TaskRouteInput, _task_payload
from .production_design_specification_currentness import (
    AcceptedDesignError,
    AcceptedDesignInspection,
    _expected_planning_fields,
    _matches_expected_planning_input,
    inspect_accepted_design,
)
from .production_design_specification_evidence import DesignSpecificationEvidenceStore
from .production_model3d_request_authoring_models import (
    Model3DRequestAudit,
    Model3DRequestAuditStatus,
    Model3DRequestAuthoringModelError,
    Model3DRequestInput,
    Model3DRequestProposal,
    canonical_hash,
)
from .production_planning_evidence import (
    MaterializedTaskBinding,
    PlanMaterialization,
    ProductionPlanningEvidenceError,
    ProductionPlanningEvidenceStore,
)
from .production_planning_models import PlanAuditStatus, PlanProposal, PlanningInput
from .production_read_guard import production_read_connection
from .runtime import OriginForgeRuntime
from .service import utc_now


_SCHEMA_VERSION = 1
_MAX_PAYLOAD_BYTES = 1024 * 1024


class Model3DRequestAuthoringEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Model3DRequestLineage:
    task_route_input: TaskRouteInput
    materialization: PlanMaterialization
    planning_input: PlanningInput
    planning_proposal: PlanProposal
    planning_audit_id: str
    planning_audit_hash: str
    planning_step_key: str
    accepted_design: AcceptedDesignInspection

    def context(self) -> dict[str, object]:
        accepted = self.accepted_design
        return {
            "schema_version": 1,
            "translation_contract_version": "model3d-semantic-translation-v1",
            "request_contract": {
                "schema_version": 1,
                "operation": "EXPORT_GLB",
                "project_schema_version": 1,
            },
            "task": self.task_route_input.to_dict(),
            "planning": {
                "materialization_id": self.materialization.materialization_id,
                "materialization_hash": self.materialization.content_hash,
                "planning_input_id": self.planning_input.planning_input_id,
                "planning_input_hash": self.planning_input.content_hash,
                "planning_proposal_id": self.planning_proposal.proposal_id,
                "planning_proposal_hash": self.planning_proposal.content_hash,
                "planning_audit_id": self.planning_audit_id,
                "planning_audit_hash": self.planning_audit_hash,
                "step_key": self.planning_step_key,
            },
            "accepted_design": {
                "acceptance": accepted.acceptance.to_dict(),
                "design_input": accepted.design_input.to_dict(),
                "specification": accepted.specification.to_dict(),
                "audit": accepted.audit.to_dict(),
            },
        }


@dataclass(frozen=True)
class Model3DRequestInputInspection:
    request_input: Model3DRequestInput
    current: bool
    stale_reason: str | None

    def __post_init__(self) -> None:
        if self.current != (self.stale_reason is None):
            raise Model3DRequestAuthoringEvidenceError(
                "MODEL3D request input currentness result is inconsistent"
            )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Model3DRequestAuthoringEvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_text(value: object) -> str:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise Model3DRequestAuthoringEvidenceError(
            "MODEL3D request evidence is not canonical JSON"
        ) from exc
    if not raw or len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise Model3DRequestAuthoringEvidenceError(
            "MODEL3D request evidence is outside byte bounds"
        )
    return raw


def _decode_payload(raw: object) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise Model3DRequestAuthoringEvidenceError("stored payload is outside bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except Model3DRequestAuthoringEvidenceError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise Model3DRequestAuthoringEvidenceError("stored payload is invalid JSON") from exc
    if not isinstance(value, dict) or _canonical_text(value) != raw:
        raise Model3DRequestAuthoringEvidenceError("stored payload is not canonical JSON")
    return value


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise Model3DRequestAuthoringEvidenceError(f"{label} schema drifted")
    return value


def _materialization_from_payload(value: dict[str, Any]) -> PlanMaterialization:
    _exact_keys(
        value,
        {
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
        },
        "PlanMaterialization",
    )
    if not isinstance(value["task_bindings"], list):
        raise Model3DRequestAuthoringEvidenceError(
            "PlanMaterialization task_bindings are invalid"
        )
    bindings: list[MaterializedTaskBinding] = []
    for item in value["task_bindings"]:
        raw = _exact_keys(item, {"step_key", "task_id"}, "materialized Task binding")
        try:
            bindings.append(MaterializedTaskBinding(raw["step_key"], raw["task_id"]))
        except (ProductionPlanningEvidenceError, TypeError, ValueError) as exc:
            raise Model3DRequestAuthoringEvidenceError(
                "materialized Task binding failed validation"
            ) from exc
    try:
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
        raise Model3DRequestAuthoringEvidenceError(
            "PlanMaterialization failed typed validation"
        ) from exc


def _assert_task_matches_step(task_payload: dict[str, object], step: object, flow_id: str) -> None:
    expected = {
        "flow_id": flow_id,
        "parent_task_id": None,
        "objective": step.objective,
        "acceptance_criteria": list(step.acceptance_criteria),
        "constraints": list(step.constraints),
        "required_capabilities": list(step.required_capabilities),
        "budget": {"attempts": step.max_attempts},
        "priority": step.priority,
    }
    for field, value in expected.items():
        if task_payload[field] != value:
            raise Model3DRequestAuthoringEvidenceError(
                f"materialized Task {field} drifted from Phase-31 proposal"
            )


def resolve_model3d_request_lineage(
    runtime: OriginForgeRuntime,
    task_id: str,
) -> Model3DRequestLineage:
    """Reconstruct exact current Task -> Phase-31 -> accepted-design provenance."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(task_id, IdKind.TASK):
        raise Model3DRequestAuthoringEvidenceError("task_id must be a TASK ID")
    project_id = runtime.project_id()
    planning_store = ProductionPlanningEvidenceStore(runtime)

    with production_read_connection(runtime) as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            raise KeyError(task_id)
        task_route_input = TaskRouteInput.from_row(task)
        task_payload = _task_payload(task)
        flow = conn.execute(
            "SELECT id, goal_id FROM flows WHERE id = ?", (task_route_input.flow_id,)
        ).fetchone()
        if flow is None:
            raise Model3DRequestAuthoringEvidenceError("Task references a missing Flow")
        goal = conn.execute(
            "SELECT id, project_id FROM goals WHERE id = ?", (flow["goal_id"],)
        ).fetchone()
        if goal is None or goal["project_id"] != project_id:
            raise Model3DRequestAuthoringEvidenceError(
                "Task belongs to another project or missing Goal"
            )

        rows = conn.execute(
            """SELECT materialization_id
               FROM plan_materializations
               WHERE flow_id = ?
               ORDER BY materialization_id""",
            (task_route_input.flow_id,),
        ).fetchall()
        if len(rows) != 1:
            raise Model3DRequestAuthoringEvidenceError(
                "Task Phase-31 materialization relation is missing or ambiguous"
            )
        materialization_id = rows[0]["materialization_id"]
        try:
            materialization_payload, materialization_hash = planning_store._load_payload(
                conn,
                "plan_materializations",
                "materialization_id",
                materialization_id,
            )
            materialization = _materialization_from_payload(materialization_payload)
            planning_input = planning_store._load_input_conn(
                conn, materialization.planning_input_id
            )
            proposal = planning_store._load_proposal_conn(conn, materialization.proposal_id)
            audit = planning_store._load_audit_conn(conn, materialization.audit_id)
        except (ProductionPlanningEvidenceError, KeyError) as exc:
            raise Model3DRequestAuthoringEvidenceError(
                "Phase-31 lineage failed canonical validation"
            ) from exc
        if materialization.content_hash != materialization_hash:
            raise Model3DRequestAuthoringEvidenceError(
                "Phase-31 materialization canonical hash drifted"
            )
        if (
            materialization.flow_id != task_route_input.flow_id
            or materialization.goal_id != flow["goal_id"]
            or materialization.planning_input_hash != planning_input.content_hash
            or materialization.proposal_hash != proposal.content_hash
            or materialization.audit_hash != audit.content_hash
            or audit.status is not PlanAuditStatus.PASS
        ):
            raise Model3DRequestAuthoringEvidenceError(
                "Phase-31 materialization lineage is inconsistent"
            )
        matches = [
            binding
            for binding in materialization.task_bindings
            if binding.task_id == task_id
        ]
        if len(matches) != 1:
            raise Model3DRequestAuthoringEvidenceError(
                "Task is not uniquely bound by its Phase-31 materialization"
            )
        step_key = matches[0].step_key
        steps = [step for step in proposal.steps if step.step_key == step_key]
        if len(steps) != 1:
            raise Model3DRequestAuthoringEvidenceError(
                "materialized Task step is missing from Phase-31 proposal"
            )
        _assert_task_matches_step(task_payload, steps[0], materialization.flow_id)
        if (
            planning_input.project_id != project_id
            or planning_input.goal_id != materialization.goal_id
            or planning_input.goal_revision != materialization.goal_revision
        ):
            raise Model3DRequestAuthoringEvidenceError(
                "PlanningInput project/Goal relation drifted"
            )
        acceptance_refs = tuple(
            ref
            for ref in planning_input.verified_state_refs
            if validate_id(ref.ref_id, IdKind.DESIGN_SPECIFICATION_ACCEPTANCE)
        )
        if len(acceptance_refs) != 1:
            raise Model3DRequestAuthoringEvidenceError(
                "PlanningInput does not carry exactly one DESIGNACC reference"
            )
        acceptance_ref = acceptance_refs[0]
        planning_audit_id = audit.audit_id
        planning_audit_hash = audit.content_hash

    try:
        accepted = inspect_accepted_design(runtime, acceptance_ref.ref_id)
    except (AcceptedDesignError, KeyError) as exc:
        raise Model3DRequestAuthoringEvidenceError(
            "accepted-design lineage failed canonical validation"
        ) from exc
    if not accepted.current:
        raise Model3DRequestAuthoringEvidenceError(
            f"accepted-design lineage is stale: {accepted.stale_reason}"
        )
    if acceptance_ref.content_hash != accepted.acceptance.content_hash:
        raise Model3DRequestAuthoringEvidenceError(
            "PlanningInput DESIGNACC hash does not match accepted design"
        )
    design_evidence = DesignSpecificationEvidenceStore(runtime)
    expected = _expected_planning_fields(design_evidence, accepted)
    if not _matches_expected_planning_input(planning_input, expected):
        raise Model3DRequestAuthoringEvidenceError(
            "PlanningInput is not the exact accepted-design bridge relation"
        )

    return Model3DRequestLineage(
        task_route_input=task_route_input,
        materialization=materialization,
        planning_input=planning_input,
        planning_proposal=proposal,
        planning_audit_id=planning_audit_id,
        planning_audit_hash=planning_audit_hash,
        planning_step_key=step_key,
        accepted_design=accepted,
    )


def _input_fields(lineage: Model3DRequestLineage) -> dict[str, object]:
    accepted = lineage.accepted_design
    context_hash = canonical_hash(lineage.context())
    return {
        "project_id": accepted.acceptance.project_id,
        "task_id": lineage.task_route_input.task_id,
        "flow_id": lineage.task_route_input.flow_id,
        "task_revision": lineage.task_route_input.task_revision,
        "task_content_hash": lineage.task_route_input.task_content_hash,
        "materialization_id": lineage.materialization.materialization_id,
        "materialization_hash": lineage.materialization.content_hash,
        "planning_input_id": lineage.planning_input.planning_input_id,
        "planning_input_hash": lineage.planning_input.content_hash,
        "planning_proposal_id": lineage.planning_proposal.proposal_id,
        "planning_proposal_hash": lineage.planning_proposal.content_hash,
        "planning_audit_id": lineage.planning_audit_id,
        "planning_audit_hash": lineage.planning_audit_hash,
        "design_acceptance_id": accepted.acceptance.acceptance_id,
        "design_acceptance_hash": accepted.acceptance.content_hash,
        "design_specification_id": accepted.specification.design_specification_id,
        "design_specification_hash": accepted.specification.content_hash,
        "design_input_id": accepted.design_input.design_input_id,
        "design_input_hash": accepted.design_input.content_hash,
        "goal_id": accepted.acceptance.goal_id,
        "goal_revision": accepted.design_input.goal_revision,
        "goal_content_hash": accepted.design_input.goal_content_hash,
        "context_hash": context_hash,
    }


def _input_from_dict(value: dict[str, Any]) -> Model3DRequestInput:
    keys = {
        "request_input_id",
        "project_id",
        "task_id",
        "flow_id",
        "task_revision",
        "task_content_hash",
        "materialization_id",
        "materialization_hash",
        "planning_input_id",
        "planning_input_hash",
        "planning_proposal_id",
        "planning_proposal_hash",
        "planning_audit_id",
        "planning_audit_hash",
        "design_acceptance_id",
        "design_acceptance_hash",
        "design_specification_id",
        "design_specification_hash",
        "design_input_id",
        "design_input_hash",
        "goal_id",
        "goal_revision",
        "goal_content_hash",
        "context_hash",
        "translation_contract_version",
        "request_schema_version",
        "request_operation",
        "schema_version",
    }
    raw = _exact_keys(value, keys, "M3DREQIN")
    try:
        return Model3DRequestInput(**raw)
    except (Model3DRequestAuthoringModelError, TypeError, ValueError) as exc:
        raise Model3DRequestAuthoringEvidenceError("M3DREQIN failed typed validation") from exc


def _proposal_from_dict(value: dict[str, Any]) -> Model3DRequestProposal:
    raw = _exact_keys(
        value,
        {
            "proposal_id",
            "request_input_id",
            "request_input_hash",
            "run_id",
            "model_id",
            "model_hash",
            "response_text",
            "response_hash",
            "operation",
            "project",
            "project_hash",
            "schema_version",
        },
        "M3DREQPROP",
    )
    try:
        project = _project(raw["project"])
        if raw["project_hash"] != project.content_hash:
            raise Model3DRequestAuthoringEvidenceError(
                "M3DREQPROP project hash drifted"
            )
        from .model3d_requests import Model3DRequestOperation

        return Model3DRequestProposal(
            proposal_id=raw["proposal_id"],
            request_input_id=raw["request_input_id"],
            request_input_hash=raw["request_input_hash"],
            run_id=raw["run_id"],
            model_id=raw["model_id"],
            model_hash=raw["model_hash"],
            response_text=raw["response_text"],
            response_hash=raw["response_hash"],
            operation=Model3DRequestOperation(raw["operation"]),
            project=project,
            schema_version=raw["schema_version"],
        )
    except Model3DRequestAuthoringEvidenceError:
        raise
    except (Model3DRequestError, Model3DRequestAuthoringModelError, TypeError, ValueError) as exc:
        raise Model3DRequestAuthoringEvidenceError(
            "M3DREQPROP failed typed validation"
        ) from exc


def _audit_from_dict(value: dict[str, Any]) -> Model3DRequestAudit:
    raw = _exact_keys(
        value,
        {
            "audit_id",
            "request_input_id",
            "request_input_hash",
            "proposal_id",
            "proposal_hash",
            "response_hash",
            "project_hash",
            "status",
            "failure_reason",
            "schema_version",
        },
        "M3DREQAUD",
    )
    try:
        return Model3DRequestAudit(
            audit_id=raw["audit_id"],
            request_input_id=raw["request_input_id"],
            request_input_hash=raw["request_input_hash"],
            proposal_id=raw["proposal_id"],
            proposal_hash=raw["proposal_hash"],
            response_hash=raw["response_hash"],
            project_hash=raw["project_hash"],
            status=Model3DRequestAuditStatus(raw["status"]),
            failure_reason=raw["failure_reason"],
            schema_version=raw["schema_version"],
        )
    except (Model3DRequestAuthoringModelError, TypeError, ValueError) as exc:
        raise Model3DRequestAuthoringEvidenceError("M3DREQAUD failed typed validation") from exc


class Model3DRequestAuthoringEvidenceStore:
    """Immutable v22 Phase-57A evidence; no MODEL3DREQ publication authority."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    @staticmethod
    def _insert(
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
        placeholders = ",".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",
            values,
        )

    @staticmethod
    def _load_payload(
        conn: sqlite3.Connection,
        *,
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
            raise Model3DRequestAuthoringEvidenceError(
                f"{table} schema version drifted"
            )
        payload = _decode_payload(row["payload_json"])
        if canonical_hash(payload) != row["content_hash"]:
            raise Model3DRequestAuthoringEvidenceError(f"{table} content hash drifted")
        return payload, row["content_hash"]

    def _load_input_conn(
        self, conn: sqlite3.Connection, request_input_id: str
    ) -> Model3DRequestInput:
        payload, expected_hash = self._load_payload(
            conn,
            table="model3d_request_inputs",
            id_column="request_input_id",
            object_id=request_input_id,
        )
        value = _input_from_dict(payload)
        if value.content_hash != expected_hash:
            raise Model3DRequestAuthoringEvidenceError("M3DREQIN canonical hash drifted")
        return value

    def load_input(self, request_input_id: str) -> Model3DRequestInput:
        with production_read_connection(self.runtime) as conn:
            return self._load_input_conn(conn, request_input_id)

    def publish_input(self, value: Model3DRequestInput) -> Model3DRequestInput:
        if not isinstance(value, Model3DRequestInput):
            raise TypeError("value must be a Model3DRequestInput")
        if value.project_id != self.runtime.project_id():
            raise Model3DRequestAuthoringEvidenceError("M3DREQIN belongs to another project")
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT request_input_id
                   FROM model3d_request_inputs
                   WHERE task_id = ? AND task_revision = ? AND task_content_hash = ?
                     AND materialization_id = ? AND planning_input_id = ?
                     AND design_acceptance_id = ? AND design_specification_id = ?
                   ORDER BY request_input_id""",
                (
                    value.task_id,
                    value.task_revision,
                    value.task_content_hash,
                    value.materialization_id,
                    value.planning_input_id,
                    value.design_acceptance_id,
                    value.design_specification_id,
                ),
            ).fetchall()
            if len(rows) > 1:
                raise Model3DRequestAuthoringEvidenceError(
                    "exact M3DREQIN recovery relation is ambiguous"
                )
            if rows:
                existing = self._load_input_conn(conn, rows[0]["request_input_id"])
                expected = value.to_dict()
                expected["request_input_id"] = existing.request_input_id
                if existing.to_dict() != expected:
                    raise Model3DRequestAuthoringEvidenceError(
                        "existing M3DREQIN exact lineage binding drifted"
                    )
                return existing
            try:
                self._insert(
                    conn,
                    table="model3d_request_inputs",
                    id_column="request_input_id",
                    object_id=value.request_input_id,
                    content_hash=value.content_hash,
                    payload=value.to_dict(),
                    extra_columns=(
                        "project_id",
                        "task_id",
                        "flow_id",
                        "task_revision",
                        "task_content_hash",
                        "materialization_id",
                        "planning_input_id",
                        "design_acceptance_id",
                        "design_specification_id",
                    ),
                    extra_values=(
                        value.project_id,
                        value.task_id,
                        value.flow_id,
                        value.task_revision,
                        value.task_content_hash,
                        value.materialization_id,
                        value.planning_input_id,
                        value.design_acceptance_id,
                        value.design_specification_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise Model3DRequestAuthoringEvidenceError(
                    "M3DREQIN publication relation failed"
                ) from exc
        return value

    def _load_proposal_conn(
        self, conn: sqlite3.Connection, proposal_id: str
    ) -> Model3DRequestProposal:
        payload, expected_hash = self._load_payload(
            conn,
            table="model3d_request_proposals",
            id_column="proposal_id",
            object_id=proposal_id,
        )
        value = _proposal_from_dict(payload)
        if value.content_hash != expected_hash:
            raise Model3DRequestAuthoringEvidenceError("M3DREQPROP canonical hash drifted")
        request_input = self._load_input_conn(conn, value.request_input_id)
        try:
            value.bind(request_input)
        except Model3DRequestAuthoringModelError as exc:
            raise Model3DRequestAuthoringEvidenceError(
                "M3DREQPROP input binding drifted"
            ) from exc
        return value

    def load_proposal(self, proposal_id: str) -> Model3DRequestProposal:
        with production_read_connection(self.runtime) as conn:
            return self._load_proposal_conn(conn, proposal_id)

    def publish_proposal(self, value: Model3DRequestProposal) -> None:
        if not isinstance(value, Model3DRequestProposal):
            raise TypeError("value must be a Model3DRequestProposal")
        with self.runtime.store.session() as conn:
            request_input = self._load_input_conn(conn, value.request_input_id)
            try:
                value.bind(request_input)
            except Model3DRequestAuthoringModelError as exc:
                raise Model3DRequestAuthoringEvidenceError(
                    "M3DREQPROP failed exact input binding"
                ) from exc
            try:
                self._insert(
                    conn,
                    table="model3d_request_proposals",
                    id_column="proposal_id",
                    object_id=value.proposal_id,
                    content_hash=value.content_hash,
                    payload=value.to_dict(),
                    extra_columns=("request_input_id", "run_id"),
                    extra_values=(value.request_input_id, value.run_id),
                )
            except sqlite3.IntegrityError as exc:
                raise Model3DRequestAuthoringEvidenceError(
                    "M3DREQPROP evidence already exists or is invalid"
                ) from exc

    def _load_audit_conn(
        self, conn: sqlite3.Connection, audit_id: str
    ) -> Model3DRequestAudit:
        payload, expected_hash = self._load_payload(
            conn,
            table="model3d_request_audits",
            id_column="audit_id",
            object_id=audit_id,
        )
        value = _audit_from_dict(payload)
        if value.content_hash != expected_hash:
            raise Model3DRequestAuthoringEvidenceError("M3DREQAUD canonical hash drifted")
        request_input = self._load_input_conn(conn, value.request_input_id)
        proposal = self._load_proposal_conn(conn, value.proposal_id)
        if (
            value.request_input_hash != request_input.content_hash
            or value.proposal_hash != proposal.content_hash
            or value.response_hash != proposal.response_hash
            or value.project_hash != proposal.project.content_hash
        ):
            raise Model3DRequestAuthoringEvidenceError(
                "M3DREQAUD exact evidence relation drifted"
            )
        return value

    def load_audit(self, audit_id: str) -> Model3DRequestAudit:
        with production_read_connection(self.runtime) as conn:
            return self._load_audit_conn(conn, audit_id)

    def audit_for_proposal(self, proposal_id: str) -> Model3DRequestAudit | None:
        with production_read_connection(self.runtime) as conn:
            rows = conn.execute(
                "SELECT audit_id FROM model3d_request_audits WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise Model3DRequestAuthoringEvidenceError(
                    "M3DREQPROP audit relation is ambiguous"
                )
            return self._load_audit_conn(conn, rows[0]["audit_id"])

    def _publish_audit(self, value: Model3DRequestAudit) -> Model3DRequestAudit:
        if not isinstance(value, Model3DRequestAudit):
            raise TypeError("value must be a Model3DRequestAudit")
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT audit_id FROM model3d_request_audits WHERE proposal_id = ?",
                (value.proposal_id,),
            ).fetchall()
            if len(rows) > 1:
                raise Model3DRequestAuthoringEvidenceError(
                    "M3DREQPROP audit relation is ambiguous"
                )
            if rows:
                return self._load_audit_conn(conn, rows[0]["audit_id"])
            request_input = self._load_input_conn(conn, value.request_input_id)
            proposal = self._load_proposal_conn(conn, value.proposal_id)
            if (
                value.request_input_hash != request_input.content_hash
                or value.proposal_hash != proposal.content_hash
                or value.response_hash != proposal.response_hash
                or value.project_hash != proposal.project.content_hash
            ):
                raise Model3DRequestAuthoringEvidenceError(
                    "M3DREQAUD does not bind exact durable evidence"
                )
            try:
                self._insert(
                    conn,
                    table="model3d_request_audits",
                    id_column="audit_id",
                    object_id=value.audit_id,
                    content_hash=value.content_hash,
                    payload=value.to_dict(),
                    extra_columns=("request_input_id", "proposal_id", "status"),
                    extra_values=(
                        value.request_input_id,
                        value.proposal_id,
                        value.status.value,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise Model3DRequestAuthoringEvidenceError(
                    "M3DREQAUD publication relation failed"
                ) from exc
        return value


def freeze_model3d_request_input(
    runtime: OriginForgeRuntime,
    task_id: str,
    *,
    evidence_store: Model3DRequestAuthoringEvidenceStore | None = None,
) -> Model3DRequestInput:
    lineage = resolve_model3d_request_lineage(runtime, task_id)
    value = Model3DRequestInput.create(**_input_fields(lineage))
    store = evidence_store or Model3DRequestAuthoringEvidenceStore(runtime)
    published = store.publish_input(value)
    current = inspect_model3d_request_input(runtime, published.request_input_id, evidence_store=store)
    if not current.current:
        raise Model3DRequestAuthoringEvidenceError(
            f"M3DREQIN became stale during publication: {current.stale_reason}"
        )
    return published


def inspect_model3d_request_input(
    runtime: OriginForgeRuntime,
    request_input_id: str,
    *,
    evidence_store: Model3DRequestAuthoringEvidenceStore | None = None,
) -> Model3DRequestInputInspection:
    store = evidence_store or Model3DRequestAuthoringEvidenceStore(runtime)
    value = store.load_input(request_input_id)
    try:
        lineage = resolve_model3d_request_lineage(runtime, value.task_id)
        fields = _input_fields(lineage)
        for field, expected in fields.items():
            if getattr(value, field) != expected:
                return Model3DRequestInputInspection(
                    request_input=value,
                    current=False,
                    stale_reason=f"{field} no longer matches current governed lineage",
                )
        return Model3DRequestInputInspection(
            request_input=value,
            current=True,
            stale_reason=None,
        )
    except (Model3DRequestAuthoringEvidenceError, AcceptedDesignError, KeyError) as exc:
        return Model3DRequestInputInspection(
            request_input=value,
            current=False,
            stale_reason=str(exc)[:2048] or type(exc).__name__,
        )


def generation_context_for_input(
    runtime: OriginForgeRuntime,
    request_input_id: str,
    *,
    evidence_store: Model3DRequestAuthoringEvidenceStore | None = None,
) -> dict[str, object]:
    store = evidence_store or Model3DRequestAuthoringEvidenceStore(runtime)
    inspection = inspect_model3d_request_input(
        runtime, request_input_id, evidence_store=store
    )
    if not inspection.current:
        raise Model3DRequestAuthoringEvidenceError(
            f"M3DREQIN is stale: {inspection.stale_reason}"
        )
    lineage = resolve_model3d_request_lineage(runtime, inspection.request_input.task_id)
    context = lineage.context()
    if canonical_hash(context) != inspection.request_input.context_hash:
        raise Model3DRequestAuthoringEvidenceError(
            "M3DREQIN generation context hash drifted"
        )
    return context