from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from origin_forge.audio_adoption import AudioAdoptionError, GeneratedAudioAdopter
from origin_forge.audio_wav import encode_pcm16_wav, inspect_pcm16_wav
from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime


class GeneratedAudioAdopterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("audio-adoption-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.workspace = self.runtime.state_dir / "audio-workspaces" / "AUDIO-test"
        (self.workspace / "exports").mkdir(parents=True)
        self.source_path = self.workspace / "exports" / "source.wav"
        self.source_data = encode_pcm16_wav(
            channels=1,
            sample_rate=8_000,
            pcm_bytes=b"".join(struct.pack("<h", value) for value in (0, 50, -50, 0)),
        )
        self.source_path.write_bytes(self.source_data)
        self.source_artifact_id = self.lineage.create_artifact(
            artifact_type="AUDIO_OUTPUT_WAV",
            path_or_uri=str(self.source_path),
            status="PRODUCED",
        )
        self.inspection = inspect_pcm16_wav(self.source_data)
        self._record_pass(self.source_artifact_id)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _evidence(self) -> dict[str, object]:
        return {
            "content_hash": self.inspection.content_hash,
            "pcm_hash": self.inspection.pcm_hash,
            "byte_count": self.inspection.byte_count,
            "frame_count": self.inspection.frame_count,
            "sample_rate": self.inspection.sample_rate,
            "channels": self.inspection.channels,
            "peak_abs_sample": self.inspection.peak_abs_sample,
            "clipped_sample_count": self.inspection.clipped_sample_count,
            "nonzero_sample_count": self.inspection.nonzero_sample_count,
            "production_task_verified": False,
            "semantic_audio_quality_verified": False,
            "canonical_asset_adopted": False,
        }

    def _record_pass(self, artifact_id: str, *, evidence: dict[str, object] | None = None) -> str:
        return self.lineage.record_artifact_verification(
            artifact_id,
            verification_type="audio-output-integrity",
            verifier="OriginForge.AudioOperationService",
            status="PASS",
            evidence=evidence or self._evidence(),
        )

    def test_adoption_is_create_only_and_records_independent_integrity_evidence(self) -> None:
        adopter = GeneratedAudioAdopter(self.runtime)
        result = adopter.adopt_new(self.source_artifact_id, "audio/generated/source.wav")

        destination = self.root / "audio" / "generated" / "source.wav"
        self.assertEqual(destination.read_bytes(), self.source_data)
        adopted = self.lineage.get_artifact(result.adopted_artifact_id)
        self.assertEqual(adopted["type"], "ADOPTED_AUDIO_WAV")
        self.assertEqual(adopted["parent_artifact_id"], self.source_artifact_id)
        verification = self.lineage.list_artifact_verifications(
            result.adopted_artifact_id
        )
        self.assertEqual(len(verification), 1)
        self.assertEqual(
            verification[0]["verification_type"], "audio-adoption-integrity"
        )
        self.assertEqual(verification[0]["status"], "PASS")
        self.assertEqual(result.content_hash, self.inspection.content_hash)
        self.assertEqual(result.pcm_hash, self.inspection.pcm_hash)
        self.assertFalse(result.to_dict()["existing_asset_overwritten"])
        self.assertFalse(result.to_dict()["production_task_verified"])
        self.assertFalse(result.to_dict()["semantic_audio_quality_verified"])

    def test_existing_and_protected_destinations_are_refused(self) -> None:
        adopter = GeneratedAudioAdopter(self.runtime)
        existing = self.root / "audio" / "existing.wav"
        existing.parent.mkdir()
        existing.write_bytes(b"keep")
        with self.assertRaisesRegex(AudioAdoptionError, "create-only"):
            adopter.adopt_new(self.source_artifact_id, "audio/existing.wav")
        self.assertEqual(existing.read_bytes(), b"keep")

        with self.assertRaisesRegex(AudioAdoptionError, "invalid audio adoption destination"):
            adopter.adopt_new(self.source_artifact_id, ".origin-forge/escape.wav")
        with self.assertRaisesRegex(AudioAdoptionError, "destination must be WAV"):
            adopter.adopt_new(self.source_artifact_id, "audio/output.mp3")

    def test_source_byte_tamper_is_rejected_before_publication(self) -> None:
        self.source_path.write_bytes(self.source_data + b"tamper")
        destination = self.root / "audio" / "tampered.wav"
        with self.assertRaisesRegex(AudioAdoptionError, "bytes drifted"):
            GeneratedAudioAdopter(self.runtime).adopt_new(
                self.source_artifact_id, "audio/tampered.wav"
            )
        self.assertFalse(destination.exists())

    def test_verification_evidence_drift_is_rejected(self) -> None:
        workspace = self.runtime.state_dir / "audio-workspaces" / "AUDIO-evidence"
        (workspace / "exports").mkdir(parents=True)
        path = workspace / "exports" / "other.wav"
        path.write_bytes(self.source_data)
        artifact_id = self.lineage.create_artifact(
            artifact_type="AUDIO_OUTPUT_WAV",
            path_or_uri=str(path),
            status="PRODUCED",
        )
        evidence = self._evidence()
        evidence["pcm_hash"] = "sha256:" + "0" * 64
        self._record_pass(artifact_id, evidence=evidence)
        with self.assertRaisesRegex(AudioAdoptionError, "verification evidence drifted: pcm_hash"):
            GeneratedAudioAdopter(self.runtime).adopt_new(
                artifact_id, "audio/evidence-drift.wav"
            )

    def test_exactly_one_matching_pass_is_required(self) -> None:
        workspace = self.runtime.state_dir / "audio-workspaces" / "AUDIO-pass-count"
        (workspace / "exports").mkdir(parents=True)
        path = workspace / "exports" / "other.wav"
        path.write_bytes(self.source_data)
        artifact_id = self.lineage.create_artifact(
            artifact_type="AUDIO_OUTPUT_WAV",
            path_or_uri=str(path),
            status="PRODUCED",
        )
        with self.assertRaisesRegex(AudioAdoptionError, "exactly one PASS"):
            GeneratedAudioAdopter(self.runtime).adopt_new(
                artifact_id, "audio/no-pass.wav"
            )
        self._record_pass(artifact_id)
        self._record_pass(artifact_id)
        with self.assertRaisesRegex(AudioAdoptionError, "exactly one PASS"):
            GeneratedAudioAdopter(self.runtime).adopt_new(
                artifact_id, "audio/two-pass.wav"
            )

    def test_wrong_artifact_type_is_not_adoptable(self) -> None:
        workspace = self.runtime.state_dir / "audio-workspaces" / "AUDIO-wrong-type"
        (workspace / "exports").mkdir(parents=True)
        path = workspace / "exports" / "wrong.wav"
        path.write_bytes(self.source_data)
        artifact_id = self.lineage.create_artifact(
            artifact_type="TEST_AUDIO_WAV",
            path_or_uri=str(path),
            status="PRODUCED",
        )
        self._record_pass(artifact_id)
        with self.assertRaisesRegex(AudioAdoptionError, "not an audio operation output"):
            GeneratedAudioAdopter(self.runtime).adopt_new(
                artifact_id, "audio/wrong.wav"
            )

    def test_adopter_exposes_no_task_merge_release_or_install_surface(self) -> None:
        adopter = GeneratedAudioAdopter(self.runtime)
        for forbidden in (
            "transition_task",
            "verify_task",
            "complete_task",
            "merge",
            "release",
            "sign",
            "install_plugin",
            "download_model",
        ):
            self.assertFalse(hasattr(adopter, forbidden))


if __name__ == "__main__":
    unittest.main()
