from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.image_adoption import GeneratedImageAdopter, ImageAdoptionError
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png, inspect_rgba8_png
from origin_forge.runtime import OriginForgeRuntime


class ImageAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("image-adoption-test")
        self.lineage = OriginForgeLineage(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _verified_source(self) -> tuple[str, Path, bytes]:
        workspace_id = new_id(IdKind.IMAGE_WORKSPACE)
        path = (
            self.runtime.state_dir
            / "image-workspaces"
            / workspace_id
            / "exports"
            / "source.png"
        )
        path.parent.mkdir(parents=True)
        data = encode_rgba8_png(
            PixelPlane(2, 2, bytes([20, 40, 60, 255] * 4))
        )
        path.write_bytes(data)
        inspection = inspect_rgba8_png(data)
        artifact_id = self.lineage.create_artifact(
            artifact_type="GENERATED_RASTER_PNG",
            path_or_uri=str(path),
            model_id="image-model",
            status="PRODUCED",
        )
        self.lineage.record_artifact_verification(
            artifact_id,
            verification_type="image-output-integrity",
            verifier="OriginForge.ImageGenerationService",
            status="PASS",
            evidence={
                "content_hash": "sha256:" + hashlib.sha256(data).hexdigest(),
                "pixel_hash": inspection.pixel_hash,
                "semantic_visual_quality_verified": False,
                "production_task_verified": False,
            },
        )
        return artifact_id, path, data

    def test_adopt_new_copies_verified_raster_and_preserves_parent_lineage(self) -> None:
        artifact_id, _, data = self._verified_source()
        result = GeneratedImageAdopter(self.runtime).adopt_new(
            artifact_id,
            "assets/concepts/enemy.png",
        )
        destination = self.root / result.destination_path
        self.assertEqual(destination.read_bytes(), data)
        adopted = self.lineage.get_artifact(result.adopted_artifact_id)
        self.assertEqual(adopted["parent_artifact_id"], artifact_id)
        self.assertEqual(adopted["type"], "ADOPTED_GENERATED_RASTER_PNG")
        verifications = self.lineage.list_artifact_verifications(
            result.adopted_artifact_id
        )
        self.assertEqual(len(verifications), 1)
        self.assertEqual(
            verifications[0]["verification_type"], "image-adoption-integrity"
        )
        self.assertEqual(verifications[0]["status"], "PASS")
        self.assertFalse(result.to_dict()["existing_asset_overwritten"])
        self.assertFalse(result.to_dict()["semantic_visual_quality_verified"])

    def test_adoption_is_create_only_and_rejects_protected_or_non_png_paths(self) -> None:
        artifact_id, _, _ = self._verified_source()
        adopter = GeneratedImageAdopter(self.runtime)
        adopter.adopt_new(artifact_id, "assets/concept.png")
        with self.assertRaisesRegex(ImageAdoptionError, "create-only"):
            adopter.adopt_new(artifact_id, "assets/concept.png")
        with self.assertRaises(Exception):
            adopter.adopt_new(artifact_id, ".origin-forge/forbidden.png")
        with self.assertRaisesRegex(ImageAdoptionError, "must be PNG"):
            adopter.adopt_new(artifact_id, "assets/concept.jpg")

    def test_source_drift_or_wrong_verifier_prevents_adoption(self) -> None:
        artifact_id, path, _ = self._verified_source()
        path.write_bytes(b"tampered")
        with self.assertRaises(Exception):
            GeneratedImageAdopter(self.runtime).adopt_new(
                artifact_id, "assets/tampered.png"
            )
        self.assertFalse((self.root / "assets/tampered.png").exists())

        workspace_id = new_id(IdKind.IMAGE_WORKSPACE)
        other = (
            self.runtime.state_dir
            / "image-workspaces"
            / workspace_id
            / "exports"
            / "other.png"
        )
        other.parent.mkdir(parents=True)
        other.write_bytes(
            encode_rgba8_png(PixelPlane(1, 1, bytes([1, 2, 3, 255])))
        )
        wrong = self.lineage.create_artifact(
            artifact_type="GENERATED_RASTER_PNG",
            path_or_uri=str(other),
            status="PRODUCED",
        )
        self.lineage.record_artifact_verification(
            wrong,
            verification_type="image-output-integrity",
            verifier="UntrustedVerifier",
            status="PASS",
        )
        with self.assertRaisesRegex(ImageAdoptionError, "lacks PASS"):
            GeneratedImageAdopter(self.runtime).adopt_new(
                wrong, "assets/wrong.png"
            )

    def test_adopter_has_no_task_merge_release_sign_or_generation_surface(self) -> None:
        public = {
            name
            for name in dir(GeneratedImageAdopter(self.runtime))
            if not name.startswith("_")
        }
        for forbidden in (
            "transition_task",
            "verify_task",
            "complete_task",
            "merge",
            "release",
            "sign",
            "generate",
            "download_model",
            "install_plugin",
        ):
            self.assertNotIn(forbidden, public)


if __name__ == "__main__":
    unittest.main()
