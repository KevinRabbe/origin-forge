from __future__ import annotations

import sqlite3

from .ids import IdKind, validate_id
from .production_audio_dispatch_output_binding_models import (
    AUDIO_EXECUTION_OWNER_ID,
    AudioDispatchOutputBinding,
    AudioDispatchOutputBindingModelError,
)
from .production_dispatch_execution_models import DispatchExecution
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime


class AudioDispatchOutputBindingError(RuntimeError):
    pass


class AudioDispatchOutputBindingConflict(AudioDispatchOutputBindingError):
    pass


def _read_rows(runtime: OriginForgeRuntime, execution_id: str):
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise AudioDispatchOutputBindingError("execution_id must be a valid DISPEXEC ID")
    try:
        with production_read_connection(runtime) as conn:
            rows = conn.execute(
                "SELECT * FROM audio_dispatch_output_bindings WHERE execution_id = ?",
                (execution_id,),
            ).fetchall()
            if not rows:
                raise AudioDispatchOutputBindingError("audio dispatch-output binding does not exist")
            return rows
    except AudioDispatchOutputBindingError:
        raise
    except ProductionReadGuardError as exc:
        raise AudioDispatchOutputBindingError(str(exc)) from exc


def _from_row(row) -> AudioDispatchOutputBinding:
    try:
        return AudioDispatchOutputBinding(
            execution_id=row["execution_id"], claim_id=row["claim_id"], task_id=row["task_id"],
            task_revision=int(row["task_revision"]), task_content_hash=row["task_content_hash"],
            work_order_id=row["work_order_id"], work_order_hash=row["work_order_hash"],
            dispatch_binding_id=row["dispatch_binding_id"], dispatch_binding_hash=row["dispatch_binding_hash"],
            execution_owner_id=row["execution_owner_id"], run_id=row["run_id"],
            request_artifact_id=row["request_artifact_id"], result_artifact_id=row["result_artifact_id"],
            output_artifact_id=row["output_artifact_id"], output_verification_id=row["output_verification_id"],
            output_relative_path=row["output_relative_path"], output_content_hash=row["output_content_hash"],
            output_pcm_hash=row["output_pcm_hash"], output_byte_count=int(row["output_byte_count"]),
            output_frame_count=int(row["output_frame_count"]), output_sample_rate=int(row["output_sample_rate"]),
            output_channels=int(row["output_channels"]), output_peak_abs_sample=int(row["output_peak_abs_sample"]),
            output_clipped_sample_count=int(row["output_clipped_sample_count"]),
            output_nonzero_sample_count=int(row["output_nonzero_sample_count"]),
            backend_result_hash=row["backend_result_hash"], schema_version=int(row["schema_version"]),
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError, AudioDispatchOutputBindingModelError) as exc:
        raise AudioDispatchOutputBindingError("stored audio output binding is invalid") from exc


def read_audio_dispatch_output_binding(runtime: OriginForgeRuntime, execution_id: str) -> AudioDispatchOutputBinding:
    return _from_row(_read_rows(runtime, execution_id)[0])


def publish_audio_dispatch_output_binding(runtime: OriginForgeRuntime, binding: AudioDispatchOutputBinding) -> AudioDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime) or not isinstance(binding, AudioDispatchOutputBinding):
        raise TypeError("runtime and binding must be canonical objects")
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        execution = conn.execute(
            "SELECT * FROM dispatch_executions WHERE execution_id = ?", (binding.execution_id,)
        ).fetchone()
        if execution is None:
            raise AudioDispatchOutputBindingError("dispatch execution does not exist")
        for field, expected in (
            ("project_id", runtime.project_id()), ("claim_id", binding.claim_id),
            ("task_id", binding.task_id), ("task_revision", binding.task_revision),
            ("task_content_hash", binding.task_content_hash), ("work_order_id", binding.work_order_id),
            ("work_order_hash", binding.work_order_hash), ("dispatch_binding_id", binding.dispatch_binding_id),
            ("dispatch_binding_hash", binding.dispatch_binding_hash),
            ("execution_owner_id", AUDIO_EXECUTION_OWNER_ID),
        ):
            if execution[field] != expected:
                raise AudioDispatchOutputBindingError("audio binding does not match exact execution relation")
        existing = conn.execute(
            "SELECT * FROM audio_dispatch_output_bindings WHERE execution_id = ?", (binding.execution_id,)
        ).fetchone()
        if existing is not None:
            value = _from_row(existing)
            if value == binding:
                return value
            raise AudioDispatchOutputBindingConflict("audio execution already has a different output binding")
        try:
            conn.execute(
                """INSERT INTO audio_dispatch_output_bindings(
                    execution_id, claim_id, task_id, task_revision, task_content_hash,
                    work_order_id, work_order_hash, dispatch_binding_id, dispatch_binding_hash,
                    execution_owner_id, run_id, request_artifact_id, result_artifact_id,
                    output_artifact_id, output_verification_id, output_relative_path,
                    output_content_hash, output_pcm_hash, output_byte_count, output_frame_count,
                    output_sample_rate, output_channels, output_peak_abs_sample,
                    output_clipped_sample_count, output_nonzero_sample_count, backend_result_hash,
                    schema_version, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (binding.execution_id, binding.claim_id, binding.task_id, binding.task_revision,
                 binding.task_content_hash, binding.work_order_id, binding.work_order_hash,
                 binding.dispatch_binding_id, binding.dispatch_binding_hash, binding.execution_owner_id,
                 binding.run_id, binding.request_artifact_id, binding.result_artifact_id, binding.output_artifact_id,
                 binding.output_verification_id, binding.output_relative_path, binding.output_content_hash,
                 binding.output_pcm_hash, binding.output_byte_count, binding.output_frame_count,
                 binding.output_sample_rate, binding.output_channels, binding.output_peak_abs_sample,
                 binding.output_clipped_sample_count, binding.output_nonzero_sample_count,
                 binding.backend_result_hash, binding.schema_version, binding.created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise AudioDispatchOutputBindingConflict("audio output identity is already bound") from exc
        return binding


def binding_from_audio_result(execution: DispatchExecution, result, *, created_at: str) -> AudioDispatchOutputBinding:
    return AudioDispatchOutputBinding.from_execution_result(execution, result, created_at=created_at)
