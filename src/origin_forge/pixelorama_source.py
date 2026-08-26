from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .lineage import OriginForgeLineage
from .path_policy import portable_relative_path
from .production_evidence_read import ProductionEvidenceReadService
from .records import create_artifact
from .runtime import OriginForgeRuntime, RuntimeInvariantError


class PixeloramaSourceImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class PixeloramaSourceImportResult:
    artifact_id: str
    relative_path: str
    content_hash: str
    byte_count: int
    verification_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "verification_id": self.verification_id,
        }


@dataclass(frozen=True)
class PixeloramaSourceInspection:
    artifact: dict[str, object]
    verification_ids: tuple[str, ...]
    byte_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact": self.artifact,
            "verification_ids": list(self.verification_ids),
            "byte_count": self.byte_count,
            "read_only": True,
        }


def import_pixelorama_source(
    runtime: OriginForgeRuntime,
    source_path: str,
) -> PixeloramaSourceImportResult:
    """Explicitly register an existing project-contained Pixelorama source."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    try:
        relative = portable_relative_path(source_path)
    except ValueError as exc:
        raise PixeloramaSourceImportError(f"invalid Pixelorama source path: {exc}") from exc
    if relative.suffix.casefold() != ".pxo":
        raise PixeloramaSourceImportError("Pixelorama source must use the .pxo extension")
    candidate = runtime.project_root / Path(relative.as_posix())
    if candidate.is_symlink():
        raise PixeloramaSourceImportError("Pixelorama source must be a regular non-symlink file")
    path = candidate.resolve()
    try:
        path.relative_to(runtime.project_root)
    except ValueError as exc:
        raise PixeloramaSourceImportError("Pixelorama source escaped project root") from exc
    if not path.is_file():
        raise PixeloramaSourceImportError("Pixelorama source must be a regular non-symlink file")
    byte_count = path.stat().st_size
    if byte_count <= 0 or byte_count > 256 * 1024 * 1024:
        raise PixeloramaSourceImportError("Pixelorama source byte count is outside bounds")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lineage = OriginForgeLineage(runtime)
    artifact_id = create_artifact(
        runtime.store,
        runtime.project_id(),
        artifact_type="PIXELORAMA_PROJECT",
        path_or_uri=relative.as_posix(),
        status="PRODUCED",
        content_hash=digest,
    )
    artifact = lineage.get_artifact(artifact_id)
    content_hash = artifact.get("content_hash")
    if not isinstance(content_hash, str) or content_hash != digest:
        raise RuntimeInvariantError("imported Pixelorama source did not receive a content hash")
    verification_id = lineage.record_artifact_verification(
        artifact_id,
        verification_type="pixelorama-source-import-integrity",
        verifier="OriginForge.PixeloramaSourceImporter",
        status="PASS",
        evidence={
            "source_path": relative.as_posix(),
            "content_hash": content_hash,
            "byte_count": byte_count,
            "semantic_acceptance": False,
        },
    )
    return PixeloramaSourceImportResult(
        artifact_id, relative.as_posix(), content_hash, byte_count, verification_id
    )


def inspect_pixelorama_source(
    runtime: OriginForgeRuntime,
    artifact_id: str,
) -> PixeloramaSourceInspection:
    """Inspect one imported Pixelorama source without changing durable state."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    lineage = OriginForgeLineage(runtime)
    try:
        artifact = lineage.get_artifact(artifact_id)
    except KeyError as exc:
        raise PixeloramaSourceImportError("Pixelorama source artifact does not exist") from exc
    if artifact.get("type") != "PIXELORAMA_PROJECT":
        raise PixeloramaSourceImportError(
            "artifact is not a governed PIXELORAMA_PROJECT source"
        )
    location = artifact.get("path_or_uri")
    if not isinstance(location, str) or "://" in location:
        raise PixeloramaSourceImportError("Pixelorama source artifact is not a local file")
    candidate = runtime.project_root / Path(location)
    if candidate.is_symlink():
        raise PixeloramaSourceImportError("Pixelorama source artifact may not be a symlink")
    path = candidate.resolve()
    try:
        path.relative_to(runtime.project_root)
    except ValueError as exc:
        raise PixeloramaSourceImportError("Pixelorama source artifact escaped project root") from exc
    if not path.is_file():
        raise PixeloramaSourceImportError("Pixelorama source artifact file is missing")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    expected_hash = artifact.get("content_hash")
    if expected_hash not in {actual_hash, "sha256:" + actual_hash}:
        raise PixeloramaSourceImportError("Pixelorama source artifact integrity drifted")
    verifications = ProductionEvidenceReadService(runtime).list_artifact_verifications()
    verification_ids = tuple(
        str(item["id"])
        for item in verifications
        if item.get("target_id") == artifact_id and item.get("status") == "PASS"
    )
    return PixeloramaSourceInspection(
        artifact=artifact,
        verification_ids=verification_ids,
        byte_count=path.stat().st_size,
    )
