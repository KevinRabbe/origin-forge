from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .ids import IdKind, validate_id
from .image_vision_service import ImageGenerationServiceResult
from .lineage import OriginForgeLineage
from .orchestration_policy import PolicyResult
from .production_dispatch_binding import CodeBoundedRetryInputBinder
from .production_dispatch_binding_models import BindingAuditStatus, DispatchBinding
from .production_dispatch_binding_simulation import DeterministicSimulationInputBinder
from .production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
from .production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    inspect_dispatch_claim_currentness_readonly,
    read_dispatch_claim,
)
from .production_dispatch_execution import (
    StartedDispatchExecution,
    begin_dispatch_execution,
    mark_dispatch_execution_raised,
    mark_dispatch_execution_returned,
)
from .production_dispatch_execution_models import (
    DispatchExecution,
    DispatchExecutionStatus,
)
from .production_dispatch_read import (
    ProductionDispatchReadError,
    read_dispatch_binding,
    read_dispatch_binding_audit,
)
from .production_execution_owner import (
    ProductionExecutionOwnerError,
    build_builtin_execution_owner_registry,
)
from .production_pixelorama_export import PixeloramaCliExportServiceResult
from .production_work_order_builtin import (
    CodeBoundedRetryDispatchValidator,
    DispatchValidatorError,
)
from .production_work_order_models import content_hash
from .runtime import OriginForgeRuntime
from .runtime_observation_models import (
    canonical_bytes as simulation_canonical_bytes,
    content_hash as simulation_content_hash,
)
from .simulation_models import (
    SimulationInvariant,
    SimulationModelError,
    SimulationRule,
    SimulationSpec,
)
from .simulation_service import SimulationService, SimulationServiceResult
from .simulation_spec_template import (
    SIMULATION_ENGINE_ID,
    SIMULATION_ENGINE_VERSION,
    SimulationSpecTemplate,
)
from .state import RunStatus, TaskStatus


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_EXCEPTION_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,255}$")
_BOUNDED_OWNER_ID = "originforge.execution.bounded-retry@1"
_BOUNDED_ADAPTER_ID = "originforge.code.bounded-retry"
_BOUNDED_CONTRACT_ID = "code.bounded-retry@1"
_BOUNDED_BINDER_ID = "binder.code.bounded-retry@1"
_BOUNDED_REQUEST_TYPE_ID = "BoundedRetryPolicy.drive@1"
_SIMULATION_OWNER_ID = "originforge.execution.simulation.deterministic@1"
_SIMULATION_ADAPTER_ID = "originforge.simulation.deterministic"
_SIMULATION_CONTRACT_ID = "simulation.deterministic@1"
_SIMULATION_BINDER_ID = "binder.simulation.deterministic@1"
_SIMULATION_REQUEST_TYPE_ID = "SimulationService.execute@production-v1"
_BOUNDED_RETURNED_DETAIL = "trusted bounded-retry execution owner returned normally"
_SIMULATION_RETURNED_DETAIL = "trusted deterministic simulation execution owner returned normally"
_BOUNDED_REQUEST_FIELDS = {
    "task_id",
    "selected_paths",
    "auto_context",
    "context_seed_paths",
    "structural_context",
    "semantic_context",
}
_SIMULATION_REQUEST_FIELDS = {
    "task_id",
    "engine_id",
    "engine_version",
    "seed",
    "replicates",
    "max_steps",
    "stall_steps",
    "initial_state",
    "rules",
    "invariants",
}
_SIMULATION_RULE_FIELDS = {
    "rule_id",
    "priority",
    "probability_ppm",
    "requires",
    "consume",
    "produce",
}
_SIMULATION_INVARIANT_FIELDS = {
    "invariant_id",
    "variable",
    "minimum",
    "maximum",
}


class ProductionDispatchInvocationError(RuntimeError):
    pass


