from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .model import ModelAdapter, ModelRequest, ModelResponse
from .production_capability_store import ProductionCapabilityStore
from .production_design_specification_evidence import (
    DesignSpecificationEvidenceError,
    DesignSpecificationEvidenceStore,
    build_design_input,
)
from .production_design_specification_models import (
    DesignDeliverable,
    DesignRequirement,
    DesignSpecification,
    DesignSpecificationInput,
    DesignSpecificationModelError,
    canonical_hash,
)
from .runs import create_run, finish_run
from .runtime import OriginForgeRuntime
from .scheduled_model_adapter import RuntimeModelScheduleRecorder, ScheduledModelAdapter
from .state import RunStatus


_MAX_RESPONSE_BYTES = 256 * 1024

DESIGN_SPECIFIER_INSTRUCTIONS = """You are the Origin Forge bounded design specifier.
You receive one exact frozen Goal, current governed project-intelligence evidence, active Design Rules, and an infrastructure-owned capability set.
Return exactly one JSON object matching the supplied schema.
Use proposal-local requirement and deliverable keys only. Never invent Origin Forge canonical IDs.
Requirements and deliverables are inert planning-facing design evidence, not Tasks and not execution instructions.
Do not claim approval, acceptance, verification, currentness, Task status, Artifact adoption, provenance, merge, deploy, release, or semantic mutation authority.
Do not emit shell commands, SQL, callbacks, executable code, tool calls, or hidden workflows.
A valid response is only a candidate design specification. Infrastructure will parse and independently audit it; only a later explicit HUMAN_OPERATOR gate may accept it.
"""

DESIGN_SPECIFICATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "requirements", "deliverables"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 4096},
        "requirements": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "statement", "acceptance_criteria", "constraints"],
                "properties": {
                    "key": {
                        "type": "string",
                        "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                    },
                    "statement": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "acceptance_criteria": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                    },
                    "constraints": {
                        "type": "array",
                        "maxItems": 32,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                    },
                },
            },
        },
        "deliverables": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "key",
                    "objective",
                    "acceptance_criteria",
                    "constraints",
                    "required_capabilities",
                ],
                "properties": {
                    "key": {
                        "type": "string",
                        "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                    },
                    "objective": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "acceptance_criteria": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                    },
                    "constraints": {
                        "type": "array",
                        "maxItems": 32,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                    },
                    "required_capabilities": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {
                            "type": "string",
                            "pattern": "^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$",
                        },
                    },
                },
            },
        },
    },
}


class DesignSpecifierError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DesignSpecifierError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise DesignSpecifierError(f"non-finite JSON value is forbidden: {value}")


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DesignSpecifierError(f"{label} schema drifted")
    return value


def _canonical_request_hash(value: object) -> str:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DesignSpecifierError("design model request is not canonical JSON") from exc
    return hashlib.sha256(data).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resource_capacity_payload(model: ScheduledModelAdapter) -> dict[str, object]:
    capacity = model.scheduler.resources.capacity
    return {
        "cpu_slots": capacity.cpu_slots,
        "ram_mib": capacity.ram_mib,
        "max_active_leases": capacity.max_active_leases,
        "gpus": [
            {
                "device_id": gpu.device_id,
                "vram_mib": gpu.vram_mib,
                "reserve_vram_mib": gpu.reserve_vram_mib,
                "compute_slots": gpu.compute_slots,
            }
            for gpu in sorted(capacity.gpus, key=lambda value: value.device_id)
        ],
    }


def design_model_policy_hash(model: ModelAdapter) -> str:
    if isinstance(model, ScheduledModelAdapter):
        profiles = tuple(
            model.scheduler.registry.profile(profile_id)
            for profile_id in model.policy.ordered_profile_ids
        )
        return canonical_hash(
            {
                "kind": "scheduled-model-policy-v1",
                "role": model.policy.role.value,
                "primary_profile_id": model.policy.primary_profile_id,
                "fallback_profile_ids": list(model.policy.fallback_profile_ids),
                "profiles": [value.to_dict() for value in profiles],
            }
        )
    if isinstance(model, DeterministicDesignSpecifierAdapter):
        return canonical_hash(
            {
                "kind": "deterministic-design-specifier-fixture-v1",
                "model_id": model.fixture_model_id,
            }
        )
    raise TypeError(
        "design model must be ScheduledModelAdapter or DeterministicDesignSpecifierAdapter"
    )


