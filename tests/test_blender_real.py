from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from origin_forge.blender_adapter import (
    BlenderAdapter,
    BlenderRuntimeProfile,
    blender_runner_v1_fingerprint,
    blender_runtime_tree_hash,
)
from origin_forge.blender_models import BlenderBudget, BlenderJobRequest
from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.runtime import OriginForgeRuntime


_REQUIRED_ENV = (
    "ORIGIN_FORGE_REAL_BLENDER_RUNTIME_ROOT",
    "ORIGIN_FORGE_REAL_BLENDER_EXECUTABLE",
    "ORIGIN_FORGE_REAL_BLENDER_RUNTIME_HASH",
    "ORIGIN_FORGE_REAL_BLENDER_VERSION",
    "ORIGIN_FORGE_REAL_BLENDER_SOURCE_COMMIT",
    "ORIGIN_FORGE_REAL_BLENDER_ARCHIVE_SHA256",
    "ORIGIN_FORGE_REAL_BLENDER_RUNNER_SHA256",
)


class RealBlenderIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        all(os.environ.get(name) for name in _REQUIRED_ENV),
        "real pinned Blender evidence is not configured",
    )
    def test_real_pinned_blender_exports_frozen_cuboid_glb(self) -> None:
        runtime_root = Path(os.environ["ORIGIN_FORGE_REAL_BLENDER_RUNTIME_ROOT"])
        executable = Path(os.environ["ORIGIN_FORGE_REAL_BLENDER_EXECUTABLE"])
        runtime_hash = os.environ["ORIGIN_FORGE_REAL_BLENDER_RUNTIME_HASH"]
        expected_version = os.environ["ORIGIN_FORGE_REAL_BLENDER_VERSION"]
        source_commit = os.environ["ORIGIN_FORGE_REAL_BLENDER_SOURCE_COMMIT"]
        archive_sha = os.environ["ORIGIN_FORGE_REAL_BLENDER_ARCHIVE_SHA256"]
        runner_sha = os.environ["ORIGIN_FORGE_REAL_BLENDER_RUNNER_SHA256"]

        self.assertEqual(
            source_commit,
            "fbe6228777e7d9afefcd61a413844e790ae75db7",
        )
        self.assertEqual(
            archive_sha,
            "96f6c181a30f4950607839dc84d42a354b250d8a0231b098b59b7bc69c351c48",
        )
        self.assertEqual(expected_version, "Blender 5.2.0 LTS")
        self.assertEqual(blender_runtime_tree_hash(runtime_root), runtime_hash)
        self.assertEqual(blender_runner_v1_fingerprint(), runner_sha)

        project = BlockbenchProjectSpec(
            project_name="origin-forge-real-blender-crate",
            bones=(),
            cuboids=(
                CuboidSpec(
                    element_id="crate",
                    name="Crate",
                    from_point=Vec3(-1, -2, -3),
                    to_point=Vec3(1, 2, 3),
                    origin=Vec3(0, 0, 0),
                ),
            ),
        )
        profile = BlenderRuntimeProfile(
            runtime_root=runtime_root,
            executable=executable,
            runtime_hash=runtime_hash,
            expected_blender_version=expected_version,
            runner_fingerprint=runner_sha,
        )

        with tempfile.TemporaryDirectory() as tempdir:
            runtime = OriginForgeRuntime(Path(tempdir) / "project")
            runtime.initialize("real-blender-evidence")
            before_runs = runtime.list_runs()
            request = BlenderJobRequest.create(
                project=project,
                output_relative_path="exports/crate.glb",
                runner_fingerprint=runner_sha,
                runtime_hash=runtime_hash,
                expected_blender_version=expected_version,
                budget=BlenderBudget(timeout_seconds=180),
            )
            execution = BlenderAdapter(runtime, profile).execute(request)
            self.assertEqual(runtime.list_runs(), before_runs)
            self.assertEqual(execution.inspection.mesh_count, 1)
            self.assertGreaterEqual(execution.inspection.node_count, 1)
            self.assertEqual(execution.inspection.material_count, 0)
            self.assertEqual(execution.inspection.texture_count, 0)
            self.assertEqual(execution.inspection.animation_count, 0)
            self.assertGreater(execution.inspection.embedded_bin_bytes, 0)
            self.assertEqual(execution.blender_version, expected_version)
            self.assertEqual(execution.runtime_hash, runtime_hash)
            self.assertEqual(execution.runner_fingerprint, runner_sha)
            self.assertFalse(execution.to_dict()["production_verification_changed"])
            self.assertFalse(execution.to_dict()["canonical_asset_adopted"])


if __name__ == "__main__":
    unittest.main()
