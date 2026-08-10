from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.audio_models import AudioOperation
from origin_forge.audio_profiles import (
    AudioProfileError,
    AudioProfileKind,
    AudioProfileStore,
    GovernedAudioProfile,
)
from origin_forge.runtime import OriginForgeRuntime


RUNTIME_HASH = "sha256:" + "1" * 64
MODEL_HASH = "sha256:" + "2" * 64
CONFIG_HASH = "sha256:" + "3" * 64
LICENSE_HASH = "sha256:" + "4" * 64


class AudioProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("audio-profile-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_ffmpeg_profile_is_content_addressed_and_model_free(self) -> None:
        profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.FFMPEG_PCM16,
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=48_000,
            target_channels=1,
        )
        self.assertTrue(profile.profile_hash.startswith("sha256:"))
        self.assertIsNone(profile.model_id)
        self.assertIsNone(profile.license_hash)
        with self.assertRaisesRegex(AudioProfileError, "requires operation"):
            GovernedAudioProfile.create(
                kind=AudioProfileKind.FFMPEG_PCM16,
                operation=AudioOperation.GENERATE_MUSIC,
                backend_id="ffmpeg",
                backend_version="8.1.2",
                runtime_hash=RUNTIME_HASH,
                target_sample_rate=48_000,
                target_channels=1,
            )

    def test_piper_profile_requires_model_config_and_license_evidence(self) -> None:
        profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.PIPER_TTS,
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.4.2",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=22_050,
            target_channels=1,
            model_id="en-test",
            model_hash=MODEL_HASH,
            model_config_hash=CONFIG_HASH,
            license_id="CC0-1.0",
            license_hash=LICENSE_HASH,
        )
        self.assertEqual(profile.license_id, "CC0-1.0")
        self.assertEqual(profile.license_hash, LICENSE_HASH)
        with self.assertRaisesRegex(AudioProfileError, "license_id and license_hash"):
            GovernedAudioProfile.create(
                kind=AudioProfileKind.PIPER_TTS,
                operation=AudioOperation.SYNTHESIZE_SPEECH,
                backend_id="piper",
                backend_version="1.4.2",
                runtime_hash=RUNTIME_HASH,
                target_sample_rate=22_050,
                target_channels=1,
                model_id="en-test",
                model_hash=MODEL_HASH,
                model_config_hash=CONFIG_HASH,
                license_id="CC0-1.0",
            )

    def test_profile_hash_changes_when_license_evidence_changes(self) -> None:
        first = GovernedAudioProfile.create(
            kind=AudioProfileKind.PIPER_TTS,
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.4.2",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=22_050,
            target_channels=1,
            model_id="en-test",
            model_hash=MODEL_HASH,
            model_config_hash=CONFIG_HASH,
            license_id="CC0-1.0",
            license_hash=LICENSE_HASH,
        )
        second = GovernedAudioProfile(
            profile_id=first.profile_id,
            kind=first.kind,
            operation=first.operation,
            backend_id=first.backend_id,
            backend_version=first.backend_version,
            runtime_hash=first.runtime_hash,
            target_sample_rate=first.target_sample_rate,
            target_channels=first.target_channels,
            model_id=first.model_id,
            model_hash=first.model_hash,
            model_config_hash=first.model_config_hash,
            license_id=first.license_id,
            license_hash="sha256:" + "5" * 64,
        )
        self.assertNotEqual(first.profile_hash, second.profile_hash)

    def test_store_is_immutable_tamper_detected_and_listed(self) -> None:
        profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.PROCEDURAL_SFX,
            operation=AudioOperation.SYNTHESIZE_SFX,
            backend_id="origin-forge-procedural",
            backend_version="1",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=48_000,
            target_channels=1,
        )
        store = AudioProfileStore(self.runtime)
        first = store.put(profile)
        second = store.put(profile)
        self.assertEqual(first.path, second.path)
        self.assertEqual(store.get(profile.profile_id, profile.profile_hash), profile)
        self.assertEqual(len(store.list()), 1)

        value = json.loads(first.path.read_text(encoding="utf-8"))
        value["target_channels"] = 2
        first.path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(AudioProfileError):
            store.get(profile.profile_id, profile.profile_hash)

    def test_store_rejects_symlink_and_undeclared_entries(self) -> None:
        store = AudioProfileStore(self.runtime)
        root = self.runtime.state_dir / "audio-profiles"
        root.mkdir(parents=True)
        (root / "junk.txt").write_text("junk", encoding="utf-8")
        with self.assertRaisesRegex(AudioProfileError, "undeclared"):
            store.list()

        (root / "junk.txt").unlink()
        target = self.root / "outside"
        target.mkdir()
        root.rmdir()
        try:
            root.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(AudioProfileError, "root may not be a symlink"):
            store.list()

    def test_store_enforces_catalog_limit(self) -> None:
        store = AudioProfileStore(self.runtime, max_profiles=1)
        first = GovernedAudioProfile.create(
            kind=AudioProfileKind.PROCEDURAL_SFX,
            operation=AudioOperation.SYNTHESIZE_SFX,
            backend_id="origin-forge-procedural",
            backend_version="1",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=48_000,
            target_channels=1,
        )
        second = GovernedAudioProfile.create(
            kind=AudioProfileKind.PROCEDURAL_MUSIC,
            operation=AudioOperation.GENERATE_MUSIC,
            backend_id="origin-forge-procedural",
            backend_version="1",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=48_000,
            target_channels=2,
        )
        store.put(first)
        with self.assertRaisesRegex(AudioProfileError, "catalog is full"):
            store.put(second)


if __name__ == "__main__":
    unittest.main()
