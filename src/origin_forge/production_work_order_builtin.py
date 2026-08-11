from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from .production_capability_models import CapabilityCatalog
from .production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
    WorkOrderInputRef,
    content_hash,
)
from .production_work_order_validators import (
    DispatchContractValidatorRegistry,
    DispatchPayloadValidator,
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)


_CODE_ADAPTER_ID = "originforge.code.bounded-retry"
_CODE_VALIDATOR_ID = "validator.code.bounded-retry@1"
_CODE_SCHEMA_ID = "schema.code.bounded-retry@1"
_MAX_CONTEXT_PATHS = 64
_MAX_PATH_CHARS = 512


class BuiltinDispatchReviewStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    DEFERRED_INPUT_EVIDENCE_RESOLUTION = "DEFERRED_INPUT_EVIDENCE_RESOLUTION"
    NO_PHASE32_ADAPTER = "NO_PHASE32_ADAPTER"
    DEFERRED_BACKEND = "DEFERRED_BACKEND"


@dataclass(frozen=True)
class BuiltinDispatchReview:
    adapter_id: str
    status: BuiltinDispatchReviewStatus
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "adapter_id": self.adapter_id,
            "status": self.status.value,
            "reason": self.reason,
        }


def builtin_dispatch_review() -> tuple[BuiltinDispatchReview, ...]:
    """Document the reviewed v1 dispatch-contract inclusion boundary.

    Absence from the dispatch catalog is intentional. Phase-32 route inventory
    is broader than Phase-33 dispatch eligibility until exact phase-specific
    evidence references can be independently resolved and revalidated.
    """

    deferred = (
        "originforge.pixelorama.export",
        "originforge.blender.model3d",
        "originforge.image.generate",
        "originforge.vision.inspect",
        "originforge.audio.ffmpeg",
        "originforge.audio.piper",
        "originforge.runtime.observe",
        "originforge.playtest.cooperative",
        "originforge.simulation.deterministic",
    )
    rows = [
        BuiltinDispatchReview(
            _CODE_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "bounded retry drive inputs are finite context-selection data; model and sandbox authority remain infrastructure-injected",
        )
    ]
    rows.extend(
        BuiltinDispatchReview(
            adapter_id,
            BuiltinDispatchReviewStatus.DEFERRED_INPUT_EVIDENCE_RESOLUTION,
            "backend requires exact phase-specific request/spec/profile/source evidence that Phase 33 does not yet resolve generically",
        )
        for adapter_id in deferred
    )
    rows.extend(
        (
            BuiltinDispatchReview(
                "design.specify",
                BuiltinDispatchReviewStatus.NO_PHASE32_ADAPTER,
                "Phase 32 intentionally defines the capability without a built-in executor",
            ),
            BuiltinDispatchReview(
                "blockbench",
                BuiltinDispatchReviewStatus.DEFERRED_BACKEND,
                "Phase 20B remains deferred and Phase 32 exposes no Blockbench adapter",
            ),
        )
    )
    return tuple(sorted(rows, key=lambda value: value.adapter_id))


def _portable_context_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_PATH_CHARS
        or "\\" in value
        or value.startswith("/")
    ):
        raise DispatchValidatorError("coding context path is not a bounded POSIX-relative path")
    path = PurePosixPath(value)
    parts = path.parts
    if (
        not parts
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0] in {".git", ".origin-forge"}
    ):
        raise DispatchValidatorError("coding context path is protected or non-portable")
    normalized = path.as_posix()
    if normalized != value:
        raise DispatchValidatorError("coding context path is not canonical")
    return normalized


