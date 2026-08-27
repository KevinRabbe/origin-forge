from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.pixelorama_models import (
    AnimationLoopMode,
    AnimationSpec,
    BridgeBudget,
    BridgeOutputType,
    ExportSpec,
    FrameSpec,
    LayerBlendMode,
    RasterLayerSpec,
    SpriteProjectSpec,
)
from origin_forge.production_pixelorama_source_request import (
    PixeloramaSourceRequestError,
    decode_pixelorama_source_request,
)


class PixeloramaSourceRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = SpriteProjectSpec(
            width=16,
            height=16,
            layers=(
                RasterLayerSpec(
                    "player", "Player", blend_mode=LayerBlendMode.NORMAL
                ),
            ),
            frames=(FrameSpec("idle-0", 100), FrameSpec("idle-1", 100)),
            animations=(AnimationSpec("idle", 0, 1, AnimationLoopMode.LOOP),),
            output_basename="player",
        )
        self.projection = {
            "acceptance_id": new_id(IdKind.DESIGN_SPECIFICATION_ACCEPTANCE),
            "acceptance_hash": "sha256:" + "a" * 64,
            "design_input_id": new_id(IdKind.DESIGN_SPECIFICATION_INPUT),
            "planning_input_id": new_id(IdKind.PLANNING_INPUT),
        }

    def _payload(self) -> dict[str, object]:
        return {
            "operation": "CREATE_SPRITE_PROJECT",
            "sprite_spec": self.spec.to_dict(),
            "export_specs": [
                ExportSpec(BridgeOutputType.PNG, "exports/player.png").to_dict()
            ],
            "budget": BridgeBudget().to_dict(),
        }

    def test_decode_preserves_animation_and_exact_design_projection(self) -> None:
        request = decode_pixelorama_source_request(
            new_id(IdKind.TASK), self._payload(), self.projection
        )
        self.assertEqual(request.sprite_spec.animations[0].name, "idle")
        self.assertEqual(request.accepted_design_id, self.projection["acceptance_id"])
        self.assertEqual(request.content_hash, request.content_hash)
        bridge = request.to_bridge_request()
        self.assertEqual(bridge.sprite_spec, self.spec)

    def test_decode_rejects_extra_payload_fields(self) -> None:
        payload = self._payload()
        payload["output_path"] = "exports/player.png"
        with self.assertRaisesRegex(PixeloramaSourceRequestError, "fields are not exact"):
            decode_pixelorama_source_request(new_id(IdKind.TASK), payload, self.projection)

    def test_decode_rejects_animation_hash_drift(self) -> None:
        payload = self._payload()
        payload["sprite_spec"] = {**self.spec.to_dict(), "content_hash": "sha256:" + "f" * 64}
        with self.assertRaisesRegex(PixeloramaSourceRequestError, "projection is invalid"):
            decode_pixelorama_source_request(new_id(IdKind.TASK), payload, self.projection)


if __name__ == "__main__":
    unittest.main()
