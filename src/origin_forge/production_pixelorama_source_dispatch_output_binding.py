from __future__ import annotations

import sqlite3
import json

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .pixelorama_bridge import PixeloramaOperationResult
from .pixelorama_media import PixeloramaMediaResult
from .pixelorama_models import BridgeOutputType
from .production_dispatch_execution_models import DispatchExecution
from .production_pixelorama_source_dispatch_output_binding_models import (
    PIXELORAMA_SOURCE_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION,
    PIXELORAMA_SOURCE_EXECUTION_OWNER_ID,
    PixeloramaSourceDispatchOutput,
    PixeloramaSourceDispatchOutputBinding,
    PixeloramaSourceOutputBindingModelError,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime
from .pixelorama_protocol import PixeloramaProtocolError, parse_bridge_request, parse_bridge_result


class PixeloramaSourceOutputBindingError(RuntimeError):
    pass


class PixeloramaSourceOutputBindingConflict(PixeloramaSourceOutputBindingError):
    pass


def _binding_from_rows(rows) -> PixeloramaSourceDispatchOutputBinding:
    if not rows:
        raise PixeloramaSourceOutputBindingError(
            "Pixelorama source dispatch-output binding does not exist"
        )
    first = rows[0]
    try:
        indices = [int(row["output_index"]) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise PixeloramaSourceOutputBindingError("stored source output indices are invalid") from exc
    if indices != list(range(len(rows))):
        raise PixeloramaSourceOutputBindingError(
            "stored source output indices are not contiguous and canonical"
        )
    shared_fields = (
        "execution_id", "claim_id", "task_id", "task_revision", "task_content_hash",
        "work_order_id", "work_order_hash", "dispatch_binding_id", "dispatch_binding_hash",
        "execution_owner_id", "run_id", "request_artifact_id", "result_artifact_id",
        "run_verification_id", "backend_result_hash", "schema_version", "created_at",
    )
    for row in rows[1:]:
        if any(row[field] != first[field] for field in shared_fields):
            raise PixeloramaSourceOutputBindingError(
                "stored source output rows disagree on shared execution relation"
            )
    try:
        outputs = tuple(
            PixeloramaSourceDispatchOutput(
                output_type=BridgeOutputType(row["output_type"]),
                relative_path=row["output_relative_path"],
                artifact_id=row["output_artifact_id"],
                verification_id=row["output_verification_id"],
                content_hash=row["output_content_hash"],
                byte_count=int(row["output_byte_count"]),
                width=None if row["output_width"] is None else int(row["output_width"]),
                height=None if row["output_height"] is None else int(row["output_height"]),
            )
            for row in rows
        )
        return PixeloramaSourceDispatchOutputBinding(
            execution_id=first["execution_id"],
            claim_id=first["claim_id"],
            task_id=first["task_id"],
            task_revision=int(first["task_revision"]),
            task_content_hash=first["task_content_hash"],
            work_order_id=first["work_order_id"],
            work_order_hash=first["work_order_hash"],
            dispatch_binding_id=first["dispatch_binding_id"],
            dispatch_binding_hash=first["dispatch_binding_hash"],
            execution_owner_id=first["execution_owner_id"],
            run_id=first["run_id"],
            request_artifact_id=first["request_artifact_id"],
            result_artifact_id=first["result_artifact_id"],
            outputs=outputs,
            run_verification_id=first["run_verification_id"],
            backend_result_hash=first["backend_result_hash"],
            schema_version=int(first["schema_version"]),
            created_at=first["created_at"],
        )
    except (KeyError, TypeError, ValueError, PixeloramaSourceOutputBindingModelError) as exc:
        raise PixeloramaSourceOutputBindingError("stored source output binding is invalid") from exc


def _require_execution_relation(conn, project_id: str, binding: PixeloramaSourceDispatchOutputBinding) -> None:
    row = conn.execute(
        "SELECT * FROM dispatch_executions WHERE execution_id = ?",
        (binding.execution_id,),
    ).fetchone()
    if row is None:
        raise PixeloramaSourceOutputBindingError("dispatch execution does not exist")
    fields = (
        ("project_id", project_id), ("claim_id", binding.claim_id), ("task_id", binding.task_id),
        ("task_revision", binding.task_revision), ("task_content_hash", binding.task_content_hash),
        ("work_order_id", binding.work_order_id), ("work_order_hash", binding.work_order_hash),
        ("dispatch_binding_id", binding.dispatch_binding_id),
        ("dispatch_binding_hash", binding.dispatch_binding_hash),
        ("execution_owner_id", PIXELORAMA_SOURCE_EXECUTION_OWNER_ID),
    )
    if any(row[field] != expected for field, expected in fields):
        raise PixeloramaSourceOutputBindingError(
            "source output binding does not match exact dispatch execution relation"
        )


def publish_pixelorama_source_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    binding: PixeloramaSourceDispatchOutputBinding,
) -> PixeloramaSourceDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, PixeloramaSourceDispatchOutputBinding):
        raise TypeError("binding must be a PixeloramaSourceDispatchOutputBinding")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_execution_relation(conn, project_id, binding)
        rows = conn.execute(
            "SELECT * FROM pixelorama_source_dispatch_output_bindings WHERE execution_id = ? ORDER BY output_index",
            (binding.execution_id,),
        ).fetchall()
        if rows:
            existing = _binding_from_rows(rows)
            if existing == binding:
                return existing
            raise PixeloramaSourceOutputBindingConflict(
                "dispatch execution already has a different source output binding"
            )
        try:
            for index, output in enumerate(binding.outputs):
                conn.execute(
                    """INSERT INTO pixelorama_source_dispatch_output_bindings(
                       execution_id, output_index, claim_id, task_id, task_revision,
                       task_content_hash, work_order_id, work_order_hash,
                       dispatch_binding_id, dispatch_binding_hash, execution_owner_id,
                       run_id, request_artifact_id, result_artifact_id,
                       output_artifact_id, output_verification_id, run_verification_id,
                       output_type, output_relative_path, output_content_hash,
                       output_byte_count, output_width, output_height, backend_result_hash,
                       schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        binding.execution_id, index, binding.claim_id, binding.task_id,
                        binding.task_revision, binding.task_content_hash, binding.work_order_id,
                        binding.work_order_hash, binding.dispatch_binding_id,
                        binding.dispatch_binding_hash, binding.execution_owner_id,
                        binding.run_id, binding.request_artifact_id, binding.result_artifact_id,
                        output.artifact_id, output.verification_id, binding.run_verification_id,
                        output.output_type.value, output.relative_path, output.content_hash,
                        output.byte_count, output.width, output.height, binding.backend_result_hash,
                        binding.schema_version, binding.created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise PixeloramaSourceOutputBindingConflict(
                "source output identity is already bound elsewhere"
            ) from exc
        stored = _binding_from_rows(
            conn.execute(
                "SELECT * FROM pixelorama_source_dispatch_output_bindings WHERE execution_id = ? ORDER BY output_index",
                (binding.execution_id,),
            ).fetchall()
        )
        if stored != binding:
            raise PixeloramaSourceOutputBindingError(
                "published source output binding changed during transaction"
            )
        return stored


def read_pixelorama_source_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> PixeloramaSourceDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(execution_id, str) or not validate_id(
        execution_id, IdKind.DISPATCH_EXECUTION
    ):
        raise PixeloramaSourceOutputBindingError("execution_id must be a valid DISPEXEC ID")
    try:
        with production_read_connection(runtime) as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?", (str(runtime.project_root),)
            ).fetchone()
            if project is None:
                raise PixeloramaSourceOutputBindingError("project is not initialized")
            rows = conn.execute(
                "SELECT * FROM pixelorama_source_dispatch_output_bindings WHERE execution_id = ? ORDER BY output_index",
                (execution_id,),
            ).fetchall()
            binding = _binding_from_rows(rows)
            _require_execution_relation(conn, project["id"], binding)
            return binding
    except PixeloramaSourceOutputBindingError:
        raise
    except ProductionReadGuardError as exc:
        raise PixeloramaSourceOutputBindingError(str(exc)) from exc


def binding_from_pixelorama_source_result(
    execution: DispatchExecution,
    result: PixeloramaMediaResult,
    *,
    output_byte_counts: tuple[int, ...],
    run_verification_id: str,
    created_at: str,
) -> PixeloramaSourceDispatchOutputBinding:
    if not isinstance(execution, DispatchExecution):
        raise TypeError("execution must be a DispatchExecution")
    if not isinstance(result, PixeloramaMediaResult):
        raise TypeError("result must be a PixeloramaMediaResult")
    if execution.execution_owner_id != PIXELORAMA_SOURCE_EXECUTION_OWNER_ID:
        raise PixeloramaSourceOutputBindingError("execution is not owned by Pixelorama source")
    if len(output_byte_counts) != len(result.output_evidence):
        raise PixeloramaSourceOutputBindingError("output byte counts must match source outputs")
    if not validate_id(run_verification_id, IdKind.VERIFICATION):
        raise PixeloramaSourceOutputBindingError("run_verification_id must be a VERIFICATION ID")
    bridge_outputs = result.operation.bridge_result.outputs
    if len(bridge_outputs) != len(result.output_evidence):
        raise PixeloramaSourceOutputBindingError("source result output evidence is incomplete")
    outputs = tuple(
        PixeloramaSourceDispatchOutput(
            output_type=evidence.output_type,
            relative_path=evidence.relative_path,
            artifact_id=evidence.artifact_id,
            verification_id=evidence.verification_id,
            content_hash=evidence.content_hash.removeprefix("sha256:"),
            byte_count=byte_count,
            width=bridge_output.width,
            height=bridge_output.height,
        )
        for evidence, byte_count, bridge_output in zip(
            result.output_evidence, output_byte_counts, bridge_outputs, strict=True
        )
    )
    return PixeloramaSourceDispatchOutputBinding(
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
        outputs=outputs,
        run_verification_id=run_verification_id,
        backend_result_hash=result.operation.bridge_result.content_hash.removeprefix("sha256:"),
        schema_version=PIXELORAMA_SOURCE_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION,
        created_at=created_at,
    )


def materialize_pixelorama_source_result(
    runtime: OriginForgeRuntime,
    binding: PixeloramaSourceDispatchOutputBinding,
) -> PixeloramaMediaResult:
    """Reconstruct a successful source result from durable evidence only."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, PixeloramaSourceDispatchOutputBinding):
        raise TypeError("binding must be a PixeloramaSourceDispatchOutputBinding")
    lineage = OriginForgeLineage(runtime)
    try:
        request_path = lineage.local_artifact_path(binding.request_artifact_id)
        result_path = lineage.local_artifact_path(binding.result_artifact_id)
        request_raw = json.loads(request_path.read_text(encoding="utf-8"))
        result_raw = json.loads(result_path.read_text(encoding="utf-8"))
        request = parse_bridge_request(request_raw)
        bridge_result = parse_bridge_result(result_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError, PixeloramaProtocolError) as exc:
        raise PixeloramaSourceOutputBindingError(
            "durable Pixelorama source request/result evidence is invalid"
        ) from exc
    if request.content_hash != bridge_result.request_hash:
        raise PixeloramaSourceOutputBindingError(
            "durable Pixelorama source result is bound to a different request"
        )
    if bridge_result.content_hash.removeprefix("sha256:") != binding.backend_result_hash:
        raise PixeloramaSourceOutputBindingError(
            "durable Pixelorama source backend result hash drifted"
        )
    expected_outputs = tuple(
        (value.output_type.value, value.relative_path, value.content_hash, value.byte_count)
        for value in binding.outputs
    )
    actual_outputs = tuple(
        (value.output_type.value, value.relative_path, value.content_hash.removeprefix("sha256:"), value.byte_count)
        for value in bridge_result.outputs
    )
    if actual_outputs != expected_outputs:
        raise PixeloramaSourceOutputBindingError(
            "durable Pixelorama source outputs drifted from the binding"
        )
    operation = PixeloramaOperationResult(
        request=request,
        bridge_result=bridge_result,
        workspace_path=runtime.state_dir / "media-workspaces" / request.workspace_id,
        process_exit_code=0,
        stdout=b"",
        stderr=b"",
        stdout_truncated=False,
        stderr_truncated=False,
    )
    outputs = tuple(
        value
        for value in binding.outputs
    )
    from .pixelorama_media import PixeloramaOutputEvidence

    return PixeloramaMediaResult(
        run_id=binding.run_id,
        request_artifact_id=binding.request_artifact_id,
        result_artifact_id=binding.result_artifact_id,
        output_evidence=tuple(
            PixeloramaOutputEvidence(
                relative_path=value.relative_path,
                artifact_id=value.artifact_id,
                verification_id=value.verification_id,
                content_hash="sha256:" + value.content_hash,
                output_type=value.output_type,
            )
            for value in outputs
        ),
        operation=operation,
    )
