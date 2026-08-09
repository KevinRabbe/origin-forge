from __future__ import annotations

import unittest

from origin_forge.blockbench_models import (
    BlockbenchBridgeRequest,
    BlockbenchModelError,
    BlockbenchOperation,
    BlockbenchProjectSpec,
    BoneSpec,
    CuboidSpec,
    Vec3,
)
from origin_forge.blockbench_protocol import (
    BlockbenchBridgeOutput,
    BlockbenchBridgeResult,
    BlockbenchOutputType,
    BlockbenchResultStatus,
)


class BlockbenchProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        project = BlockbenchProjectSpec(
            project_name="crate",
            bones=(BoneSpec("root", "Root", Vec3(0, 0, 0)),),
            cuboids=(
                CuboidSpec(
                    element_id="crate",
                    name="Crate",
                    from_point=Vec3(0, 0, 0),
                    to_point=Vec3(2, 2, 2),
                    origin=Vec3(1, 1, 1),
                    parent_bone_id="root",
                ),
            ),
        )
        self.request = BlockbenchBridgeRequest.create(
            operation=BlockbenchOperation.EXPORT_GLB,
            project=project,
            output_relative_path="exports/crate.glb",
            bridge_fingerprint="sha256:" + "a" * 64,
            expected_blockbench_version="5.1.4",
        )
        self.output = BlockbenchBridgeOutput(
            output_type=BlockbenchOutputType.GLB,
            relative_path="exports/crate.glb",
            content_hash="sha256:" + "b" * 64,
            byte_count=128,
        )

    def _result(self, **overrides) -> BlockbenchBridgeResult:
        values = dict(
            operation_id=self.request.operation_id,
            workspace_id=self.request.workspace_id,
            request_hash=self.request.content_hash,
            status=BlockbenchResultStatus.SUCCEEDED,
            blockbench_version="5.1.4",
            bridge_fingerprint=self.request.bridge_fingerprint,
            outputs=(self.output,),
            diagnostics=(),
        )
        values.update(overrides)
        return BlockbenchBridgeResult(**values)

    def test_exact_success_binds_request_and_is_content_addressed(self) -> None:
        result = self._result()
        result.bind_to_request(self.request)
        self.assertTrue(result.content_hash.startswith("sha256:"))
        restored = BlockbenchBridgeResult.from_dict(result.to_dict())
        self.assertEqual(restored, result)
        restored.bind_to_request(self.request)

    def test_wrong_request_identity_version_and_fingerprint_fail_binding(self) -> None:
        for override, message in (
            ({"request_hash": "sha256:" + "0" * 64}, "request_hash"),
            ({"blockbench_version": "5.1.3"}, "version"),
            ({"bridge_fingerprint": "sha256:" + "0" * 64}, "fingerprint"),
        ):
            with self.assertRaisesRegex(BlockbenchModelError, message):
                self._result(**override).bind_to_request(self.request)

    def test_success_must_bind_exact_declared_output(self) -> None:
        wrong = BlockbenchBridgeOutput(
            output_type=BlockbenchOutputType.GLB,
            relative_path="exports/other.glb",
            content_hash="sha256:" + "c" * 64,
            byte_count=10,
        )
        with self.assertRaisesRegex(BlockbenchModelError, "exact declared output"):
            self._result(outputs=(wrong,)).bind_to_request(self.request)
        with self.assertRaisesRegex(BlockbenchModelError, "must contain output"):
            self._result(outputs=())

    def test_extra_authority_fields_and_unknown_output_fields_fail_strict_parse(self) -> None:
        payload = self._result().to_dict()
        payload["task_verified"] = True
        with self.assertRaisesRegex(BlockbenchModelError, "strict schema"):
            BlockbenchBridgeResult.from_dict(payload)

        payload = self._result().to_dict()
        payload["outputs"][0]["merge"] = True
        with self.assertRaisesRegex(BlockbenchModelError, "strict schema"):
            BlockbenchBridgeResult.from_dict(payload)

    def test_output_paths_and_suffixes_are_bounded(self) -> None:
        with self.assertRaises(BlockbenchModelError):
            BlockbenchBridgeOutput(
                output_type=BlockbenchOutputType.GLB,
                relative_path="../outside.glb",
                content_hash="sha256:" + "b" * 64,
                byte_count=1,
            )
        with self.assertRaisesRegex(BlockbenchModelError, "end with .glb"):
            BlockbenchBridgeOutput(
                output_type=BlockbenchOutputType.GLB,
                relative_path="exports/model.bbmodel",
                content_hash="sha256:" + "b" * 64,
                byte_count=1,
            )

    def test_failed_result_can_carry_diagnostics_without_success_authority(self) -> None:
        result = self._result(
            status=BlockbenchResultStatus.FAILED,
            outputs=(),
            diagnostics=("Blockbench rejected the project",),
        )
        result.bind_to_request(self.request)
        self.assertEqual(result.status, BlockbenchResultStatus.FAILED)
        self.assertFalse(hasattr(result, "verify_task"))
        self.assertFalse(hasattr(result, "merge"))
        self.assertFalse(hasattr(result, "release"))


if __name__ == "__main__":
    unittest.main()
