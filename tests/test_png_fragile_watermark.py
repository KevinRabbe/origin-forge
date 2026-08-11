from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.exact_media_fingerprint import fingerprint_raster_png
from origin_forge.media_fingerprint_models import (
    FingerprintComparison,
    FingerprintComparisonOutcome,
    MediaFingerprintModelError,
)
from origin_forge.media_fingerprint_store import MediaFingerprintStore
from origin_forge.media_watermark_models import WatermarkDetectionStatus
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png
from origin_forge.png_fragile_watermark import (
    PngWatermarkError,
    create_png_fragile_metadata_plan,
    detect_png_fragile_metadata,
    embed_png_fragile_metadata,
)
from origin_forge.runtime import OriginForgeRuntime


class PngFragileWatermarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent = encode_rgba8_png(
            PixelPlane(
                2,
                2,
                bytes(
                    (
                        10, 20, 30, 255,
                        40, 50, 60, 255,
                        70, 80, 90, 128,
                        100, 110, 120, 0,
                    )
                ),
            )
        )
        self.payload = b"origin-forge-phase28-mark"
        self.plan = create_png_fragile_metadata_plan(
            parent_ref="ART-parent-png",
            parent=self.parent,
            mark_payload=self.payload,
        )

    def test_derivative_preserves_exact_pixel_fingerprint_and_detector_is_separate(self) -> None:
        derivative = embed_png_fragile_metadata(
            plan=self.plan,
            parent=self.parent,
            mark_payload=self.payload,
        )
        self.assertNotEqual(derivative, self.parent)
        before = fingerprint_raster_png(source_ref="ART-parent", source=self.parent)
        after = fingerprint_raster_png(source_ref="ART-derivative", source=derivative)
        comparison = FingerprintComparison.compare(before, after)
        self.assertIs(comparison.outcome, FingerprintComparisonOutcome.EXACT_MATCH)

        result = detect_png_fragile_metadata(plan=self.plan, derivative=derivative)
        self.assertIs(result.status, WatermarkDetectionStatus.DETECTED)
        result.bind_plan(self.plan)
        payload = result.to_dict()
        self.assertTrue(payload["format_validated"])
        self.assertFalse(payload["authorship_proven"])
        self.assertFalse(payload["cryptographic_provenance_verified"])
        self.assertFalse(payload["parent_lineage_verified"])
        self.assertFalse(payload["canonical_asset_adopted"])
        self.assertFalse(payload["production_task_verified"])

    def test_original_parent_has_no_mark_and_mismatched_plan_does_not_authenticate(self) -> None:
        missing = detect_png_fragile_metadata(plan=self.plan, derivative=self.parent)
        self.assertIs(missing.status, WatermarkDetectionStatus.NOT_DETECTED)
        self.assertIsNone(missing.observed_payload_hash)

        derivative = embed_png_fragile_metadata(
            plan=self.plan,
            parent=self.parent,
            mark_payload=self.payload,
        )
        other_plan = create_png_fragile_metadata_plan(
            parent_ref="ART-parent-png",
            parent=self.parent,
            mark_payload=b"different-nonsecret-mark",
        )
        mismatch = detect_png_fragile_metadata(plan=other_plan, derivative=derivative)
        self.assertIs(mismatch.status, WatermarkDetectionStatus.MISMATCH)
        self.assertNotEqual(mismatch.observed_payload_hash, other_plan.payload_hash)

    def test_parent_and_payload_hash_drift_fail_before_embedding(self) -> None:
        with self.assertRaisesRegex(PngWatermarkError, "parent bytes"):
            embed_png_fragile_metadata(
                plan=self.plan,
                parent=self.parent + b"drift",
                mark_payload=self.payload,
            )
        with self.assertRaisesRegex(PngWatermarkError, "mark payload"):
            embed_png_fragile_metadata(
                plan=self.plan,
                parent=self.parent,
                mark_payload=b"wrong",
            )

    def test_existing_private_chunk_is_not_reembedded(self) -> None:
        derivative = embed_png_fragile_metadata(
            plan=self.plan,
            parent=self.parent,
            mark_payload=self.payload,
        )
        nested_plan = create_png_fragile_metadata_plan(
            parent_ref="ART-already-marked",
            parent=derivative,
            mark_payload=b"second",
        )
        with self.assertRaisesRegex(PngWatermarkError, "already contains"):
            embed_png_fragile_metadata(
                plan=nested_plan,
                parent=derivative,
                mark_payload=b"second",
            )

    def test_detector_contract_drift_fails_closed(self) -> None:
        derivative = embed_png_fragile_metadata(
            plan=self.plan,
            parent=self.parent,
            mark_payload=self.payload,
        )
        drifted = replace(self.plan, detector_version="999")
        with self.assertRaisesRegex(MediaFingerprintModelError, "exact governed"):
            detect_png_fragile_metadata(plan=drifted, derivative=derivative)

    def test_watermark_result_requires_validated_format_and_exact_plan_binding(self) -> None:
        derivative = embed_png_fragile_metadata(
            plan=self.plan,
            parent=self.parent,
            mark_payload=self.payload,
        )
        result = detect_png_fragile_metadata(plan=self.plan, derivative=derivative)
        with self.assertRaisesRegex(MediaFingerprintModelError, "validated derivative format"):
            replace(result, format_validated=False)

        other_plan = create_png_fragile_metadata_plan(
            parent_ref="ART-parent-png",
            parent=self.parent,
            mark_payload=b"other",
        )
        with self.assertRaisesRegex(MediaFingerprintModelError, "exact plan"):
            result.bind_plan(other_plan)

        forged = replace(result, status=WatermarkDetectionStatus.MISMATCH)
        with self.assertRaisesRegex(MediaFingerprintModelError, "incorrectly matches"):
            forged.bind_plan(self.plan)

    def test_plan_and_detection_result_persist_as_immutable_evidence(self) -> None:
        derivative = embed_png_fragile_metadata(
            plan=self.plan,
            parent=self.parent,
            mark_payload=self.payload,
        )
        result = detect_png_fragile_metadata(plan=self.plan, derivative=derivative)
        with tempfile.TemporaryDirectory() as tempdir:
            runtime = OriginForgeRuntime(Path(tempdir))
            runtime.initialize("phase28-watermark-store-test")
            store = MediaFingerprintStore(runtime)
            plan_path = store.publish_watermark_plan(self.plan)
            result_path = store.publish_watermark_result(result, plan=self.plan)
            self.assertTrue(plan_path.is_file())
            self.assertTrue(result_path.is_file())
            loaded = store.load("watermark-results", result.result_id)
            self.assertEqual(loaded["content_hash"], result.content_hash)
            self.assertEqual(loaded["payload"]["status"], "DETECTED")


if __name__ == "__main__":
    unittest.main()
