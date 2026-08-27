from __future__ import annotations

import json
import sqlite3

from .ids import IdKind, validate_id
from .playtest_service import PlaytestServiceResult
from .production_dispatch_execution_models import DispatchExecution
from .production_playtest_dispatch_output_binding_models import (
    PLAYTEST_EXECUTION_OWNER_ID,
    PlaytestDispatchOutputBinding,
    PlaytestDispatchOutputBindingModelError,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime


class PlaytestDispatchOutputBindingError(RuntimeError):
    pass


class PlaytestDispatchOutputBindingConflict(PlaytestDispatchOutputBindingError):
    pass


def _from_row(row) -> PlaytestDispatchOutputBinding:
    try:
        return PlaytestDispatchOutputBinding(
            execution_id=row["execution_id"], claim_id=row["claim_id"], task_id=row["task_id"],
            task_revision=int(row["task_revision"]), task_content_hash=row["task_content_hash"],
            work_order_id=row["work_order_id"], work_order_hash=row["work_order_hash"],
            dispatch_binding_id=row["dispatch_binding_id"], dispatch_binding_hash=row["dispatch_binding_hash"],
            execution_owner_id=row["execution_owner_id"], run_id=row["run_id"],
            scenario_artifact_id=row["scenario_artifact_id"], telemetry_artifact_id=row["telemetry_artifact_id"],
            summary_artifact_id=row["summary_artifact_id"], stdout_artifact_id=row["stdout_artifact_id"],
            stderr_artifact_id=row["stderr_artifact_id"], telemetry_hash=row["telemetry_hash"],
            summary_json=row["summary_json"], outcome=row["outcome"],
            timed_out=bool(row["timed_out"]),
            exit_code=None if row["exit_code"] is None else int(row["exit_code"]),
            schema_version=int(row["schema_version"]), created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError, PlaytestDispatchOutputBindingModelError) as exc:
        raise PlaytestDispatchOutputBindingError("stored playtest output binding is invalid") from exc


def _require_relation(conn, runtime: OriginForgeRuntime, binding: PlaytestDispatchOutputBinding) -> None:
    row = conn.execute(
        "SELECT * FROM dispatch_executions WHERE execution_id = ?", (binding.execution_id,)
    ).fetchone()
    if row is None:
        raise PlaytestDispatchOutputBindingError("dispatch execution does not exist")
    for field, expected in (
        ("project_id", runtime.project_id()), ("claim_id", binding.claim_id),
        ("task_id", binding.task_id), ("task_revision", binding.task_revision),
        ("task_content_hash", binding.task_content_hash), ("work_order_id", binding.work_order_id),
        ("work_order_hash", binding.work_order_hash), ("dispatch_binding_id", binding.dispatch_binding_id),
        ("dispatch_binding_hash", binding.dispatch_binding_hash),
        ("execution_owner_id", PLAYTEST_EXECUTION_OWNER_ID),
    ):
        if row[field] != expected:
            raise PlaytestDispatchOutputBindingError("playtest binding does not match exact execution relation")


def publish_playtest_dispatch_output_binding(
    runtime: OriginForgeRuntime, binding: PlaytestDispatchOutputBinding
) -> PlaytestDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime) or not isinstance(binding, PlaytestDispatchOutputBinding):
        raise TypeError("runtime and binding must be canonical objects")
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_relation(conn, runtime, binding)
        existing = conn.execute(
            "SELECT * FROM playtest_dispatch_output_bindings WHERE execution_id = ?",
            (binding.execution_id,),
        ).fetchone()
        if existing is not None:
            value = _from_row(existing)
            if value == binding:
                return value
            raise PlaytestDispatchOutputBindingConflict("playtest execution already has a different output binding")
        try:
            conn.execute(
                """INSERT INTO playtest_dispatch_output_bindings(
                    execution_id, claim_id, task_id, task_revision, task_content_hash,
                    work_order_id, work_order_hash, dispatch_binding_id, dispatch_binding_hash,
                    execution_owner_id, run_id, scenario_artifact_id, telemetry_artifact_id,
                    summary_artifact_id, stdout_artifact_id, stderr_artifact_id, telemetry_hash,
                    summary_json, outcome, timed_out, exit_code, schema_version, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    binding.execution_id, binding.claim_id, binding.task_id, binding.task_revision,
                    binding.task_content_hash, binding.work_order_id, binding.work_order_hash,
                    binding.dispatch_binding_id, binding.dispatch_binding_hash, binding.execution_owner_id,
                    binding.run_id, binding.scenario_artifact_id, binding.telemetry_artifact_id,
                    binding.summary_artifact_id, binding.stdout_artifact_id, binding.stderr_artifact_id,
                    binding.telemetry_hash, binding.summary_json, binding.outcome, int(binding.timed_out),
                    binding.exit_code, binding.schema_version, binding.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PlaytestDispatchOutputBindingConflict("playtest output identity is already bound") from exc
        return binding


def read_playtest_dispatch_output_binding(
    runtime: OriginForgeRuntime, execution_id: str
) -> PlaytestDispatchOutputBinding:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
        raise PlaytestDispatchOutputBindingError("execution_id must be a valid DISPEXEC ID")
    try:
        with production_read_connection(runtime) as conn:
            row = conn.execute(
                "SELECT * FROM playtest_dispatch_output_bindings WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            if row is None:
                raise PlaytestDispatchOutputBindingError("playtest dispatch-output binding does not exist")
            binding = _from_row(row)
            _require_relation(conn, runtime, binding)
            return binding
    except PlaytestDispatchOutputBindingError:
        raise
    except ProductionReadGuardError as exc:
        raise PlaytestDispatchOutputBindingError(str(exc)) from exc


def binding_from_playtest_result(
    execution: DispatchExecution, result: PlaytestServiceResult, *, created_at: str
) -> PlaytestDispatchOutputBinding:
    if not isinstance(execution, DispatchExecution) or not isinstance(result, PlaytestServiceResult):
        raise TypeError("execution and result must be canonical objects")
    if execution.execution_owner_id != PLAYTEST_EXECUTION_OWNER_ID:
        raise PlaytestDispatchOutputBindingError("execution is not owned by cooperative playtesting")
    return PlaytestDispatchOutputBinding(
        execution_id=execution.execution_id, claim_id=execution.claim_id, task_id=execution.task_id,
        task_revision=execution.task_revision, task_content_hash=execution.task_content_hash,
        work_order_id=execution.work_order_id, work_order_hash=execution.work_order_hash,
        dispatch_binding_id=execution.dispatch_binding_id, dispatch_binding_hash=execution.dispatch_binding_hash,
        execution_owner_id=execution.execution_owner_id, run_id=result.run_id,
        scenario_artifact_id=result.scenario_artifact_id, telemetry_artifact_id=result.telemetry_artifact_id,
        summary_artifact_id=result.summary_artifact_id, stdout_artifact_id=result.stdout_artifact_id,
        stderr_artifact_id=result.stderr_artifact_id, telemetry_hash=result.telemetry_hash.removeprefix("sha256:"),
        summary_json=json.dumps(result.summary.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        outcome=result.outcome, timed_out=result.timed_out, exit_code=result.exit_code,
        schema_version=1, created_at=created_at,
    )
