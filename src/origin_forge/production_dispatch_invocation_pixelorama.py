from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .pixelorama_cli_export import PixeloramaCliExportRequest
from .production_dispatch_binding_models import DispatchBinding
from .production_dispatch_binding_pixelorama import (
    PIXELORAMA_BINDER_ID,
    PIXELORAMA_REQUEST_TYPE_ID,
    PixeloramaSpritesheetExportInputBinder,
)
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_execution_assembly import PixeloramaSpritesheetExportExecutionPayload
from .production_pixelorama_export import (
    PixeloramaCliExportService,
    PixeloramaCliExportServiceResult,
)
from .production_work_order_models import content_hash
from .production_work_order_pixelorama import (
    PIXELORAMA_ADAPTER_ID,
    PIXELORAMA_CONTRACT_ID,
    PIXELORAMA_EXPORT_PATH,
    PIXELORAMA_OPERATION,
    PIXELORAMA_SOURCE_ARTIFACT_TYPE,
    PIXELORAMA_STAGED_SOURCE_PATH,
)
from .runtime import OriginForgeRuntime
from .state import RunStatus, TaskStatus


_PIXELORAMA_OWNER_ID = "originforge.execution.pixelorama.spritesheet-export@1"
_PIXELORAMA_RETURNED_DETAIL = "trusted Pixelorama spritesheet-export execution owner returned normally"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_OUTPUT_BYTES = 128 * 1024 * 1024
_PIXELORAMA_REQUEST_FIELDS = {
    "task_id",
    "source_artifact_id",
    "source_artifact_hash",
    "source_artifact_type",
    "source_artifact_status",
    "source_path_or_uri",
    "operation",
    "staged_source_relative_path",
    "output_relative_path",
}


@dataclass(frozen=True)
class PixeloramaInvocationRequest:
    """Strict inert view of the frozen Phase-34 Pixelorama projection."""

    task_id: str
    source_artifact_id: str
    source_artifact_hash: str
    source_artifact_type: str
    source_artifact_status: str
    source_path_or_uri: str
    operation: str
    staged_source_relative_path: str
    output_relative_path: str
    request_content_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.task_id, IdKind.TASK):
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation task_id must be a valid TASK ID"
            )
        if not validate_id(self.source_artifact_id, IdKind.ARTIFACT):
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation source_artifact_id must be an ARTIFACT ID"
            )
        if (
            not isinstance(self.source_artifact_hash, str)
            or len(self.source_artifact_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in self.source_artifact_hash)
        ):
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation source Artifact hash is invalid"
            )
        if self.source_artifact_type != PIXELORAMA_SOURCE_ARTIFACT_TYPE:
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation source Artifact type drifted"
            )
        if self.source_artifact_status != "PRODUCED":
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation source Artifact status drifted"
            )
        if (
            not isinstance(self.source_path_or_uri, str)
            or not self.source_path_or_uri
            or len(self.source_path_or_uri) > 4096
        ):
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation source path metadata is invalid"
            )
        if self.operation != PIXELORAMA_OPERATION:
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation operation drifted"
            )
        if self.staged_source_relative_path != PIXELORAMA_STAGED_SOURCE_PATH:
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation staged source path drifted"
            )
        if self.output_relative_path != PIXELORAMA_EXPORT_PATH:
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation output path drifted"
            )
        if (
            not isinstance(self.request_content_hash, str)
            or len(self.request_content_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in self.request_content_hash)
        ):
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation request content hash is invalid"
            )
        if content_hash(self.projection_dict()) != self.request_content_hash:
            raise ProductionDispatchInvocationError(
                "Pixelorama invocation request content hash does not recompute"
            )

    def projection_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_hash": self.source_artifact_hash,
            "source_artifact_type": self.source_artifact_type,
            "source_artifact_status": self.source_artifact_status,
            "source_path_or_uri": self.source_path_or_uri,
            "operation": self.operation,
            "staged_source_relative_path": self.staged_source_relative_path,
            "output_relative_path": self.output_relative_path,
        }


def _decode_pixelorama_request_projection(binding: DispatchBinding) -> PixeloramaInvocationRequest:
    projection = binding.request_projection
    if not isinstance(projection, dict) or set(projection) != _PIXELORAMA_REQUEST_FIELDS:
        raise ProductionDispatchInvocationError(
            "Pixelorama request projection schema drifted"
        )
    request = PixeloramaInvocationRequest(
        task_id=projection["task_id"],
        source_artifact_id=projection["source_artifact_id"],
        source_artifact_hash=projection["source_artifact_hash"],
        source_artifact_type=projection["source_artifact_type"],
        source_artifact_status=projection["source_artifact_status"],
        source_path_or_uri=projection["source_path_or_uri"],
        operation=projection["operation"],
        staged_source_relative_path=projection["staged_source_relative_path"],
        output_relative_path=projection["output_relative_path"],
        request_content_hash=binding.request_content_hash,
    )
    if request.projection_dict() != projection:
        raise ProductionDispatchInvocationError(
            "Pixelorama request projection is not canonical"
        )
    return request


