from __future__ import annotations

import re
from dataclasses import dataclass

from .ids import IdKind, validate_id


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_IDENTITY_TEXT = 256
_MAX_TIMESTAMP_CHARS = 128
PIXELORAMA_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION = 1
PIXELORAMA_EXECUTION_OWNER_ID = "originforge.execution.pixelorama.spritesheet-export@1"


class PixeloramaDispatchOutputBindingModelError(ValueError):
    pass


def _typed_id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise PixeloramaDispatchOutputBindingModelError(
            f"{label} must be a valid {kind.value} ID"
        )
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise PixeloramaDispatchOutputBindingModelError(
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
        raise PixeloramaDispatchOutputBindingModelError(f"{label} is invalid")
    return value


def _timestamp(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TIMESTAMP_CHARS
        or value.strip() != value
    ):
        raise PixeloramaDispatchOutputBindingModelError("created_at is invalid")
    return value


@dataclass(frozen=True)
class PixeloramaDispatchOutputBinding:
    """Immutable one-to-one relation between one DISPEXEC and one Pixelorama output."""

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
    request_artifact_id: str
    result_artifact_id: str
    output_artifact_id: str
    output_verification_id: str
    run_verification_id: str
    output_content_hash: str
    output_byte_count: int
    schema_version: int
    created_at: str

    def __post_init__(self) -> None:
        _typed_id(self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id")
        _typed_id(self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id")
        _typed_id(self.task_id, IdKind.TASK, "task_id")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise PixeloramaDispatchOutputBindingModelError(
                "task_revision must be a non-negative integer"
            )
        _digest(self.task_content_hash, "task_content_hash")
        _typed_id(self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id")
        _digest(self.work_order_hash, "work_order_hash")
        _typed_id(
            self.dispatch_binding_id,
            IdKind.DISPATCH_BINDING,
            "dispatch_binding_id",
        )
        _digest(self.dispatch_binding_hash, "dispatch_binding_hash")
        _identity_text(self.execution_owner_id, "execution_owner_id")
        if self.execution_owner_id != PIXELORAMA_EXECUTION_OWNER_ID:
            raise PixeloramaDispatchOutputBindingModelError(
                "execution_owner_id is not the reviewed Pixelorama execution owner"
            )
        _typed_id(self.run_id, IdKind.RUN, "run_id")
        _typed_id(self.request_artifact_id, IdKind.ARTIFACT, "request_artifact_id")
        _typed_id(self.result_artifact_id, IdKind.ARTIFACT, "result_artifact_id")
        _typed_id(self.output_artifact_id, IdKind.ARTIFACT, "output_artifact_id")
        _typed_id(
            self.output_verification_id,
            IdKind.VERIFICATION,
            "output_verification_id",
        )
        _typed_id(
            self.run_verification_id,
            IdKind.VERIFICATION,
            "run_verification_id",
        )
        artifact_ids = {
            self.request_artifact_id,
            self.result_artifact_id,
            self.output_artifact_id,
        }
        if len(artifact_ids) != 3:
            raise PixeloramaDispatchOutputBindingModelError(
                "request/result/output Artifact IDs must be distinct"
            )
        if self.output_verification_id == self.run_verification_id:
            raise PixeloramaDispatchOutputBindingModelError(
                "output/run Verification IDs must be distinct"
            )
        _digest(self.output_content_hash, "output_content_hash")
        if type(self.output_byte_count) is not int or self.output_byte_count < 0:
            raise PixeloramaDispatchOutputBindingModelError(
                "output_byte_count must be a non-negative integer"
            )
        if self.schema_version != PIXELORAMA_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION:
            raise PixeloramaDispatchOutputBindingModelError(
                "unsupported Pixelorama dispatch-output binding schema_version"
            )
        _timestamp(self.created_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "dispatch_binding_id": self.dispatch_binding_id,
            "dispatch_binding_hash": self.dispatch_binding_hash,
            "execution_owner_id": self.execution_owner_id,
            "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "output_artifact_id": self.output_artifact_id,
            "output_verification_id": self.output_verification_id,
            "run_verification_id": self.run_verification_id,
            "output_content_hash": self.output_content_hash,
            "output_byte_count": self.output_byte_count,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }
