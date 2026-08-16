from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from origin_forge.production_dispatch_invocation import ProductionDispatchInvocationError
from origin_forge.production_dispatch_invocation_pixelorama import (
    PixeloramaInvocationRequest,
    _safe_source_path,
)
from origin_forge.production_work_order_models import content_hash
from origin_forge.records import create_artifact
from origin_forge.runtime import OriginForgeRuntime


class Phase48FPixeloramaMaterializerSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase48f-materializer-security")
        goal = self.runtime.create_goal("materializer security")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "materialize one Pixelorama project",
            required_capabilities=("media.2d.export",),
        )

    def _request(self, path: str, *, digest: str) -> PixeloramaInvocationRequest:
        artifact_id = create_artifact(
            self.runtime.store,
            self.runtime.project_id(),
            artifact_type="PIXELORAMA_PROJECT",
            path_or_uri=path,
            content_hash=digest,
        )
        projection = {
            "task_id": self.task_id,
            "source_artifact_id": artifact_id,
            "source_artifact_hash": digest,
            "source_artifact_type": "PIXELORAMA_PROJECT",
            "source_artifact_status": "PRODUCED",
            "source_path_or_uri": path,
            "operation": "EXPORT_SPRITESHEET",
            "staged_source_relative_path": "inputs/source.pxo",
            "output_relative_path": "exports/spritesheet.png",
        }
        return PixeloramaInvocationRequest(
            **projection,
            request_content_hash=content_hash(projection),
        )

    def test_protected_uri_noncanonical_and_non_pxo_paths_fail_before_source_read(self) -> None:
        cases = (
            ".origin-forge/source.pxo",
            ".git/source.pxo",
            "https://example.invalid/source.pxo",
            "assets/../source.pxo",
            "assets\\source.pxo",
            "assets/source.txt",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                request = self._request(raw, digest="a" * 64)
                with self.assertRaises(ProductionDispatchInvocationError):
                    _safe_source_path(self.runtime, request)

    def test_symlink_source_and_parent_fail_closed(self) -> None:
        real = self.root / "assets" / "real.pxo"
        real.parent.mkdir()
        real.write_bytes(b"opaque\n")
        digest = hashlib.sha256(real.read_bytes()).hexdigest()

        alias = self.root / "assets" / "alias.pxo"
        alias.symlink_to(real.name)
        request = self._request("assets/alias.pxo", digest=digest)
        with self.assertRaisesRegex(ProductionDispatchInvocationError, "symlink"):
            _safe_source_path(self.runtime, request)

        outside = self.root / "outside"
        outside.mkdir()
        (outside / "source.pxo").write_bytes(b"opaque\n")
        parent_alias = self.root / "linked"
        parent_alias.symlink_to(outside, target_is_directory=True)
        linked_digest = hashlib.sha256((outside / "source.pxo").read_bytes()).hexdigest()
        request = self._request("linked/source.pxo", digest=linked_digest)
        with self.assertRaisesRegex(ProductionDispatchInvocationError, "symlink"):
            _safe_source_path(self.runtime, request)

    def test_valid_portable_local_pxo_is_rehashed_and_sized(self) -> None:
        source = self.root / "assets" / "valid.pxo"
        source.parent.mkdir()
        source.write_bytes(b"opaque-pixelorama-project\n")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        request = self._request("assets/valid.pxo", digest=digest)

        materialized, byte_count = _safe_source_path(self.runtime, request)

        self.assertEqual(materialized, source.resolve())
        self.assertEqual(byte_count, source.stat().st_size)


if __name__ == "__main__":
    unittest.main()