class ProductionDispatchInvocationRecoveryRequired(ProductionDispatchInvocationError):
    """The owner boundary was crossed and the durable STARTED receipt must be reviewed."""

    def __init__(self, execution_id: str, reason_code: str):
        if not isinstance(execution_id, str) or not validate_id(
            execution_id,
            IdKind.DISPATCH_EXECUTION,
        ):
            raise ValueError("recovery error requires a valid DISPEXEC ID")
        if reason_code not in {
            "STARTED_RELATION_MISMATCH",
            "OWNER_RETURN_CONTRACT_MISMATCH",
            "RETURNED_TERMINALIZATION_FAILED",
            "RAISED_TERMINALIZATION_FAILED",
        }:
            raise ValueError("recovery error reason_code is unsupported")
        self.execution_id = execution_id
        self.reason_code = reason_code
        super().__init__(
            f"dispatch execution {execution_id} requires explicit recovery: {reason_code}"
        )


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ProductionDispatchInvocationError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _expected_revision(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ProductionDispatchInvocationError(
            "expected_claim_revision must be a non-negative integer"
        )
    return value


def _path_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProductionDispatchInvocationError(f"{label} must be a canonical string list")
    return tuple(value)


def _exception_type_commitment(exc: Exception) -> str:
    candidate = f"{type(exc).__module__}.{type(exc).__qualname__}"
    if _EXCEPTION_TYPE_RE.fullmatch(candidate) is not None:
        return candidate
    candidate = type(exc).__name__
    if _EXCEPTION_TYPE_RE.fullmatch(candidate) is not None:
        return candidate
    return "Exception"


@dataclass(frozen=True)
class BoundedRetryInvocationRequest:
    """Strict in-memory view of the exact frozen Phase-34 drive projection."""

    task_id: str
    selected_paths: tuple[str, ...]
    auto_context: bool
    context_seed_paths: tuple[str, ...]
    structural_context: bool
    semantic_context: bool
    request_content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not validate_id(self.task_id, IdKind.TASK):
            raise ProductionDispatchInvocationError(
                "invocation request task_id must be a valid TASK ID"
            )
        selected = tuple(self.selected_paths)
        seeds = tuple(self.context_seed_paths)
        if any(not isinstance(value, str) for value in selected):
            raise ProductionDispatchInvocationError(
                "invocation selected_paths must contain only strings"
            )
        if any(not isinstance(value, str) for value in seeds):
            raise ProductionDispatchInvocationError(
                "invocation context_seed_paths must contain only strings"
            )
        object.__setattr__(self, "selected_paths", selected)
        object.__setattr__(self, "context_seed_paths", seeds)
        for value, label in (
            (self.auto_context, "auto_context"),
            (self.structural_context, "structural_context"),
            (self.semantic_context, "semantic_context"),
        ):
            if type(value) is not bool:
                raise ProductionDispatchInvocationError(
                    f"invocation {label} must be an exact boolean"
                )
        _digest(self.request_content_hash, "request_content_hash")

        validator = CodeBoundedRetryDispatchValidator()
        payload = {
            "context_mode": "auto" if self.auto_context else "manual",
            "selected_paths": list(selected),
            "context_seed_paths": list(seeds),
            "structural_context": self.structural_context,
            "semantic_context": self.semantic_context,
        }
        try:
            normalized = validator.validate(payload, ())
        except DispatchValidatorError as exc:
            raise ProductionDispatchInvocationError(
                "frozen invocation request violates bounded coding context contract"
            ) from exc
        expected_payload = {
            "context_mode": payload["context_mode"],
            "selected_paths": list(selected),
            "context_seed_paths": list(seeds),
            "structural_context": self.structural_context,
            "semantic_context": self.semantic_context,
        }
        if normalized != expected_payload:
            raise ProductionDispatchInvocationError(
                "frozen invocation request is not canonical under the trusted validator"
            )
        if content_hash(self.projection_dict()) != self.request_content_hash:
            raise ProductionDispatchInvocationError(
                "frozen invocation request content hash does not recompute"
            )

    def projection_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "selected_paths": list(self.selected_paths),
            "auto_context": self.auto_context,
            "context_seed_paths": list(self.context_seed_paths),
            "structural_context": self.structural_context,
            "semantic_context": self.semantic_context,
        }


@dataclass(frozen=True)
class SimulationInvocationRequest:
    """Strict in-memory view of one exact frozen simulation semantic request."""

    task_id: str
    template: SimulationSpecTemplate
    request_content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not validate_id(self.task_id, IdKind.TASK):
            raise ProductionDispatchInvocationError(
                "simulation invocation task_id must be a valid TASK ID"
            )
        if not isinstance(self.template, SimulationSpecTemplate):
            raise TypeError("template must be a SimulationSpecTemplate")
        _digest(self.request_content_hash, "request_content_hash")
        if content_hash(self.projection_dict()) != self.request_content_hash:
            raise ProductionDispatchInvocationError(
                "simulation invocation request content hash does not recompute"
            )

    def projection_dict(self) -> dict[str, object]:
        return {"task_id": self.task_id, **self.template.to_dict()}


@dataclass(frozen=True)
class CompletedDispatchInvocation:
    """Synchronous non-canonical wrapper around exactly one reviewed owner return."""

    execution: DispatchExecution
    policy_result: PolicyResult | None = None
    simulation_result: SimulationServiceResult | None = None
    pixelorama_result: PixeloramaCliExportServiceResult | None = None
    image_result: ImageGenerationServiceResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution, DispatchExecution):
            raise TypeError("execution must be a DispatchExecution")
        if self.execution.status is not DispatchExecutionStatus.RETURNED:
            raise ProductionDispatchInvocationError(
                "completed invocation wrapper requires RETURNED execution"
            )
        has_policy = self.policy_result is not None
        has_simulation = self.simulation_result is not None
        has_pixelorama = self.pixelorama_result is not None
        has_image = self.image_result is not None
        if sum((has_policy, has_simulation, has_pixelorama, has_image)) != 1:
            raise ProductionDispatchInvocationError(
                "completed invocation requires exactly one reviewed owner result"
            )
        if self.execution.execution_owner_id == _BOUNDED_OWNER_ID:
            if (
                not isinstance(self.policy_result, PolicyResult)
                or has_simulation
                or has_pixelorama
            ):
                raise ProductionDispatchInvocationError(
                    "bounded execution requires exactly one PolicyResult"
                )
            if self.execution.task_id != self.policy_result.task_id:
                raise ProductionDispatchInvocationError(
                    "completed invocation Task relation drifted"
                )
        elif self.execution.execution_owner_id == _SIMULATION_OWNER_ID:
            if (
                not isinstance(self.simulation_result, SimulationServiceResult)
                or has_policy
                or has_pixelorama
            ):
                raise ProductionDispatchInvocationError(
                    "simulation execution requires exactly one SimulationServiceResult"
                )
        elif self.execution.execution_owner_id == "originforge.execution.pixelorama.spritesheet-export@1":
            if (
                not isinstance(self.pixelorama_result, PixeloramaCliExportServiceResult)
                or has_policy
                or has_simulation
                or has_image
            ):
                raise ProductionDispatchInvocationError(
                    "Pixelorama execution requires exactly one PixeloramaCliExportServiceResult"
                )
        elif self.execution.execution_owner_id == "originforge.execution.image.generate@1":
            if (
                not isinstance(self.image_result, ImageGenerationServiceResult)
                or has_policy
                or has_simulation
                or has_pixelorama
            ):
                raise ProductionDispatchInvocationError(
                    "image execution requires exactly one ImageGenerationServiceResult"
                )
        else:
            raise ProductionDispatchInvocationError(
                "completed invocation has an unsupported execution owner"
            )

    @property
    def execution_id(self) -> str:
        return self.execution.execution_id

def _require_trusted_relation(
    binding: DispatchBinding,
    *,
    descriptor,
    expected_owner_id: str,
    expected_adapter_id: str,
    expected_contract_id: str,
    expected_binder_id: str,
    expected_request_type_id: str,
) -> None:
    if (
        binding.selected_adapter_id != expected_adapter_id
        or binding.dispatch_contract_id != expected_contract_id
        or binding.binder_id != expected_binder_id
        or binding.request_type_id != expected_request_type_id
        or binding.binder_id != descriptor.binder_id
        or binding.binder_fingerprint != descriptor.binder_fingerprint
        or binding.selected_adapter_id != descriptor.adapter_id
        or binding.dispatch_contract_id != descriptor.dispatch_contract_id
        or binding.request_type_id != descriptor.request_type_id
        or binding.request_schema_hash != descriptor.request_schema_hash
    ):
        raise ProductionDispatchInvocationError(
            "dispatch binding does not match the exact current trusted owner relation"
        )
    try:
        owner = build_builtin_execution_owner_registry().owner_for(
            adapter_id=binding.selected_adapter_id,
            adapter_fingerprint=binding.selected_adapter_fingerprint,
            dispatch_contract_id=binding.dispatch_contract_id,
            binder_id=binding.binder_id,
            binder_fingerprint=binding.binder_fingerprint,
            request_type_id=binding.request_type_id,
            request_schema_hash=binding.request_schema_hash,
        )
    except ProductionExecutionOwnerError as exc:
        raise ProductionDispatchInvocationError(
            "dispatch binding has no exact current trusted execution owner"
        ) from exc
    if owner.owner_id != expected_owner_id:
        raise ProductionDispatchInvocationError(
            "dispatch binding resolved to an unexpected execution owner"
        )


def _require_trusted_bounded_retry_relation(binding: DispatchBinding) -> None:
    _require_trusted_relation(
        binding,
        descriptor=CodeBoundedRetryInputBinder().descriptor,
        expected_owner_id=_BOUNDED_OWNER_ID,
        expected_adapter_id=_BOUNDED_ADAPTER_ID,
        expected_contract_id=_BOUNDED_CONTRACT_ID,
        expected_binder_id=_BOUNDED_BINDER_ID,
        expected_request_type_id=_BOUNDED_REQUEST_TYPE_ID,
    )


