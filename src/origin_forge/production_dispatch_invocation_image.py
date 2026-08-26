from __future__ import annotations

from dataclasses import dataclass

from .adapters.comfyui import ComfyWorkflowTemplate
from .ids import IdKind, validate_id
from .image_vision_models import (
    ImageOperation,
    ImageOperationBudget,
    ImageOperationRequest,
)
from .production_dispatch_binding_image import ImageGenerationInputBinder
from .production_work_order_image import ImageGenerationDispatchValidator
from .production_work_order_models import content_hash


class ImageGenerationInvocationError(RuntimeError):
    """The frozen image request cannot be reconstructed safely."""


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ImageGenerationInvocationError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    if any(char not in "0123456789abcdef" for char in value):
        raise ImageGenerationInvocationError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


@dataclass(frozen=True)
class ImageGenerationInvocationRequest:
    """Strict in-memory view of one frozen image GENERATE projection.

    Operation and workspace IDs intentionally do not belong to this object. They
    are allocated only after the durable DISPATCH_EXECUTION_STARTED boundary.
    """

    task_id: str
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
    budget: ImageOperationBudget
    request_content_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.task_id, IdKind.TASK):
            raise ImageGenerationInvocationError(
                "image invocation task_id must be a valid TASK ID"
            )
        if not isinstance(self.output_relative_paths, tuple):
            object.__setattr__(self, "output_relative_paths", tuple(self.output_relative_paths))
        if not isinstance(self.budget, ImageOperationBudget):
            raise ImageGenerationInvocationError("image invocation budget is invalid")
        _digest(self.request_content_hash, "request_content_hash")
        try:
            validator_payload = self.projection_dict(include_task=False)
            validator_payload["guidance_scale"] = str(validator_payload["guidance_scale"])
            normalized = ImageGenerationDispatchValidator().validate(
                validator_payload, ()
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise ImageGenerationInvocationError(
                "frozen image invocation violates the trusted WorkOrder contract"
            ) from exc
        expected = self._normalized_projection(normalized)
        if expected != self.projection_dict():
            raise ImageGenerationInvocationError(
                "frozen image invocation is not canonical under the trusted validator"
            )
        if content_hash(self.projection_dict()) != self.request_content_hash:
            raise ImageGenerationInvocationError(
                "frozen image invocation request content hash does not recompute"
            )

    def projection_dict(self, *, include_task: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "operation": "GENERATE",
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
            **self.budget.to_dict(),
        }
        if include_task:
            return {"task_id": self.task_id, **value}
        return value

    def _normalized_projection(self, normalized: dict[str, object]) -> dict[str, object]:
        budget = normalized.get("budget")
        if not isinstance(budget, dict):
            raise ImageGenerationInvocationError("validated image budget is missing")
        normalized = dict(normalized)
        normalized.pop("budget", None)
        normalized.pop("timeout_seconds", None)
        normalized.pop("max_output_bytes", None)
        normalized.pop("max_history_bytes", None)
        return {
            "task_id": self.task_id,
            **normalized,
            **budget,
        }

    @classmethod
    def from_projection(
        cls,
        projection: dict[str, object],
        request_content_hash: str,
    ) -> ImageGenerationInvocationRequest:
        if not isinstance(projection, dict):
            raise ImageGenerationInvocationError("image invocation projection must be an object")
        if set(projection) != {
            "task_id",
            "operation",
            "backend_version",
            "workflow_id",
            "workflow_hash",
            "model_id",
            "model_hash",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "seed",
            "steps",
            "guidance_scale",
            "output_relative_paths",
            "timeout_seconds",
            "max_output_bytes",
            "max_history_bytes",
        }:
            raise ImageGenerationInvocationError(
                "image invocation projection has unknown or missing fields"
            )
        task_id = projection.get("task_id")
        if not isinstance(task_id, str):
            raise ImageGenerationInvocationError(
                "image invocation projection task_id must be text"
            )
        try:
            validator_payload = {
                key: value for key, value in projection.items() if key != "task_id"
            }
            # The persisted binder projection carries the validator's normalized
            # float, while the WorkOrder input encoding is a decimal string.
            validator_payload["guidance_scale"] = str(validator_payload["guidance_scale"])
            normalized = ImageGenerationDispatchValidator().validate(
                validator_payload, ()
            )
            budget = ImageOperationBudget(**normalized.pop("budget"))
            value = cls(
                task_id=task_id,
                backend_version=normalized["backend_version"],
                workflow_id=normalized["workflow_id"],
                workflow_hash=normalized["workflow_hash"],
                model_id=normalized["model_id"],
                model_hash=normalized["model_hash"],
                prompt=normalized["prompt"],
                negative_prompt=normalized.get("negative_prompt", ""),
                width=normalized["width"],
                height=normalized["height"],
                seed=normalized["seed"],
                steps=normalized["steps"],
                guidance_scale=normalized["guidance_scale"],
                output_relative_paths=tuple(normalized["output_relative_paths"]),
                budget=budget,
                request_content_hash=request_content_hash,
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            if isinstance(exc, ImageGenerationInvocationError):
                raise
            raise ImageGenerationInvocationError(
                "image invocation projection cannot be reconstructed"
            ) from exc
        if value.projection_dict() != projection:
            raise ImageGenerationInvocationError(
                "image invocation projection is not canonical"
            )
        return value

    def to_operation_request(
        self,
        *,
        template: ComfyWorkflowTemplate,
    ) -> ImageOperationRequest:
        """Allocate operation/workspace IDs only after execution ownership starts."""
        if not isinstance(template, ComfyWorkflowTemplate):
            raise TypeError("template must be a ComfyWorkflowTemplate")
        if (
            template.workflow_id != self.workflow_id
            or template.workflow_hash != self.workflow_hash
            or template.model_id != self.model_id
            or template.model_hash != self.model_hash
            or template.backend_version != self.backend_version
        ):
            raise ImageGenerationInvocationError(
                "image workflow template does not match the frozen invocation"
            )
        return ImageOperationRequest.create(
            operation=ImageOperation.GENERATE,
            backend_id="comfyui",
            backend_version=self.backend_version,
            workflow_id=self.workflow_id,
            workflow_hash=self.workflow_hash,
            model_id=self.model_id,
            model_hash=self.model_hash,
            prompt=self.prompt,
            negative_prompt=self.negative_prompt,
            width=self.width,
            height=self.height,
            seed=self.seed,
            steps=self.steps,
            guidance_scale=self.guidance_scale,
            output_relative_paths=self.output_relative_paths,
            budget=self.budget,
        )


def image_generation_binder_schema_hash() -> str:
    """Expose the trusted binder schema without duplicating its private fields."""
    return ImageGenerationInputBinder().descriptor.request_schema_hash
