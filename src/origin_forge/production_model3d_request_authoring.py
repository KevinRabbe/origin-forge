from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .model import ModelAdapter, ModelRequest, ModelResponse
from .model3d_requests import Model3DRequestError, Model3DRequestOperation, _project
from .production_model3d_request_authoring_evidence import (
    Model3DRequestAuthoringEvidenceError,
    Model3DRequestAuthoringEvidenceStore,
    generation_context_for_input,
    inspect_model3d_request_input,
)
from .production_model3d_request_authoring_models import (
    Model3DRequestAudit,
    Model3DRequestAuditStatus,
    Model3DRequestAuthoringModelError,
    Model3DRequestInput,
    Model3DRequestProposal,
    canonical_hash,
)
from .runs import create_run, finish_run
from .runtime import OriginForgeRuntime
from .scheduled_model_adapter import RuntimeModelScheduleRecorder, ScheduledModelAdapter
from .state import RunStatus


_MAX_RESPONSE_BYTES = 256 * 1024

MODEL3D_REQUEST_AUTHOR_INSTRUCTIONS = """You are the Origin Forge bounded Blender semantic-request author.
You receive one exact immutable Phase-57 translation input reconstructed from a governed production Task, its Phase-31 planning lineage, and its exact current HUMAN_OPERATOR-accepted Phase-56 design specification.
Return exactly one JSON object with operation EXPORT_GLB and one canonical Blockbench project semantic payload matching the supplied schema.
The response is proposal-only semantic content. Never invent or emit Origin Forge canonical IDs, Task/planning/design evidence identities or hashes, WorkOrder/dispatch identities, filesystem destinations, executable/runtime/profile authority, audit status, operator approval, provenance/signing, merge, deploy, or release authority.
Do not emit shell commands, SQL, callbacks, tool calls, hidden workflows, or arbitrary external paths.
Infrastructure will strictly parse and independently audit the proposal. A PASS audit still does not publish MODEL3DREQ evidence; publication requires a later explicit HUMAN_OPERATOR gate.
"""

MODEL3D_REQUEST_PROPOSAL_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["operation", "project"],
    "properties": {
        "operation": {"const": "EXPORT_GLB"},
        "project": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "project_name",
                "bones",
                "cuboids",
                "textures",
                "animations",
            ],
            "properties": {
                "schema_version": {"const": 1},
                "project_name": {"type": "string", "minLength": 1},
                "bones": {"type": "array"},
                "cuboids": {"type": "array"},
                "textures": {"type": "array"},
                "animations": {"type": "array"},
            },
        },
    },
}


class Model3DRequestAuthorError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Model3DRequestAuthorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise Model3DRequestAuthorError(f"non-finite JSON value is forbidden: {value}")


def _request_hash(value: object) -> str:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Model3DRequestAuthorError(
            "MODEL3D author request is not canonical JSON"
        ) from exc
    return hashlib.sha256(data).hexdigest()


