from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from origin_forge.adapters.audio_piper import PiperAudioAdapter, piper_runtime_tree_hash
from origin_forge.audio_models import AudioOperation, AudioOperationRequest
from origin_forge.audio_profiles import (
    AudioProfileKind,
    AudioProfileStore,
    GovernedAudioProfile,
)
from origin_forge.audio_service import AudioOperationService
from origin_forge.audio_wav import canonicalize_pcm16_wav, inspect_pcm16_wav
from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


_REQUIRED_ENV = (
    "ORIGIN_FORGE_REAL_PIPER_RUNTIME_ROOT",
    "ORIGIN_FORGE_REAL_PIPER_EXECUTABLE",
    "ORIGIN_FORGE_REAL_PIPER_ESPEAK_DATA",
    "ORIGIN_FORGE_REAL_PIPER_VERSION",
    "ORIGIN_FORGE_REAL_PIPER_SOURCE_COMMIT",
    "ORIGIN_FORGE_REAL_PIPER_RUNTIME_HASH",
    "ORIGIN_FORGE_REAL_PIPER_ORT_SHA512",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_REPO_COMMIT",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_MODEL",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_CONFIG",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_LICENSE",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_MODEL_SHA256",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_CONFIG_SHA256",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_LICENSE_SHA256",
    "ORIGIN_FORGE_REAL_PIPER_VOICE_LICENSE_ID",
)

_PIPER_SOURCE_COMMIT = "f04d52c5528ac7cf2d73757f57990ff490f75005"
_VOICE_REPO_COMMIT = "375a0fe641dea077c2a47b4e9a056d6da521eed3"
_VOICE_MODEL_SHA256 = (
    "58afce0321b8d9c46d7cdf9c16500cc55a793b4220212dba6b70fb788b3baf06"
)
_ORT_SHA512 = (
    "c49d927a39dc27fcdf3b41436806af74c24c79ead09289d986c359fc1380ea363"
    "cf83d4085212b8972cb752a0fa8b9b1a06b82ad19e2d4dd6e22e44c79050386"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


@unittest.skipUnless(
    all(os.environ.get(name) for name in _REQUIRED_ENV),
    "real pinned Piper runtime/voice evidence is not configured",
)
class RealPiperAudioIntegrationTests(unittest.TestCase):
    def test_real_pinned_piper_synthesizes_through_governed_audio_service(self) -> None:
        runtime_root = Path(os.environ["ORIGIN_FORGE_REAL_PIPER_RUNTIME_ROOT"])
        executable = Path(os.environ["ORIGIN_FORGE_REAL_PIPER_EXECUTABLE"])
        espeak_data = Path(os.environ["ORIGIN_FORGE_REAL_PIPER_ESPEAK_DATA"])
        version = os.environ["ORIGIN_FORGE_REAL_PIPER_VERSION"]
        source_commit = os.environ["ORIGIN_FORGE_REAL_PIPER_SOURCE_COMMIT"]
        expected_runtime_hash = os.environ["ORIGIN_FORGE_REAL_PIPER_RUNTIME_HASH"]
        ort_sha512 = os.environ["ORIGIN_FORGE_REAL_PIPER_ORT_SHA512"]
        voice_repo_commit = os.environ["ORIGIN_FORGE_REAL_PIPER_VOICE_REPO_COMMIT"]
        model_path = Path(os.environ["ORIGIN_FORGE_REAL_PIPER_VOICE_MODEL"])
        config_path = Path(os.environ["ORIGIN_FORGE_REAL_PIPER_VOICE_CONFIG"])
        license_path = Path(os.environ["ORIGIN_FORGE_REAL_PIPER_VOICE_LICENSE"])
        expected_model_hash = os.environ["ORIGIN_FORGE_REAL_PIPER_VOICE_MODEL_SHA256"]
        expected_config_hash = os.environ["ORIGIN_FORGE_REAL_PIPER_VOICE_CONFIG_SHA256"]
        expected_license_hash = os.environ[
            "ORIGIN_FORGE_REAL_PIPER_VOICE_LICENSE_SHA256"
        ]
        license_id = os.environ["ORIGIN_FORGE_REAL_PIPER_VOICE_LICENSE_ID"]

        self.assertEqual(version, "1.6.0")
        self.assertEqual(source_commit, _PIPER_SOURCE_COMMIT)
        self.assertEqual(voice_repo_commit, _VOICE_REPO_COMMIT)
        self.assertEqual(ort_sha512, _ORT_SHA512)
        self.assertEqual(expected_model_hash, "sha256:" + _VOICE_MODEL_SHA256)
        self.assertEqual(license_id, "CC0-1.0")
        self.assertTrue(runtime_root.is_dir())
        self.assertFalse(runtime_root.is_symlink())
        self.assertTrue(executable.is_file())
        self.assertFalse(executable.is_symlink())
        self.assertTrue(espeak_data.is_dir())
        self.assertFalse(espeak_data.is_symlink())
        self.assertFalse(any(path.is_symlink() for path in runtime_root.rglob("*")))
        actual_runtime_hash = piper_runtime_tree_hash(runtime_root)
        self.assertEqual(actual_runtime_hash, expected_runtime_hash)

        self.assertEqual(_sha256(model_path), expected_model_hash)
        self.assertEqual(_sha256(config_path), expected_config_hash)
        self.assertEqual(_sha256(license_path), expected_license_hash)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["audio"]["sample_rate"], 22_050)
        self.assertEqual(config["num_speakers"], 1)
        license_text = license_path.read_text(encoding="utf-8")
        self.assertIn("* License: CC0", license_text)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("real-piper-evidence")
            lineage = OriginForgeLineage(runtime)

            goal = runtime.create_goal("Prove pinned Piper TTS evidence")
            flow = runtime.create_flow(goal)
            runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
            task = runtime.create_task(flow, "Synthesize one frozen voice utterance")
            revision = runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
            runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)

            profile = GovernedAudioProfile.create(
                kind=AudioProfileKind.PIPER_TTS,
                operation=AudioOperation.SYNTHESIZE_SPEECH,
                backend_id="piper",
                backend_version=version,
                runtime_hash=actual_runtime_hash,
                target_sample_rate=22_050,
                target_channels=1,
                model_id="en_US-joe-medium",
                model_hash=expected_model_hash,
                model_config_hash=expected_config_hash,
                license_id=license_id,
                license_hash=expected_license_hash,
            )
            AudioProfileStore(runtime).put(profile)
            self.assertEqual(
                AudioProfileStore(runtime).get(profile.profile_id, profile.profile_hash),
                profile,
            )

            request = AudioOperationRequest.create(
                operation=AudioOperation.SYNTHESIZE_SPEECH,
                backend_id=profile.backend_id,
                backend_version=profile.backend_version,
                profile_id=profile.profile_id,
                profile_hash=profile.profile_hash,
                model_id=profile.model_id,
                model_hash=profile.model_hash,
                text="Origin Forge real Piper evidence.",
                target_sample_rate=profile.target_sample_rate,
                target_channels=profile.target_channels,
                max_duration_ms=10_000,
                timeout_seconds=120,
                output_relative_path="exports/speech.wav",
            )
            adapter = PiperAudioAdapter(
                runtime,
                profile,
                runtime_root=runtime_root,
                executable=executable,
                espeak_data_path=espeak_data,
                model_path=model_path,
                model_config_path=config_path,
                license_path=license_path,
            )
            service = AudioOperationService(runtime, adapter)
            before = runtime.get_task(task)
            result = service.execute(task, request, source_artifact_ids={})
            after = runtime.get_task(task)

            self.assertEqual(
                runtime.get_run(result.run_id)["status"], RunStatus.SUCCEEDED.value
            )
            self.assertEqual(after["status"], TaskStatus.RUNNING.value)
            self.assertEqual(after["revision"], before["revision"])
            self.assertEqual(after["attempt_count"], before["attempt_count"] + 1)
            self.assertIsNone(after["assigned_run_id"])
            self.assertEqual(runtime.list_verifications("TASK", task), [])

            output_artifact = lineage.get_artifact(result.output.artifact_id)
            self.assertEqual(output_artifact["type"], "AUDIO_OUTPUT_WAV")
            self.assertEqual(output_artifact["model_id"], profile.model_id)
            tool_versions = json.loads(output_artifact["tool_versions_json"])
            self.assertIn(
                f"audio-model:{profile.model_id}:{profile.model_hash}", tool_versions
            )
            output_path = lineage.local_artifact_path(result.output.artifact_id)
            output_data = output_path.read_bytes()
            self.assertEqual(canonicalize_pcm16_wav(output_data), output_data)
            output = inspect_pcm16_wav(output_data)
            self.assertEqual(output.sample_rate, 22_050)
            self.assertEqual(output.channels, 1)
            self.assertGreater(output.nonzero_sample_count, 0)
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
            self.assertFalse(result.to_dict()["production_task_verified"])
            self.assertFalse(result.to_dict()["semantic_audio_quality_verified"])
            self.assertFalse(result.to_dict()["canonical_asset_adopted"])
            self.assertFalse((root / "audio" / "speech.wav").exists())


if __name__ == "__main__":
    unittest.main()
