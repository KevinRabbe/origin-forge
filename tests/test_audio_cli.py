from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.audio_cli import build_parser, main
from origin_forge.audio_models import AudioOperation
from origin_forge.audio_profiles import (
    AudioProfileKind,
    AudioProfileStore,
    GovernedAudioProfile,
)
from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime


RUNTIME_HASH = "sha256:" + "7" * 64


class AudioCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("audio-cli-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str) -> tuple[int, object]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def _profile(self) -> GovernedAudioProfile:
        return GovernedAudioProfile.create(
            kind=AudioProfileKind.PROCEDURAL_SFX,
            operation=AudioOperation.SYNTHESIZE_SFX,
            backend_id="origin-forge-procedural",
            backend_version="v1",
            runtime_hash=RUNTIME_HASH,
            target_sample_rate=48_000,
            target_channels=1,
        )

    def test_surface_is_strictly_read_only(self) -> None:
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if action.dest == "command"
        )
        commands = set(subparsers.choices)
        self.assertEqual(
            commands,
            {"status", "profile-list", "profile-show", "artifact-show", "operation-runs"},
        )
        for forbidden in (
            "generate",
            "speak",
            "process",
            "adopt",
            "install",
            "download",
            "download-model",
            "promote",
            "verify-task",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_and_empty_catalogs_are_deterministic_and_non_mutating(self) -> None:
        before = self.runtime.status()
        code, value = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "OK")
        self.assertEqual(value["governed_profile_count"], 0)
        self.assertEqual(value["audio_operation_run_count"], 0)
        self.assertEqual(value["artifact_counts"], {})
        self.assertFalse(value["audio_execution_enabled"])
        self.assertFalse(value["profile_install_enabled"])
        self.assertFalse(value["model_download_enabled"])
        self.assertFalse(value["canonical_asset_adoption_enabled"])
        self.assertFalse(value["task_mutation_enabled"])
        self.assertEqual(self.runtime.status(), before)

    def test_profile_list_and_show_read_exact_stored_profile(self) -> None:
        profile = self._profile()
        AudioProfileStore(self.runtime).put(profile)
        code, listing = self._call("profile-list")
        self.assertEqual(code, 0)
        self.assertEqual(
            listing["profiles"],
            [
                {
                    "profile_id": profile.profile_id,
                    "profile_hash": profile.profile_hash,
                    "byte_count": len(
                        json.dumps(
                            profile.to_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")
                    ),
                }
            ],
        )
        code, shown = self._call("profile-show", profile.profile_id, profile.profile_hash)
        self.assertEqual(code, 0)
        self.assertEqual(shown, profile.to_dict())

    def test_artifact_show_is_limited_to_audio_artifacts(self) -> None:
        lineage = OriginForgeLineage(self.runtime)
        workspace = self.runtime.state_dir / "audio-workspaces" / "AUDIO-cli"
        (workspace / "exports").mkdir(parents=True)
        audio_path = workspace / "exports" / "output.wav"
        audio_path.write_bytes(b"not-decoded-by-read-only-cli")
        audio_id = lineage.create_artifact(
            artifact_type="AUDIO_OUTPUT_WAV",
            path_or_uri=str(audio_path),
            status="PRODUCED",
        )
        code, value = self._call("artifact-show", audio_id)
        self.assertEqual(code, 0)
        self.assertEqual(value["artifact"]["id"], audio_id)
        self.assertEqual(value["verifications"], [])

        other_path = self.root / "other.bin"
        other_path.write_bytes(b"other")
        other_id = lineage.create_artifact(
            artifact_type="OTHER",
            path_or_uri=str(other_path),
            status="PRODUCED",
        )
        code, value = self._call("artifact-show", other_id)
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")
        self.assertIn("Phase-22 audio Artifact", value["detail"])

    def test_operation_runs_and_invalid_ids_are_structured(self) -> None:
        code, value = self._call("operation-runs")
        self.assertEqual(code, 0)
        self.assertEqual(value, {"runs": []})
        code, value = self._call("artifact-show", "not-an-artifact")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
