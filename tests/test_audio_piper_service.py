from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from origin_forge.adapters.audio_piper import (
    PiperAudioAdapter,
    PiperProcessOutcome,
    piper_runtime_tree_hash,
)
from origin_forge.audio_models import AudioOperation, AudioOperationRequest
from origin_forge.audio_profiles import AudioProfileKind, GovernedAudioProfile
from origin_forge.audio_service import AudioOperationService
from origin_forge.audio_wav import encode_pcm16_wav
from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _ServicePiperRunner:
    def run(
        self,
        argv,
        *,
        cwd,
        stdin_bytes,
        timeout_seconds,
        max_stdout_bytes,
        max_stderr_bytes,
    ):
        values = tuple(argv)
        if values[1:] == ("--version",):
            return PiperProcessOutcome(0, b"1.6.0\n", b"")
        output = Path(values[values.index("--output-file") + 1])
        pcm = b"".join(
            struct.pack("<h", value) for value in (0, 300, -300, 150, -150, 0)
        )
        output.write_bytes(
            encode_pcm16_wav(channels=1, sample_rate=22_050, pcm_bytes=pcm)
        )
        return PiperProcessOutcome(0, str(output).encode("utf-8") + b"\n", b"")


class PiperAudioServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root / "project")
        self.runtime.initialize("piper-service-test")
        self.lineage = OriginForgeLineage(self.runtime)

        goal = self.runtime.create_goal("Create governed speech evidence")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "Synthesize bounded speech")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )

        self.runtime_root = self.root / "piper-runtime"
        (self.runtime_root / "bin").mkdir(parents=True)
        (self.runtime_root / "lib").mkdir()
        (self.runtime_root / "espeak-ng-data").mkdir()
        self.executable = self.runtime_root / "bin" / "piper"
        self.executable.write_bytes(b"service piper executable")
        (self.runtime_root / "lib" / "libpiper.so").write_bytes(b"service libpiper")
        (self.runtime_root / "lib" / "libonnxruntime.so").write_bytes(
            b"service onnxruntime"
        )
        (self.runtime_root / "espeak-ng-data" / "en_dict").write_bytes(
            b"service espeak data"
        )

        self.model_path = self.root / "voice.onnx"
        self.model_path.write_bytes(b"service voice model")
        self.config_path = self.root / "voice.onnx.json"
        self.config_path.write_text(
            json.dumps({"audio": {"sample_rate": 22_050}}), encoding="utf-8"
        )
        self.license_path = self.root / "MODEL_CARD"
        self.license_path.write_text("CC0-1.0 evidence\n", encoding="utf-8")

        self.profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.PIPER_TTS,
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            runtime_hash=piper_runtime_tree_hash(self.runtime_root),
            target_sample_rate=22_050,
            target_channels=1,
            model_id="en_US-joe-medium",
            model_hash=_sha256(self.model_path.read_bytes()),
            model_config_hash=_sha256(self.config_path.read_bytes()),
            license_id="CC0-1.0",
            license_hash=_sha256(self.license_path.read_bytes()),
        )
        self.adapter = PiperAudioAdapter(
            self.runtime,
            self.profile,
            runtime_root=self.runtime_root,
            executable=self.executable,
            espeak_data_path=self.runtime_root / "espeak-ng-data",
            model_path=self.model_path,
            model_config_path=self.config_path,
            license_path=self.license_path,
            runner=_ServicePiperRunner(),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_piper_service_records_structural_model_evidence_without_task_success(self) -> None:
        request = AudioOperationRequest.create(
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id=self.profile.backend_id,
            backend_version=self.profile.backend_version,
            profile_id=self.profile.profile_id,
            profile_hash=self.profile.profile_hash,
            model_id=self.profile.model_id,
            model_hash=self.profile.model_hash,
            text="Governed speech is evidence, not production approval.",
            target_sample_rate=self.profile.target_sample_rate,
            target_channels=self.profile.target_channels,
            max_duration_ms=5_000,
            timeout_seconds=5,
            output_relative_path="exports/speech.wav",
        )
        before = self.runtime.get_task(self.task)
        result = AudioOperationService(self.runtime, self.adapter).execute(
            self.task,
            request,
            source_artifact_ids={},
        )

        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], AudioOperationService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(run["model_profile"], self.profile.model_id)

        after = self.runtime.get_task(self.task)
        self.assertEqual(after["status"], TaskStatus.RUNNING.value)
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["attempt_count"], before["attempt_count"] + 1)
        self.assertIsNone(after["assigned_run_id"])
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

        output_artifact = self.lineage.get_artifact(result.output.artifact_id)
        self.assertEqual(output_artifact["type"], "AUDIO_OUTPUT_WAV")
        self.assertEqual(output_artifact["model_id"], self.profile.model_id)
        self.assertIn(
            f"audio-model:{self.profile.model_id}:{self.profile.model_hash}",
            output_artifact["tool_versions"],
        )
        verifications = self.lineage.list_artifact_verifications(
            result.output.artifact_id
        )
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["status"], "PASS")
        self.assertEqual(
            verifications[0]["verification_type"], "audio-output-integrity"
        )
        self.assertFalse(result.to_dict()["production_task_verified"])
        self.assertFalse(result.to_dict()["semantic_audio_quality_verified"])
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])


if __name__ == "__main__":
    unittest.main()
