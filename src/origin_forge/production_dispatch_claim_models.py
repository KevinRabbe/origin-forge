from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_IDENTITY_TEXT = 256
_MAX_REASON_CHARS = 4096
_MAX_TIMESTAMP_CHARS = 128


class DispatchClaimModelError(ValueError):
    pass


class DispatchClaimStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    INTERRUPTED = "INTERRUPTED"


def _exact_nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise DispatchClaimModelError(f"{label} must be a non-negative integer")
    return value


def _typed_id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise DispatchClaimModelError(f"{label} must be a valid {kind.value} ID")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise DispatchClaimModelError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _identity_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTITY_TEXT
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise DispatchClaimModelError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TIMESTAMP_CHARS
        or value.strip() != value
    ):
        raise DispatchClaimModelError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class DispatchClaim:
    claim_id: str
    project_id: str
    task_id: str
    task_revision: int
    task_content_hash: str
    work_order_id: str
    work_order_hash: str
    work_order_audit_id: str
    work_order_audit_hash: str
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
    status: DispatchClaimStatus
    revision: int
    created_at: str
    updated_at: str
    terminal_reason: str | None

    def __post_init__(self) -> None:
        _typed_id(self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id")
        _typed_id(self.project_id, IdKind.PROJECT, "project_id")
        _typed_id(self.task_id, IdKind.TASK, "task_id")
        _exact_nonnegative_int(self.task_revision, "task_revision")
        _digest(self.task_content_hash, "task_content_hash")
        _typed_id(self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id")
        _digest(self.work_order_hash, "work_order_hash")
        _typed_id(self.work_order_audit_id, IdKind.WORK_ORDER_AUDIT, "work_order_audit_id")
        _digest(self.work_order_audit_hash, "work_order_audit_hash")
        _typed_id(self.input_resolution_id, IdKind.INPUT_RESOLUTION_BUNDLE, "input_resolution_id")
        _digest(self.input_resolution_hash, "input_resolution_hash")
        _typed_id(self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id")
        _digest(self.dispatch_binding_hash, "dispatch_binding_hash")
        _typed_id(self.binding_audit_id, IdKind.DISPATCH_BINDING_AUDIT, "binding_audit_id")
        _digest(self.binding_audit_hash, "binding_audit_hash")
        _identity_text(self.selected_adapter_id, "selected_adapter_id")
        _digest(self.selected_adapter_fingerprint, "selected_adapter_fingerprint")
        _identity_text(self.dispatch_contract_id, "dispatch_contract_id")
        _digest(self.dispatch_contract_hash, "dispatch_contract_hash")
        _identity_text(self.binder_id, "binder_id")
        _digest(self.binder_fingerprint, "binder_fingerprint")
        if not isinstance(self.status, DispatchClaimStatus):
            raise DispatchClaimModelError("status must be a DispatchClaimStatus")
        _exact_nonnegative_int(self.revision, "revision")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.updated_at, "updated_at")
        if self.status is DispatchClaimStatus.ACTIVE:
            if self.terminal_reason is not None:
                raise DispatchClaimModelError("ACTIVE claim cannot have terminal_reason")
        else:
            if (
                not isinstance(self.terminal_reason, str)
                or not self.terminal_reason.strip()
                or len(self.terminal_reason) > _MAX_REASON_CHARS
                or self.terminal_reason.strip() != self.terminal_reason
            ):
                raise DispatchClaimModelError(
                    "terminal claim requires bounded non-empty terminal_reason"
                )

    @property
    def is_active(self) -> bool:
        return self.status is DispatchClaimStatus.ACTIVE

    def frozen_authority_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
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
            "selected_adapter_id": self.selected_adapter_id,
            "selected_adapter_fingerprint": self.selected_adapter_fingerprint,
            "dispatch_contract_id": self.dispatch_contract_id,
            "dispatch_contract_hash": self.dispatch_contract_hash,
            "binder_id": self.binder_id,
            "binder_fingerprint": self.binder_fingerprint,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.frozen_authority_dict(),
            "status": self.status.value,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "terminal_reason": self.terminal_reason,
        }
