from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observation_models import (
    RuntimeCaptureKind,
    RuntimeCaptureSpec,
    RuntimeExitKind,
    RuntimeLogEvidence,
    RuntimeObservationRequest,
    RuntimeObservationResult,
    RuntimeObservationStatus,
    RuntimePerformanceEvidence,
    canonical_bytes,
)
from origin_forge.runtime_observation_service import RuntimeObservationService
from origin_forge.state import FlowStatus, TaskStatus


EXECUTABLE_HASH = "sha256:" + "8" * 64


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _CrashBeforeCaptureBackend:
    def __init__(self, runtime: OriginForgeRuntime):
        self.runtime = runtime

    def execute(self, request: RuntimeObservationRequest):
        workspace = self.runtime.state_dir / "runtime-observations" / request.workspace_id
        for name in ("request", "logs", "captures", "runtime"):
            (workspace / name).mkdir(parents=True, exist_ok=True)
        (workspace / "request" / "request.json").write_bytes(
            canonical_bytes(request.to_dict())
        )
        stdout = b"booted\n"
        stderr = b"fatal-before-capture\n"
        (workspace / "logs" / "stdout.log").write_bytes(stdout)
        (workspace / "logs" / "stderr.log").write_bytes(stderr)
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
            exit_code=7,
            stdout=RuntimeLogEvidence("logs/stdout.log", _hash(stdout), len(stdout)),
            stderr=RuntimeLogEvidence("logs/stderr.log", _hash(stderr), len(stderr)),
            captures=(),
            performance=RuntimePerformanceEvidence(duration_ms=50, peak_rss_kib=1024),
        )
        return SimpleNamespace(request=request, result=result, workspace_path=workspace)


class RuntimeObservationPartialServiceTests(unittest.TestCase):
    def test_service_records_missing_capture_ids_without_losing_crash_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime = OriginForgeRuntime(Path(tempdir))
            runtime.initialize("runtime-observation-partial-service-test")
            goal = runtime.create_goal("Observe crash")
            flow = runtime.create_flow(goal)
            runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
            task = runtime.create_task(flow, "Observe target")
            revision = runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
            runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)

            request = RuntimeObservationRequest.create(
                backend_id="fixture-observer",
                backend_version="1",
                target_id="fixture-game",
                target_version="1",
                executable_hash=EXECUTABLE_HASH,
                captures=(
                    RuntimeCaptureSpec(
                        capture_id="late-shot",
                        kind=RuntimeCaptureKind.SCREENSHOT,
                        relative_path="captures/late-shot.png",
                        timestamp_ms=1000,
                    ),
                ),
            )
            result = RuntimeObservationService(
                runtime, _CrashBeforeCaptureBackend(runtime)
            ).execute(task, request)

            self.assertTrue(result.crash_detected)
            self.assertFalse(result.timed_out)
            self.assertEqual(result.captures, ())
            self.assertEqual(result.missing_capture_ids, ("late-shot",))
            self.assertEqual(result.to_dict()["missing_capture_ids"], ["late-shot"])
            verification = runtime.list_verifications("RUN", result.run_id)[0]
            evidence = json.loads(verification["evidence_json"])
            self.assertEqual(evidence["missing_capture_ids"], ["late-shot"])
            self.assertEqual(runtime.get_task(task)["status"], TaskStatus.RUNNING.value)
            self.assertEqual(runtime.list_verifications("TASK", task), [])


if __name__ == "__main__":
    unittest.main()