def _require_trusted_simulation_relation(binding: DispatchBinding) -> None:
    _require_trusted_relation(
        binding,
        descriptor=DeterministicSimulationInputBinder().descriptor,
        expected_owner_id=_SIMULATION_OWNER_ID,
        expected_adapter_id=_SIMULATION_ADAPTER_ID,
        expected_contract_id=_SIMULATION_CONTRACT_ID,
        expected_binder_id=_SIMULATION_BINDER_ID,
        expected_request_type_id=_SIMULATION_REQUEST_TYPE_ID,
    )


def _decode_bounded_request_projection(binding: DispatchBinding) -> BoundedRetryInvocationRequest:
    projection = binding.request_projection
    if not isinstance(projection, dict) or set(projection) != _BOUNDED_REQUEST_FIELDS:
        raise ProductionDispatchInvocationError(
            "bounded-retry request projection schema drifted"
        )
    if type(projection["auto_context"]) is not bool:
        raise ProductionDispatchInvocationError(
            "bounded-retry auto_context must be an exact boolean"
        )
    if type(projection["structural_context"]) is not bool:
        raise ProductionDispatchInvocationError(
            "bounded-retry structural_context must be an exact boolean"
        )
    if type(projection["semantic_context"]) is not bool:
        raise ProductionDispatchInvocationError(
            "bounded-retry semantic_context must be an exact boolean"
        )
    return BoundedRetryInvocationRequest(
        task_id=projection["task_id"],
        selected_paths=_path_tuple(projection["selected_paths"], "selected_paths"),
        auto_context=projection["auto_context"],
        context_seed_paths=_path_tuple(
            projection["context_seed_paths"],
            "context_seed_paths",
        ),
        structural_context=projection["structural_context"],
        semantic_context=projection["semantic_context"],
        request_content_hash=binding.request_content_hash,
    )


def _decode_request_projection(binding: DispatchBinding) -> BoundedRetryInvocationRequest:
    """Phase-37 compatibility alias for the accepted bounded-code decoder."""

    return _decode_bounded_request_projection(binding)


