from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from .lineage import OriginForgeLineage
from .pixelorama_cli_export import (
    PixeloramaCliExportRequest,
    PixeloramaCliExportResult,
)
from .pixelorama_models import BridgeOperation
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import (
    DispatchExecutionCurrentnessStatus,
    inspect_dispatch_execution_currentness_readonly,
    read_dispatch_execution,
)
from .production_pixelorama_dispatch_output_binding_models import (
    PIXELORAMA_EXECUTION_OWNER_ID,
    PixeloramaDispatchOutputBinding,
)
from .production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from .production_pixelorama_export import (
    PixeloramaCliExportService,
    PixeloramaCliExportServiceResult,
)
from .runtime import OriginForgeRuntime
from .state import RunStatus, TaskStatus


_MAX_RECOVERED_STREAM_BYTES = 16 * 1024 * 1024


class PixeloramaDispatchOutputCurrentnessStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXECUTION_NOT_RETURNED = "EXECUTION_NOT_RETURNED"
    STALE_EXECUTION = "STALE_EXECUTION"
    TASK_NOT_RUNNING = "TASK_NOT_RUNNING"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"


@dataclass(frozen=True)
class PixeloramaDispatchOutputCurrentness:
    execution_id: str
    task_id: str | None
    output_artifact_id: str | None
    status: PixeloramaDispatchOutputCurrentnessStatus
    production_task_verified: bool
    detail: str | None = None

    @property
    def adoption_eligible(self) -> bool:
        return self.status is PixeloramaDispatchOutputCurrentnessStatus.ELIGIBLE

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "output_artifact_id": self.output_artifact_id,
            "status": self.status.value,
            "production_task_verified": self.production_task_verified,
            "adoption_eligible": self.adoption_eligible,
            "detail": self.detail,
        }


