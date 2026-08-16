from __future__ import annotations

import sqlite3

from .production_pixelorama_dispatch_output_binding_models import (
    PIXELORAMA_EXECUTION_OWNER_ID,
    PixeloramaDispatchOutputBinding,
    PixeloramaDispatchOutputBindingModelError,
)
from .runtime import OriginForgeRuntime


class PixeloramaDispatchOutputBindingStoreError(RuntimeError):
    pass


class PixeloramaDispatchOutputBindingConflict(PixeloramaDispatchOutputBindingStoreError):
    pass


def _binding_from_row(row) -> PixeloramaDispatchOutputBinding:
    try:
        return PixeloramaDispatchOutputBinding(
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
    except (KeyError, TypeError, ValueError, PixeloramaDispatchOutputBindingModelError) as exc:
        raise PixeloramaDispatchOutputBindingStoreError(
            "stored Pixelorama dispatch-output binding failed canonical validation"
        ) from exc


def _require_execution_relation(conn, project_id: str, binding: PixeloramaDispatchOutputBinding) -> None:
    row = conn.execute(
        """SELECT project_id, claim_id, task_id, task_revision, task_content_hash,
                  work_order_id, work_order_hash, dispatch_binding_id,
                  dispatch_binding_hash, execution_owner_id
           FROM dispatch_executions WHERE execution_id = ?""",
        (binding.execution_id,),
    ).fetchone()
    if row is None:
        raise PixeloramaDispatchOutputBindingStoreError(
            "dispatch execution does not exist"
        )
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
        raise PixeloramaDispatchOutputBindingStoreError(
            "binding does not match the exact frozen dispatch execution authority"
        )
    if row["execution_owner_id"] != PIXELORAMA_EXECUTION_OWNER_ID:
        raise PixeloramaDispatchOutputBindingStoreError(
            "dispatch execution is not owned by the reviewed Pixelorama owner"
        )


def publish_pixelorama_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
) -> PixeloramaDispatchOutputBinding:
    """Insert one immutable relation, or return an exactly identical existing row."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(binding, PixeloramaDispatchOutputBinding):
        raise TypeError("binding must be a PixeloramaDispatchOutputBinding")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_execution_relation(conn, project_id, binding)
        existing_row = conn.execute(
            "SELECT * FROM pixelorama_dispatch_output_bindings WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if existing_row is not None:
            existing = _binding_from_row(existing_row)
            if existing == binding:
                return existing
            raise PixeloramaDispatchOutputBindingConflict(
                "dispatch execution already has a different Pixelorama output binding"
            )
        try:
            conn.execute(
                """INSERT INTO pixelorama_dispatch_output_bindings(
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
            raise PixeloramaDispatchOutputBindingConflict(
                "Pixelorama dispatch-output identity is already bound elsewhere"
            ) from exc
        stored_row = conn.execute(
            "SELECT * FROM pixelorama_dispatch_output_bindings WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if stored_row is None:
            raise PixeloramaDispatchOutputBindingStoreError(
                "Pixelorama dispatch-output binding disappeared during publication"
            )
        stored = _binding_from_row(stored_row)
        if stored != binding:
            raise PixeloramaDispatchOutputBindingStoreError(
                "published Pixelorama dispatch-output binding changed during transaction"
            )
        return stored
