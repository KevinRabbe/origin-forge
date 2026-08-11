from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Sequence

from .model import ModelAdapter, ModelRequest, ModelResponse
from .production_capability_routing import CapabilityRouteOutcome
from .production_capability_store import (
    CapabilityRouteDecision,
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
    content_hash,
)
from .production_work_order_validators import (
    DispatchContractValidatorRegistry,
    DispatchValidatorError,
)
from .production_work_orders import (
    ProductionWorkOrder,
    ProductionWorkOrderError,
    create_current_work_order,
)
from .runs import create_run, finish_run
from .runtime import OriginForgeRuntime
from .scheduled_model_adapter import ScheduledModelAdapter
from .state import RunStatus


WORK_ORDER_PLANNER_INSTRUCTIONS = """You are the Origin Forge bounded Work Order Planner.
You receive one exact current Task projection, one current Phase-32 route, one infrastructure-selected dispatch contract, its inert payload schema, and a finite allow-list of exact input evidence refs.
Return exactly one JSON object matching the supplied response schema.
You may choose only the supplied contract_id and only exact input refs from the supplied allow-list.
Do not invent WorkOrder, Task, Flow, Run, route, adapter, catalog, verification, approval, completion, adoption, signing, merge, or release authority.
Do not emit shell commands, argv, environment blocks, executable paths, endpoints, imports, callables, container authority, secrets, code, SQL, tool calls, callbacks, loops, or hidden executable predicates.
The response is inert proposal data only. Infrastructure independently validates it and constructs a WorkOrder; this worker never audits or dispatches it.
"""

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 16
_MAX_JSON_CONTAINER_ITEMS = 512
_MAX_JSON_STRING_CHARS = 65_536
_MAX_JSON_INTEGER = 9_223_372_036_854_775_807
_FORBIDDEN_AUTHORITY_KEYS = {
    "work_order_id",
    "task_id",
    "task_revision",
    "task_content_hash",
    "flow_id",
    "run_id",
    "route_decision_id",
    "route_decision_hash",
    "selected_adapter_id",
    "selected_adapter_fingerprint",
    "dispatch_catalog_id",
    "dispatch_catalog_hash",
    "dispatch_contract_hash",
    "status",
    "approved",
    "approval",
    "verified",
    "verification",
    "complete",
    "completed",
    "adopt",
    "adopted",
    "sign",
    "signed",
    "merge",
    "merged",
    "release",
    "released",
    "shell",
    "argv",
    "command",
    "environment",
    "env",
    "import",
    "callable",
    "executable",
    "endpoint",
    "container",
    "secret",
    "password",
    "token",
}


