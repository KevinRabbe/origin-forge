from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from origin_forge.audio_models import (
    AudioOperation,
    AudioOperationRequest,
    AudioOperationResult,
    AudioOutputEvidence,
    AudioResultStatus,
    AudioSourceRef,
    canonical_bytes,
)
from origin_forge.audio_profiles import AudioProfileKind, GovernedAudioProfile
from origin_forge.audio_service import AudioOperationService, AudioServiceError
from origin_forge.audio_wav import encode_pcm16_wav, inspect_pcm16_wav
from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


RUNTIME_HASH = "sha256:" + "7" * 64


class _FakeAudioAdapter:
    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        corrupt: bool = False,
        reported_workspace: Path | None = None,
    ):
        self.runtime = runtime
        self.corrupt = corrupt
        self.reported_workspace = reported_workspace

    def execute(self, request: AudioOperationRequest, source_bytes_by_id):
        if set(source_bytes_by_id) != {source.source_id for source in request.inputs}:
            raise AssertionError("service did not provide exact frozen source set")
        workspace = self.runtime.state_dir / "audio-workspaces" / request.workspace_id
        (workspace / "request").mkdir(parents=True)
        (workspace / "inputs").mkdir()
        (workspace / "exports").mkdir()
        (workspace / "runtime").mkdir()
        (workspace / "request" / "request.json").write_bytes(
            canonical_bytes(request.to_dict())
        )
        pcm = b"".join(struct.pack("<h", value) for value in (0, 100, -100, 0))
        data = encode_pcm16_wav(
            channels=request.target_channels,
            sample_rate=request.target_sample_rate,
            pcm_bytes=pcm if request.target_channels == 1 else b"".join(
                struct.pack("<hh", value, value) for value in (0, 100, -100, 0)
            ),
        )
        inspection = inspect_pcm16_wav(data)
        path = workspace / request.output_relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        output = AudioOutputEvidence(
            relative_path=request.output_relative_path,
            content_hash=inspection.content_hash,
            pcm_hash=inspection.pcm_hash,
            byte_count=inspection.byte_count,
            frame_count=inspection.frame_count,
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
            peak_abs_sample=inspection.peak_abs_sample,
            clipped_sample_count=inspection.clipped_sample_count,
            nonzero_sample_count=inspection.nonzero_sample_count,
        )
        result = AudioOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=AudioResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            profile_id=request.profile_id,
            profile_hash=request.profile_hash,
            model_id=request.model_id,
            model_hash=request.model_hash,
            outputs=(output,),
        )
        if self.corrupt:
            path.write_bytes(data + b"drift")
        return SimpleNamespace(
            request=request,
            result=result,
            workspace_path=(
                self.reported_workspace
                if self.reported_workspace is not None
                else workspace
            ),
        )


class AudioOperationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("audio-service-test")
        self.lineage = OriginForgeLineage(self.runtime)
        goal = self.runtime.create_goal("Create audio evidence")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "Process source audio")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )
        self.profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.FFMPEG_PCM16,
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=8_000,
            target_channels=1,
        )
        self.source_path = self.root / "fixtures" / "source.wav"
        self.source_path.parent.mkdir()
        self.source_data = encode_pcm16_wav(
            channels=1,
            sample_rate=8_000,
            pcm_bytes=b"".join(struct.pack("<h", value) for value in (1, 2, 3, 4)),
        )
        self.source_path.write_bytes(self.source_data)
        self.source_artifact_id = self.lineage.create_artifact(
            artifact_type="TEST_AUDIO_WAV",
            path_or_uri=str(self.source_path),
            status="PRODUCED",
        )
        inspection = inspect_pcm16_wav(self.source_data)
        self.source_ref = AudioSourceRef(
            source_id="source",
            relative_path="inputs/source.wav",
            content_hash=inspection.content_hash,
            pcm_hash=inspection.pcm_hash,
            byte_count=inspection.byte_count,
            frame_count=inspection.frame_count,
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _request(self) -> AudioOperationRequest:
        return AudioOperationRequest.create(
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id=self.profile.backend_id,
            backend_version=self.profile.backend_version,
            profile_id=self.profile.profile_id,
            profile_hash=self.profile.profile_hash,
            inputs=(self.source_ref,),
            target_sample_rate=self.profile.target_sample_rate,
            target_channels=self.profile.target_channels,
            max_duration_ms=1_000,
            output_relative_path="exports/processed.wav",
        )

    @staticmethod
    def _assert_task_not_completed(before, after) -> None:
        if after["status"] != TaskStatus.RUNNING.value:
            raise AssertionError("audio evidence service changed Task status")
        if after["revision"] != before["revision"]:
            raise AssertionError("audio evidence service changed Task revision")
        if after["attempt_count"] != before["attempt_count"] + 1:
            raise AssertionError("audio evidence service did not record one Run attempt")
        if after["assigned_run_id"] is not None:
            raise AssertionError("finished audio Run left Task assigned")

    def test_success_records_structural_artifacts_without_task_success(self) -> None:
        before = self.runtime.get_task(self.task)
        result = AudioOperationService(
            self.runtime, _FakeAudioAdapter(self.runtime)
        ).execute(
            self.task,
            self._request(),
            source_artifact_ids={"source": self.source_artifact_id},
        )
        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], AudioOperationService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

        artifact = self.lineage.get_artifact(result.output.artifact_id)
        self.assertEqual(artifact["type"], "AUDIO_OUTPUT_WAV")
        verifications = self.lineage.list_artifact_verifications(
            result.output.artifact_id
        )
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["verification_type"], "audio-output-integrity")
        self.assertEqual(verifications[0]["status"], "PASS")
        run_verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(
            run_verifications[0]["verification_type"], "audio-operation-structure"
        )
        self.assertFalse(result.to_dict()["semantic_audio_quality_verified"])
        self.assertFalse(result.to_dict()["production_task_verified"])
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])

    def test_source_drift_fails_before_audio_run_exists(self) -> None:
        before = self.runtime.get_task(self.task)
        self.source_path.write_bytes(self.source_data + b"tamper")
        with self.assertRaises(AudioServiceError):
            AudioOperationService(
                self.runtime, _FakeAudioAdapter(self.runtime)
            ).execute(
                self.task,
                self._request(),
                source_artifact_ids={"source": self.source_artifact_id},
            )
        self.assertEqual(self.runtime.get_task(self.task), before)
        audio_runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == AudioOperationService.RUN_ROLE
        ]
        self.assertEqual(audio_runs, [])

    def test_backend_workspace_escape_fails_run_only(self) -> None:
        before = self.runtime.get_task(self.task)
        with self.assertRaisesRegex(AudioServiceError, "outside the exact frozen workspace ID"):
            AudioOperationService(
                self.runtime,
                _FakeAudioAdapter(
                    self.runtime,
                    reported_workspace=self.runtime.state_dir,
                ),
            ).execute(
                self.task,
                self._request(),
                source_artifact_ids={"source": self.source_artifact_id},
            )
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == AudioOperationService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_backend_output_drift_fails_run_only(self) -> None:
        before = self.runtime.get_task(self.task)
        with self.assertRaisesRegex(AudioServiceError, "output bytes drifted"):
            AudioOperationService(
                self.runtime,
                _FakeAudioAdapter(self.runtime, corrupt=True),
            ).execute(
                self.task,
                self._request(),
                source_artifact_ids={"source": self.source_artifact_id},
            )
        self._assert_task_not_completed(before, self.runtime.get_task(self.task))
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == AudioOperationService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_service_exposes_no_task_or_release_authority_surface(self) -> None:
        service = AudioOperationService(self.runtime, _FakeAudioAdapter(self.runtime))
        for forbidden in (
            "transition_task",
            "verify_task",
            "complete_task",
            "adopt",
            "sign",
            "merge",
            "release",
            "install_plugin",
            "download_model",
        ):
            self.assertFalse(hasattr(service, forbidden))


if __name__ == "__main__":
    unittest.main()
