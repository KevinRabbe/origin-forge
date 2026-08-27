from __future__ import annotations

import re
from dataclasses import dataclass

from .ids import IdKind, validate_id


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 4096
IMAGE_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION = 1
IMAGE_EXECUTION_OWNER_ID = "originforge.execution.image.generate@1"


class ImageDispatchOutputBindingModelError(ValueError):
    pass


def _id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise ImageDispatchOutputBindingModelError(f"{label} must be a valid {kind.value} ID")
    return value


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ImageDispatchOutputBindingModelError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TEXT
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ImageDispatchOutputBindingModelError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class ImageDispatchOutput:
    relative_path: str
    artifact_id: str
    verification_id: str
    content_hash: str
    pixel_hash: str
    width: int
    height: int
    byte_count: int

    def __post_init__(self) -> None:
        _text(self.relative_path, "relative_path")
        if not self.relative_path.startswith("exports/") or not self.relative_path.lower().endswith(".png"):
            raise ImageDispatchOutputBindingModelError("relative_path must be a PNG under exports/")
        _id(self.artifact_id, IdKind.ARTIFACT, "artifact_id")
        _id(self.verification_id, IdKind.VERIFICATION, "verification_id")
        _hash(self.content_hash, "content_hash")
        _hash(self.pixel_hash, "pixel_hash")
        for value, label in ((self.width, "width"), (self.height, "height"), (self.byte_count, "byte_count")):
            if type(value) is not int or value <= 0:
                raise ImageDispatchOutputBindingModelError(f"{label} must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "artifact_id": self.artifact_id,
            "verification_id": self.verification_id,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "width": self.width,
            "height": self.height,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True)
class ImageDispatchOutputBinding:
    """Immutable relation between one image execution and all generated PNG outputs."""

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
    outputs: tuple[ImageDispatchOutput, ...]
    backend_result_hash: str
    schema_version: int
    created_at: str

    def __post_init__(self) -> None:
        _id(self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id")
        _id(self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id")
        _id(self.task_id, IdKind.TASK, "task_id")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise ImageDispatchOutputBindingModelError("task_revision must be non-negative")
        _hash(self.task_content_hash, "task_content_hash")
        _id(self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id")
        _hash(self.work_order_hash, "work_order_hash")
        _id(self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id")
        _hash(self.dispatch_binding_hash, "dispatch_binding_hash")
        if self.execution_owner_id != IMAGE_EXECUTION_OWNER_ID:
            raise ImageDispatchOutputBindingModelError("execution_owner_id is not the image owner")
        _id(self.run_id, IdKind.RUN, "run_id")
        _id(self.request_artifact_id, IdKind.ARTIFACT, "request_artifact_id")
        _id(self.result_artifact_id, IdKind.ARTIFACT, "result_artifact_id")
        if self.request_artifact_id == self.result_artifact_id:
            raise ImageDispatchOutputBindingModelError("request and result Artifacts must differ")
        outputs = tuple(self.outputs)
        if not outputs or len(outputs) > 4 or any(not isinstance(value, ImageDispatchOutput) for value in outputs):
            raise ImageDispatchOutputBindingModelError("outputs must contain 1..4 image outputs")
        if len({value.relative_path.casefold() for value in outputs}) != len(outputs):
            raise ImageDispatchOutputBindingModelError("image output paths must be distinct")
        if len({value.artifact_id for value in outputs}) != len(outputs):
            raise ImageDispatchOutputBindingModelError("image output Artifacts must be distinct")
        if len({value.verification_id for value in outputs}) != len(outputs):
            raise ImageDispatchOutputBindingModelError("image output Verifications must be distinct")
        object.__setattr__(self, "outputs", outputs)
        _hash(self.backend_result_hash, "backend_result_hash")
        if self.schema_version != IMAGE_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION:
            raise ImageDispatchOutputBindingModelError("unsupported image binding schema_version")
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
            "backend_result_hash": self.backend_result_hash,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }
