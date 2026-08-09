from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .audio_models import (
    AudioOperationRequest,
    AudioOperationResult,
    AudioResultStatus,
    canonical_bytes,
)
from .audio_wav import WavError, canonicalize_pcm16_wav, inspect_pcm16_wav
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import RunStatus, TaskStatus


class AudioServiceError(RuntimeError):
    pass


class AudioBackendExecution(Protocol):
    request: AudioOperationRequest
    result: AudioOperationResult
    workspace_path: Path


class AudioBackendAdapter(Protocol):
    def execute(
        self,
        request: AudioOperationRequest,
        source_bytes_by_id: Mapping[str, bytes],
    ) -> AudioBackendExecution: ...


@dataclass(frozen=True)
class AudioOutputArtifactEvidence:
    relative_path: str
    artifact_id: str
    verification_id: str
    content_hash: str
    pcm_hash: str
    byte_count: int
    frame_count: int
    sample_rate: int
    channels: int
    peak_abs_sample: int
    clipped_sample_count: int
    nonzero_sample_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "artifact_id": self.artifact_id,
            "verification_id": self.verification_id,
            "content_hash": self.content_hash,
            "pcm_hash": self.pcm_hash,
            "byte_count": self.byte_count,
            "frame_count": self.frame_count,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "peak_abs_sample": self.peak_abs_sample,
            "clipped_sample_count": self.clipped_sample_count,
            "nonzero_sample_count": self.nonzero_sample_count,
        }


@dataclass(frozen=True)
class AudioOperationServiceResult:
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    output: AudioOutputArtifactEvidence
    backend_result_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "output": self.output.to_dict(),
            "backend_result_hash": self.backend_result_hash,
            "task_status_changed": False,
            "production_task_verified": False,
            "semantic_audio_quality_verified": False,
            "canonical_asset_adopted": False,
        }


