from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_adoption import (
    GovernedPixeloramaOutputAdopter,
    PixeloramaAdoptionError,
)
from origin_forge.runtime import OriginForgeRuntime


class PixeloramaAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-adoption-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.workspace_id = new_id(IdKind.MEDIA_WORKSPACE)
        self.workspace = (
            self.runtime.state_dir / "media-workspaces" / self.workspace_id
        )
        self.exports = self.workspace / "exports"
        self.exports.mkdir(parents=True)
        self.source = self.exports / "sprite.png"
        self.source.write_bytes(b"bounded-media-output")
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.source_artifact = self.lineage.create_artifact(
            artifact_type="RASTER_EXPORT_PNG",
            path_or_uri=str(self.source),
            tool_versions=("pixelorama:test", "origin-forge-pixelorama-bridge:test"),
            status="PRODUCED",
        )
        self.runtime.record_verification(
            "ARTIFACT",
            self.source_artifact,
            verification_type="pixelorama-output-integrity",
            verifier="OriginForge.PixeloramaMediaService",
            status="PASS",
            evidence={"content_hash": self.source_hash},
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_adoption_streams_verified_media_workspace_output_to_new_project_file(self) -> None:
        adopter = GovernedPixeloramaOutputAdopter(self.runtime)
        result = adopter.adopt_new(
            self.source_artifact,
            "assets/sprites/sprite.png",
        )
        destination = self.root / result.destination_path
        self.assertEqual(destination.read_bytes(), self.source.read_bytes())
        self.assertEqual(result.content_hash, self.source_hash)
        self.assertEqual(result.byte_count, len(self.source.read_bytes()))
        self.assertFalse(result.to_dict()["existing_asset_overwritten"])
        self.assertFalse(result.to_dict()["production_task_verified"])
        with self.runtime.store.session() as conn:
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (result.adopted_artifact_id,),
            ).fetchone()
        self.assertEqual(artifact["parent_artifact_id"], self.source_artifact)
        self.assertEqual(
            json.loads(artifact["tool_versions_json"]),
            ["pixelorama:test", "origin-forge-pixelorama-bridge:test"],
        )

    def test_source_must_be_actual_media_workspace_export_or_project_file(self) -> None:
        outside = self.runtime.state_dir / "other" / "sprite.png"
        outside.parent.mkdir()
        outside.write_bytes(b"outside")
        artifact = self.lineage.create_artifact(
            artifact_type="RASTER_EXPORT_PNG",
            path_or_uri=str(outside),
            status="PRODUCED",
        )
        self.runtime.record_verification(
            "ARTIFACT",
            artifact,
            verification_type="pixelorama-output-integrity",
            verifier="OriginForge.PixeloramaMediaService",
            status="PASS",
        )
        with self.assertRaisesRegex(PixeloramaAdoptionError, "media workspace"):
            GovernedPixeloramaOutputAdopter(self.runtime).adopt_new(
                artifact,
                "assets/outside.png",
            )

        bad_workspace = (
            self.runtime.state_dir
            / "media-workspaces"
            / "not-a-media-id"
            / "exports"
            / "bad.png"
        )
        bad_workspace.parent.mkdir(parents=True)
        bad_workspace.write_bytes(b"bad")
        artifact = self.lineage.create_artifact(
            artifact_type="RASTER_EXPORT_PNG",
            path_or_uri=str(bad_workspace),
            status="PRODUCED",
        )
        self.runtime.record_verification(
            "ARTIFACT",
            artifact,
            verification_type="pixelorama-output-integrity",
            verifier="OriginForge.PixeloramaMediaService",
            status="PASS",
        )
        with self.assertRaisesRegex(PixeloramaAdoptionError, "workspace ID"):
            GovernedPixeloramaOutputAdopter(self.runtime).adopt_new(
                artifact,
                "assets/bad.png",
            )

    def test_missing_pass_evidence_and_post_verification_drift_fail_closed(self) -> None:
        unverified = self.exports / "unverified.png"
        unverified.write_bytes(b"unverified")
        artifact = self.lineage.create_artifact(
            artifact_type="RASTER_EXPORT_PNG",
            path_or_uri=str(unverified),
            status="PRODUCED",
        )
        with self.assertRaisesRegex(PixeloramaAdoptionError, "lacks PASS"):
            GovernedPixeloramaOutputAdopter(self.runtime).adopt_new(
                artifact,
                "assets/unverified.png",
            )

        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(PixeloramaAdoptionError, "drifted"):
            GovernedPixeloramaOutputAdopter(self.runtime).adopt_new(
                self.source_artifact,
                "assets/drift.png",
            )

    def test_source_byte_limit_is_hard_before_destination_publication(self) -> None:
        adopter = GovernedPixeloramaOutputAdopter(
            self.runtime,
            max_source_bytes=4,
        )
        destination = self.root / "assets" / "too-large.png"
        with self.assertRaisesRegex(PixeloramaAdoptionError, "byte limit"):
            adopter.adopt_new(
                self.source_artifact,
                "assets/too-large.png",
            )
        self.assertFalse(destination.exists())

    def test_protected_existing_and_symlink_destinations_are_rejected(self) -> None:
        adopter = GovernedPixeloramaOutputAdopter(self.runtime)
        for protected in (
            ".origin-forge/asset.png",
            ".git/asset.png",
            ".GIT/asset.png",
        ):
            with self.subTest(protected=protected):
                with self.assertRaisesRegex(PixeloramaAdoptionError, "protected"):
                    adopter.adopt_new(self.source_artifact, protected)

        existing = self.root / "assets" / "existing.png"
        existing.parent.mkdir()
        existing.write_bytes(b"keep")
        with self.assertRaisesRegex(PixeloramaAdoptionError, "create-only"):
            adopter.adopt_new(self.source_artifact, "assets/existing.png")
        self.assertEqual(existing.read_bytes(), b"keep")

        target = self.root / "outside-assets"
        target.mkdir()
        link = self.root / "linked-assets"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            return
        with self.assertRaisesRegex(PixeloramaAdoptionError, "symlink"):
            adopter.adopt_new(self.source_artifact, "linked-assets/sprite.png")

    def test_tool_version_corruption_fails_before_adopted_artifact_record(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE artifacts SET tool_versions_json = ? WHERE id = ?",
                ('{"not":"an array"}', self.source_artifact),
            )
        before = self.runtime.list_artifacts()
        with self.assertRaisesRegex(PixeloramaAdoptionError, "tool_versions_json"):
            GovernedPixeloramaOutputAdopter(self.runtime).adopt_new(
                self.source_artifact,
                "assets/tool-corrupt.png",
            )
        self.assertEqual(self.runtime.list_artifacts(), before)

    def test_adopter_has_no_model_editor_task_merge_release_or_signing_surface(self) -> None:
        adopter = GovernedPixeloramaOutputAdopter(self.runtime)
        for forbidden in (
            "model",
            "generate",
            "execute",
            "run_script",
            "install_plugin",
            "verify_task",
            "transition_task",
            "merge",
            "release",
            "sign",
            "private_key",
        ):
            self.assertFalse(hasattr(adopter, forbidden))


if __name__ == "__main__":
    unittest.main()
