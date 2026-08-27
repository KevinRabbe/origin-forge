from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .ids import IdKind, validate_id

PLAYTEST_EXECUTION_OWNER_ID = "originforge.execution.playtest.cooperative@1"
PLAYTEST_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION = 1
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PlaytestDispatchOutputBindingModelError(ValueError):
    pass


def _id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise PlaytestDispatchOutputBindingModelError(f"{label} is invalid")
    return value


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise PlaytestDispatchOutputBindingModelError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class PlaytestDispatchOutputBinding:
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
    scenario_artifact_id: str
    telemetry_artifact_id: str
    summary_artifact_id: str
    stdout_artifact_id: str
    stderr_artifact_id: str
    telemetry_hash: str
    summary_json: str
    outcome: str
    timed_out: bool
    exit_code: int | None
    schema_version: int
    created_at: str

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id"),
            (self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id"),
            (self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id"),
            (self.run_id, IdKind.RUN, "run_id"),
            (self.scenario_artifact_id, IdKind.ARTIFACT, "scenario_artifact_id"),
            (self.telemetry_artifact_id, IdKind.ARTIFACT, "telemetry_artifact_id"),
            (self.summary_artifact_id, IdKind.ARTIFACT, "summary_artifact_id"),
            (self.stdout_artifact_id, IdKind.ARTIFACT, "stdout_artifact_id"),
            (self.stderr_artifact_id, IdKind.ARTIFACT, "stderr_artifact_id"),
        ):
            _id(value, kind, label)
        if self.execution_owner_id != PLAYTEST_EXECUTION_OWNER_ID:
            raise PlaytestDispatchOutputBindingModelError("playtest binding owner is invalid")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise PlaytestDispatchOutputBindingModelError("task_revision is invalid")
        for value, label in ((self.task_content_hash, "task_content_hash"), (self.work_order_hash, "work_order_hash"), (self.dispatch_binding_hash, "dispatch_binding_hash"), (self.telemetry_hash, "telemetry_hash")):
            _hash(value, label)
        if not isinstance(self.summary_json, str):
            raise PlaytestDispatchOutputBindingModelError("summary_json is invalid")
        try:
            if not isinstance(json.loads(self.summary_json), dict):
                raise TypeError
        except (TypeError, ValueError) as exc:
            raise PlaytestDispatchOutputBindingModelError("summary_json is not an object") from exc
        if not isinstance(self.outcome, str) or not self.outcome or type(self.timed_out) is not bool:
            raise PlaytestDispatchOutputBindingModelError("playtest result metadata is invalid")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise PlaytestDispatchOutputBindingModelError("exit_code is invalid")
        if self.schema_version != 1 or not isinstance(self.created_at, str) or not self.created_at:
            raise PlaytestDispatchOutputBindingModelError("binding metadata is invalid")
