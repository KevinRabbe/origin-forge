from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.pixelorama_models import (
    AnimationLoopMode,
    AnimationSpec,
    BridgeBudget,
    BridgeInputRef,
    BridgeOperation,
    BridgeOutput,
    BridgeOutputType,
    BridgeResultStatus,
    ExportSpec,
    FrameSpec,
    PixelPlane,
    PixeloramaBridgeRequest,
    PixeloramaBridgeResult,
    PixeloramaModelError,
    RasterLayerSpec,
    Rgba8,
    SpriteProjectSpec,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


class PixeloramaModelTests(unittest.TestCase):
    def _spec(self) -> SpriteProjectSpec:
        return SpriteProjectSpec(
            width=16,
            height=16,
            layers=(RasterLayerSpec("base", "Base"), RasterLayerSpec("detail", "Detail")),
            frames=(FrameSpec("idle-0", 100), FrameSpec("idle-1", 120)),
            animations=(AnimationSpec("idle", 0, 1, AnimationLoopMode.LOOP),),
            palette=(Rgba8(0, 0, 0, 0), Rgba8(255, 255, 255, 255)),
            output_basename="stone-golem",
        )

    def test_pixel_plane_requires_exact_rgba_bytes_and_hashes_pixels(self) -> None:
        pixels = bytes([255, 0, 0, 255] * 4)
        plane = PixelPlane(2, 2, pixels)
        self.assertEqual(plane.to_dict()["byte_count"], 16)
        self.assertTrue(plane.rgba_hash.startswith("sha256:"))
        with self.assertRaisesRegex(PixeloramaModelError, "byte count mismatch"):
            PixelPlane(2, 2, b"short")

    def test_sprite_spec_is_canonical_bounded_and_animation_ranges_are_checked(self) -> None:
        first = self._spec()
        second = SpriteProjectSpec(
            width=16,
            height=16,
            layers=first.layers,
            frames=first.frames,
            animations=first.animations,
            palette=first.palette,
            output_basename="stone-golem",
        )
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.to_dict(), second.to_dict())
        with self.assertRaisesRegex(PixeloramaModelError, "duplicate layer"):
            SpriteProjectSpec(
                16,
                16,
                (RasterLayerSpec("same", "A"), RasterLayerSpec("same", "B")),
                (FrameSpec("frame"),),
            )
        with self.assertRaisesRegex(PixeloramaModelError, "exceeds sprite frame count"):
            SpriteProjectSpec(
                16,
                16,
                (RasterLayerSpec("base", "Base"),),
                (FrameSpec("frame"),),
                animations=(AnimationSpec("bad", 0, 1),),
            )

    def test_request_sorts_refs_and_rejects_path_escape_overlap_and_budget_overflow(self) -> None:
        spec = self._spec()
        inputs = (
            BridgeInputRef("inputs/z.png", HASH_A, 5),
            BridgeInputRef("inputs/a.png", HASH_B, 7),
        )
        exports = (
            ExportSpec(BridgeOutputType.PNG, "exports/z.png"),
            ExportSpec(BridgeOutputType.SPRITESHEET, "exports/a.png"),
        )
        request = PixeloramaBridgeRequest.create(
            operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            sprite_spec=spec,
            input_refs=inputs,
            export_specs=exports,
        )
        self.assertEqual(
            [value.relative_path for value in request.input_refs],
            ["inputs/a.png", "inputs/z.png"],
        )
        self.assertEqual(
            [value.relative_path for value in request.export_specs],
            ["exports/a.png", "exports/z.png"],
        )
        self.assertTrue(request.content_hash.startswith("sha256:"))
        with self.assertRaises(PixeloramaModelError):
            BridgeInputRef("../outside.png", HASH_A, 1)
        with self.assertRaisesRegex(PixeloramaModelError, "exports/"):
            ExportSpec(BridgeOutputType.PNG, "project/not-export.png")
        with self.assertRaisesRegex(PixeloramaModelError, "input byte total"):
            PixeloramaBridgeRequest.create(
                operation=BridgeOperation.CREATE_SPRITE_PROJECT,
                sprite_spec=spec,
                input_refs=(BridgeInputRef("inputs/a.png", HASH_A, 11),),
                budget=BridgeBudget(max_input_bytes=10),
            )

    def test_create_operation_requires_sprite_spec(self) -> None:
        with self.assertRaisesRegex(PixeloramaModelError, "requires sprite_spec"):
            PixeloramaBridgeRequest.create(
                operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            )

    def test_bridge_result_is_hash_bound_and_has_no_production_authority_fields(self) -> None:
        operation_id = new_id(IdKind.PIXELORAMA_OPERATION)
        result = PixeloramaBridgeResult(
            operation_id=operation_id,
            request_hash=HASH_A,
            status=BridgeResultStatus.SUCCEEDED,
            pixelorama_version="test",
            bridge_version="0.1.0",
            bridge_fingerprint=HASH_B,
            outputs=(
                BridgeOutput(
                    BridgeOutputType.PNG,
                    "exports/frame.png",
                    HASH_A,
                    10,
                    16,
                    16,
                ),
            ),
            elapsed_ms=5,
        )
        payload = result.to_dict()
        self.assertTrue(payload["content_hash"].startswith("sha256:"))
        for forbidden in (
            "task_status",
            "verified",
            "approved",
            "merge",
            "release",
            "script",
            "command",
            "tool_call",
        ):
            self.assertNotIn(forbidden, payload)

    def test_output_paths_and_hashes_fail_closed(self) -> None:
        with self.assertRaisesRegex(PixeloramaModelError, "exports/ or project/"):
            BridgeOutput(BridgeOutputType.PNG, "outside/file.png", HASH_A, 1)
        with self.assertRaisesRegex(PixeloramaModelError, "sha256"):
            BridgeOutput(BridgeOutputType.PNG, "exports/file.png", "bad", 1)


if __name__ == "__main__":
    unittest.main()