def _require_trusted_pixelorama_relation(binding: DispatchBinding) -> None:
    import origin_forge.production_dispatch_invocation as legacy

    legacy._require_trusted_relation(
        binding,
        descriptor=PixeloramaSpritesheetExportInputBinder().descriptor,
        expected_owner_id=_PIXELORAMA_OWNER_ID,
        expected_adapter_id=PIXELORAMA_ADAPTER_ID,
        expected_contract_id=PIXELORAMA_CONTRACT_ID,
        expected_binder_id=PIXELORAMA_BINDER_ID,
        expected_request_type_id=PIXELORAMA_REQUEST_TYPE_ID,
    )


def _safe_source_path(
    runtime: OriginForgeRuntime,
    request: PixeloramaInvocationRequest,
) -> tuple[Path, int]:
    lineage = OriginForgeLineage(runtime)
    try:
        artifact = lineage.get_artifact(request.source_artifact_id)
    except KeyError as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact is no longer project-owned"
        ) from exc
    if (
        artifact["type"] != request.source_artifact_type
        or artifact["status"] != request.source_artifact_status
        or artifact["content_hash"] != request.source_artifact_hash
        or artifact["path_or_uri"] != request.source_path_or_uri
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact metadata drifted after STARTED"
        )

    raw = request.source_path_or_uri
    if "://" in raw or "\x00" in raw:
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact must be a local project file"
        )
    relative = Path(raw)
    if relative.is_absolute() or relative.suffix.lower() != ".pxo":
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact must be a relative .pxo project file"
        )
    root = runtime.project_root.resolve()
    current = runtime.project_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ProductionDispatchInvocationError(
                "Pixelorama source Artifact path contains a symlink"
            )
    try:
        source = current.resolve(strict=True)
        source.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact escaped or is unavailable"
        ) from exc
    if not source.is_file():
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact is not a regular file"
        )

    size = source.stat().st_size
    if size <= 0 or size > _MAX_SOURCE_BYTES:
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact byte count is outside the reviewed bound"
        )
    digest = hashlib.sha256()
    total = 0
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_SOURCE_BYTES:
                raise ProductionDispatchInvocationError(
                    "Pixelorama source Artifact exceeds the reviewed byte bound"
                )
            digest.update(chunk)
    if total != size or digest.hexdigest() != request.source_artifact_hash:
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact bytes drifted after STARTED"
        )
    return source, size


def _canonical_service_json(value: dict[str, object]) -> bytes:
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


