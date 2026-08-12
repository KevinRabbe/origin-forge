from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, new_id, validate_id


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_MAX_OBJECT_BYTES = 1024 * 1024
_MAX_REASON_CHARS = 4096
_MAX_TIMESTAMP_CHARS = 128
_MAX_MODEL_STRATEGY_ROLES = 16
_POLICY_SCHEMA_VERSION = 1


class ProductionPreparationModelError(ValueError):
    pass


class PreparationStage(StrEnum):
    CLAIMED = "CLAIMED"
    ACTIVATED = "ACTIVATED"
    ROUTED = "ROUTED"
    PLANNER_STARTED = "PLANNER_STARTED"
    PLANNER_RETURNED = "PLANNER_RETURNED"
    WORK_ORDER_AUDITED = "WORK_ORDER_AUDITED"
    BOUND = "BOUND"


class PreparationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    READY = "READY"
    INTERRUPTED = "INTERRUPTED"
    FAILED_PRE_PLANNER = "FAILED_PRE_PLANNER"


_STAGE_ORDER = {
    PreparationStage.CLAIMED: 0,
    PreparationStage.ACTIVATED: 1,
    PreparationStage.ROUTED: 2,
    PreparationStage.PLANNER_STARTED: 3,
    PreparationStage.PLANNER_RETURNED: 4,
    PreparationStage.WORK_ORDER_AUDITED: 5,
    PreparationStage.BOUND: 6,
}


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionPreparationModelError(
            "preparation data is not finite canonical JSON"
        ) from exc
    if not encoded or len(encoded) > _MAX_OBJECT_BYTES:
        raise ProductionPreparationModelError(
            "preparation object is outside byte bounds"
        )
    return encoded


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _typed_id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise ProductionPreparationModelError(
            f"{label} must be a valid {kind.value} ID"
        )
    return value


def _optional_typed_id(value: object, kind: IdKind, label: str) -> str | None:
    if value is None:
        return None
    return _typed_id(value, kind, label)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ProductionPreparationModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _optional_digest(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _digest(value, label)


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise ProductionPreparationModelError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProductionPreparationModelError(
            f"{label} must be a non-negative integer"
        )
    return value


def _optional_nonnegative_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, label)


def _timestamp(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TIMESTAMP_CHARS
        or value.strip() != value
    ):
        raise ProductionPreparationModelError(f"{label} is invalid")
    return value


def _checkpoint_pair(
    identifier: object,
    digest: object,
    kind: IdKind,
    id_label: str,
    hash_label: str,
) -> tuple[str | None, str | None]:
    if (identifier is None) != (digest is None):
        raise ProductionPreparationModelError(
            f"{id_label} and {hash_label} must appear together"
        )
    return (
        _optional_typed_id(identifier, kind, id_label),
        _optional_digest(digest, hash_label),
    )


