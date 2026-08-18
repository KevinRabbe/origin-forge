from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from .ids import IdKind, new_id, validate_id
from .production_pixelorama_adoption_receipt import (
    PixeloramaProductionAdoptionReceipt,
    PixeloramaProductionAdoptionStatus,
)
from .production_pixelorama_dispatch_output_binding_models import (
    PixeloramaDispatchOutputBinding,
)
from .runtime import OriginForgeRuntime
from .service import utc_now


PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE = "pixelorama-production-task-acceptance"
PRODUCTION_TASK_ACCEPTANCE_VERIFIER = "OriginForge.GovernedPixeloramaProductionTaskAcceptor"
PRODUCTION_TASK_ACCEPTANCE_AUTHORITY = "HUMAN_OPERATOR"
PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION = 1
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class PixeloramaProductionTaskAcceptanceError(RuntimeError):
    pass


class PixeloramaProductionTaskAcceptanceConflict(
    PixeloramaProductionTaskAcceptanceError
):
    pass


@dataclass(frozen=True)
class PixeloramaProductionTaskAcceptanceReceipt:
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
        typed = (
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
        )
        for value, kind, label in typed:
            if not isinstance(value, str) or not validate_id(value, kind):
                raise PixeloramaProductionTaskAcceptanceError(
                    f"{label} must be a valid {kind.value} ID"
                )
        if self.adoption_verification_id == self.task_verification_id:
            raise PixeloramaProductionTaskAcceptanceError(
                "adoption and Task Verification IDs must be distinct"
            )
        if (
            type(self.task_revision_at_acceptance) is not int
            or self.task_revision_at_acceptance < 0
        ):
            raise PixeloramaProductionTaskAcceptanceError(
                "task_revision_at_acceptance must be a non-negative integer"
            )
        if not isinstance(self.accepted_content_hash, str) or _HASH_RE.fullmatch(
            self.accepted_content_hash
        ) is None:
            raise PixeloramaProductionTaskAcceptanceError(
                "accepted_content_hash must be a canonical SHA-256 content hash"
            )
        if type(self.accepted_byte_count) is not int or self.accepted_byte_count <= 0:
            raise PixeloramaProductionTaskAcceptanceError(
                "accepted_byte_count must be a positive integer"
            )
        if (
            not isinstance(self.accepted_destination_path, str)
            or not self.accepted_destination_path
            or self.accepted_destination_path.strip()
            != self.accepted_destination_path
        ):
            raise PixeloramaProductionTaskAcceptanceError(
                "accepted_destination_path is invalid"
            )
        if self.acceptance_authority != PRODUCTION_TASK_ACCEPTANCE_AUTHORITY:
            raise PixeloramaProductionTaskAcceptanceError(
                "acceptance_authority must be HUMAN_OPERATOR"
            )
        if self.schema_version != PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION:
            raise PixeloramaProductionTaskAcceptanceError(
                "unsupported production Task acceptance schema_version"
            )
        if (
            not isinstance(self.accepted_at, str)
            or not self.accepted_at
            or self.accepted_at.strip() != self.accepted_at
        ):
            raise PixeloramaProductionTaskAcceptanceError("accepted_at is invalid")

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


