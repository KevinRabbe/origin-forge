from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .path_policy import portable_relative_path
from .pixelorama_adoption import (
    GovernedPixeloramaAdoptionResult,
    GovernedPixeloramaOutputAdopter,
    PixeloramaAdoptionError,
)
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_pixelorama_source_dispatch_output_binding import (
    PixeloramaSourceOutputBindingError,
    materialize_pixelorama_source_result,
    read_pixelorama_source_dispatch_output_binding,
)
from .production_pixelorama_source_dispatch_output_binding_models import (
    PixeloramaSourceDispatchOutput,
)
from .runtime import OriginForgeRuntime
from .service import utc_now


class PixeloramaSourceProductionAdoptionError(RuntimeError):
    pass


class SourceAdoptionStatus(StrEnum):
    PREPARED = "PREPARED"
    PUBLISHED = "PUBLISHED"


@dataclass(frozen=True)
class SourceAdoptionReceipt:
    execution_id: str
    output_index: int
    output_artifact_id: str
    destination_path: str
    status: SourceAdoptionStatus
    adopted_artifact_id: str | None
    verification_id: str | None
    created_at: str
    published_at: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.execution_id, IdKind.DISPATCH_EXECUTION):
            raise PixeloramaSourceProductionAdoptionError("execution_id is invalid")
        if not validate_id(self.output_artifact_id, IdKind.ARTIFACT):
            raise PixeloramaSourceProductionAdoptionError("output_artifact_id is invalid")
        if type(self.output_index) is not int or self.output_index < 0 or self.output_index >= 64:
            raise PixeloramaSourceProductionAdoptionError("output_index is invalid")
        try:
            if portable_relative_path(self.destination_path).as_posix() != self.destination_path:
                raise ValueError
        except ValueError:
            raise PixeloramaSourceProductionAdoptionError("destination_path is not canonical")
        if self.status is SourceAdoptionStatus.PREPARED:
            if self.adopted_artifact_id is not None or self.verification_id is not None or self.published_at is not None:
                raise PixeloramaSourceProductionAdoptionError("PREPARED receipt contains publication identities")
        elif self.status is SourceAdoptionStatus.PUBLISHED:
            if not self.adopted_artifact_id or not validate_id(self.adopted_artifact_id, IdKind.ARTIFACT) or not self.verification_id or not validate_id(self.verification_id, IdKind.VERIFICATION) or not self.published_at:
                raise PixeloramaSourceProductionAdoptionError("PUBLISHED receipt is incomplete")
        else:
            raise PixeloramaSourceProductionAdoptionError("unsupported adoption status")

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy() | {"status": self.status.value}


def _receipt(row) -> SourceAdoptionReceipt:
    try:
        return SourceAdoptionReceipt(
            execution_id=row["execution_id"], output_index=int(row["output_index"]),
            output_artifact_id=row["output_artifact_id"], destination_path=row["destination_path"],
            status=SourceAdoptionStatus(row["status"]), adopted_artifact_id=row["adopted_artifact_id"],
            verification_id=row["verification_id"], created_at=row["created_at"], published_at=row["published_at"],
        )
    except (KeyError, TypeError, ValueError, PixeloramaSourceProductionAdoptionError) as exc:
        raise PixeloramaSourceProductionAdoptionError("stored source adoption receipt is invalid") from exc


def read_source_adoption_receipt(runtime: OriginForgeRuntime, execution_id: str, output_index: int) -> SourceAdoptionReceipt:
    with runtime.store.session() as conn:
        row = conn.execute("SELECT * FROM pixelorama_source_production_adoptions WHERE execution_id = ? AND output_index = ?", (execution_id, output_index)).fetchone()
    if row is None:
        raise PixeloramaSourceProductionAdoptionError("source adoption receipt does not exist")
    return _receipt(row)


