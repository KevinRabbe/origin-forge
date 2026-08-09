from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Mapping

from .ids import IdKind, new_id, validate_id
from .path_policy import portable_relative_path


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_DIMENSION = 4096
_MAX_PIXELS = 16_777_216
_MAX_IMAGE_BYTES = 128 * 1024 * 1024
_MAX_INPUT_IMAGES = 8
_MAX_OUTPUT_IMAGES = 4
_MAX_PROMPT = 16_384
_MAX_CRITERIA = 32
_MAX_DIAGNOSTICS = 64
_MAX_FINDINGS = 128
_MAX_TEXT = 8192


class ImageVisionModelError(ValueError):
    pass


class ImageOperation(StrEnum):
    GENERATE = "GENERATE"
    EDIT = "EDIT"


class ImageResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class VisionSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ImageVisionModelError("value is not canonical JSON serializable") from exc


def canonical_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ImageVisionModelError(f"{field} must be a lowercase sha256: digest")
    return value


def _text(
    value: str,
    field: str,
    *,
    maximum: int = _MAX_TEXT,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ImageVisionModelError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise ImageVisionModelError(f"{field} must be non-empty")
    if len(value) > maximum:
        raise ImageVisionModelError(f"{field} exceeds character limit")
    if "\x00" in value:
        raise ImageVisionModelError(f"{field} may not contain NUL")
    return value


def _token(value: str, field: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ImageVisionModelError(f"{field} must be a bounded portable token")
    return value


def _positive_int(value: int, field: str, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= maximum
    ):
        raise ImageVisionModelError(f"{field} must be between 1 and {maximum}")
    return value


def _finite_number(
    value: int | float,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImageVisionModelError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ImageVisionModelError(
            f"{field} must be finite and between {minimum} and {maximum}"
        )
    return result


def workspace_relative_path(value: str, field: str) -> str:
    _text(value, field, maximum=4096)
    try:
        path = portable_relative_path(value)
    except ValueError as exc:
        raise ImageVisionModelError(f"invalid {field}") from exc
    normalized = PurePosixPath(path.as_posix())
    if not normalized.parts:
        raise ImageVisionModelError(f"{field} may not be empty")
    return normalized.as_posix()


@dataclass(frozen=True)
class RasterInputRef:
    image_id: str
    relative_path: str
    content_hash: str
    pixel_hash: str
    byte_count: int
    width: int
    height: int

    def __post_init__(self) -> None:
        _token(self.image_id, "image_id")
        relative = workspace_relative_path(self.relative_path, "image relative_path")
        if not relative.startswith("inputs/") or not relative.lower().endswith(".png"):
            raise ImageVisionModelError(
                "image relative_path must be a PNG under inputs/"
            )
        object.__setattr__(self, "relative_path", relative)
        validate_sha256(self.content_hash, "image content_hash")
        validate_sha256(self.pixel_hash, "image pixel_hash")
        _positive_int(self.byte_count, "image byte_count", _MAX_IMAGE_BYTES)
        _positive_int(self.width, "image width", _MAX_DIMENSION)
        _positive_int(self.height, "image height", _MAX_DIMENSION)
        if self.width * self.height > _MAX_PIXELS:
            raise ImageVisionModelError("image dimensions exceed pixel limit")

    def to_dict(self) -> dict[str, object]:
        return {
            "image_id": self.image_id,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ImageOperationBudget:
    timeout_seconds: int = 300
    max_output_bytes: int = 64 * 1024 * 1024
    max_history_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        _positive_int(self.timeout_seconds, "timeout_seconds", 3600)
        _positive_int(self.max_output_bytes, "max_output_bytes", _MAX_IMAGE_BYTES)
        _positive_int(self.max_history_bytes, "max_history_bytes", 16 * 1024 * 1024)

    def to_dict(self) -> dict[str, int]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_history_bytes": self.max_history_bytes,
        }


@dataclass(frozen=True)
class ImageOperationRequest:
    operation_id: str
    workspace_id: str
    operation: ImageOperation
    backend_id: str
    backend_version: str
    workflow_id: str
    workflow_hash: str
    model_id: str
    model_hash: str
    prompt: str
    negative_prompt: str
    width: int
    height: int
    seed: int
    steps: int
    guidance_scale: float
    output_relative_paths: tuple[str, ...]
    input_images: tuple[RasterInputRef, ...] = ()
    budget: ImageOperationBudget = ImageOperationBudget()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImageVisionModelError("unsupported ImageOperationRequest schema_version")
        if not validate_id(self.operation_id, IdKind.IMAGE_OPERATION):
            raise ImageVisionModelError("operation_id must be an IMAGE_OPERATION ID")
        if not validate_id(self.workspace_id, IdKind.IMAGE_WORKSPACE):
            raise ImageVisionModelError("workspace_id must be an IMAGE_WORKSPACE ID")
        if not isinstance(self.operation, ImageOperation):
            raise ImageVisionModelError("operation must be an ImageOperation")
        _token(self.backend_id, "backend_id")
        _text(self.backend_version, "backend_version", maximum=256)
        _token(self.workflow_id, "workflow_id")
        validate_sha256(self.workflow_hash, "workflow_hash")
        _text(self.model_id, "model_id", maximum=256)
        validate_sha256(self.model_hash, "model_hash")
        _text(self.prompt, "prompt", maximum=_MAX_PROMPT)
        _text(
            self.negative_prompt,
            "negative_prompt",
            maximum=_MAX_PROMPT,
            allow_empty=True,
        )
        _positive_int(self.width, "width", _MAX_DIMENSION)
        _positive_int(self.height, "height", _MAX_DIMENSION)
        if self.width * self.height > _MAX_PIXELS:
            raise ImageVisionModelError("image request dimensions exceed pixel limit")
        if (
            not isinstance(self.seed, int)
            or isinstance(self.seed, bool)
            or not 0 <= self.seed <= 2**63 - 1
        ):
            raise ImageVisionModelError("seed must be an integer from 0 through 2^63-1")
        _positive_int(self.steps, "steps", 1000)
        object.__setattr__(
            self,
            "guidance_scale",
            _finite_number(
                self.guidance_scale,
                "guidance_scale",
                minimum=0.0,
                maximum=100.0,
            ),
        )
        outputs = tuple(self.output_relative_paths)
        if not outputs or len(outputs) > _MAX_OUTPUT_IMAGES:
            raise ImageVisionModelError(
                f"output_relative_paths must contain 1..{_MAX_OUTPUT_IMAGES} items"
            )
        normalized_outputs = tuple(
            workspace_relative_path(value, "output_relative_path") for value in outputs
        )
        if any(
            not value.startswith("exports/") or not value.lower().endswith(".png")
            for value in normalized_outputs
        ):
            raise ImageVisionModelError("image outputs must be PNG files under exports/")
        if len({value.casefold() for value in normalized_outputs}) != len(normalized_outputs):
            raise ImageVisionModelError("image outputs must be distinct")
        object.__setattr__(self, "output_relative_paths", normalized_outputs)

        inputs = tuple(self.input_images)
        if len(inputs) > _MAX_INPUT_IMAGES:
            raise ImageVisionModelError("input_images exceed item limit")
        if any(not isinstance(value, RasterInputRef) for value in inputs):
            raise ImageVisionModelError("input_images must contain RasterInputRef values")
        if len({value.image_id for value in inputs}) != len(inputs):
            raise ImageVisionModelError("input_images contain duplicate image IDs")
        if self.operation is ImageOperation.GENERATE and inputs:
            raise ImageVisionModelError("GENERATE requests may not contain input images")
        if self.operation is ImageOperation.EDIT and not inputs:
            raise ImageVisionModelError("EDIT requests require at least one input image")
        object.__setattr__(self, "input_images", tuple(sorted(inputs, key=lambda value: value.image_id)))
        if not isinstance(self.budget, ImageOperationBudget):
            raise ImageVisionModelError("budget must be an ImageOperationBudget")

    @classmethod
    def create(
        cls,
        *,
        operation: ImageOperation,
        backend_id: str,
        backend_version: str,
        workflow_id: str,
        workflow_hash: str,
        model_id: str,
        model_hash: str,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        seed: int,
        steps: int,
        guidance_scale: float,
        output_relative_paths: tuple[str, ...],
        input_images: tuple[RasterInputRef, ...] = (),
        budget: ImageOperationBudget = ImageOperationBudget(),
    ) -> "ImageOperationRequest":
        return cls(
            operation_id=new_id(IdKind.IMAGE_OPERATION),
            workspace_id=new_id(IdKind.IMAGE_WORKSPACE),
            operation=operation,
            backend_id=backend_id,
            backend_version=backend_version,
            workflow_id=workflow_id,
            workflow_hash=workflow_hash,
            model_id=model_id,
            model_hash=model_hash,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
            steps=steps,
            guidance_scale=guidance_scale,
            output_relative_paths=output_relative_paths,
            input_images=input_images,
            budget=budget,
        )

    def semantic_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "operation": self.operation.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "workflow_id": self.workflow_id,
            "workflow_hash": self.workflow_hash,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "output_relative_paths": list(self.output_relative_paths),
            "input_images": [value.to_dict() for value in self.input_images],
            "budget": self.budget.to_dict(),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.semantic_dict())

    def to_dict(self) -> dict[str, object]:
        value = self.semantic_dict()
        value["content_hash"] = self.content_hash
        return value


@dataclass(frozen=True)
class ImageOutputEvidence:
    relative_path: str
    content_hash: str
    pixel_hash: str
    byte_count: int
    width: int
    height: int

    def __post_init__(self) -> None:
        relative = workspace_relative_path(self.relative_path, "output relative_path")
        if not relative.startswith("exports/") or not relative.lower().endswith(".png"):
            raise ImageVisionModelError("output evidence must reference a PNG under exports/")
        object.__setattr__(self, "relative_path", relative)
        validate_sha256(self.content_hash, "output content_hash")
        validate_sha256(self.pixel_hash, "output pixel_hash")
        _positive_int(self.byte_count, "output byte_count", _MAX_IMAGE_BYTES)
        _positive_int(self.width, "output width", _MAX_DIMENSION)
        _positive_int(self.height, "output height", _MAX_DIMENSION)
        if self.width * self.height > _MAX_PIXELS:
            raise ImageVisionModelError("output dimensions exceed pixel limit")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ImageOperationResult:
    operation_id: str
    workspace_id: str
    request_hash: str
    status: ImageResultStatus
    backend_id: str
    backend_version: str
    workflow_hash: str
    model_id: str
    model_hash: str
    outputs: tuple[ImageOutputEvidence, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.IMAGE_OPERATION):
            raise ImageVisionModelError("result operation_id must be an IMAGE_OPERATION ID")
        if not validate_id(self.workspace_id, IdKind.IMAGE_WORKSPACE):
            raise ImageVisionModelError("result workspace_id must be an IMAGE_WORKSPACE ID")
        validate_sha256(self.request_hash, "result request_hash")
        if not isinstance(self.status, ImageResultStatus):
            raise ImageVisionModelError("status must be an ImageResultStatus")
        _token(self.backend_id, "result backend_id")
        _text(self.backend_version, "result backend_version", maximum=256)
        validate_sha256(self.workflow_hash, "result workflow_hash")
        _text(self.model_id, "result model_id", maximum=256)
        validate_sha256(self.model_hash, "result model_hash")
        outputs = tuple(self.outputs)
        if len(outputs) > _MAX_OUTPUT_IMAGES or any(
            not isinstance(value, ImageOutputEvidence) for value in outputs
        ):
            raise ImageVisionModelError("result outputs are invalid or exceed item limit")
        if len({value.relative_path.casefold() for value in outputs}) != len(outputs):
            raise ImageVisionModelError("result outputs contain duplicate paths")
        if self.status is ImageResultStatus.SUCCEEDED and not outputs:
            raise ImageVisionModelError("successful image result requires output evidence")
        if self.status is not ImageResultStatus.SUCCEEDED and outputs:
            raise ImageVisionModelError("non-success image result may not claim outputs")
        object.__setattr__(self, "outputs", tuple(sorted(outputs, key=lambda value: value.relative_path)))
        diagnostics = tuple(self.diagnostics)
        if len(diagnostics) > _MAX_DIAGNOSTICS:
            raise ImageVisionModelError("result diagnostics exceed item limit")
        for value in diagnostics:
            _text(value, "diagnostic", maximum=2048)
        object.__setattr__(self, "diagnostics", diagnostics)

    def bind_request(self, request: ImageOperationRequest) -> None:
        if not isinstance(request, ImageOperationRequest):
            raise TypeError("request must be an ImageOperationRequest")
        expected = (
            request.operation_id,
            request.workspace_id,
            request.content_hash,
            request.backend_id,
            request.backend_version,
            request.workflow_hash,
            request.model_id,
            request.model_hash,
        )
        actual = (
            self.operation_id,
            self.workspace_id,
            self.request_hash,
            self.backend_id,
            self.backend_version,
            self.workflow_hash,
            self.model_id,
            self.model_hash,
        )
        if actual != expected:
            raise ImageVisionModelError("image result does not bind the exact request")
        if self.status is ImageResultStatus.SUCCEEDED:
            if tuple(value.relative_path for value in self.outputs) != tuple(
                sorted(request.output_relative_paths)
            ):
                raise ImageVisionModelError("image result does not bind exact requested outputs")

    def semantic_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "request_hash": self.request_hash,
            "status": self.status.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "workflow_hash": self.workflow_hash,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "outputs": [value.to_dict() for value in self.outputs],
            "diagnostics": list(self.diagnostics),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.semantic_dict())

    def to_dict(self) -> dict[str, object]:
        value = self.semantic_dict()
        value["content_hash"] = self.content_hash
        return value


@dataclass(frozen=True)
class VisionImageRef:
    image_id: str
    content_hash: str
    pixel_hash: str
    byte_count: int
    width: int
    height: int

    def __post_init__(self) -> None:
        _token(self.image_id, "vision image_id")
        validate_sha256(self.content_hash, "vision image content_hash")
        validate_sha256(self.pixel_hash, "vision image pixel_hash")
        _positive_int(self.byte_count, "vision image byte_count", _MAX_IMAGE_BYTES)
        _positive_int(self.width, "vision image width", _MAX_DIMENSION)
        _positive_int(self.height, "vision image height", _MAX_DIMENSION)
        if self.width * self.height > _MAX_PIXELS:
            raise ImageVisionModelError("vision image dimensions exceed pixel limit")

    def to_dict(self) -> dict[str, object]:
        return {
            "image_id": self.image_id,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


VISION_REPORT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "findings"],
    "properties": {
        "summary": {"type": "string", "maxLength": 8192},
        "findings": {
            "type": "array",
            "maxItems": _MAX_FINDINGS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "severity", "image_id", "description"],
                "properties": {
                    "category": {"type": "string", "maxLength": 128},
                    "severity": {
                        "type": "string",
                        "enum": [value.value for value in VisionSeverity],
                    },
                    "image_id": {"type": "string", "maxLength": 128},
                    "description": {"type": "string", "maxLength": 4096},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class VisionInspectionRequest:
    inspection_id: str
    images: tuple[VisionImageRef, ...]
    objective: str
    criteria: tuple[str, ...]
    expected_model_id: str
    expected_model_hash: str
    max_output_tokens: int = 4096
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImageVisionModelError("unsupported VisionInspectionRequest schema_version")
        if not validate_id(self.inspection_id, IdKind.VISION_INSPECTION):
            raise ImageVisionModelError("inspection_id must be a VISION_INSPECTION ID")
        images = tuple(self.images)
        if not images or len(images) > _MAX_INPUT_IMAGES:
            raise ImageVisionModelError(
                f"vision images must contain 1..{_MAX_INPUT_IMAGES} items"
            )
        if any(not isinstance(value, VisionImageRef) for value in images):
            raise ImageVisionModelError("vision images must contain VisionImageRef values")
        if len({value.image_id for value in images}) != len(images):
            raise ImageVisionModelError("vision images contain duplicate image IDs")
        object.__setattr__(self, "images", tuple(sorted(images, key=lambda value: value.image_id)))
        _text(self.objective, "vision objective", maximum=_MAX_TEXT)
        criteria = tuple(self.criteria)
        if len(criteria) > _MAX_CRITERIA:
            raise ImageVisionModelError("vision criteria exceed item limit")
        for value in criteria:
            _text(value, "vision criterion", maximum=512)
        object.__setattr__(self, "criteria", criteria)
        _text(self.expected_model_id, "expected_model_id", maximum=256)
        validate_sha256(self.expected_model_hash, "expected_model_hash")
        _positive_int(self.max_output_tokens, "max_output_tokens", 32_768)

    @classmethod
    def create(
        cls,
        *,
        images: tuple[VisionImageRef, ...],
        objective: str,
        criteria: tuple[str, ...],
        expected_model_id: str,
        expected_model_hash: str,
        max_output_tokens: int = 4096,
    ) -> "VisionInspectionRequest":
        return cls(
            inspection_id=new_id(IdKind.VISION_INSPECTION),
            images=images,
            objective=objective,
            criteria=criteria,
            expected_model_id=expected_model_id,
            expected_model_hash=expected_model_hash,
            max_output_tokens=max_output_tokens,
        )

    def semantic_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "inspection_id": self.inspection_id,
            "images": [value.to_dict() for value in self.images],
            "objective": self.objective,
            "criteria": list(self.criteria),
            "expected_model_id": self.expected_model_id,
            "expected_model_hash": self.expected_model_hash,
            "max_output_tokens": self.max_output_tokens,
            "response_schema_hash": canonical_hash(VISION_REPORT_SCHEMA),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.semantic_dict())

    def to_dict(self) -> dict[str, object]:
        value = self.semantic_dict()
        value["content_hash"] = self.content_hash
        return value


@dataclass(frozen=True)
class VisionFinding:
    category: str
    severity: VisionSeverity
    image_id: str
    description: str

    def __post_init__(self) -> None:
        _token(self.category, "vision finding category")
        if not isinstance(self.severity, VisionSeverity):
            raise ImageVisionModelError("vision finding severity must be a VisionSeverity")
        _token(self.image_id, "vision finding image_id")
        _text(self.description, "vision finding description", maximum=4096)

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "severity": self.severity.value,
            "image_id": self.image_id,
            "description": self.description,
        }

    @property
    def semantic_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class VisionReport:
    inspection_id: str
    request_hash: str
    model_id: str
    model_hash: str
    summary: str
    findings: tuple[VisionFinding, ...]
    input_tokens: int | None = None
    output_tokens: int | None = None
    semantic_findings_verified: bool = False
    advisory_only: bool = True

    def __post_init__(self) -> None:
        if not validate_id(self.inspection_id, IdKind.VISION_INSPECTION):
            raise ImageVisionModelError("report inspection_id must be a VISION_INSPECTION ID")
        validate_sha256(self.request_hash, "report request_hash")
        _text(self.model_id, "report model_id", maximum=256)
        validate_sha256(self.model_hash, "report model_hash")
        _text(self.summary, "vision report summary", maximum=_MAX_TEXT, allow_empty=True)
        findings = tuple(self.findings)
        if len(findings) > _MAX_FINDINGS or any(
            not isinstance(value, VisionFinding) for value in findings
        ):
            raise ImageVisionModelError("vision findings are invalid or exceed item limit")
        if len({value.semantic_hash for value in findings}) != len(findings):
            raise ImageVisionModelError("vision report contains duplicate semantic findings")
        object.__setattr__(
            self,
            "findings",
            tuple(
                sorted(
                    findings,
                    key=lambda value: (
                        value.image_id,
                        value.severity.value,
                        value.category,
                        value.description,
                    ),
                )
            ),
        )
        for value, field in (
            (self.input_tokens, "input_tokens"),
            (self.output_tokens, "output_tokens"),
        ):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ImageVisionModelError(f"{field} must be a non-negative integer or None")
        if self.semantic_findings_verified is not False:
            raise ImageVisionModelError("vision model may not mark semantic findings verified")
        if self.advisory_only is not True:
            raise ImageVisionModelError("vision report must remain advisory only")

    def bind_request(self, request: VisionInspectionRequest) -> None:
        if not isinstance(request, VisionInspectionRequest):
            raise TypeError("request must be a VisionInspectionRequest")
        if self.inspection_id != request.inspection_id or self.request_hash != request.content_hash:
            raise ImageVisionModelError("vision report does not bind the exact request")
        if self.model_id != request.expected_model_id or self.model_hash != request.expected_model_hash:
            raise ImageVisionModelError("vision report does not bind the expected model identity")
        known_ids = {value.image_id for value in request.images}
        if any(value.image_id not in known_ids for value in self.findings):
            raise ImageVisionModelError("vision finding references image outside frozen request")

    def semantic_dict(self) -> dict[str, object]:
        return {
            "inspection_id": self.inspection_id,
            "request_hash": self.request_hash,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "summary": self.summary,
            "findings": [value.to_dict() for value in self.findings],
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "semantic_findings_verified": self.semantic_findings_verified,
            "advisory_only": self.advisory_only,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.semantic_dict())

    def to_dict(self) -> dict[str, object]:
        value = self.semantic_dict()
        value["content_hash"] = self.content_hash
        return value


def parse_vision_report(
    text: str,
    *,
    request: VisionInspectionRequest,
    model_id: str,
    model_hash: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> VisionReport:
    _text(text, "vision response", maximum=1_000_000)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImageVisionModelError("vision response is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"summary", "findings"}:
        raise ImageVisionModelError("vision response must contain exactly summary and findings")
    summary = value["summary"]
    raw_findings = value["findings"]
    if not isinstance(summary, str) or not isinstance(raw_findings, list):
        raise ImageVisionModelError("vision response summary/findings have invalid types")
    if len(raw_findings) > _MAX_FINDINGS:
        raise ImageVisionModelError("vision response findings exceed item limit")
    findings: list[VisionFinding] = []
    known_ids = {image.image_id for image in request.images}
    for item in raw_findings:
        if not isinstance(item, dict) or set(item) != {
            "category",
            "severity",
            "image_id",
            "description",
        }:
            raise ImageVisionModelError("vision finding has unknown or missing fields")
        try:
            severity = VisionSeverity(item["severity"])
        except (ValueError, TypeError) as exc:
            raise ImageVisionModelError("vision finding severity is invalid") from exc
        finding = VisionFinding(
            category=item["category"],
            severity=severity,
            image_id=item["image_id"],
            description=item["description"],
        )
        if finding.image_id not in known_ids:
            raise ImageVisionModelError("vision finding references unknown image_id")
        findings.append(finding)
    report = VisionReport(
        inspection_id=request.inspection_id,
        request_hash=request.content_hash,
        model_id=model_id,
        model_hash=model_hash,
        summary=summary,
        findings=tuple(findings),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    report.bind_request(request)
    return report


def validate_vision_image_bytes(
    request: VisionInspectionRequest,
    image_bytes_by_id: Mapping[str, bytes],
) -> None:
    if set(image_bytes_by_id) != {value.image_id for value in request.images}:
        raise ImageVisionModelError("vision image byte set must exactly match request images")
