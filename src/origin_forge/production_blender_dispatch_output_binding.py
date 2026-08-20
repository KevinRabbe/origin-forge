from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .blender_adapter import BlenderExecution
from .blender_models import BlenderBudget, BlenderJobRequest, BlenderModelError, BlenderOperation
from .blockbench_glb import GlbError, inspect_glb
from .blockbench_models import canonical_bytes
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .model3d_requests import Model3DRequestError, _project
from .production_blender_export import BlenderExportService, BlenderExportServiceResult
from .production_dispatch_execution_models import DispatchExecution
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime
from .service import utc_now
from .state import RunStatus, TaskStatus


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_IDENTITY_TEXT = 256
_MAX_TIMESTAMP_CHARS = 128
BLENDER_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION = 1
BLENDER_EXECUTION_OWNER_ID = "originforge.execution.blender.export-glb@1"


class BlenderDispatchOutputBindingError(RuntimeError):
    pass


class BlenderDispatchOutputBindingConflict(BlenderDispatchOutputBindingError):
    pass


def _typed_id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise BlenderDispatchOutputBindingError(
            f"{label} must be a valid {kind.value} ID"
        )
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise BlenderDispatchOutputBindingError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _identity_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTITY_TEXT
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise BlenderDispatchOutputBindingError(f"{label} is invalid")
    return value


def _timestamp(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TIMESTAMP_CHARS
        or value.strip() != value
    ):
        raise BlenderDispatchOutputBindingError("created_at is invalid")
    return value


