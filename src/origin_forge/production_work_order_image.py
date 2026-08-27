from __future__ import annotations

import math
from typing import Any

from .image_vision_models import (
    ImageOperationBudget,
    validate_sha256,
    workspace_relative_path,
)
from .production_work_order_models import WorkOrderInputRef, content_hash
from .production_work_order_validators import (
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)

IMAGE_ADAPTER_ID = "originforge.image.generate"
IMAGE_CONTRACT_ID = "image.generate@1"
IMAGE_VALIDATOR_ID = "validator.image.generate@1"
IMAGE_SCHEMA_ID = "schema.image.generate@1"
IMAGE_REQUEST_TYPE_ID = "ImageGenerationService.execute@production-v1"
IMAGE_OPERATION = "GENERATE"


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise DispatchValidatorError(f"{label} must be a bounded non-empty string")
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise DispatchValidatorError(f"{label} contains invalid characters")
    return value


def _guidance(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise DispatchValidatorError("guidance_scale must be a finite decimal string")
    try:
        result = float(value)
    except ValueError as exc:
        raise DispatchValidatorError("guidance_scale must be a finite decimal string") from exc
    if not math.isfinite(result) or not 0.0 <= result <= 100.0:
        raise DispatchValidatorError("guidance_scale must be between 0 and 100")
    return result


class ImageGenerationDispatchValidator:
    """Validate one inert, exact ComfyUI GENERATE WorkOrder payload."""

    def __init__(self) -> None:
        self._base = StaticObjectPayloadValidator(
            validator_id=IMAGE_VALIDATOR_ID,
            payload_schema_id=IMAGE_SCHEMA_ID,
            fields=(
                PayloadFieldRule("operation", PayloadFieldKind.STRING, allowed_values=(IMAGE_OPERATION,)),
                PayloadFieldRule("backend_version", PayloadFieldKind.STRING, max_string_chars=256),
                PayloadFieldRule("workflow_id", PayloadFieldKind.STRING, max_string_chars=256),
                PayloadFieldRule("workflow_hash", PayloadFieldKind.STRING, max_string_chars=71),
                PayloadFieldRule("model_id", PayloadFieldKind.STRING, max_string_chars=256),
                PayloadFieldRule("model_hash", PayloadFieldKind.STRING, max_string_chars=71),
                PayloadFieldRule("prompt", PayloadFieldKind.STRING, max_string_chars=16_384),
                PayloadFieldRule("negative_prompt", PayloadFieldKind.STRING, required=False, max_string_chars=16_384),
                PayloadFieldRule("width", PayloadFieldKind.INTEGER, min_integer=1, max_integer=4096),
                PayloadFieldRule("height", PayloadFieldKind.INTEGER, min_integer=1, max_integer=4096),
                PayloadFieldRule("seed", PayloadFieldKind.INTEGER, min_integer=0, max_integer=2**63 - 1),
                PayloadFieldRule("steps", PayloadFieldKind.INTEGER, min_integer=1, max_integer=1000),
                PayloadFieldRule("guidance_scale", PayloadFieldKind.STRING, max_string_chars=64),
                PayloadFieldRule("output_relative_paths", PayloadFieldKind.STRING_LIST, max_items=4, max_string_chars=4096),
                PayloadFieldRule("timeout_seconds", PayloadFieldKind.INTEGER, min_integer=1, max_integer=3600),
                PayloadFieldRule("max_output_bytes", PayloadFieldKind.INTEGER, min_integer=1, max_integer=128 * 1024 * 1024),
                PayloadFieldRule("max_history_bytes", PayloadFieldKind.INTEGER, min_integer=1, max_integer=16 * 1024 * 1024),
            ),
        )
        self._fingerprint = content_hash(
            {
                "implementation_id": "origin-forge-image-generation-work-order-validator@1",
                "base_validator_fingerprint": self._base.validator_fingerprint,
                "backend": "comfyui-local-only",
                "request_type": IMAGE_REQUEST_TYPE_ID,
                "guidance_encoding": "finite decimal string in WorkOrder; float only after validation",
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

    def schema_dict(self) -> dict[str, object]:
        return self._base.schema_dict()

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if input_refs:
            raise DispatchValidatorError("image GENERATE WorkOrder accepts no input refs")
        # WorkOrder construction stores the validator's normalized budget.  Frozen
        # re-audits therefore receive that derived field back; accept it only when
        # it exactly recomputes from the three canonical scalar limits.
        supplied_budget = payload.get("budget")
        base_payload = dict(payload)
        base_payload.pop("budget", None)
        # The canonical stored projection contains the normalized float, while
        # the external WorkOrder contract accepts a decimal text representation.
        if isinstance(base_payload.get("guidance_scale"), (int, float)) and not isinstance(
            base_payload.get("guidance_scale"), bool
        ):
            base_payload["guidance_scale"] = str(base_payload["guidance_scale"])
        normalized = self._base.validate(base_payload, input_refs)
        if normalized["operation"] != IMAGE_OPERATION:
            raise DispatchValidatorError("image WorkOrder operation must be GENERATE")
        normalized["workflow_id"] = _token(normalized["workflow_id"], "workflow_id")
        normalized["model_id"] = _token(normalized["model_id"], "model_id")
        try:
            normalized["workflow_hash"] = validate_sha256(normalized["workflow_hash"], "workflow_hash")
            normalized["model_hash"] = validate_sha256(normalized["model_hash"], "model_hash")
        except ValueError as exc:
            raise DispatchValidatorError(str(exc)) from exc
        if normalized["width"] * normalized["height"] > 16_777_216:
            raise DispatchValidatorError("image dimensions exceed pixel limit")
        normalized["guidance_scale"] = _guidance(normalized["guidance_scale"])
        outputs: list[str] = []
        for value in normalized["output_relative_paths"]:
            try:
                path = workspace_relative_path(value, "output_relative_path")
            except ValueError as exc:
                raise DispatchValidatorError("image output path is invalid") from exc
            if not path.startswith("exports/") or not path.lower().endswith(".png"):
                raise DispatchValidatorError("image outputs must be PNG files under exports/")
            outputs.append(path)
        if len({value.casefold() for value in outputs}) != len(outputs):
            raise DispatchValidatorError("image outputs must be distinct")
        normalized["output_relative_paths"] = outputs
        try:
            budget = ImageOperationBudget(
                timeout_seconds=normalized["timeout_seconds"],
                max_output_bytes=normalized["max_output_bytes"],
                max_history_bytes=normalized["max_history_bytes"],
            )
        except (TypeError, ValueError) as exc:
            raise DispatchValidatorError("image operation budget is invalid") from exc
        if supplied_budget is not None and supplied_budget != budget.to_dict():
            raise DispatchValidatorError("image operation budget is not canonical")
        normalized["budget"] = budget.to_dict()
        return normalized
