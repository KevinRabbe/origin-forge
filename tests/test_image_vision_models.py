from __future__ import annotations

import json
import unittest

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.image_vision_models import (
    ImageOperation,
    ImageOperationRequest,
    ImageOperationResult,
    ImageOutputEvidence,
    ImageResultStatus,
    ImageVisionModelError,
    RasterInputRef,
    VisionImageRef,
    VisionInspectionRequest,
    VisionReport,
    VisionSeverity,
    parse_vision_report,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


class ImageVisionModelTests(unittest.TestCase):
    def _generate_request(self) -> ImageOperationRequest:
        return ImageOperationRequest.create(
            operation=ImageOperation.GENERATE,
            backend_id="comfyui",
            backend_version="0.1",
            workflow_id="concept-v1",
            workflow_hash=HASH_A,
            model_id="local-image-model",
            model_hash=HASH_B,
            prompt="armored factory enemy concept",
            negative_prompt="",
            width=512,
            height=512,
            seed=42,
            steps=20,
            guidance_scale=7.0,
            output_relative_paths=("exports/concept.png",),
        )

    def _vision_request(self) -> VisionInspectionRequest:
        image = VisionImageRef(
            image_id="concept",
            content_hash=HASH_A,
            pixel_hash=HASH_B,
            byte_count=128,
            width=16,
            height=16,
        )
        return VisionInspectionRequest.create(
            images=(image,),
            objective="Inspect silhouette readability and rendering artifacts",
            criteria=("silhouette readability", "obvious generation artifacts"),
            expected_model_id="vision-model",
            expected_model_hash=HASH_C,
            max_output_tokens=1024,
        )

    def test_phase21_ids_use_typed_infrastructure_identity(self) -> None:
        for kind in (
            IdKind.IMAGE_WORKSPACE,
            IdKind.IMAGE_OPERATION,
            IdKind.VISION_INSPECTION,
        ):
            value = new_id(kind)
            self.assertTrue(validate_id(value, kind))

    def test_generate_request_is_content_addressed_and_has_no_arbitrary_graph(self) -> None:
        request = self._generate_request()
        same = ImageOperationRequest(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            operation=request.operation,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            workflow_id=request.workflow_id,
            workflow_hash=request.workflow_hash,
            model_id=request.model_id,
            model_hash=request.model_hash,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            width=request.width,
            height=request.height,
            seed=request.seed,
            steps=request.steps,
            guidance_scale=request.guidance_scale,
            output_relative_paths=request.output_relative_paths,
            input_images=request.input_images,
            budget=request.budget,
        )
        self.assertEqual(request.content_hash, same.content_hash)
        self.assertNotIn("workflow", request.to_dict())
        self.assertNotIn("javascript", request.to_dict())
        self.assertNotIn("task_status", request.to_dict())

    def test_generate_and_edit_input_rules_fail_closed(self) -> None:
        image = RasterInputRef(
            image_id="source",
            relative_path="inputs/source.png",
            content_hash=HASH_A,
            pixel_hash=HASH_B,
            byte_count=128,
            width=16,
            height=16,
        )
        with self.assertRaises(ImageVisionModelError):
            ImageOperationRequest.create(
                operation=ImageOperation.GENERATE,
                backend_id="comfyui",
                backend_version="0.1",
                workflow_id="concept-v1",
                workflow_hash=HASH_A,
                model_id="model",
                model_hash=HASH_B,
                prompt="test",
                negative_prompt="",
                width=16,
                height=16,
                seed=1,
                steps=1,
                guidance_scale=1.0,
                output_relative_paths=("exports/out.png",),
                input_images=(image,),
            )
        with self.assertRaises(ImageVisionModelError):
            ImageOperationRequest.create(
                operation=ImageOperation.EDIT,
                backend_id="comfyui",
                backend_version="0.1",
                workflow_id="edit-v1",
                workflow_hash=HASH_A,
                model_id="model",
                model_hash=HASH_B,
                prompt="test",
                negative_prompt="",
                width=16,
                height=16,
                seed=1,
                steps=1,
                guidance_scale=1.0,
                output_relative_paths=("exports/out.png",),
            )

    def test_output_paths_are_portable_bounded_png_exports(self) -> None:
        base = self._generate_request()
        for bad in ("../escape.png", "/tmp/out.png", "output.png", "exports/out.jpg"):
            with self.subTest(path=bad), self.assertRaises(ImageVisionModelError):
                ImageOperationRequest(
                    operation_id=base.operation_id,
                    workspace_id=base.workspace_id,
                    operation=base.operation,
                    backend_id=base.backend_id,
                    backend_version=base.backend_version,
                    workflow_id=base.workflow_id,
                    workflow_hash=base.workflow_hash,
                    model_id=base.model_id,
                    model_hash=base.model_hash,
                    prompt=base.prompt,
                    negative_prompt=base.negative_prompt,
                    width=base.width,
                    height=base.height,
                    seed=base.seed,
                    steps=base.steps,
                    guidance_scale=base.guidance_scale,
                    output_relative_paths=(bad,),
                )

    def test_success_result_must_bind_exact_request_and_outputs(self) -> None:
        request = self._generate_request()
        output = ImageOutputEvidence(
            relative_path="exports/concept.png",
            content_hash=HASH_A,
            pixel_hash=HASH_B,
            byte_count=128,
            width=512,
            height=512,
        )
        result = ImageOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=ImageResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            workflow_hash=request.workflow_hash,
            model_id=request.model_id,
            model_hash=request.model_hash,
            outputs=(output,),
        )
        result.bind_request(request)
        changed = ImageOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=ImageResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            workflow_hash=request.workflow_hash,
            model_id=request.model_id,
            model_hash=request.model_hash,
            outputs=(
                ImageOutputEvidence(
                    relative_path="exports/other.png",
                    content_hash=HASH_A,
                    pixel_hash=HASH_B,
                    byte_count=128,
                    width=512,
                    height=512,
                ),
            ),
        )
        with self.assertRaises(ImageVisionModelError):
            changed.bind_request(request)

    def test_vision_request_is_frozen_and_model_report_is_advisory_only(self) -> None:
        request = self._vision_request()
        raw = json.dumps(
            {
                "summary": "Readable overall.",
                "findings": [
                    {
                        "category": "readability",
                        "severity": "MEDIUM",
                        "image_id": "concept",
                        "description": "Hammer silhouette merges with the torso.",
                    }
                ],
            }
        )
        report = parse_vision_report(
            raw,
            request=request,
            model_id="vision-model",
            model_hash=HASH_C,
            input_tokens=100,
            output_tokens=30,
        )
        self.assertFalse(report.semantic_findings_verified)
        self.assertTrue(report.advisory_only)
        self.assertEqual(report.findings[0].severity, VisionSeverity.MEDIUM)
        report.bind_request(request)

    def test_vision_response_rejects_authority_fields_and_unknown_images(self) -> None:
        request = self._vision_request()
        with self.assertRaises(ImageVisionModelError):
            parse_vision_report(
                json.dumps(
                    {
                        "summary": "ok",
                        "findings": [],
                        "verified": True,
                    }
                ),
                request=request,
                model_id="vision-model",
                model_hash=HASH_C,
            )
        with self.assertRaises(ImageVisionModelError):
            parse_vision_report(
                json.dumps(
                    {
                        "summary": "ok",
                        "findings": [
                            {
                                "category": "artifact",
                                "severity": "LOW",
                                "image_id": "not-frozen",
                                "description": "unknown source",
                            }
                        ],
                    }
                ),
                request=request,
                model_id="vision-model",
                model_hash=HASH_C,
            )

    def test_model_identity_drift_fails_report_binding(self) -> None:
        request = self._vision_request()
        with self.assertRaises(ImageVisionModelError):
            parse_vision_report(
                json.dumps({"summary": "ok", "findings": []}),
                request=request,
                model_id="different-model",
                model_hash=HASH_C,
            )
        with self.assertRaises(ImageVisionModelError):
            VisionReport(
                inspection_id=request.inspection_id,
                request_hash=request.content_hash,
                model_id=request.expected_model_id,
                model_hash=request.expected_model_hash,
                summary="ok",
                findings=(),
                semantic_findings_verified=True,
            )


if __name__ == "__main__":
    unittest.main()