def _from_row(row) -> PixeloramaProductionTaskAcceptanceReceipt:
    try:
        return PixeloramaProductionTaskAcceptanceReceipt(
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
    except (KeyError, TypeError, ValueError, PixeloramaProductionTaskAcceptanceError) as exc:
        raise PixeloramaProductionTaskAcceptanceError(
            "stored production Task acceptance failed canonical validation"
        ) from exc


def _expected_evidence(
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
    task_revision_at_acceptance: int,
) -> dict[str, object]:
    return {
        "production_task_verified": True,
        "semantic_visual_quality_verified": True,
        "acceptance_authority": PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
        "production_dispatch_output_bound": True,
        "canonical_asset_adopted": True,
        "existing_asset_overwritten": False,
        "provenance_signed": False,
        "release_authorized": False,
        "dispatch_execution_id": binding.execution_id,
        "production_claim_id": binding.claim_id,
        "production_run_id": binding.run_id,
        "source_output_artifact_id": binding.output_artifact_id,
        "production_adoption_verification_id": adoption.verification_id,
        "adopted_artifact_id": adoption.adopted_artifact_id,
        "adopted_destination_path": adoption.destination_path,
        "accepted_content_hash": "sha256:" + binding.output_content_hash,
        "accepted_byte_count": binding.output_byte_count,
        "task_content_hash": binding.task_content_hash,
        "task_revision_at_acceptance": task_revision_at_acceptance,
    }


def _require_structural_relation(
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
    task_revision_at_acceptance: int,
) -> None:
    if adoption.status is not PixeloramaProductionAdoptionStatus.PUBLISHED:
        raise PixeloramaProductionTaskAcceptanceError(
            "production Task acceptance requires a PUBLISHED adoption receipt"
        )
    if (
        adoption.execution_id != binding.execution_id
        or adoption.output_artifact_id != binding.output_artifact_id
        or adoption.adopted_artifact_id is None
        or adoption.verification_id is None
    ):
        raise PixeloramaProductionTaskAcceptanceError(
            "production Task acceptance inputs do not name one structural production relation"
        )
    if type(task_revision_at_acceptance) is not int or task_revision_at_acceptance < 0:
        raise ValueError("task_revision_at_acceptance must be a non-negative integer")
    if binding.output_byte_count <= 0:
        raise PixeloramaProductionTaskAcceptanceError(
            "production Task acceptance requires non-empty accepted output"
        )


def _matches_request(
    receipt: PixeloramaProductionTaskAcceptanceReceipt,
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
    task_revision_at_acceptance: int,
) -> bool:
    return (
        receipt.execution_id == binding.execution_id
        and receipt.task_id == binding.task_id
        and receipt.adopted_artifact_id == adoption.adopted_artifact_id
        and receipt.adoption_verification_id == adoption.verification_id
        and receipt.task_revision_at_acceptance == task_revision_at_acceptance
        and receipt.accepted_content_hash == "sha256:" + binding.output_content_hash
        and receipt.accepted_byte_count == binding.output_byte_count
        and receipt.accepted_destination_path == adoption.destination_path
        and receipt.acceptance_authority == PRODUCTION_TASK_ACCEPTANCE_AUTHORITY
        and receipt.schema_version == PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION
    )


def _require_exact_task_verification(
    conn: sqlite3.Connection,
    receipt: PixeloramaProductionTaskAcceptanceReceipt,
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
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
        raise PixeloramaProductionTaskAcceptanceError(
            "production Task acceptance Verification JSON is invalid"
        ) from exc
    if (
        row is None
        or row["target_type"] != "TASK"
        or row["target_id"] != binding.task_id
        or row["verification_type"] != PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE
        or row["verifier"] != PRODUCTION_TASK_ACCEPTANCE_VERIFIER
        or row["status"] != "PASS"
        or evidence
        != _expected_evidence(binding, adoption, receipt.task_revision_at_acceptance)
        or metrics != {}
        or row["run_id"] != binding.run_id
        or row["created_at"] != receipt.accepted_at
    ):
        raise PixeloramaProductionTaskAcceptanceError(
            "production Task acceptance Verification is not exact"
        )


def read_pixelorama_production_task_acceptance(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> PixeloramaProductionTaskAcceptanceReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise ValueError("execution_id must be a DISPEXEC ID")
    with runtime.store.session() as conn:
        row = conn.execute(
            "SELECT * FROM pixelorama_production_task_acceptances WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
    if row is None:
        raise PixeloramaProductionTaskAcceptanceError(
            "production Task acceptance does not exist"
        )
    return _from_row(row)


def publish_pixelorama_production_task_acceptance(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
    *,
    task_revision_at_acceptance: int,
    actor_id: str | None = None,
) -> PixeloramaProductionTaskAcceptanceReceipt:
    """Atomically publish one infrastructure-owned Task PASS and its immutable receipt.

    Phase 50A deliberately accepts a prevalidated production snapshot. Full live
    currentness/eligibility checks are owned by Phase 50B; Task terminalization is
    owned by Phase 50C.
    """
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, PixeloramaDispatchOutputBinding):
        raise TypeError("binding must be a PixeloramaDispatchOutputBinding")
    if not isinstance(adoption, PixeloramaProductionAdoptionReceipt):
        raise TypeError("adoption must be a PixeloramaProductionAdoptionReceipt")
    _require_structural_relation(binding, adoption, task_revision_at_acceptance)

    evidence = _expected_evidence(binding, adoption, task_revision_at_acceptance)
    accepted_content_hash = "sha256:" + binding.output_content_hash

    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing_rows = conn.execute(
            """SELECT * FROM pixelorama_production_task_acceptances
               WHERE execution_id = ? OR task_id = ? OR adopted_artifact_id = ?
                     OR adoption_verification_id = ?""",
            (
                binding.execution_id,
                binding.task_id,
                adoption.adopted_artifact_id,
                adoption.verification_id,
            ),
        ).fetchall()
        if existing_rows:
            if len(existing_rows) != 1:
                raise PixeloramaProductionTaskAcceptanceConflict(
                    "production acceptance identities are split across conflicting rows"
                )
            existing = _from_row(existing_rows[0])
            if not _matches_request(
                existing, binding, adoption, task_revision_at_acceptance
            ):
                raise PixeloramaProductionTaskAcceptanceConflict(
                    "production relation is already accepted with different identities or content"
                )
            _require_exact_task_verification(conn, existing, binding, adoption)
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
                    binding.task_id,
                    PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    PRODUCTION_TASK_ACCEPTANCE_VERIFIER,
                    _json(evidence),
                    binding.run_id,
                    accepted_at,
                ),
            )
            runtime.store._append_event(
                conn,
                "TASK",
                binding.task_id,
                "VERIFICATION_RECORDED",
                None,
                "PASS",
                None,
                "HUMAN",
                actor_id,
                {
                    "verification_id": task_verification_id,
                    "verification_type": PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                },
                accepted_at,
            )
            conn.execute(
                """INSERT INTO pixelorama_production_task_acceptances(
                       execution_id, task_id, adopted_artifact_id,
                       adoption_verification_id, task_verification_id,
                       task_revision_at_acceptance, accepted_content_hash,
                       accepted_byte_count, accepted_destination_path,
                       acceptance_authority, schema_version, accepted_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    binding.execution_id,
                    binding.task_id,
                    adoption.adopted_artifact_id,
                    adoption.verification_id,
                    task_verification_id,
                    task_revision_at_acceptance,
                    accepted_content_hash,
                    binding.output_byte_count,
                    adoption.destination_path,
                    PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
                    PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION,
                    accepted_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PixeloramaProductionTaskAcceptanceConflict(
                "production Task acceptance conflicts with durable uniqueness or relation constraints"
            ) from exc

        row = conn.execute(
            "SELECT * FROM pixelorama_production_task_acceptances WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if row is None:
            raise PixeloramaProductionTaskAcceptanceError(
                "production Task acceptance disappeared during transaction"
            )
        stored = _from_row(row)
        if not _matches_request(stored, binding, adoption, task_revision_at_acceptance):
            raise PixeloramaProductionTaskAcceptanceError(
                "production Task acceptance changed during transaction"
            )
        _require_exact_task_verification(conn, stored, binding, adoption)
        return stored