def _artifact_json(
    lineage: OriginForgeLineage,
    artifact_id: str,
    label: str,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        artifact = lineage.get_artifact(artifact_id)
        path = lineage.local_artifact_path(artifact_id)
        data = path.read_bytes()
        payload = json.loads(data.decode("utf-8"))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise ProductionDispatchInvocationError(
            f"Pixelorama {label} Artifact cannot be revalidated"
        ) from exc
    if not isinstance(payload, dict) or _canonical_service_json(payload) != data:
        raise ProductionDispatchInvocationError(
            f"Pixelorama {label} Artifact is not exact canonical service evidence"
        )
    return artifact, payload


def _require_pixelorama_result_durable(
    runtime: OriginForgeRuntime,
    frozen_request: PixeloramaInvocationRequest,
    concrete_request: PixeloramaCliExportRequest,
    result: PixeloramaCliExportServiceResult,
    profile_payload: PixeloramaSpritesheetExportExecutionPayload,
) -> None:
    if not isinstance(result, PixeloramaCliExportServiceResult):
        raise ProductionDispatchInvocationError(
            "Pixelorama owner returned an invalid result type"
        )
    operation = result.operation
    if operation.request != concrete_request:
        raise ProductionDispatchInvocationError(
            "Pixelorama owner result does not bind the allocated request"
        )
    if (
        concrete_request.source_hash != "sha256:" + frozen_request.source_artifact_hash
        or concrete_request.source_relative_path != frozen_request.staged_source_relative_path
        or concrete_request.output_relative_path != frozen_request.output_relative_path
        or operation.pixelorama_version != profile_payload.profile.expected_pixelorama_version
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama owner result drifted from frozen source/profile authority"
        )
    try:
        run = runtime.get_run(result.run_id)
        task = runtime.get_task(frozen_request.task_id)
    except (KeyError, RuntimeError) as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama owner Run/Task relation cannot be read"
        ) from exc
    if (
        run["task_id"] != frozen_request.task_id
        or run["role"] != PixeloramaCliExportService.RUN_ROLE
        or run["status"] != RunStatus.SUCCEEDED.value
        or task["status"] != TaskStatus.RUNNING.value
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama owner result does not bind one SUCCEEDED PIXELORAMA Run to RUNNING Task"
        )

    lineage = OriginForgeLineage(runtime)
    request_artifact, request_payload = _artifact_json(
        lineage,
        result.request_artifact_id,
        "request",
    )
    result_artifact, result_payload = _artifact_json(
        lineage,
        result.result_artifact_id,
        "result",
    )
    try:
        output_artifact = lineage.get_artifact(result.output_artifact_id)
        output_path = lineage.local_artifact_path(result.output_artifact_id)
    except (KeyError, RuntimeError) as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama output Artifact cannot be revalidated"
        ) from exc

    request_location = (
        f".origin-forge/pixelorama-production-export-evidence/{result.run_id}/request.json"
    )
    result_location = (
        f".origin-forge/pixelorama-production-export-evidence/{result.run_id}/result.json"
    )
    output_location = (
        f".origin-forge/media-workspaces/{concrete_request.workspace_id}/"
        f"{concrete_request.output_relative_path}"
    )
    if (
        request_artifact["type"] != "PIXELORAMA_CLI_EXPORT_REQUEST"
        or request_artifact["created_by_run_id"] != result.run_id
        or request_artifact["parent_artifact_id"] is not None
        or request_artifact["status"] != "CAPTURED"
        or request_artifact["path_or_uri"] != request_location
        or request_payload != concrete_request.to_dict()
        or result_artifact["type"] != "PIXELORAMA_CLI_EXPORT_RESULT"
        or result_artifact["created_by_run_id"] != result.run_id
        or result_artifact["parent_artifact_id"] != result.request_artifact_id
        or result_artifact["status"] != "CAPTURED"
        or result_artifact["path_or_uri"] != result_location
        or result_payload != operation.to_dict()
        or output_artifact["type"] != "SPRITESHEET_EXPORT"
        or output_artifact["created_by_run_id"] != result.run_id
        or output_artifact["parent_artifact_id"] != result.result_artifact_id
        or output_artifact["status"] != "PRODUCED"
        or output_artifact["path_or_uri"] != output_location
        or output_artifact["content_hash"] != operation.output_hash
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama owner durable Artifact lineage is not exact"
        )
    if output_path.stat().st_size != operation.output_byte_count:
        raise ProductionDispatchInvocationError(
            "Pixelorama durable output byte count drifted"
        )

    output_verifications = lineage.list_artifact_verifications(result.output_artifact_id)
    matching_output = [
        value for value in output_verifications if value["id"] == result.output_verification_id
    ]
    if len(matching_output) != 1:
        raise ProductionDispatchInvocationError(
            "Pixelorama output Verification identity is missing or ambiguous"
        )
    output_verification = matching_output[0]
    try:
        output_evidence = json.loads(output_verification["evidence_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama output Verification evidence is invalid"
        ) from exc
    if (
        output_verification["verification_type"] != "pixelorama-cli-export-integrity"
        or output_verification["verifier"] != PixeloramaCliExportService.VERIFIER
        or output_verification["status"] != "PASS"
        or output_verification["run_id"] != result.run_id
        or output_evidence.get("source_hash") != concrete_request.source_hash
        or output_evidence.get("source_byte_count") != concrete_request.source_byte_count
        or output_evidence.get("request_hash") != concrete_request.content_hash
        or output_evidence.get("request_artifact_id") != result.request_artifact_id
        or output_evidence.get("result_artifact_id") != result.result_artifact_id
        or output_evidence.get("output_hash") != operation.output_hash
        or output_evidence.get("output_byte_count") != operation.output_byte_count
        or output_evidence.get("pixelorama_version") != operation.pixelorama_version
        or output_evidence.get("pixelorama_executable_fingerprint")
        != profile_payload.profile.pixelorama_fingerprint
        or output_evidence.get("production_task_verified") is not False
        or output_evidence.get("canonical_asset_adopted") is not False
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama output Verification does not bind exact durable evidence"
        )

    run_verifications = runtime.list_verifications("RUN", result.run_id)
    if len(run_verifications) != 1 or run_verifications[0]["id"] != result.run_verification_id:
        raise ProductionDispatchInvocationError(
            "Pixelorama owner requires exactly one canonical Run Verification"
        )
    run_verification = run_verifications[0]
    try:
        run_evidence = json.loads(run_verification["evidence_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama Run Verification evidence is invalid"
        ) from exc
    if (
        run_verification["verification_type"] != "pixelorama-cli-export"
        or run_verification["verifier"] != PixeloramaCliExportService.VERIFIER
        or run_verification["status"] != "PASS"
        or run_verification["run_id"] != result.run_id
        or run_evidence.get("source_hash") != concrete_request.source_hash
        or run_evidence.get("request_hash") != concrete_request.content_hash
        or run_evidence.get("request_artifact_id") != result.request_artifact_id
        or run_evidence.get("result_artifact_id") != result.result_artifact_id
        or run_evidence.get("output_artifact_id") != result.output_artifact_id
        or run_evidence.get("output_verification_id") != result.output_verification_id
        or run_evidence.get("output_hash") != operation.output_hash
        or run_evidence.get("output_byte_count") != operation.output_byte_count
        or run_evidence.get("pixelorama_version") != operation.pixelorama_version
        or run_evidence.get("pixelorama_executable_fingerprint")
        != profile_payload.profile.pixelorama_fingerprint
        or run_evidence.get("production_task_verified") is not False
        or run_evidence.get("canonical_asset_adopted") is not False
        or run_evidence.get("provenance_signed") is not False
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama Run Verification does not bind exact durable evidence"
        )


def _dispatch_claim_once_three_owner(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_claim_revision: int,
) -> CompletedDispatchInvocation:
    """Keep one public single-shot coordinator while adding the reviewed Pixelorama owner."""

    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    if binding.request_type_id != PIXELORAMA_REQUEST_TYPE_ID:
        return legacy._legacy_dispatch_claim_once(
            runtime,
            claim_id,
            expected_claim_revision,
        )

    _require_trusted_pixelorama_relation(binding)
    request = _decode_pixelorama_request_projection(binding)
    if (
        frozen_claim.status is not DispatchClaimStatus.ACTIVE
        or frozen_claim.revision != expected_claim_revision
        or frozen_claim.task_id != request.task_id
    ):
        raise ProductionDispatchInvocationError(
            "Pixelorama dispatch claim changed before execution ownership begin"
        )

    started = legacy.begin_dispatch_execution(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    execution = started.execution
    plan = started.dependencies.plan
    payload = started.dependencies.payload
    if (
        execution.status is not DispatchExecutionStatus.STARTED
        or execution.claim_id != frozen_claim.claim_id
        or execution.claim_revision_at_start != frozen_claim.revision
        or execution.task_id != request.task_id
        or execution.dispatch_binding_id != frozen_claim.dispatch_binding_id
        or execution.dispatch_binding_hash != frozen_claim.dispatch_binding_hash
        or execution.execution_owner_id != _PIXELORAMA_OWNER_ID
        or plan.claim_id != frozen_claim.claim_id
        or plan.claim_revision != frozen_claim.revision
        or plan.task_id != request.task_id
        or plan.dispatch_binding_id != frozen_claim.dispatch_binding_id
        or plan.dispatch_binding_hash != frozen_claim.dispatch_binding_hash
        or plan.request_type_id != PIXELORAMA_REQUEST_TYPE_ID
        or plan.request_content_hash != request.request_content_hash
        or plan.owner_id != _PIXELORAMA_OWNER_ID
        or not isinstance(payload, PixeloramaSpritesheetExportExecutionPayload)
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "STARTED_RELATION_MISMATCH",
        )

    try:
        source_path, source_byte_count = _safe_source_path(runtime, request)
        concrete_request = PixeloramaCliExportRequest.create(
            source_hash="sha256:" + request.source_artifact_hash,
            source_byte_count=source_byte_count,
            source_relative_path=request.staged_source_relative_path,
            output_relative_path=request.output_relative_path,
            timeout_seconds=min(60, payload.profile.timeout_seconds),
            max_output_bytes=_MAX_OUTPUT_BYTES,
        )
        pixelorama_result = PixeloramaCliExportService(
            runtime,
            payload.profile,
        ).execute(
            request.task_id,
            concrete_request,
            source_path=source_path,
        )
    except Exception as exc:
        exception_type = legacy._exception_type_commitment(exc)
        legacy._record_raised_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=(
                "trusted Pixelorama spritesheet-export execution owner raised "
                f"{exception_type}"
            ),
        )
        raise ProductionDispatchInvocationError(
            "trusted Pixelorama spritesheet-export execution owner raised "
            f"{exception_type}; dispatch execution {execution.execution_id} recorded RAISED"
        ) from exc

    try:
        _require_pixelorama_result_durable(
            runtime,
            request,
            concrete_request,
            pixelorama_result,
            payload,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "OWNER_RETURN_CONTRACT_MISMATCH",
        ) from exc

    returned = legacy._record_returned_or_recovery(
        runtime,
        started,
        frozen_claim,
        detail=_PIXELORAMA_RETURNED_DETAIL,
    )
    return CompletedDispatchInvocation(
        returned,
        pixelorama_result=pixelorama_result,
    )
