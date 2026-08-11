from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_IDENTITY_TEXT = 256
_MAX_TIMESTAMP_CHARS = 128


class DispatchExecutionModelError(ValueError):
    pass


class DispatchExecutionStatus(StrEnum):
    STARTED = "STARTED"
    RETURNED = "RETURNED"
    RAISED = "RAISED"
    INTERRUPTED = "INTERRUPTED"


def _typed_id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise DispatchExecutionModelError(
            f"{label} must be a valid {kind.value} ID"
        )
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise DispatchExecutionModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _identity_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTITY_TEXT
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise DispatchExecutionModelError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TIMESTAMP_CHARS
        or value.strip() != value
    ):
        raise DispatchExecutionModelError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise DispatchExecutionModelError(
            f"{label} must be a non-negative integer"
        )
    return value


@dataclass(frozen=True)
class DispatchExecution:
    execution_id: str
    project_id: str
    claim_id: str
    claim_revision_at_start: int
    task_id: str
    task_revision: int
    task_content_hash: str
    work_order_id: str
    work_order_hash: str
    input_resolution_id: str
    input_resolution_hash: str
    dispatch_binding_id: str
    dispatch_binding_hash: str
    binding_audit_id: str
    binding_audit_hash: str
    selected_adapter_id: str
    selected_adapter_fingerprint: str
    dispatch_contract_id: str
    dispatch_contract_hash: str
    binder_id: str
    binder_fingerprint: str
    execution_owner_id: str
    execution_owner_fingerprint: str
    runtime_dependency_plan_hash: str
    status: DispatchExecutionStatus
    revision: int
    created_at: str
    updated_at: str
    terminal_detail_hash: str | None

    def __post_init__(self) -> None:
        _typed_id(self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id")
        _typed_id(self.project_id, IdKind.PROJECT, "project_id")
        _typed_id(self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id")
        _nonnegative_int(self.claim_revision_at_start, "claim_revision_at_start")
        _typed_id(self.task_id, IdKind.TASK, "task_id")
        _nonnegative_int(self.task_revision, "task_revision")
        _digest(self.task_content_hash, "task_content_hash")
        _typed_id(
            self.work_order_id,
            IdKind.PRODUCTION_WORK_ORDER,
            "work_order_id",
        )
        _digest(self.work_order_hash, "work_order_hash")
        _typed_id(
            self.input_resolution_id,
            IdKind.INPUT_RESOLUTION_BUNDLE,
            "input_resolution_id",
        )
        _digest(self.input_resolution_hash, "input_resolution_hash")
        _typed_id(
            self.dispatch_binding_id,
            IdKind.DISPATCH_BINDING,
            "dispatch_binding_id",
        )
        _digest(self.dispatch_binding_hash, "dispatch_binding_hash")
        _typed_id(
            self.binding_audit_id,
            IdKind.DISPATCH_BINDING_AUDIT,
            "binding_audit_id",
        )
        _digest(self.binding_audit_hash, "binding_audit_hash")
        _identity_text(self.selected_adapter_id, "selected_adapter_id")
        _digest(
            self.selected_adapter_fingerprint,
            "selected_adapter_fingerprint",
        )
        _identity_text(self.dispatch_contract_id, "dispatch_contract_id")
        _digest(self.dispatch_contract_hash, "dispatch_contract_hash")
        _identity_text(self.binder_id, "binder_id")
        _digest(self.binder_fingerprint, "binder_fingerprint")
        _identity_text(self.execution_owner_id, "execution_owner_id")
        _digest(
            self.execution_owner_fingerprint,
            "execution_owner_fingerprint",
        )
        _digest(
            self.runtime_dependency_plan_hash,
            "runtime_dependency_plan_hash",
        )
        if not isinstance(self.status, DispatchExecutionStatus):
            raise DispatchExecutionModelError(
                "status must be a DispatchExecutionStatus"
            )
        _nonnegative_int(self.revision, "revision")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.updated_at, "updated_at")
        if self.status is DispatchExecutionStatus.STARTED:
            if self.revision != 0:
                raise DispatchExecutionModelError(
                    "STARTED execution must have revision 0"
                )
            if self.terminal_detail_hash is not None:
                raise DispatchExecutionModelError(
                    "STARTED execution cannot have terminal_detail_hash"
                )
        else:
            if self.revision != 1:
                raise DispatchExecutionModelError(
                    "terminal execution must have revision 1"
                )
            _digest(self.terminal_detail_hash, "terminal_detail_hash")

    @property
    def is_started(self) -> bool:
        return self.status is DispatchExecutionStatus.STARTED

    @property
    def is_terminal(self) -> bool:
        return not self.is_started

    def frozen_authority_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "project_id": self.project_id,
            "claim_id": self.claim_id,
            "claim_revision_at_start": self.claim_revision_at_start,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "input_resolution_id": self.input_resolution_id,
            "input_resolution_hash": self.input_resolution_hash,
            "dispatch_binding_id": self.dispatch_binding_id,
            "dispatch_binding_hash": self.dispatch_binding_hash,
            "binding_audit_id": self.binding_audit_id,
            "binding_audit_hash": self.binding_audit_hash,
            "selected_adapter_id": self.selected_adapter_id,
            "selected_adapter_fingerprint": self.selected_adapter_fingerprint,
            "dispatch_contract_id": self.dispatch_contract_id,
            "dispatch_contract_hash": self.dispatch_contract_hash,
            "binder_id": self.binder_id,
            "binder_fingerprint": self.binder_fingerprint,
            "execution_owner_id": self.execution_owner_id,
            "execution_owner_fingerprint": self.execution_owner_fingerprint,
            "runtime_dependency_plan_hash": self.runtime_dependency_plan_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.frozen_authority_dict(),
            "status": self.status.value,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "terminal_detail_hash": self.terminal_detail_hash,
        }
