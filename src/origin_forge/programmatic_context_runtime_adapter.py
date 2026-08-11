from __future__ import annotations

import json
from typing import Mapping

from .ids import IdKind, validate_id
from .programmatic_context_interpreter import ContextAdapterRegistry
from .programmatic_context_models import (
    ContextOperationDescriptor,
    ContextReplayClass,
    ProgrammaticContextModelError,
)
from .runtime import OriginForgeRuntime
from .runtime_observation_models import content_hash
from .state import RunStatus


RUN_SHOW_OPERATION_ID = "runtime.run_show"
RUN_SHOW_OPERATION_VERSION = "1"
_TERMINAL_RUN_STATUSES = frozenset(
    value.value for value in RunStatus if value is not RunStatus.RUNNING
)
_RUN_OUTPUT_FIELDS = (
    "id",
    "task_id",
    "role",
    "model_profile",
    "model_hash",
    "skills",
    "allowed_tools",
    "started_at",
    "ended_at",
    "status",
    "failure_reason",
    "input_token_count",
    "output_token_count",
    "resource_metrics",
)
_RUN_SHOW_INPUT_SCHEMA = {
    "type": "object",
    "required": ["run_id"],
    "additional_properties": False,
    "properties": {"run_id": "RUN-ID"},
}
_RUN_SHOW_OUTPUT_SCHEMA = {
    "type": "object",
    "required": list(_RUN_OUTPUT_FIELDS),
    "additional_properties": False,
}
_RUN_SHOW_ADAPTER_FINGERPRINT = content_hash(
    {
        "adapter": "origin-forge:programmatic-context:runtime-run-show",
        "version": RUN_SHOW_OPERATION_VERSION,
        "projection": list(_RUN_OUTPUT_FIELDS),
        "terminal_only": True,
        "task_scoped_project_validation": True,
    }
)


def runtime_run_show_descriptor() -> ContextOperationDescriptor:
    return ContextOperationDescriptor(
        operation_id=RUN_SHOW_OPERATION_ID,
        version=RUN_SHOW_OPERATION_VERSION,
        adapter_fingerprint=_RUN_SHOW_ADAPTER_FINGERPRINT,
        input_schema_hash=content_hash(_RUN_SHOW_INPUT_SCHEMA),
        output_schema_hash=content_hash(_RUN_SHOW_OUTPUT_SCHEMA),
        max_calls=8,
        max_response_bytes=64 * 1024,
        replay_class=ContextReplayClass.DETERMINISTIC,
    )


def _validate_input(value: Mapping[str, object]) -> None:
    if set(value) != {"run_id"}:
        raise ProgrammaticContextModelError("runtime.run_show input must contain only run_id")
    run_id = value["run_id"]
    if not isinstance(run_id, str) or not validate_id(run_id, IdKind.RUN):
        raise ProgrammaticContextModelError("runtime.run_show run_id must be a RUN ID")


def _validate_output(value: object) -> None:
    if not isinstance(value, dict) or set(value) != set(_RUN_OUTPUT_FIELDS):
        raise ProgrammaticContextModelError("runtime.run_show output projection is invalid")
    if not isinstance(value["id"], str) or not validate_id(value["id"], IdKind.RUN):
        raise ProgrammaticContextModelError("runtime.run_show output id is invalid")
    if not isinstance(value["task_id"], str) or not validate_id(value["task_id"], IdKind.TASK):
        raise ProgrammaticContextModelError("runtime.run_show output task_id is invalid")
    if value["status"] not in _TERMINAL_RUN_STATUSES:
        raise ProgrammaticContextModelError("runtime.run_show exposes terminal Runs only")
    if not isinstance(value["skills"], list) or not all(isinstance(v, str) for v in value["skills"]):
        raise ProgrammaticContextModelError("runtime.run_show output skills are invalid")
    if not isinstance(value["allowed_tools"], list) or not all(
        isinstance(v, str) for v in value["allowed_tools"]
    ):
        raise ProgrammaticContextModelError("runtime.run_show output allowed_tools are invalid")
    if not isinstance(value["resource_metrics"], dict):
        raise ProgrammaticContextModelError("runtime.run_show output resource_metrics are invalid")


def _decode_json_field(raw: object, label: str, expected: type) -> object:
    if not isinstance(raw, str):
        raise ProgrammaticContextModelError(f"{label} is not stored as JSON text")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProgrammaticContextModelError(f"{label} contains invalid JSON") from exc
    if not isinstance(value, expected):
        raise ProgrammaticContextModelError(f"{label} has unexpected JSON type")
    return value


def _project_terminal_run(runtime: OriginForgeRuntime, run_id: str) -> dict[str, object]:
    row = runtime.get_run(run_id)
    task_id = row.get("task_id")
    # OriginForgeRuntime.get_run can resolve task-less infrastructure runs. Phase 27
    # intentionally excludes them because there is no project ownership chain through
    # Goal/Flow/Task to revalidate.
    if not isinstance(task_id, str) or not validate_id(task_id, IdKind.TASK):
        raise ProgrammaticContextModelError(
            "runtime.run_show requires a task-scoped project Run"
        )
    runtime.get_task(task_id)
    if row.get("status") not in _TERMINAL_RUN_STATUSES:
        raise ProgrammaticContextModelError("runtime.run_show exposes terminal Runs only")
    result = {
        "id": row["id"],
        "task_id": task_id,
        "role": row.get("role"),
        "model_profile": row.get("model_profile"),
        "model_hash": row.get("model_hash"),
        "skills": _decode_json_field(row.get("skills_json"), "skills_json", list),
        "allowed_tools": _decode_json_field(
            row.get("allowed_tools_json"), "allowed_tools_json", list
        ),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "status": row.get("status"),
        "failure_reason": row.get("failure_reason"),
        "input_token_count": row.get("input_token_count"),
        "output_token_count": row.get("output_token_count"),
        "resource_metrics": _decode_json_field(
            row.get("resource_metrics_json"), "resource_metrics_json", dict
        ),
    }
    _validate_output(result)
    return result


def register_runtime_run_show_adapter(
    runtime: OriginForgeRuntime,
    registry: ContextAdapterRegistry,
) -> ContextOperationDescriptor:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if runtime.project_id() == "":  # pragma: no cover - project IDs are always non-empty
        raise ProgrammaticContextModelError("project must be initialized")
    descriptor = runtime_run_show_descriptor()

    def invoke(arguments: Mapping[str, object]) -> object:
        run_id = arguments["run_id"]
        assert isinstance(run_id, str)
        return _project_terminal_run(runtime, run_id)

    registry.register(
        descriptor,
        invoke,
        validate_input=_validate_input,
        validate_output=_validate_output,
    )
    return descriptor
