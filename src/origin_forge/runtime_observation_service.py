from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .ids import IdKind, validate_id
from .image_png import inspect_truecolor8_png
from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .runtime_observation_models import (
    RuntimeCaptureKind,
    RuntimeObservationRequest,
    RuntimeObservationResult,
    RuntimeObservationStatus,
    VisualBaselineRef,
    canonical_bytes,
)
from .runtime_visual import RuntimeVisualDiff, compare_png_to_baseline
from .state import RunStatus, TaskStatus


_MAX_CAPTURE_BYTES = 128 * 1024 * 1024


class RuntimeObservationServiceError(RuntimeError):
    pass


class RuntimeObservationBackendExecution(Protocol):
    request: RuntimeObservationRequest
    result: RuntimeObservationResult
    workspace_path: Path


class RuntimeObservationBackend(Protocol):
    def execute(
        self, request: RuntimeObservationRequest
    ) -> RuntimeObservationBackendExecution: ...


@dataclass(frozen=True)
class RuntimeCaptureArtifactEvidence:
    capture_id: str
    artifact_id: str
    integrity_verification_id: str
    visual_verification_id: str | None
    visual_diff: RuntimeVisualDiff | None

    def to_dict(self) -> dict[str, object]:
        return {
            "capture_id": self.capture_id,
            "artifact_id": self.artifact_id,
            "integrity_verification_id": self.integrity_verification_id,
            "visual_verification_id": self.visual_verification_id,
            "visual_diff": None if self.visual_diff is None else self.visual_diff.to_dict(),
        }


@dataclass(frozen=True)
class RuntimeObservationServiceResult:
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    stdout_artifact_id: str
    stderr_artifact_id: str
    captures: tuple[RuntimeCaptureArtifactEvidence, ...]
    missing_capture_ids: tuple[str, ...]
    backend_result_hash: str
    crash_detected: bool
    timed_out: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "stdout_artifact_id": self.stdout_artifact_id,
            "stderr_artifact_id": self.stderr_artifact_id,
            "captures": [value.to_dict() for value in self.captures],
            "missing_capture_ids": list(self.missing_capture_ids),
            "backend_result_hash": self.backend_result_hash,
            "crash_detected": self.crash_detected,
            "timed_out": self.timed_out,
            "production_task_verified": False,
            "task_status_changed": False,
            "visual_semantics_verified": False,
            "performance_requirement_verified": False,
            "canonical_asset_adopted": False,
        }