def _json_evidence(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise RuntimeError(f"{label} evidence_json is not text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} evidence_json is invalid") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{label} evidence_json is not an object")
    return decoded


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
        raise RuntimeError(f"bound Pixelorama {label} Artifact cannot be reread") from exc
    if (
        not isinstance(payload, dict)
        or PixeloramaCliExportService._canonical_json_bytes(payload) != data
        or artifact["content_hash"] != "sha256:" + hashlib.sha256(data).hexdigest()
    ):
        raise RuntimeError(f"bound Pixelorama {label} Artifact bytes drifted")
    return artifact, payload


def _prefixed_output_hash(binding: PixeloramaDispatchOutputBinding) -> str:
    return "sha256:" + binding.output_content_hash


def _bounded_stream_length(value: object, label: str) -> int:
    if (
        type(value) is not int
        or value < 0
        or value > _MAX_RECOVERED_STREAM_BYTES
    ):
        raise RuntimeError(f"bound Pixelorama {label} length is invalid")
    return value


def _materialize_result_payloads(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
    request_payload: dict[str, object],
    result_payload: dict[str, object],
) -> PixeloramaCliExportServiceResult:
    try:
        request = PixeloramaCliExportRequest(
            operation_id=request_payload["operation_id"],
            workspace_id=request_payload["workspace_id"],
            operation=BridgeOperation(request_payload["operation"]),
            source_relative_path=request_payload["source_relative_path"],
            source_hash=request_payload["source_hash"],
            source_byte_count=request_payload["source_byte_count"],
            output_relative_path=request_payload["output_relative_path"],
            timeout_seconds=request_payload["timeout_seconds"],
            max_output_bytes=request_payload["max_output_bytes"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("bound Pixelorama request payload is invalid") from exc
    if request.to_dict() != request_payload:
        raise RuntimeError("bound Pixelorama request payload is not canonical")

    stdout_bytes = _bounded_stream_length(result_payload.get("stdout_bytes"), "stdout")
    stderr_bytes = _bounded_stream_length(result_payload.get("stderr_bytes"), "stderr")
    try:
        operation = PixeloramaCliExportResult(
            request=request,
            workspace_path=(
                runtime.state_dir / "media-workspaces" / request.workspace_id
            ),
            pixelorama_version=result_payload["pixelorama_version"],
            process_exit_code=result_payload["process_exit_code"],
            output_hash=result_payload["output_hash"],
            output_byte_count=result_payload["output_byte_count"],
            width=result_payload["width"],
            height=result_payload["height"],
            stdout=b"\x00" * stdout_bytes,
            stderr=b"\x00" * stderr_bytes,
            stdout_truncated=result_payload["stdout_truncated"],
            stderr_truncated=result_payload["stderr_truncated"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("bound Pixelorama result payload is invalid") from exc
    if operation.to_dict() != result_payload:
        raise RuntimeError("bound Pixelorama result payload is not canonical")
    if (
        operation.process_exit_code != 0
        or operation.output_hash != _prefixed_output_hash(binding)
        or operation.output_byte_count != binding.output_byte_count
        or operation.width <= 0
        or operation.height <= 0
        or not isinstance(operation.pixelorama_version, str)
        or not operation.pixelorama_version
    ):
        raise RuntimeError("bound Pixelorama result payload drifted from immutable binding")

    return PixeloramaCliExportServiceResult(
        run_id=binding.run_id,
        request_artifact_id=binding.request_artifact_id,
        result_artifact_id=binding.result_artifact_id,
        output_artifact_id=binding.output_artifact_id,
        output_verification_id=binding.output_verification_id,
        run_verification_id=binding.run_verification_id,
        operation=operation,
    )


def require_bound_pixelorama_output_evidence(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
) -> None:
    """Fail closed unless one binding still names exact durable Phase-48 evidence."""
    execution = read_dispatch_execution(runtime, binding.execution_id)
    if (
        execution.execution_owner_id != PIXELORAMA_EXECUTION_OWNER_ID
        or execution.claim_id != binding.claim_id
        or execution.task_id != binding.task_id
        or execution.task_revision != binding.task_revision
        or execution.task_content_hash != binding.task_content_hash
        or execution.work_order_id != binding.work_order_id
        or execution.work_order_hash != binding.work_order_hash
        or execution.dispatch_binding_id != binding.dispatch_binding_id
        or execution.dispatch_binding_hash != binding.dispatch_binding_hash
    ):
        raise RuntimeError("binding drifted from frozen Pixelorama execution authority")

    run = runtime.get_run(binding.run_id)
    task = runtime.get_task(binding.task_id)
    if (
        run["task_id"] != binding.task_id
        or run["role"] != PixeloramaCliExportService.RUN_ROLE
        or run["status"] != RunStatus.SUCCEEDED.value
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != binding.task_revision + 1
    ):
        raise RuntimeError("bound Pixelorama Run/Task lifecycle is not exact")

    lineage = OriginForgeLineage(runtime)
    request_artifact, request_payload = _artifact_json(
        lineage, binding.request_artifact_id, "request"
    )
    result_artifact, result_payload = _artifact_json(
        lineage, binding.result_artifact_id, "result"
    )
    try:
        output_artifact = lineage.get_artifact(binding.output_artifact_id)
        output_path = lineage.local_artifact_path(binding.output_artifact_id)
        output_bytes = output_path.read_bytes()
    except (KeyError, OSError, RuntimeError) as exc:
        raise RuntimeError("bound Pixelorama output Artifact cannot be reread") from exc
    prefixed_hash = _prefixed_output_hash(binding)
    if (
        request_artifact["type"] != "PIXELORAMA_CLI_EXPORT_REQUEST"
        or request_artifact["created_by_run_id"] != binding.run_id
        or request_artifact["parent_artifact_id"] is not None
        or request_artifact["status"] != "CAPTURED"
        or result_artifact["type"] != "PIXELORAMA_CLI_EXPORT_RESULT"
        or result_artifact["created_by_run_id"] != binding.run_id
        or result_artifact["parent_artifact_id"] != binding.request_artifact_id
        or result_artifact["status"] != "CAPTURED"
        or output_artifact["type"] != "SPRITESHEET_EXPORT"
        or output_artifact["created_by_run_id"] != binding.run_id
        or output_artifact["parent_artifact_id"] != binding.result_artifact_id
        or output_artifact["status"] != "PRODUCED"
        or output_artifact["content_hash"] != prefixed_hash
        or len(output_bytes) != binding.output_byte_count
        or "sha256:" + hashlib.sha256(output_bytes).hexdigest() != prefixed_hash
    ):
        raise RuntimeError("bound Pixelorama Artifact lineage is not exact")

    materialized = _materialize_result_payloads(
        runtime, binding, request_payload, result_payload
    )
    if materialized.operation.output_hash != prefixed_hash:
        raise RuntimeError("bound Pixelorama result materialization drifted")

    output_matches = [
        item
        for item in lineage.list_artifact_verifications(binding.output_artifact_id)
        if item["id"] == binding.output_verification_id
    ]
    if len(output_matches) != 1:
        raise RuntimeError("bound Pixelorama output Verification is missing or ambiguous")
    output_verification = output_matches[0]
    output_evidence = _json_evidence(output_verification["evidence_json"], "output Verification")
    if (
        output_verification["verification_type"] != "pixelorama-cli-export-integrity"
        or output_verification["verifier"] != PixeloramaCliExportService.VERIFIER
        or output_verification["status"] != "PASS"
        or output_verification["run_id"] != binding.run_id
        or output_evidence.get("request_artifact_id") != binding.request_artifact_id
        or output_evidence.get("result_artifact_id") != binding.result_artifact_id
        or output_evidence.get("output_hash") != prefixed_hash
        or output_evidence.get("output_byte_count") != binding.output_byte_count
        or output_evidence.get("production_task_verified") is not False
        or output_evidence.get("canonical_asset_adopted") is not False
    ):
        raise RuntimeError("bound Pixelorama output Verification drifted")

    run_matches = [
        item
        for item in runtime.list_verifications("RUN", binding.run_id)
        if item["id"] == binding.run_verification_id
    ]
    if len(run_matches) != 1:
        raise RuntimeError("bound Pixelorama Run Verification is missing or ambiguous")
    run_verification = run_matches[0]
    run_evidence = _json_evidence(run_verification["evidence_json"], "Run Verification")
    if (
        run_verification["verification_type"] != "pixelorama-cli-export"
        or run_verification["verifier"] != PixeloramaCliExportService.VERIFIER
        or run_verification["status"] != "PASS"
        or run_verification["run_id"] != binding.run_id
        or run_evidence.get("request_artifact_id") != binding.request_artifact_id
        or run_evidence.get("result_artifact_id") != binding.result_artifact_id
        or run_evidence.get("output_artifact_id") != binding.output_artifact_id
        or run_evidence.get("output_verification_id") != binding.output_verification_id
        or run_evidence.get("output_hash") != prefixed_hash
        or run_evidence.get("output_byte_count") != binding.output_byte_count
        or run_evidence.get("production_task_verified") is not False
        or run_evidence.get("canonical_asset_adopted") is not False
        or run_evidence.get("provenance_signed") is not False
    ):
        raise RuntimeError("bound Pixelorama Run Verification drifted")


def materialize_bound_pixelorama_result(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
) -> PixeloramaCliExportServiceResult:
    """Reconstruct the typed Phase-48 return from exact immutable durable evidence."""
    require_bound_pixelorama_output_evidence(runtime, binding)
    lineage = OriginForgeLineage(runtime)
    _, request_payload = _artifact_json(lineage, binding.request_artifact_id, "request")
    _, result_payload = _artifact_json(lineage, binding.result_artifact_id, "result")
    return _materialize_result_payloads(runtime, binding, request_payload, result_payload)


def inspect_pixelorama_dispatch_output_currentness_readonly(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> PixeloramaDispatchOutputCurrentness:
    """Resolve terminal Pixelorama output adoption eligibility without mutating state."""
    try:
        execution = read_dispatch_execution(runtime, execution_id)
        binding = read_pixelorama_dispatch_output_binding(runtime, execution_id)
    except Exception as exc:
        return PixeloramaDispatchOutputCurrentness(
            execution_id,
            None,
            None,
            PixeloramaDispatchOutputCurrentnessStatus.INVALID_EVIDENCE,
            False,
            str(exc),
        )
    if execution.execution_owner_id != PIXELORAMA_EXECUTION_OWNER_ID:
        return PixeloramaDispatchOutputCurrentness(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            PixeloramaDispatchOutputCurrentnessStatus.STALE_EXECUTION,
            False,
            "dispatch execution is not owned by reviewed Pixelorama owner",
        )

    currentness = inspect_dispatch_execution_currentness_readonly(runtime, execution_id)
    if execution.status is not DispatchExecutionStatus.RETURNED:
        status = (
            PixeloramaDispatchOutputCurrentnessStatus.EXECUTION_NOT_RETURNED
            if currentness.status is DispatchExecutionCurrentnessStatus.CURRENT_STARTED
            else PixeloramaDispatchOutputCurrentnessStatus.STALE_EXECUTION
        )
        return PixeloramaDispatchOutputCurrentness(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            status,
            False,
            currentness.detail,
        )
    if currentness.status is not DispatchExecutionCurrentnessStatus.RETURNED:
        return PixeloramaDispatchOutputCurrentness(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            PixeloramaDispatchOutputCurrentnessStatus.STALE_EXECUTION,
            False,
            currentness.detail,
        )
    try:
        require_bound_pixelorama_output_evidence(runtime, binding)
    except Exception as exc:
        detail = str(exc)
        status = (
            PixeloramaDispatchOutputCurrentnessStatus.TASK_NOT_RUNNING
            if "Run/Task lifecycle" in detail
            else PixeloramaDispatchOutputCurrentnessStatus.INVALID_EVIDENCE
        )
        return PixeloramaDispatchOutputCurrentness(
            execution_id,
            execution.task_id,
            binding.output_artifact_id,
            status,
            False,
            detail,
        )
    return PixeloramaDispatchOutputCurrentness(
        execution_id,
        execution.task_id,
        binding.output_artifact_id,
        PixeloramaDispatchOutputCurrentnessStatus.ELIGIBLE,
        True,
        None,
    )