@dataclass(frozen=True)
class BlenderDispatchOutputBinding:
    """Immutable one-to-one relation between one DISPEXEC and one Blender GLB output."""

    execution_id: str
    claim_id: str
    task_id: str
    task_revision: int
    task_content_hash: str
    work_order_id: str
    work_order_hash: str
    dispatch_binding_id: str
    dispatch_binding_hash: str
    execution_owner_id: str
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    output_artifact_id: str
    output_verification_id: str
    run_verification_id: str
    output_content_hash: str
    output_byte_count: int
    schema_version: int
    created_at: str

    def __post_init__(self) -> None:
        _typed_id(self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id")
        _typed_id(self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id")
        _typed_id(self.task_id, IdKind.TASK, "task_id")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise BlenderDispatchOutputBindingError(
                "task_revision must be a non-negative integer"
            )
        _digest(self.task_content_hash, "task_content_hash")
        _typed_id(self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id")
        _digest(self.work_order_hash, "work_order_hash")
        _typed_id(self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id")
        _digest(self.dispatch_binding_hash, "dispatch_binding_hash")
        _identity_text(self.execution_owner_id, "execution_owner_id")
        if self.execution_owner_id != BLENDER_EXECUTION_OWNER_ID:
            raise BlenderDispatchOutputBindingError(
                "execution_owner_id is not the reviewed Blender execution owner"
            )
        _typed_id(self.run_id, IdKind.RUN, "run_id")
        _typed_id(self.request_artifact_id, IdKind.ARTIFACT, "request_artifact_id")
        _typed_id(self.result_artifact_id, IdKind.ARTIFACT, "result_artifact_id")
        _typed_id(self.output_artifact_id, IdKind.ARTIFACT, "output_artifact_id")
        _typed_id(self.output_verification_id, IdKind.VERIFICATION, "output_verification_id")
        _typed_id(self.run_verification_id, IdKind.VERIFICATION, "run_verification_id")
        if len({self.request_artifact_id, self.result_artifact_id, self.output_artifact_id}) != 3:
            raise BlenderDispatchOutputBindingError(
                "request/result/output Artifact IDs must be distinct"
            )
        if self.output_verification_id == self.run_verification_id:
            raise BlenderDispatchOutputBindingError(
                "output/run Verification IDs must be distinct"
            )
        _digest(self.output_content_hash, "output_content_hash")
        if type(self.output_byte_count) is not int or self.output_byte_count <= 0:
            raise BlenderDispatchOutputBindingError(
                "output_byte_count must be a positive integer"
            )
        if self.schema_version != BLENDER_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION:
            raise BlenderDispatchOutputBindingError(
                "unsupported Blender dispatch-output binding schema_version"
            )
        _timestamp(self.created_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "dispatch_binding_id": self.dispatch_binding_id,
            "dispatch_binding_hash": self.dispatch_binding_hash,
            "execution_owner_id": self.execution_owner_id,
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "output_artifact_id": self.output_artifact_id,
            "output_verification_id": self.output_verification_id,
            "run_verification_id": self.run_verification_id,
            "output_content_hash": self.output_content_hash,
            "output_byte_count": self.output_byte_count,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }


def _binding_from_row(row) -> BlenderDispatchOutputBinding:
    try:
        return BlenderDispatchOutputBinding(
            execution_id=row["execution_id"],
            claim_id=row["claim_id"],
            task_id=row["task_id"],
            task_revision=int(row["task_revision"]),
            task_content_hash=row["task_content_hash"],
            work_order_id=row["work_order_id"],
            work_order_hash=row["work_order_hash"],
            dispatch_binding_id=row["dispatch_binding_id"],
            dispatch_binding_hash=row["dispatch_binding_hash"],
            execution_owner_id=row["execution_owner_id"],
            run_id=row["run_id"],
            request_artifact_id=row["request_artifact_id"],
            result_artifact_id=row["result_artifact_id"],
            output_artifact_id=row["output_artifact_id"],
            output_verification_id=row["output_verification_id"],
            run_verification_id=row["run_verification_id"],
            output_content_hash=row["output_content_hash"],
            output_byte_count=int(row["output_byte_count"]),
            schema_version=int(row["schema_version"]),
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError, BlenderDispatchOutputBindingError) as exc:
        raise BlenderDispatchOutputBindingError(
            "stored Blender dispatch-output binding failed canonical validation"
        ) from exc


def _require_execution_relation(conn, project_id: str, binding: BlenderDispatchOutputBinding) -> None:
    row = conn.execute(
        """SELECT project_id, claim_id, task_id, task_revision, task_content_hash,
                  work_order_id, work_order_hash, dispatch_binding_id,
                  dispatch_binding_hash, execution_owner_id
           FROM dispatch_executions WHERE execution_id = ?""",
        (binding.execution_id,),
    ).fetchone()
    if row is None:
        raise BlenderDispatchOutputBindingError("dispatch execution does not exist")
    expected = {
        "claim_id": binding.claim_id,
        "task_id": binding.task_id,
        "task_revision": binding.task_revision,
        "task_content_hash": binding.task_content_hash,
        "work_order_id": binding.work_order_id,
        "work_order_hash": binding.work_order_hash,
        "dispatch_binding_id": binding.dispatch_binding_id,
        "dispatch_binding_hash": binding.dispatch_binding_hash,
        "execution_owner_id": binding.execution_owner_id,
    }
    if row["project_id"] != project_id or any(row[key] != value for key, value in expected.items()):
        raise BlenderDispatchOutputBindingError(
            "binding does not match the exact frozen dispatch execution authority"
        )
    if row["execution_owner_id"] != BLENDER_EXECUTION_OWNER_ID:
        raise BlenderDispatchOutputBindingError(
            "dispatch execution is not owned by the reviewed Blender owner"
        )


def publish_blender_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    binding: BlenderDispatchOutputBinding,
) -> BlenderDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, BlenderDispatchOutputBinding):
        raise TypeError("binding must be a BlenderDispatchOutputBinding")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_execution_relation(conn, project_id, binding)
        existing_row = conn.execute(
            "SELECT * FROM blender_dispatch_output_bindings WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if existing_row is not None:
            existing = _binding_from_row(existing_row)
            if existing == binding:
                return existing
            raise BlenderDispatchOutputBindingConflict(
                "dispatch execution already has a different Blender output binding"
            )
        try:
            conn.execute(
                """INSERT INTO blender_dispatch_output_bindings(
                       execution_id, claim_id, task_id, task_revision, task_content_hash,
                       work_order_id, work_order_hash, dispatch_binding_id,
                       dispatch_binding_hash, execution_owner_id, run_id,
                       request_artifact_id, result_artifact_id, output_artifact_id,
                       output_verification_id, run_verification_id, output_content_hash,
                       output_byte_count, schema_version, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    binding.execution_id,
                    binding.claim_id,
                    binding.task_id,
                    binding.task_revision,
                    binding.task_content_hash,
                    binding.work_order_id,
                    binding.work_order_hash,
                    binding.dispatch_binding_id,
                    binding.dispatch_binding_hash,
                    binding.execution_owner_id,
                    binding.run_id,
                    binding.request_artifact_id,
                    binding.result_artifact_id,
                    binding.output_artifact_id,
                    binding.output_verification_id,
                    binding.run_verification_id,
                    binding.output_content_hash,
                    binding.output_byte_count,
                    binding.schema_version,
                    binding.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise BlenderDispatchOutputBindingConflict(
                "Blender dispatch-output identity is already bound elsewhere"
            ) from exc
        stored_row = conn.execute(
            "SELECT * FROM blender_dispatch_output_bindings WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if stored_row is None:
            raise BlenderDispatchOutputBindingError(
                "Blender dispatch-output binding disappeared during publication"
            )
        stored = _binding_from_row(stored_row)
        if stored != binding:
            raise BlenderDispatchOutputBindingError(
                "published Blender dispatch-output binding changed during transaction"
            )
        return stored


def read_blender_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> BlenderDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(execution_id, str) or not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise BlenderDispatchOutputBindingError(
            "execution_id must be a valid DISPEXEC ID"
        )
    try:
        with production_read_connection(runtime) as conn:
            project_row = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?",
                (str(runtime.project_root),),
            ).fetchone()
            if project_row is None:
                raise BlenderDispatchOutputBindingError(
                    "project is not initialized for current repository root"
                )
            row = conn.execute(
                "SELECT * FROM blender_dispatch_output_bindings WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise BlenderDispatchOutputBindingError(
                    "Blender dispatch-output binding does not exist"
                )
            binding = _binding_from_row(row)
            _require_execution_relation(conn, project_row["id"], binding)
            return binding
    except BlenderDispatchOutputBindingError:
        raise
    except ProductionReadGuardError as exc:
        raise BlenderDispatchOutputBindingError(str(exc)) from exc


def bind_blender_dispatch_output(
    runtime: OriginForgeRuntime,
    execution: DispatchExecution,
    result: BlenderExportServiceResult,
) -> BlenderDispatchOutputBinding:
    """Persist the exact already-revalidated Blender result before dispatch terminalization."""
    if not isinstance(execution, DispatchExecution):
        raise TypeError("execution must be a DispatchExecution")
    if not isinstance(result, BlenderExportServiceResult):
        raise TypeError("result must be a BlenderExportServiceResult")
    if execution.execution_owner_id != BLENDER_EXECUTION_OWNER_ID:
        raise BlenderDispatchOutputBindingError("execution is not owned by Blender")
    operation = result.operation
    output_hash = operation.inspection.content_hash
    if not isinstance(output_hash, str) or not output_hash.startswith("sha256:"):
        raise BlenderDispatchOutputBindingError("Blender output hash is invalid")
    try:
        existing = read_blender_dispatch_output_binding(runtime, execution.execution_id)
    except BlenderDispatchOutputBindingError:
        existing = None
    candidate = BlenderDispatchOutputBinding(
        execution_id=execution.execution_id,
        claim_id=execution.claim_id,
        task_id=execution.task_id,
        task_revision=execution.task_revision,
        task_content_hash=execution.task_content_hash,
        work_order_id=execution.work_order_id,
        work_order_hash=execution.work_order_hash,
        dispatch_binding_id=execution.dispatch_binding_id,
        dispatch_binding_hash=execution.dispatch_binding_hash,
        execution_owner_id=execution.execution_owner_id,
        run_id=result.run_id,
        request_artifact_id=result.request_artifact_id,
        result_artifact_id=result.result_artifact_id,
        output_artifact_id=result.output_artifact_id,
        output_verification_id=result.output_verification_id,
        run_verification_id=result.run_verification_id,
        output_content_hash=output_hash.removeprefix("sha256:"),
        output_byte_count=operation.inspection.byte_count,
        schema_version=BLENDER_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION,
        created_at=existing.created_at if existing is not None else utc_now(),
    )
    return publish_blender_dispatch_output_binding(runtime, candidate)


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
        raise BlenderDispatchOutputBindingError(
            f"bound Blender {label} Artifact cannot be reread"
        ) from exc
    expected_hash = "sha256:" + hashlib.sha256(data).hexdigest()
    if (
        not isinstance(payload, dict)
        or canonical_bytes(payload) != data
        or artifact["content_hash"] != expected_hash
    ):
        raise BlenderDispatchOutputBindingError(
            f"bound Blender {label} Artifact bytes drifted"
        )
    return artifact, payload


def _request_from_payload(payload: dict[str, object]) -> BlenderJobRequest:
    expected = {
        "protocol_version",
        "operation_id",
        "workspace_id",
        "operation",
        "project",
        "project_hash",
        "output_relative_path",
        "runner_fingerprint",
        "runtime_hash",
        "expected_blender_version",
        "budget",
    }
    if set(payload) != expected or payload.get("protocol_version") != 1:
        raise BlenderDispatchOutputBindingError("bound Blender request schema drifted")
    budget_value = payload.get("budget")
    if not isinstance(budget_value, dict) or set(budget_value) != {
        "timeout_seconds",
        "max_output_bytes",
        "max_stdout_bytes",
        "max_stderr_bytes",
    }:
        raise BlenderDispatchOutputBindingError("bound Blender request budget drifted")
    try:
        project = _project(payload["project"])
        if payload["project_hash"] != project.content_hash:
            raise BlenderDispatchOutputBindingError("bound Blender project hash drifted")
        request = BlenderJobRequest(
            operation_id=payload["operation_id"],
            workspace_id=payload["workspace_id"],
            operation=BlenderOperation(payload["operation"]),
            project=project,
            output_relative_path=payload["output_relative_path"],
            runner_fingerprint=payload["runner_fingerprint"],
            runtime_hash=payload["runtime_hash"],
            expected_blender_version=payload["expected_blender_version"],
            budget=BlenderBudget(
                timeout_seconds=budget_value["timeout_seconds"],
                max_output_bytes=budget_value["max_output_bytes"],
                max_stdout_bytes=budget_value["max_stdout_bytes"],
                max_stderr_bytes=budget_value["max_stderr_bytes"],
            ),
        )
    except (KeyError, TypeError, ValueError, BlenderModelError, Model3DRequestError) as exc:
        raise BlenderDispatchOutputBindingError("bound Blender request payload is invalid") from exc
    if request.to_dict() != payload:
        raise BlenderDispatchOutputBindingError("bound Blender request payload is not canonical")
    return request


def _safe_exact_output_path(
    runtime: OriginForgeRuntime,
    artifact: dict[str, object],
    request: BlenderJobRequest,
) -> Path:
    expected = (
        f".origin-forge/model3d-workspaces/{request.workspace_id}/"
        f"{request.output_relative_path}"
    )
    if artifact["path_or_uri"] != expected:
        raise BlenderDispatchOutputBindingError("bound Blender output location drifted")
    current = runtime.project_root
    for part in Path(expected).parts:
        current = current / part
        if current.is_symlink():
            raise BlenderDispatchOutputBindingError(
                "bound Blender output path contains a symlink"
            )
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(runtime.project_root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise BlenderDispatchOutputBindingError(
            "bound Blender output escaped protected project state"
        ) from exc
    if not resolved.is_file():
        raise BlenderDispatchOutputBindingError(
            "bound Blender output is not a regular file"
        )
    return resolved


def _json_evidence(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise BlenderDispatchOutputBindingError(f"{label} evidence_json is not text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BlenderDispatchOutputBindingError(f"{label} evidence_json is invalid") from exc
    if not isinstance(decoded, dict):
        raise BlenderDispatchOutputBindingError(f"{label} evidence_json is not an object")
    return decoded


def materialize_bound_blender_result(
    runtime: OriginForgeRuntime,
    binding: BlenderDispatchOutputBinding,
) -> BlenderExportServiceResult:
    """Reconstruct the typed Blender return from exact immutable durable evidence."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, BlenderDispatchOutputBinding):
        raise TypeError("binding must be a BlenderDispatchOutputBinding")

    try:
        from .production_dispatch_execution_read import read_dispatch_execution

        execution = read_dispatch_execution(runtime, binding.execution_id)
    except Exception as exc:
        raise BlenderDispatchOutputBindingError(
            "bound Blender dispatch execution cannot be reread"
        ) from exc
    if (
        execution.execution_owner_id != BLENDER_EXECUTION_OWNER_ID
        or execution.claim_id != binding.claim_id
        or execution.task_id != binding.task_id
        or execution.task_revision != binding.task_revision
        or execution.task_content_hash != binding.task_content_hash
        or execution.work_order_id != binding.work_order_id
        or execution.work_order_hash != binding.work_order_hash
        or execution.dispatch_binding_id != binding.dispatch_binding_id
        or execution.dispatch_binding_hash != binding.dispatch_binding_hash
    ):
        raise BlenderDispatchOutputBindingError(
            "binding drifted from frozen Blender execution authority"
        )

    try:
        run = runtime.get_run(binding.run_id)
        task = runtime.get_task(binding.task_id)
    except (KeyError, RuntimeError) as exc:
        raise BlenderDispatchOutputBindingError(
            "bound Blender Run/Task relation cannot be read"
        ) from exc
    if (
        run["task_id"] != binding.task_id
        or run["role"] != BlenderExportService.RUN_ROLE
        or run["status"] != RunStatus.SUCCEEDED.value
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != binding.task_revision + 1
    ):
        raise BlenderDispatchOutputBindingError(
            "bound Blender Run/Task lifecycle is not exact"
        )

    lineage = OriginForgeLineage(runtime)
    request_artifact, request_payload = _artifact_json(
        lineage, binding.request_artifact_id, "request"
    )
    result_artifact, result_payload = _artifact_json(
        lineage, binding.result_artifact_id, "result"
    )
    request = _request_from_payload(request_payload)
    try:
        output_artifact = lineage.get_artifact(binding.output_artifact_id)
        output_path = _safe_exact_output_path(runtime, output_artifact, request)
        output_bytes = output_path.read_bytes()
        inspection = inspect_glb(output_bytes)
    except (KeyError, OSError, RuntimeError, GlbError) as exc:
        raise BlenderDispatchOutputBindingError(
            "bound Blender output Artifact cannot be independently revalidated"
        ) from exc

    prefixed_hash = "sha256:" + binding.output_content_hash
    if (
        request_artifact["type"] != "BLENDER_JOB_REQUEST"
        or request_artifact["created_by_run_id"] != binding.run_id
        or request_artifact["parent_artifact_id"] is not None
        or request_artifact["status"] != "CAPTURED"
        or request_artifact["path_or_uri"]
        != f".origin-forge/blender-production-export-evidence/{binding.run_id}/request.json"
        or result_artifact["type"] != "BLENDER_EXECUTION_RESULT"
        or result_artifact["created_by_run_id"] != binding.run_id
        or result_artifact["parent_artifact_id"] != binding.request_artifact_id
        or result_artifact["status"] != "CAPTURED"
        or result_artifact["path_or_uri"]
        != f".origin-forge/blender-production-export-evidence/{binding.run_id}/result.json"
        or output_artifact["type"] != "BLENDER_GLB_EXPORT"
        or output_artifact["created_by_run_id"] != binding.run_id
        or output_artifact["parent_artifact_id"] != binding.result_artifact_id
        or output_artifact["status"] != "PRODUCED"
        or output_artifact["content_hash"] != prefixed_hash
        or len(output_bytes) != binding.output_byte_count
        or inspection.content_hash != prefixed_hash
        or inspection.byte_count != binding.output_byte_count
    ):
        raise BlenderDispatchOutputBindingError(
            "bound Blender Artifact lineage is not exact"
        )

    expected_result_fields = {
        "operation_id",
        "workspace_id",
        "request_hash",
        "project_hash",
        "output_relative_path",
        "output",
        "blender_version",
        "runtime_hash",
        "runner_fingerprint",
        "production_verification_changed",
        "canonical_asset_adopted",
    }
    if not isinstance(result_payload, dict) or set(result_payload) != expected_result_fields:
        raise BlenderDispatchOutputBindingError("bound Blender result schema drifted")
    try:
        operation = BlenderExecution(
            request=request,
            workspace_path=runtime.state_dir / "model3d-workspaces" / request.workspace_id,
            output_path=output_path,
            inspection=inspection,
            blender_version=result_payload["blender_version"],
            runtime_hash=result_payload["runtime_hash"],
            runner_fingerprint=result_payload["runner_fingerprint"],
            stdout=b"",
            stderr=b"",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BlenderDispatchOutputBindingError("bound Blender result payload is invalid") from exc
    if operation.to_dict() != result_payload:
        raise BlenderDispatchOutputBindingError(
            "bound Blender result payload drifted from durable output"
        )

    output_matches = [
        value
        for value in lineage.list_artifact_verifications(binding.output_artifact_id)
        if value["id"] == binding.output_verification_id
    ]
    if len(output_matches) != 1:
        raise BlenderDispatchOutputBindingError(
            "bound Blender output Verification is missing or ambiguous"
        )
    output_verification = output_matches[0]
    output_evidence = _json_evidence(
        output_verification["evidence_json"], "output Verification"
    )
    expected_output_evidence = {
        "request_hash": request.content_hash,
        "request_artifact_id": binding.request_artifact_id,
        "result_artifact_id": binding.result_artifact_id,
        "operation_id": request.operation_id,
        "workspace_id": request.workspace_id,
        "project_hash": request.project.content_hash,
        "output_relative_path": request.output_relative_path,
        "output_hash": prefixed_hash,
        "output_byte_count": binding.output_byte_count,
        "blender_version": operation.blender_version,
        "runtime_hash": operation.runtime_hash,
        "runner_fingerprint": operation.runner_fingerprint,
        "glb_inspection": inspection.to_dict(),
        "semantic_geometry_verified": False,
        "production_task_verified": False,
        "canonical_asset_adopted": False,
    }
    if (
        output_verification["verification_type"] != "blender-glb-export-integrity"
        or output_verification["verifier"] != BlenderExportService.VERIFIER
        or output_verification["status"] != "PASS"
        or output_verification["run_id"] != binding.run_id
        or output_evidence != expected_output_evidence
    ):
        raise BlenderDispatchOutputBindingError(
            "bound Blender output Verification drifted"
        )

    run_matches = [
        value
        for value in runtime.list_verifications("RUN", binding.run_id)
        if value["id"] == binding.run_verification_id
    ]
    if len(run_matches) != 1:
        raise BlenderDispatchOutputBindingError(
            "bound Blender Run Verification is missing or ambiguous"
        )
    run_verification = run_matches[0]
    run_evidence = _json_evidence(run_verification["evidence_json"], "Run Verification")
    expected_run_evidence = {
        "request_hash": request.content_hash,
        "request_artifact_id": binding.request_artifact_id,
        "result_artifact_id": binding.result_artifact_id,
        "output_artifact_id": binding.output_artifact_id,
        "output_verification_id": binding.output_verification_id,
        "operation_id": request.operation_id,
        "workspace_id": request.workspace_id,
        "project_hash": request.project.content_hash,
        "output_relative_path": request.output_relative_path,
        "output_hash": prefixed_hash,
        "output_byte_count": binding.output_byte_count,
        "blender_version": operation.blender_version,
        "runtime_hash": operation.runtime_hash,
        "runner_fingerprint": operation.runner_fingerprint,
        "production_task_verified": False,
        "canonical_asset_adopted": False,
        "provenance_signed": False,
    }
    if (
        run_verification["verification_type"] != "blender-export-glb"
        or run_verification["verifier"] != BlenderExportService.VERIFIER
        or run_verification["status"] != "PASS"
        or run_verification["run_id"] != binding.run_id
        or run_evidence != expected_run_evidence
    ):
        raise BlenderDispatchOutputBindingError(
            "bound Blender Run Verification drifted"
        )

    return BlenderExportServiceResult(
        run_id=binding.run_id,
        request_artifact_id=binding.request_artifact_id,
        result_artifact_id=binding.result_artifact_id,
        output_artifact_id=binding.output_artifact_id,
        output_verification_id=binding.output_verification_id,
        run_verification_id=binding.run_verification_id,
        operation=operation,
    )
