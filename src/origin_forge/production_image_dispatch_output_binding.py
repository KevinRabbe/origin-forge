from __future__ import annotations

import sqlite3

from .image_vision_service import ImageGenerationServiceResult
from .ids import IdKind, validate_id
from .production_dispatch_execution_models import DispatchExecution
from .production_image_dispatch_output_binding_models import (
    IMAGE_EXECUTION_OWNER_ID,
    ImageDispatchOutput,
    ImageDispatchOutputBinding,
    ImageDispatchOutputBindingModelError,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime


class ImageDispatchOutputBindingError(RuntimeError):
    pass


class ImageDispatchOutputBindingConflict(ImageDispatchOutputBindingError):
    pass


def _binding_from_rows(rows) -> ImageDispatchOutputBinding:
    if not rows:
        raise ImageDispatchOutputBindingError("image dispatch-output binding does not exist")
    first = rows[0]
    try:
        outputs = tuple(
            ImageDispatchOutput(
                relative_path=row["output_relative_path"],
                artifact_id=row["output_artifact_id"],
                verification_id=row["output_verification_id"],
                content_hash=row["output_content_hash"],
                pixel_hash=row["output_pixel_hash"],
                width=int(row["output_width"]),
                height=int(row["output_height"]),
                byte_count=int(row["output_byte_count"]),
            )
            for row in rows
        )
        return ImageDispatchOutputBinding(
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
            backend_result_hash=first["backend_result_hash"],
            schema_version=int(first["schema_version"]),
            created_at=first["created_at"],
        )
    except (KeyError, TypeError, ValueError, ImageDispatchOutputBindingModelError) as exc:
        raise ImageDispatchOutputBindingError("stored image output binding is invalid") from exc


def _require_execution_relation(conn, project_id: str, binding: ImageDispatchOutputBinding) -> None:
    rows = conn.execute(
        "SELECT * FROM dispatch_executions WHERE execution_id = ?",
        (binding.execution_id,),
    ).fetchall()
    if not rows:
        raise ImageDispatchOutputBindingError("dispatch execution does not exist")
    row = rows[0]
    fields = (
        ("project_id", project_id),
        ("claim_id", binding.claim_id),
        ("task_id", binding.task_id),
        ("task_revision", binding.task_revision),
        ("task_content_hash", binding.task_content_hash),
        ("work_order_id", binding.work_order_id),
        ("work_order_hash", binding.work_order_hash),
        ("dispatch_binding_id", binding.dispatch_binding_id),
        ("dispatch_binding_hash", binding.dispatch_binding_hash),
        ("execution_owner_id", binding.execution_owner_id),
    )
    if any(row[field] != expected for field, expected in fields):
        raise ImageDispatchOutputBindingError(
            "image output binding does not match exact dispatch execution relation"
        )


def publish_image_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    binding: ImageDispatchOutputBinding,
) -> ImageDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, ImageDispatchOutputBinding):
        raise TypeError("binding must be an ImageDispatchOutputBinding")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_execution_relation(conn, project_id, binding)
        rows = conn.execute(
            "SELECT * FROM image_dispatch_output_bindings WHERE execution_id = ? ORDER BY output_index",
            (binding.execution_id,),
        ).fetchall()
        if rows:
            existing = _binding_from_rows(rows)
            if existing == binding:
                return existing
            raise ImageDispatchOutputBindingConflict(
                "dispatch execution already has a different image output binding"
            )
        try:
            for index, output in enumerate(binding.outputs):
                conn.execute(
                    """INSERT INTO image_dispatch_output_bindings(
                       execution_id, output_index, claim_id, task_id, task_revision,
                       task_content_hash, work_order_id, work_order_hash,
                       dispatch_binding_id, dispatch_binding_hash, execution_owner_id,
                       run_id, request_artifact_id, result_artifact_id,
                       output_artifact_id, output_verification_id, output_relative_path,
                       output_content_hash, output_pixel_hash, output_width,
                       output_height, output_byte_count, backend_result_hash,
                       schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        binding.execution_id, index, binding.claim_id, binding.task_id,
                        binding.task_revision, binding.task_content_hash, binding.work_order_id,
                        binding.work_order_hash, binding.dispatch_binding_id,
                        binding.dispatch_binding_hash, binding.execution_owner_id, binding.run_id,
                        binding.request_artifact_id, binding.result_artifact_id, output.artifact_id,
                        output.verification_id, output.relative_path, output.content_hash,
                        output.pixel_hash, output.width, output.height, output.byte_count,
                        binding.backend_result_hash, binding.schema_version, binding.created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ImageDispatchOutputBindingConflict(
                "image dispatch-output identity is already bound elsewhere"
            ) from exc
        stored = _binding_from_rows(
            conn.execute(
                "SELECT * FROM image_dispatch_output_bindings WHERE execution_id = ? ORDER BY output_index",
                (binding.execution_id,),
            ).fetchall()
        )
        if stored != binding:
            raise ImageDispatchOutputBindingError(
                "published image dispatch-output binding changed during transaction"
            )
        return stored


def read_image_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> ImageDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(execution_id, str) or not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise ImageDispatchOutputBindingError("execution_id must be a valid DISPEXEC ID")
    try:
        with production_read_connection(runtime) as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?", (str(runtime.project_root),)
            ).fetchone()
            if project is None:
                raise ImageDispatchOutputBindingError("project is not initialized")
            rows = conn.execute(
                "SELECT * FROM image_dispatch_output_bindings WHERE execution_id = ? ORDER BY output_index",
                (execution_id,),
            ).fetchall()
            binding = _binding_from_rows(rows)
            _require_execution_relation(conn, project["id"], binding)
            return binding
    except ImageDispatchOutputBindingError:
        raise
    except ProductionReadGuardError as exc:
        raise ImageDispatchOutputBindingError(str(exc)) from exc


def binding_from_image_result(
    execution: DispatchExecution,
    result: ImageGenerationServiceResult,
    *,
    output_byte_counts: tuple[int, ...],
    created_at: str,
) -> ImageDispatchOutputBinding:
    """Build a fully checked binding candidate; do not persist or terminalize."""
    if not isinstance(execution, DispatchExecution):
        raise TypeError("execution must be a DispatchExecution")
    if not isinstance(result, ImageGenerationServiceResult):
        raise TypeError("result must be an ImageGenerationServiceResult")
    if execution.execution_owner_id != IMAGE_EXECUTION_OWNER_ID:
        raise ImageDispatchOutputBindingError("execution is not owned by image generation")
    if not result.outputs:
        raise ImageDispatchOutputBindingError("image result must contain at least one output")
    if len(output_byte_counts) != len(result.outputs):
        raise ImageDispatchOutputBindingError(
            "image output byte counts must exactly match result outputs"
        )
    outputs = tuple(
        ImageDispatchOutput(
            relative_path=value.relative_path,
            artifact_id=value.artifact_id,
            verification_id=value.verification_id,
            content_hash=value.content_hash.removeprefix("sha256:"),
            pixel_hash=value.pixel_hash.removeprefix("sha256:"),
            width=value.width,
            height=value.height,
            byte_count=byte_count,
        )
        for value, byte_count in zip(result.outputs, output_byte_counts, strict=True)
    )
    return ImageDispatchOutputBinding(
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
        backend_result_hash=result.backend_result_hash.removeprefix("sha256:"),
        schema_version=1,
        created_at=created_at,
    )