def _simulation_pairs(value: object, label: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ProductionDispatchInvocationError(
            f"simulation {label} must be a canonical object"
        )
    return tuple((key, item) for key, item in value.items())


def _simulation_rule(value: object) -> SimulationRule:
    if not isinstance(value, dict) or set(value) != _SIMULATION_RULE_FIELDS:
        raise ProductionDispatchInvocationError("simulation rule projection schema drifted")
    try:
        return SimulationRule(
            rule_id=value["rule_id"],
            priority=value["priority"],
            probability_ppm=value["probability_ppm"],
            requires=_simulation_pairs(value["requires"], "rule requires"),
            consume=_simulation_pairs(value["consume"], "rule consume"),
            produce=_simulation_pairs(value["produce"], "rule produce"),
        )
    except (SimulationModelError, TypeError, ValueError) as exc:
        raise ProductionDispatchInvocationError(
            "simulation rule projection violates Phase-25 bounds"
        ) from exc


def _simulation_invariant(value: object) -> SimulationInvariant:
    if not isinstance(value, dict) or set(value) != _SIMULATION_INVARIANT_FIELDS:
        raise ProductionDispatchInvocationError(
            "simulation invariant projection schema drifted"
        )
    try:
        return SimulationInvariant(
            invariant_id=value["invariant_id"],
            variable=value["variable"],
            minimum=value["minimum"],
            maximum=value["maximum"],
        )
    except (SimulationModelError, TypeError, ValueError) as exc:
        raise ProductionDispatchInvocationError(
            "simulation invariant projection violates Phase-25 bounds"
        ) from exc


def _decode_simulation_request_projection(binding: DispatchBinding) -> SimulationInvocationRequest:
    projection = binding.request_projection
    if not isinstance(projection, dict) or set(projection) != _SIMULATION_REQUEST_FIELDS:
        raise ProductionDispatchInvocationError(
            "simulation request projection schema drifted"
        )
    if (
        projection["engine_id"] != SIMULATION_ENGINE_ID
        or projection["engine_version"] != SIMULATION_ENGINE_VERSION
    ):
        raise ProductionDispatchInvocationError(
            "simulation request projection engine identity drifted"
        )
    if not isinstance(projection["rules"], list) or not isinstance(
        projection["invariants"], list
    ):
        raise ProductionDispatchInvocationError(
            "simulation request projection list fields drifted"
        )
    try:
        template = SimulationSpecTemplate.create(
            seed=projection["seed"],
            replicates=projection["replicates"],
            max_steps=projection["max_steps"],
            stall_steps=projection["stall_steps"],
            initial_state=_simulation_pairs(projection["initial_state"], "initial_state"),
            rules=tuple(_simulation_rule(value) for value in projection["rules"]),
            invariants=tuple(
                _simulation_invariant(value) for value in projection["invariants"]
            ),
        )
    except ProductionDispatchInvocationError:
        raise
    except (SimulationModelError, TypeError, ValueError) as exc:
        raise ProductionDispatchInvocationError(
            "simulation request projection violates Phase-25 template bounds"
        ) from exc
    request = SimulationInvocationRequest(
        task_id=projection["task_id"],
        template=template,
        request_content_hash=binding.request_content_hash,
    )
    if request.projection_dict() != projection:
        raise ProductionDispatchInvocationError(
            "simulation request projection is not canonical under trusted template semantics"
        )
    return request


def _read_frozen_request_evidence(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_claim_revision: int,
) -> tuple[DispatchClaim, DispatchBinding]:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(claim_id, str) or not validate_id(claim_id, IdKind.DISPATCH_CLAIM):
        raise ProductionDispatchInvocationError(
            "claim_id must be a valid DISPCLAIM ID"
        )
    expected_claim_revision = _expected_revision(expected_claim_revision)

    currentness = inspect_dispatch_claim_currentness_readonly(runtime, claim_id)
    if currentness.status is not DispatchClaimCurrentnessStatus.CURRENT_ACTIVE:
        raise ProductionDispatchInvocationError(
            f"dispatch claim is not CURRENT_ACTIVE: {currentness.status.value}"
        )
    claim = read_dispatch_claim(runtime, claim_id)
    if claim.status is not DispatchClaimStatus.ACTIVE:
        raise ProductionDispatchInvocationError("dispatch claim is not ACTIVE")
    if claim.revision != expected_claim_revision:
        raise ProductionDispatchInvocationError(
            "dispatch claim revision changed before invocation request freeze"
        )

    try:
        binding = read_dispatch_binding(runtime, claim.dispatch_binding_id)
        audit = read_dispatch_binding_audit(runtime, claim.binding_audit_id)
    except ProductionDispatchReadError as exc:
        raise ProductionDispatchInvocationError(
            "exact Phase-34 invocation evidence could not be read"
        ) from exc

    if (
        binding.content_hash != claim.dispatch_binding_hash
        or binding.dispatch_binding_id != claim.dispatch_binding_id
        or binding.task_id != claim.task_id
        or binding.task_revision != claim.task_revision
        or binding.task_content_hash != claim.task_content_hash
        or binding.selected_adapter_id != claim.selected_adapter_id
        or binding.selected_adapter_fingerprint != claim.selected_adapter_fingerprint
        or binding.dispatch_contract_id != claim.dispatch_contract_id
        or binding.dispatch_contract_hash != claim.dispatch_contract_hash
        or binding.binder_id != claim.binder_id
        or binding.binder_fingerprint != claim.binder_fingerprint
    ):
        raise ProductionDispatchInvocationError(
            "dispatch claim does not bind the exact Phase-34 invocation relation"
        )
    if (
        audit.status is not BindingAuditStatus.PASS
        or audit.content_hash != claim.binding_audit_hash
        or audit.binding_audit_id != claim.binding_audit_id
        or audit.dispatch_binding_id != binding.dispatch_binding_id
        or audit.dispatch_binding_hash != binding.content_hash
        or audit.binder_id != binding.binder_id
        or audit.binder_fingerprint != binding.binder_fingerprint
        or audit.request_type_id != binding.request_type_id
        or audit.request_schema_hash != binding.request_schema_hash
        or audit.request_content_hash != binding.request_content_hash
    ):
        raise ProductionDispatchInvocationError(
            "binding audit does not authorize the exact frozen invocation request"
        )
    return claim, binding


def freeze_bounded_retry_invocation_request(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_claim_revision: int,
) -> BoundedRetryInvocationRequest:
    """Freeze the exact persisted Phase-34 bounded-code projection for one ACTIVE claim."""

    claim, binding = _read_frozen_request_evidence(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    _require_trusted_bounded_retry_relation(binding)
    request = _decode_bounded_request_projection(binding)
    if request.task_id != claim.task_id:
        raise ProductionDispatchInvocationError(
            "frozen invocation request task_id does not match the exact claim Task"
        )
    return request


def _freeze_invocation_request(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_claim_revision: int,
) -> tuple[DispatchClaim, BoundedRetryInvocationRequest | SimulationInvocationRequest]:
    claim, binding = _read_frozen_request_evidence(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    if binding.request_type_id == _BOUNDED_REQUEST_TYPE_ID:
        _require_trusted_bounded_retry_relation(binding)
        request: BoundedRetryInvocationRequest | SimulationInvocationRequest = (
            _decode_bounded_request_projection(binding)
        )
    elif binding.request_type_id == _SIMULATION_REQUEST_TYPE_ID:
        _require_trusted_simulation_relation(binding)
        request = _decode_simulation_request_projection(binding)
    else:
        raise ProductionDispatchInvocationError(
            "dispatch binding request type has no reviewed production invocation owner"
        )
    if request.task_id != claim.task_id:
        raise ProductionDispatchInvocationError(
            "frozen invocation request task_id does not match the exact claim Task"
        )
    return claim, request


def _request_owner_id(
    request: BoundedRetryInvocationRequest | SimulationInvocationRequest,
) -> str:
    if isinstance(request, BoundedRetryInvocationRequest):
        return _BOUNDED_OWNER_ID
    if isinstance(request, SimulationInvocationRequest):
        return _SIMULATION_OWNER_ID
    raise TypeError("request has unsupported invocation type")


def _request_type_id(
    request: BoundedRetryInvocationRequest | SimulationInvocationRequest,
) -> str:
    if isinstance(request, BoundedRetryInvocationRequest):
        return _BOUNDED_REQUEST_TYPE_ID
    if isinstance(request, SimulationInvocationRequest):
        return _SIMULATION_REQUEST_TYPE_ID
    raise TypeError("request has unsupported invocation type")


def _require_started_matches_frozen(
    started: StartedDispatchExecution,
    claim: DispatchClaim,
    request: BoundedRetryInvocationRequest | SimulationInvocationRequest,
) -> None:
    if not isinstance(started, StartedDispatchExecution):
        raise TypeError("started must be a StartedDispatchExecution")
    execution = started.execution
    plan = started.dependencies.plan
    expected_owner_id = _request_owner_id(request)
    expected_request_type_id = _request_type_id(request)
    if (
        execution.claim_id != claim.claim_id
        or execution.claim_revision_at_start != claim.revision
        or execution.task_id != claim.task_id
        or execution.task_id != request.task_id
        or execution.dispatch_binding_id != claim.dispatch_binding_id
        or execution.dispatch_binding_hash != claim.dispatch_binding_hash
        or execution.execution_owner_id != expected_owner_id
        or plan.claim_id != claim.claim_id
        or plan.claim_revision != claim.revision
        or plan.task_id != request.task_id
        or plan.dispatch_binding_id != claim.dispatch_binding_id
        or plan.dispatch_binding_hash != claim.dispatch_binding_hash
        or plan.request_type_id != expected_request_type_id
        or plan.request_content_hash != request.request_content_hash
        or plan.owner_id != expected_owner_id
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id,
            "STARTED_RELATION_MISMATCH",
        )


def _simulation_spec(request: SimulationInvocationRequest) -> SimulationSpec:
    template = request.template
    return SimulationSpec.create(
        seed=template.seed,
        initial_state=template.initial_state,
        rules=template.rules,
        invariants=template.invariants,
        replicates=template.replicates,
        max_steps=template.max_steps,
        stall_steps=template.stall_steps,
        engine_id=template.engine_id,
        engine_version=template.engine_version,
    )


def _canonical_artifact_json(
    lineage: OriginForgeLineage,
    artifact_id: str,
    label: str,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        artifact = lineage.get_artifact(artifact_id)
        path = lineage.local_artifact_path(artifact_id)
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise ProductionDispatchInvocationError(
            f"simulation {label} artifact cannot be revalidated"
        ) from exc
    if not isinstance(value, dict) or simulation_canonical_bytes(value) != data:
        raise ProductionDispatchInvocationError(
            f"simulation {label} artifact is not exact canonical JSON"
        )
    return artifact, value


def _require_simulation_result_durable(
    runtime: OriginForgeRuntime,
    request: SimulationInvocationRequest,
    spec: SimulationSpec,
    result: SimulationServiceResult,
) -> None:
    if not isinstance(result, SimulationServiceResult):
        raise ProductionDispatchInvocationError(
            "simulation owner returned an invalid result type"
        )
    try:
        run = runtime.get_run(result.run_id)
        task = runtime.get_task(request.task_id)
    except (KeyError, RuntimeError) as exc:
        raise ProductionDispatchInvocationError(
            "simulation owner result Run/Task relation cannot be read"
        ) from exc
    if (
        run["task_id"] != request.task_id
        or run["role"] != SimulationService.RUN_ROLE
        or run["status"] != RunStatus.SUCCEEDED.value
        or task["status"] != TaskStatus.RUNNING.value
    ):
        raise ProductionDispatchInvocationError(
            "simulation owner result does not bind one SUCCEEDED SIMULATOR Run to RUNNING Task"
        )

    lineage = OriginForgeLineage(runtime)
    spec_artifact, spec_payload = _canonical_artifact_json(
        lineage,
        result.spec_artifact_id,
        "specification",
    )
    result_artifact, result_payload = _canonical_artifact_json(
        lineage,
        result.result_artifact_id,
        "result",
    )
    summary_artifact, summary_payload = _canonical_artifact_json(
        lineage,
        result.summary_artifact_id,
        "summary",
    )
    expected_locations = {
        result.spec_artifact_id: f".origin-forge/simulations/{spec.workspace_id}/request/spec.json",
        result.result_artifact_id: f".origin-forge/simulations/{spec.workspace_id}/evidence/result.json",
        result.summary_artifact_id: f".origin-forge/simulations/{spec.workspace_id}/evidence/summary.json",
    }
    if (
        spec_artifact["type"] != "SIMULATION_SPEC"
        or spec_artifact["created_by_run_id"] != result.run_id
        or spec_artifact["parent_artifact_id"] is not None
        or spec_artifact["status"] != "CAPTURED"
        or spec_artifact["path_or_uri"] != expected_locations[result.spec_artifact_id]
        or result_artifact["type"] != "SIMULATION_RESULT"
        or result_artifact["created_by_run_id"] != result.run_id
        or result_artifact["parent_artifact_id"] != result.spec_artifact_id
        or result_artifact["status"] != "CAPTURED"
        or result_artifact["path_or_uri"] != expected_locations[result.result_artifact_id]
        or summary_artifact["type"] != "SIMULATION_SUMMARY"
        or summary_artifact["created_by_run_id"] != result.run_id
        or summary_artifact["parent_artifact_id"] != result.result_artifact_id
        or summary_artifact["status"] != "DERIVED"
        or summary_artifact["path_or_uri"] != expected_locations[result.summary_artifact_id]
    ):
        raise ProductionDispatchInvocationError(
            "simulation owner durable artifact lineage does not match exact Phase-25 contract"
        )
    if spec_payload != spec.to_dict():
        raise ProductionDispatchInvocationError(
            "simulation owner durable specification differs from allocated concrete spec"
        )
    if (
        result_payload.get("session_id") != spec.session_id
        or result_payload.get("spec_hash") != spec.content_hash
        or result_payload.get("engine_id") != spec.engine_id
        or result_payload.get("engine_version") != spec.engine_version
        or simulation_content_hash(result_payload) != result.result_hash
    ):
        raise ProductionDispatchInvocationError(
            "simulation owner durable result does not bind exact concrete spec/result hash"
        )
    if (
        summary_payload != result.summary.to_dict()
        or summary_payload.get("spec_hash") != spec.content_hash
        or summary_payload.get("result_hash") != result.result_hash
    ):
        raise ProductionDispatchInvocationError(
            "simulation owner durable summary does not bind exact result"
        )

    try:
        verifications = runtime.list_verifications("RUN", result.run_id)
    except (KeyError, RuntimeError) as exc:
        raise ProductionDispatchInvocationError(
            "simulation owner Run verification cannot be read"
        ) from exc
    if len(verifications) != 1:
        raise ProductionDispatchInvocationError(
            "simulation owner requires exactly one canonical Run verification"
        )
    verification = verifications[0]
    try:
        evidence = json.loads(verification["evidence_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProductionDispatchInvocationError(
            "simulation owner Run verification evidence is invalid JSON"
        ) from exc
    expected_evidence = {
        "spec_id": spec.spec_id,
        "spec_hash": spec.content_hash,
        "session_id": spec.session_id,
        "engine_id": spec.engine_id,
        "engine_version": spec.engine_version,
        "result_hash": result.result_hash,
        "summary": result.summary.to_dict(),
        "spec_artifact_id": result.spec_artifact_id,
        "result_artifact_id": result.result_artifact_id,
        "summary_artifact_id": result.summary_artifact_id,
        "production_task_verified": False,
        "semantic_balance_verified": False,
        "automatic_tuning_authorized": False,
        "canonical_asset_adopted": False,
    }
    if (
        verification["verification_type"] != "simulation-structure"
        or verification["verifier"] != "OriginForge.SimulationService"
        or verification["status"] != "PASS"
        or verification["run_id"] != result.run_id
        or evidence != expected_evidence
    ):
        raise ProductionDispatchInvocationError(
            "simulation owner Run verification does not exactly authorize returned evidence"
        )


def _record_raised_or_recovery(
    runtime: OriginForgeRuntime,
    started: StartedDispatchExecution,
    frozen_claim: DispatchClaim,
    *,
    detail: str,
) -> None:
    try:
        mark_dispatch_execution_raised(
            runtime,
            started.execution.execution_id,
            started.execution.revision,
            frozen_claim.revision,
            detail,
        )
    except Exception as terminalization_exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            started.execution.execution_id,
            "RAISED_TERMINALIZATION_FAILED",
        ) from terminalization_exc


def _record_returned_or_recovery(
    runtime: OriginForgeRuntime,
    started: StartedDispatchExecution,
    frozen_claim: DispatchClaim,
    *,
    detail: str,
) -> DispatchExecution:
    try:
        return mark_dispatch_execution_returned(
            runtime,
            started.execution.execution_id,
            started.execution.revision,
            frozen_claim.revision,
            detail,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            started.execution.execution_id,
            "RETURNED_TERMINALIZATION_FAILED",
        ) from exc


def dispatch_claim_once(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_claim_revision: int,
) -> CompletedDispatchInvocation:
    """Invoke exactly one of the two reviewed production owners for one ACTIVE claim.

    There is deliberately no dispatcher-level retry or replay. Once STARTED is
    committed, any uncertain or failed terminalization state requires explicit
    Phase-36 recovery instead of a second owner call.
    """

    frozen_claim, request = _freeze_invocation_request(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    if (
        frozen_claim.status is not DispatchClaimStatus.ACTIVE
        or frozen_claim.revision != expected_claim_revision
        or frozen_claim.task_id != request.task_id
    ):
        raise ProductionDispatchInvocationError(
            "dispatch claim changed before execution ownership begin"
        )

    started = begin_dispatch_execution(
        runtime,
        claim_id,
        expected_claim_revision,
    )
    _require_started_matches_frozen(started, frozen_claim, request)

    if isinstance(request, BoundedRetryInvocationRequest):
        try:
            policy_result = started.dependencies.bounded_retry_policy.drive(
                task_id=request.task_id,
                selected_paths=request.selected_paths,
                auto_context=request.auto_context,
                context_seed_paths=request.context_seed_paths,
                structural_context=request.structural_context,
                semantic_context=request.semantic_context,
            )
        except Exception as exc:
            exception_type = _exception_type_commitment(exc)
            _record_raised_or_recovery(
                runtime,
                started,
                frozen_claim,
                detail=f"trusted bounded-retry execution owner raised {exception_type}",
            )
            raise ProductionDispatchInvocationError(
                "trusted bounded-retry execution owner raised "
                f"{exception_type}; dispatch execution "
                f"{started.execution.execution_id} recorded RAISED"
            ) from exc

        if not isinstance(policy_result, PolicyResult) or policy_result.task_id != request.task_id:
            raise ProductionDispatchInvocationRecoveryRequired(
                started.execution.execution_id,
                "OWNER_RETURN_CONTRACT_MISMATCH",
            )
        returned = _record_returned_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=_BOUNDED_RETURNED_DETAIL,
        )
        return CompletedDispatchInvocation(returned, policy_result)

    if isinstance(request, SimulationInvocationRequest):
        try:
            concrete_spec = _simulation_spec(request)
            simulation_result = SimulationService(runtime).execute(
                request.task_id,
                concrete_spec,
            )
        except Exception as exc:
            exception_type = _exception_type_commitment(exc)
            _record_raised_or_recovery(
                runtime,
                started,
                frozen_claim,
                detail=(
                    "trusted deterministic simulation execution owner raised "
                    f"{exception_type}"
                ),
            )
            raise ProductionDispatchInvocationError(
                "trusted deterministic simulation execution owner raised "
                f"{exception_type}; dispatch execution "
                f"{started.execution.execution_id} recorded RAISED"
            ) from exc

        try:
            _require_simulation_result_durable(
                runtime,
                request,
                concrete_spec,
                simulation_result,
            )
        except Exception as exc:
            raise ProductionDispatchInvocationRecoveryRequired(
                started.execution.execution_id,
                "OWNER_RETURN_CONTRACT_MISMATCH",
            ) from exc
        returned = _record_returned_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=_SIMULATION_RETURNED_DETAIL,
        )
        return CompletedDispatchInvocation(
            returned,
            simulation_result=simulation_result,
        )

    raise ProductionDispatchInvocationRecoveryRequired(
        started.execution.execution_id,
        "STARTED_RELATION_MISMATCH",
    )

_legacy_dispatch_claim_once = dispatch_claim_once
from .production_dispatch_invocation_pixelorama import (
    _dispatch_claim_once_three_owner as dispatch_claim_once,
)
