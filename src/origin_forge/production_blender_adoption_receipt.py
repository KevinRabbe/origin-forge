from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .path_policy import portable_relative_path
from .production_blender_dispatch_output_binding import BlenderDispatchOutputBinding
from .runtime import OriginForgeRuntime


BLENDER_PRODUCTION_ADOPTION_VERIFICATION_TYPE = "blender-production-adoption-integrity"
BLENDER_PRODUCTION_ADOPTION_VERIFIER = "OriginForge.GovernedBlenderProductionOutputAdopter"


class BlenderProductionAdoptionReceiptError(RuntimeError):
    pass


class BlenderProductionAdoptionConflict(BlenderProductionAdoptionReceiptError):
    pass


class BlenderProductionAdoptionStatus(StrEnum):
    PREPARED = "PREPARED"
    PUBLISHED = "PUBLISHED"


@dataclass(frozen=True)
class BlenderProductionAdoptionReceipt:
    execution_id: str
    output_artifact_id: str
    destination_path: str
    status: BlenderProductionAdoptionStatus
    adopted_artifact_id: str | None
    verification_id: str | None
    created_at: str
    published_at: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.execution_id, IdKind.DISPATCH_EXECUTION):
            raise BlenderProductionAdoptionReceiptError("execution_id must be a DISPEXEC ID")
        if not validate_id(self.output_artifact_id, IdKind.ARTIFACT):
            raise BlenderProductionAdoptionReceiptError("output_artifact_id must be an ART ID")
        try:
            portable = portable_relative_path(self.destination_path)
        except ValueError as exc:
            raise BlenderProductionAdoptionReceiptError(
                "destination_path is not canonical portable project-relative text"
            ) from exc
        if portable.as_posix() != self.destination_path:
            raise BlenderProductionAdoptionReceiptError(
                "destination_path is not canonical portable project-relative text"
            )
        if not self.created_at or self.created_at.strip() != self.created_at:
            raise BlenderProductionAdoptionReceiptError("created_at is invalid")
        if self.status is BlenderProductionAdoptionStatus.PREPARED:
            if (
                self.adopted_artifact_id is not None
                or self.verification_id is not None
                or self.published_at is not None
            ):
                raise BlenderProductionAdoptionReceiptError(
                    "PREPARED adoption receipt may not contain publication identities"
                )
        elif self.status is BlenderProductionAdoptionStatus.PUBLISHED:
            if (
                self.adopted_artifact_id is None
                or not validate_id(self.adopted_artifact_id, IdKind.ARTIFACT)
                or self.verification_id is None
                or not validate_id(self.verification_id, IdKind.VERIFICATION)
                or self.published_at is None
                or not self.published_at
                or self.published_at.strip() != self.published_at
            ):
                raise BlenderProductionAdoptionReceiptError(
                    "PUBLISHED adoption receipt requires canonical publication identities"
                )
        else:
            raise BlenderProductionAdoptionReceiptError(
                "unsupported Blender production adoption receipt status"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "output_artifact_id": self.output_artifact_id,
            "destination_path": self.destination_path,
            "status": self.status.value,
            "adopted_artifact_id": self.adopted_artifact_id,
            "verification_id": self.verification_id,
            "created_at": self.created_at,
            "published_at": self.published_at,
        }


def _from_row(row) -> BlenderProductionAdoptionReceipt:
    try:
        return BlenderProductionAdoptionReceipt(
            execution_id=row["execution_id"],
            output_artifact_id=row["output_artifact_id"],
            destination_path=row["destination_path"],
            status=BlenderProductionAdoptionStatus(row["status"]),
            adopted_artifact_id=row["adopted_artifact_id"],
            verification_id=row["verification_id"],
            created_at=row["created_at"],
            published_at=row["published_at"],
        )
    except (KeyError, TypeError, ValueError, BlenderProductionAdoptionReceiptError) as exc:
        raise BlenderProductionAdoptionReceiptError(
            "stored Blender production adoption receipt failed canonical validation"
        ) from exc


