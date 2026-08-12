from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_MAX_REASON_CHARS = 4096
_MAX_TIMESTAMP_CHARS = 128


class TaskPreparationModelError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TaskPreparationModelError("preparation data is not canonical JSON") from exc


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _typed_id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise TaskPreparationModelError(f"{label} must be a valid {kind.value} ID")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise TaskPreparationModelError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise TaskPreparationModelError(f"{label} must be a bounded identity token")
    return value


def _revision(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise TaskPreparationModelError(f"{label} must be a non-negative integer")
    return value


def _timestamp(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > _MAX_TIMESTAMP_CHARS
    ):
        raise TaskPreparationModelError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class PreparationPolicy:
    preparation_policy_id: str
    materialization_id: str
    materialization_hash: str
    planning_input_id: str
    planning_input_hash: str
    capability_catalog_id: str
    capability_catalog_hash: str
    routing_policy_id: str
    routing_policy_hash: str
    dispatch_catalog_id: str
    dispatch_catalog_hash: str
    preparation_owner_id: str
    preparation_owner_fingerprint: str
    planner_contract_id: str
    model_strategy_roles: tuple[str, ...]
    policy_version: str = "1"

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.preparation_policy_id, IdKind.PREPARATION_POLICY, "preparation_policy_id"),
            (self.materialization_id, IdKind.PLAN_MATERIALIZATION, "materialization_id"),
            (self.planning_input_id, IdKind.PLANNING_INPUT, "planning_input_id"),
            (self.capability_catalog_id, IdKind.CAPABILITY_CATALOG, "capability_catalog_id"),
            (self.routing_policy_id, IdKind.CAPABILITY_ROUTING_POLICY, "routing_policy_id"),
            (self.dispatch_catalog_id, IdKind.DISPATCH_CONTRACT_CATALOG, "dispatch_catalog_id"),
        ):
            _typed_id(value, kind, label)
        for value, label in (
            (self.materialization_hash, "materialization_hash"),
            (self.planning_input_hash, "planning_input_hash"),
            (self.capability_catalog_hash, "capability_catalog_hash"),
            (self.routing_policy_hash, "routing_policy_hash"),
            (self.dispatch_catalog_hash, "dispatch_catalog_hash"),
            (self.preparation_owner_fingerprint, "preparation_owner_fingerprint"),
        ):
            _digest(value, label)
        _token(self.preparation_owner_id, "preparation_owner_id")
        _token(self.planner_contract_id, "planner_contract_id")
        _token(self.policy_version, "policy_version")
        roles = tuple(_token(value, "model_strategy_role") for value in self.model_strategy_roles)
        if not roles or len(roles) > 8 or len(roles) != len(set(roles)):
            raise TaskPreparationModelError("model_strategy_roles are outside bounds")
        object.__setattr__(self, "model_strategy_roles", roles)
        _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "preparation_policy_id": self.preparation_policy_id,
            "materialization_id": self.materialization_id,
            "materialization_hash": self.materialization_hash,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "capability_catalog_id": self.capability_catalog_id,
            "capability_catalog_hash": self.capability_catalog_hash,
            "routing_policy_id": self.routing_policy_id,
            "routing_policy_hash": self.routing_policy_hash,
            "dispatch_catalog_id": self.dispatch_catalog_id,
            "dispatch_catalog_hash": self.dispatch_catalog_hash,
            "preparation_owner_id": self.preparation_owner_id,
            "preparation_owner_fingerprint": self.preparation_owner_fingerprint,
            "planner_contract_id": self.planner_contract_id,
            "model_strategy_roles": list(self.model_strategy_roles),
            "policy_version": self.policy_version,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self.to_dict())


class TaskPreparationStage(StrEnum):
    CLAIMED = "CLAIMED"
    ACTIVATED = "ACTIVATED"
    ROUTED = "ROUTED"
    PLANNER_STARTED = "PLANNER_STARTED"
    PLANNER_RETURNED = "PLANNER_RETURNED"
    WORK_ORDER_AUDITED = "WORK_ORDER_AUDITED"
    BOUND = "BOUND"


class TaskPreparationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    READY = "READY"
    INTERRUPTED = "INTERRUPTED"
    FAILED_PRE_PLANNER = "FAILED_PRE_PLANNER"