@dataclass(frozen=True)
class TaskPreparationPolicyBinding:
    preparation_policy_id: str
    project_id: str
    materialization_id: str
    materialization_hash: str
    planning_input_id: str
    planning_input_hash: str
    capability_catalog_id: str
    capability_catalog_hash: str
    capability_routing_policy_id: str
    capability_routing_policy_hash: str
    dispatch_contract_catalog_id: str
    dispatch_contract_catalog_hash: str
    preparation_owner_id: str
    preparation_owner_fingerprint: str
    planner_request_version: str
    planner_contract_id: str
    model_strategy_roles: tuple[str, ...]
    schema_version: int = _POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _typed_id(
            self.preparation_policy_id,
            IdKind.TASK_PREPARATION_POLICY,
            "preparation_policy_id",
        )
        _typed_id(self.project_id, IdKind.PROJECT, "project_id")
        _typed_id(
            self.materialization_id,
            IdKind.PLAN_MATERIALIZATION,
            "materialization_id",
        )
        _digest(self.materialization_hash, "materialization_hash")
        _typed_id(self.planning_input_id, IdKind.PLANNING_INPUT, "planning_input_id")
        _digest(self.planning_input_hash, "planning_input_hash")
        _typed_id(
            self.capability_catalog_id,
            IdKind.CAPABILITY_CATALOG,
            "capability_catalog_id",
        )
        _digest(self.capability_catalog_hash, "capability_catalog_hash")
        _typed_id(
            self.capability_routing_policy_id,
            IdKind.CAPABILITY_ROUTING_POLICY,
            "capability_routing_policy_id",
        )
        _digest(
            self.capability_routing_policy_hash,
            "capability_routing_policy_hash",
        )
        _typed_id(
            self.dispatch_contract_catalog_id,
            IdKind.DISPATCH_CONTRACT_CATALOG,
            "dispatch_contract_catalog_id",
        )
        _digest(
            self.dispatch_contract_catalog_hash,
            "dispatch_contract_catalog_hash",
        )
        _identity(self.preparation_owner_id, "preparation_owner_id")
        _digest(
            self.preparation_owner_fingerprint,
            "preparation_owner_fingerprint",
        )
        _identity(self.planner_request_version, "planner_request_version")
        _identity(self.planner_contract_id, "planner_contract_id")
        roles = tuple(_identity(value, "model_strategy_role") for value in self.model_strategy_roles)
        if not roles or len(roles) > _MAX_MODEL_STRATEGY_ROLES:
            raise ProductionPreparationModelError(
                "model_strategy_roles are outside bounds"
            )
        if len(roles) != len(set(roles)):
            raise ProductionPreparationModelError(
                "model_strategy_roles contain duplicates"
            )
        object.__setattr__(self, "model_strategy_roles", roles)
        if type(self.schema_version) is not int or self.schema_version != _POLICY_SCHEMA_VERSION:
            raise ProductionPreparationModelError(
                "unsupported preparation policy schema_version"
            )
        _canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        materialization_id: str,
        materialization_hash: str,
        planning_input_id: str,
        planning_input_hash: str,
        capability_catalog_id: str,
        capability_catalog_hash: str,
        capability_routing_policy_id: str,
        capability_routing_policy_hash: str,
        dispatch_contract_catalog_id: str,
        dispatch_contract_catalog_hash: str,
        preparation_owner_id: str,
        preparation_owner_fingerprint: str,
        planner_request_version: str,
        planner_contract_id: str,
        model_strategy_roles: tuple[str, ...],
    ) -> "TaskPreparationPolicyBinding":
        return cls(
            preparation_policy_id=new_id(IdKind.TASK_PREPARATION_POLICY),
            project_id=project_id,
            materialization_id=materialization_id,
            materialization_hash=materialization_hash,
            planning_input_id=planning_input_id,
            planning_input_hash=planning_input_hash,
            capability_catalog_id=capability_catalog_id,
            capability_catalog_hash=capability_catalog_hash,
            capability_routing_policy_id=capability_routing_policy_id,
            capability_routing_policy_hash=capability_routing_policy_hash,
            dispatch_contract_catalog_id=dispatch_contract_catalog_id,
            dispatch_contract_catalog_hash=dispatch_contract_catalog_hash,
            preparation_owner_id=preparation_owner_id,
            preparation_owner_fingerprint=preparation_owner_fingerprint,
            planner_request_version=planner_request_version,
            planner_contract_id=planner_contract_id,
            model_strategy_roles=model_strategy_roles,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "preparation_policy_id": self.preparation_policy_id,
            "project_id": self.project_id,
            "materialization_id": self.materialization_id,
            "materialization_hash": self.materialization_hash,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "capability_catalog_id": self.capability_catalog_id,
            "capability_catalog_hash": self.capability_catalog_hash,
            "capability_routing_policy_id": self.capability_routing_policy_id,
            "capability_routing_policy_hash": self.capability_routing_policy_hash,
            "dispatch_contract_catalog_id": self.dispatch_contract_catalog_id,
            "dispatch_contract_catalog_hash": self.dispatch_contract_catalog_hash,
            "preparation_owner_id": self.preparation_owner_id,
            "preparation_owner_fingerprint": self.preparation_owner_fingerprint,
            "planner_request_version": self.planner_request_version,
            "planner_contract_id": self.planner_contract_id,
            "model_strategy_roles": list(self.model_strategy_roles),
            "schema_version": self.schema_version,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self.to_dict())


