from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from origin_forge.ids import IdKind, new_id
from origin_forge.image_vision_models import (
    ImageOperation,
    ImageOperationRequest,
    ImageOperationResult,
    ImageOutputEvidence,
    ImageResultStatus,
    VisionImageRef,
    VisionInspectionRequest,
    VisionReport,
    canonical_bytes,
)
from origin_forge.image_vision_service import (
    ImageGenerationService,
    ImageVisionServiceError,
    VisionInspectionService,
)
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png, inspect_rgba8_png
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


MODEL_HASH = "sha256:" + "a" * 64
WORKFLOW_HASH = "sha256:" + "b" * 64
VISION_HASH = "sha256:" + "c" * 64


class _FakeImageAdapter:
    def __init__(self, runtime: OriginForgeRuntime, *, corrupt: bool = False):
        self.runtime = runtime
        self.corrupt = corrupt

    def execute(self, request: ImageOperationRequest):
        workspace = (
            self.runtime.state_dir / "image-workspaces" / request.workspace_id
        )
        (workspace / "request").mkdir(parents=True)
        (workspace / "inputs").mkdir()
        (workspace / "exports").mkdir()
        (workspace / "runtime").mkdir()
        (workspace / "request" / "request.json").write_bytes(
            canonical_bytes(request.to_dict())
        )
        png = encode_rgba8_png(
            PixelPlane(
                request.width,
                request.height,
                bytes([20, 30, 40, 255] * (request.width * request.height)),
            )
        )
        inspection = inspect_rgba8_png(png)
        path = workspace / request.output_relative_paths[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        output = ImageOutputEvidence(
            relative_path=request.output_relative_paths[0],
            content_hash="sha256:" + hashlib.sha256(png).hexdigest(),
            pixel_hash=inspection.pixel_hash,
            byte_count=len(png),
            width=inspection.width,
            height=inspection.height,
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
        if self.corrupt:
            path.write_bytes(png + b"drift")
        return SimpleNamespace(
            request=request,
            result=result,
            workspace_path=workspace,
        )


class _FakeVisionAdapter:
    model_id = "vision-model"
    model_hash = VISION_HASH

    def inspect(self, request: VisionInspectionRequest, image_bytes_by_id):
        if set(image_bytes_by_id) != {image.image_id for image in request.images}:
            raise AssertionError("service did not provide exact frozen image set")
        report = VisionReport(
            inspection_id=request.inspection_id,
            request_hash=request.content_hash,
            model_id=self.model_id,
            model_hash=self.model_hash,
            summary="Advisory inspection completed.",
            findings=(),
            input_tokens=10,
            output_tokens=4,
        )
        report.bind_request(request)
        return report


class ImageVisionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("image-vision-service-test")
        self.lineage = OriginForgeLineage(self.runtime)
        goal = self.runtime.create_goal("Create and inspect concept art")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "Create image")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _request() -> ImageOperationRequest:
        return ImageOperationRequest.create(
            operation=ImageOperation.GENERATE,
            backend_id="fake-image",
            backend_version="1",
            workflow_id="concept-v1",
            workflow_hash=WORKFLOW_HASH,
            model_id="image-model",
            model_hash=MODEL_HASH,
            prompt="factory enemy concept",
            negative_prompt="",
            width=4,
            height=4,
            seed=7,
            steps=4,
            guidance_scale=2.0,
            output_relative_paths=("exports/concept.png",),
        )

    @staticmethod
    def _assert_task_not_completed(before, after) -> None:
        if after["status"] != TaskStatus.RUNNING.value:
            raise AssertionError("media evidence service changed Task status")
        if after["revision"] != before["revision"]:
            raise AssertionError("media evidence service changed Task revision")
        if after["attempt_count"] != before["attempt_count"] + 1:
            raise AssertionError("media evidence service did not record one Run attempt")
        if after["assigned_run_id"] is not None:
            raise AssertionError("finished media Run left Task assigned")

    def test_generation_records_artifacts_and_raster_pass_without_task_success(self) -> None:
        before = self.runtime.get_task(self.task)
        result = ImageGenerationService(
            self.runtime, _FakeImageAdapter(self.runtime)
        ).execute(self.task, self._request())
        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], ImageGenerationService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])
        self.assertEqual(len(result.outputs), 1)
        artifact_verifications = self.lineage.list_artifact_verifications(
            result.outputs[0].artifact_id
        )
        self.assertEqual(len(artifact_verifications), 1)
        self.assertEqual(
            artifact_verifications[0]["verification_type"],
            "image-output-integrity",
        )
        self.assertEqual(artifact_verifications[0]["status"], "PASS")
        run_verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(
            run_verifications[0]["verification_type"],
            "image-generation-structure",
        )
        self.assertFalse(result.to_dict()["semantic_visual_quality_verified"])
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])

    def test_generation_detects_post_backend_output_drift_and_fails_run_only(self) -> None:
        before = self.runtime.get_task(self.task)
        with self.assertRaises(ImageVisionServiceError):
            ImageGenerationService(
                self.runtime, _FakeImageAdapter(self.runtime, corrupt=True)
            ).execute(self.task, self._request())
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == ImageGenerationService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def _source_artifact(self):
        path = self.root / "inputs" / "source.png"
        path.parent.mkdir()
        png = encode_rgba8_png(PixelPlane(2, 2, bytes([1, 2, 3, 255] * 4)))
        path.write_bytes(png)
        artifact_id = self.lineage.create_artifact(
            artifact_type="TEST_RASTER_PNG",
            path_or_uri=str(path),
            status="PRODUCED",
        )
        inspection = inspect_rgba8_png(png)
        ref = VisionImageRef(
            image_id="source",
            content_hash="sha256:" + hashlib.sha256(png).hexdigest(),
            pixel_hash=inspection.pixel_hash,
            byte_count=len(png),
            width=inspection.width,
            height=inspection.height,
        )
        return artifact_id, ref, path

    def test_vision_report_is_durable_structural_evidence_not_semantic_verification(self) -> None:
        artifact_id, ref, _ = self._source_artifact()
        request = VisionInspectionRequest.create(
            images=(ref,),
            objective="Inspect composition",
            criteria=("readability",),
            expected_model_id="vision-model",
            expected_model_hash=VISION_HASH,
        )
        before = self.runtime.get_task(self.task)
        result = VisionInspectionService(
            self.runtime, _FakeVisionAdapter()
        ).execute(
            self.task,
            request,
            image_artifact_ids={"source": artifact_id},
        )
        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], VisionInspectionService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])
        self.assertFalse(result.report.semantic_findings_verified)
        self.assertTrue(result.report.advisory_only)
        verifications = self.lineage.list_artifact_verifications(
            result.report_artifact_id
        )
        self.assertEqual(len(verifications), 1)
        self.assertEqual(
            verifications[0]["verification_type"], "vision-report-structure"
        )
        self.assertEqual(verifications[0]["status"], "PASS")
        self.assertFalse(result.to_dict()["semantic_findings_verified"])

    def test_vision_source_drift_fails_before_model_run_and_creates_no_vision_run(self) -> None:
        artifact_id, ref, path = self._source_artifact()
        request = VisionInspectionRequest.create(
            images=(ref,),
            objective="Inspect composition",
            criteria=(),
            expected_model_id="vision-model",
            expected_model_hash=VISION_HASH,
        )
        path.write_bytes(b"tampered")
        before = self.runtime.get_task(self.task)
        with self.assertRaises(Exception):
            VisionInspectionService(self.runtime, _FakeVisionAdapter()).execute(
                self.task,
                request,
                image_artifact_ids={"source": artifact_id},
            )
        self.assertEqual(self.runtime.get_task(self.task), before)
        vision_runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == VisionInspectionService.RUN_ROLE
        ]
        self.assertEqual(vision_runs, [])

    def test_services_expose_no_task_merge_release_or_adoption_surface(self) -> None:
        objects = (
            ImageGenerationService(self.runtime, _FakeImageAdapter(self.runtime)),
            VisionInspectionService(self.runtime, _FakeVisionAdapter()),
        )
        for obj in objects:
            for forbidden in (
                "transition_task",
                "verify_task",
                "complete_task",
                "merge",
                "release",
                "sign",
                "adopt",
                "install_plugin",
                "download_model",
            ):
                self.assertFalse(hasattr(obj, forbidden))


if __name__ == "__main__":
    unittest.main()
