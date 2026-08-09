from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .audio_wav import WavError, canonicalize_pcm16_wav, inspect_pcm16_wav
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .path_policy import portable_relative_path
from .runtime import OriginForgeRuntime, RuntimeInvariantError


class AudioAdoptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioAdoptionResult:
    source_artifact_id: str
    adopted_artifact_id: str
    verification_id: str
    destination_path: str
    content_hash: str
    pcm_hash: str
    byte_count: int
    frame_count: int
    sample_rate: int
    channels: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_artifact_id": self.source_artifact_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "verification_id": self.verification_id,
            "destination_path": self.destination_path,
            "content_hash": self.content_hash,
            "pcm_hash": self.pcm_hash,
            "byte_count": self.byte_count,
            "frame_count": self.frame_count,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "existing_asset_overwritten": False,
            "task_status_changed": False,
            "production_task_verified": False,
            "semantic_audio_quality_verified": False,
        }


class GeneratedAudioAdopter:
    """Publish one structurally verified audio output as a new project WAV only."""

    SOURCE_TYPE = "AUDIO_OUTPUT_WAV"
    SOURCE_VERIFICATION = "audio-output-integrity"
    SOURCE_VERIFIER = "OriginForge.AudioOperationService"
    MAX_BYTES = 64 * 1024 * 1024

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.lineage = OriginForgeLineage(runtime)

    def _verified_source(
        self, artifact_id: str
    ) -> tuple[dict[str, object], dict[str, object], Path, bytes]:
        if not validate_id(artifact_id, IdKind.ARTIFACT):
            raise ValueError("source_artifact_id must be an ART ID")
        artifact = self.lineage.get_artifact(artifact_id)
        if artifact["type"] != self.SOURCE_TYPE:
            raise AudioAdoptionError("source Artifact is not an audio operation output")
        verifications = self.lineage.list_artifact_verifications(artifact_id)
        passes = [
            row
            for row in verifications
            if row["verification_type"] == self.SOURCE_VERIFICATION
            and row["verifier"] == self.SOURCE_VERIFIER
            and row["status"] == "PASS"
        ]
        if len(passes) != 1:
            raise AudioAdoptionError(
                "source Artifact must have exactly one PASS audio-output-integrity verification"
            )
        verification = passes[0]
        evidence = verification.get("evidence")
        if not isinstance(evidence, dict):
            raise AudioAdoptionError("source audio verification lacks structured evidence")
        try:
            path = self.lineage.local_artifact_path(artifact_id)
        except RuntimeInvariantError as exc:
            raise AudioAdoptionError("source Artifact bytes drifted after verification") from exc
        try:
            path.resolve(strict=True).relative_to(
                (self.runtime.state_dir / "audio-workspaces").resolve(strict=True)
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise AudioAdoptionError(
                "source Artifact must be an isolated Origin Forge audio output"
            ) from exc
        if path.is_symlink() or not path.is_file():
            raise AudioAdoptionError("source Artifact file is missing or unsafe")
        if path.stat().st_size > self.MAX_BYTES:
            raise AudioAdoptionError("source Artifact exceeds adoption byte limit")
        data = path.read_bytes()
        content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        if content_hash != artifact["content_hash"]:
            raise AudioAdoptionError("source Artifact content hash drifted")
        try:
            if canonicalize_pcm16_wav(data) != data:
                raise AudioAdoptionError("source Artifact is not canonical PCM16 WAV")
            inspection = inspect_pcm16_wav(data)
        except WavError as exc:
            raise AudioAdoptionError("source Artifact is not accepted PCM16 WAV") from exc
        expected_evidence = {
            "content_hash": inspection.content_hash,
            "pcm_hash": inspection.pcm_hash,
            "byte_count": inspection.byte_count,
            "frame_count": inspection.frame_count,
            "sample_rate": inspection.sample_rate,
            "channels": inspection.channels,
            "peak_abs_sample": inspection.peak_abs_sample,
            "clipped_sample_count": inspection.clipped_sample_count,
            "nonzero_sample_count": inspection.nonzero_sample_count,
            "production_task_verified": False,
            "semantic_audio_quality_verified": False,
            "canonical_asset_adopted": False,
        }
        for key, expected in expected_evidence.items():
            if evidence.get(key) != expected:
                raise AudioAdoptionError(
                    f"source audio verification evidence drifted: {key}"
                )
        return artifact, verification, path, data

    def adopt_new(
        self,
        source_artifact_id: str,
        destination_relative_path: str,
    ) -> AudioAdoptionResult:
        artifact, _, source, data = self._verified_source(source_artifact_id)
        try:
            relative = portable_relative_path(destination_relative_path)
        except ValueError as exc:
            raise AudioAdoptionError("invalid audio adoption destination path") from exc
        if relative.suffix.lower() != ".wav":
            raise AudioAdoptionError("generated audio adoption destination must be WAV")
        destination = self.runtime.project_root / relative
        if destination.is_symlink() or destination.exists():
            raise AudioAdoptionError(
                "generated audio adoption is create-only and refuses existing destinations"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        project_root = self.runtime.project_root.resolve()
        current = project_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise AudioAdoptionError("audio adoption destination contains a symlink")
        try:
            destination.parent.resolve().relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise AudioAdoptionError("audio adoption destination escapes project root") from exc

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
                        raise AudioAdoptionError("source exceeded audio adoption byte limit")
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            try:
                os.link(temp, destination)
            except FileExistsError as exc:
                raise AudioAdoptionError(
                    "audio adoption destination appeared concurrently; refusing overwrite"
                ) from exc
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        if destination.is_symlink() or not destination.is_file():
            raise AudioAdoptionError("adopted audio destination is not a regular file")
        adopted_data = destination.read_bytes()
        if adopted_data != data:
            try:
                destination.unlink()
            except OSError:
                pass
            raise AudioAdoptionError("adopted audio bytes do not match verified source")
        try:
            if canonicalize_pcm16_wav(adopted_data) != adopted_data:
                raise AudioAdoptionError("adopted audio is not canonical PCM16 WAV")
            inspection = inspect_pcm16_wav(adopted_data)
        except WavError as exc:
            raise AudioAdoptionError("adopted audio is not accepted PCM16 WAV") from exc

        adopted_artifact_id = self.lineage.create_artifact(
            artifact_type="ADOPTED_AUDIO_WAV",
            path_or_uri=str(destination),
            parent_artifact_id=source_artifact_id,
            created_by_run_id=artifact.get("created_by_run_id"),
            model_id=artifact.get("model_id"),
            status="ADOPTED",
        )
        verification_id = self.lineage.record_artifact_verification(
            adopted_artifact_id,
            verification_type="audio-adoption-integrity",
            verifier="OriginForge.GeneratedAudioAdopter",
            status="PASS",
            evidence={
                "source_artifact_id": source_artifact_id,
                "source_content_hash": artifact["content_hash"],
                "source_verification_type": self.SOURCE_VERIFICATION,
                "destination_path": relative.as_posix(),
                "content_hash": inspection.content_hash,
                "pcm_hash": inspection.pcm_hash,
                "byte_count": inspection.byte_count,
                "frame_count": inspection.frame_count,
                "sample_rate": inspection.sample_rate,
                "channels": inspection.channels,
                "peak_abs_sample": inspection.peak_abs_sample,
                "clipped_sample_count": inspection.clipped_sample_count,
                "nonzero_sample_count": inspection.nonzero_sample_count,
                "existing_asset_overwritten": False,
                "production_task_verified": False,
                "semantic_audio_quality_verified": False,
            },
            run_id=artifact.get("created_by_run_id"),
        )
        return AudioAdoptionResult(
            source_artifact_id=source_artifact_id,
            adopted_artifact_id=adopted_artifact_id,
            verification_id=verification_id,
            destination_path=relative.as_posix(),
            content_hash=inspection.content_hash,
            pcm_hash=inspection.pcm_hash,
            byte_count=inspection.byte_count,
            frame_count=inspection.frame_count,
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
        )