@dataclass(frozen=True)
class TaskPreparationReceipt:
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
    queued_task_hash: str
    ready_task_revision: int | None
    ready_task_hash: str | None
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
    stage: PreparationStage
    status: PreparationStatus
    revision: int
    created_at: str
    updated_at: str
    terminal_reason: str | None

    def __post_init__(self) -> None:
        _typed_id(self.preparation_id, IdKind.TASK_PREPARATION, "preparation_id")
        _typed_id(self.project_id, IdKind.PROJECT, "project_id")
        _typed_id(
            self.preparation_policy_id,
            IdKind.TASK_PREPARATION_POLICY,
            "preparation_policy_id",
        )
        _digest(self.preparation_policy_hash, "preparation_policy_hash")
        _typed_id(
            self.materialization_id,
            IdKind.PLAN_MATERIALIZATION,
            "materialization_id",
        )
        _digest(self.materialization_hash, "materialization_hash")
        _typed_id(self.planning_input_id, IdKind.PLANNING_INPUT, "planning_input_id")
        _digest(self.planning_input_hash, "planning_input_hash")
        _typed_id(self.task_id, IdKind.TASK, "task_id")
        _nonnegative_int(self.queued_task_revision, "queued_task_revision")
        _digest(self.queued_task_hash, "queued_task_hash")
        _optional_nonnegative_int(self.ready_task_revision, "ready_task_revision")
        _optional_digest(self.ready_task_hash, "ready_task_hash")
        if (self.ready_task_revision is None) != (self.ready_task_hash is None):
            raise ProductionPreparationModelError(
                "ready_task_revision and ready_task_hash must appear together"
            )
        _checkpoint_pair(
            self.route_decision_id,
            self.route_decision_hash,
            IdKind.CAPABILITY_ROUTE_DECISION,
            "route_decision_id",
            "route_decision_hash",
        )
        _optional_digest(
            self.planner_dependency_plan_hash,
            "planner_dependency_plan_hash",
        )
        _optional_typed_id(self.planner_run_id, IdKind.RUN, "planner_run_id")
        _checkpoint_pair(
            self.work_order_id,
            self.work_order_hash,
            IdKind.PRODUCTION_WORK_ORDER,
            "work_order_id",
            "work_order_hash",
        )
        _checkpoint_pair(
            self.work_order_audit_id,
            self.work_order_audit_hash,
            IdKind.WORK_ORDER_AUDIT,
            "work_order_audit_id",
            "work_order_audit_hash",
        )
        _checkpoint_pair(
            self.input_resolution_id,
            self.input_resolution_hash,
            IdKind.INPUT_RESOLUTION_BUNDLE,
            "input_resolution_id",
            "input_resolution_hash",
        )
        _checkpoint_pair(
            self.dispatch_binding_id,
            self.dispatch_binding_hash,
            IdKind.DISPATCH_BINDING,
            "dispatch_binding_id",
            "dispatch_binding_hash",
        )
        _checkpoint_pair(
            self.binding_audit_id,
            self.binding_audit_hash,
            IdKind.DISPATCH_BINDING_AUDIT,
            "binding_audit_id",
            "binding_audit_hash",
        )
        if not isinstance(self.stage, PreparationStage):
            raise ProductionPreparationModelError("stage must be a PreparationStage")
        if not isinstance(self.status, PreparationStatus):
            raise ProductionPreparationModelError("status must be a PreparationStatus")
        _nonnegative_int(self.revision, "revision")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.updated_at, "updated_at")
        self._validate_checkpoint_shape()
        self._validate_terminal_shape()

    def _validate_checkpoint_shape(self) -> None:
        rank = _STAGE_ORDER[self.stage]
        checkpoint_presence = (
            (
                PreparationStage.ACTIVATED,
                self.ready_task_revision is not None and self.ready_task_hash is not None,
                "ready Task checkpoint",
            ),
            (
                PreparationStage.ROUTED,
                self.route_decision_id is not None and self.route_decision_hash is not None,
                "route checkpoint",
            ),
            (
                PreparationStage.PLANNER_STARTED,
                self.planner_dependency_plan_hash is not None,
                "planner dependency checkpoint",
            ),
            (
                PreparationStage.PLANNER_RETURNED,
                self.planner_run_id is not None
                and self.work_order_id is not None
                and self.work_order_hash is not None,
                "planner return checkpoint",
            ),
            (
                PreparationStage.WORK_ORDER_AUDITED,
                self.work_order_audit_id is not None
                and self.work_order_audit_hash is not None,
                "WorkOrder audit checkpoint",
            ),
            (
                PreparationStage.BOUND,
                self.input_resolution_id is not None
                and self.input_resolution_hash is not None
                and self.dispatch_binding_id is not None
                and self.dispatch_binding_hash is not None
                and self.binding_audit_id is not None
                and self.binding_audit_hash is not None,
                "Phase-34 binding checkpoint",
            ),
        )
        for checkpoint_stage, present, label in checkpoint_presence:
            expected = rank >= _STAGE_ORDER[checkpoint_stage]
            if present != expected:
                relation = "requires" if expected else "cannot contain"
                raise ProductionPreparationModelError(
                    f"{self.stage.value} {relation} {label}"
                )

    def _validate_terminal_shape(self) -> None:
        if self.status in (PreparationStatus.ACTIVE, PreparationStatus.READY):
            if self.terminal_reason is not None:
                raise ProductionPreparationModelError(
                    f"{self.status.value} preparation cannot have terminal_reason"
                )
        else:
            if (
                not isinstance(self.terminal_reason, str)
                or not self.terminal_reason
                or self.terminal_reason.strip() != self.terminal_reason
                or len(self.terminal_reason) > _MAX_REASON_CHARS
            ):
                raise ProductionPreparationModelError(
                    "terminal failed/interrupted preparation requires bounded terminal_reason"
                )
        if self.status is PreparationStatus.READY and self.stage is not PreparationStage.BOUND:
            raise ProductionPreparationModelError(
                "READY preparation must be at BOUND stage"
            )
        if self.status is PreparationStatus.FAILED_PRE_PLANNER and _STAGE_ORDER[self.stage] >= _STAGE_ORDER[PreparationStage.PLANNER_STARTED]:
            raise ProductionPreparationModelError(
                "FAILED_PRE_PLANNER cannot cross PLANNER_STARTED"
            )

    @property
    def is_active(self) -> bool:
        return self.status is PreparationStatus.ACTIVE

    @property
    def requires_planner_recovery(self) -> bool:
        return (
            self.status is PreparationStatus.ACTIVE
            and self.stage is PreparationStage.PLANNER_STARTED
        )

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
            "queued_task_hash": self.queued_task_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.frozen_authority_dict(),
            "ready_task_revision": self.ready_task_revision,
            "ready_task_hash": self.ready_task_hash,
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