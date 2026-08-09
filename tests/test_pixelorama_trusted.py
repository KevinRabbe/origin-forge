from __future__ import annotations

import hashlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from origin_forge.pixelorama_bridge import (
    PixeloramaBridgeIntegrityError,
    PixeloramaBridgeProfile,
)
from origin_forge.pixelorama_models import (
    BridgeBudget,
    BridgeOperation,
    BridgeOutputType,
    ExportSpec,
    FrameSpec,
    PixeloramaBridgeRequest,
    RasterLayerSpec,
    SpriteProjectSpec,
)
from origin_forge.pixelorama_trusted import (
    PixeloramaInstallationError,
    TrustedPixeloramaBridgeAdapter,
    TrustedPixeloramaInstallation,
)
from origin_forge.runtime import OriginForgeRuntime


BRIDGE = r'''import binascii
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path


def canonical_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def chunk(kind, data):
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xffffffff
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png(width, height):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend((255, 0, 0, 255) if (x, y) == (0, 0) else (0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")

args = sys.argv[1:]
args = args[args.index("--") + 1:]
request_path = Path(args[args.index("--origin-forge-request") + 1])
result_path = Path(args[args.index("--origin-forge-result") + 1])
request = json.loads(request_path.read_text(encoding="utf-8"))
spec = request["sprite_spec"]
fingerprint = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
project = Path("project") / (spec["output_basename"] + ".pxo")
project.write_bytes(b"fake project\n")
path = Path("exports/frame.png")
path.parent.mkdir(parents=True, exist_ok=True)
data = png(spec["width"], spec["height"])
path.write_bytes(data)
outputs = [
    {
        "output_type": "PIXELORAMA_PROJECT",
        "relative_path": project.as_posix(),
        "content_hash": "sha256:" + hashlib.sha256(project.read_bytes()).hexdigest(),
        "byte_count": project.stat().st_size,
        "width": None,
        "height": None,
    },
    {
        "output_type": "PNG",
        "relative_path": path.as_posix(),
        "content_hash": "sha256:" + hashlib.sha256(data).hexdigest(),
        "byte_count": len(data),
        "width": spec["width"],
        "height": spec["height"],
    },
]
outputs.sort(key=lambda value: value["relative_path"])
result = {
    "protocol_version": 1,
    "operation_id": request["operation_id"],
    "request_hash": request["content_hash"],
    "status": "SUCCEEDED",
    "pixelorama_version": "trusted-test-version",
    "bridge_version": "trusted-test-bridge",
    "bridge_fingerprint": fingerprint,
    "outputs": outputs,
    "diagnostics": [],
    "elapsed_ms": 1,
}
result["content_hash"] = canonical_hash(result)
result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
'''


class PixeloramaTrustedInstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-trusted-test")
        self.bridge = self.root / "trusted_bridge.py"
        self.bridge.write_text(textwrap.dedent(BRIDGE), encoding="utf-8")
        self.executable = Path(sys.executable).resolve()
        self.executable_hash = self._hash(self.executable)
        self.bridge_hash = self._hash(self.bridge)
        self.profile = PixeloramaBridgeProfile(
            bridge_id="trusted-pixelorama-test",
            bridge_version="trusted-test-bridge",
            bridge_fingerprint=self.bridge_hash,
            pixelorama_executable=self.executable,
            bridge_package=self.bridge,
            allowed_operations=(BridgeOperation.CREATE_SPRITE_PROJECT,),
            launcher_args=(str(self.bridge),),
            timeout_seconds=5,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _request() -> PixeloramaBridgeRequest:
        return PixeloramaBridgeRequest.create(
            operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            sprite_spec=SpriteProjectSpec(
                2,
                2,
                (RasterLayerSpec("base", "Base"),),
                (FrameSpec("frame-0"),),
                output_basename="trusted-test",
            ),
            export_specs=(ExportSpec(BridgeOutputType.PNG, "exports/frame.png"),),
            budget=BridgeBudget(timeout_seconds=5),
        )

    def _installation(self, **overrides) -> TrustedPixeloramaInstallation:
        values = dict(
            profile=self.profile,
            pixelorama_fingerprint=self.executable_hash,
            expected_pixelorama_version="trusted-test-version",
        )
        values.update(overrides)
        return TrustedPixeloramaInstallation(**values)

    def test_pinned_editor_and_bridge_identity_wrap_successful_operation(self) -> None:
        installation = self._installation()
        identity = installation.verify_files()
        self.assertEqual(identity["pixelorama_fingerprint"], self.executable_hash)
        self.assertEqual(identity["bridge_fingerprint"], self.bridge_hash)
        result = TrustedPixeloramaBridgeAdapter(
            self.runtime,
            installation,
        ).execute(self._request())
        self.assertTrue(result.succeeded)
        self.assertEqual(
            result.bridge_result.pixelorama_version,
            "trusted-test-version",
        )

    def test_wrong_executable_hash_fails_before_bridge_run(self) -> None:
        installation = self._installation(
            pixelorama_fingerprint="sha256:" + "0" * 64
        )
        with self.assertRaisesRegex(
            PixeloramaInstallationError,
            "executable fingerprint mismatch",
        ):
            TrustedPixeloramaBridgeAdapter(
                self.runtime,
                installation,
            ).execute(self._request())
        self.assertFalse((self.runtime.state_dir / "media-workspaces").exists())

    def test_bridge_reported_wrong_pixelorama_version_is_rejected(self) -> None:
        installation = self._installation(
            expected_pixelorama_version="different-version"
        )
        with self.assertRaisesRegex(
            PixeloramaBridgeIntegrityError,
            "version does not match",
        ):
            TrustedPixeloramaBridgeAdapter(
                self.runtime,
                installation,
            ).execute(self._request())

    def test_executable_size_limit_is_bounded(self) -> None:
        installation = self._installation(max_executable_bytes=1)
        with self.assertRaisesRegex(
            PixeloramaInstallationError,
            "exceeds byte limit",
        ):
            installation.verify_files()

    def test_trusted_wrapper_has_no_model_task_merge_release_or_install_surface(self) -> None:
        adapter = TrustedPixeloramaBridgeAdapter(
            self.runtime,
            self._installation(),
        )
        for forbidden in (
            "model",
            "generate",
            "verify_task",
            "transition_task",
            "merge",
            "release",
            "install_plugin",
            "download_extension",
            "sign",
        ):
            self.assertFalse(hasattr(adapter, forbidden))


if __name__ == "__main__":
    unittest.main()
