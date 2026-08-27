from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from origin_forge.ids import IdKind, new_id
from origin_forge.image_png import inspect_truecolor8_png
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png
from origin_forge.production_dispatch_invocation_runtime_owner import (
    _require_runtime_binding_evidence,
)
from origin_forge.production_runtime_dispatch_output_binding_models import (
    RUNTIME_EXECUTION_OWNER_ID,
    RuntimeDispatchCapture,
    RuntimeDispatchOutputBinding,
)
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.runtime_observation_models import (
    RuntimeCaptureEvidence,
    RuntimeCaptureKind,
    RuntimeCaptureSpec,
    RuntimeExitKind,
    RuntimeLogEvidence,
    RuntimeObservationRequest,
    RuntimeObservationResult,
    RuntimeObservationStatus,
    RuntimePerformanceEvidence,
    VisualBaselineRef,
    canonical_bytes,
)
from origin_forge.runtime_observation_service import (
    RuntimeObservationService,
    RuntimeObservationServiceError,
)
from origin_forge.state import FlowStatus, RunStatus, TaskStatus

EXECUTABLE_HASH = "sha256:" + "9" * 64


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _FakeObserver:
    def __init__(
        self,
        runtime: OriginForgeRuntime,
        capture_png: bytes,
        *,
        reported_workspace: Path | None = None,
    ):
        self.runtime = runtime
        self.capture_png = capture_png
        self.reported_workspace = reported_workspace

    def execute(self, request: RuntimeObservationRequest):
        workspace = (
            self.runtime.state_dir / "runtime-observations" / request.workspace_id
        )
        for name in ("request", "logs", "captures", "runtime"):
            (workspace / name).mkdir(parents=True, exist_ok=name != "request")
        (workspace / "request" / "request.json").write_bytes(
            canonical_bytes(request.to_dict())
        )
        stdout = b"fixture stdout\n"
        stderr = b"fixture stderr\n"
        (workspace / "logs" / "stdout.log").write_bytes(stdout)
        (workspace / "logs" / "stderr.log").write_bytes(stderr)
        captures = []
        for spec in request.captures:
            path = workspace / spec.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.capture_png)
            inspection = inspect_truecolor8_png(self.capture_png)
            captures.append(
                RuntimeCaptureEvidence(
                    capture_id=spec.capture_id,
                    kind=spec.kind,
                    relative_path=spec.relative_path,
                    timestamp_ms=spec.timestamp_ms,
                    content_hash=_hash(self.capture_png),
                    pixel_hash=inspection.pixel_hash,
                    byte_count=inspection.byte_count,
                    width=inspection.width,
                    height=inspection.height,
                )
            )
        result = RuntimeObservationResult(
            observation_id=request.observation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=RuntimeObservationStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            target_id=request.target_id,
            target_version=request.target_version,
            executable_hash=request.executable_hash,
            exit_kind=RuntimeExitKind.FAILED,
            exit_code=3,
            stdout=RuntimeLogEvidence("logs/stdout.log", _hash(stdout), len(stdout)),
            stderr=RuntimeLogEvidence("logs/stderr.log", _hash(stderr), len(stderr)),
            captures=tuple(captures),
            performance=RuntimePerformanceEvidence(duration_ms=123, peak_rss_kib=4567),
        )
        return SimpleNamespace(
            request=request,
            result=result,
            workspace_path=self.reported_workspace or workspace,
        )


class RuntimeObservationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("runtime-observation-service-test")
        self.lineage = OriginForgeLineage(self.runtime)
        goal = self.runtime.create_goal("Observe runtime")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "Capture runtime evidence")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )
        self.baseline_png = encode_rgba8_png(
            PixelPlane(1, 1, bytes((255, 0, 0, 255)))
        )
        baseline_path = self.root / "fixtures" / "baseline.png"
        baseline_path.parent.mkdir()
        baseline_path.write_bytes(self.baseline_png)
        self.baseline_artifact_id = self.lineage.create_artifact(
            artifact_type="TEST_VISUAL_BASELINE_PNG",
            path_or_uri=str(baseline_path),
            status="PRODUCED",
        )
        inspection = inspect_truecolor8_png(self.baseline_png)
        self.baseline = VisualBaselineRef(
            baseline_id="main-menu",
            content_hash=_hash(self.baseline_png),
            pixel_hash=inspection.pixel_hash,
            width=inspection.width,
            height=inspection.height,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _request(self) -> RuntimeObservationRequest:
        return RuntimeObservationRequest.create(
            backend_id="fake-observer",
            backend_version="1",
            target_id="fixture-game",
            target_version="1",
            executable_hash=EXECUTABLE_HASH,
            captures=(
                RuntimeCaptureSpec(
                    "main-menu",
                    RuntimeCaptureKind.SCREENSHOT,
                    "captures/main-menu.png",
                    100,
                    baseline_id="main-menu",
                ),
                RuntimeCaptureSpec(
                    "frame-1",
                    RuntimeCaptureKind.VIDEO_FRAME,
                    "captures/video/0001.png",
                    200,
                ),
            ),
            baselines=(self.baseline,),
        )

    @staticmethod
    def _assert_task_not_completed(before, after) -> None:
        if after["status"] != TaskStatus.RUNNING.value:
            raise AssertionError("runtime observation changed Task status")
        if after["revision"] != before["revision"]:
            raise AssertionError("runtime observation changed Task revision")
        if after["attempt_count"] != before["attempt_count"] + 1:
            raise AssertionError("runtime observation did not record one Run attempt")
        if after["assigned_run_id"] is not None:
            raise AssertionError("finished runtime observation left Task assigned")

    def test_success_persists_crash_visual_and_performance_evidence_only(self) -> None:
        before = self.runtime.get_task(self.task)
        result = RuntimeObservationService(
            self.runtime, _FakeObserver(self.runtime, self.baseline_png)
        ).execute(
            self.task,
            self._request(),
            baseline_artifact_ids={"main-menu": self.baseline_artifact_id},
        )
        self.assertTrue(result.crash_detected)
        self.assertFalse(result.timed_out)
        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], RuntimeObservationService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])
        self.assertEqual(len(result.captures), 2)
        screenshot = next(value for value in result.captures if value.capture_id == "main-menu")
        self.assertIsNotNone(screenshot.visual_diff)
        self.assertTrue(screenshot.visual_diff.passed)
        verifications = self.lineage.list_artifact_verifications(screenshot.artifact_id)
        self.assertEqual(
            [value["verification_type"] for value in verifications],
            ["runtime-capture-integrity", "runtime-visual-regression"],
        )
        self.assertEqual([value["status"] for value in verifications], ["PASS", "PASS"])
        run_verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(
            run_verifications[0]["verification_type"],
            "runtime-observation-structure",
        )
        self.assertFalse(result.to_dict()["production_task_verified"])
        self.assertFalse(result.to_dict()["visual_semantics_verified"])
        self.assertFalse(result.to_dict()["performance_requirement_verified"])

    def test_recovery_evidence_rejects_tampered_capture_before_terminalization(self) -> None:
        request = self._request()
        result = RuntimeObservationService(
            self.runtime, _FakeObserver(self.runtime, self.baseline_png)
        ).execute(
            self.task,
            request,
            baseline_artifact_ids={"main-menu": self.baseline_artifact_id},
        )
        captures = []
        for evidence in result.captures:
            path = self.lineage.local_artifact_path(evidence.artifact_id)
            data = path.read_bytes()
            inspection = inspect_truecolor8_png(data)
            relative_path = path.relative_to(
                self.runtime.state_dir / "runtime-observations" / request.workspace_id
            ).as_posix()
            captures.append(
                RuntimeDispatchCapture(
                    capture_id=evidence.capture_id,
                    artifact_id=evidence.artifact_id,
                    integrity_verification_id=evidence.integrity_verification_id,
                    visual_verification_id=evidence.visual_verification_id,
                    relative_path=relative_path,
                    content_hash=self.lineage.get_artifact(evidence.artifact_id)[
                        "content_hash"
                    ].removeprefix("sha256:"),
                    pixel_hash=inspection.pixel_hash.removeprefix("sha256:"),
                    byte_count=len(data),
                    width=inspection.width,
                    height=inspection.height,
                )
            )
        binding = RuntimeDispatchOutputBinding(
            execution_id=new_id(IdKind.DISPATCH_EXECUTION),
            claim_id=new_id(IdKind.DISPATCH_CLAIM),
            task_id=self.task,
            task_revision=2,
            task_content_hash="a" * 64,
            work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
            work_order_hash="b" * 64,
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            dispatch_binding_hash="c" * 64,
            execution_owner_id=RUNTIME_EXECUTION_OWNER_ID,
            run_id=result.run_id,
            request_artifact_id=result.request_artifact_id,
            result_artifact_id=result.result_artifact_id,
            stdout_artifact_id=result.stdout_artifact_id,
            stderr_artifact_id=result.stderr_artifact_id,
            captures=tuple(captures),
            backend_result_hash=result.backend_result_hash.removeprefix("sha256:"),
            schema_version=1,
            created_at="2026-08-27T00:00:00Z",
        )
        _require_runtime_binding_evidence(self.runtime, binding)
        capture_path = self.lineage.local_artifact_path(captures[0].artifact_id)
        capture_path.write_bytes(
            encode_rgba8_png(PixelPlane(1, 1, bytes((0, 0, 255, 255))))
        )
        with self.assertRaises(RuntimeInvariantError):
            _require_runtime_binding_evidence(self.runtime, binding)

    def test_visual_regression_is_fail_evidence_without_task_failure_authority(self) -> None:
        changed = encode_rgba8_png(PixelPlane(1, 1, bytes((0, 0, 255, 255))))
        before = self.runtime.get_task(self.task)
        result = RuntimeObservationService(
            self.runtime, _FakeObserver(self.runtime, changed)
        ).execute(
            self.task,
            self._request(),
            baseline_artifact_ids={"main-menu": self.baseline_artifact_id},
        )
        screenshot = next(value for value in result.captures if value.capture_id == "main-menu")
        self.assertFalse(screenshot.visual_diff.passed)
        verification = next(
            value
            for value in self.lineage.list_artifact_verifications(screenshot.artifact_id)
            if value["verification_type"] == "runtime-visual-regression"
        )
        self.assertEqual(verification["status"], "FAIL")
        self.assertEqual(self.runtime.get_run(result.run_id)["status"], RunStatus.SUCCEEDED.value)
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_baseline_drift_fails_before_runtime_run_exists(self) -> None:
        baseline_path = self.lineage.local_artifact_path(self.baseline_artifact_id)
        baseline_path.write_bytes(self.baseline_png + b"tamper")
        before = self.runtime.get_task(self.task)
        with self.assertRaisesRegex(RuntimeObservationServiceError, "baseline"):
            RuntimeObservationService(
                self.runtime, _FakeObserver(self.runtime, self.baseline_png)
            ).execute(
                self.task,
                self._request(),
                baseline_artifact_ids={"main-menu": self.baseline_artifact_id},
            )
        self.assertEqual(self.runtime.get_task(self.task), before)
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == RuntimeObservationService.RUN_ROLE
        ]
        self.assertEqual(runs, [])

    def test_workspace_escape_fails_only_observation_run(self) -> None:
        before = self.runtime.get_task(self.task)
        with self.assertRaisesRegex(RuntimeObservationServiceError, "outside"):
            RuntimeObservationService(
                self.runtime,
                _FakeObserver(
                    self.runtime,
                    self.baseline_png,
                    reported_workspace=self.runtime.state_dir,
                ),
            ).execute(
                self.task,
                self._request(),
                baseline_artifact_ids={"main-menu": self.baseline_artifact_id},
            )
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == RuntimeObservationService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_service_exposes_no_task_merge_or_release_authority(self) -> None:
        service = RuntimeObservationService(
            self.runtime, _FakeObserver(self.runtime, self.baseline_png)
        )
        for forbidden in (
            "transition_task",
            "verify_task",
            "complete_task",
            "adopt",
            "sign",
            "merge",
            "release",
            "install",
            "download",
        ):
            self.assertFalse(hasattr(service, forbidden))


if __name__ == "__main__":
    unittest.main()
