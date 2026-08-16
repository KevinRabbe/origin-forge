from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .pixelorama_cli_export import (
    PixeloramaCliExportAdapter,
    PixeloramaCliExportRequest,
    PixeloramaCliExportResult,
    PixeloramaCliProfile,
)
from .pixelorama_png import PngError, inspect_rgba8_png
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import RunStatus, TaskStatus


_MAX_REINSPECTION_BYTES = 128 * 1024 * 1024


class ProductionPixeloramaExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class PixeloramaCliExportServiceResult:
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    output_artifact_id: str
    output_verification_id: str
    run_verification_id: str
    operation: PixeloramaCliExportResult

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


class PixeloramaCliExportService:
    """Persist one proven direct-CLI spritesheet export without Task outcome authority."""

    RUN_ROLE = "PIXELORAMA"
    VERIFIER = "OriginForge.PixeloramaCliExportService"

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: PixeloramaCliProfile,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, PixeloramaCliProfile):
            raise TypeError("profile must be a PixeloramaCliProfile")
        self.runtime = runtime
        self.profile = profile
        self.adapter = PixeloramaCliExportAdapter(runtime, profile)
        self.lineage = OriginForgeLineage(runtime)

    @staticmethod
    def _canonical_json_bytes(value: dict[str, object]) -> bytes:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def _evidence_root(self, run_id: str) -> Path:
        state = self.runtime.state_dir
        if state.is_symlink():
            raise ProductionPixeloramaExportError(
                "protected project state may not be a symlink"
            )
        root = state / "pixelorama-production-export-evidence"
        if root.is_symlink():
            raise ProductionPixeloramaExportError(
                "Pixelorama production evidence root may not be a symlink"
            )
        root.mkdir(parents=True, exist_ok=True)
        try:
            state_resolved = state.resolve(strict=True)
            root_resolved = root.resolve(strict=True)
            root_resolved.relative_to(state_resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionPixeloramaExportError(
                "Pixelorama production evidence root escaped protected state"
            ) from exc
        run_root = root / run_id
        if run_root.exists() or run_root.is_symlink():
            raise ProductionPixeloramaExportError(
                "Pixelorama production Run evidence path already exists"
            )
        run_root.mkdir()
        return run_root

    @classmethod
    def _write_json_once(
        cls,
        root: Path,
        filename: str,
        value: dict[str, object],
    ) -> Path:
        path = root / filename
        if path.exists() or path.is_symlink():
            raise ProductionPixeloramaExportError(
                f"Pixelorama production evidence already exists: {filename}"
            )
        payload = cls._canonical_json_bytes(value)
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def _tool_versions(self, pixelorama_version: str) -> tuple[str, ...]:
        if pixelorama_version != self.profile.expected_pixelorama_version:
            raise ProductionPixeloramaExportError(
                "Pixelorama result version does not match trusted production profile"
            )
        return (
            f"pixelorama:{pixelorama_version}",
            f"pixelorama-executable:{self.profile.pixelorama_fingerprint}",
            "origin-forge-pixelorama-cli-export-service:1",
        )

    def _output_path(
        self,
        request: PixeloramaCliExportRequest,
        operation: PixeloramaCliExportResult,
    ) -> Path:
        if operation.request != request:
            raise ProductionPixeloramaExportError(
                "Pixelorama CLI result does not bind the exact request"
            )
        workspace = Path(operation.workspace_path)
        if workspace.is_symlink():
            raise ProductionPixeloramaExportError(
                "Pixelorama result workspace may not be a symlink"
            )
        expected_workspace = (
            self.runtime.state_dir / "media-workspaces" / request.workspace_id
        )
        try:
            workspace_resolved = workspace.resolve(strict=True)
            expected_resolved = expected_workspace.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProductionPixeloramaExportError(
                "Pixelorama result workspace is unavailable"
            ) from exc
        if workspace_resolved != expected_resolved or not workspace_resolved.is_dir():
            raise ProductionPixeloramaExportError(
                "Pixelorama result workspace is not the exact infrastructure-owned workspace"
            )

        current = workspace
        for part in Path(request.output_relative_path).parts:
            current = current / part
            if current.is_symlink():
                raise ProductionPixeloramaExportError(
                    "Pixelorama output path contains a symlink component"
                )
        try:
            output = current.resolve(strict=True)
            output.relative_to(workspace_resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionPixeloramaExportError(
                "Pixelorama output escaped its media workspace"
            ) from exc
        if not output.is_file():
            raise ProductionPixeloramaExportError(
                "Pixelorama declared output is not a regular file"
            )
        return output

    def _reinspect_output(
        self,
        request: PixeloramaCliExportRequest,
        operation: PixeloramaCliExportResult,
    ) -> tuple[Path, dict[str, object]]:
        if operation.process_exit_code != 0:
            raise ProductionPixeloramaExportError(
                "Pixelorama CLI service received a non-success process result"
            )
        output = self._output_path(request, operation)
        byte_count = output.stat().st_size
        if (
            byte_count <= 0
            or byte_count > request.max_output_bytes
            or byte_count > _MAX_REINSPECTION_BYTES
        ):
            raise ProductionPixeloramaExportError(
                "Pixelorama output byte count exceeds the proven raster inspection boundary"
            )
        digest = hashlib.sha256()
        with output.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        output_hash = "sha256:" + digest.hexdigest()
        if (
            output_hash != operation.output_hash
            or byte_count != operation.output_byte_count
        ):
            raise ProductionPixeloramaExportError(
                "Pixelorama output bytes do not match the typed CLI result"
            )
        try:
            inspection = inspect_rgba8_png(output.read_bytes())
        except (OSError, PngError) as exc:
            raise ProductionPixeloramaExportError(
                "Pixelorama output failed independent RGBA8 PNG inspection"
            ) from exc
        if (
            inspection.width != operation.width
            or inspection.height != operation.height
            or inspection.byte_count != byte_count
        ):
            raise ProductionPixeloramaExportError(
                "Pixelorama output geometry does not match the typed CLI result"
            )
        return output, inspection.to_dict()

    def execute(
        self,
        task_id: str,
        request: PixeloramaCliExportRequest,
        *,
        source_path: Path,
    ) -> PixeloramaCliExportServiceResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(request, PixeloramaCliExportRequest):
            raise TypeError("request must be a PixeloramaCliExportRequest")
        source = Path(source_path)
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"Pixelorama CLI export requires RUNNING Task; task {task_id} is {task['status']}"
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
                artifact_type="PIXELORAMA_CLI_EXPORT_REQUEST",
                path_or_uri=str(request_path),
                created_by_run_id=run_id,
                tool_versions=(
                    f"pixelorama:{self.profile.expected_pixelorama_version}",
                    f"pixelorama-executable:{self.profile.pixelorama_fingerprint}",
                    "origin-forge-pixelorama-cli-export-service:1",
                ),
                status="CAPTURED",
            )

            operation = self.adapter.execute(request, source_path=source)
            if not isinstance(operation, PixeloramaCliExportResult):
                raise ProductionPixeloramaExportError(
                    "Pixelorama CLI adapter returned an invalid result type"
                )
            if operation.request != request:
                raise ProductionPixeloramaExportError(
                    "Pixelorama CLI adapter returned a result for another request"
                )
            tool_versions = self._tool_versions(operation.pixelorama_version)

            result_path = self._write_json_once(
                evidence_root,
                "result.json",
                operation.to_dict(),
            )
            result_artifact_id = self.lineage.create_artifact(
                artifact_type="PIXELORAMA_CLI_EXPORT_RESULT",
                path_or_uri=str(result_path),
                parent_artifact_id=request_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )

            output_path, inspection = self._reinspect_output(request, operation)
            output_artifact_id = self.lineage.create_artifact(
                artifact_type="SPRITESHEET_EXPORT",
                path_or_uri=str(output_path),
                parent_artifact_id=result_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="PRODUCED",
            )
            output_artifact = self.lineage.get_artifact(output_artifact_id)
            if output_artifact["content_hash"] != operation.output_hash:
                raise ProductionPixeloramaExportError(
                    "persisted Pixelorama output Artifact hash drifted from typed result"
                )

            output_verification_id = self.lineage.record_artifact_verification(
                output_artifact_id,
                verification_type="pixelorama-cli-export-integrity",
                verifier=self.VERIFIER,
                status="PASS",
                evidence={
                    "source_hash": request.source_hash,
                    "source_byte_count": request.source_byte_count,
                    "request_hash": request.content_hash,
                    "request_artifact_id": request_artifact_id,
                    "result_artifact_id": result_artifact_id,
                    "operation_id": request.operation_id,
                    "workspace_id": request.workspace_id,
                    "output_relative_path": request.output_relative_path,
                    "output_hash": operation.output_hash,
                    "output_byte_count": operation.output_byte_count,
                    "pixelorama_version": operation.pixelorama_version,
                    "pixelorama_executable_fingerprint": self.profile.pixelorama_fingerprint,
                    "png_inspection": inspection,
                    "semantic_visual_quality_verified": False,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            run_verification_id = self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="pixelorama-cli-export",
                verifier=self.VERIFIER,
                status="PASS",
                evidence={
                    "source_hash": request.source_hash,
                    "source_byte_count": request.source_byte_count,
                    "request_hash": request.content_hash,
                    "request_artifact_id": request_artifact_id,
                    "result_artifact_id": result_artifact_id,
                    "output_artifact_id": output_artifact_id,
                    "output_verification_id": output_verification_id,
                    "output_hash": operation.output_hash,
                    "output_byte_count": operation.output_byte_count,
                    "width": operation.width,
                    "height": operation.height,
                    "pixelorama_version": operation.pixelorama_version,
                    "pixelorama_executable_fingerprint": self.profile.pixelorama_fingerprint,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                    "provenance_signed": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return PixeloramaCliExportServiceResult(
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
                            verification_type="pixelorama-cli-export",
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
