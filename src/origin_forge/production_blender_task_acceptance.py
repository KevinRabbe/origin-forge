from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from .ids import IdKind, new_id, validate_id
from .path_policy import portable_relative_path
from .production_blender_adoption_receipt import (
    BlenderProductionAdoptionReceipt,
    BlenderProductionAdoptionStatus,
)
from .production_blender_dispatch_output_binding import BlenderDispatchOutputBinding
from .production_dispatch_binding_blender import (
    BLENDER_BINDER_ID,
    BLENDER_REQUEST_TYPE_ID,
)
from .production_dispatch_binding_models import DispatchBinding
from .production_work_order_blender import (
    BLENDER_ADAPTER_ID,
    BLENDER_CONTRACT_ID,
    BLENDER_OPERATION,
)
from .runtime import OriginForgeRuntime
from .service import utc_now


BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE = (
    "blender-production-task-acceptance"
)
BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFIER = (
    "OriginForge.GovernedBlenderProductionTaskAcceptor"
)
BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY = "HUMAN_OPERATOR"
BLENDER_PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION = 1
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUEST_PROJECTION_KEYS = frozenset(
    {
        "task_id",
        "model3d_request_id",
        "model3d_request_hash",
        "operation",
        "project",
        "project_hash",
    }
)


class BlenderProductionTaskAcceptanceError(RuntimeError):
    pass


class BlenderProductionTaskAcceptanceConflict(BlenderProductionTaskAcceptanceError):
    pass


@dataclass(frozen=True)
class BlenderProductionTaskAcceptanceReceipt:
    execution_id: str
    task_id: str
    adopted_artifact_id: str
    adoption_verification_id: str
    task_verification_id: str
    task_revision_at_acceptance: int
    accepted_content_hash: str
    accepted_byte_count: int
    accepted_destination_path: str
    acceptance_authority: str
    schema_version: int
    accepted_at: str

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.adopted_artifact_id, IdKind.ARTIFACT, "adopted_artifact_id"),
            (
                self.adoption_verification_id,
                IdKind.VERIFICATION,
                "adoption_verification_id",
            ),
            (
                self.task_verification_id,
                IdKind.VERIFICATION,
                "task_verification_id",
            ),
        ):
            if not isinstance(value, str) or not validate_id(value, kind):
                raise BlenderProductionTaskAcceptanceError(
                    f"{label} must be a valid {kind.value} ID"
                )
        if self.adoption_verification_id == self.task_verification_id:
            raise BlenderProductionTaskAcceptanceError(
                "adoption and Task Verification IDs must be distinct"
            )
        if (
            type(self.task_revision_at_acceptance) is not int
            or self.task_revision_at_acceptance < 0
        ):
            raise BlenderProductionTaskAcceptanceError(
                "task_revision_at_acceptance must be a non-negative integer"
            )
        if not isinstance(self.accepted_content_hash, str) or _HASH_RE.fullmatch(
            self.accepted_content_hash
        ) is None:
            raise BlenderProductionTaskAcceptanceError(
                "accepted_content_hash must be a canonical SHA-256 content hash"
            )
        if type(self.accepted_byte_count) is not int or self.accepted_byte_count <= 0:
            raise BlenderProductionTaskAcceptanceError(
                "accepted_byte_count must be a positive integer"
            )
        try:
            portable = portable_relative_path(self.accepted_destination_path)
        except ValueError as exc:
            raise BlenderProductionTaskAcceptanceError(
                "accepted_destination_path must be canonical project-relative text"
            ) from exc
        if portable.as_posix() != self.accepted_destination_path:
            raise BlenderProductionTaskAcceptanceError(
                "accepted_destination_path must be canonical project-relative text"
            )
        if self.acceptance_authority != BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY:
            raise BlenderProductionTaskAcceptanceError(
                "acceptance_authority must be HUMAN_OPERATOR"
            )
        if self.schema_version != BLENDER_PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION:
            raise BlenderProductionTaskAcceptanceError(
                "unsupported Blender production Task acceptance schema_version"
            )
        if (
            not isinstance(self.accepted_at, str)
            or not self.accepted_at
            or self.accepted_at.strip() != self.accepted_at
        ):
            raise BlenderProductionTaskAcceptanceError("accepted_at is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "adoption_verification_id": self.adoption_verification_id,
            "task_verification_id": self.task_verification_id,
            "task_revision_at_acceptance": self.task_revision_at_acceptance,
            "accepted_content_hash": self.accepted_content_hash,
            "accepted_byte_count": self.accepted_byte_count,
            "accepted_destination_path": self.accepted_destination_path,
            "acceptance_authority": self.acceptance_authority,
            "schema_version": self.schema_version,
            "accepted_at": self.accepted_at,
        }


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _from_row(row) -> BlenderProductionTaskAcceptanceReceipt:
    try:
        return BlenderProductionTaskAcceptanceReceipt(
            execution_id=row["execution_id"],
            task_id=row["task_id"],
            adopted_artifact_id=row["adopted_artifact_id"],
            adoption_verification_id=row["adoption_verification_id"],
            task_verification_id=row["task_verification_id"],
            task_revision_at_acceptance=row["task_revision_at_acceptance"],
            accepted_content_hash=row["accepted_content_hash"],
            accepted_byte_count=row["accepted_byte_count"],
            accepted_destination_path=row["accepted_destination_path"],
            acceptance_authority=row["acceptance_authority"],
            schema_version=row["schema_version"],
            accepted_at=row["accepted_at"],
        )
    except (KeyError, TypeError, ValueError, BlenderProductionTaskAcceptanceError) as exc:
        raise BlenderProductionTaskAcceptanceError(
            "stored Blender production Task acceptance failed canonical validation"
        ) from exc


