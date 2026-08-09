from __future__ import annotations

import unittest

from origin_forge.blockbench_models import (
    AnimationLoopMode,
    AnimationSpec,
    BlockbenchBridgeRequest,
    BlockbenchModelError,
    BlockbenchOperation,
    BlockbenchProjectSpec,
    BoneSpec,
    CuboidSpec,
    KeyframeSpec,
    TransformChannel,
    Vec3,
)
from origin_forge.ids import IdKind, validate_id


class BlockbenchModelTests(unittest.TestCase):
    @staticmethod
    def _cube(element_id: str, parent: str | None = None) -> CuboidSpec:
        return CuboidSpec(
            element_id=element_id,
            name=element_id,
            from_point=Vec3(0, 0, 0),
            to_point=Vec3(2, 3, 4),
            origin=Vec3(1, 1.5, 2),
            parent_bone_id=parent,
            uv_offset=(0, 0),
        )

    def test_project_is_order_normalized_and_content_addressed(self) -> None:
        root = BoneSpec("root", "Root", Vec3(0, 0, 0))
        child = BoneSpec("arm", "Arm", Vec3(1, 2, 3), parent_bone_id="root")
        animation = AnimationSpec(
            animation_id="idle",
            name="Idle",
            length_seconds=1,
            loop_mode=AnimationLoopMode.LOOP,
            keyframes=(
                KeyframeSpec("arm", 1, TransformChannel.ROTATION, Vec3(0, 20, 0)),
                KeyframeSpec("arm", 0, TransformChannel.ROTATION, Vec3(0, 0, 0)),
            ),
        )
        first = BlockbenchProjectSpec(
            project_name="robot",
            bones=(child, root),
            cuboids=(self._cube("body", "root"), self._cube("hand", "arm")),
            animations=(animation,),
        )
        second = BlockbenchProjectSpec(
            project_name="robot",
            bones=(root, child),
            cuboids=(self._cube("hand", "arm"), self._cube("body", "root")),
            animations=(animation,),
        )
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual([bone.bone_id for bone in first.bones], ["arm", "root"])
        self.assertEqual(
            [frame.time_seconds for frame in first.animations[0].keyframes],
            [0.0, 1.0],
        )

    def test_hierarchy_cycle_missing_parent_and_unknown_animation_bone_fail_closed(self) -> None:
        with self.assertRaisesRegex(BlockbenchModelError, "cycle"):
            BlockbenchProjectSpec(
                project_name="cycle",
                bones=(
                    BoneSpec("a", "A", Vec3(0, 0, 0), parent_bone_id="b"),
                    BoneSpec("b", "B", Vec3(0, 0, 0), parent_bone_id="a"),
                ),
                cuboids=(self._cube("body", "a"),),
            )
        with self.assertRaisesRegex(BlockbenchModelError, "parent"):
            BlockbenchProjectSpec(
                project_name="missing",
                bones=(),
                cuboids=(self._cube("body", "missing"),),
            )
        animation = AnimationSpec(
            animation_id="bad",
            name="Bad",
            length_seconds=1,
            loop_mode=AnimationLoopMode.ONCE,
            keyframes=(
                KeyframeSpec("missing", 0, TransformChannel.POSITION, Vec3(0, 0, 0)),
            ),
        )
        with self.assertRaisesRegex(BlockbenchModelError, "project bones"):
            BlockbenchProjectSpec(
                project_name="animation",
                bones=(BoneSpec("root", "Root", Vec3(0, 0, 0)),),
                cuboids=(self._cube("body", "root"),),
                animations=(animation,),
            )

    def test_cuboid_bounds_and_duplicate_keyframes_are_strict(self) -> None:
        with self.assertRaisesRegex(BlockbenchModelError, "to_point.x"):
            CuboidSpec(
                element_id="bad",
                name="Bad",
                from_point=Vec3(2, 0, 0),
                to_point=Vec3(1, 1, 1),
                origin=Vec3(0, 0, 0),
            )
        frame = KeyframeSpec("root", 0, TransformChannel.SCALE, Vec3(1, 1, 1))
        with self.assertRaisesRegex(BlockbenchModelError, "duplicate"):
            AnimationSpec(
                animation_id="dup",
                name="Duplicate",
                length_seconds=1,
                loop_mode=AnimationLoopMode.LOOP,
                keyframes=(frame, frame),
            )

    def test_bridge_request_owns_ids_and_rejects_arbitrary_output_paths(self) -> None:
        project = BlockbenchProjectSpec(
            project_name="crate",
            bones=(BoneSpec("root", "Root", Vec3(0, 0, 0)),),
            cuboids=(self._cube("crate", "root"),),
        )
        request = BlockbenchBridgeRequest.create(
            operation=BlockbenchOperation.EXPORT_GLB,
            project=project,
            output_relative_path="exports/crate.glb",
            bridge_fingerprint="sha256:" + "1" * 64,
            expected_blockbench_version="5.1.4",
        )
        self.assertTrue(validate_id(request.operation_id, IdKind.BLOCKBENCH_OPERATION))
        self.assertTrue(validate_id(request.workspace_id, IdKind.MODEL3D_WORKSPACE))
        self.assertTrue(request.content_hash.startswith("sha256:"))
        self.assertEqual(request.to_dict()["project_hash"], project.content_hash)
        with self.assertRaises(BlockbenchModelError):
            BlockbenchBridgeRequest.create(
                operation=BlockbenchOperation.EXPORT_GLB,
                project=project,
                output_relative_path="../crate.glb",
                bridge_fingerprint="sha256:" + "1" * 64,
                expected_blockbench_version="5.1.4",
            )
        with self.assertRaisesRegex(BlockbenchModelError, "end with .glb"):
            BlockbenchBridgeRequest.create(
                operation=BlockbenchOperation.EXPORT_GLB,
                project=project,
                output_relative_path="exports/crate.bbmodel",
                bridge_fingerprint="sha256:" + "1" * 64,
                expected_blockbench_version="5.1.4",
            )


if __name__ == "__main__":
    unittest.main()