class ProductionWorkOrderPlannerError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionWorkOrderPlannerError(
                f"work-order proposal contains duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _scan_bounded_json(value: object, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ProductionWorkOrderPlannerError("work-order proposal exceeds JSON depth bound")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > _MAX_JSON_INTEGER:
            raise ProductionWorkOrderPlannerError(
                "work-order proposal contains an integer outside bounds"
            )
        return
    if isinstance(value, float):
        raise ProductionWorkOrderPlannerError(
            "work-order proposal cannot contain floating-point values"
        )
    if isinstance(value, str):
        if not value or len(value) > _MAX_JSON_STRING_CHARS:
            raise ProductionWorkOrderPlannerError(
                "work-order proposal contains text outside bounds"
            )
        return
    if isinstance(value, list):
        if len(value) > _MAX_JSON_CONTAINER_ITEMS:
            raise ProductionWorkOrderPlannerError(
                "work-order proposal array exceeds item bound"
            )
        for item in value:
            _scan_bounded_json(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > _MAX_JSON_CONTAINER_ITEMS:
            raise ProductionWorkOrderPlannerError(
                "work-order proposal object exceeds field bound"
            )
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > 256
                or key.lower() in _FORBIDDEN_AUTHORITY_KEYS
            ):
                raise ProductionWorkOrderPlannerError(
                    f"work-order proposal contains forbidden authority field: {key!r}"
                )
            _scan_bounded_json(item, depth=depth + 1)
        return
    raise ProductionWorkOrderPlannerError("work-order proposal contains unsupported JSON data")


def _proposal_ref(value: object) -> WorkOrderInputRef:
    if not isinstance(value, dict):
        raise ProductionWorkOrderPlannerError("work-order proposal input_ref must be an object")
    allowed = {"ref_type", "ref_id", "content_hash", "role", "revision"}
    required = {"ref_type", "ref_id", "content_hash", "role"}
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise ProductionWorkOrderPlannerError("work-order proposal input_ref schema drifted")
    revision = value.get("revision")
    if revision is not None and type(revision) is not int:
        raise ProductionWorkOrderPlannerError("work-order proposal input_ref revision is invalid")
    try:
        return WorkOrderInputRef(
            ref_type=WorkOrderRefType(value["ref_type"]),
            ref_id=value["ref_id"],
            content_hash=value["content_hash"],
            role=value["role"],
            revision=revision,
        )
    except (ProductionWorkOrderModelError, TypeError, ValueError) as exc:
        raise ProductionWorkOrderPlannerError(
            "work-order proposal input_ref failed validation"
        ) from exc


def _ref_identity(value: WorkOrderInputRef) -> tuple[object, ...]:
    return (
        value.ref_type.value,
        value.ref_id,
        value.content_hash,
        value.role,
        value.revision,
    )


@dataclass(frozen=True)
class WorkOrderProposal:
    contract_id: str
    input_refs: tuple[WorkOrderInputRef, ...]
    payload_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.contract_id, str) or not self.contract_id:
            raise ProductionWorkOrderPlannerError("proposal contract_id is invalid")
        refs = tuple(self.input_refs)
        if not all(isinstance(value, WorkOrderInputRef) for value in refs):
            raise ProductionWorkOrderPlannerError("proposal input_refs are invalid")
        identities = [_ref_identity(value) for value in refs]
        if len(identities) != len(set(identities)):
            raise ProductionWorkOrderPlannerError("proposal input_refs contain duplicates")
        object.__setattr__(
            self,
            "input_refs",
            tuple(sorted(refs, key=_ref_identity)),
        )
        if not isinstance(self.payload_json, str) or not self.payload_json:
            raise ProductionWorkOrderPlannerError("proposal payload_json is invalid")
        try:
            payload = json.loads(self.payload_json, object_pairs_hook=_strict_object)
        except ProductionWorkOrderPlannerError:
            raise
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProductionWorkOrderPlannerError("proposal payload_json is invalid") from exc
        if not isinstance(payload, dict):
            raise ProductionWorkOrderPlannerError("proposal payload must be an object")
        expected = canonical_bytes(payload).decode("utf-8")
        if expected != self.payload_json:
            raise ProductionWorkOrderPlannerError("proposal payload_json is not canonical")

    @property
    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_json)
        assert isinstance(value, dict)
        return value

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "input_refs": [value.to_dict() for value in self.input_refs],
            "payload": self.payload,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


