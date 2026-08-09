from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .ids import IdKind, validate_id
from .image_vision_models import (
    ImageOperationRequest,
    ImageOperationResult,
    VisionInspectionRequest,
    VisionReport,
    canonical_bytes,
)
from .lineage import OriginForgeLineage
from .pixelorama_png import PngError, inspect_rgba8_png
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import RunStatus, TaskStatus


class ImageVisionServiceError(RuntimeError):
    pass


class ImageBackendExecution(Protocol):
    request: ImageOperationRequest
    result: ImageOperationResult
    workspace_path: Path


class ImageBackendAdapter(Protocol):
    def execute(self, request: ImageOperationRequest) -> ImageBackendExecution: ...


class VisionBackendAdapter(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def model_hash(self) -> str: ...

    def inspect(
        self,
        request: VisionInspectionRequest,
        image_bytes_by_id: Mapping[str, bytes],
    ) -> VisionReport: ...


@dataclass(frozen=True)
class GeneratedImageEvidence:
    relative_path: str
    artifact_id: str
    verification_id: str
    content_hash: str
    pixel_hash: str
    width: int
    height: int

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "artifact_id": self.artifact_id,
            "verification_id": self.verification_id,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ImageGenerationServiceResult:
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    outputs: tuple[GeneratedImageEvidence, ...]
    backend_result_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "outputs": [value.to_dict() for value in self.outputs],
            "backend_result_hash": self.backend_result_hash,
            "task_status_changed": False,
            "semantic_visual_quality_verified": False,
            "canonical_asset_adopted": False,
        }


@dataclass(frozen=True)
class VisionInspectionServiceResult:
    run_id: str
    request_artifact_id: str
    report_artifact_id: str
    report_verification_id: str
    report: VisionReport

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "report_artifact_id": self.report_artifact_id,
            "report_verification_id": self.report_verification_id,
            "report_hash": self.report.content_hash,
            "semantic_findings_verified": False,
            "task_status_changed": False,
            "canonical_asset_adopted": False,
        }


