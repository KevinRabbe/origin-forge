from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from origin_forge.project_binding_inspection import (
    BindingInspectionStatus,
    BindingInspector,
)
from origin_forge.project_intelligence import ProjectIntelligenceService
from origin_forge.project_models import BindingType, EntityKind
from origin_forge.runtime import OriginForgeRuntime


def file_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ProjectBindingInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("binding-inspection-test")
        self.intelligence = ProjectIntelligenceService(self.runtime)
        self.entity = self.intelligence.create_entity(EntityKind.COMPONENT, "Bound file")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_pinned_file_transitions_current_stale_missing_without_mutation(self) -> None:
        path = self.root / "asset.txt"
        path.write_bytes(b"first")
        binding = self.intelligence.create_binding(
            self.entity,
            BindingType.FILE,
            "asset.txt",
            target_hash=file_hash(b"first"),
        )
        inspector = BindingInspector(self.intelligence)
        current = inspector.inspect(binding)
        self.assertEqual(current.status, BindingInspectionStatus.CURRENT)
        self.assertEqual(current.current_hash, file_hash(b"first"))
        self.assertFalse(current.to_dict()["canonical_binding_changed"])

        path.write_bytes(b"second")
        stale = inspector.inspect(binding)
        self.assertEqual(stale.status, BindingInspectionStatus.STALE)
        self.assertEqual(
            self.intelligence.get_binding(binding)["target_hash"],
            file_hash(b"first"),
        )

        path.unlink()
        missing = inspector.inspect(binding)
        self.assertEqual(missing.status, BindingInspectionStatus.MISSING)

    def test_unpinned_nonfile_symlink_and_size_limits_are_explicit(self) -> None:
        unpinned = self.intelligence.create_binding(
            self.entity,
            BindingType.FILE,
            "untracked.txt",
        )
        self.assertEqual(
            BindingInspector(self.intelligence).inspect(unpinned).status,
            BindingInspectionStatus.UNPINNED,
        )

        external = self.intelligence.create_binding(
            self.entity,
            BindingType.EXTERNAL_REF,
            "spec:combat-v1",
        )
        self.assertEqual(
            BindingInspector(self.intelligence).inspect(external).status,
            BindingInspectionStatus.UNSUPPORTED,
        )

        real = self.root / "real.txt"
        real.write_bytes(b"content")
        link = self.root / "link.txt"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pass
        else:
            linked = self.intelligence.create_binding(
                self.entity,
                BindingType.FILE,
                "link.txt",
                target_hash=file_hash(b"content"),
            )
            self.assertEqual(
                BindingInspector(self.intelligence).inspect(linked).status,
                BindingInspectionStatus.INVALID_PATH,
            )

        large = self.root / "large.bin"
        large.write_bytes(b"12345")
        large_binding = self.intelligence.create_binding(
            self.entity,
            BindingType.FILE,
            "large.bin",
            target_hash=file_hash(b"12345"),
        )
        inspection = BindingInspector(self.intelligence, max_file_bytes=4).inspect(
            large_binding
        )
        self.assertEqual(inspection.status, BindingInspectionStatus.TOO_LARGE)
        self.assertGreater(inspection.bytes_read, 4)


if __name__ == "__main__":
    unittest.main()
