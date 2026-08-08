from __future__ import annotations

import copy
import unittest

from origin_forge.pixelorama_models import (
    BridgeOperation,
    BridgeOutput,
    BridgeOutputType,
    BridgeResultStatus,
    ExportSpec,
    FrameSpec,
    PixeloramaBridgeRequest,
    PixeloramaBridgeResult,
    RasterLayerSpec,
    SpriteProjectSpec,
    canonical_hash,
)
from origin_forge.pixelorama_protocol import (
    PixeloramaProtocolError,
    parse_bridge_request,
    parse_bridge_result,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


class PixeloramaProtocolTests(unittest.TestCase):
    @staticmethod
    def _request() -> PixeloramaBridgeRequest:
        return PixeloramaBridgeRequest.create(
            operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            sprite_spec=SpriteProjectSpec(
                8,
                8,
                (RasterLayerSpec("base", "Base"),),
                (FrameSpec("idle-0"),),
                output_basename="protocol-test",
            ),
            export_specs=(
                ExportSpec(BridgeOutputType.PNG, "exports/frame.png"),
            ),
        )

    def test_exact_request_and_result_round_trip(self) -> None:
        request = self._request()
        self.assertEqual(parse_bridge_request(request.to_dict()), request)
        result = PixeloramaBridgeResult(
            operation_id=request.operation_id,
            request_hash=request.content_hash,
            status=BridgeResultStatus.SUCCEEDED,
            pixelorama_version="1.1-test",
            bridge_version="0.1.0",
            bridge_fingerprint=HASH_A,
            outputs=(
                BridgeOutput(
                    BridgeOutputType.PNG,
                    "exports/frame.png",
                    HASH_B,
                    100,
                    8,
                    8,
                ),
            ),
            elapsed_ms=10,
        )
        self.assertEqual(parse_bridge_result(result.to_dict()), result)

    def test_unknown_top_level_or_nested_fields_fail_closed(self) -> None:
        request = self._request().to_dict()
        request["approved"] = True
        with self.assertRaisesRegex(PixeloramaProtocolError, "request fields"):
            parse_bridge_request(request)

        request = self._request().to_dict()
        request["sprite_spec"]["model_script"] = "dangerous()"
        request["content_hash"] = canonical_hash(
            {key: value for key, value in request.items() if key != "content_hash"}
        )
        with self.assertRaisesRegex(PixeloramaProtocolError, "sprite specification fields"):
            parse_bridge_request(request)

        result = PixeloramaBridgeResult(
            operation_id=self._request().operation_id,
            request_hash=HASH_A,
            status=BridgeResultStatus.FAILED,
            pixelorama_version="test",
            bridge_version="0.1.0",
            bridge_fingerprint=HASH_B,
        ).to_dict()
        result["task_verified"] = True
        with self.assertRaisesRegex(PixeloramaProtocolError, "result fields"):
            parse_bridge_result(result)

    def test_nested_sprite_hash_drift_fails_even_if_outer_request_hash_is_recomputed(self) -> None:
        request = self._request().to_dict()
        request["sprite_spec"]["width"] = 9
        request["content_hash"] = canonical_hash(
            {key: value for key, value in request.items() if key != "content_hash"}
        )
        with self.assertRaisesRegex(PixeloramaProtocolError, "sprite specification content hash mismatch"):
            parse_bridge_request(request)

    def test_outer_request_and_result_hash_mismatch_fail_closed(self) -> None:
        request = self._request().to_dict()
        request["content_hash"] = HASH_A
        with self.assertRaisesRegex(PixeloramaProtocolError, "request content hash mismatch"):
            parse_bridge_request(request)

        original_request = self._request()
        result = PixeloramaBridgeResult(
            operation_id=original_request.operation_id,
            request_hash=original_request.content_hash,
            status=BridgeResultStatus.FAILED,
            pixelorama_version="test",
            bridge_version="0.1.0",
            bridge_fingerprint=HASH_B,
        ).to_dict()
        result["content_hash"] = HASH_A
        with self.assertRaisesRegex(PixeloramaProtocolError, "result content hash mismatch"):
            parse_bridge_result(result)

    def test_invalid_enum_type_and_boolean_integer_confusion_fail_closed(self) -> None:
        request = self._request().to_dict()
        request["operation"] = "RUN_ARBITRARY_SCRIPT"
        request["content_hash"] = canonical_hash(
            {key: value for key, value in request.items() if key != "content_hash"}
        )
        with self.assertRaises(PixeloramaProtocolError):
            parse_bridge_request(request)

        request = self._request().to_dict()
        request["sprite_spec"]["width"] = True
        request["sprite_spec"]["content_hash"] = canonical_hash(
            {
                key: value
                for key, value in request["sprite_spec"].items()
                if key != "content_hash"
            }
        )
        request["content_hash"] = canonical_hash(
            {key: value for key, value in request.items() if key != "content_hash"}
        )
        with self.assertRaisesRegex(PixeloramaProtocolError, "width must be an integer"):
            parse_bridge_request(request)

    def test_result_output_content_cannot_be_changed_under_recomputed_outer_hash(self) -> None:
        request = self._request()
        result = PixeloramaBridgeResult(
            operation_id=request.operation_id,
            request_hash=request.content_hash,
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
                    8,
                    8,
                ),
            ),
        ).to_dict()
        changed = copy.deepcopy(result)
        changed["outputs"][0]["output_type"] = "PIXELORAMA_PROJECT"
        changed["content_hash"] = canonical_hash(
            {key: value for key, value in changed.items() if key != "content_hash"}
        )
        # The parser reconstructs a typed BridgeOutput; the adapter later checks
        # that it also matches the request's exact declared output type/path set.
        parsed = parse_bridge_result(changed)
        self.assertEqual(parsed.outputs[0].output_type, BridgeOutputType.PIXELORAMA_PROJECT)


if __name__ == "__main__":
    unittest.main()