class AudioOperationService:
    """Persist one bounded audio execution as structural evidence, never Task success."""

    RUN_ROLE = "AUDIO_OPERATOR"

    def __init__(self, runtime: OriginForgeRuntime, adapter: AudioBackendAdapter):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not hasattr(adapter, "execute"):
            raise TypeError("adapter must provide execute(request, source_bytes_by_id)")
        self.runtime = runtime
        self.adapter = adapter
        self.lineage = OriginForgeLineage(runtime)
        self.workspace_root = runtime.state_dir / "audio-workspaces"

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise AudioServiceError(f"audio evidence path already exists: {path.name}")
        with path.open("xb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _tool_versions(request: AudioOperationRequest) -> tuple[str, ...]:
        values = [
            f"audio-backend:{request.backend_id}:{request.backend_version}",
            f"audio-profile:{request.profile_id}:{request.profile_hash}",
        ]
        if request.model_id is not None and request.model_hash is not None:
            values.append(f"audio-model:{request.model_id}:{request.model_hash}")
        return tuple(values)

    def _source_bytes(
        self,
        request: AudioOperationRequest,
        source_artifact_ids: Mapping[str, str],
    ) -> tuple[dict[str, bytes], dict[str, str]]:
        expected_ids = {source.source_id for source in request.inputs}
        if set(source_artifact_ids) != expected_ids:
            raise AudioServiceError(
                "audio source Artifact map must exactly match frozen source IDs"
            )
        refs = {source.source_id: source for source in request.inputs}
        data_by_id: dict[str, bytes] = {}
        artifact_refs: dict[str, str] = {}
        for source_id in sorted(expected_ids):
            artifact_id = source_artifact_ids[source_id]
            if not validate_id(artifact_id, IdKind.ARTIFACT):
                raise AudioServiceError(
                    f"audio source for {source_id} is not an ARTIFACT ID"
                )
            artifact = self.lineage.get_artifact(artifact_id)
            path = self.lineage.local_artifact_path(artifact_id)
            if path.is_symlink() or not path.is_file():
                raise AudioServiceError(f"audio source Artifact is missing or unsafe: {source_id}")
            data = path.read_bytes()
            ref = refs[source_id]
            actual_hash = "sha256:" + hashlib.sha256(data).hexdigest()
            if actual_hash != ref.content_hash or len(data) != ref.byte_count:
                raise AudioServiceError(
                    f"audio source Artifact does not match frozen bytes: {source_id}"
                )
            if artifact.get("content_hash") != ref.content_hash:
                raise AudioServiceError(
                    f"audio source Artifact durable hash does not match request: {source_id}"
                )
            try:
                inspection = inspect_pcm16_wav(data)
            except WavError as exc:
                raise AudioServiceError(
                    f"audio source Artifact is not accepted PCM16 WAV: {source_id}"
                ) from exc
            if (
                inspection.pcm_hash != ref.pcm_hash
                or inspection.frame_count != ref.frame_count
                or inspection.sample_rate != ref.sample_rate
                or inspection.channels != ref.channels
            ):
                raise AudioServiceError(
                    f"audio source Artifact structural evidence drifted: {source_id}"
                )
            data_by_id[source_id] = data
            artifact_refs[source_id] = artifact_id
        return data_by_id, artifact_refs

    def _trusted_workspace(
        self,
        request: AudioOperationRequest,
        returned_workspace: Path,
    ) -> Path:
        state = self.runtime.state_dir.resolve()
        root = self.workspace_root
        expected = root / request.workspace_id
        returned = Path(returned_workspace)
        if root.is_symlink():
            raise AudioServiceError("audio workspace root may not be a symlink")
        if expected.is_symlink() or returned.is_symlink():
            raise AudioServiceError("audio workspace may not be a symlink")
        try:
            root_resolved = root.resolve(strict=True)
            root_resolved.relative_to(state)
            expected_resolved = expected.resolve(strict=True)
            expected_resolved.relative_to(root_resolved)
            returned_resolved = returned.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise AudioServiceError(
                "audio workspace is not an existing protected project path"
            ) from exc
        if returned_resolved != expected_resolved:
            raise AudioServiceError(
                "audio backend returned a workspace outside the exact frozen workspace ID"
            )
        return expected

    def execute(
        self,
        task_id: str,
        request: AudioOperationRequest,
        *,
        source_artifact_ids: Mapping[str, str] | None = None,
    ) -> AudioOperationServiceResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(request, AudioOperationRequest):
            raise TypeError("request must be an AudioOperationRequest")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"audio operation requires RUNNING Task; task {task_id} is {task['status']}"
            )
        sources, artifact_refs = self._source_bytes(
            request, source_artifact_ids or {}
        )
        run_id = self.runtime.start_run(
            task_id,
            role=self.RUN_ROLE,
            model_profile=request.model_id,
        )
        try:
            execution = self.adapter.execute(request, sources)
            if execution.request.content_hash != request.content_hash:
                raise AudioServiceError("audio backend execution returned a different request")
            execution.result.bind_request(request)
            if execution.result.status is not AudioResultStatus.SUCCEEDED:
                raise AudioServiceError(
                    f"audio backend did not succeed: {execution.result.status.value}"
                )
            workspace = self._trusted_workspace(request, execution.workspace_path)
            request_path = workspace / "request" / "request.json"
            if request_path.is_symlink() or not request_path.is_file():
                raise AudioServiceError("audio backend omitted request evidence")
            if request_path.read_bytes() != canonical_bytes(request.to_dict()):
                raise AudioServiceError("persisted audio request bytes drifted")
            result_path = workspace / "runtime" / "result.json"
            self._write_json(result_path, execution.result.to_dict())

            tool_versions = self._tool_versions(request)
            request_artifact_id = self.lineage.create_artifact(
                artifact_type="AUDIO_OPERATION_REQUEST",
                path_or_uri=str(request_path),
                created_by_run_id=run_id,
                model_id=request.model_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            result_artifact_id = self.lineage.create_artifact(
                artifact_type="AUDIO_OPERATION_RESULT",
                path_or_uri=str(result_path),
                parent_artifact_id=request_artifact_id,
                created_by_run_id=run_id,
                model_id=request.model_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )

            output = execution.result.outputs[0]
            path = workspace / output.relative_path
            if path.is_symlink() or not path.is_file():
                raise AudioServiceError("audio backend output is missing or unsafe")
            data = path.read_bytes()
            actual_hash = "sha256:" + hashlib.sha256(data).hexdigest()
            if actual_hash != output.content_hash or len(data) != output.byte_count:
                raise AudioServiceError("audio backend output bytes drifted")
            try:
                if canonicalize_pcm16_wav(
                    data, max_duration_ms=request.max_duration_ms
                ) != data:
                    raise AudioServiceError("audio backend output is not canonical PCM16 WAV")
                inspection = inspect_pcm16_wav(
                    data, max_duration_ms=request.max_duration_ms
                )
            except WavError as exc:
                raise AudioServiceError("audio backend output is not accepted PCM16 WAV") from exc
            expected_metrics = (
                output.pcm_hash,
                output.frame_count,
                output.sample_rate,
                output.channels,
                output.peak_abs_sample,
                output.clipped_sample_count,
                output.nonzero_sample_count,
            )
            actual_metrics = (
                inspection.pcm_hash,
                inspection.frame_count,
                inspection.sample_rate,
                inspection.channels,
                inspection.peak_abs_sample,
                inspection.clipped_sample_count,
                inspection.nonzero_sample_count,
            )
            if actual_metrics != expected_metrics:
                raise AudioServiceError("audio backend structural evidence drifted")
            if (
                inspection.sample_rate != request.target_sample_rate
                or inspection.channels != request.target_channels
            ):
                raise AudioServiceError("audio backend output format drifted from request")

            output_artifact_id = self.lineage.create_artifact(
                artifact_type="AUDIO_OUTPUT_WAV",
                path_or_uri=str(path),
                parent_artifact_id=result_artifact_id,
                created_by_run_id=run_id,
                model_id=request.model_id,
                tool_versions=tool_versions,
                status="PRODUCED",
            )
            verification_id = self.lineage.record_artifact_verification(
                output_artifact_id,
                verification_type="audio-output-integrity",
                verifier="OriginForge.AudioOperationService",
                status="PASS",
                evidence={
                    "operation_id": request.operation_id,
                    "request_hash": request.content_hash,
                    "backend_result_hash": execution.result.content_hash,
                    "backend_id": request.backend_id,
                    "backend_version": request.backend_version,
                    "profile_id": request.profile_id,
                    "profile_hash": request.profile_hash,
                    "model_id": request.model_id,
                    "model_hash": request.model_hash,
                    "source_artifact_ids": artifact_refs,
                    "relative_path": output.relative_path,
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
                },
                run_id=run_id,
            )
            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="audio-operation-structure",
                verifier="OriginForge.AudioOperationService",
                status="PASS",
                evidence={
                    "operation_id": request.operation_id,
                    "request_hash": request.content_hash,
                    "backend_result_hash": execution.result.content_hash,
                    "source_artifact_ids": artifact_refs,
                    "output_artifact_id": output_artifact_id,
                    "production_task_verified": False,
                    "semantic_audio_quality_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            evidence = AudioOutputArtifactEvidence(
                relative_path=output.relative_path,
                artifact_id=output_artifact_id,
                verification_id=verification_id,
                content_hash=inspection.content_hash,
                pcm_hash=inspection.pcm_hash,
                byte_count=inspection.byte_count,
                frame_count=inspection.frame_count,
                sample_rate=inspection.sample_rate,
                channels=inspection.channels,
                peak_abs_sample=inspection.peak_abs_sample,
                clipped_sample_count=inspection.clipped_sample_count,
                nonzero_sample_count=inspection.nonzero_sample_count,
            )
            return AudioOperationServiceResult(
                run_id=run_id,
                request_artifact_id=request_artifact_id,
                result_artifact_id=result_artifact_id,
                output=evidence,
                backend_result_hash=execution.result.content_hash,
            )
        except Exception as exc:
            self._fail_run(run_id, request, exc)
            raise

    def _fail_run(
        self,
        run_id: str,
        request: AudioOperationRequest,
        exc: Exception,
    ) -> None:
        try:
            run = self.runtime.get_run(run_id)
            if run["status"] != RunStatus.RUNNING.value:
                return
            try:
                self.runtime.record_verification(
                    "RUN",
                    run_id,
                    verification_type="audio-operation-structure",
                    verifier="OriginForge.AudioOperationService",
                    status="FAIL",
                    evidence={
                        "operation_id": request.operation_id,
                        "request_hash": request.content_hash,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2048],
                        "production_task_verified": False,
                        "semantic_audio_quality_verified": False,
                        "canonical_asset_adopted": False,
                    },
                    run_id=run_id,
                )
            finally:
                self.runtime.finish_run(
                    run_id,
                    RunStatus.FAILED,
                    failure_reason=f"{type(exc).__name__}: {str(exc)[:2048]}",
                )
        except Exception:
            pass
