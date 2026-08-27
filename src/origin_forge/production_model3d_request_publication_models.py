from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .ids import IdKind, validate_id
from .model3d_requests import Model3DProductionRequest

_SCHEMA_VERSION = 1
_AUTHORITY = "HUMAN_OPERATOR"


class Model3DRequestPublicationModelError(ValueError):
    pass


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise Model3DRequestPublicationModelError(
            "MODEL3D publication evidence is not canonical JSON"
        ) from exc


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:") or any(
        character not in "0123456789abcdef" for character in value[7:]
    ):
        raise Model3DRequestPublicationModelError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise Model3DRequestPublicationModelError(f"{label} has invalid identity")
    return value


def _text(value: object, label: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Model3DRequestPublicationModelError(f"{label} is outside bounds")
    return value.strip()


@dataclass(frozen=True)
class Model3DRequestApproval:
    approval_id: str
    project_id: str
    task_id: str
    request_input_id: str
    proposal_id: str
    audit_id: str
    request_id: str
    request_hash: str
    request_json: str
    operator_id: str | None
    approved_at: str
    authority: str = _AUTHORITY
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.approval_id, IdKind.MODEL3D_REQUEST_APPROVAL, "approval_id"),
            (self.project_id, IdKind.PROJECT, "project_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.request_input_id, IdKind.MODEL3D_REQUEST_INPUT, "request_input_id"),
            (self.proposal_id, IdKind.MODEL3D_REQUEST_PROPOSAL, "proposal_id"),
            (self.audit_id, IdKind.MODEL3D_REQUEST_AUDIT, "audit_id"),
            (self.request_id, IdKind.MODEL3D_REQUEST, "request_id"),
        ):
            _id(value, kind, label)
        _digest(self.request_hash, "request_hash")
        if not isinstance(self.request_json, str) or not self.request_json:
            raise Model3DRequestPublicationModelError("request_json must be non-empty text")
        try:
            parsed = json.loads(self.request_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise Model3DRequestPublicationModelError("request_json is invalid JSON") from exc
        if _canonical(parsed) != self.request_json:
            raise Model3DRequestPublicationModelError("request_json is not canonical JSON")
        if not isinstance(self.operator_id, (str, type(None))):
            raise Model3DRequestPublicationModelError("operator_id is invalid")
        if self.operator_id is not None:
            _text(self.operator_id, "operator_id")
        if not isinstance(self.approved_at, str) or not self.approved_at:
            raise Model3DRequestPublicationModelError("approved_at is invalid")
        if self.authority != _AUTHORITY or self.schema_version != _SCHEMA_VERSION:
            raise Model3DRequestPublicationModelError("approval authority or schema drifted")

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "approval_id": self.approval_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "request_input_id": self.request_input_id,
            "proposal_id": self.proposal_id,
            "audit_id": self.audit_id,
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "request_json": self.request_json,
            "operator_id": self.operator_id,
            "authority": self.authority,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class Model3DRequestPublication:
    publication_id: str
    approval_id: str
    project_id: str
    task_id: str
    request_id: str
    request_hash: str
    published_at: str
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.publication_id, IdKind.MODEL3D_REQUEST_PUBLICATION, "publication_id"),
            (self.approval_id, IdKind.MODEL3D_REQUEST_APPROVAL, "approval_id"),
            (self.project_id, IdKind.PROJECT, "project_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.request_id, IdKind.MODEL3D_REQUEST, "request_id"),
        ):
            _id(value, kind, label)
        _digest(self.request_hash, "request_hash")
        if not isinstance(self.published_at, str) or not self.published_at:
            raise Model3DRequestPublicationModelError("published_at is invalid")
        if self.schema_version != _SCHEMA_VERSION:
            raise Model3DRequestPublicationModelError("publication schema drifted")

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "publication_id": self.publication_id,
            "approval_id": self.approval_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "schema_version": self.schema_version,
        }


def canonical_request_json(request: Model3DProductionRequest) -> str:
    if not isinstance(request, Model3DProductionRequest):
        raise TypeError("request must be a Model3DProductionRequest")
    return _canonical(request.to_dict())