def parse_work_order_proposal(
    text: str,
    *,
    contract: DispatchContract,
    allowed_input_refs: Sequence[WorkOrderInputRef],
) -> WorkOrderProposal:
    if not isinstance(text, str):
        raise ProductionWorkOrderPlannerError("model response must be text")
    raw = text.encode("utf-8")
    if not raw or len(raw) > _MAX_RESPONSE_BYTES:
        raise ProductionWorkOrderPlannerError("model response is outside byte bounds")
    try:
        value = json.loads(text, object_pairs_hook=_strict_object)
    except ProductionWorkOrderPlannerError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProductionWorkOrderPlannerError("model response is not strict JSON") from exc
    if not isinstance(value, dict) or set(value) != {"contract_id", "input_refs", "payload"}:
        raise ProductionWorkOrderPlannerError("work-order proposal top-level schema drifted")
    _scan_bounded_json(value)
    if value["contract_id"] != contract.contract_id:
        raise ProductionWorkOrderPlannerError(
            "model cannot select a dispatch contract outside infrastructure authority"
        )
    if not isinstance(value["input_refs"], list) or len(value["input_refs"]) > contract.max_input_refs:
        raise ProductionWorkOrderPlannerError("work-order proposal input_refs exceed contract")
    refs = tuple(_proposal_ref(item) for item in value["input_refs"])
    identities = [_ref_identity(item) for item in refs]
    if len(identities) != len(set(identities)):
        raise ProductionWorkOrderPlannerError("work-order proposal input_refs contain duplicates")
    allowed = {_ref_identity(item) for item in allowed_input_refs}
    if any(identity not in allowed for identity in identities):
        raise ProductionWorkOrderPlannerError(
            "model proposed an input ref outside the infrastructure allow-list"
        )
    if not isinstance(value["payload"], dict):
        raise ProductionWorkOrderPlannerError("work-order proposal payload must be an object")
    try:
        payload_json = canonical_bytes(value["payload"]).decode("utf-8")
    except ProductionWorkOrderModelError as exc:
        raise ProductionWorkOrderPlannerError(
            "work-order proposal payload is outside canonical bounds"
        ) from exc
    return WorkOrderProposal(
        contract_id=contract.contract_id,
        input_refs=refs,
        payload_json=payload_json,
    )


def _payload_json_schema(schema: object) -> dict[str, object]:
    if not isinstance(schema, dict) or set(schema) != {
        "schema_id",
        "type",
        "fields",
        "additional_fields",
    }:
        raise ProductionWorkOrderPlannerError("dispatch validator schema is not a supported inert schema")
    if schema["type"] != "OBJECT" or schema["additional_fields"] is not False:
        raise ProductionWorkOrderPlannerError("dispatch validator schema is not an exact object")
    fields = schema["fields"]
    if not isinstance(fields, list) or len(fields) > 128:
        raise ProductionWorkOrderPlannerError("dispatch validator schema fields are outside bounds")
    properties: dict[str, object] = {}
    required: list[str] = []
    for raw in fields:
        if not isinstance(raw, dict):
            raise ProductionWorkOrderPlannerError("dispatch validator schema field is invalid")
        expected_keys = {
            "name",
            "kind",
            "required",
            "allowed_values",
            "max_string_chars",
            "min_integer",
            "max_integer",
            "max_items",
        }
        if set(raw) != expected_keys:
            raise ProductionWorkOrderPlannerError("dispatch validator schema field drifted")
        name = raw["name"]
        kind = raw["kind"]
        if not isinstance(name, str) or not name:
            raise ProductionWorkOrderPlannerError("dispatch validator schema field name is invalid")
        if raw["required"] is True:
            required.append(name)
        allowed_values = raw["allowed_values"]
        if not isinstance(allowed_values, list):
            raise ProductionWorkOrderPlannerError("dispatch validator allowed_values are invalid")
        if kind == "STRING":
            rule: dict[str, object] = {
                "type": "string",
                "minLength": 1,
                "maxLength": raw["max_string_chars"],
            }
            if allowed_values:
                rule["enum"] = list(allowed_values)
        elif kind == "INTEGER":
            rule = {
                "type": "integer",
                "minimum": raw["min_integer"],
                "maximum": raw["max_integer"],
            }
        elif kind == "BOOLEAN":
            rule = {"type": "boolean"}
        elif kind == "STRING_LIST":
            item: dict[str, object] = {
                "type": "string",
                "minLength": 1,
                "maxLength": raw["max_string_chars"],
            }
            if allowed_values:
                item["enum"] = list(allowed_values)
            rule = {
                "type": "array",
                "maxItems": raw["max_items"],
                "uniqueItems": True,
                "items": item,
            }
        else:
            raise ProductionWorkOrderPlannerError("dispatch validator schema kind is unsupported")
        properties[name] = rule
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(required),
        "properties": properties,
    }


