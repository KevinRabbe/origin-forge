from __future__ import annotations

import json
import sqlite3

from .ids import IdKind, validate_id
from .production_dispatch_execution_models import DispatchExecution
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .production_runtime_dispatch_output_binding_models import (
    RUNTIME_EXECUTION_OWNER_ID,
    RuntimeDispatchCapture,
    RuntimeDispatchOutputBinding,
    RuntimeDispatchOutputBindingModelError,
)
from .runtime import OriginForgeRuntime


class RuntimeDispatchOutputBindingError(RuntimeError):
    pass


class RuntimeDispatchOutputBindingConflict(RuntimeDispatchOutputBindingError):
    pass


def _from_row(row) -> RuntimeDispatchOutputBinding:
    try:
        raw_captures = json.loads(row["capture_evidence_json"])
        if not isinstance(raw_captures, list):
            raise TypeError("capture evidence must be a list")
        captures = tuple(RuntimeDispatchCapture(**value) for value in raw_captures)
        return RuntimeDispatchOutputBinding(
            execution_id=row["execution_id"], claim_id=row["claim_id"], task_id=row["task_id"],
            task_revision=int(row["task_revision"]), task_content_hash=row["task_content_hash"],
            work_order_id=row["work_order_id"], work_order_hash=row["work_order_hash"],
            dispatch_binding_id=row["dispatch_binding_id"], dispatch_binding_hash=row["dispatch_binding_hash"],
            execution_owner_id=row["execution_owner_id"], run_id=row["run_id"],
            request_artifact_id=row["request_artifact_id"], result_artifact_id=row["result_artifact_id"],
            stdout_artifact_id=row["stdout_artifact_id"], stderr_artifact_id=row["stderr_artifact_id"],
            captures=captures, backend_result_hash=row["backend_result_hash"],
            schema_version=int(row["schema_version"]), created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError, RuntimeDispatchOutputBindingModelError) as exc:
        raise RuntimeDispatchOutputBindingError("stored runtime output binding is invalid") from exc


def _require_relation(conn, runtime: OriginForgeRuntime, binding: RuntimeDispatchOutputBinding) -> None:
    row = conn.execute(
        "SELECT * FROM dispatch_executions WHERE execution_id = ?", (binding.execution_id,)
    ).fetchone()
    if row is None:
        raise RuntimeDispatchOutputBindingError("dispatch execution does not exist")
    for field, expected in (
        ("project_id", runtime.project_id()), ("claim_id", binding.claim_id),
        ("task_id", binding.task_id), ("task_revision", binding.task_revision),
        ("task_content_hash", binding.task_content_hash), ("work_order_id", binding.work_order_id),
        ("work_order_hash", binding.work_order_hash), ("dispatch_binding_id", binding.dispatch_binding_id),
        ("dispatch_binding_hash", binding.dispatch_binding_hash),
        ("execution_owner_id", RUNTIME_EXECUTION_OWNER_ID),
    ):
        if row[field] != expected:
            raise RuntimeDispatchOutputBindingError("runtime binding does not match exact execution relation")


def publish_runtime_dispatch_output_binding(
    runtime: OriginForgeRuntime, binding: RuntimeDispatchOutputBinding
) -> RuntimeDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime) or not isinstance(binding, RuntimeDispatchOutputBinding):
        raise TypeError("runtime and binding must be canonical objects")
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_relation(conn, runtime, binding)
        existing = conn.execute(
            "SELECT * FROM runtime_dispatch_output_bindings WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if existing is not None:
            value = _from_row(existing)
            if value == binding:
                return value
            raise RuntimeDispatchOutputBindingConflict("runtime execution already has a different output binding")
        try:
            conn.execute(
                """INSERT INTO runtime_dispatch_output_bindings(
                    execution_id, claim_id, task_id, task_revision, task_content_hash,
                    work_order_id, work_order_hash, dispatch_binding_id, dispatch_binding_hash,
                    execution_owner_id, run_id, request_artifact_id, result_artifact_id,
                    stdout_artifact_id, stderr_artifact_id, capture_evidence_json,
                    backend_result_hash, schema_version, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    binding.execution_id, binding.claim_id, binding.task_id, binding.task_revision,
                    binding.task_content_hash, binding.work_order_id, binding.work_order_hash,
                    binding.dispatch_binding_id, binding.dispatch_binding_hash, binding.execution_owner_id,
                    binding.run_id, binding.request_artifact_id, binding.result_artifact_id,
                    binding.stdout_artifact_id, binding.stderr_artifact_id, binding.captures_json,
                    binding.backend_result_hash, binding.schema_version, binding.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise RuntimeDispatchOutputBindingConflict("runtime output identity is already bound") from exc
        return binding


def read_runtime_dispatch_output_binding(
    runtime: OriginForgeRuntime, execution_id: str
) -> RuntimeDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise RuntimeDispatchOutputBindingError("execution_id must be a valid DISPEXEC ID")
    try:
        with production_read_connection(runtime) as conn:
            row = conn.execute(
                "SELECT * FROM runtime_dispatch_output_bindings WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise RuntimeDispatchOutputBindingError("runtime dispatch-output binding does not exist")
            binding = _from_row(row)
            _require_relation(conn, runtime, binding)
            return binding
    except RuntimeDispatchOutputBindingError:
        raise
    except ProductionReadGuardError as exc:
        raise RuntimeDispatchOutputBindingError(str(exc)) from exc


def binding_from_runtime_result(
    execution: DispatchExecution, result, *, captures: tuple[RuntimeDispatchCapture, ...], created_at: str
) -> RuntimeDispatchOutputBinding:
    if not isinstance(execution, DispatchExecution):
        raise TypeError("execution must be a DispatchExecution")
    if execution.execution_owner_id != RUNTIME_EXECUTION_OWNER_ID:
        raise RuntimeDispatchOutputBindingError("execution is not owned by runtime observation")
    return RuntimeDispatchOutputBinding(
        execution_id=execution.execution_id, claim_id=execution.claim_id, task_id=execution.task_id,
        task_revision=execution.task_revision, task_content_hash=execution.task_content_hash,
        work_order_id=execution.work_order_id, work_order_hash=execution.work_order_hash,
        dispatch_binding_id=execution.dispatch_binding_id, dispatch_binding_hash=execution.dispatch_binding_hash,
        execution_owner_id=execution.execution_owner_id, run_id=result.run_id,
        request_artifact_id=result.request_artifact_id, result_artifact_id=result.result_artifact_id,
        stdout_artifact_id=result.stdout_artifact_id, stderr_artifact_id=result.stderr_artifact_id,
        captures=captures, backend_result_hash=result.backend_result_hash,
        schema_version=1, created_at=created_at,
    )
