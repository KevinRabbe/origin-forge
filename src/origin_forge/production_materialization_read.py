from __future__ import annotations

import json
from typing import Any

from .ids import IdKind, validate_id
from .production_planning_evidence import (
    MaterializedTaskBinding,
    PlanMaterialization,
    ProductionPlanningEvidenceError,
)
from .runtime import OriginForgeRuntime


class ProductionMaterializationReadError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProductionMaterializationReadError(
                f"duplicate materialization JSON key: {key}"
            )
        value[key] = item
    return value


def _materialization_from_payload(payload: object) -> PlanMaterialization:
    if not isinstance(payload, dict):
        raise ProductionMaterializationReadError(
            "stored plan materialization payload is not an object"
        )
    expected_keys = {
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
    if set(payload) != expected_keys:
        raise ProductionMaterializationReadError(
            "stored plan materialization payload schema drifted"
        )
    raw_bindings = payload["task_bindings"]
    if not isinstance(raw_bindings, list):
        raise ProductionMaterializationReadError(
            "stored plan materialization task bindings are invalid"
        )
    try:
        bindings: list[MaterializedTaskBinding] = []
        for raw_binding in raw_bindings:
            if not isinstance(raw_binding, dict) or set(raw_binding) != {
                "step_key",
                "task_id",
            }:
                raise ProductionMaterializationReadError(
                    "stored plan materialization task binding schema drifted"
                )
            bindings.append(
                MaterializedTaskBinding(
                    step_key=raw_binding["step_key"],
                    task_id=raw_binding["task_id"],
                )
            )
        return PlanMaterialization(
            materialization_id=payload["materialization_id"],
            planning_input_id=payload["planning_input_id"],
            planning_input_hash=payload["planning_input_hash"],
            proposal_id=payload["proposal_id"],
            proposal_hash=payload["proposal_hash"],
            audit_id=payload["audit_id"],
            audit_hash=payload["audit_hash"],
            goal_id=payload["goal_id"],
            goal_revision=payload["goal_revision"],
            flow_id=payload["flow_id"],
            task_bindings=tuple(bindings),
        )
    except ProductionMaterializationReadError:
        raise
    except (ProductionPlanningEvidenceError, TypeError, ValueError) as exc:
        raise ProductionMaterializationReadError(
            "stored plan materialization failed canonical validation"
        ) from exc


def read_plan_materialization(
    runtime: OriginForgeRuntime,
    materialization_id: str,
) -> PlanMaterialization:
    """Read and cross-check one durable plan materialization without creating work."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(materialization_id, str) or not validate_id(
        materialization_id,
        IdKind.PLAN_MATERIALIZATION,
    ):
        raise ValueError("materialization_id must be a PLMAT ID")

    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        row = conn.execute(
            """SELECT pm.materialization_id, pm.planning_input_id, pm.proposal_id,
                      pm.audit_id, pm.goal_id, pm.flow_id, pm.content_hash,
                      pm.payload_json
               FROM plan_materializations AS pm
               JOIN goals AS g ON g.id = pm.goal_id
               WHERE pm.materialization_id = ? AND g.project_id = ?""",
            (materialization_id, project_id),
        ).fetchone()
        if row is None:
            raise KeyError(materialization_id)
        raw_payload = row["payload_json"]
        if not isinstance(raw_payload, str):
            raise ProductionMaterializationReadError(
                "stored plan materialization payload is not JSON text"
            )
        try:
            payload = json.loads(raw_payload, object_pairs_hook=_strict_object)
        except ProductionMaterializationReadError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ProductionMaterializationReadError(
                "stored plan materialization payload is invalid JSON"
            ) from exc
        materialization = _materialization_from_payload(payload)
        if materialization.materialization_id != materialization_id:
            raise ProductionMaterializationReadError(
                "stored plan materialization identity drifted"
            )
        denormalized = (
            ("planning_input_id", materialization.planning_input_id),
            ("proposal_id", materialization.proposal_id),
            ("audit_id", materialization.audit_id),
            ("goal_id", materialization.goal_id),
            ("flow_id", materialization.flow_id),
        )
        if any(row[field] != value for field, value in denormalized):
            raise ProductionMaterializationReadError(
                "stored plan materialization columns drifted from payload"
            )
        if row["content_hash"] != materialization.content_hash:
            raise ProductionMaterializationReadError(
                "stored plan materialization content hash drifted"
            )

        flow = conn.execute(
            "SELECT id FROM flows WHERE id = ? AND goal_id = ?",
            (materialization.flow_id, materialization.goal_id),
        ).fetchone()
        if flow is None:
            raise ProductionMaterializationReadError(
                "materialized Flow is missing or escaped its Goal"
            )
        task_ids = tuple(binding.task_id for binding in materialization.task_bindings)
        placeholders = ",".join("?" for _ in task_ids)
        task_rows = conn.execute(
            f"SELECT id FROM tasks WHERE flow_id = ? AND id IN ({placeholders})",
            (materialization.flow_id, *task_ids),
        ).fetchall()
        if {str(task["id"]) for task in task_rows} != set(task_ids):
            raise ProductionMaterializationReadError(
                "materialized Tasks are missing or escaped their Flow"
            )
        return materialization
