from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.image_vision_models import ImageOperationBudget
from origin_forge.production_dispatch_binding_image import ImageGenerationInputBinder
from origin_forge.production_dispatch_invocation_image import (
    ImageGenerationInvocationError,
    ImageGenerationInvocationRequest,
)
from origin_forge.production_execution_owner_image import (
    image_generation_execution_owner_descriptor,
)
from origin_forge.production_image_dispatch_output_binding_models import (
    ImageDispatchOutput,
    ImageDispatchOutputBinding,
    ImageDispatchOutputBindingModelError,
)
from origin_forge.production_work_order_image import (
    IMAGE_REQUEST_TYPE_ID,
    ImageGenerationDispatchValidator,
)
from origin_forge.production_work_order_models import content_hash
from origin_forge.production_work_order_validators import DispatchValidatorError


def _payload() -> dict[str, object]:
    return {
        "operation": "GENERATE",
        "backend_version": "0.3.0",
        "workflow_id": "workflow-sd15",
        "workflow_hash": "sha256:" + "a" * 64,
        "model_id": "sd15",
        "model_hash": "sha256:" + "b" * 64,
        "prompt": "a small blue robot",
        "negative_prompt": "blurry",
        "width": 512,
        "height": 512,
        "seed": 7,
        "steps": 20,
        "guidance_scale": "7.5",
        "output_relative_paths": ["exports/robot.png"],
        "timeout_seconds": 300,
        "max_output_bytes": 64 * 1024 * 1024,
        "max_history_bytes": 4 * 1024 * 1024,
    }


