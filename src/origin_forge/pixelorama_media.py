from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .path_policy import portable_relative_path
from .pixelorama_bridge import (
    PixeloramaBridgeAdapter,
    PixeloramaBridgeError,
    PixeloramaBridgeProfile,
    PixeloramaOperationResult,
)
from .pixelorama_models import (
    BridgeOutput,
    BridgeOutputType,
    PixeloramaBridgeRequest,
)
from .pixelorama_validation import validate_frame_png
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import RunStatus, TaskStatus


class PixeloramaMediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class PixeloramaOutputEvidence:
    relative_path: str
    artifact_id: str
    verification_id: str
    content_hash: str
    output_type: BridgeOutputType

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "artifact_id": self.artifact_id,
            "verification_id": self.verification_id,
            "content_hash": self.content_hash,
            "output_type": self.output_type.value,
        }


@dataclass(frozen=True)
class PixeloramaMediaResult:
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    output_evidence: tuple[PixeloramaOutputEvidence, ...]
    operation: PixeloramaOperationResult

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "outputs": [value.to_dict() for value in self.output_evidence],
            "operation": self.operation.to_dict(),
            "task_status_changed": False,
            "canonical_asset_adopted": False,
        }


class PixeloramaMediaService:
    """Run one isolated Pixelorama operation and persist evidence, never Task success."""

    RUN_ROLE = "PIXELORAMA"

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: PixeloramaBridgeProfile,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, PixeloramaBridgeProfile):
            raise TypeError("profile must be a PixeloramaBridgeProfile")
        self.runtime = runtime
        self.profile = profile
        self.adapter = PixeloramaBridgeAdapter(runtime, profile)
        self.lineage = OriginForgeLineage(runtime)

    @staticmethod
    def _tool_versions(operation: PixeloramaOperationResult) -> tuple[str, ...]:
        result = operation.bridge_result
        return (
            f"pixelorama:{result.pixelorama_version}",
            f"origin-forge-pixelorama-bridge:{result.bridge_version}:{result.bridge_fingerprint}",
        )

    def _artifact(
        self,
        *,
        artifact_type: str,
        path: Path,
        run_id: str,
        parent_artifact_id: str | None,
        tool_versions: tuple[str, ...],
        status: str,
    ) -> str:
        return self.lineage.create_artifact(
            artifact_type=artifact_type,
            path_or_uri=str(path),
            parent_artifact_id=parent_artifact_id,
            created_by_run_id=run_id,
            tool_versions=tool_versions,
            status=status,
        )

    def _validate_output(
        self,
        request: PixeloramaBridgeRequest,
        operation: PixeloramaOperationResult,
        output: BridgeOutput,
        artifact_id: str,
        run_id: str,
    ) -> str:
        evidence: dict[str, object] = {
            "operation_id": request.operation_id,
            "request_hash": request.content_hash,
            "bridge_result_hash": operation.bridge_result.content_hash,
            "output_type": output.output_type.value,
            "relative_path": output.relative_path,
            "content_hash": output.content_hash,
            "byte_count": output.byte_count,
            "bridge_version": operation.bridge_result.bridge_version,
            "bridge_fingerprint": operation.bridge_result.bridge_fingerprint,
            "pixelorama_version": operation.bridge_result.pixelorama_version,
            "semantic_visual_quality_verified": False,
        }
        verification_status = "PASS"
        if output.output_type == BridgeOutputType.PNG:
            if request.sprite_spec is None:
                raise PixeloramaMediaError(
                    "PNG structural validation requires a frozen sprite specification"
                )
            data = (operation.workspace_path / output.relative_path).read_bytes()
            validation = validate_frame_png(data, request.sprite_spec)
            evidence["raster_validation"] = validation.to_dict()
            if not validation.passed:
                verification_status = "FAIL"
        elif output.output_type == BridgeOutputType.SPRITESHEET:
            # V0 does not guess sheet layout without an explicit columns contract.
            evidence["raster_validation"] = {
                "passed": True,
                "geometry_verified": False,
                "reason": "spritesheet layout requires an explicit columns contract",
            }
        else:
            evidence["raster_validation"] = None
        verification_id = self.lineage.record_artifact_verification(
            artifact_id,
            verification_type="pixelorama-output-integrity",
            verifier="OriginForge.PixeloramaMediaService",
            status=verification_status,
            evidence=evidence,
            run_id=run_id,
        )
        if verification_status != "PASS":
            raise PixeloramaMediaError(
                f"Pixelorama output failed deterministic validation: {output.relative_path}"
            )
        return verification_id

    def execute(
        self,
        task_id: str,
        request: PixeloramaBridgeRequest,
        *,
        staged_inputs: dict[str, Path] | None = None,
    ) -> PixeloramaMediaResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(request, PixeloramaBridgeRequest):
            raise TypeError("request must be a PixeloramaBridgeRequest")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"Pixelorama media operation requires RUNNING Task; task {task_id} is {task['status']}"
            )
        run_id = self.runtime.start_run(task_id, role=self.RUN_ROLE)
        try:
            operation = self.adapter.execute(
                request,
                staged_inputs=staged_inputs or {},
            )
            if not operation.succeeded:
                raise PixeloramaMediaError(
                    f"Pixelorama bridge operation did not succeed: {operation.bridge_result.status.value}"
                )
            tool_versions = self._tool_versions(operation)
            request_artifact_id = self._artifact(
                artifact_type="PIXELORAMA_BRIDGE_REQUEST",
                path=operation.workspace_path / "request.json",
                run_id=run_id,
                parent_artifact_id=None,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            result_artifact_id = self._artifact(
                artifact_type="PIXELORAMA_BRIDGE_RESULT",
                path=operation.workspace_path / "result.json",
                run_id=run_id,
                parent_artifact_id=request_artifact_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            outputs: list[PixeloramaOutputEvidence] = []
            for output in operation.bridge_result.outputs:
                artifact_type = {
                    BridgeOutputType.PIXELORAMA_PROJECT: "PIXELORAMA_PROJECT",
                    BridgeOutputType.PNG: "RASTER_EXPORT_PNG",
                    BridgeOutputType.SPRITESHEET: "SPRITESHEET_EXPORT",
                }[output.output_type]
                artifact_id = self._artifact(
                    artifact_type=artifact_type,
                    path=operation.workspace_path / output.relative_path,
                    run_id=run_id,
                    parent_artifact_id=result_artifact_id,
                    tool_versions=tool_versions,
                    status="PRODUCED",
                )
                verification_id = self._validate_output(
                    request,
                    operation,
                    output,
                    artifact_id,
                    run_id,
                )
                outputs.append(
                    PixeloramaOutputEvidence(
                        relative_path=output.relative_path,
                        artifact_id=artifact_id,
                        verification_id=verification_id,
                        content_hash=output.content_hash,
                        output_type=output.output_type,
                    )
                )
            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="pixelorama-operation",
                verifier="OriginForge.PixeloramaMediaService",
                status="PASS",
                evidence={
                    "operation_id": request.operation_id,
                    "request_hash": request.content_hash,
                    "bridge_result_hash": operation.bridge_result.content_hash,
                    "output_artifact_ids": [value.artifact_id for value in outputs],
                    "bridge_version": operation.bridge_result.bridge_version,
                    "bridge_fingerprint": operation.bridge_result.bridge_fingerprint,
                    "pixelorama_version": operation.bridge_result.pixelorama_version,
                    "production_task_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return PixeloramaMediaResult(
                run_id=run_id,
                request_artifact_id=request_artifact_id,
                result_artifact_id=result_artifact_id,
                output_evidence=tuple(outputs),
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
                            verification_type="pixelorama-operation",
                            verifier="OriginForge.PixeloramaMediaService",
                            status="FAIL",
                            evidence={
                                "operation_id": request.operation_id,
                                "request_hash": request.content_hash,
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:2048],
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
            raise


@dataclass(frozen=True)
class PixeloramaAdoptionResult:
    source_artifact_id: str
    adopted_artifact_id: str
    verification_id: str
    destination_path: str
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_artifact_id": self.source_artifact_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "verification_id": self.verification_id,
            "destination_path": self.destination_path,
            "content_hash": self.content_hash,
            "existing_asset_overwritten": False,
            "task_status_changed": False,
        }


class PixeloramaOutputAdopter:
    """Explicitly publish one verified media output as a new project file only."""

    ALLOWED_SOURCE_TYPES = {"RASTER_EXPORT_PNG", "SPRITESHEET_EXPORT", "PIXELORAMA_PROJECT"}

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.lineage = OriginForgeLineage(runtime)

    def _artifact_row(self, artifact_id: str) -> dict[str, object]:
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
                (artifact_id, self.runtime.project_id()),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return dict(row)

    def _verified_source(self, artifact_id: str) -> tuple[dict[str, object], Path, str]:
        artifact = self._artifact_row(artifact_id)
        if artifact["type"] not in self.ALLOWED_SOURCE_TYPES:
            raise PixeloramaMediaError("source Artifact is not an adoptable Pixelorama output")
        with self.runtime.store.session() as conn:
            rows = list(
                conn.execute(
                    """SELECT * FROM verifications
                       WHERE target_type = 'ARTIFACT' AND target_id = ?
                         AND verification_type = 'pixelorama-output-integrity'
                         AND verifier = 'OriginForge.PixeloramaMediaService'
                         AND status = 'PASS'
                       ORDER BY created_at, id""",
                    (artifact_id,),
                )
            )
        if not rows:
            raise PixeloramaMediaError(
                "source Artifact lacks PASS pixelorama-output-integrity evidence"
            )
        raw = artifact.get("path_or_uri")
        if not isinstance(raw, str) or not raw or "://" in raw:
            raise PixeloramaMediaError("source Artifact file is missing or unsafe")
        source = Path(raw)
        if not source.is_absolute():
            source = self.runtime.project_root / source
        if source.is_symlink() or not source.is_file():
            raise PixeloramaMediaError("source Artifact file is missing or unsafe")
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(self.runtime.state_dir.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise PixeloramaMediaError(
                "adoption source must be an isolated Origin Forge media output"
            ) from exc
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        current_hash = "sha256:" + digest
        if current_hash != artifact["content_hash"]:
            raise PixeloramaMediaError("source Artifact bytes drifted after verification")
        return artifact, resolved, current_hash

    def adopt_new(
        self,
        source_artifact_id: str,
        destination_relative_path: str,
    ) -> PixeloramaAdoptionResult:
        if not validate_id(source_artifact_id, IdKind.ARTIFACT):
            raise ValueError("source_artifact_id must be an ART ID")
        artifact, source, content_hash = self._verified_source(source_artifact_id)
        try:
            relative = portable_relative_path(destination_relative_path)
        except ValueError as exc:
            raise PixeloramaMediaError("invalid adoption destination path") from exc
        destination = self.runtime.project_root / relative
        if destination.is_symlink() or destination.exists():
            raise PixeloramaMediaError(
                "v0 Pixelorama adoption is create-only and refuses existing destinations"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        project_root = self.runtime.project_root.resolve()
        current = project_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise PixeloramaMediaError("adoption destination contains a symlink")
        try:
            destination.parent.resolve().relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PixeloramaMediaError("adoption destination escapes project root") from exc

        temp = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            with source.open("rb") as src, temp.open("xb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            try:
                os.link(temp, destination)
            except FileExistsError as exc:
                raise PixeloramaMediaError(
                    "adoption destination appeared concurrently; refusing overwrite"
                ) from exc
        finally:
            temp.unlink(missing_ok=True)

        adopted_artifact_id = self.lineage.create_artifact(
            artifact_type=str(artifact["type"]),
            path_or_uri=str(destination),
            parent_artifact_id=source_artifact_id,
            created_by_run_id=(
                str(artifact["created_by_run_id"])
                if artifact["created_by_run_id"] is not None
                else None
            ),
            tool_versions=tuple(__import__("json").loads(str(artifact["tool_versions_json"]))),
            status="ADOPTED",
        )
        verification_id = self.lineage.record_artifact_verification(
            adopted_artifact_id,
            verification_type="pixelorama-adoption-integrity",
            verifier="OriginForge.PixeloramaOutputAdopter",
            status="PASS",
            evidence={
                "source_artifact_id": source_artifact_id,
                "source_content_hash": content_hash,
                "destination_path": relative.as_posix(),
                "destination_content_hash": content_hash,
                "existing_asset_overwritten": False,
                "production_task_verified": False,
            },
            run_id=(
                str(artifact["created_by_run_id"])
                if artifact["created_by_run_id"] is not None
                else None
            ),
        )
        return PixeloramaAdoptionResult(
            source_artifact_id=source_artifact_id,
            adopted_artifact_id=adopted_artifact_id,
            verification_id=verification_id,
            destination_path=relative.as_posix(),
            content_hash=content_hash,
        )