from __future__ import annotations

import re
from dataclasses import dataclass

from .ids import IdKind, validate_id
from .production_dispatch_binding import CodeBoundedRetryInputBinder
from .production_dispatch_binding_models import BindingAuditStatus, DispatchBinding
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    inspect_dispatch_claim_currentness_readonly,
    read_dispatch_claim,
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
from .production_work_order_builtin import (
    CodeBoundedRetryDispatchValidator,
    DispatchValidatorError,
)
from .production_work_order_models import content_hash
from .runtime import OriginForgeRuntime


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_OWNER_ID = "originforge.execution.bounded-retry@1"
_EXPECTED_ADAPTER_ID = "originforge.code.bounded-retry"
_EXPECTED_CONTRACT_ID = "code.bounded-retry@1"
_EXPECTED_BINDER_ID = "binder.code.bounded-retry@1"
_EXPECTED_REQUEST_TYPE_ID = "BoundedRetryPolicy.drive@1"
_REQUEST_FIELDS = {
    "task_id",
    "selected_paths",
    "auto_context",
    "context_seed_paths",
    "structural_context",
    "semantic_context",
}


class ProductionDispatchInvocationError(RuntimeError):
    pass


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


def _require_trusted_bounded_retry_relation(binding: DispatchBinding) -> None:
    binder = CodeBoundedRetryInputBinder().descriptor
    if (
        binding.selected_adapter_id != _EXPECTED_ADAPTER_ID
        or binding.dispatch_contract_id != _EXPECTED_CONTRACT_ID
        or binding.binder_id != _EXPECTED_BINDER_ID
        or binding.request_type_id != _EXPECTED_REQUEST_TYPE_ID
        or binding.binder_id != binder.binder_id
        or binding.binder_fingerprint != binder.binder_fingerprint
        or binding.selected_adapter_id != binder.adapter_id
        or binding.dispatch_contract_id != binder.dispatch_contract_id
        or binding.request_type_id != binder.request_type_id
        or binding.request_schema_hash != binder.request_schema_hash
    ):
        raise ProductionDispatchInvocationError(
            "dispatch binding does not match the current trusted bounded-retry binder relation"
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
    if owner.owner_id != _EXPECTED_OWNER_ID:
        raise ProductionDispatchInvocationError(
            "dispatch binding resolved to an unexpected execution owner"
        )


def _decode_request_projection(binding: DispatchBinding) -> BoundedRetryInvocationRequest:
    projection = binding.request_projection
    if not isinstance(projection, dict) or set(projection) != _REQUEST_FIELDS:
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


def freeze_bounded_retry_invocation_request(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_claim_revision: int,
) -> BoundedRetryInvocationRequest:
    """Freeze the exact persisted Phase-34 drive projection for one ACTIVE claim.

    This function is read-only. It does not assemble runtime dependencies, create
    a DISPEXEC receipt, invoke an execution owner, start a Run, or mutate Task,
    Workspace, Artifact, Verification, claim, or execution state.
    """

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

    _require_trusted_bounded_retry_relation(binding)
    request = _decode_request_projection(binding)
    if request.task_id != claim.task_id:
        raise ProductionDispatchInvocationError(
            "frozen invocation request task_id does not match the exact claim Task"
        )
    return request
