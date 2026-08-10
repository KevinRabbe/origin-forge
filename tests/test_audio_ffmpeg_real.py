from __future__ import annotations

import hashlib
import os
import struct
import tempfile
import unittest
from pathlib import Path

from origin_forge.adapters.audio_ffmpeg import FfmpegAudioAdapter
from origin_forge.audio_models import AudioOperation, AudioOperationRequest, AudioSourceRef
from origin_forge.audio_profiles import (
    AudioProfileKind,
    AudioProfileStore,
    GovernedAudioProfile,
)
from origin_forge.audio_service import AudioOperationService
from origin_forge.audio_wav import canonicalize_pcm16_wav, encode_pcm16_wav, inspect_pcm16_wav
from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


_REQUIRED_ENV = (
    "ORIGIN_FORGE_REAL_FFMPEG_EXECUTABLE",
    "ORIGIN_FORGE_REAL_FFMPEG_VERSION",
    "ORIGIN_FORGE_REAL_FFMPEG_SOURCE_COMMIT",
    "ORIGIN_FORGE_REAL_FFMPEG_RUNTIME_SHA256",
)


@unittest.skipUnless(
    all(os.environ.get(name) for name in _REQUIRED_ENV),
    "real pinned FFmpeg runtime evidence is not configured",
)
class RealFfmpegAudioIntegrationTests(unittest.TestCase):
    def test_real_pinned_ffmpeg_processes_through_governed_audio_service(self) -> None:
        executable = Path(os.environ["ORIGIN_FORGE_REAL_FFMPEG_EXECUTABLE"])
        version = os.environ["ORIGIN_FORGE_REAL_FFMPEG_VERSION"]
        source_commit = os.environ["ORIGIN_FORGE_REAL_FFMPEG_SOURCE_COMMIT"]
        expected_runtime_hash = os.environ["ORIGIN_FORGE_REAL_FFMPEG_RUNTIME_SHA256"]
        self.assertEqual(source_commit, "38b88335f99e76ed89ff3c93f877fdefce736c13")
        self.assertEqual(version, "8.1.2")
        self.assertTrue(executable.is_file())
        self.assertFalse(executable.is_symlink())
        actual_runtime_hash = "sha256:" + hashlib.sha256(executable.read_bytes()).hexdigest()
        self.assertEqual(actual_runtime_hash, expected_runtime_hash)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("real-ffmpeg-evidence")
            lineage = OriginForgeLineage(runtime)

            goal = runtime.create_goal("Prove pinned FFmpeg audio evidence")
            flow = runtime.create_flow(goal)
            runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
            task = runtime.create_task(flow, "Process one frozen PCM16 WAV")
            revision = runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
            runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)

            profile = GovernedAudioProfile.create(
                kind=AudioProfileKind.FFMPEG_PCM16,
                operation=AudioOperation.PROCESS_AUDIO,
                backend_id="ffmpeg",
                backend_version=version,
                runtime_hash=actual_runtime_hash,
                target_sample_rate=8_000,
                target_channels=2,
            )
            AudioProfileStore(runtime).put(profile)
            self.assertEqual(
                AudioProfileStore(runtime).get(profile.profile_id, profile.profile_hash),
                profile,
            )

            source_pcm = b"".join(
                struct.pack("<h", ((index % 64) - 32) * 256)
                for index in range(320)
            )
            source_data = encode_pcm16_wav(
                channels=1,
                sample_rate=16_000,
                pcm_bytes=source_pcm,
            )
            source_path = root / "fixtures" / "source.wav"
            source_path.parent.mkdir()
            source_path.write_bytes(source_data)
            source_artifact_id = lineage.create_artifact(
                artifact_type="TEST_AUDIO_WAV",
                path_or_uri=str(source_path),
                status="PRODUCED",
            )
            source_inspection = inspect_pcm16_wav(source_data)
            source_ref = AudioSourceRef(
                source_id="source",
                relative_path="inputs/source.wav",
                content_hash=source_inspection.content_hash,
                pcm_hash=source_inspection.pcm_hash,
                byte_count=source_inspection.byte_count,
                frame_count=source_inspection.frame_count,
                sample_rate=source_inspection.sample_rate,
                channels=source_inspection.channels,
            )
            request = AudioOperationRequest.create(
                operation=AudioOperation.PROCESS_AUDIO,
                backend_id=profile.backend_id,
                backend_version=profile.backend_version,
                profile_id=profile.profile_id,
                profile_hash=profile.profile_hash,
                inputs=(source_ref,),
                target_sample_rate=profile.target_sample_rate,
                target_channels=profile.target_channels,
                max_duration_ms=1_000,
                timeout_seconds=30,
                output_relative_path="exports/processed.wav",
            )
            adapter = FfmpegAudioAdapter(runtime, profile, executable=executable)
            service = AudioOperationService(runtime, adapter)
            before = runtime.get_task(task)
            result = service.execute(
                task,
                request,
                source_artifact_ids={"source": source_artifact_id},
            )
            after = runtime.get_task(task)

            self.assertEqual(runtime.get_run(result.run_id)["status"], RunStatus.SUCCEEDED.value)
            self.assertEqual(after["status"], TaskStatus.RUNNING.value)
            self.assertEqual(after["revision"], before["revision"])
            self.assertEqual(after["attempt_count"], before["attempt_count"] + 1)
            self.assertIsNone(after["assigned_run_id"])

            output_artifact = lineage.get_artifact(result.output.artifact_id)
            self.assertEqual(output_artifact["type"], "AUDIO_OUTPUT_WAV")
            output_path = lineage.local_artifact_path(result.output.artifact_id)
            output_data = output_path.read_bytes()
            self.assertEqual(canonicalize_pcm16_wav(output_data), output_data)
            output = inspect_pcm16_wav(output_data)
            self.assertEqual(output.sample_rate, 8_000)
            self.assertEqual(output.channels, 2)
            self.assertEqual(output.content_hash, result.output.content_hash)
            self.assertEqual(output.pcm_hash, result.output.pcm_hash)
            passes = [
                row
                for row in lineage.list_artifact_verifications(result.output.artifact_id)
                if row["verification_type"] == "audio-output-integrity"
                and row["verifier"] == "OriginForge.AudioOperationService"
                and row["status"] == "PASS"
            ]
            self.assertEqual(len(passes), 1)
            self.assertFalse((root / "audio" / "processed.wav").exists())


if __name__ == "__main__":
    unittest.main()