class ImageGenerationService:
    """Persist one bounded image generation execution as evidence, never Task success."""

    RUN_ROLE = "IMAGE_GENERATOR"

    def __init__(self, runtime: OriginForgeRuntime, adapter: ImageBackendAdapter):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not hasattr(adapter, "execute"):
            raise TypeError("adapter must provide execute(request)")
        self.runtime = runtime
        self.adapter = adapter
        self.lineage = OriginForgeLineage(runtime)

    @staticmethod
    def _tool_versions(request: ImageOperationRequest) -> tuple[str, ...]:
        return (
            f"image-backend:{request.backend_id}:{request.backend_version}",
            f"image-workflow:{request.workflow_id}:{request.workflow_hash}",
        )

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise ImageVisionServiceError(f"evidence path already exists: {path.name}")
        with path.open("xb") as handle:
            data = canonical_bytes(value)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def execute(
        self,
        task_id: str,
        request: ImageOperationRequest,
    ) -> ImageGenerationServiceResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(request, ImageOperationRequest):
            raise TypeError("request must be an ImageOperationRequest")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"image generation requires RUNNING Task; task {task_id} is {task['status']}"
            )
        run_id = self.runtime.start_run(
            task_id,
            role=self.RUN_ROLE,
            model_profile=request.model_id,
        )
        try:
            operation = self.adapter.execute(request)
            if operation.request.content_hash != request.content_hash:
                raise ImageVisionServiceError(
                    "image backend execution returned a different request"
                )
            operation.result.bind_request(request)
            if operation.result.status.value != "SUCCEEDED":
                raise ImageVisionServiceError(
                    f"image backend did not succeed: {operation.result.status.value}"
                )
            workspace = Path(operation.workspace_path)
            request_path = workspace / "request" / "request.json"
            if request_path.is_symlink() or not request_path.is_file():
                raise ImageVisionServiceError("image backend omitted request evidence")
            expected_request = canonical_bytes(request.to_dict())
            if request_path.read_bytes() != expected_request:
                raise ImageVisionServiceError("persisted image request bytes drifted")
            result_path = workspace / "runtime" / "result.json"
            self._write_json(result_path, operation.result.to_dict())

            tool_versions = self._tool_versions(request)
            request_artifact_id = self.lineage.create_artifact(
                artifact_type="IMAGE_OPERATION_REQUEST",
                path_or_uri=str(request_path),
                created_by_run_id=run_id,
                model_id=request.model_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            result_artifact_id = self.lineage.create_artifact(
                artifact_type="IMAGE_OPERATION_RESULT",
                path_or_uri=str(result_path),
                parent_artifact_id=request_artifact_id,
                created_by_run_id=run_id,
                model_id=request.model_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )

            outputs: list[GeneratedImageEvidence] = []
            for output in operation.result.outputs:
                path = workspace / output.relative_path
                if path.is_symlink() or not path.is_file():
                    raise ImageVisionServiceError(
                        f"generated output is missing or unsafe: {output.relative_path}"
                    )
                data = path.read_bytes()
                content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
                if content_hash != output.content_hash or len(data) != output.byte_count:
                    raise ImageVisionServiceError(
                        f"generated output bytes drifted: {output.relative_path}"
                    )
                try:
                    inspection = inspect_rgba8_png(data)
                except PngError as exc:
                    raise ImageVisionServiceError(
                        f"generated output is not accepted RGBA8 PNG: {output.relative_path}"
                    ) from exc
                if (
                    inspection.pixel_hash != output.pixel_hash
                    or inspection.width != output.width
                    or inspection.height != output.height
                ):
                    raise ImageVisionServiceError(
                        f"generated raster evidence drifted: {output.relative_path}"
                    )
                artifact_id = self.lineage.create_artifact(
                    artifact_type="GENERATED_RASTER_PNG",
                    path_or_uri=str(path),
                    parent_artifact_id=result_artifact_id,
                    created_by_run_id=run_id,
                    model_id=request.model_id,
                    tool_versions=tool_versions,
                    status="PRODUCED",
                )
                verification_id = self.lineage.record_artifact_verification(
                    artifact_id,
                    verification_type="image-output-integrity",
                    verifier="OriginForge.ImageGenerationService",
                    status="PASS",
                    evidence={
                        "operation_id": request.operation_id,
                        "request_hash": request.content_hash,
                        "backend_result_hash": operation.result.content_hash,
                        "backend_id": request.backend_id,
                        "backend_version": request.backend_version,
                        "workflow_id": request.workflow_id,
                        "workflow_hash": request.workflow_hash,
                        "model_id": request.model_id,
                        "model_hash": request.model_hash,
                        "relative_path": output.relative_path,
                        "content_hash": content_hash,
                        "pixel_hash": inspection.pixel_hash,
                        "width": inspection.width,
                        "height": inspection.height,
                        "semantic_visual_quality_verified": False,
                        "production_task_verified": False,
                        "canonical_asset_adopted": False,
                    },
                    run_id=run_id,
                )
                outputs.append(
                    GeneratedImageEvidence(
                        relative_path=output.relative_path,
                        artifact_id=artifact_id,
                        verification_id=verification_id,
                        content_hash=content_hash,
                        pixel_hash=inspection.pixel_hash,
                        width=inspection.width,
                        height=inspection.height,
                    )
                )

            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="image-generation-structure",
                verifier="OriginForge.ImageGenerationService",
                status="PASS",
                evidence={
                    "operation_id": request.operation_id,
                    "request_hash": request.content_hash,
                    "backend_result_hash": operation.result.content_hash,
                    "output_artifact_ids": [value.artifact_id for value in outputs],
                    "semantic_visual_quality_verified": False,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return ImageGenerationServiceResult(
                run_id=run_id,
                request_artifact_id=request_artifact_id,
                result_artifact_id=result_artifact_id,
                outputs=tuple(outputs),
                backend_result_hash=operation.result.content_hash,
            )
        except Exception as exc:
            self._fail_run(run_id, request, exc)
            raise

    def _fail_run(
        self,
        run_id: str,
        request: ImageOperationRequest,
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
                    verification_type="image-generation-structure",
                    verifier="OriginForge.ImageGenerationService",
                    status="FAIL",
                    evidence={
                        "operation_id": request.operation_id,
                        "request_hash": request.content_hash,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2048],
                        "semantic_visual_quality_verified": False,
                        "production_task_verified": False,
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


class VisionInspectionService:
    """Persist one isolated advisory vision inspection over exact existing Artifacts."""

    RUN_ROLE = "VISION_INSPECTOR"

    def __init__(self, runtime: OriginForgeRuntime, adapter: VisionBackendAdapter):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not hasattr(adapter, "inspect"):
            raise TypeError("adapter must provide inspect(request, image_bytes_by_id)")
        self.runtime = runtime
        self.adapter = adapter
        self.lineage = OriginForgeLineage(runtime)
        self.inspection_root = runtime.state_dir / "vision-inspections"

    def _inspection_dir(self, inspection_id: str) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.inspection_root.is_symlink():
            raise ImageVisionServiceError("vision inspection root may not be a symlink")
        self.inspection_root.mkdir(parents=True, exist_ok=True)
        try:
            self.inspection_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ImageVisionServiceError(
                "vision inspection root escapes protected project state"
            ) from exc
        path = self.inspection_root / inspection_id
        if path.exists() or path.is_symlink():
            raise ImageVisionServiceError(
                f"vision inspection evidence already exists: {inspection_id}"
            )
        path.mkdir()
        return path

    def _source_bytes(
        self,
        request: VisionInspectionRequest,
        image_artifact_ids: Mapping[str, str],
    ) -> tuple[dict[str, bytes], dict[str, str]]:
        expected_ids = {value.image_id for value in request.images}
        if set(image_artifact_ids) != expected_ids:
            raise ImageVisionServiceError(
                "vision source Artifact map must exactly match frozen image IDs"
            )
        refs = {value.image_id: value for value in request.images}
        data_by_id: dict[str, bytes] = {}
        artifact_refs: dict[str, str] = {}
        for image_id in sorted(expected_ids):
            artifact_id = image_artifact_ids[image_id]
            if not validate_id(artifact_id, IdKind.ARTIFACT):
                raise ImageVisionServiceError(
                    f"vision source for {image_id} is not an ARTIFACT ID"
                )
            artifact = self.lineage.get_artifact(artifact_id)
            path = self.lineage.local_artifact_path(artifact_id)
            data = path.read_bytes()
            ref = refs[image_id]
            content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
            if content_hash != ref.content_hash or len(data) != ref.byte_count:
                raise ImageVisionServiceError(
                    f"vision source Artifact does not match frozen bytes: {image_id}"
                )
            try:
                inspection = inspect_rgba8_png(data)
            except PngError as exc:
                raise ImageVisionServiceError(
                    f"vision source Artifact is not accepted RGBA8 PNG: {image_id}"
                ) from exc
            if (
                inspection.pixel_hash != ref.pixel_hash
                or inspection.width != ref.width
                or inspection.height != ref.height
            ):
                raise ImageVisionServiceError(
                    f"vision source Artifact does not match frozen raster evidence: {image_id}"
                )
            if artifact.get("content_hash") != ref.content_hash:
                raise ImageVisionServiceError(
                    f"vision source Artifact durable hash does not match request: {image_id}"
                )
            data_by_id[image_id] = data
            artifact_refs[image_id] = artifact_id
        return data_by_id, artifact_refs

    def execute(
        self,
        task_id: str,
        request: VisionInspectionRequest,
        *,
        image_artifact_ids: Mapping[str, str],
    ) -> VisionInspectionServiceResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(request, VisionInspectionRequest):
            raise TypeError("request must be a VisionInspectionRequest")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"vision inspection requires RUNNING Task; task {task_id} is {task['status']}"
            )
        if request.expected_model_id != self.adapter.model_id:
            raise ImageVisionServiceError("vision adapter model_id does not match request")
        if request.expected_model_hash != self.adapter.model_hash:
            raise ImageVisionServiceError("vision adapter model_hash does not match request")
        data_by_id, artifact_refs = self._source_bytes(request, image_artifact_ids)
        run_id = self.runtime.start_run(
            task_id,
            role=self.RUN_ROLE,
            model_profile=request.expected_model_id,
        )
        evidence_dir: Path | None = None
        try:
            evidence_dir = self._inspection_dir(request.inspection_id)
            request_path = evidence_dir / "request.json"
            with request_path.open("xb") as handle:
                handle.write(canonical_bytes(request.to_dict()))
                handle.flush()
                os.fsync(handle.fileno())
            request_artifact_id = self.lineage.create_artifact(
                artifact_type="VISION_INSPECTION_REQUEST",
                path_or_uri=str(request_path),
                created_by_run_id=run_id,
                model_id=request.expected_model_id,
                status="CAPTURED",
            )

            report = self.adapter.inspect(request, data_by_id)
            report.bind_request(request)
            if report.semantic_findings_verified or not report.advisory_only:
                raise ImageVisionServiceError(
                    "vision backend attempted to exceed advisory authority"
                )
            report_path = evidence_dir / "report.json"
            with report_path.open("xb") as handle:
                handle.write(canonical_bytes(report.to_dict()))
                handle.flush()
                os.fsync(handle.fileno())
            report_artifact_id = self.lineage.create_artifact(
                artifact_type="VISION_ADVISORY_REPORT",
                path_or_uri=str(report_path),
                parent_artifact_id=request_artifact_id,
                created_by_run_id=run_id,
                model_id=request.expected_model_id,
                status="CAPTURED",
            )
            report_verification_id = self.lineage.record_artifact_verification(
                report_artifact_id,
                verification_type="vision-report-structure",
                verifier="OriginForge.VisionInspectionService",
                status="PASS",
                evidence={
                    "inspection_id": request.inspection_id,
                    "request_hash": request.content_hash,
                    "report_hash": report.content_hash,
                    "model_id": report.model_id,
                    "model_hash": report.model_hash,
                    "source_artifact_ids": artifact_refs,
                    "source_images": [value.to_dict() for value in request.images],
                    "finding_count": len(report.findings),
                    "semantic_findings_verified": False,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="vision-inspection-structure",
                verifier="OriginForge.VisionInspectionService",
                status="PASS",
                evidence={
                    "inspection_id": request.inspection_id,
                    "request_hash": request.content_hash,
                    "report_artifact_id": report_artifact_id,
                    "report_hash": report.content_hash,
                    "source_artifact_ids": artifact_refs,
                    "semantic_findings_verified": False,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return VisionInspectionServiceResult(
                run_id=run_id,
                request_artifact_id=request_artifact_id,
                report_artifact_id=report_artifact_id,
                report_verification_id=report_verification_id,
                report=report,
            )
        except Exception as exc:
            self._fail_run(run_id, request, exc)
            raise

    def _fail_run(
        self,
        run_id: str,
        request: VisionInspectionRequest,
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
                    verification_type="vision-inspection-structure",
                    verifier="OriginForge.VisionInspectionService",
                    status="FAIL",
                    evidence={
                        "inspection_id": request.inspection_id,
                        "request_hash": request.content_hash,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2048],
                        "semantic_findings_verified": False,
                        "production_task_verified": False,
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