def _semantic_request(
    output_binding: BlenderDispatchOutputBinding,
    dispatch_binding: DispatchBinding,
) -> tuple[str, str]:
    if (
        dispatch_binding.dispatch_binding_id != output_binding.dispatch_binding_id
        or dispatch_binding.content_hash != output_binding.dispatch_binding_hash
        or dispatch_binding.task_id != output_binding.task_id
        or dispatch_binding.task_content_hash != output_binding.task_content_hash
        or dispatch_binding.work_order_id != output_binding.work_order_id
        or dispatch_binding.work_order_hash != output_binding.work_order_hash
    ):
        raise BlenderProductionTaskAcceptanceError(
            "Phase-34 dispatch binding does not match the exact Blender production relation"
        )
    if (
        dispatch_binding.selected_adapter_id != BLENDER_ADAPTER_ID
        or dispatch_binding.dispatch_contract_id != BLENDER_CONTRACT_ID
        or dispatch_binding.binder_id != BLENDER_BINDER_ID
        or dispatch_binding.request_type_id != BLENDER_REQUEST_TYPE_ID
    ):
        raise BlenderProductionTaskAcceptanceError(
            "Phase-34 dispatch binding is not the reviewed Blender semantic binding"
        )
    projection = dispatch_binding.request_projection
    if not isinstance(projection, dict) or set(projection) != _REQUEST_PROJECTION_KEYS:
        raise BlenderProductionTaskAcceptanceError(
            "Blender semantic request projection has an unexpected shape"
        )
    request_id = projection.get("model3d_request_id")
    request_hash = projection.get("model3d_request_hash")
    if (
        projection.get("task_id") != output_binding.task_id
        or projection.get("operation") != BLENDER_OPERATION
        or not isinstance(projection.get("project"), dict)
        or not isinstance(projection.get("project_hash"), str)
        or _HASH_RE.fullmatch(projection["project_hash"]) is None
        or not isinstance(request_id, str)
        or not validate_id(request_id, IdKind.MODEL3D_REQUEST)
        or not isinstance(request_hash, str)
        or _HASH_RE.fullmatch(request_hash) is None
    ):
        raise BlenderProductionTaskAcceptanceError(
            "Blender semantic request projection is not canonical"
        )
    return request_id, request_hash


def _require_structural_relation(
    output_binding: BlenderDispatchOutputBinding,
    adoption: BlenderProductionAdoptionReceipt,
    dispatch_binding: DispatchBinding,
    task_revision_at_acceptance: int,
) -> tuple[str, str]:
    if adoption.status is not BlenderProductionAdoptionStatus.PUBLISHED:
        raise BlenderProductionTaskAcceptanceError(
            "Blender production Task acceptance requires a PUBLISHED adoption receipt"
        )
    if (
        adoption.execution_id != output_binding.execution_id
        or adoption.output_artifact_id != output_binding.output_artifact_id
        or adoption.adopted_artifact_id is None
        or adoption.verification_id is None
    ):
        raise BlenderProductionTaskAcceptanceError(
            "Blender production Task acceptance inputs do not name one structural production relation"
        )
    if type(task_revision_at_acceptance) is not int or task_revision_at_acceptance < 0:
        raise ValueError("task_revision_at_acceptance must be a non-negative integer")
    if output_binding.output_byte_count <= 0:
        raise BlenderProductionTaskAcceptanceError(
            "Blender production Task acceptance requires non-empty accepted output"
        )
    return _semantic_request(output_binding, dispatch_binding)


