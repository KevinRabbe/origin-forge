from __future__ import annotations

import hashlib
import unittest

from origin_forge.image_png import inspect_truecolor8_png
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png
from origin_forge.runtime_observation_models import VisualBaselineRef
from origin_forge.runtime_visual import RuntimeVisualError, compare_png_to_baseline


class RuntimeVisualTests(unittest.TestCase):
    @staticmethod
    def _png(pixels: bytes) -> bytes:
        return encode_rgba8_png(PixelPlane(2, 1, pixels))

    def _baseline(self, data: bytes, **thresholds: int) -> VisualBaselineRef:
        inspection = inspect_truecolor8_png(data)
        return VisualBaselineRef(
            baseline_id="baseline",
            content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
            pixel_hash=inspection.pixel_hash,
            width=inspection.width,
            height=inspection.height,
            max_changed_pixels=thresholds.get("max_changed_pixels", 0),
            max_channel_delta=thresholds.get("max_channel_delta", 0),
            max_total_channel_delta=thresholds.get("max_total_channel_delta", 0),
        )

    def test_exact_match_passes_zero_tolerance(self) -> None:
        baseline_png = self._png(bytes((10, 20, 30, 255, 40, 50, 60, 255)))
        diff = compare_png_to_baseline(
            baseline_png, baseline_png, self._baseline(baseline_png)
        )
        self.assertTrue(diff.passed)
        self.assertEqual(diff.changed_pixels, 0)
        self.assertEqual(diff.max_channel_delta, 0)
        self.assertEqual(diff.total_channel_delta, 0)

    def test_thresholds_are_deterministic_and_regression_dominant(self) -> None:
        baseline_png = self._png(bytes((10, 20, 30, 255, 40, 50, 60, 255)))
        observed_png = self._png(bytes((12, 20, 30, 255, 40, 50, 60, 255)))
        diff = compare_png_to_baseline(
            baseline_png,
            observed_png,
            self._baseline(
                baseline_png,
                max_changed_pixels=1,
                max_channel_delta=2,
                max_total_channel_delta=2,
            ),
        )
        self.assertTrue(diff.passed)
        self.assertEqual(diff.changed_pixels, 1)
        self.assertEqual(diff.max_channel_delta, 2)
        self.assertEqual(diff.total_channel_delta, 2)

        strict = compare_png_to_baseline(
            baseline_png,
            observed_png,
            self._baseline(
                baseline_png,
                max_changed_pixels=1,
                max_channel_delta=1,
                max_total_channel_delta=2,
            ),
        )
        self.assertFalse(strict.passed)

    def test_dimension_drift_is_not_reinterpreted_as_pixel_difference(self) -> None:
        baseline_png = self._png(bytes((10, 20, 30, 255, 40, 50, 60, 255)))
        observed_png = encode_rgba8_png(PixelPlane(1, 1, bytes((10, 20, 30, 255))))
        with self.assertRaisesRegex(RuntimeVisualError, "dimensions"):
            compare_png_to_baseline(
                baseline_png, observed_png, self._baseline(baseline_png)
            )


if __name__ == "__main__":
    unittest.main()