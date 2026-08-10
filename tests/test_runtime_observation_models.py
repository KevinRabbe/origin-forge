from __future__ import annotations

import unittest

from origin_forge.runtime_observation_models import (
    RuntimeCaptureEvidence,
    RuntimeCaptureKind,
    RuntimeCaptureSpec,
    RuntimeExitKind,
    RuntimeLogEvidence,
    RuntimeObservationModelError,
    RuntimeObservationRequest,
    RuntimeObservationResult,
    RuntimeObservationStatus,
    RuntimePerformanceEvidence,
    VisualBaselineRef,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


class RuntimeObservationModelTests(unittest.TestCase):
    def _baseline(self) -> VisualBaselineRef:
        return VisualBaselineRef(
            baseline_id="main-menu",
            content_hash=SHA_B,
            pixel_hash=SHA_C,
            width=2,
            height=2,
            max_changed_pixels=1,
            max_channel_delta=8,
            max_total_channel_delta=16,
        )

    def _request(self) -> RuntimeObservationRequest:
        return RuntimeObservationRequest.create(
            backend_id="local-process",
            backend_version="1",
            target_id="fixture-game",
            target_version="1",
            executable_hash=SHA_A,
            timeout_seconds=5,
            max_log_bytes=4096,
            captures=(
                RuntimeCaptureSpec(
                    capture_id="shot",
                    kind=RuntimeCaptureKind.SCREENSHOT,
                    relative_path="captures/shot.png",
                    timestamp_ms=100,
                    baseline_id="main-menu",
                ),
                RuntimeCaptureSpec(
                    capture_id="frame-2",
                    kind=RuntimeCaptureKind.VIDEO_FRAME,
                    relative_path="captures/video/0002.png",
                    timestamp_ms=200,
                ),
                RuntimeCaptureSpec(
                    capture_id="frame-1",
                    kind=RuntimeCaptureKind.VIDEO_FRAME,
                    relative_path="captures/video/0001.png",
                    timestamp_ms=150,
                ),
            ),
            baselines=(self._baseline(),),
        )

    def _outputs(self, request: RuntimeObservationRequest) -> tuple[RuntimeCaptureEvidence, ...]:
        return tuple(
            RuntimeCaptureEvidence(
                capture_id=spec.capture_id,
                kind=spec.kind,
                relative_path=spec.relative_path,
                timestamp_ms=spec.timestamp_ms,
                content_hash=SHA_B,
                pixel_hash=SHA_C,
                byte_count=70,
                width=2,
                height=2,
            )
            for spec in request.captures
        )

    def test_request_is_content_addressed_and_orders_timed_captures(self) -> None:
        request = self._request()
        self.assertTrue(request.observation_id.startswith("OBS-"))
        self.assertTrue(request.workspace_id.startswith("OBSWS-"))
        self.assertEqual(
            [capture.capture_id for capture in request.captures],
            ["shot", "frame-1", "frame-2"],
        )
        self.assertTrue(request.content_hash.startswith("sha256:"))
        self.assertEqual(request.to_dict()["baselines"][0]["baseline_id"], "main-menu")

    def test_rejects_unsafe_capture_path_and_duplicate_video_timestamp(self) -> None:
        with self.assertRaises(RuntimeObservationModelError):
            RuntimeCaptureSpec(
                capture_id="bad",
                kind=RuntimeCaptureKind.SCREENSHOT,
                relative_path="../shot.png",
                timestamp_ms=0,
            )
        with self.assertRaisesRegex(RuntimeObservationModelError, "timestamps"):
            RuntimeObservationRequest.create(
                backend_id="local-process",
                backend_version="1",
                target_id="fixture",
                target_version="1",
                executable_hash=SHA_A,
                captures=(
                    RuntimeCaptureSpec(
                        "a", RuntimeCaptureKind.VIDEO_FRAME, "captures/a.png", 10
                    ),
                    RuntimeCaptureSpec(
                        "b", RuntimeCaptureKind.VIDEO_FRAME, "captures/b.png", 10
                    ),
                ),
            )

    def test_result_binds_exact_capture_set_on_normal_exit(self) -> None:
        request = self._request()
        outputs = self._outputs(request)
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
            exit_kind=RuntimeExitKind.EXITED,
            exit_code=0,
            stdout=RuntimeLogEvidence("logs/stdout.log", SHA_B, 0),
            stderr=RuntimeLogEvidence("logs/stderr.log", SHA_B, 0),
            captures=outputs,
            performance=RuntimePerformanceEvidence(12, 1000),
        )
        result.bind_request(request)
        self.assertTrue(result.content_hash.startswith("sha256:"))

        missing = RuntimeObservationResult(
            observation_id=request.observation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=RuntimeObservationStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            target_id=request.target_id,
            target_version=request.target_version,
            executable_hash=request.executable_hash,
            exit_kind=RuntimeExitKind.EXITED,
            exit_code=0,
            stdout=RuntimeLogEvidence("logs/stdout.log", SHA_B, 0),
            stderr=RuntimeLogEvidence("logs/stderr.log", SHA_B, 0),
            captures=outputs[:-1],
            performance=RuntimePerformanceEvidence(12, 1000),
        )
        with self.assertRaisesRegex(RuntimeObservationModelError, "capture set"):
            missing.bind_request(request)

    def test_abnormal_exit_may_bind_declared_capture_subset(self) -> None:
        request = self._request()
        outputs = self._outputs(request)
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
            stdout=RuntimeLogEvidence("logs/stdout.log", SHA_B, 0),
            stderr=RuntimeLogEvidence("logs/stderr.log", SHA_B, 0),
            captures=outputs[:1],
            performance=RuntimePerformanceEvidence(12, 1000),
        )
        result.bind_request(request)

    def test_timeout_may_not_claim_exit_code(self) -> None:
        request = RuntimeObservationRequest.create(
            backend_id="local-process",
            backend_version="1",
            target_id="fixture",
            target_version="1",
            executable_hash=SHA_A,
        )
        with self.assertRaisesRegex(RuntimeObservationModelError, "timeout"):
            RuntimeObservationResult(
                observation_id=request.observation_id,
                workspace_id=request.workspace_id,
                request_hash=request.content_hash,
                status=RuntimeObservationStatus.SUCCEEDED,
                backend_id=request.backend_id,
                backend_version=request.backend_version,
                target_id=request.target_id,
                target_version=request.target_version,
                executable_hash=request.executable_hash,
                exit_kind=RuntimeExitKind.TIMEOUT,
                exit_code=9,
                stdout=RuntimeLogEvidence("logs/stdout.log", SHA_B, 0),
                stderr=RuntimeLogEvidence("logs/stderr.log", SHA_B, 0),
                captures=(),
                performance=RuntimePerformanceEvidence(10, 0),
            )


if __name__ == "__main__":
    unittest.main()
