from __future__ import annotations

import unittest

from origin_forge.blender_models import BlenderJobRequest, BlenderModelError
from origin_forge.blockbench_models import (
    AnimationLoopMode,
    AnimationSpec,
    BlockbenchProjectSpec,
    BoneSpec,
    CuboidSpec,
    TextureRef,
    Vec3,
)
from origin_forge.ids import IdKind, validate_id


class BlenderModelTests(unittest.TestCase):
    @staticmethod
    def _cube(**overrides) -> CuboidSpec:
        values = {
            "element_id": "crate",
            "name": "Crate",
            "from_point": Vec3(-1, -1, -1),
            "to_point": Vec3(1, 1, 1),
            "origin": Vec3(0, 0, 0),
        }
        values.update(overrides)
        return CuboidSpec(**values)

    @classmethod
    def _project(cls, cube: CuboidSpec | None = None) -> BlockbenchProjectSpec:
        return BlockbenchProjectSpec(
            project_name="crate",
            bones=(),
            cuboids=(cube or cls._cube(),),
        )

    def test_request_owns_blender_and_workspace_ids_and_is_content_addressed(self) -> None:
        request = BlenderJobRequest.create(
            project=self._project(),
            output_relative_path="exports/crate.glb",
            runner_fingerprint="sha256:" + "1" * 64,
            runtime_hash="sha256:" + "2" * 64,
            expected_blender_version="Blender 5.2.0",
        )
        self.assertTrue(validate_id(request.operation_id, IdKind.BLENDER_OPERATION))
        self.assertTrue(validate_id(request.workspace_id, IdKind.MODEL3D_WORKSPACE))
        self.assertEqual(request.to_dict()["project_hash"], request.project.content_hash)
        self.assertTrue(request.content_hash.startswith("sha256:"))

    def test_output_path_and_runtime_runner_pins_are_strict(self) -> None:
        kwargs = {
            "project": self._project(),
            "runner_fingerprint": "sha256:" + "1" * 64,
            "runtime_hash": "sha256:" + "2" * 64,
            "expected_blender_version": "Blender 5.2.0",
        }
        with self.assertRaises(BlenderModelError):
            BlenderJobRequest.create(output_relative_path="../crate.glb", **kwargs)
        with self.assertRaisesRegex(BlenderModelError, "GLB"):
            BlenderJobRequest.create(output_relative_path="exports/crate.blend", **kwargs)
        with self.assertRaises(BlenderModelError):
            BlenderJobRequest.create(
                output_relative_path="exports/crate.glb",
                **{**kwargs, "runner_fingerprint": "not-a-hash"},
            )
        with self.assertRaises(BlenderModelError):
            BlenderJobRequest.create(
                output_relative_path="exports/crate.glb",
                **{**kwargs, "expected_blender_version": "Blender 5.2.0\nextra"},
            )

    def test_v1_rejects_unimplemented_scene_semantics_instead_of_dropping_them(self) -> None:
        base = {
            "output_relative_path": "exports/crate.glb",
            "runner_fingerprint": "sha256:" + "1" * 64,
            "runtime_hash": "sha256:" + "2" * 64,
            "expected_blender_version": "Blender 5.2.0",
        }
        projects = (
            BlockbenchProjectSpec(
                project_name="bones",
                bones=(BoneSpec("root", "Root", Vec3(0, 0, 0)),),
                cuboids=(self._cube(parent_bone_id="root"),),
            ),
            self._project(self._cube(rotation=Vec3(0, 45, 0))),
            self._project(self._cube(inflate=1)),
            self._project(self._cube(uv_offset=(4, 4))),
            self._project(self._cube(mirror_uv=True)),
            self._project(self._cube(visible=False)),
            BlockbenchProjectSpec(
                project_name="textures",
                bones=(),
                cuboids=(self._cube(),),
                textures=(
                    TextureRef(
                        "main",
                        "inputs/textures/main.png",
                        "sha256:" + "3" * 64,
                        10,
                        1,
                        1,
                    ),
                ),
            ),
        )
        for project in projects:
            with self.subTest(project=project.project_name):
                with self.assertRaises(BlenderModelError):
                    BlenderJobRequest.create(project=project, **base)

        animation = AnimationSpec(
            animation_id="idle",
            name="Idle",
            length_seconds=1,
            loop_mode=AnimationLoopMode.LOOP,
            keyframes=(),
        )
        with self.assertRaises(BlenderModelError):
            BlenderJobRequest.create(
                project=BlockbenchProjectSpec(
                    project_name="animation",
                    bones=(),
                    cuboids=(self._cube(),),
                    animations=(animation,),
                ),
                **base,
            )


if __name__ == "__main__":
    unittest.main()