def _reserve(runtime: OriginForgeRuntime, output: PixeloramaSourceDispatchOutput, output_index: int, execution_id: str, destination: str) -> SourceAdoptionReceipt:
    candidate = SourceAdoptionReceipt(execution_id, output_index=output_index, output_artifact_id=output.artifact_id, destination_path=destination, status=SourceAdoptionStatus.PREPARED, adopted_artifact_id=None, verification_id=None, created_at=utc_now(), published_at=None)
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT INTO pixelorama_source_production_adoptions(execution_id, output_index, output_artifact_id, destination_path, status, adopted_artifact_id, verification_id, created_at, published_at) VALUES (?, ?, ?, ?, 'PREPARED', NULL, NULL, ?, NULL)", (execution_id, output_index, output.artifact_id, destination, candidate.created_at))
        except sqlite3.IntegrityError as exc:
            row = conn.execute("SELECT * FROM pixelorama_source_production_adoptions WHERE execution_id = ? AND output_index = ?", (execution_id, output_index)).fetchone()
            if row is None:
                raise PixeloramaSourceProductionAdoptionError("source adoption reservation conflicted") from exc
            existing = _receipt(row)
            if existing.output_artifact_id != output.artifact_id or existing.destination_path != destination:
                raise PixeloramaSourceProductionAdoptionError("source adoption is reserved for a different output or destination") from exc
            return existing
        return candidate


class GovernedPixeloramaSourceOutputAdopter:
    """Explicit create-only adoption of the one generated Pixelorama project output."""

    def __init__(self, runtime: OriginForgeRuntime):
        self.runtime = runtime
        self.publisher = GovernedPixeloramaOutputAdopter(runtime)

    def adopt_new(self, execution_id: str, destination_relative_path: str):
        if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
            raise ValueError("execution_id must be a DISPEXEC ID")
        execution = read_dispatch_execution(self.runtime, execution_id)
        if execution.execution_owner_id != "originforge.execution.pixelorama.source-create@1" or execution.status is not DispatchExecutionStatus.RETURNED:
            raise PixeloramaSourceProductionAdoptionError("source execution is not a returned source production execution")
        binding = read_pixelorama_source_dispatch_output_binding(self.runtime, execution_id)
        try:
            materialize_pixelorama_source_result(self.runtime, binding)
        except PixeloramaSourceOutputBindingError as exc:
            raise PixeloramaSourceProductionAdoptionError("source output binding is not adoption-safe") from exc
        projects = [(index, output) for index, output in enumerate(binding.outputs) if output.output_type.value == "PIXELORAMA_PROJECT"]
        if len(projects) != 1:
            raise PixeloramaSourceProductionAdoptionError("source execution must contain exactly one project output")
        output_index, output = projects[0]
        try:
            destination, portable = self.publisher._destination(destination_relative_path)
            artifact = self.publisher._artifact_row(output.artifact_id)
            source = self.publisher._source_path(artifact)
            content_hash, byte_count = self.publisher._stream_hash(source)
        except (PixeloramaAdoptionError, KeyError, OSError) as exc:
            raise PixeloramaSourceProductionAdoptionError("source output cannot be prepared for adoption") from exc
        if artifact.get("type") != "PIXELORAMA_PROJECT" or artifact.get("status") != "PRODUCED" or content_hash != "sha256:" + output.content_hash or byte_count != output.byte_count:
            raise PixeloramaSourceProductionAdoptionError("source project output drifted before adoption")
        receipt = _reserve(self.runtime, output, output_index, execution_id, portable)
        if receipt.status is SourceAdoptionStatus.PUBLISHED:
            raise PixeloramaSourceProductionAdoptionError("source output is already adopted")
        try:
            published: GovernedPixeloramaAdoptionResult = self.publisher._publish_verified_new(
                source_artifact_id=output.artifact_id, artifact=artifact, source=source,
                content_hash=content_hash, byte_count=byte_count, destination=destination,
                portable_destination=portable, verification_type="pixelorama-source-production-adoption-integrity",
                verifier="OriginForge.GovernedPixeloramaSourceOutputAdopter",
                extra_evidence={"production_dispatch_output_bound": True, "dispatch_execution_id": execution_id, "output_index": output_index},
            )
        except PixeloramaAdoptionError as exc:
            raise PixeloramaSourceProductionAdoptionError(str(exc)) from exc
        with self.runtime.store.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE pixelorama_source_production_adoptions SET status = 'PUBLISHED', adopted_artifact_id = ?, verification_id = ?, published_at = ? WHERE execution_id = ? AND output_index = ? AND status = 'PREPARED'", (published.adopted_artifact_id, published.verification_id, utc_now(), execution_id, output_index))
            row = conn.execute("SELECT * FROM pixelorama_source_production_adoptions WHERE execution_id = ? AND output_index = ?", (execution_id, output_index)).fetchone()
        if row is None or _receipt(row).adopted_artifact_id != published.adopted_artifact_id:
            raise PixeloramaSourceProductionAdoptionError("source adoption receipt finalization failed")
        return published
