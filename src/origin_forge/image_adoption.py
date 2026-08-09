from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .path_policy import portable_relative_path
from .pixelorama_png import PngError, inspect_rgba8_png
from .runtime import OriginForgeRuntime


class ImageAdoptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageAdoptionResult:
    source_artifact_id: str
    adopted_artifact_id: str
    verification_id: str
    destination_path: str
    content_hash: str
    pixel_hash: str
    width: int
    height: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_artifact_id": self.source_artifact_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "verification_id": self.verification_id,
            "destination_path": self.destination_path,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "width": self.width,
            "height": self.height,
            "existing_asset_overwritten": False,
            "task_status_changed": False,
            "semantic_visual_quality_verified": False,
        }


class GeneratedImageAdopter:
    """Explicitly publish one verified generated raster as a new project file only."""

    SOURCE_TYPE = "GENERATED_RASTER_PNG"
    SOURCE_VERIFICATION = "image-output-integrity"
    SOURCE_VERIFIER = "OriginForge.ImageGenerationService"
    MAX_BYTES = 128 * 1024 * 1024

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.lineage = OriginForgeLineage(runtime)

    def _verified_source(self, artifact_id: str) -> tuple[dict[str, object], Path, bytes]:
        if not validate_id(artifact_id, IdKind.ARTIFACT):
            raise ValueError("source_artifact_id must be an ART ID")
        artifact = self.lineage.get_artifact(artifact_id)
        if artifact["type"] != self.SOURCE_TYPE:
            raise ImageAdoptionError("source Artifact is not a generated raster output")
        verifications = self.lineage.list_artifact_verifications(artifact_id)
        passes = [
            row
            for row in verifications
            if row["verification_type"] == self.SOURCE_VERIFICATION
            and row["verifier"] == self.SOURCE_VERIFIER
            and row["status"] == "PASS"
        ]
        if not passes:
            raise ImageAdoptionError(
                "source Artifact lacks PASS image-output-integrity evidence"
            )
        path = self.lineage.local_artifact_path(artifact_id)
        try:
            path.resolve(strict=True).relative_to(
                (self.runtime.state_dir / "image-workspaces").resolve(strict=True)
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ImageAdoptionError(
                "source Artifact must be an isolated Origin Forge image output"
            ) from exc
        if path.is_symlink() or not path.is_file():
            raise ImageAdoptionError("source Artifact file is missing or unsafe")
        if path.stat().st_size > self.MAX_BYTES:
            raise ImageAdoptionError("source Artifact exceeds adoption byte limit")
        data = path.read_bytes()
        content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        if content_hash != artifact["content_hash"]:
            raise ImageAdoptionError("source Artifact bytes drifted after verification")
        try:
            inspect_rgba8_png(data)
        except PngError as exc:
            raise ImageAdoptionError("source Artifact is not an accepted RGBA8 PNG") from exc
        return artifact, path, data

    def adopt_new(
        self,
        source_artifact_id: str,
        destination_relative_path: str,
    ) -> ImageAdoptionResult:
        artifact, source, data = self._verified_source(source_artifact_id)
        try:
            relative = portable_relative_path(destination_relative_path)
        except ValueError as exc:
            raise ImageAdoptionError("invalid adoption destination path") from exc
        if relative.suffix.lower() != ".png":
            raise ImageAdoptionError("generated image adoption destination must be PNG")
        destination = self.runtime.project_root / relative
        if destination.is_symlink() or destination.exists():
            raise ImageAdoptionError(
                "generated image adoption is create-only and refuses existing destinations"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        project_root = self.runtime.project_root.resolve()
        current = project_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ImageAdoptionError("adoption destination contains a symlink")
        try:
            destination.parent.resolve().relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ImageAdoptionError("adoption destination escapes project root") from exc

        temp = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            with source.open("rb") as src, temp.open("xb") as dst:
                total = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        raise ImageAdoptionError("source exceeded adoption byte limit")
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            try:
                os.link(temp, destination)
            except FileExistsError as exc:
                raise ImageAdoptionError(
                    "adoption destination appeared concurrently; refusing overwrite"
                ) from exc
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        if destination.is_symlink() or not destination.is_file():
            raise ImageAdoptionError("adopted destination is not a regular file")
        adopted_data = destination.read_bytes()
        if adopted_data != data:
            try:
                destination.unlink()
            except OSError:
                pass
            raise ImageAdoptionError("adopted bytes do not match verified source")
        inspection = inspect_rgba8_png(adopted_data)
        content_hash = "sha256:" + hashlib.sha256(adopted_data).hexdigest()

        adopted_artifact_id = self.lineage.create_artifact(
            artifact_type="ADOPTED_GENERATED_RASTER_PNG",
            path_or_uri=str(destination),
            parent_artifact_id=source_artifact_id,
            created_by_run_id=artifact.get("created_by_run_id"),
            model_id=artifact.get("model_id"),
            status="ADOPTED",
        )
        verification_id = self.lineage.record_artifact_verification(
            adopted_artifact_id,
            verification_type="image-adoption-integrity",
            verifier="OriginForge.GeneratedImageAdopter",
            status="PASS",
            evidence={
                "source_artifact_id": source_artifact_id,
                "source_content_hash": artifact["content_hash"],
                "destination_path": relative.as_posix(),
                "content_hash": content_hash,
                "pixel_hash": inspection.pixel_hash,
                "width": inspection.width,
                "height": inspection.height,
                "source_verification_type": self.SOURCE_VERIFICATION,
                "existing_asset_overwritten": False,
                "production_task_verified": False,
                "semantic_visual_quality_verified": False,
            },
            run_id=artifact.get("created_by_run_id"),
        )
        return ImageAdoptionResult(
            source_artifact_id=source_artifact_id,
            adopted_artifact_id=adopted_artifact_id,
            verification_id=verification_id,
            destination_path=relative.as_posix(),
            content_hash=content_hash,
            pixel_hash=inspection.pixel_hash,
            width=inspection.width,
            height=inspection.height,
        )
