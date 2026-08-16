from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .path_policy import portable_relative_path
from .production_pixelorama_dispatch_output_binding_models import (
    PixeloramaDispatchOutputBinding,
)
from .runtime import OriginForgeRuntime


PRODUCTION_ADOPTION_VERIFICATION_TYPE = "pixelorama-production-adoption-integrity"
PRODUCTION_ADOPTION_VERIFIER = "OriginForge.GovernedPixeloramaProductionOutputAdopter"


class PixeloramaProductionAdoptionReceiptError(RuntimeError):
    pass


class PixeloramaProductionAdoptionConflict(PixeloramaProductionAdoptionReceiptError):
    pass


class PixeloramaProductionAdoptionStatus(StrEnum):
    PREPARED = "PREPARED"
    PUBLISHED = "PUBLISHED"


@dataclass(frozen=True)
class PixeloramaProductionAdoptionReceipt:
    execution_id: str
    output_artifact_id: str
    destination_path: str
    status: PixeloramaProductionAdoptionStatus
    adopted_artifact_id: str | None
    verification_id: str | None
    created_at: str
    published_at: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.execution_id, IdKind.DISPATCH_EXECUTION):
            raise PixeloramaProductionAdoptionReceiptError(
                "execution_id must be a DISPEXEC ID"
            )
        if not validate_id(self.output_artifact_id, IdKind.ARTIFACT):
            raise PixeloramaProductionAdoptionReceiptError(
                "output_artifact_id must be an ART ID"
            )
        try:
            portable = portable_relative_path(self.destination_path)
        except ValueError as exc:
            raise PixeloramaProductionAdoptionReceiptError(
                "destination_path is not canonical portable project-relative text"
            ) from exc
        if portable.as_posix() != self.destination_path:
            raise PixeloramaProductionAdoptionReceiptError(
                "destination_path is not canonical portable project-relative text"
            )
        if not self.created_at or self.created_at.strip() != self.created_at:
            raise PixeloramaProductionAdoptionReceiptError("created_at is invalid")
        if self.status is PixeloramaProductionAdoptionStatus.PREPARED:
            if (
                self.adopted_artifact_id is not None
                or self.verification_id is not None
                or self.published_at is not None
            ):
                raise PixeloramaProductionAdoptionReceiptError(
                    "PREPARED adoption receipt may not contain publication identities"
                )
        elif self.status is PixeloramaProductionAdoptionStatus.PUBLISHED:
            if (
                self.adopted_artifact_id is None
                or not validate_id(self.adopted_artifact_id, IdKind.ARTIFACT)
                or self.verification_id is None
                or not validate_id(self.verification_id, IdKind.VERIFICATION)
                or self.published_at is None
                or not self.published_at
                or self.published_at.strip() != self.published_at
            ):
                raise PixeloramaProductionAdoptionReceiptError(
                    "PUBLISHED adoption receipt requires canonical publication identities"
                )
        else:
            raise PixeloramaProductionAdoptionReceiptError(
                "unsupported production adoption receipt status"
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


def _from_row(row) -> PixeloramaProductionAdoptionReceipt:
    try:
        return PixeloramaProductionAdoptionReceipt(
            execution_id=row["execution_id"],
            output_artifact_id=row["output_artifact_id"],
            destination_path=row["destination_path"],
            status=PixeloramaProductionAdoptionStatus(row["status"]),
            adopted_artifact_id=row["adopted_artifact_id"],
            verification_id=row["verification_id"],
            created_at=row["created_at"],
            published_at=row["published_at"],
        )
    except (KeyError, TypeError, ValueError, PixeloramaProductionAdoptionReceiptError) as exc:
        raise PixeloramaProductionAdoptionReceiptError(
            "stored production adoption receipt failed canonical validation"
        ) from exc


def read_pixelorama_production_adoption_receipt(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> PixeloramaProductionAdoptionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise ValueError("execution_id must be a DISPEXEC ID")
    with runtime.store.session() as conn:
        row = conn.execute(
            "SELECT * FROM pixelorama_production_adoptions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
    if row is None:
        raise PixeloramaProductionAdoptionReceiptError(
            "production adoption receipt does not exist"
        )
    return _from_row(row)


def reserve_pixelorama_production_adoption(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
    destination_path: str,
    created_at: str,
) -> PixeloramaProductionAdoptionReceipt:
    """Reserve one execution/output for one exact destination before filesystem publication."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, PixeloramaDispatchOutputBinding):
        raise TypeError("binding must be a PixeloramaDispatchOutputBinding")
    candidate = PixeloramaProductionAdoptionReceipt(
        execution_id=binding.execution_id,
        output_artifact_id=binding.output_artifact_id,
        destination_path=destination_path,
        status=PixeloramaProductionAdoptionStatus.PREPARED,
        adopted_artifact_id=None,
        verification_id=None,
        created_at=created_at,
        published_at=None,
    )
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        relation = conn.execute(
            """SELECT output_artifact_id FROM pixelorama_dispatch_output_bindings
               WHERE execution_id = ?""",
            (binding.execution_id,),
        ).fetchone()
        if relation is None or relation["output_artifact_id"] != binding.output_artifact_id:
            raise PixeloramaProductionAdoptionReceiptError(
                "production adoption reservation does not match durable dispatch-output binding"
            )
        existing_row = conn.execute(
            "SELECT * FROM pixelorama_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if existing_row is not None:
            existing = _from_row(existing_row)
            if (
                existing.output_artifact_id != binding.output_artifact_id
                or existing.destination_path != destination_path
            ):
                raise PixeloramaProductionAdoptionConflict(
                    "production execution is already reserved for a different output or destination"
                )
            return existing
        try:
            conn.execute(
                """INSERT INTO pixelorama_production_adoptions(
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
            raise PixeloramaProductionAdoptionConflict(
                "production output or destination is already reserved elsewhere"
            ) from exc
        row = conn.execute(
            "SELECT * FROM pixelorama_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if row is None:
            raise PixeloramaProductionAdoptionReceiptError(
                "production adoption reservation disappeared during transaction"
            )
        stored = _from_row(row)
        if stored != candidate:
            raise PixeloramaProductionAdoptionReceiptError(
                "production adoption reservation changed during transaction"
            )
        return stored


def finalize_pixelorama_production_adoption(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
    *,
    destination_path: str,
    adopted_artifact_id: str,
    verification_id: str,
    published_at: str,
) -> PixeloramaProductionAdoptionReceipt:
    """Bind a successful create-only publication to the reserved production execution."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, PixeloramaDispatchOutputBinding):
        raise TypeError("binding must be a PixeloramaDispatchOutputBinding")
    if not validate_id(adopted_artifact_id, IdKind.ARTIFACT):
        raise ValueError("adopted_artifact_id must be an ART ID")
    if not validate_id(verification_id, IdKind.VERIFICATION):
        raise ValueError("verification_id must be a VER ID")
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM pixelorama_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if row is None:
            raise PixeloramaProductionAdoptionReceiptError(
                "production adoption was not reserved"
            )
        existing = _from_row(row)
        if (
            existing.output_artifact_id != binding.output_artifact_id
            or existing.destination_path != destination_path
        ):
            raise PixeloramaProductionAdoptionConflict(
                "production adoption reservation drifted before finalization"
            )
        if existing.status is PixeloramaProductionAdoptionStatus.PUBLISHED:
            if (
                existing.adopted_artifact_id == adopted_artifact_id
                and existing.verification_id == verification_id
            ):
                return existing
            raise PixeloramaProductionAdoptionConflict(
                "production execution is already published with different identities"
            )

        artifact = conn.execute(
            """SELECT type, parent_artifact_id, created_by_run_id, status
               FROM artifacts WHERE id = ? AND project_id = ?""",
            (adopted_artifact_id, runtime.project_id()),
        ).fetchone()
        verification = conn.execute(
            """SELECT target_type, target_id, verification_type, verifier, status, run_id
               FROM verifications WHERE id = ?""",
            (verification_id,),
        ).fetchone()
        if (
            artifact is None
            or artifact["type"] != "SPRITESHEET_EXPORT"
            or artifact["parent_artifact_id"] != binding.output_artifact_id
            or artifact["created_by_run_id"] != binding.run_id
            or artifact["status"] != "ADOPTED"
            or verification is None
            or verification["target_type"] != "ARTIFACT"
            or verification["target_id"] != adopted_artifact_id
            or verification["verification_type"] != PRODUCTION_ADOPTION_VERIFICATION_TYPE
            or verification["verifier"] != PRODUCTION_ADOPTION_VERIFIER
            or verification["status"] != "PASS"
            or verification["run_id"] != binding.run_id
        ):
            raise PixeloramaProductionAdoptionReceiptError(
                "production adoption Artifact/Verification relation is not exact"
            )
        try:
            conn.execute(
                """UPDATE pixelorama_production_adoptions
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
            raise PixeloramaProductionAdoptionConflict(
                "production adoption publication identities are already used elsewhere"
            ) from exc
        final_row = conn.execute(
            "SELECT * FROM pixelorama_production_adoptions WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if final_row is None:
            raise PixeloramaProductionAdoptionReceiptError(
                "production adoption receipt disappeared during finalization"
            )
        final = _from_row(final_row)
        if (
            final.status is not PixeloramaProductionAdoptionStatus.PUBLISHED
            or final.adopted_artifact_id != adopted_artifact_id
            or final.verification_id != verification_id
        ):
            raise PixeloramaProductionAdoptionReceiptError(
                "production adoption finalization was not durable"
            )
        return final