def _response_schema(contract: DispatchContract, payload_schema: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_id", "input_refs", "payload"],
        "properties": {
            "contract_id": {"type": "string", "enum": [contract.contract_id]},
            "input_refs": {
                "type": "array",
                "maxItems": contract.max_input_refs,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ref_type", "ref_id", "content_hash", "role"],
                    "properties": {
                        "ref_type": {
                            "type": "string",
                            "enum": [value.value for value in contract.allowed_input_ref_types],
                        },
                        "ref_id": {"type": "string", "minLength": 1, "maxLength": 256},
                        "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "role": {"type": "string", "minLength": 1, "maxLength": 96},
                        "revision": {
                            "type": ["integer", "null"],
                            "minimum": 0,
                            "maximum": 2147483647,
                        },
                    },
                },
            },
            "payload": payload_schema,
        },
    }


def _stored_list(raw: object, label: str) -> list[object]:
    if not isinstance(raw, str):
        raise ProductionWorkOrderPlannerError(f"Task {label} is not stored JSON")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except ProductionWorkOrderPlannerError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProductionWorkOrderPlannerError(f"Task {label} is invalid JSON") from exc
    if not isinstance(value, list):
        raise ProductionWorkOrderPlannerError(f"Task {label} is not a list")
    _scan_bounded_json(value)
    return value