def _require_exact_binding(conn, binding: BlenderDispatchOutputBinding) -> None:
    row = conn.execute(
        "SELECT * FROM blender_dispatch_output_bindings WHERE execution_id = ?",
        (binding.execution_id,),
    ).fetchone()
    if row is None:
        raise BlenderProductionAdoptionReceiptError(
            "Blender production adoption requires an exact durable dispatch-output binding"
        )
    expected = binding.to_dict()
    if any(row[key] != value for key, value in expected.items()):
        raise BlenderProductionAdoptionReceiptError(
            "Blender production adoption binding drifted from immutable durable truth"
        )


def expected_blender_production_adoption_evidence(
    binding: BlenderDispatchOutputBinding,
    destination_path: str,
) -> dict[str, object]:
    content_hash = "sha256:" + binding.output_content_hash
    return {
        "source_artifact_id": binding.output_artifact_id,
        "source_content_hash": content_hash,
        "source_byte_count": binding.output_byte_count,
        "destination_path": destination_path,
        "destination_content_hash": content_hash,
        "existing_asset_overwritten": False,
        "production_dispatch_output_bound": True,
        "dispatch_execution_id": binding.execution_id,
        "dispatch_claim_id": binding.claim_id,
        "production_run_id": binding.run_id,
        "production_task_verified": False,
        "semantic_geometry_verified": False,
        "provenance_signed": False,
    }