_STAGE_ORDER = {
    TaskPreparationStage.CLAIMED: 0,
    TaskPreparationStage.ACTIVATED: 1,
    TaskPreparationStage.ROUTED: 2,
    TaskPreparationStage.PLANNER_STARTED: 3,
    TaskPreparationStage.PLANNER_RETURNED: 4,
    TaskPreparationStage.WORK_ORDER_AUDITED: 5,
    TaskPreparationStage.BOUND: 6,
}


@dataclass(frozen=True)
class TaskPreparation:
    preparation_id: str
    project_id: str
    preparation_policy_id: str
    preparation_policy_hash: str
    materialization_id: str
    materialization_hash: str
    planning_input_id: str
    planning_input_hash: str
    task_id: str
    queued_task_revision: int
    queued_task_content_hash: str
    ready_task_revision: int | None
    ready_task_content_hash: str | None
    route_decision_id: str | None
    route_decision_hash: str | None
    planner_dependency_plan_hash: str | None
    planner_run_id: str | None
    work_order_id: str | None
    work_order_hash: str | None
    work_order_audit_id: str | None
    work_order_audit_hash: str | None
    input_resolution_id: str | None
    input_resolution_hash: str | None
    dispatch_binding_id: str | None
    dispatch_binding_hash: str | None
    binding_audit_id: str | None
    binding_audit_hash: str | None
    stage: TaskPreparationStage
    status: TaskPreparationStatus
    revision: int
    created_at: str
    updated_at: str
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.preparation_id, IdKind.TASK_PREPARATION, "preparation_id"),
            (self.project_id, IdKind.PROJECT, "project_id"),
            (self.preparation_policy_id, IdKind.PREPARATION_POLICY, "preparation_policy_id"),
            (self.materialization_id, IdKind.PLAN_MATERIALIZATION, "materialization_id"),
            (self.planning_input_id, IdKind.PLANNING_INPUT, "planning_input_id"),
            (self.task_id, IdKind.TASK, "task_id"),
        ):
            _typed_id(value, kind, label)
        for value, label in (
            (self.preparation_policy_hash, "preparation_policy_hash"),
            (self.materialization_hash, "materialization_hash"),
            (self.planning_input_hash, "planning_input_hash"),
            (self.queued_task_content_hash, "queued_task_content_hash"),
        ):
            _digest(value, label)
        _revision(self.queued_task_revision, "queued_task_revision")
        _revision(self.revision, "revision")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.updated_at, "updated_at")
        if not isinstance(self.stage, TaskPreparationStage):
            raise TaskPreparationModelError("stage must be a TaskPreparationStage")
        if not isinstance(self.status, TaskPreparationStatus):
            raise TaskPreparationModelError("status must be a TaskPreparationStatus")

        self._validate_checkpoint(
            TaskPreparationStage.ACTIVATED,
            (
                (self.ready_task_revision, None, "ready_task_revision"),
                (self.ready_task_content_hash, "hash", "ready_task_content_hash"),
            ),
        )
        self._validate_checkpoint(
            TaskPreparationStage.ROUTED,
            (
                (self.route_decision_id, IdKind.CAPABILITY_ROUTE_DECISION, "route_decision_id"),
                (self.route_decision_hash, "hash", "route_decision_hash"),
            ),
        )
        self._validate_checkpoint(
            TaskPreparationStage.PLANNER_STARTED,
            ((self.planner_dependency_plan_hash, "hash", "planner_dependency_plan_hash"),),
        )
        self._validate_checkpoint(
            TaskPreparationStage.PLANNER_RETURNED,
            (
                (self.planner_run_id, IdKind.RUN, "planner_run_id"),
                (self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id"),
                (self.work_order_hash, "hash", "work_order_hash"),
            ),
        )
        self._validate_checkpoint(
            TaskPreparationStage.WORK_ORDER_AUDITED,
            (
                (self.work_order_audit_id, IdKind.WORK_ORDER_AUDIT, "work_order_audit_id"),
                (self.work_order_audit_hash, "hash", "work_order_audit_hash"),
            ),
        )
        self._validate_checkpoint(
            TaskPreparationStage.BOUND,
            (
                (self.input_resolution_id, IdKind.INPUT_RESOLUTION_BUNDLE, "input_resolution_id"),
                (self.input_resolution_hash, "hash", "input_resolution_hash"),
                (self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id"),
                (self.dispatch_binding_hash, "hash", "dispatch_binding_hash"),
                (self.binding_audit_id, IdKind.DISPATCH_BINDING_AUDIT, "binding_audit_id"),
                (self.binding_audit_hash, "hash", "binding_audit_hash"),
            ),
        )

        if self.ready_task_revision is not None:
            _revision(self.ready_task_revision, "ready_task_revision")
            if self.ready_task_revision <= self.queued_task_revision:
                raise TaskPreparationModelError(
                    "ready_task_revision must advance queued_task_revision"
                )

        if self.status is TaskPreparationStatus.ACTIVE:
            if self.terminal_reason is not None:
                raise TaskPreparationModelError("ACTIVE preparation cannot have terminal_reason")
        elif self.status is TaskPreparationStatus.READY:
            if self.stage is not TaskPreparationStage.BOUND:
                raise TaskPreparationModelError("READY preparation requires BOUND stage")
            if self.terminal_reason is not None:
                raise TaskPreparationModelError("READY preparation cannot have terminal_reason")
        else:
            if (
                not isinstance(self.terminal_reason, str)
                or not self.terminal_reason
                or self.terminal_reason.strip() != self.terminal_reason
                or len(self.terminal_reason) > _MAX_REASON_CHARS
            ):
                raise TaskPreparationModelError(
                    "terminal unsuccessful preparation requires bounded terminal_reason"
                )
        if (
            self.status is TaskPreparationStatus.FAILED_PRE_PLANNER
            and _STAGE_ORDER[self.stage] >= _STAGE_ORDER[TaskPreparationStage.PLANNER_STARTED]
        ):
            raise TaskPreparationModelError(
                "FAILED_PRE_PLANNER cannot be used after PLANNER_STARTED"
            )

    def _validate_checkpoint(
        self,
        required_stage: TaskPreparationStage,
        values: tuple[tuple[object, object, str], ...],
    ) -> None:
        reached = _STAGE_ORDER[self.stage] >= _STAGE_ORDER[required_stage]
        present = [value is not None for value, _, _ in values]
        if reached and not all(present):
            raise TaskPreparationModelError(
                f"{required_stage.value} checkpoint fields are incomplete"
            )
        if not reached and any(present):
            raise TaskPreparationModelError(
                f"{required_stage.value} checkpoint fields appeared before stage"
            )
        if not reached:
            return
        for value, validator, label in values:
            if validator is None:
                _revision(value, label)
            elif validator == "hash":
                _digest(value, label)
            else:
                _typed_id(value, validator, label)

    def frozen_authority_dict(self) -> dict[str, object]:
        return {
            "preparation_id": self.preparation_id,
            "project_id": self.project_id,
            "preparation_policy_id": self.preparation_policy_id,
            "preparation_policy_hash": self.preparation_policy_hash,
            "materialization_id": self.materialization_id,
            "materialization_hash": self.materialization_hash,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "task_id": self.task_id,
            "queued_task_revision": self.queued_task_revision,
            "queued_task_content_hash": self.queued_task_content_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.frozen_authority_dict(),
            "ready_task_revision": self.ready_task_revision,
            "ready_task_content_hash": self.ready_task_content_hash,
            "route_decision_id": self.route_decision_id,
            "route_decision_hash": self.route_decision_hash,
            "planner_dependency_plan_hash": self.planner_dependency_plan_hash,
            "planner_run_id": self.planner_run_id,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "work_order_audit_id": self.work_order_audit_id,
            "work_order_audit_hash": self.work_order_audit_hash,
            "input_resolution_id": self.input_resolution_id,
            "input_resolution_hash": self.input_resolution_hash,
            "dispatch_binding_id": self.dispatch_binding_id,
            "dispatch_binding_hash": self.dispatch_binding_hash,
            "binding_audit_id": self.binding_audit_id,
            "binding_audit_hash": self.binding_audit_hash,
            "stage": self.stage.value,
            "status": self.status.value,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "terminal_reason": self.terminal_reason,
        }
