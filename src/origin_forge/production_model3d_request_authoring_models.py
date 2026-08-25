from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from .blockbench_models import BlockbenchProjectSpec
from .ids import IdKind, new_id, validate_id
from .model3d_requests import Model3DRequestOperation


_SCHEMA_VERSION = 1
_TRANSLATION_CONTRACT_VERSION = "model3d-semantic-translation-v1"
_REQUEST_SCHEMA_VERSION = 1
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_MODEL_ID_CHARS = 256
_MAX_MODEL_HASH_CHARS = 512
_MAX_FAILURE_REASON_CHARS = 2048


class Model3DRequestAuthoringModelError(ValueError):
    pass


class Model3DRequestAuditStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Model3DRequestAuthoringModelError(
            "MODEL3D request authoring data is not canonical JSON"
        ) from exc


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be text")
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise Model3DRequestAuthoringModelError("text is not valid UTF-8") from exc


def _sha256(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Model3DRequestAuthoringModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _bounded_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Model3DRequestAuthoringModelError(f"{label} must be non-empty text")
    normalized = value.strip()
    if "\x00" in normalized or len(normalized) > maximum:
        raise Model3DRequestAuthoringModelError(f"{label} is outside text bounds")
    return normalized


@dataclass(frozen=True)
class Model3DRequestInput:
    request_input_id: str
    project_id: str
    task_id: str
    flow_id: str
    task_revision: int
    task_content_hash: str
    materialization_id: str
    materialization_hash: str
    planning_input_id: str
    planning_input_hash: str
    planning_proposal_id: str
    planning_proposal_hash: str
    planning_audit_id: str
    planning_audit_hash: str
    design_acceptance_id: str
    design_acceptance_hash: str
    design_specification_id: str
    design_specification_hash: str
    design_input_id: str
    design_input_hash: str
    goal_id: str
    goal_revision: int
    goal_content_hash: str
    context_hash: str
    translation_contract_version: str = _TRANSLATION_CONTRACT_VERSION
    request_schema_version: int = _REQUEST_SCHEMA_VERSION
    request_operation: str = Model3DRequestOperation.EXPORT_GLB.value
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        id_checks = (
            (self.request_input_id, IdKind.MODEL3D_REQUEST_INPUT, "request_input_id"),
            (self.project_id, IdKind.PROJECT, "project_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.flow_id, IdKind.FLOW, "flow_id"),
            (self.materialization_id, IdKind.PLAN_MATERIALIZATION, "materialization_id"),
            (self.planning_input_id, IdKind.PLANNING_INPUT, "planning_input_id"),
            (self.planning_proposal_id, IdKind.PLAN_PROPOSAL, "planning_proposal_id"),
            (self.planning_audit_id, IdKind.PLAN_AUDIT, "planning_audit_id"),
            (
                self.design_acceptance_id,
                IdKind.DESIGN_SPECIFICATION_ACCEPTANCE,
                "design_acceptance_id",
            ),
            (
                self.design_specification_id,
                IdKind.DESIGN_SPECIFICATION,
                "design_specification_id",
            ),
            (self.design_input_id, IdKind.DESIGN_SPECIFICATION_INPUT, "design_input_id"),
            (self.goal_id, IdKind.GOAL, "goal_id"),
        )
        for value, kind, label in id_checks:
            if not validate_id(value, kind):
                raise Model3DRequestAuthoringModelError(f"{label} has invalid identity")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise Model3DRequestAuthoringModelError("task_revision is invalid")
        if type(self.goal_revision) is not int or self.goal_revision < 0:
            raise Model3DRequestAuthoringModelError("goal_revision is invalid")
        for field in (
            "task_content_hash",
            "materialization_hash",
            "planning_input_hash",
            "planning_proposal_hash",
            "planning_audit_hash",
            "design_acceptance_hash",
            "design_specification_hash",
            "design_input_hash",
            "goal_content_hash",
            "context_hash",
        ):
            _sha256(getattr(self, field), field)
        if self.translation_contract_version != _TRANSLATION_CONTRACT_VERSION:
            raise Model3DRequestAuthoringModelError("translation contract version drifted")
        if self.request_schema_version != _REQUEST_SCHEMA_VERSION:
            raise Model3DRequestAuthoringModelError("request schema version drifted")
        if self.request_operation != Model3DRequestOperation.EXPORT_GLB.value:
            raise Model3DRequestAuthoringModelError("request operation must be EXPORT_GLB")
        if self.schema_version != _SCHEMA_VERSION:
            raise Model3DRequestAuthoringModelError("request input schema version drifted")
        canonical_bytes(self.to_dict())

    @classmethod
    def create(cls, **fields: object) -> "Model3DRequestInput":
        return cls(
            request_input_id=new_id(IdKind.MODEL3D_REQUEST_INPUT),
            **fields,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_input_id": self.request_input_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "flow_id": self.flow_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "materialization_id": self.materialization_id,
            "materialization_hash": self.materialization_hash,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "planning_proposal_id": self.planning_proposal_id,
            "planning_proposal_hash": self.planning_proposal_hash,
            "planning_audit_id": self.planning_audit_id,
            "planning_audit_hash": self.planning_audit_hash,
            "design_acceptance_id": self.design_acceptance_id,
            "design_acceptance_hash": self.design_acceptance_hash,
            "design_specification_id": self.design_specification_id,
            "design_specification_hash": self.design_specification_hash,
            "design_input_id": self.design_input_id,
            "design_input_hash": self.design_input_hash,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_content_hash": self.goal_content_hash,
            "context_hash": self.context_hash,
            "translation_contract_version": self.translation_contract_version,
            "request_schema_version": self.request_schema_version,
            "request_operation": self.request_operation,
            "schema_version": self.schema_version,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class Model3DRequestProposal:
    proposal_id: str
    request_input_id: str
    request_input_hash: str
    run_id: str
    model_id: str
    model_hash: str | None
    response_text: str
    response_hash: str
    operation: Model3DRequestOperation
    project: BlockbenchProjectSpec
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not validate_id(self.proposal_id, IdKind.MODEL3D_REQUEST_PROPOSAL):
            raise Model3DRequestAuthoringModelError("proposal_id must be an M3DREQPROP ID")
        if not validate_id(self.request_input_id, IdKind.MODEL3D_REQUEST_INPUT):
            raise Model3DRequestAuthoringModelError("request_input_id must be an M3DREQIN ID")
        if not validate_id(self.run_id, IdKind.RUN):
            raise Model3DRequestAuthoringModelError("run_id must be a RUN ID")
        _sha256(self.request_input_hash, "request_input_hash")
        object.__setattr__(
            self, "model_id", _bounded_text(self.model_id, "model_id", _MAX_MODEL_ID_CHARS)
        )
        if self.model_hash is not None:
            object.__setattr__(
                self,
                "model_hash",
                _bounded_text(self.model_hash, "model_hash", _MAX_MODEL_HASH_CHARS),
            )
        if not isinstance(self.response_text, str):
            raise Model3DRequestAuthoringModelError("response_text must be text")
        try:
            response_bytes = self.response_text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise Model3DRequestAuthoringModelError("response_text is not valid UTF-8") from exc
        if not response_bytes or len(response_bytes) > _MAX_RESPONSE_BYTES:
            raise Model3DRequestAuthoringModelError("response_text is outside byte bounds")
        _sha256(self.response_hash, "response_hash")
        if sha256_text(self.response_text) != self.response_hash:
            raise Model3DRequestAuthoringModelError("response_hash does not match exact response bytes")
        if self.operation is not Model3DRequestOperation.EXPORT_GLB:
            raise Model3DRequestAuthoringModelError("proposal operation must be EXPORT_GLB")
        if not isinstance(self.project, BlockbenchProjectSpec):
            raise Model3DRequestAuthoringModelError(
                "proposal project must be a canonical BlockbenchProjectSpec"
            )
        if self.schema_version != _SCHEMA_VERSION:
            raise Model3DRequestAuthoringModelError("proposal schema version drifted")
        canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        *,
        request_input: Model3DRequestInput,
        run_id: str,
        model_id: str,
        model_hash: str | None,
        response_text: str,
        project: BlockbenchProjectSpec,
    ) -> "Model3DRequestProposal":
        if not isinstance(request_input, Model3DRequestInput):
            raise TypeError("request_input must be a Model3DRequestInput")
        return cls(
            proposal_id=new_id(IdKind.MODEL3D_REQUEST_PROPOSAL),
            request_input_id=request_input.request_input_id,
            request_input_hash=request_input.content_hash,
            run_id=run_id,
            model_id=model_id,
            model_hash=model_hash,
            response_text=response_text,
            response_hash=sha256_text(response_text),
            operation=Model3DRequestOperation.EXPORT_GLB,
            project=project,
        )

    def bind(self, request_input: Model3DRequestInput) -> None:
        if not isinstance(request_input, Model3DRequestInput):
            raise TypeError("request_input must be a Model3DRequestInput")
        if self.request_input_id != request_input.request_input_id:
            raise Model3DRequestAuthoringModelError("proposal request_input_id does not match")
        if self.request_input_hash != request_input.content_hash:
            raise Model3DRequestAuthoringModelError("proposal request_input_hash does not match")
        if self.operation.value != request_input.request_operation:
            raise Model3DRequestAuthoringModelError("proposal operation does not match request input")

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "request_input_id": self.request_input_id,
            "request_input_hash": self.request_input_hash,
            "run_id": self.run_id,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "response_text": self.response_text,
            "response_hash": self.response_hash,
            "operation": self.operation.value,
            "project": self.project.to_dict(),
            "project_hash": self.project.content_hash,
            "schema_version": self.schema_version,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class Model3DRequestAudit:
    audit_id: str
    request_input_id: str
    request_input_hash: str
    proposal_id: str
    proposal_hash: str
    response_hash: str
    project_hash: str
    status: Model3DRequestAuditStatus
    failure_reason: str | None
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not validate_id(self.audit_id, IdKind.MODEL3D_REQUEST_AUDIT):
            raise Model3DRequestAuthoringModelError("audit_id must be an M3DREQAUD ID")
        if not validate_id(self.request_input_id, IdKind.MODEL3D_REQUEST_INPUT):
            raise Model3DRequestAuthoringModelError("request_input_id must be an M3DREQIN ID")
        if not validate_id(self.proposal_id, IdKind.MODEL3D_REQUEST_PROPOSAL):
            raise Model3DRequestAuthoringModelError("proposal_id must be an M3DREQPROP ID")
        for field in (
            "request_input_hash",
            "proposal_hash",
            "response_hash",
            "project_hash",
        ):
            _sha256(getattr(self, field), field)
        if not isinstance(self.status, Model3DRequestAuditStatus):
            raise Model3DRequestAuthoringModelError("audit status is invalid")
        if self.status is Model3DRequestAuditStatus.PASS:
            if self.failure_reason is not None:
                raise Model3DRequestAuthoringModelError("PASS audit cannot have failure_reason")
        else:
            if self.failure_reason is None:
                raise Model3DRequestAuthoringModelError("FAIL audit requires failure_reason")
            object.__setattr__(
                self,
                "failure_reason",
                _bounded_text(
                    self.failure_reason,
                    "failure_reason",
                    _MAX_FAILURE_REASON_CHARS,
                ),
            )
        if self.schema_version != _SCHEMA_VERSION:
            raise Model3DRequestAuthoringModelError("audit schema version drifted")
        canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        *,
        request_input: Model3DRequestInput,
        proposal: Model3DRequestProposal,
        status: Model3DRequestAuditStatus,
        failure_reason: str | None,
    ) -> "Model3DRequestAudit":
        if not isinstance(request_input, Model3DRequestInput):
            raise TypeError("request_input must be a Model3DRequestInput")
        if not isinstance(proposal, Model3DRequestProposal):
            raise TypeError("proposal must be a Model3DRequestProposal")
        proposal.bind(request_input)
        return cls(
            audit_id=new_id(IdKind.MODEL3D_REQUEST_AUDIT),
            request_input_id=request_input.request_input_id,
            request_input_hash=request_input.content_hash,
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.content_hash,
            response_hash=proposal.response_hash,
            project_hash=proposal.project.content_hash,
            status=status,
            failure_reason=failure_reason,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_id": self.audit_id,
            "request_input_id": self.request_input_id,
            "request_input_hash": self.request_input_hash,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "response_hash": self.response_hash,
            "project_hash": self.project_hash,
            "status": self.status.value,
            "failure_reason": self.failure_reason,
            "schema_version": self.schema_version,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())