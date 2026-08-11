from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.media_fingerprint_models import (
    FingerprintComparison,
    FingerprintMediaClass,
    WatermarkMutationClass,
    WatermarkPlan,
    WatermarkRobustnessClass,
)
from origin_forge.media_fingerprint_store import (
    MediaFingerprintStore,
    MediaFingerprintStoreError,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observation_models import canonical_bytes
from origin_forge.source_text_fingerprint import fingerprint_source_text


HASH_A = "sha256:" + "a" * 64


class MediaFingerprintStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("media-fingerprint-store-test")
        self.store = MediaFingerprintStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _objects(self):
        left = fingerprint_source_text(source_ref="ART-left", source=b"alpha\r\nbeta\r\n")
        right = fingerprint_source_text(source_ref="ART-right", source=b"alpha\nbeta\n")
        comparison = FingerprintComparison.compare(left, right)
        plan = WatermarkPlan.create(
            media_class=FingerprintMediaClass.RASTER_IMAGE,
            parent_ref="ART-parent",
            parent_hash=HASH_A,
            mark_payload=b"mark",
            embedder_id="png-fragile-content",
            embedder_version="1",
            embedder_fingerprint=HASH_A,
            detector_id="png-fragile-content-detector",
            detector_version="1",
            detector_fingerprint=HASH_A,
            robustness_class=WatermarkRobustnessClass.FRAGILE_CONTENT,
            mutation_class=WatermarkMutationClass.CONTENT_MUTATION,
        )
        return left, right, comparison, plan

    def test_publish_and_load_evidence(self) -> None:
        left, right, comparison, plan = self._objects()
        published = (
            ("fingerprints", left.fingerprint_id, left.content_hash, self.store.publish_fingerprint(left)),
            ("fingerprints", right.fingerprint_id, right.content_hash, self.store.publish_fingerprint(right)),
            ("comparisons", comparison.comparison_id, comparison.content_hash, self.store.publish_comparison(comparison)),
            ("watermark-plans", plan.plan_id, plan.content_hash, self.store.publish_watermark_plan(plan)),
        )
        for category, object_id, expected_hash, path in published:
            self.assertTrue(path.is_file())
            envelope = self.store.load(category, object_id)
            self.assertEqual(envelope["content_hash"], expected_hash)
            self.assertEqual(envelope["object_id"], object_id)

    def test_no_overwrite_and_tamper_detection(self) -> None:
        left, *_ = self._objects()
        path = self.store.publish_fingerprint(left)
        with self.assertRaisesRegex(MediaFingerprintStoreError, "already exists"):
            self.store.publish_fingerprint(left)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["source_ref"] = "ART-tampered"
        path.write_bytes(canonical_bytes(envelope))
        with self.assertRaisesRegex(MediaFingerprintStoreError, "content hash drifted"):
            self.store.load("fingerprints", left.fingerprint_id)

    def test_noncanonical_rewrite_is_rejected(self) -> None:
        left, *_ = self._objects()
        path = self.store.publish_fingerprint(left)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(MediaFingerprintStoreError, "not canonical"):
            self.store.load("fingerprints", left.fingerprint_id)

    def test_symlinked_category_is_rejected(self) -> None:
        left, *_ = self._objects()
        root = self.runtime.state_dir / "media-fingerprints"
        root.mkdir()
        target = self.runtime.state_dir / "outside-fingerprints"
        target.mkdir()
        (root / "fingerprints").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(MediaFingerprintStoreError, "may not be a symlink"):
            self.store.publish_fingerprint(left)

    def test_listing_revalidates_objects(self) -> None:
        left, _, comparison, _ = self._objects()
        self.store.publish_fingerprint(left)
        self.store.publish_comparison(comparison)
        self.assertEqual(
            self.store.list_objects("fingerprints")[0]["content_hash"],
            left.content_hash,
        )
        self.assertEqual(
            self.store.list_objects("comparisons")[0]["object_id"],
            comparison.comparison_id,
        )


if __name__ == "__main__":
    unittest.main()