def design_resource_policy_hash(model: ModelAdapter) -> str:
    if isinstance(model, ScheduledModelAdapter):
        return canonical_hash(
            {
                "kind": "resource-capacity-v1",
                "capacity": _resource_capacity_payload(model),
            }
        )
    if isinstance(model, DeterministicDesignSpecifierAdapter):
        return canonical_hash({"kind": "deterministic-no-io-fixture-v1"})
    raise TypeError(
        "design model must be ScheduledModelAdapter or DeterministicDesignSpecifierAdapter"
    )


@dataclass
class DeterministicDesignSpecifierAdapter:
    """Infrastructure-owned no-I/O fixture; never a production provider bypass."""

    response_text: str
    fixture_model_id: str = "deterministic-design-specifier-fixture"
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
                {"fixture": "OriginForge.DeterministicDesignSpecifierAdapter", "version": 1}
            ),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


def parse_design_specification(
    raw_text: str,
    *,
    design_input: DesignSpecificationInput,
    run_id: str,
    model_id: str,
    model_hash: str | None,
) -> DesignSpecification:
    if not isinstance(raw_text, str):
        raise DesignSpecifierError("design response must be text")
    try:
        size = len(raw_text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise DesignSpecifierError("design response is not valid UTF-8") from exc
    if not raw_text or size > _MAX_RESPONSE_BYTES:
        raise DesignSpecifierError("design response is outside byte bounds")
    try:
        value = json.loads(
            raw_text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except DesignSpecifierError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DesignSpecifierError("design response is invalid JSON") from exc
    top = _exact_keys(value, {"summary", "requirements", "deliverables"}, "design response")
    if not isinstance(top["requirements"], list) or not isinstance(top["deliverables"], list):
        raise DesignSpecifierError("design response arrays are invalid")

    requirements: list[DesignRequirement] = []
    for item in top["requirements"]:
        raw = _exact_keys(
            item,
            {"key", "statement", "acceptance_criteria", "constraints"},
            "design requirement",
        )
        if not isinstance(raw["acceptance_criteria"], list) or not isinstance(
            raw["constraints"], list
        ):
            raise DesignSpecifierError("design requirement arrays are invalid")
        try:
            requirements.append(
                DesignRequirement(
                    key=raw["key"],
                    statement=raw["statement"],
                    acceptance_criteria=tuple(raw["acceptance_criteria"]),
                    constraints=tuple(raw["constraints"]),
                )
            )
        except (DesignSpecificationModelError, TypeError, ValueError) as exc:
            raise DesignSpecifierError("design requirement failed validation") from exc

    deliverables: list[DesignDeliverable] = []
    for item in top["deliverables"]:
        raw = _exact_keys(
            item,
            {
                "key",
                "objective",
                "acceptance_criteria",
                "constraints",
                "required_capabilities",
            },
            "design deliverable",
        )
        for field in ("acceptance_criteria", "constraints", "required_capabilities"):
            if not isinstance(raw[field], list):
                raise DesignSpecifierError(f"design deliverable {field} is invalid")
        try:
            deliverables.append(
                DesignDeliverable(
                    key=raw["key"],
                    objective=raw["objective"],
                    acceptance_criteria=tuple(raw["acceptance_criteria"]),
                    constraints=tuple(raw["constraints"]),
                    required_capabilities=tuple(raw["required_capabilities"]),
                )
            )
        except (DesignSpecificationModelError, TypeError, ValueError) as exc:
            raise DesignSpecifierError("design deliverable failed validation") from exc

    try:
        return DesignSpecification.create(
            design_input=design_input,
            run_id=run_id,
            model_id=model_id,
            model_hash=model_hash,
            summary=top["summary"],
            requirements=requirements,
            deliverables=deliverables,
        )
    except (DesignSpecificationModelError, TypeError, ValueError) as exc:
        raise DesignSpecifierError("design specification failed governed validation") from exc


def freeze_governed_design_input(
    runtime: OriginForgeRuntime,
    goal_id: str,
    *,
    capability_store: ProductionCapabilityStore,
    catalog_id: str,
    routing_policy_id: str,
    model: ModelAdapter,
) -> DesignSpecificationInput:
    if not isinstance(model, (ScheduledModelAdapter, DeterministicDesignSpecifierAdapter)):
        raise TypeError(
            "design model must be ScheduledModelAdapter or DeterministicDesignSpecifierAdapter"
        )
    return build_design_input(
        runtime,
        goal_id=goal_id,
        capability_store=capability_store,
        catalog_id=catalog_id,
        routing_policy_id=routing_policy_id,
        model_policy_hash=design_model_policy_hash(model),
        resource_policy_hash=design_resource_policy_hash(model),
    )


@dataclass(frozen=True)
class DesignSpecifierResult:
    run_id: str
    design_input_id: str
    design_input_hash: str
    request_hash: str
    response_hash: str
    specification: DesignSpecification
    verification_id: str
    model_id: str
    model_hash: str | None


class BoundedDesignSpecifier:
    """One-shot Task-less proposal producer over one immutable DESIGNIN input."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        model: ModelAdapter,
        *,
        capability_store: ProductionCapabilityStore,
        evidence_store: DesignSpecificationEvidenceStore | None = None,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(model, (ScheduledModelAdapter, DeterministicDesignSpecifierAdapter)):
            raise TypeError(
                "design model must be ScheduledModelAdapter or DeterministicDesignSpecifierAdapter"
            )
        if isinstance(model, ScheduledModelAdapter) and not isinstance(
            model.recorder, RuntimeModelScheduleRecorder
        ):
            raise TypeError(
                "ScheduledModelAdapter requires RuntimeModelScheduleRecorder for governed design runs"
            )
        if not isinstance(capability_store, ProductionCapabilityStore):
            raise TypeError("capability_store must be a ProductionCapabilityStore")
        if capability_store.runtime.project_root != runtime.project_root:
            raise DesignSpecifierError(
                "capability authority belongs to a different project root"
            )
        self.runtime = runtime
        self.model = model
        self.capability_store = capability_store
        self.evidence_store = evidence_store or DesignSpecificationEvidenceStore(runtime)

    def propose(
        self,
        design_input_id: str,
        *,
        model_profile: str | None = None,
    ) -> DesignSpecifierResult:
        design_input = self.evidence_store.load_input(design_input_id)
        self.evidence_store._assert_capability_binding(
            design_input, self.capability_store
        )
        if design_input.model_policy_hash != design_model_policy_hash(self.model):
            raise DesignSpecifierError("design input model policy binding drifted")
        if design_input.resource_policy_hash != design_resource_policy_hash(self.model):
            raise DesignSpecifierError("design input resource policy binding drifted")
        context = self.evidence_store.generation_context(design_input)

        run_id = create_run(
            self.runtime.store,
            None,
            role="DESIGN_SPECIFIER",
            model_profile=model_profile or self.model.model_id,
        )
        request = ModelRequest(
            run_id=run_id,
            task_id=None,
            instructions=DESIGN_SPECIFIER_INSTRUCTIONS,
            context=context,
            response_schema=DESIGN_SPECIFICATION_SCHEMA,
        )
        request_hash = _canonical_request_hash(
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
                raise DesignSpecifierError(
                    "design model returned an invalid response envelope"
                )
            specification = parse_design_specification(
                response.text,
                design_input=design_input,
                run_id=run_id,
                model_id=response.model_id,
                model_hash=response.model_hash,
            )
            self.evidence_store.publish_specification(specification)
            response_hash = _text_hash(response.text)
            verification_id = self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="design-specification-generation",
                verifier="OriginForge.BoundedDesignSpecifier",
                status="PASS",
                evidence={
                    "design_input_id": design_input.design_input_id,
                    "design_input_hash": design_input.content_hash,
                    "request_hash": request_hash,
                    "response_hash": response_hash,
                    "design_specification_id": specification.design_specification_id,
                    "design_specification_hash": specification.content_hash,
                    "model_id": response.model_id,
                    "model_hash": response.model_hash,
                    "accepted": False,
                    "audited": False,
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
            return DesignSpecifierResult(
                run_id=run_id,
                design_input_id=design_input.design_input_id,
                design_input_hash=design_input.content_hash,
                request_hash=request_hash,
                response_hash=response_hash,
                specification=specification,
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
