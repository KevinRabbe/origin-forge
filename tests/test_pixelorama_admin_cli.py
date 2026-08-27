from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_admin_cli import build_parser, main
from origin_forge.runtime import OriginForgeRuntime


class PixeloramaAdminCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-admin-cli-test")
        self.lineage = OriginForgeLineage(self.runtime)
        workspace_id = new_id(IdKind.MEDIA_WORKSPACE)
        exports = self.runtime.state_dir / "media-workspaces" / workspace_id / "exports"
        exports.mkdir(parents=True)
        self.source = exports / "sprite.png"
        self.source.write_bytes(b"verified sprite bytes")
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.source_artifact = self.lineage.create_artifact(
            artifact_type="RASTER_EXPORT_PNG",
            path_or_uri=str(self.source),
            tool_versions=("pixelorama:test",),
            status="PRODUCED",
        )
        self.lineage.record_artifact_verification(
            self.source_artifact,
            verification_type="pixelorama-output-integrity",
            verifier="OriginForge.PixeloramaMediaService",
            status="PASS",
            evidence={"content_hash": self.source_hash},
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_surface_contains_only_explicit_governed_commands(self) -> None:
        parser = build_parser()
        subparsers = [
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        self.assertEqual(len(subparsers), 1)
        self.assertEqual(
            set(subparsers[0].choices),
            {
                "adopt-new",
                "adopt-production-new",
                "accept-production-task",
                "sign-production-provenance",
                "source-import",
                "source-inspect",
                "source-history",
                "source-replace",
            },
        )
        production = subparsers[0].choices["adopt-production-new"]
        positional_names = {
            action.dest
            for action in production._actions
            if action.dest not in {"help", "max_source_bytes"}
        }
        self.assertEqual(
            positional_names,
            {"execution_id", "destination_relative_path"},
        )
        acceptance = subparsers[0].choices["accept-production-task"]
        acceptance_argument_names = {
            action.dest
            for action in acceptance._actions
            if action.dest != "help"
        }
        self.assertEqual(acceptance_argument_names, {"execution_id"})
        for forbidden in (
            "run",
            "create",
            "export",
            "overwrite",
            "replace",
            "install",
            "script",
            "merge",
            "release",
            "sign",
        ):
            self.assertNotIn(forbidden, subparsers[0].choices)

    def test_adopt_new_creates_new_file_and_refuses_second_overwrite(self) -> None:
        code, payload = self._call(
            "adopt-new",
            self.source_artifact,
            "assets/sprites/adopted.png",
        )
        self.assertEqual(code, 0)
        destination = self.root / payload["destination_path"]
        self.assertEqual(destination.read_bytes(), self.source.read_bytes())
        self.assertEqual(payload["content_hash"], self.source_hash)
        self.assertFalse(payload["existing_asset_overwritten"])
        self.assertFalse(payload["production_task_verified"])

        code, failure = self._call(
            "adopt-new",
            self.source_artifact,
            "assets/sprites/adopted.png",
        )
        self.assertEqual(code, 2)
        self.assertIn("create-only", failure["detail"])
        self.assertEqual(destination.read_bytes(), b"verified sprite bytes")

    def test_protected_destination_and_byte_limit_fail_before_publication(self) -> None:
        code, payload = self._call(
            "adopt-new",
            self.source_artifact,
            ".git/forbidden.png",
        )
        self.assertEqual(code, 2)
        self.assertFalse((self.root / ".git" / "forbidden.png").exists())

        code, payload = self._call(
            "adopt-new",
            self.source_artifact,
            "assets/too-large.png",
            "--max-source-bytes",
            "4",
        )
        self.assertEqual(code, 2)
        self.assertIn("byte limit", payload["detail"])
        self.assertFalse((self.root / "assets" / "too-large.png").exists())

    def test_unknown_artifact_is_structured_not_found(self) -> None:
        code, payload = self._call(
            "adopt-new",
            new_id(IdKind.ARTIFACT),
            "assets/missing.png",
        )
        self.assertEqual(code, 3)
        self.assertEqual(payload["error"], "NOT_FOUND")

    def test_source_import_and_read_only_inspection_are_explicit(self) -> None:
        source = self.root / "assets" / "player.pxo"
        source.parent.mkdir()
        source.write_bytes(b"pixelorama source")

        code, imported = self._call("source-import", "assets/player.pxo")
        self.assertEqual(code, 0)
        self.assertTrue(imported["artifact_id"].startswith("ART-"))

        code, inspected = self._call("source-inspect", imported["artifact_id"])
        self.assertEqual(code, 0)
        self.assertTrue(inspected["read_only"])
        self.assertEqual(inspected["artifact"]["id"], imported["artifact_id"])

        code, history = self._call("source-history", imported["artifact_id"])
        self.assertEqual(code, 0)
        self.assertTrue(history["read_only"])
        self.assertEqual(len(history["revisions"]), 1)

        replacement = self.root / "assets" / "player-v2.pxo"
        replacement.write_bytes(b"pixelorama source v2")
        code, replaced = self._call(
            "source-replace",
            imported["artifact_id"],
            "assets/player-v2.pxo",
        )
        self.assertEqual(code, 0)
        self.assertNotEqual(replaced["artifact_id"], imported["artifact_id"])
        code, history = self._call("source-history", replaced["artifact_id"])
        self.assertEqual(code, 0)
        self.assertEqual(
            [item["artifact"]["id"] for item in history["revisions"]],
            [replaced["artifact_id"], imported["artifact_id"]],
        )


if __name__ == "__main__":
    unittest.main()