def _stored_object(raw: object, label: str) -> dict[str, object]:
    if not isinstance(raw, str):
        raise ProductionWorkOrderPlannerError(f"Task {label} is not stored JSON")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except ProductionWorkOrderPlannerError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProductionWorkOrderPlannerError(f"Task {label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProductionWorkOrderPlannerError(f"Task {label} is not an object")
    _scan_bounded_json(value)
    return value


def _request_hash(request: ModelRequest) -> str:
    return content_hash(
        {
            "run_id": request.run_id,
            "task_id": request.task_id,
            "instructions": request.instructions,
            "context": request.context,
            "response_schema": request.response_schema,
        }
    )


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class DeterministicWorkOrderPlannerAdapter:
    """No-I/O deterministic adapter for tests/manual proposal evidence only."""

    response_text: str
    fixture_model_id: str = "deterministic-work-order-planner-fixture"
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
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


@dataclass(frozen=True)
class WorkOrderPlannerResult:
    run_id: str
    route_decision_id: str
    route_decision_hash: str
    request_hash: str
    response_hash: str
    proposal_hash: str
    work_order: ProductionWorkOrder
    verification_id: str
    model_id: str
    model_hash: str | None


class BoundedProductionWorkOrderPlanner:
    """One-shot model proposal boundary that stops before audit or dispatch."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        capability_store: ProductionCapabilityStore,
        dispatch_catalog: DispatchContractCatalog,
        validator_registry: DispatchContractValidatorRegistry,
        model: ModelAdapter,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(capability_store, ProductionCapabilityStore):
            raise TypeError("capability_store must be a ProductionCapabilityStore")
        if capability_store.runtime.project_root != runtime.project_root:
            raise ProductionWorkOrderPlannerError(
                "capability_store belongs to a different project root"
            )
        if not isinstance(dispatch_catalog, DispatchContractCatalog):
            raise TypeError("dispatch_catalog must be a DispatchContractCatalog")
        if not isinstance(validator_registry, DispatchContractValidatorRegistry):
            raise TypeError("validator_registry must be a DispatchContractValidatorRegistry")
        if not isinstance(
            model,
            (ScheduledModelAdapter, DeterministicWorkOrderPlannerAdapter),
        ):
            raise TypeError(
                "WorkOrder planner model must be ScheduledModelAdapter or DeterministicWorkOrderPlannerAdapter"
            )
        self.runtime = runtime
        self.capability_store = capability_store
        self.dispatch_catalog = dispatch_catalog
        self.validator_registry = validator_registry
        self.model = model

    def _preflight(
        self,
        route_decision_id: str,
        allowed_input_refs: Sequence[WorkOrderInputRef],
    ) -> tuple[
        CapabilityRouteDecision,
        DispatchContract,
        tuple[WorkOrderInputRef, ...],
        dict[str, object],
        dict[str, object],
    ]:
        try:
            route = self.capability_store.require_current_route(route_decision_id)
        except ProductionCapabilityStoreError as exc:
            raise ProductionWorkOrderPlannerError(
                "Phase-32 route is unavailable or stale before WorkOrder planning"
            ) from exc
        resolution = route.resolution
        if resolution.outcome is not CapabilityRouteOutcome.ROUTABLE:
            raise ProductionWorkOrderPlannerError("Phase-32 route is not ROUTABLE")
        if not resolution.selected_adapter_id or not resolution.selected_adapter_fingerprint:
            raise ProductionWorkOrderPlannerError("ROUTABLE route lacks adapter identity")

        try:
            phase32_catalog = self.capability_store.load_catalog(resolution.catalog_id)
            self.dispatch_catalog.validate_against(phase32_catalog)
            contract = self.dispatch_catalog.contract_for_adapter(
                resolution.selected_adapter_id
            )
        except (ProductionCapabilityStoreError, ProductionWorkOrderModelError, KeyError) as exc:
            raise ProductionWorkOrderPlannerError(
                "dispatch authority is unavailable for the current route"
            ) from exc
        if (
            self.dispatch_catalog.phase32_catalog_id != resolution.catalog_id
            or self.dispatch_catalog.phase32_catalog_hash != resolution.catalog_hash
            or contract.adapter_fingerprint != resolution.selected_adapter_fingerprint
        ):
            raise ProductionWorkOrderPlannerError("dispatch authority drifted from current route")

        try:
            validator = self.validator_registry.validate_contract(contract)
        except DispatchValidatorError as exc:
            raise ProductionWorkOrderPlannerError("dispatch validator authority drifted") from exc
        schema_reader = getattr(validator, "schema_dict", None)
        if not callable(schema_reader):
            raise ProductionWorkOrderPlannerError(
                "selected dispatch validator exposes no inert planner schema"
            )
        schema = schema_reader()
        try:
            if content_hash(schema) != contract.payload_schema_hash:
                raise ProductionWorkOrderPlannerError(
                    "model-visible payload schema hash does not match dispatch contract"
                )
        except ProductionWorkOrderModelError as exc:
            raise ProductionWorkOrderPlannerError(
                "model-visible payload schema is outside canonical bounds"
            ) from exc
        payload_schema = _payload_json_schema(schema)

        refs = tuple(allowed_input_refs)
        if len(refs) > contract.max_input_refs or not all(
            isinstance(value, WorkOrderInputRef) for value in refs
        ):
            raise ProductionWorkOrderPlannerError(
                "allowed input evidence is outside selected contract bounds"
            )
        identities = [_ref_identity(value) for value in refs]
        if len(identities) != len(set(identities)):
            raise ProductionWorkOrderPlannerError("allowed input evidence contains duplicates")
        allowed_types = set(contract.allowed_input_ref_types)
        if any(value.ref_type not in allowed_types for value in refs):
            raise ProductionWorkOrderPlannerError(
                "allowed input evidence contains a disallowed ref type"
            )
        refs = tuple(sorted(refs, key=_ref_identity))

        task = self.runtime.get_task(resolution.route_input.task_id)
        if (
            int(task["revision"]) != resolution.route_input.task_revision
            or task["flow_id"] != resolution.route_input.flow_id
        ):
            raise ProductionWorkOrderPlannerError("Task changed before WorkOrder planning")
        task_projection = {
            "id": task["id"],
            "flow_id": task["flow_id"],
            "revision": int(task["revision"]),
            "content_hash": resolution.route_input.task_content_hash,
            "status": task["status"],
            "objective": task["objective"],
            "acceptance_criteria": _stored_list(
                task["acceptance_criteria_json"], "acceptance_criteria_json"
            ),
            "constraints": _stored_list(task["constraints_json"], "constraints_json"),
            "required_capabilities": list(resolution.route_input.required_capabilities),
            "budget": _stored_object(task["budget_json"], "budget_json"),
            "priority": int(task["priority"]),
        }
        context = {
            "task": task_projection,
            "route": route.to_dict(),
            "dispatch_catalog": {
                "dispatch_catalog_id": self.dispatch_catalog.dispatch_catalog_id,
                "dispatch_catalog_hash": self.dispatch_catalog.content_hash,
                "phase32_catalog_id": self.dispatch_catalog.phase32_catalog_id,
                "phase32_catalog_hash": self.dispatch_catalog.phase32_catalog_hash,
            },
            "dispatch_contract": contract.to_dict(),
            "payload_schema": schema,
            "allowed_input_refs": [value.to_dict() for value in refs],
        }
        canonical_bytes(context)
        return route, contract, refs, payload_schema, context

    def propose(
        self,
        route_decision_id: str,
        *,
        allowed_input_refs: Sequence[WorkOrderInputRef] = (),
        model_profile: str | None = None,
    ) -> WorkOrderPlannerResult:
        route, contract, allowed_refs, payload_schema, context = self._preflight(
            route_decision_id,
            allowed_input_refs,
        )
        run_id = create_run(
            self.runtime.store,
            None,
            role="WORK_ORDER_PLANNER",
            model_profile=model_profile or self.model.model_id,
        )
        request = ModelRequest(
            run_id=run_id,
            task_id=None,
            instructions=WORK_ORDER_PLANNER_INSTRUCTIONS,
            context=context,
            response_schema=_response_schema(contract, payload_schema),
        )
        request_hash = _request_hash(request)
        try:
            response = self.model.generate(request)
            if not isinstance(response, ModelResponse) or not response.model_id:
                raise ProductionWorkOrderPlannerError(
                    "WorkOrder planner model returned an invalid response envelope"
                )
            proposal = parse_work_order_proposal(
                response.text,
                contract=contract,
                allowed_input_refs=allowed_refs,
            )
            try:
                work_order = create_current_work_order(
                    self.runtime,
                    self.capability_store,
                    self.dispatch_catalog,
                    self.validator_registry,
                    route.route_decision_id,
                    input_refs=proposal.input_refs,
                    payload=proposal.payload,
                )
            except ProductionWorkOrderError as exc:
                raise ProductionWorkOrderPlannerError(
                    "model proposal failed current infrastructure WorkOrder construction"
                ) from exc
            response_hash = _text_hash(response.text)
            verification_id = self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="work-order-planner-generation",
                verifier="OriginForge.BoundedProductionWorkOrderPlanner",
                status="PASS",
                evidence={
                    "route_decision_id": route.route_decision_id,
                    "route_decision_hash": route.content_hash,
                    "task_id": work_order.task_id,
                    "task_revision": work_order.task_revision,
                    "task_content_hash": work_order.task_content_hash,
                    "dispatch_catalog_id": work_order.dispatch_catalog_id,
                    "dispatch_catalog_hash": work_order.dispatch_catalog_hash,
                    "dispatch_contract_id": work_order.dispatch_contract_id,
                    "dispatch_contract_hash": work_order.dispatch_contract_hash,
                    "validator_id": contract.validator_id,
                    "validator_fingerprint": contract.validator_fingerprint,
                    "payload_schema_id": contract.payload_schema_id,
                    "payload_schema_hash": contract.payload_schema_hash,
                    "request_hash": request_hash,
                    "response_hash": response_hash,
                    "proposal_hash": proposal.content_hash,
                    "proposal": proposal.to_dict(),
                    "work_order_id": work_order.work_order_id,
                    "work_order_hash": work_order.content_hash,
                    "work_order": work_order.to_dict(),
                    "model_id": response.model_id,
                    "model_hash": response.model_hash,
                    "audited": False,
                    "dispatched": False,
                },
                metrics={
                    "response_bytes": len(response.text.encode("utf-8")),
                    "allowed_input_refs": len(allowed_refs),
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
            return WorkOrderPlannerResult(
                run_id=run_id,
                route_decision_id=route.route_decision_id,
                route_decision_hash=route.content_hash,
                request_hash=request_hash,
                response_hash=response_hash,
                proposal_hash=proposal.content_hash,
                work_order=work_order,
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