class RuntimeObservationService:
    """Persist bounded runtime evidence without changing production Task truth."""

    RUN_ROLE = "RUNTIME_OBSERVER"

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        adapter: RuntimeObservationBackend,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not hasattr(adapter, "execute"):
            raise TypeError("adapter must provide execute(request)")
        self.runtime = runtime
        self.adapter = adapter
        self.lineage = OriginForgeLineage(runtime)
        self.workspace_root = runtime.state_dir / "runtime-observations"

    @staticmethod
    def _hash_bytes(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise RuntimeObservationServiceError(
                f"runtime evidence path already exists: {path.name}"
            )
        with path.open("xb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())

    def _trusted_workspace(
        self,
        request: RuntimeObservationRequest,
        returned_workspace: Path,
    ) -> Path:
        state = self.runtime.state_dir.resolve()
        root = self.workspace_root
        expected = root / request.workspace_id
        returned = Path(returned_workspace)
        if root.is_symlink() or expected.is_symlink() or returned.is_symlink():
            raise RuntimeObservationServiceError(
                "runtime observation workspace may not use symlinks"
            )
        try:
            root_resolved = root.resolve(strict=True)
            root_resolved.relative_to(state)
            expected_resolved = expected.resolve(strict=True)
            expected_resolved.relative_to(root_resolved)
            returned_resolved = returned.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeObservationServiceError(
                "runtime observation workspace is not an existing protected project path"
            ) from exc
        if returned_resolved != expected_resolved:
            raise RuntimeObservationServiceError(
                "runtime backend returned a workspace outside the exact frozen workspace ID"
            )
        return expected

    def _baseline_bytes(
        self,
        request: RuntimeObservationRequest,
        baseline_artifact_ids: Mapping[str, str],
    ) -> tuple[dict[str, bytes], dict[str, str]]:
        expected = {value.baseline_id for value in request.baselines}
        if set(baseline_artifact_ids) != expected:
            raise RuntimeObservationServiceError(
                "visual baseline Artifact map must exactly match frozen baseline IDs"
            )
        refs = {value.baseline_id: value for value in request.baselines}
        data_by_id: dict[str, bytes] = {}
        artifact_refs: dict[str, str] = {}
        for baseline_id in sorted(expected):
            artifact_id = baseline_artifact_ids[baseline_id]
            if not validate_id(artifact_id, IdKind.ARTIFACT):
                raise RuntimeObservationServiceError(
                    f"visual baseline {baseline_id} is not an ARTIFACT ID"
                )
            try:
                artifact = self.lineage.get_artifact(artifact_id)
                path = self.lineage.local_artifact_path(artifact_id)
            except (KeyError, RuntimeInvariantError) as exc:
                raise RuntimeObservationServiceError(
                    f"visual baseline Artifact integrity check failed: {baseline_id}"
                ) from exc
            if path.is_symlink() or not path.is_file():
                raise RuntimeObservationServiceError(
                    f"visual baseline is missing or unsafe: {baseline_id}"
                )
            size = path.stat().st_size
            if size <= 0 or size > _MAX_CAPTURE_BYTES:
                raise RuntimeObservationServiceError(
                    f"visual baseline exceeds bounded PNG byte limit: {baseline_id}"
                )
            data = path.read_bytes()
            if len(data) != size:
                raise RuntimeObservationServiceError(
                    f"visual baseline changed while being read: {baseline_id}"
                )
            ref = refs[baseline_id]
            inspection = inspect_truecolor8_png(data)
            actual_hash = self._hash_bytes(data)
            if (
                actual_hash != ref.content_hash
                or inspection.pixel_hash != ref.pixel_hash
                or inspection.width != ref.width
                or inspection.height != ref.height
            ):
                raise RuntimeObservationServiceError(
                    f"visual baseline bytes drifted: {baseline_id}"
                )
            if artifact.get("content_hash") != ref.content_hash:
                raise RuntimeObservationServiceError(
                    f"visual baseline durable hash drifted: {baseline_id}"
                )
            data_by_id[baseline_id] = data
            artifact_refs[baseline_id] = artifact_id
        return data_by_id, artifact_refs

    @staticmethod
    def _read_bound_file(
        path: Path,
        *,
        content_hash: str,
        byte_count: int,
        label: str,
        max_bytes: int,
    ) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise RuntimeObservationServiceError(f"{label} is missing or unsafe")
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise RuntimeObservationServiceError(f"{label} has invalid byte budget")
        if not isinstance(byte_count, int) or byte_count < 0 or byte_count > max_bytes:
            raise RuntimeObservationServiceError(f"{label} exceeds byte budget")
        size = path.stat().st_size
        if size != byte_count or size > max_bytes:
            raise RuntimeObservationServiceError(f"{label} bytes drifted")
        data = path.read_bytes()
        if len(data) != size:
            raise RuntimeObservationServiceError(f"{label} changed while being read")
        actual_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual_hash != content_hash:
            raise RuntimeObservationServiceError(f"{label} bytes drifted")
        return data

    def execute(
        self,
        task_id: str,
        request: RuntimeObservationRequest,
        *,
        baseline_artifact_ids: Mapping[str, str] | None = None,
    ) -> RuntimeObservationServiceResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(request, RuntimeObservationRequest):
            raise TypeError("request must be a RuntimeObservationRequest")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"runtime observation requires RUNNING Task; task {task_id} is {task['status']}"
            )
        baseline_bytes, baseline_refs = self._baseline_bytes(
            request, baseline_artifact_ids or {}
        )
        run_id = self.runtime.start_run(task_id, role=self.RUN_ROLE)
        try:
            execution = self.adapter.execute(request)
            if execution.request.content_hash != request.content_hash:
                raise RuntimeObservationServiceError(
                    "runtime backend execution returned a different request"
                )
            execution.result.bind_request(request)
            if execution.result.status is not RuntimeObservationStatus.SUCCEEDED:
                raise RuntimeObservationServiceError(
                    f"runtime backend did not succeed: {execution.result.status.value}"
                )
            workspace = self._trusted_workspace(request, execution.workspace_path)
            request_path = workspace / "request" / "request.json"
            if request_path.is_symlink() or not request_path.is_file():
                raise RuntimeObservationServiceError("runtime backend omitted request evidence")
            expected_request_bytes = canonical_bytes(request.to_dict())
            if request_path.stat().st_size != len(expected_request_bytes):
                raise RuntimeObservationServiceError("persisted runtime request bytes drifted")
            if request_path.read_bytes() != expected_request_bytes:
                raise RuntimeObservationServiceError("persisted runtime request bytes drifted")
            result_path = workspace / "runtime" / "result.json"
            self._write_json(result_path, execution.result.to_dict())

            tool_versions = (
                f"runtime-observer:{request.backend_id}:{request.backend_version}",
                f"runtime-target:{request.target_id}:{request.target_version}",
                f"runtime-executable:{request.executable_hash}",
            )
            request_artifact_id = self.lineage.create_artifact(
                artifact_type="RUNTIME_OBSERVATION_REQUEST",
                path_or_uri=str(request_path),
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            result_artifact_id = self.lineage.create_artifact(
                artifact_type="RUNTIME_OBSERVATION_RESULT",
                path_or_uri=str(result_path),
                parent_artifact_id=request_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )

            stdout_path = workspace / execution.result.stdout.relative_path
            stderr_path = workspace / execution.result.stderr.relative_path
            self._read_bound_file(
                stdout_path,
                content_hash=execution.result.stdout.content_hash,
                byte_count=execution.result.stdout.byte_count,
                label="runtime stdout log",
                max_bytes=request.max_log_bytes,
            )
            self._read_bound_file(
                stderr_path,
                content_hash=execution.result.stderr.content_hash,
                byte_count=execution.result.stderr.byte_count,
                label="runtime stderr log",
                max_bytes=request.max_log_bytes,
            )
            stdout_artifact_id = self.lineage.create_artifact(
                artifact_type="RUNTIME_STDOUT_LOG",
                path_or_uri=str(stdout_path),
                parent_artifact_id=result_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            stderr_artifact_id = self.lineage.create_artifact(
                artifact_type="RUNTIME_STDERR_LOG",
                path_or_uri=str(stderr_path),
                parent_artifact_id=result_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )

            baseline_by_id: dict[str, VisualBaselineRef] = {
                value.baseline_id: value for value in request.baselines
            }
            spec_by_id = {value.capture_id: value for value in request.captures}
            capture_results: list[RuntimeCaptureArtifactEvidence] = []
            for output in execution.result.captures:
                spec = spec_by_id[output.capture_id]
                path = workspace / output.relative_path
                data = self._read_bound_file(
                    path,
                    content_hash=output.content_hash,
                    byte_count=output.byte_count,
                    label=f"runtime capture {output.capture_id}",
                    max_bytes=_MAX_CAPTURE_BYTES,
                )
                inspection = inspect_truecolor8_png(data)
                if (
                    inspection.pixel_hash != output.pixel_hash
                    or inspection.width != output.width
                    or inspection.height != output.height
                ):
                    raise RuntimeObservationServiceError(
                        f"runtime capture structural evidence drifted: {output.capture_id}"
                    )
                artifact_type = (
                    "RUNTIME_SCREENSHOT_PNG"
                    if output.kind is RuntimeCaptureKind.SCREENSHOT
                    else "RUNTIME_VIDEO_FRAME_PNG"
                )
                artifact_id = self.lineage.create_artifact(
                    artifact_type=artifact_type,
                    path_or_uri=str(path),
                    parent_artifact_id=result_artifact_id,
                    created_by_run_id=run_id,
                    tool_versions=tool_versions,
                    status="PRODUCED",
                )
                integrity_verification_id = self.lineage.record_artifact_verification(
                    artifact_id,
                    verification_type="runtime-capture-integrity",
                    verifier="OriginForge.RuntimeObservationService",
                    status="PASS",
                    evidence={
                        "observation_id": request.observation_id,
                        "request_hash": request.content_hash,
                        "backend_result_hash": execution.result.content_hash,
                        "capture_id": output.capture_id,
                        "kind": output.kind.value,
                        "timestamp_ms": output.timestamp_ms,
                        "content_hash": output.content_hash,
                        "pixel_hash": inspection.pixel_hash,
                        "width": inspection.width,
                        "height": inspection.height,
                        "production_task_verified": False,
                        "visual_semantics_verified": False,
                        "canonical_asset_adopted": False,
                    },
                    run_id=run_id,
                )
                visual_verification_id = None
                visual_diff = None
                if spec.baseline_id is not None:
                    baseline = baseline_by_id[spec.baseline_id]
                    visual_diff = compare_png_to_baseline(
                        baseline_bytes[spec.baseline_id], data, baseline
                    )
                    visual_verification_id = self.lineage.record_artifact_verification(
                        artifact_id,
                        verification_type="runtime-visual-regression",
                        verifier="OriginForge.RuntimeObservationService",
                        status="PASS" if visual_diff.passed else "FAIL",
                        evidence={
                            **visual_diff.to_dict(),
                            "baseline_artifact_id": baseline_refs[spec.baseline_id],
                            "capture_id": output.capture_id,
                            "production_task_verified": False,
                            "visual_semantics_verified": False,
                        },
                        run_id=run_id,
                    )
                capture_results.append(
                    RuntimeCaptureArtifactEvidence(
                        capture_id=output.capture_id,
                        artifact_id=artifact_id,
                        integrity_verification_id=integrity_verification_id,
                        visual_verification_id=visual_verification_id,
                        visual_diff=visual_diff,
                    )
                )

            observed_capture_ids = {value.capture_id for value in execution.result.captures}
            missing_capture_ids = tuple(sorted(set(spec_by_id) - observed_capture_ids))
            crash_detected = execution.result.exit_kind.value in {"FAILED", "SIGNALED"}
            timed_out = execution.result.exit_kind.value == "TIMEOUT"
            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="runtime-observation-structure",
                verifier="OriginForge.RuntimeObservationService",
                status="PASS",
                evidence={
                    "observation_id": request.observation_id,
                    "request_hash": request.content_hash,
                    "backend_result_hash": execution.result.content_hash,
                    "target_id": request.target_id,
                    "target_version": request.target_version,
                    "executable_hash": request.executable_hash,
                    "exit_kind": execution.result.exit_kind.value,
                    "exit_code": execution.result.exit_code,
                    "crash_detected": crash_detected,
                    "timed_out": timed_out,
                    "missing_capture_ids": list(missing_capture_ids),
                    "duration_ms": execution.result.performance.duration_ms,
                    "peak_rss_kib": execution.result.performance.peak_rss_kib,
                    "stdout_artifact_id": stdout_artifact_id,
                    "stderr_artifact_id": stderr_artifact_id,
                    "capture_artifact_ids": [
                        value.artifact_id for value in capture_results
                    ],
                    "baseline_artifact_ids": baseline_refs,
                    "production_task_verified": False,
                    "visual_semantics_verified": False,
                    "performance_requirement_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return RuntimeObservationServiceResult(
                run_id=run_id,
                request_artifact_id=request_artifact_id,
                result_artifact_id=result_artifact_id,
                stdout_artifact_id=stdout_artifact_id,
                stderr_artifact_id=stderr_artifact_id,
                captures=tuple(capture_results),
                missing_capture_ids=missing_capture_ids,
                backend_result_hash=execution.result.content_hash,
                crash_detected=crash_detected,
                timed_out=timed_out,
            )
        except Exception as exc:
            self._fail_run(run_id, request, exc)
            raise

    def _fail_run(
        self,
        run_id: str,
        request: RuntimeObservationRequest,
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
                    verification_type="runtime-observation-structure",
                    verifier="OriginForge.RuntimeObservationService",
                    status="FAIL",
                    evidence={
                        "observation_id": request.observation_id,
                        "request_hash": request.content_hash,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2048],
                        "production_task_verified": False,
                        "visual_semantics_verified": False,
                        "performance_requirement_verified": False,
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
