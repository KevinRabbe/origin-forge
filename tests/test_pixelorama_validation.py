from __future__ import annotations

import unittest

from origin_forge.pixelorama_models import (
    FrameSpec,
    PixelPlane,
    RasterLayerSpec,
    SpriteProjectSpec,
)
from origin_forge.pixelorama_png import encode_rgba8_png
from origin_forge.pixelorama_validation import (
    RasterFindingCode,
    validate_frame_png,
    validate_spritesheet_png,
)


class PixeloramaValidationTests(unittest.TestCase):
    def _spec(self, *, frames: int = 1, transparency_required: bool = True):
        return SpriteProjectSpec(
            2,
            2,
            (RasterLayerSpec("base", "Base"),),
            tuple(FrameSpec(f"frame-{index}") for index in range(frames)),
            transparency_required=transparency_required,
        )

    def test_frame_validator_checks_dimensions_transparency_and_empty_output(self) -> None:
        spec = self._spec()
        pixels = bytes(
            [
                255, 0, 0, 255,
                0, 0, 0, 0,
                0, 255, 0, 255,
                0, 0, 0, 0,
            ]
        )
        valid = validate_frame_png(encode_rgba8_png(PixelPlane(2, 2, pixels)), spec)
        self.assertTrue(valid.passed)
        self.assertEqual(valid.findings, ())
        self.assertFalse(valid.to_dict()["production_verification_changed"])

        wrong = validate_frame_png(
            encode_rgba8_png(PixelPlane(1, 1, bytes([1, 2, 3, 4]))), spec
        )
        self.assertFalse(wrong.passed)
        self.assertIn(
            RasterFindingCode.DIMENSION_MISMATCH,
            {finding.code for finding in wrong.findings},
        )

        empty = validate_frame_png(
            encode_rgba8_png(PixelPlane(2, 2, bytes([0, 0, 0, 0] * 4))), spec
        )
        self.assertFalse(empty.passed)
        self.assertIn(
            RasterFindingCode.FULLY_TRANSPARENT,
            {finding.code for finding in empty.findings},
        )

        opaque = validate_frame_png(
            encode_rgba8_png(PixelPlane(2, 2, bytes([1, 2, 3, 255] * 4))), spec
        )
        self.assertFalse(opaque.passed)
        self.assertIn(
            RasterFindingCode.TRANSPARENCY_REQUIRED,
            {finding.code for finding in opaque.findings},
        )

        allowed_opaque = validate_frame_png(
            encode_rgba8_png(PixelPlane(2, 2, bytes([1, 2, 3, 255] * 4))),
            self._spec(transparency_required=False),
        )
        self.assertTrue(allowed_opaque.passed)

    def test_spritesheet_geometry_is_derived_from_frame_count_and_columns(self) -> None:
        spec = self._spec(frames=3)
        sheet = PixelPlane(4, 4, bytes([1, 2, 3, 255] * 15 + [0, 0, 0, 0]))
        valid = validate_spritesheet_png(encode_rgba8_png(sheet), spec, columns=2)
        self.assertTrue(valid.passed)

        wrong = validate_spritesheet_png(
            encode_rgba8_png(PixelPlane(4, 2, bytes([1, 2, 3, 255] * 7 + [0, 0, 0, 0]))),
            spec,
            columns=2,
        )
        self.assertFalse(wrong.passed)
        self.assertIn(
            RasterFindingCode.SPRITESHEET_GEOMETRY_MISMATCH,
            {finding.code for finding in wrong.findings},
        )

    def test_invalid_png_is_a_deterministic_finding(self) -> None:
        result = validate_frame_png(b"not-png", self._spec())
        self.assertFalse(result.passed)
        self.assertEqual(result.findings[0].code, RasterFindingCode.INVALID_PNG)
        self.assertIsNone(result.inspection)


if __name__ == "__main__":
    unittest.main()