def _expected_evidence(
    output_binding: BlenderDispatchOutputBinding,
    adoption: BlenderProductionAdoptionReceipt,
    dispatch_binding: DispatchBinding,
    task_revision_at_acceptance: int,
) -> dict[str, object]:
    request_id, request_hash = _semantic_request(output_binding, dispatch_binding)
    return {
        "production_task_verified": True,
        "semantic_geometry_verified": True,
        "acceptance_authority": BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
        "production_dispatch_output_bound": True,
        "canonical_asset_adopted": True,
        "existing_asset_overwritten": False,
        "provenance_signed": False,
        "release_authorized": False,
        "dispatch_execution_id": output_binding.execution_id,
        "production_claim_id": output_binding.claim_id,
        "production_run_id": output_binding.run_id,
        "work_order_id": output_binding.work_order_id,
        "model3d_request_id": request_id,
        "model3d_request_hash": request_hash,
        "source_output_artifact_id": output_binding.output_artifact_id,
        "production_adoption_verification_id": adoption.verification_id,
        "adopted_artifact_id": adoption.adopted_artifact_id,
        "adopted_destination_path": adoption.destination_path,
        "accepted_content_hash": "sha256:" + output_binding.output_content_hash,
        "accepted_byte_count": output_binding.output_byte_count,
        "task_content_hash": output_binding.task_content_hash,
        "task_revision_at_acceptance": task_revision_at_acceptance,
    }


def _matches_request(
    receipt: BlenderProductionTaskAcceptanceReceipt,
    output_binding: BlenderDispatchOutputBinding,
    adoption: BlenderProductionAdoptionReceipt,
    task_revision_at_acceptance: int,
) -> bool:
    return (
        receipt.execution_id == output_binding.execution_id
        and receipt.task_id == output_binding.task_id
        and receipt.adopted_artifact_id == adoption.adopted_artifact_id
        and receipt.adoption_verification_id == adoption.verification_id
        and receipt.task_revision_at_acceptance == task_revision_at_acceptance
        and receipt.accepted_content_hash
        == "sha256:" + output_binding.output_content_hash
        and receipt.accepted_byte_count == output_binding.output_byte_count
        and receipt.accepted_destination_path == adoption.destination_path
        and receipt.acceptance_authority == BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY
        and receipt.schema_version == BLENDER_PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION
    )


def _require_exact_task_verification(
    conn: sqlite3.Connection,
    receipt: BlenderProductionTaskAcceptanceReceipt,
    output_binding: BlenderDispatchOutputBinding,
    adoption: BlenderProductionAdoptionReceipt,
    dispatch_binding: DispatchBinding,
) -> None:
    row = conn.execute(
        """SELECT target_type, target_id, verification_type, verifier, status,
                  evidence_json, metrics_json, run_id, created_at
           FROM verifications WHERE id = ?""",
        (receipt.task_verification_id,),
    ).fetchone()
    try:
        evidence = json.loads(row["evidence_json"]) if row is not None else None
        metrics = json.loads(row["metrics_json"]) if row is not None else None
    except (TypeError, json.JSONDecodeError) as exc:
        raise BlenderProductionTaskAcceptanceError(
            "Blender production Task acceptance Verification JSON is invalid"
        ) from exc
    if (
        row is None
        or row["target_type"] != "TASK"
        or row["target_id"] != output_binding.task_id
        or row["verification_type"]
        != BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE
        or row["verifier"] != BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFIER
        or row["status"] != "PASS"
        or evidence
        != _expected_evidence(
            output_binding,
            adoption,
            dispatch_binding,
            receipt.task_revision_at_acceptance,
        )
        or metrics != {}
        or row["run_id"] != output_binding.run_id
        or row["created_at"] != receipt.accepted_at
    ):
        raise BlenderProductionTaskAcceptanceError(
            "Blender production Task acceptance Verification is not exact"
        )


