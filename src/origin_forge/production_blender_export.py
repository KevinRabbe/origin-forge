from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .blender_adapter import BlenderAdapter, BlenderExecution, BlenderRuntimeProfile
from .blender_models import BlenderJobRequest
from .blockbench_glb import GlbError, inspect_glb
from .blockbench_models import canonical_bytes
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import RunStatus, TaskStatus


class ProductionBlenderExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlenderExportServiceResult:
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    output_artifact_id: str
    output_verification_id: str
    run_verification_id: str
    operation: BlenderExecution

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "output_artifact_id": self.output_artifact_id,
            "output_verification_id": self.output_verification_id,
            "run_verification_id": self.run_verification_id,
            "operation": self.operation.to_dict(),
            "task_status_changed": False,
            "canonical_asset_adopted": False,
            "provenance_signed": False,
        }


class BlenderExportService:
    """Persist one governed Blender GLB export without Task outcome authority."""

    RUN_ROLE = "MODEL3D"
    VERIFIER = "OriginForge.BlenderExportService"

    def __init__(self, runtime: OriginForgeRuntime, profile: BlenderRuntimeProfile):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, BlenderRuntimeProfile):
            raise TypeError("profile must be a BlenderRuntimeProfile")
        self.runtime = runtime
        self.profile = profile
        self.adapter = BlenderAdapter(runtime, profile)
        self.lineage = OriginForgeLineage(runtime)

    def _evidence_root(self, run_id: str) -> Path:
        state = self.runtime.state_dir
        if state.is_symlink():
            raise ProductionBlenderExportError(
                "protected project state may not be a symlink"
            )
        root = state / "blender-production-export-evidence"
        if root.is_symlink():
            raise ProductionBlenderExportError(
                "Blender production evidence root may not be a symlink"
            )
        root.mkdir(parents=True, exist_ok=True)
        try:
            state_resolved = state.resolve(strict=True)
            root_resolved = root.resolve(strict=True)
            root_resolved.relative_to(state_resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionBlenderExportError(
                "Blender production evidence root escaped protected state"
            ) from exc
        run_root = root / run_id
        if run_root.exists() or run_root.is_symlink():
            raise ProductionBlenderExportError(
                "Blender production Run evidence path already exists"
            )
        run_root.mkdir()
        return run_root

    @staticmethod
    def _write_json_once(root: Path, filename: str, value: dict[str, object]) -> Path:
        path = root / filename
        if path.exists() or path.is_symlink():
            raise ProductionBlenderExportError(
                f"Blender production evidence already exists: {filename}"
            )
        payload = canonical_bytes(value)
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def _tool_versions(self, operation: BlenderExecution) -> tuple[str, ...]:
        if (
            operation.blender_version != self.profile.expected_blender_version
            or operation.runtime_hash != self.profile.runtime_hash
            or operation.runner_fingerprint != self.profile.runner_fingerprint
        ):
            raise ProductionBlenderExportError(
                "Blender execution identity does not match trusted production profile"
            )
        return (
            f"blender:{operation.blender_version}",
            f"blender-runtime:{operation.runtime_hash}",
            f"blender-runner:{operation.runner_fingerprint}",
            "origin-forge-blender-export-service:1",
        )

    def _reinspect_output(
        self,
        request: BlenderJobRequest,
        operation: BlenderExecution,
    ) -> tuple[Path, dict[str, object]]:
        if operation.request != request:
            raise ProductionBlenderExportError(
                "Blender adapter result does not bind the exact request"
            )
        workspace = operation.workspace_path
        expected_workspace = self.runtime.state_dir / "model3d-workspaces" / request.workspace_id
        if workspace.is_symlink() or expected_workspace.is_symlink():
            raise ProductionBlenderExportError("Blender result workspace may not be a symlink")
        try:
            workspace_resolved = workspace.resolve(strict=True)
            expected_resolved = expected_workspace.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProductionBlenderExportError("Blender result workspace is unavailable") from exc
        if workspace_resolved != expected_resolved or not workspace_resolved.is_dir():
            raise ProductionBlenderExportError(
                "Blender result workspace is not the exact infrastructure-owned workspace"
            )

        current = workspace
        for part in Path(request.output_relative_path).parts:
            current = current / part
            if current.is_symlink():
                raise ProductionBlenderExportError(
                    "Blender output path contains a symlink component"
                )
        try:
            output = current.resolve(strict=True)
            output.relative_to((workspace_resolved / "exports").resolve(strict=True))
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionBlenderExportError(
                "Blender output escaped its 3D workspace"
            ) from exc
        if not output.is_file() or output != operation.output_path.resolve(strict=True):
            raise ProductionBlenderExportError(
                "Blender result output path is not the exact declared GLB"
            )
        byte_count = output.stat().st_size
        if not 1 <= byte_count <= request.budget.max_output_bytes:
            raise ProductionBlenderExportError(
                "Blender output byte count is outside the frozen request budget"
            )
        data = output.read_bytes()
        if len(data) != byte_count:
            raise ProductionBlenderExportError("Blender output changed while being re-read")
        try:
            inspection = inspect_glb(data)
        except GlbError as exc:
            raise ProductionBlenderExportError(
                "Blender durable output failed independent GLB inspection"
            ) from exc
        if inspection != operation.inspection:
            raise ProductionBlenderExportError(
                "Blender durable output inspection drifted from adapter result"
            )
        return output, inspection.to_dict()

    def execute(self, task_id: str, request: BlenderJobRequest) -> BlenderExportServiceResult:
        if not isinstance(task_id, str) or not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(request, BlenderJobRequest):
            raise TypeError("request must be a BlenderJobRequest")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"Blender export requires RUNNING Task; task {task_id} is {task['status']}"
            )

        run_id = self.runtime.start_run(task_id, role=self.RUN_ROLE)
        request_artifact_id: str | None = None
        result_artifact_id: str | None = None
        output_artifact_id: str | None = None
        try:
            evidence_root = self._evidence_root(run_id)
            request_path = self._write_json_once(
                evidence_root,
                "request.json",
                request.to_dict(),
            )
            request_artifact_id = self.lineage.create_artifact(
                artifact_type="BLENDER_JOB_REQUEST",
                path_or_uri=str(request_path),
                created_by_run_id=run_id,
                tool_versions=(
                    f"blender:{self.profile.expected_blender_version}",
                    f"blender-runtime:{self.profile.runtime_hash}",
                    f"blender-runner:{self.profile.runner_fingerprint}",
                    "origin-forge-blender-export-service:1",
                ),
                status="CAPTURED",
            )

            operation = self.adapter.execute(request)
            if not isinstance(operation, BlenderExecution):
                raise ProductionBlenderExportError(
                    "Blender adapter returned an invalid result type"
                )
            if operation.request != request:
                raise ProductionBlenderExportError(
                    "Blender adapter returned a result for another request"
                )
            tool_versions = self._tool_versions(operation)

            result_path = self._write_json_once(
                evidence_root,
                "result.json",
                operation.to_dict(),
            )
            result_artifact_id = self.lineage.create_artifact(
                artifact_type="BLENDER_EXECUTION_RESULT",
                path_or_uri=str(result_path),
                parent_artifact_id=request_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )

            output_path, inspection = self._reinspect_output(request, operation)
            output_artifact_id = self.lineage.create_artifact(
                artifact_type="BLENDER_GLB_EXPORT",
                path_or_uri=str(output_path),
                parent_artifact_id=result_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="PRODUCED",
            )
            output_artifact = self.lineage.get_artifact(output_artifact_id)
            if output_artifact["content_hash"] != operation.inspection.content_hash:
                raise ProductionBlenderExportError(
                    "persisted Blender output Artifact hash drifted from inspected result"
                )

            output_verification_id = self.lineage.record_artifact_verification(
                output_artifact_id,
                verification_type="blender-glb-export-integrity",
                verifier=self.VERIFIER,
                status="PASS",
                evidence={
                    "request_hash": request.content_hash,
                    "request_artifact_id": request_artifact_id,
                    "result_artifact_id": result_artifact_id,
                    "operation_id": request.operation_id,
                    "workspace_id": request.workspace_id,
                    "project_hash": request.project.content_hash,
                    "output_relative_path": request.output_relative_path,
                    "output_hash": operation.inspection.content_hash,
                    "output_byte_count": operation.inspection.byte_count,
                    "blender_version": operation.blender_version,
                    "runtime_hash": operation.runtime_hash,
                    "runner_fingerprint": operation.runner_fingerprint,
                    "glb_inspection": inspection,
                    "semantic_geometry_verified": False,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            run_verification_id = self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="blender-export-glb",
                verifier=self.VERIFIER,
                status="PASS",
                evidence={
                    "request_hash": request.content_hash,
                    "request_artifact_id": request_artifact_id,
                    "result_artifact_id": result_artifact_id,
                    "output_artifact_id": output_artifact_id,
                    "output_verification_id": output_verification_id,
                    "operation_id": request.operation_id,
                    "workspace_id": request.workspace_id,
                    "project_hash": request.project.content_hash,
                    "output_relative_path": request.output_relative_path,
                    "output_hash": operation.inspection.content_hash,
                    "output_byte_count": operation.inspection.byte_count,
                    "blender_version": operation.blender_version,
                    "runtime_hash": operation.runtime_hash,
                    "runner_fingerprint": operation.runner_fingerprint,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                    "provenance_signed": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return BlenderExportServiceResult(
                run_id=run_id,
                request_artifact_id=request_artifact_id,
                result_artifact_id=result_artifact_id,
                output_artifact_id=output_artifact_id,
                output_verification_id=output_verification_id,
                run_verification_id=run_verification_id,
                operation=operation,
            )
        except Exception as exc:
            try:
                run = self.runtime.get_run(run_id)
                if run["status"] == RunStatus.RUNNING.value:
                    try:
                        self.runtime.record_verification(
                            "RUN",
                            run_id,
                            verification_type="blender-export-glb",
                            verifier=self.VERIFIER,
                            status="FAIL",
                            evidence={
                                "request_hash": request.content_hash,
                                "request_artifact_id": request_artifact_id,
                                "result_artifact_id": result_artifact_id,
                                "output_artifact_id": output_artifact_id,
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:2048],
                                "production_task_verified": False,
                                "canonical_asset_adopted": False,
                                "provenance_signed": False,
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
            raise
