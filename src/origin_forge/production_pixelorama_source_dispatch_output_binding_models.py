from __future__ import annotations

import re
from dataclasses import dataclass

from .ids import IdKind, validate_id
from .pixelorama_models import BridgeOutputType

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 512
PIXELORAMA_SOURCE_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION = 1
PIXELORAMA_SOURCE_EXECUTION_OWNER_ID = "originforge.execution.pixelorama.source-create@1"


class PixeloramaSourceOutputBindingModelError(ValueError):
    pass


def _id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise PixeloramaSourceOutputBindingModelError(
            f"{label} must be a valid {kind.value} ID"
        )
    return value


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise PixeloramaSourceOutputBindingModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TEXT
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise PixeloramaSourceOutputBindingModelError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class PixeloramaSourceDispatchOutput:
    output_type: BridgeOutputType
    relative_path: str
    artifact_id: str
    verification_id: str
    content_hash: str
    byte_count: int
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_type, BridgeOutputType):
            raise PixeloramaSourceOutputBindingModelError("output_type is invalid")
        _text(self.relative_path, "relative_path")
        if not self.relative_path.startswith(("project/", "exports/")):
            raise PixeloramaSourceOutputBindingModelError(
                "relative_path must stay under project/ or exports/"
            )
        _id(self.artifact_id, IdKind.ARTIFACT, "artifact_id")
        _id(self.verification_id, IdKind.VERIFICATION, "verification_id")
        _hash(self.content_hash, "content_hash")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise PixeloramaSourceOutputBindingModelError("byte_count must be non-negative")
        for value, label in ((self.width, "width"), (self.height, "height")):
            if value is not None and (type(value) is not int or value <= 0):
                raise PixeloramaSourceOutputBindingModelError(f"{label} must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "output_type": self.output_type.value,
            "relative_path": self.relative_path,
            "artifact_id": self.artifact_id,
            "verification_id": self.verification_id,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class PixeloramaSourceDispatchOutputBinding:
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
    outputs: tuple[PixeloramaSourceDispatchOutput, ...]
    run_verification_id: str
    backend_result_hash: str
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
            (self.request_artifact_id, IdKind.ARTIFACT, "request_artifact_id"),
            (self.result_artifact_id, IdKind.ARTIFACT, "result_artifact_id"),
            (self.run_verification_id, IdKind.VERIFICATION, "run_verification_id"),
        ):
            _id(value, kind, label)
        if self.execution_owner_id != PIXELORAMA_SOURCE_EXECUTION_OWNER_ID:
            raise PixeloramaSourceOutputBindingModelError("wrong execution owner")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise PixeloramaSourceOutputBindingModelError("task_revision is invalid")
        for value, label in (
            (self.task_content_hash, "task_content_hash"),
            (self.work_order_hash, "work_order_hash"),
            (self.dispatch_binding_hash, "dispatch_binding_hash"),
            (self.backend_result_hash, "backend_result_hash"),
        ):
            _hash(value, label)
        if self.request_artifact_id == self.result_artifact_id:
            raise PixeloramaSourceOutputBindingModelError("request/result artifacts must differ")
        outputs = tuple(self.outputs)
        if not outputs or len(outputs) > 64:
            raise PixeloramaSourceOutputBindingModelError("outputs must contain 1..64 values")
        if any(not isinstance(value, PixeloramaSourceDispatchOutput) for value in outputs):
            raise PixeloramaSourceOutputBindingModelError("outputs are invalid")
        if len({value.relative_path.casefold() for value in outputs}) != len(outputs):
            raise PixeloramaSourceOutputBindingModelError("output paths must be distinct")
        if len({value.artifact_id for value in outputs}) != len(outputs):
            raise PixeloramaSourceOutputBindingModelError("output artifacts must be distinct")
        object.__setattr__(self, "outputs", outputs)
        if self.schema_version != PIXELORAMA_SOURCE_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION:
            raise PixeloramaSourceOutputBindingModelError("unsupported schema version")
        _text(self.created_at, "created_at")

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
            "outputs": [value.to_dict() for value in self.outputs],
            "run_verification_id": self.run_verification_id,
            "backend_result_hash": self.backend_result_hash,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }
