from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.blockbench_models import (
    AnimationLoopMode,
    AnimationSpec,
    BlockbenchProjectSpec,
    BoneSpec,
    CuboidSpec,
    KeyframeSpec,
    TextureRef,
    TransformChannel,
    Vec3,
    canonical_bytes,
)
from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.model3d_requests import (
    Model3DProductionRequest,
    Model3DRequestError,
    Model3DRequestOperation,
    Model3DRequestReader,
    Model3DRequestStore,
)
from origin_forge.runtime import OriginForgeRuntime


class Phase51AModel3DRequestSubstrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51a-model3d-request-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _simple_project(name: str = "crate") -> BlockbenchProjectSpec:
        return BlockbenchProjectSpec(
            project_name=name,
            bones=(),
            cuboids=(
                CuboidSpec(
                    element_id="body",
                    name="Body",
                    from_point=Vec3(0, 0, 0),
                    to_point=Vec3(2, 3, 4),
                    origin=Vec3(0, 0, 0),
                ),
            ),
        )

    @staticmethod
    def _rich_project() -> BlockbenchProjectSpec:
        return BlockbenchProjectSpec(
            project_name="rigged-source-proof",
            bones=(
                BoneSpec(
                    bone_id="root",
                    name="Root",
                    pivot=Vec3(0, 0, 0),
                ),
            ),
            cuboids=(
                CuboidSpec(
                    element_id="body",
                    name="Body",
                    from_point=Vec3(-1, 0, -1),
                    to_point=Vec3(1, 2, 1),
                    origin=Vec3(0, 1, 0),
                    parent_bone_id="root",
                    uv_offset=(4, 8),
                ),
            ),
            textures=(
                TextureRef(
                    texture_id="skin",
                    relative_path="inputs/textures/skin.png",
                    content_hash="sha256:" + "a" * 64,
                    byte_count=64,
                    width=16,
                    height=16,
                ),
            ),
            animations=(
                AnimationSpec(
                    animation_id="idle",
                    name="Idle",
                    length_seconds=1.0,
                    loop_mode=AnimationLoopMode.LOOP,
                    keyframes=(
                        KeyframeSpec(
                            bone_id="root",
                            time_seconds=0.0,
                            channel=TransformChannel.POSITION,
                            value=Vec3(0, 0, 0),
                        ),
                    ),
                ),
            ),
        )

    def test_request_identity_is_semantic_and_runtime_free(self) -> None:
        request = Model3DProductionRequest.create(project=self._simple_project())
        self.assertTrue(validate_id(request.request_id, IdKind.MODEL3D_REQUEST))
        self.assertTrue(request.request_id.startswith("MODEL3DREQ-"))
        self.assertEqual(request.operation, Model3DRequestOperation.EXPORT_GLB)
        self.assertTrue(request.request_hash.startswith("sha256:"))
        self.assertEqual(request.content_hash, request.request_hash)

        value = request.to_dict()
        self.assertEqual(
            set(value),
            {
                "schema_version",
                "request_id",
                "operation",
                "project",
                "project_hash",
                "request_hash",
            },
        )
        serialized = json.dumps(value, sort_keys=True)
        for forbidden in (
            "operation_id",
            "workspace_id",
            "output_relative_path",
            "runner_fingerprint",
            "runtime_hash",
            "expected_blender_version",
            "timeout_seconds",
            "max_output_bytes",
            "executable",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_store_and_noncreating_reader_round_trip_exact_project(self) -> None:
        request = Model3DProductionRequest.create(project=self._rich_project())
        store = Model3DRequestStore(self.runtime)
        stored = store.put(request)
        repeated = store.put(request)
        self.assertEqual(stored.path, repeated.path)
        self.assertEqual(stored.byte_count, repeated.byte_count)

        reader = Model3DRequestReader(self.runtime)
        loaded = reader.get(request.request_id, request.request_hash)
        self.assertEqual(loaded, request)
        self.assertEqual(loaded.project, self._rich_project())
        self.assertEqual(loaded.project.content_hash, request.project.content_hash)

    def test_missing_exact_reader_lookup_creates_no_registry(self) -> None:
        reader = Model3DRequestReader(self.runtime)
        registry = self.runtime.state_dir / "model3d-requests"
        self.assertFalse(registry.exists())
        with self.assertRaises(KeyError):
            reader.get(
                new_id(IdKind.MODEL3D_REQUEST),
                "sha256:" + "0" * 64,
            )
        self.assertFalse(registry.exists())

    def test_reader_rejects_hash_tamper_unknown_fields_and_noncanonical_json(self) -> None:
        request = Model3DProductionRequest.create(project=self._simple_project())
        stored = Model3DRequestStore(self.runtime).put(request)
        reader = Model3DRequestReader(self.runtime)

        value = request.to_dict()
        value["project_hash"] = "sha256:" + "1" * 64
        stored.path.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(Model3DRequestError, "project hash mismatch"):
            reader.get(request.request_id, request.request_hash)

        stored.path.write_bytes(canonical_bytes(request.to_dict()))
        value = request.to_dict()
        value["unexpected"] = True
        stored.path.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(Model3DRequestError, "unknown or missing"):
            reader.get(request.request_id, request.request_hash)

        stored.path.write_text(json.dumps(request.to_dict(), indent=2), encoding="utf-8")
        with self.assertRaisesRegex(Model3DRequestError, "not canonical JSON"):
            reader.get(request.request_id, request.request_hash)

    def test_reader_rejects_duplicate_json_keys(self) -> None:
        request = Model3DProductionRequest.create(project=self._simple_project())
        stored = Model3DRequestStore(self.runtime).put(request)
        canonical = canonical_bytes(request.to_dict()).decode("utf-8")
        duplicated = canonical.replace(
            '"schema_version":1',
            '"schema_version":1,"schema_version":1',
            1,
        )
        stored.path.write_text(duplicated, encoding="utf-8")
        with self.assertRaisesRegex(Model3DRequestError, "duplicate JSON keys"):
            Model3DRequestReader(self.runtime).get(
                request.request_id,
                request.request_hash,
            )

    def test_registry_rejects_undeclared_entry_and_catalog_overflow(self) -> None:
        store = Model3DRequestStore(self.runtime)
        registry = self.runtime.state_dir / "model3d-requests"
        registry.mkdir(parents=True)
        (registry / "junk.txt").write_text("junk", encoding="utf-8")
        with self.assertRaisesRegex(Model3DRequestError, "undeclared entry"):
            store.put(Model3DProductionRequest.create(project=self._simple_project()))

        (registry / "junk.txt").unlink()
        limited = Model3DRequestStore(self.runtime, max_requests=1)
        limited.put(Model3DProductionRequest.create(project=self._simple_project("first")))
        with self.assertRaisesRegex(Model3DRequestError, "registry is full"):
            limited.put(Model3DProductionRequest.create(project=self._simple_project("second")))

    def test_registry_and_reader_reject_symlink_authority(self) -> None:
        registry = self.runtime.state_dir / "model3d-requests"
        outside = self.root / "outside-registry"
        outside.mkdir()
        try:
            registry.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(Model3DRequestError, "root may not be a symlink"):
            Model3DRequestStore(self.runtime).put(
                Model3DProductionRequest.create(project=self._simple_project())
            )
        registry.unlink()

        request = Model3DProductionRequest.create(project=self._simple_project())
        stored = Model3DRequestStore(self.runtime).put(request)
        raw = stored.path.read_bytes()
        outside_file = self.root / "outside-request.json"
        outside_file.write_bytes(raw)
        stored.path.unlink()
        try:
            stored.path.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(Model3DRequestError, "entry may not be a symlink"):
            Model3DRequestReader(self.runtime).get(
                request.request_id,
                request.request_hash,
            )

    def test_constructor_rejects_wrong_id_and_non_enum_operation(self) -> None:
        project = self._simple_project()
        with self.assertRaisesRegex(Model3DRequestError, "MODEL3DREQ"):
            Model3DProductionRequest(
                request_id=new_id(IdKind.MODEL3D_WORKSPACE),
                operation=Model3DRequestOperation.EXPORT_GLB,
                project=project,
            )
        with self.assertRaisesRegex(Model3DRequestError, "Model3DRequestOperation"):
            Model3DProductionRequest(
                request_id=new_id(IdKind.MODEL3D_REQUEST),
                operation="EXPORT_GLB",  # type: ignore[arg-type]
                project=project,
            )


if __name__ == "__main__":
    unittest.main()