def read_blender_production_adoption_receipt(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> BlenderProductionAdoptionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise ValueError("execution_id must be a DISPEXEC ID")
    with runtime.store.session() as conn:
        row = conn.execute(
            "SELECT * FROM blender_production_adoptions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
    if row is None:
        raise BlenderProductionAdoptionReceiptError(
            "Blender production adoption receipt does not exist"
        )
    return _from_row(row)


def reserve_blender_production_adoption(
    runtime: OriginForgeRuntime,
    binding: BlenderDispatchOutputBinding,
    destination_path: str,
    created_at: str,
) -> BlenderProductionAdoptionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, BlenderDispatchOutputBinding):
        raise TypeError("binding must be a BlenderDispatchOutputBinding")
    candidate = BlenderProductionAdoptionReceipt(
        execution_id=binding.execution_id,
        output_artifact_id=binding.output_artifact_id,
        destination_path=destination_path,
        status=BlenderProductionAdoptionStatus.PREPARED,
        adopted_artifact_id=None,
        verification_id=None,
        created_at=created_at,
        published_at=None,
    )
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_exact_binding(conn, binding)
        existing_row = conn.execute(
            "SELECT * FROM blender_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if existing_row is not None:
            existing = _from_row(existing_row)
            if (
                existing.output_artifact_id != binding.output_artifact_id
                or existing.destination_path != destination_path
            ):
                raise BlenderProductionAdoptionConflict(
                    "Blender production execution is already reserved for a different output or destination"
                )
            return existing
        try:
            conn.execute(
                """INSERT INTO blender_production_adoptions(
                       execution_id, output_artifact_id, destination_path, status,
                       adopted_artifact_id, verification_id, created_at, published_at
                   ) VALUES (?, ?, ?, 'PREPARED', NULL, NULL, ?, NULL)""",
                (
                    binding.execution_id,
                    binding.output_artifact_id,
                    destination_path,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise BlenderProductionAdoptionConflict(
                "Blender production output or destination is already reserved elsewhere"
            ) from exc
        row = conn.execute(
            "SELECT * FROM blender_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if row is None:
            raise BlenderProductionAdoptionReceiptError(
                "Blender production adoption reservation disappeared during transaction"
            )
        stored = _from_row(row)
        if stored != candidate:
            raise BlenderProductionAdoptionReceiptError(
                "Blender production adoption reservation changed during transaction"
            )
        return stored


def finalize_blender_production_adoption(
    runtime: OriginForgeRuntime,
    binding: BlenderDispatchOutputBinding,
    *,
    destination_path: str,
    adopted_artifact_id: str,
    verification_id: str,
    published_at: str,
) -> BlenderProductionAdoptionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, BlenderDispatchOutputBinding):
        raise TypeError("binding must be a BlenderDispatchOutputBinding")
    if not validate_id(adopted_artifact_id, IdKind.ARTIFACT):
        raise ValueError("adopted_artifact_id must be an ART ID")
    if not validate_id(verification_id, IdKind.VERIFICATION):
        raise ValueError("verification_id must be a VER ID")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_exact_binding(conn, binding)
        row = conn.execute(
            "SELECT * FROM blender_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if row is None:
            raise BlenderProductionAdoptionReceiptError(
                "Blender production adoption was not reserved"
            )
        existing = _from_row(row)
        if (
            existing.output_artifact_id != binding.output_artifact_id
            or existing.destination_path != destination_path
        ):
            raise BlenderProductionAdoptionConflict(
                "Blender production adoption reservation drifted before finalization"
            )
        if existing.status is BlenderProductionAdoptionStatus.PUBLISHED:
            if (
                existing.adopted_artifact_id == adopted_artifact_id
                and existing.verification_id == verification_id
            ):
                return existing
            raise BlenderProductionAdoptionConflict(
                "Blender production execution is already published with different identities"
            )

        artifact = conn.execute(
            """SELECT type, path_or_uri, content_hash, parent_artifact_id,
                      created_by_run_id, status
               FROM artifacts WHERE id = ? AND project_id = ?""",
            (adopted_artifact_id, project_id),
        ).fetchone()
        verification = conn.execute(
            """SELECT target_type, target_id, verification_type, verifier, status,
                      evidence_json, run_id
               FROM verifications WHERE id = ?""",
            (verification_id,),
        ).fetchone()
        try:
            evidence = (
                json.loads(verification["evidence_json"])
                if verification is not None
                else None
            )
        except (TypeError, json.JSONDecodeError) as exc:
            raise BlenderProductionAdoptionReceiptError(
                "Blender production adoption Verification evidence is invalid"
            ) from exc
        if (
            artifact is None
            or artifact["type"] != "BLENDER_GLB_EXPORT"
            or artifact["path_or_uri"] != destination_path
            or artifact["content_hash"] != "sha256:" + binding.output_content_hash
            or artifact["parent_artifact_id"] != binding.output_artifact_id
            or artifact["created_by_run_id"] != binding.run_id
            or artifact["status"] != "ADOPTED"
            or verification is None
            or verification["target_type"] != "ARTIFACT"
            or verification["target_id"] != adopted_artifact_id
            or verification["verification_type"] != BLENDER_PRODUCTION_ADOPTION_VERIFICATION_TYPE
            or verification["verifier"] != BLENDER_PRODUCTION_ADOPTION_VERIFIER
            or verification["status"] != "PASS"
            or verification["run_id"] != binding.run_id
            or evidence != expected_blender_production_adoption_evidence(
                binding, destination_path
            )
        ):
            raise BlenderProductionAdoptionReceiptError(
                "Blender production adoption Artifact/Verification relation is not exact"
            )
        try:
            conn.execute(
                """UPDATE blender_production_adoptions
                   SET status = 'PUBLISHED', adopted_artifact_id = ?,
                       verification_id = ?, published_at = ?
                   WHERE execution_id = ? AND status = 'PREPARED'""",
                (
                    adopted_artifact_id,
                    verification_id,
                    published_at,
                    binding.execution_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise BlenderProductionAdoptionConflict(
                "Blender production adoption publication identities are already used elsewhere"
            ) from exc
        final_row = conn.execute(
            "SELECT * FROM blender_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if final_row is None:
            raise BlenderProductionAdoptionReceiptError(
                "Blender production adoption receipt disappeared during finalization"
            )
        final = _from_row(final_row)
        if (
            final.status is not BlenderProductionAdoptionStatus.PUBLISHED
            or final.adopted_artifact_id != adopted_artifact_id
            or final.verification_id != verification_id
        ):
            raise BlenderProductionAdoptionReceiptError(
                "Blender production adoption finalization was not durable"
            )
        return final