def read_blender_production_task_acceptance(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> BlenderProductionTaskAcceptanceReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise ValueError("execution_id must be a DISPEXEC ID")
    with runtime.store.session() as conn:
        row = conn.execute(
            "SELECT * FROM blender_production_task_acceptances WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
    if row is None:
        raise BlenderProductionTaskAcceptanceError(
            "Blender production Task acceptance does not exist"
        )
    return _from_row(row)


def publish_blender_production_task_acceptance(
    runtime: OriginForgeRuntime,
    output_binding: BlenderDispatchOutputBinding,
    adoption: BlenderProductionAdoptionReceipt,
    dispatch_binding: DispatchBinding,
    *,
    task_revision_at_acceptance: int,
    actor_id: str | None = None,
) -> BlenderProductionTaskAcceptanceReceipt:
    """Atomically publish one human-authorized Blender Task PASS and immutable receipt.

    Phase 53A deliberately accepts a prevalidated exact production snapshot. Full
    live currentness/eligibility is owned by Phase 53B; Task terminalization is
    also outside this publication transaction.
    """
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(output_binding, BlenderDispatchOutputBinding):
        raise TypeError("output_binding must be a BlenderDispatchOutputBinding")
    if not isinstance(adoption, BlenderProductionAdoptionReceipt):
        raise TypeError("adoption must be a BlenderProductionAdoptionReceipt")
    if not isinstance(dispatch_binding, DispatchBinding):
        raise TypeError("dispatch_binding must be a DispatchBinding")
    _require_structural_relation(
        output_binding,
        adoption,
        dispatch_binding,
        task_revision_at_acceptance,
    )

    evidence = _expected_evidence(
        output_binding,
        adoption,
        dispatch_binding,
        task_revision_at_acceptance,
    )
    accepted_content_hash = "sha256:" + output_binding.output_content_hash

    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing_rows = conn.execute(
            """SELECT * FROM blender_production_task_acceptances
               WHERE execution_id = ? OR task_id = ? OR adopted_artifact_id = ?
                     OR adoption_verification_id = ?""",
            (
                output_binding.execution_id,
                output_binding.task_id,
                adoption.adopted_artifact_id,
                adoption.verification_id,
            ),
        ).fetchall()
        if existing_rows:
            if len(existing_rows) != 1:
                raise BlenderProductionTaskAcceptanceConflict(
                    "Blender production acceptance identities are split across conflicting rows"
                )
            existing = _from_row(existing_rows[0])
            if not _matches_request(
                existing,
                output_binding,
                adoption,
                task_revision_at_acceptance,
            ):
                raise BlenderProductionTaskAcceptanceConflict(
                    "Blender production relation is already accepted with different identities or content"
                )
            _require_exact_task_verification(
                conn,
                existing,
                output_binding,
                adoption,
                dispatch_binding,
            )
            return existing

        task_verification_id = new_id(IdKind.VERIFICATION)
        accepted_at = utc_now()
        try:
            conn.execute(
                """INSERT INTO verifications(
                       id, target_type, target_id, verification_type, verifier,
                       status, evidence_json, metrics_json, run_id, created_at
                   ) VALUES (?, 'TASK', ?, ?, ?, 'PASS', ?, '{}', ?, ?)""",
                (
                    task_verification_id,
                    output_binding.task_id,
                    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFIER,
                    _json(evidence),
                    output_binding.run_id,
                    accepted_at,
                ),
            )
            runtime.store._append_event(
                conn,
                "TASK",
                output_binding.task_id,
                "VERIFICATION_RECORDED",
                None,
                "PASS",
                None,
                "HUMAN",
                actor_id,
                {
                    "verification_id": task_verification_id,
                    "verification_type": BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                },
                accepted_at,
            )
            conn.execute(
                """INSERT INTO blender_production_task_acceptances(
                       execution_id, task_id, adopted_artifact_id,
                       adoption_verification_id, task_verification_id,
                       task_revision_at_acceptance, accepted_content_hash,
                       accepted_byte_count, accepted_destination_path,
                       acceptance_authority, schema_version, accepted_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    output_binding.execution_id,
                    output_binding.task_id,
                    adoption.adopted_artifact_id,
                    adoption.verification_id,
                    task_verification_id,
                    task_revision_at_acceptance,
                    accepted_content_hash,
                    output_binding.output_byte_count,
                    adoption.destination_path,
                    BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
                    BLENDER_PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION,
                    accepted_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise BlenderProductionTaskAcceptanceConflict(
                "Blender production Task acceptance conflicts with durable uniqueness or relation constraints"
            ) from exc

        row = conn.execute(
            "SELECT * FROM blender_production_task_acceptances WHERE execution_id = ?",
            (output_binding.execution_id,),
        ).fetchone()
        if row is None:
            raise BlenderProductionTaskAcceptanceError(
                "Blender production Task acceptance disappeared during transaction"
            )
        stored = _from_row(row)
        if not _matches_request(
            stored,
            output_binding,
            adoption,
            task_revision_at_acceptance,
        ):
            raise BlenderProductionTaskAcceptanceError(
                "Blender production Task acceptance changed during transaction"
            )
        _require_exact_task_verification(
            conn,
            stored,
            output_binding,
            adoption,
            dispatch_binding,
        )
        return stored
