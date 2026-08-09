from __future__ import annotations

import binascii
import hashlib
import json
import os
import struct
import tempfile
import textwrap
import unittest
import zlib
from pathlib import Path

from origin_forge.pixelorama_cli_export import (
    PixeloramaCliExportAdapter,
    PixeloramaCliExportRequest,
    PixeloramaCliIntegrityError,
    PixeloramaCliProfile,
    PixeloramaCliUnavailable,
)
from origin_forge.pixelorama_models import BridgeOperation
from origin_forge.runtime import OriginForgeRuntime


FAKE_PIXELORAMA = r'''#!/usr/bin/env python3
import binascii
import json
import struct
import sys
import time
import zlib
from pathlib import Path


def chunk(kind, data):
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xffffffff
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png():
    width, height = 4, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend((255, 0, 0, 255) if x == 0 and y == 0 else (0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")

args = sys.argv[1:]
if "--pixelorama-version" in args:
    print("Pixelorama v1.2")
    raise SystemExit(0)
mode = Path(__file__).stem
if "timeout" in mode:
    time.sleep(5)
expected_prefix = ["--headless", "--quit", "--", "--spritesheet", "--output"]
if args[:5] != expected_prefix or len(args) != 7:
    print("unexpected argv: " + repr(args), file=sys.stderr)
    raise SystemExit(9)
output = Path(args[5])
source = Path(args[6])
if not source.is_file():
    print("missing source", file=sys.stderr)
    raise SystemExit(8)
output.parent.mkdir(parents=True, exist_ok=True)
if "invalid" in mode:
    output.write_bytes(b"not a png")
else:
    output.write_bytes(png())
if "extra" in mode:
    (output.parent / "unexpected.png").write_bytes(png())
runtime = Path("runtime")
runtime.mkdir(exist_ok=True)
(runtime / "observed-argv.json").write_text(json.dumps(args), encoding="utf-8")
'''


class PixeloramaCliExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-cli-export-test")
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.source = self.root / "source.pxo"
        self.source.write_bytes(b"opaque pixelorama project fixture")
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _executable(self, name: str = "fake_pixelorama") -> Path:
        path = self.tools / name
        path.write_text(textwrap.dedent(FAKE_PIXELORAMA), encoding="utf-8")
        path.chmod(0o755)
        return path

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    def _profile(self, executable: Path, **overrides) -> PixeloramaCliProfile:
        values = dict(
            pixelorama_executable=executable,
            pixelorama_fingerprint=self._hash(executable),
            expected_pixelorama_version="v1.2",
            timeout_seconds=3,
        )
        values.update(overrides)
        return PixeloramaCliProfile(**values)

    def _request(self, **overrides) -> PixeloramaCliExportRequest:
        values = dict(
            source_hash=self.source_hash,
            source_byte_count=self.source.stat().st_size,
            timeout_seconds=2,
        )
        values.update(overrides)
        return PixeloramaCliExportRequest.create(**values)

    def test_request_is_content_addressed_and_surface_is_spritesheet_only(self) -> None:
        request = self._request()
        self.assertEqual(request.operation, BridgeOperation.EXPORT_SPRITESHEET)
        self.assertTrue(request.content_hash.startswith("sha256:"))
        self.assertEqual(request.to_dict()["content_hash"], request.content_hash)
        with self.assertRaisesRegex(ValueError, "exports/"):
            self._request(output_relative_path="outside.png")
        with self.assertRaisesRegex(ValueError, "inputs/"):
            self._request(source_relative_path="source.pxo")
        with self.assertRaisesRegex(ValueError, "EXPORT_SPRITESHEET"):
            PixeloramaCliExportRequest(
                operation_id=request.operation_id,
                workspace_id=request.workspace_id,
                operation=BridgeOperation.CREATE_SPRITE_PROJECT,
                source_relative_path=request.source_relative_path,
                source_hash=request.source_hash,
                source_byte_count=request.source_byte_count,
                output_relative_path=request.output_relative_path,
            )

    @unittest.skipIf(os.name == "nt", "fake shebang executable is POSIX-only")
    def test_official_cli_shape_exports_opaque_project_in_isolated_workspace(self) -> None:
        executable = self._executable()
        adapter = PixeloramaCliExportAdapter(
            self.runtime,
            self._profile(executable),
        )
        before_runs = self.runtime.list_runs()
        result = adapter.execute(self._request(), source_path=self.source)
        self.assertEqual(result.pixelorama_version, "v1.2")
        self.assertEqual((result.width, result.height), (4, 2))
        self.assertEqual(result.process_exit_code, 0)
        self.assertTrue(result.output_hash.startswith("sha256:"))
        self.assertFalse(result.to_dict()["production_verification_changed"])
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])
        self.assertEqual(self.runtime.list_runs(), before_runs)
        observed = json.loads(
            (result.workspace_path / "runtime" / "observed-argv.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            observed,
            [
                "--headless",
                "--quit",
                "--",
                "--spritesheet",
                "--output",
                "exports/spritesheet.png",
                "inputs/source.pxo",
            ],
        )
        self.assertEqual(
            (result.workspace_path / "inputs" / "source.pxo").read_bytes(),
            self.source.read_bytes(),
        )

    @unittest.skipIf(os.name == "nt", "fake shebang executable is POSIX-only")
    def test_version_and_executable_identity_fail_closed(self) -> None:
        executable = self._executable()
        bad_hash = self._profile(
            executable,
            pixelorama_fingerprint="sha256:" + "0" * 64,
        )
        with self.assertRaisesRegex(PixeloramaCliIntegrityError, "fingerprint mismatch"):
            PixeloramaCliExportAdapter(self.runtime, bad_hash).probe_version()
        bad_version = self._profile(
            executable,
            expected_pixelorama_version="v9.9",
        )
        with self.assertRaisesRegex(PixeloramaCliIntegrityError, "version does not match"):
            PixeloramaCliExportAdapter(self.runtime, bad_version).probe_version()

    @unittest.skipIf(os.name == "nt", "fake shebang executable is POSIX-only")
    def test_source_hash_drift_and_undeclared_exports_fail_closed(self) -> None:
        executable = self._executable()
        adapter = PixeloramaCliExportAdapter(self.runtime, self._profile(executable))
        drifted = self._request(source_hash="sha256:" + "0" * 64)
        with self.assertRaises(PixeloramaCliIntegrityError):
            adapter.execute(drifted, source_path=self.source)

        extra = self._executable("extra_pixelorama")
        runtime = OriginForgeRuntime(self.root / "extra-case")
        runtime.initialize("extra")
        with self.assertRaisesRegex(PixeloramaCliIntegrityError, "undeclared export"):
            PixeloramaCliExportAdapter(runtime, self._profile(extra)).execute(
                self._request(),
                source_path=self.source,
            )

    @unittest.skipIf(os.name == "nt", "fake shebang executable is POSIX-only")
    def test_invalid_png_and_timeout_are_not_success(self) -> None:
        invalid = self._executable("invalid_pixelorama")
        runtime = OriginForgeRuntime(self.root / "invalid-case")
        runtime.initialize("invalid")
        with self.assertRaisesRegex(PixeloramaCliIntegrityError, "RGBA8 PNG"):
            PixeloramaCliExportAdapter(runtime, self._profile(invalid)).execute(
                self._request(),
                source_path=self.source,
            )

        timeout = self._executable("timeout_pixelorama")
        runtime = OriginForgeRuntime(self.root / "timeout-case")
        runtime.initialize("timeout")
        with self.assertRaisesRegex(PixeloramaCliUnavailable, "exceeded timeout"):
            PixeloramaCliExportAdapter(
                runtime,
                self._profile(timeout, timeout_seconds=1),
            ).execute(
                self._request(timeout_seconds=1),
                source_path=self.source,
            )

    def test_cli_adapter_has_no_project_creation_model_task_or_merge_authority(self) -> None:
        executable = self._executable()
        adapter = PixeloramaCliExportAdapter(self.runtime, self._profile(executable))
        for forbidden in (
            "create_project",
            "import_layer",
            "save_project",
            "model",
            "generate",
            "verify_task",
            "transition_task",
            "merge",
            "release",
            "install_extension",
            "download",
        ):
            self.assertFalse(hasattr(adapter, forbidden))


@unittest.skipUnless(
    os.environ.get("ORIGIN_FORGE_PIXELORAMA_EXECUTABLE")
    and os.environ.get("ORIGIN_FORGE_PIXELORAMA_FIXTURE_PXO"),
    "real Pixelorama CLI fixture not configured",
)
class RealPixeloramaCliExportIntegrationTests(unittest.TestCase):
    def test_real_installed_pixelorama_exports_frozen_pxo_through_documented_cli(self) -> None:
        executable = Path(os.environ["ORIGIN_FORGE_PIXELORAMA_EXECUTABLE"])
        source = Path(os.environ["ORIGIN_FORGE_PIXELORAMA_FIXTURE_PXO"])
        expected_version = os.environ.get("ORIGIN_FORGE_PIXELORAMA_VERSION", "v1.2")
        executable_hash = "sha256:" + hashlib.sha256(executable.read_bytes()).hexdigest()
        source_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tempdir:
            runtime = OriginForgeRuntime(Path(tempdir))
            runtime.initialize("real-pixelorama-cli-export")
            profile = PixeloramaCliProfile(
                pixelorama_executable=executable,
                pixelorama_fingerprint=executable_hash,
                expected_pixelorama_version=expected_version,
                timeout_seconds=60,
            )
            request = PixeloramaCliExportRequest.create(
                source_hash=source_hash,
                source_byte_count=source.stat().st_size,
                timeout_seconds=60,
            )
            result = PixeloramaCliExportAdapter(runtime, profile).execute(
                request,
                source_path=source,
            )
            self.assertEqual(result.pixelorama_version, expected_version)
            self.assertGreater(result.width, 0)
            self.assertGreater(result.height, 0)
            self.assertTrue(
                (result.workspace_path / request.output_relative_path).is_file()
            )


if __name__ == "__main__":
    unittest.main()
