from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .path_policy import portable_relative_path
from .runtime import OriginForgeRuntime


class PixeloramaAdoptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernedPixeloramaAdoptionResult:
    source_artifact_id: str
    adopted_artifact_id: str
    verification_id: str
    destination_path: str
    content_hash: str
    byte_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_artifact_id": self.source_artifact_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "verification_id": self.verification_id,
            "destination_path": self.destination_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "existing_asset_overwritten": False,
            "production_task_verified": False,
        }


class GovernedPixeloramaOutputAdopter:
    """Publish one verified isolated media output as a new project file only."""

    ALLOWED_SOURCE_TYPES = {
        "RASTER_EXPORT_PNG",
        "SPRITESHEET_EXPORT",
        "PIXELORAMA_PROJECT",
    }
    PROTECTED_ROOTS = {".git", ".origin-forge"}

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_source_bytes: int = 512 * 1024 * 1024,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if (
            not isinstance(max_source_bytes, int)
            or isinstance(max_source_bytes, bool)
            or max_source_bytes <= 0
            or max_source_bytes > 8 * 1024 * 1024 * 1024
        ):
            raise ValueError("max_source_bytes must be between 1 and 8 GiB")
        self.runtime = runtime
        self.lineage = OriginForgeLineage(runtime)
        self.max_source_bytes = max_source_bytes

    def _artifact_row(self, artifact_id: str) -> dict[str, object]:
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
                (artifact_id, self.runtime.project_id()),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return dict(row)

    @staticmethod
    def _tool_versions(artifact: dict[str, object]) -> tuple[str, ...]:
        raw = artifact.get("tool_versions_json")
        if not isinstance(raw, str):
            raise PixeloramaAdoptionError("source Artifact tool_versions_json is invalid")
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PixeloramaAdoptionError(
                "source Artifact tool_versions_json is invalid"
            ) from exc
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))
        ):
            raise PixeloramaAdoptionError(
                "source Artifact tool_versions_json is invalid"
            )
        return tuple(values)

    def _source_path(self, artifact: dict[str, object]) -> Path:
        raw = artifact.get("path_or_uri")
        if not isinstance(raw, str) or not raw or "://" in raw:
            raise PixeloramaAdoptionError("source Artifact path is invalid")
        source = Path(raw)
        if not source.is_absolute():
            source = self.runtime.project_root / source
        if source.is_symlink():
            raise PixeloramaAdoptionError("source Artifact path may not be a symlink")
        try:
            resolved = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PixeloramaAdoptionError("source Artifact file is unavailable") from exc
        if not resolved.is_file():
            raise PixeloramaAdoptionError("source Artifact path must be a regular file")
        try:
            relative = resolved.relative_to(self.runtime.state_dir.resolve())
        except ValueError as exc:
            raise PixeloramaAdoptionError(
                "adoption source must be an isolated Origin Forge media output"
            ) from exc
        parts = relative.parts
        if len(parts) < 4 or parts[0] != "media-workspaces":
            raise PixeloramaAdoptionError(
                "adoption source must be inside a media workspace output directory"
            )
        if not validate_id(parts[1], IdKind.MEDIA_WORKSPACE):
            raise PixeloramaAdoptionError("adoption source media workspace ID is invalid")
        if parts[2] not in {"exports", "project"}:
            raise PixeloramaAdoptionError(
                "adoption source must be under media workspace exports/ or project/"
            )
        current = self.runtime.state_dir.resolve()
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise PixeloramaAdoptionError(
                    "adoption source path contains a symlink"
                )
        return resolved

    def _stream_hash(self, source: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        total = 0
        with source.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_source_bytes:
                    raise PixeloramaAdoptionError(
                        f"source Artifact exceeds adoption byte limit ({total} > {self.max_source_bytes})"
                    )
                digest.update(chunk)
        return "sha256:" + digest.hexdigest(), total

    def _verified_source(
        self,
        artifact_id: str,
    ) -> tuple[dict[str, object], Path, str, int]:
        artifact = self._artifact_row(artifact_id)
        if artifact.get("type") not in self.ALLOWED_SOURCE_TYPES:
            raise PixeloramaAdoptionError(
                "source Artifact is not an adoptable Pixelorama output"
            )
        with self.runtime.store.session() as conn:
            rows = list(
                conn.execute(
                    """SELECT id FROM verifications
                       WHERE target_type = 'ARTIFACT' AND target_id = ?
                         AND verification_type = 'pixelorama-output-integrity'
                         AND verifier = 'OriginForge.PixeloramaMediaService'
                         AND status = 'PASS'
                       ORDER BY created_at, id""",
                    (artifact_id,),
                )
            )
        if not rows:
            raise PixeloramaAdoptionError(
                "source Artifact lacks PASS pixelorama-output-integrity evidence"
            )
        source = self._source_path(artifact)
        current_hash, byte_count = self._stream_hash(source)
        if current_hash != artifact.get("content_hash"):
            raise PixeloramaAdoptionError(
                "source Artifact bytes drifted after verification"
            )
        return artifact, source, current_hash, byte_count

    def _destination(self, relative_path: str) -> tuple[Path, str]:
        try:
            relative = portable_relative_path(relative_path)
        except ValueError as exc:
            if "protected" in str(exc).casefold():
                raise PixeloramaAdoptionError(
                    "adoption destination may not target protected project state"
                ) from exc
            raise PixeloramaAdoptionError("invalid adoption destination path") from exc
        if not relative.parts:
            raise PixeloramaAdoptionError("adoption destination path may not be empty")
        if relative.parts[0].casefold() in self.PROTECTED_ROOTS:
            raise PixeloramaAdoptionError(
                "adoption destination may not target a protected project root"
            )
        project_root = self.runtime.project_root.resolve()
        destination = self.runtime.project_root / relative
        if destination.is_symlink() or destination.exists():
            raise PixeloramaAdoptionError(
                "v0 Pixelorama adoption is create-only and refuses existing destinations"
            )
        current = project_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise PixeloramaAdoptionError(
                    "adoption destination contains a symlink"
                )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.parent.resolve().relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PixeloramaAdoptionError(
                "adoption destination escapes project root"
            ) from exc
        return destination, relative.as_posix()

    def adopt_new(
        self,
        source_artifact_id: str,
        destination_relative_path: str,
    ) -> GovernedPixeloramaAdoptionResult:
        if not validate_id(source_artifact_id, IdKind.ARTIFACT):
            raise ValueError("source_artifact_id must be an ART ID")
        artifact, source, content_hash, byte_count = self._verified_source(
            source_artifact_id
        )
        destination, portable_destination = self._destination(
            destination_relative_path
        )

        temp = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            copied = 0
            digest = hashlib.sha256()
            with source.open("rb") as src, temp.open("xb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > self.max_source_bytes:
                        raise PixeloramaAdoptionError(
                            "source Artifact grew beyond adoption byte limit while copying"
                        )
                    digest.update(chunk)
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            copied_hash = "sha256:" + digest.hexdigest()
            if copied != byte_count or copied_hash != content_hash:
                raise PixeloramaAdoptionError(
                    "source Artifact changed while adoption copy was being created"
                )
            try:
                os.link(temp, destination)
            except FileExistsError as exc:
                raise PixeloramaAdoptionError(
                    "adoption destination appeared concurrently; refusing overwrite"
                ) from exc
        finally:
            temp.unlink(missing_ok=True)

        created_by_run_id = artifact.get("created_by_run_id")
        if created_by_run_id is not None and (
            not isinstance(created_by_run_id, str)
            or not validate_id(created_by_run_id, IdKind.RUN)
        ):
            raise PixeloramaAdoptionError("source Artifact creating Run ID is invalid")
        adopted_artifact_id = self.lineage.create_artifact(
            artifact_type=str(artifact["type"]),
            path_or_uri=str(destination),
            parent_artifact_id=source_artifact_id,
            created_by_run_id=created_by_run_id,
            tool_versions=self._tool_versions(artifact),
            status="ADOPTED",
        )
        verification_id = self.lineage.record_artifact_verification(
            adopted_artifact_id,
            verification_type="pixelorama-adoption-integrity",
            verifier="OriginForge.GovernedPixeloramaOutputAdopter",
            status="PASS",
            evidence={
                "source_artifact_id": source_artifact_id,
                "source_content_hash": content_hash,
                "source_byte_count": byte_count,
                "destination_path": portable_destination,
                "destination_content_hash": content_hash,
                "existing_asset_overwritten": False,
                "production_task_verified": False,
            },
            run_id=created_by_run_id,
        )
        return GovernedPixeloramaAdoptionResult(
            source_artifact_id=source_artifact_id,
            adopted_artifact_id=adopted_artifact_id,
            verification_id=verification_id,
            destination_path=portable_destination,
            content_hash=content_hash,
            byte_count=byte_count,
        )