class CodeBoundedRetryDispatchValidator:
    """Pure WorkOrder validator for `BoundedRetryPolicy.drive()` input only."""

    _IMPLEMENTATION_ID = "origin-forge-code-bounded-retry-work-order-validator@1"

    def __init__(self) -> None:
        self._base = StaticObjectPayloadValidator(
            validator_id=_CODE_VALIDATOR_ID,
            payload_schema_id=_CODE_SCHEMA_ID,
            fields=(
                PayloadFieldRule(
                    "context_mode",
                    PayloadFieldKind.STRING,
                    allowed_values=("auto", "manual"),
                    max_string_chars=16,
                ),
                PayloadFieldRule(
                    "context_seed_paths",
                    PayloadFieldKind.STRING_LIST,
                    required=False,
                    max_string_chars=_MAX_PATH_CHARS,
                    max_items=_MAX_CONTEXT_PATHS,
                ),
                PayloadFieldRule(
                    "selected_paths",
                    PayloadFieldKind.STRING_LIST,
                    required=False,
                    max_string_chars=_MAX_PATH_CHARS,
                    max_items=_MAX_CONTEXT_PATHS,
                ),
                PayloadFieldRule(
                    "semantic_context",
                    PayloadFieldKind.BOOLEAN,
                    required=False,
                ),
                PayloadFieldRule(
                    "structural_context",
                    PayloadFieldKind.BOOLEAN,
                    required=False,
                ),
            ),
        )
        self._fingerprint = content_hash(
            {
                "implementation_id": self._IMPLEMENTATION_ID,
                "base_validator_fingerprint": self._base.validator_fingerprint,
                "cross_field_contract": {
                    "auto": "selected_paths empty; context_seed_paths optional",
                    "manual": "selected_paths non-empty; context_seed_paths empty",
                    "paths": "canonical bounded POSIX-relative; .git/.origin-forge protected",
                    "defaults": {
                        "selected_paths": [],
                        "context_seed_paths": [],
                        "structural_context": False,
                        "semantic_context": False,
                    },
                },
            }
        )

    @property
    def validator_id(self) -> str:
        return self._base.validator_id

    @property
    def validator_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def payload_schema_id(self) -> str:
        return self._base.payload_schema_id

    @property
    def payload_schema_hash(self) -> str:
        return self._base.payload_schema_hash

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if input_refs:
            raise DispatchValidatorError(
                "bounded coding WorkOrder accepts no generic evidence refs in v1"
            )
        normalized = self._base.validate(payload, input_refs)
        selected = [
            _portable_context_path(value)
            for value in normalized.get("selected_paths", [])
        ]
        seeds = [
            _portable_context_path(value)
            for value in normalized.get("context_seed_paths", [])
        ]
        mode = normalized["context_mode"]
        if mode == "manual":
            if not selected:
                raise DispatchValidatorError(
                    "manual coding context requires selected_paths"
                )
            if seeds:
                raise DispatchValidatorError(
                    "manual coding context cannot contain context_seed_paths"
                )
        elif mode == "auto":
            if selected:
                raise DispatchValidatorError(
                    "automatic coding context cannot contain selected_paths"
                )
        else:
            raise AssertionError(mode)
        return {
            "context_mode": mode,
            "selected_paths": selected,
            "context_seed_paths": seeds,
            "structural_context": normalized.get("structural_context", False),
            "semantic_context": normalized.get("semantic_context", False),
        }


def builtin_dispatch_validators() -> tuple[DispatchPayloadValidator, ...]:
    return (CodeBoundedRetryDispatchValidator(),)


def build_builtin_dispatch_validator_registry() -> DispatchContractValidatorRegistry:
    return DispatchContractValidatorRegistry(builtin_dispatch_validators())


def build_builtin_dispatch_catalog(
    phase32_catalog: CapabilityCatalog,
) -> DispatchContractCatalog:
    """Build dispatch inventory only for reviewed currently-safe adapter inputs."""

    if not isinstance(phase32_catalog, CapabilityCatalog):
        raise TypeError("phase32_catalog must be a CapabilityCatalog")
    try:
        adapter = phase32_catalog.adapter(_CODE_ADAPTER_ID)
    except KeyError as exc:
        raise ValueError(
            "Phase-32 catalog lacks the reviewed bounded coding adapter"
        ) from exc
    validator = CodeBoundedRetryDispatchValidator()
    contract = DispatchContract(
        contract_id="code.bounded-retry@1",
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(),
        max_payload_bytes=64 * 1024,
        max_input_refs=0,
    )
    return DispatchContractCatalog.create(phase32_catalog, (contract,))
