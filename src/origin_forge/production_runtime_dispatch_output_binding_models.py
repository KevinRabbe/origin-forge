from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .ids import IdKind, validate_id

RUNTIME_EXECUTION_OWNER_ID = "originforge.execution.runtime.observe@1"
RUNTIME_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION = 1
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class RuntimeDispatchOutputBindingModelError(ValueError):
    pass


def _id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise RuntimeDispatchOutputBindingModelError(f"{label} is invalid")
    return value


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise RuntimeDispatchOutputBindingModelError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class RuntimeDispatchCapture:
    capture_id: str
    artifact_id: str
    integrity_verification_id: str
    visual_verification_id: str | None
    relative_path: str
    content_hash: str
    pixel_hash: str
    byte_count: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if not isinstance(self.capture_id, str) or not self.capture_id:
            raise RuntimeDispatchOutputBindingModelError("capture_id is invalid")
        _id(self.artifact_id, IdKind.ARTIFACT, "capture artifact_id")
        _id(self.integrity_verification_id, IdKind.VERIFICATION, "integrity_verification_id")
        if self.visual_verification_id is not None:
            _id(self.visual_verification_id, IdKind.VERIFICATION, "visual_verification_id")
        path = PurePosixPath(self.relative_path)
        if (
            path.is_absolute()
            or self.relative_path != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
            or not self.relative_path.startswith("captures/")
        ):
            raise RuntimeDispatchOutputBindingModelError("capture relative_path is unsafe")
        _hash(self.content_hash, "capture content_hash")
        _hash(self.pixel_hash, "capture pixel_hash")
        for value, label in ((self.byte_count, "byte_count"), (self.width, "width"), (self.height, "height")):
            if type(value) is not int or value <= 0:
                raise RuntimeDispatchOutputBindingModelError(f"capture {label} is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "capture_id": self.capture_id,
            "artifact_id": self.artifact_id,
            "integrity_verification_id": self.integrity_verification_id,
            "visual_verification_id": self.visual_verification_id,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class RuntimeDispatchOutputBinding:
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
    stdout_artifact_id: str
    stderr_artifact_id: str
    captures: tuple[RuntimeDispatchCapture, ...]
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
            (self.stdout_artifact_id, IdKind.ARTIFACT, "stdout_artifact_id"),
            (self.stderr_artifact_id, IdKind.ARTIFACT, "stderr_artifact_id"),
        ):
            _id(value, kind, label)
        if self.execution_owner_id != RUNTIME_EXECUTION_OWNER_ID:
            raise RuntimeDispatchOutputBindingModelError("runtime binding owner is not runtime observation")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise RuntimeDispatchOutputBindingModelError("task_revision is invalid")
        for value, label in ((self.task_content_hash, "task_content_hash"), (self.work_order_hash, "work_order_hash"), (self.dispatch_binding_hash, "dispatch_binding_hash"), (self.backend_result_hash, "backend_result_hash")):
            _hash(value, label)
        captures = tuple(self.captures)
        if len({value.capture_id for value in captures}) != len(captures):
            raise RuntimeDispatchOutputBindingModelError("runtime captures contain duplicate IDs")
        if len({value.artifact_id for value in captures}) != len(captures):
            raise RuntimeDispatchOutputBindingModelError("runtime captures contain duplicate Artifacts")
        object.__setattr__(self, "captures", captures)
        if self.schema_version != RUNTIME_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION or not isinstance(self.created_at, str) or not self.created_at:
            raise RuntimeDispatchOutputBindingModelError("runtime binding metadata is invalid")

    @property
    def captures_json(self) -> str:
        return json.dumps([value.to_dict() for value in self.captures], ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id, "claim_id": self.claim_id, "task_id": self.task_id,
            "task_revision": self.task_revision, "task_content_hash": self.task_content_hash,
            "work_order_id": self.work_order_id, "work_order_hash": self.work_order_hash,
            "dispatch_binding_id": self.dispatch_binding_id, "dispatch_binding_hash": self.dispatch_binding_hash,
            "execution_owner_id": self.execution_owner_id, "run_id": self.run_id,
            "request_artifact_id": self.request_artifact_id, "result_artifact_id": self.result_artifact_id,
            "stdout_artifact_id": self.stdout_artifact_id, "stderr_artifact_id": self.stderr_artifact_id,
            "captures": [value.to_dict() for value in self.captures],
            "backend_result_hash": self.backend_result_hash, "schema_version": self.schema_version,
            "created_at": self.created_at,
        }