@dataclass
class DeterministicModel3DRequestAuthorAdapter:
    """Infrastructure-owned no-I/O test fixture; never a production provider bypass."""

    response_text: str
    fixture_model_id: str = "deterministic-model3d-request-author-fixture"
    input_tokens: int | None = None
    output_tokens: int | None = None
    call_count: int = 0
    last_request: ModelRequest | None = None

    @property
    def model_id(self) -> str:
        return self.fixture_model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise TypeError("request must be a ModelRequest")
        self.call_count += 1
        self.last_request = request
        return ModelResponse(
            text=self.response_text,
            model_id=self.fixture_model_id,
            model_hash=canonical_hash(
                {
                    "fixture": "OriginForge.DeterministicModel3DRequestAuthorAdapter",
                    "version": 1,
                }
            ),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


def _parse_semantic_payload(raw_text: str) -> tuple[Model3DRequestOperation, object]:
    if not isinstance(raw_text, str):
        raise Model3DRequestAuthorError("MODEL3D proposal response must be text")
    try:
        size = len(raw_text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise Model3DRequestAuthorError(
            "MODEL3D proposal response is not valid UTF-8"
        ) from exc
    if not raw_text or size > _MAX_RESPONSE_BYTES:
        raise Model3DRequestAuthorError(
            "MODEL3D proposal response is outside byte bounds"
        )
    try:
        value = json.loads(
            raw_text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except Model3DRequestAuthorError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise Model3DRequestAuthorError("MODEL3D proposal response is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"operation", "project"}:
        raise Model3DRequestAuthorError(
            "MODEL3D proposal response has unknown or missing fields"
        )
    if value["operation"] != Model3DRequestOperation.EXPORT_GLB.value:
        raise Model3DRequestAuthorError("MODEL3D proposal operation must be EXPORT_GLB")
    try:
        project = _project(value["project"])
    except (Model3DRequestError, TypeError, ValueError) as exc:
        raise Model3DRequestAuthorError(
            "MODEL3D proposal project failed canonical Phase-51 validation"
        ) from exc
    return Model3DRequestOperation.EXPORT_GLB, project


def parse_model3d_request_proposal(
    raw_text: str,
    *,
    request_input: Model3DRequestInput,
    run_id: str,
    model_id: str,
    model_hash: str | None,
) -> Model3DRequestProposal:
    if not isinstance(request_input, Model3DRequestInput):
        raise TypeError("request_input must be a Model3DRequestInput")
    operation, project = _parse_semantic_payload(raw_text)
    if operation.value != request_input.request_operation:
        raise Model3DRequestAuthorError(
            "MODEL3D proposal operation does not match immutable input"
        )
    try:
        proposal = Model3DRequestProposal.create(
            request_input=request_input,
            run_id=run_id,
            model_id=model_id,
            model_hash=model_hash,
            response_text=raw_text,
            project=project,
        )
        proposal.bind(request_input)
        return proposal
    except (Model3DRequestAuthoringModelError, TypeError, ValueError) as exc:
        raise Model3DRequestAuthorError(
            "MODEL3D proposal failed governed validation"
        ) from exc


@dataclass(frozen=True)
class Model3DRequestAuthorResult:
    run_id: str
    request_input_id: str
    request_input_hash: str
    request_hash: str
    response_hash: str
    proposal: Model3DRequestProposal
    verification_id: str
    model_id: str
    model_hash: str | None


class BoundedModel3DRequestAuthor:
    """One-shot proposal-only semantic translator over one immutable M3DREQIN."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        model: ModelAdapter,
        *,
        evidence_store: Model3DRequestAuthoringEvidenceStore | None = None,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(
            model,
            (ScheduledModelAdapter, DeterministicModel3DRequestAuthorAdapter),
        ):
            raise TypeError(
                "MODEL3D author model must be ScheduledModelAdapter or deterministic fixture"
            )
        if isinstance(model, ScheduledModelAdapter) and not isinstance(
            model.recorder, RuntimeModelScheduleRecorder
        ):
            raise TypeError(
                "ScheduledModelAdapter requires RuntimeModelScheduleRecorder for governed MODEL3D author runs"
            )
        self.runtime = runtime
        self.model = model
        self.evidence_store = evidence_store or Model3DRequestAuthoringEvidenceStore(runtime)

    def propose(self, request_input_id: str) -> Model3DRequestAuthorResult:
        inspection = inspect_model3d_request_input(
            self.runtime,
            request_input_id,
            evidence_store=self.evidence_store,
        )
        if not inspection.current:
            raise Model3DRequestAuthorError(
                f"M3DREQIN is stale: {inspection.stale_reason}"
            )
        request_input = inspection.request_input
        context = generation_context_for_input(
            self.runtime,
            request_input_id,
            evidence_store=self.evidence_store,
        )
        run_id = create_run(
            self.runtime.store,
            None,
            role="MODEL3D_REQUEST_AUTHOR",
            model_profile=self.model.model_id,
        )
        request = ModelRequest(
            run_id=run_id,
            task_id=None,
            instructions=MODEL3D_REQUEST_AUTHOR_INSTRUCTIONS,
            context=context,
            response_schema=MODEL3D_REQUEST_PROPOSAL_SCHEMA,
        )
        request_hash = _request_hash(
            {
                "run_id": request.run_id,
                "task_id": request.task_id,
                "instructions": request.instructions,
                "context": request.context,
                "response_schema": request.response_schema,
            }
        )
        try:
            response = self.model.generate(request)
            if not isinstance(response, ModelResponse) or not response.model_id:
                raise Model3DRequestAuthorError(
                    "MODEL3D author model returned an invalid response envelope"
                )
            proposal = parse_model3d_request_proposal(
                response.text,
                request_input=request_input,
                run_id=run_id,
                model_id=response.model_id,
                model_hash=response.model_hash,
            )
            self.evidence_store.publish_proposal(proposal)
            verification_id = self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="model3d-request-proposal-generation",
                verifier="OriginForge.BoundedModel3DRequestAuthor",
                status="PASS",
                evidence={
                    "request_input_id": request_input.request_input_id,
                    "request_input_hash": request_input.content_hash,
                    "request_hash": request_hash,
                    "response_hash": proposal.response_hash,
                    "proposal_id": proposal.proposal_id,
                    "proposal_hash": proposal.content_hash,
                    "project_hash": proposal.project.content_hash,
                    "operation": proposal.operation.value,
                    "model_id": response.model_id,
                    "model_hash": response.model_hash,
                    "audited": False,
                    "approved": False,
                    "published": False,
                },
                metrics={
                    "response_bytes": len(response.text.encode("utf-8")),
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "model_calls": 1,
                },
                run_id=run_id,
            )
            finish_run(
                self.runtime.store,
                run_id,
                RunStatus.SUCCEEDED,
                input_token_count=response.input_tokens,
                output_token_count=response.output_tokens,
            )
            return Model3DRequestAuthorResult(
                run_id=run_id,
                request_input_id=request_input.request_input_id,
                request_input_hash=request_input.content_hash,
                request_hash=request_hash,
                response_hash=proposal.response_hash,
                proposal=proposal,
                verification_id=verification_id,
                model_id=response.model_id,
                model_hash=response.model_hash,
            )
        except Exception as exc:
            try:
                run = self.runtime.get_run(run_id)
                if run["status"] == RunStatus.RUNNING.value:
                    finish_run(
                        self.runtime.store,
                        run_id,
                        RunStatus.FAILED,
                        failure_reason=f"{type(exc).__name__}: {exc}"[:1000],
                    )
            except Exception:
                pass
            raise


def audit_model3d_request_proposal(
    runtime: OriginForgeRuntime,
    proposal_id: str,
    *,
    evidence_store: Model3DRequestAuthoringEvidenceStore | None = None,
) -> Model3DRequestAudit:
    """Independently audit exact durable proposal/provenance without a model call."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    store = evidence_store or Model3DRequestAuthoringEvidenceStore(runtime)
    existing = store.audit_for_proposal(proposal_id)
    if existing is not None:
        return existing
    proposal = store.load_proposal(proposal_id)
    request_input = store.load_input(proposal.request_input_id)

    status = Model3DRequestAuditStatus.PASS
    failure_reason: str | None = None
    try:
        inspection = inspect_model3d_request_input(
            runtime,
            request_input.request_input_id,
            evidence_store=store,
        )
        if not inspection.current:
            raise Model3DRequestAuthorError(
                f"request input is stale: {inspection.stale_reason}"
            )
        operation, project = _parse_semantic_payload(proposal.response_text)
        proposal.bind(request_input)
        if operation is not proposal.operation:
            raise Model3DRequestAuthorError("proposal operation drifted on independent parse")
        if project.content_hash != proposal.project.content_hash:
            raise Model3DRequestAuthorError("proposal project drifted on independent parse")
        if proposal.response_hash != hashlib.sha256(
            proposal.response_text.encode("utf-8")
        ).hexdigest():
            raise Model3DRequestAuthorError("proposal exact response bytes/hash drifted")
        if request_input.request_operation != Model3DRequestOperation.EXPORT_GLB.value:
            raise Model3DRequestAuthorError("immutable input operation drifted")
        # Canonical semantic payload can be deterministically reconstructed later
        # with an infrastructure-owned MODEL3DREQ identity, without another model call.
        canonical_hash(
            {
                "schema_version": request_input.request_schema_version,
                "operation": proposal.operation.value,
                "project": proposal.project.to_dict(),
                "project_hash": proposal.project.content_hash,
            }
        )
    except (
        Model3DRequestAuthorError,
        Model3DRequestAuthoringEvidenceError,
        Model3DRequestAuthoringModelError,
        Model3DRequestError,
        TypeError,
        ValueError,
    ) as exc:
        status = Model3DRequestAuditStatus.FAIL
        failure_reason = f"{type(exc).__name__}: {exc}"[:2048]

    audit = Model3DRequestAudit.create(
        request_input=request_input,
        proposal=proposal,
        status=status,
        failure_reason=failure_reason,
    )
    return store._publish_audit(audit)