class ImageWorkOrderValidatorTests(unittest.TestCase):
    def test_image_binder_freezes_the_planned_owner_relation(self) -> None:
        descriptor = ImageGenerationInputBinder().descriptor
        self.assertEqual(descriptor.binder_id, "binder.image.generate@1")
        self.assertEqual(descriptor.adapter_id, "originforge.image.generate")
        self.assertEqual(descriptor.dispatch_contract_id, "image.generate@1")
        self.assertEqual(
            descriptor.request_type_id,
            "ImageGenerationService.execute@production-v1",
        )
        self.assertEqual(descriptor.accepted_input_roles, ())

    def test_image_execution_owner_freezes_exact_binder_relation(self) -> None:
        owner = image_generation_execution_owner_descriptor()
        self.assertEqual(owner.owner_id, "originforge.execution.image.generate@1")
        self.assertEqual(owner.adapter_id, "originforge.image.generate")
        self.assertEqual(owner.binder_id, "binder.image.generate@1")
        self.assertFalse(owner.requires_sandbox)
        self.assertFalse(owner.requires_workspace_manager)

    def test_valid_generation_payload_is_normalized_for_later_request_assembly(self) -> None:
        validator = ImageGenerationDispatchValidator()
        result = validator.validate(_payload(), ())
        self.assertEqual(result["workflow_hash"], "sha256:" + "a" * 64)
        self.assertEqual(result["guidance_scale"], 7.5)
        self.assertEqual(result["output_relative_paths"], ["exports/robot.png"])
        self.assertEqual(result["budget"]["timeout_seconds"], 300)
        self.assertEqual(IMAGE_REQUEST_TYPE_ID, "ImageGenerationService.execute@production-v1")

    def test_generation_rejects_input_refs_and_unsafe_or_drifted_payload(self) -> None:
        validator = ImageGenerationDispatchValidator()
        with self.assertRaisesRegex(DispatchValidatorError, "no input refs"):
            validator.validate(_payload(), (object(),))  # type: ignore[arg-type]
        for field, value, message in (
            ("workflow_hash", "not-a-hash", "workflow_hash"),
            ("guidance_scale", "nan", "between 0 and 100"),
            ("output_relative_paths", ["../robot.png"], "output path"),
        ):
            payload = _payload()
            payload[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(DispatchValidatorError, message):
                validator.validate(payload, ())

    def test_generation_rejects_unknown_fields_and_duplicate_outputs(self) -> None:
        validator = ImageGenerationDispatchValidator()
        unknown = _payload()
        unknown["workspace_id"] = "caller-controlled"
        with self.assertRaises(DispatchValidatorError):
            validator.validate(unknown, ())
        duplicate = _payload()
        duplicate["output_relative_paths"] = ["exports/robot.png", "exports/ROBOT.PNG"]
        with self.assertRaisesRegex(DispatchValidatorError, "distinct"):
            validator.validate(duplicate, ())

    def test_typed_invocation_recomputes_the_frozen_projection_hash(self) -> None:
        task_id = new_id(IdKind.TASK)
        projection = {"task_id": task_id, **ImageGenerationDispatchValidator().validate(_payload(), ())}
        # The binder projection stores budget scalars, not the validator's helper object.
        projection.pop("budget")
        request_hash = content_hash(projection)
        request = ImageGenerationInvocationRequest.from_projection(projection, request_hash)
        self.assertEqual(request.task_id, task_id)
        self.assertEqual(request.budget, ImageOperationBudget(300, 64 * 1024 * 1024, 4 * 1024 * 1024))

    def test_typed_invocation_rejects_hash_and_projection_drift(self) -> None:
        task_id = new_id(IdKind.TASK)
        projection = {"task_id": task_id, **_payload()}
        with self.assertRaises(ImageGenerationInvocationError):
            ImageGenerationInvocationRequest.from_projection(projection, "0" * 64)
        projection["unexpected"] = True
        with self.assertRaisesRegex(ImageGenerationInvocationError, "unknown or missing"):
            ImageGenerationInvocationRequest.from_projection(projection, "0" * 64)

    def test_image_output_binding_requires_distinct_verified_outputs(self) -> None:
        ids = {kind: new_id(kind) for kind in (
            IdKind.DISPATCH_EXECUTION,
            IdKind.DISPATCH_CLAIM,
            IdKind.TASK,
            IdKind.PRODUCTION_WORK_ORDER,
            IdKind.DISPATCH_BINDING,
            IdKind.RUN,
            IdKind.ARTIFACT,
            IdKind.VERIFICATION,
        )}
        output = ImageDispatchOutput(
            "exports/robot.png", new_id(IdKind.ARTIFACT), new_id(IdKind.VERIFICATION),
            "a" * 64, "b" * 64, 512, 512, 1234,
        )
        binding = ImageDispatchOutputBinding(
            ids[IdKind.DISPATCH_EXECUTION], ids[IdKind.DISPATCH_CLAIM], ids[IdKind.TASK],
            2, "c" * 64, ids[IdKind.PRODUCTION_WORK_ORDER], "d" * 64,
            ids[IdKind.DISPATCH_BINDING], "e" * 64, "originforge.execution.image.generate@1",
            ids[IdKind.RUN], ids[IdKind.ARTIFACT], new_id(IdKind.ARTIFACT), (output,),
            "f" * 64, 1, "2026-08-26T00:00:00Z",
        )
        self.assertEqual(binding.outputs[0].relative_path, "exports/robot.png")
        duplicate = ImageDispatchOutput(
            "exports/ROBOT.PNG", new_id(IdKind.ARTIFACT), new_id(IdKind.VERIFICATION),
            "1" * 64, "2" * 64, 512, 512, 1234,
        )
        with self.assertRaisesRegex(ImageDispatchOutputBindingModelError, "paths must be distinct"):
            ImageDispatchOutputBinding(
                ids[IdKind.DISPATCH_EXECUTION], ids[IdKind.DISPATCH_CLAIM], ids[IdKind.TASK],
                2, "c" * 64, ids[IdKind.PRODUCTION_WORK_ORDER], "d" * 64,
                ids[IdKind.DISPATCH_BINDING], "e" * 64, "originforge.execution.image.generate@1",
                ids[IdKind.RUN], ids[IdKind.ARTIFACT], new_id(IdKind.ARTIFACT), (output, duplicate),
                "f" * 64, 1, "2026-08-26T00:00:00Z",
            )
