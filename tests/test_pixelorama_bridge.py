from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.pixelorama_bridge import (
    PixeloramaBridgeAdapter,
    PixeloramaBridgeIntegrityError,
    PixeloramaBridgeProfile,
    PixeloramaBridgeUnavailable,
)
from origin_forge.pixelorama_models import (
    BridgeBudget,
    BridgeInputRef,
    BridgeOperation,
    BridgeOutputType,
    ExportSpec,
    FrameSpec,
    PixeloramaBridgeRequest,
    RasterLayerSpec,
    SpriteProjectSpec,
)
from origin_forge.runtime import OriginForgeRuntime


FAKE_BRIDGE = r'''#!/usr/bin/env python3
import binascii
import hashlib
import json
import struct
import sys
import time
import zlib
from pathlib import Path


def canonical_hash(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def chunk(kind, data):
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xffffffff
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png(width, height):
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            if x == 0 and y == 0:
                raw.extend((255, 0, 0, 255))
            else:
                raw.extend((0, 0, 0, 0))
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")

args = sys.argv[1:]
if "--" in args:
    args = args[args.index("--") + 1:]
request_path = Path(args[args.index("--origin-forge-request") + 1])
result_path = Path(args[args.index("--origin-forge-result") + 1])
request = json.loads(request_path.read_text(encoding="utf-8"))
mode = Path(__file__).stem
if "timeout" in mode:
    time.sleep(5)

fingerprint = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
outputs = []
status = "SUCCEEDED"
if "failed" in mode:
    status = "FAILED"
else:
    spec = request["sprite_spec"]
    project = Path("project") / (spec["output_basename"] + ".pxo")
    project.write_bytes(b"fake pixelorama project\n")
    outputs.append({
        "output_type": "PIXELORAMA_PROJECT",
        "relative_path": project.as_posix(),
        "content_hash": "sha256:" + hashlib.sha256(project.read_bytes()).hexdigest(),
        "byte_count": project.stat().st_size,
        "width": None,
        "height": None,
    })
    for export in request["export_specs"]:
        target = Path(export["relative_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        data = png(spec["width"], spec["height"])
        target.write_bytes(data)
        outputs.append({
            "output_type": export["output_type"],
            "relative_path": export["relative_path"],
            "content_hash": "sha256:" + hashlib.sha256(data).hexdigest(),
            "byte_count": len(data),
            "width": spec["width"],
            "height": spec["height"],
        })
    if "undeclared" in mode:
        Path("unexpected.txt").write_text("unexpected", encoding="utf-8")

result = {
    "protocol_version": 1,
    "operation_id": request["operation_id"],
    "request_hash": request["content_hash"],
    "status": status,
    "pixelorama_version": "fake-pixelorama",
    "bridge_version": "test-bridge-1",
    "bridge_fingerprint": fingerprint,
    "outputs": outputs if status == "SUCCEEDED" else [],
    "diagnostics": [],
    "elapsed_ms": 1,
}
if "wrong-request" in mode:
    result["request_hash"] = "sha256:" + "0" * 64
if "extra-field" in mode:
    result["approved"] = True
result["content_hash"] = canonical_hash(result)
result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
print("bridge stdout " + "x" * 5000)
print("bridge stderr " + "y" * 5000, file=sys.stderr)
if "nonzero" in mode:
    raise SystemExit(7)
'''


class PixeloramaBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-bridge-test")
        self.tools = self.root / "tools"
        self.tools.mkdir()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _script(self, name: str = "fake_bridge.py") -> Path:
        path = self.tools / name
        path.write_text(textwrap.dedent(FAKE_BRIDGE), encoding="utf-8")
        return path

    @staticmethod
    def _hash(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def _profile(self, script: Path, **overrides) -> PixeloramaBridgeProfile:
        values = dict(
            bridge_id="origin-forge-pixelorama-test",
            bridge_version="test-bridge-1",
            bridge_fingerprint=self._hash(script),
            pixelorama_executable=Path(sys.executable).resolve(),
            bridge_package=script,
            allowed_operations=(BridgeOperation.CREATE_SPRITE_PROJECT,),
            launcher_args=(str(script),),
            timeout_seconds=3,
            max_stdout_bytes=128,
            max_stderr_bytes=128,
        )
        values.update(overrides)
        return PixeloramaBridgeProfile(**values)

    @staticmethod
    def _spec() -> SpriteProjectSpec:
        return SpriteProjectSpec(
            2,
            2,
            (RasterLayerSpec("base", "Base"),),
            (FrameSpec("frame-0"),),
            output_basename="test-sprite",
        )

    def _request(self, **kwargs) -> PixeloramaBridgeRequest:
        values = dict(
            operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            sprite_spec=self._spec(),
            export_specs=(ExportSpec(BridgeOutputType.PNG, "exports/frame.png"),),
            budget=BridgeBudget(timeout_seconds=2),
        )
        values.update(kwargs)
        return PixeloramaBridgeRequest.create(**values)

    def test_successful_one_shot_bridge_validates_exact_outputs_and_bounds_logs(self) -> None:
        script = self._script()
        adapter = PixeloramaBridgeAdapter(self.runtime, self._profile(script))
        result = adapter.execute(self._request())
        self.assertTrue(result.succeeded)
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)
        self.assertLessEqual(len(result.stdout), 128)
        self.assertLessEqual(len(result.stderr), 128)
        self.assertEqual(
            {value.relative_path for value in result.bridge_result.outputs},
            {"project/test-sprite.pxo", "exports/frame.png"},
        )
        self.assertFalse(result.to_dict()["production_verification_changed"])
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])
        self.assertTrue((result.workspace_path / "request.json").is_file())
        self.assertTrue((result.workspace_path / "result.json").is_file())

    def test_bridge_fingerprint_mismatch_fails_before_process_launch(self) -> None:
        script = self._script()
        profile = self._profile(script, bridge_fingerprint="sha256:" + "0" * 64)
        adapter = PixeloramaBridgeAdapter(self.runtime, profile)
        with patch("origin_forge.pixelorama_bridge.subprocess.Popen") as popen:
            with self.assertRaisesRegex(PixeloramaBridgeIntegrityError, "fingerprint mismatch"):
                adapter.execute(self._request())
            popen.assert_not_called()

    def test_disallowed_operation_fails_before_launch(self) -> None:
        script = self._script()
        adapter = PixeloramaBridgeAdapter(self.runtime, self._profile(script))
        request = PixeloramaBridgeRequest.create(
            operation=BridgeOperation.SAVE_PROJECT,
        )
        with patch("origin_forge.pixelorama_bridge.subprocess.Popen") as popen:
            with self.assertRaisesRegex(PixeloramaBridgeUnavailable, "not allowed"):
                adapter.execute(request)
            popen.assert_not_called()

    def test_staged_input_must_exactly_match_frozen_hash_and_size(self) -> None:
        script = self._script()
        source = self.root / "input.png"
        source.write_bytes(b"source")
        request = self._request(
            input_refs=(
                BridgeInputRef(
                    "inputs/source.png",
                    "sha256:" + hashlib.sha256(b"different").hexdigest(),
                    len(b"source"),
                ),
            ),
        )
        adapter = PixeloramaBridgeAdapter(self.runtime, self._profile(script))
        with patch("origin_forge.pixelorama_bridge.subprocess.Popen") as popen:
            with self.assertRaisesRegex(PixeloramaBridgeIntegrityError, "does not match frozen"):
                adapter.execute(
                    request,
                    staged_inputs={"inputs/source.png": source},
                )
            popen.assert_not_called()

    def test_timeout_is_bounded_and_produces_no_adopted_result(self) -> None:
        script = self._script("timeout_bridge.py")
        adapter = PixeloramaBridgeAdapter(
            self.runtime,
            self._profile(script, timeout_seconds=1),
        )
        request = self._request(budget=BridgeBudget(timeout_seconds=1))
        with self.assertRaisesRegex(PixeloramaBridgeUnavailable, "exceeded timeout"):
            adapter.execute(request)

    def test_strict_result_binding_and_extra_fields_fail_closed(self) -> None:
        for name, message in (
            ("wrong-request_bridge.py", "request hash mismatch"),
            ("extra-field_bridge.py", "result validation failed"),
        ):
            with self.subTest(name=name):
                script = self._script(name)
                runtime_root = self.root / name.replace(".py", "")
                runtime = OriginForgeRuntime(runtime_root)
                runtime.initialize("subcase")
                adapter = PixeloramaBridgeAdapter(runtime, self._profile(script))
                with self.assertRaisesRegex(PixeloramaBridgeIntegrityError, message):
                    adapter.execute(self._request())

    def test_undeclared_file_and_nonzero_success_are_rejected(self) -> None:
        for name, message in (
            ("undeclared_bridge.py", "undeclared files"),
            ("nonzero_bridge.py", "non-zero process exit"),
        ):
            with self.subTest(name=name):
                script = self._script(name)
                runtime_root = self.root / name.replace(".py", "")
                runtime = OriginForgeRuntime(runtime_root)
                runtime.initialize("subcase")
                adapter = PixeloramaBridgeAdapter(runtime, self._profile(script))
                with self.assertRaisesRegex(PixeloramaBridgeIntegrityError, message):
                    adapter.execute(self._request())

    def test_failed_bridge_status_is_preserved_as_advisory_process_evidence(self) -> None:
        script = self._script("failed_bridge.py")
        adapter = PixeloramaBridgeAdapter(self.runtime, self._profile(script))
        result = adapter.execute(self._request())
        self.assertFalse(result.succeeded)
        self.assertEqual(result.bridge_result.status.value, "FAILED")
        self.assertEqual(result.bridge_result.outputs, ())

    def test_subprocess_is_never_launched_with_a_shell(self) -> None:
        script = self._script()
        adapter = PixeloramaBridgeAdapter(self.runtime, self._profile(script))
        with patch(
            "origin_forge.pixelorama_bridge.subprocess.Popen",
            side_effect=OSError("stop after call capture"),
        ) as popen:
            with self.assertRaises(PixeloramaBridgeUnavailable):
                adapter.execute(self._request())
        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_adapter_has_no_model_task_merge_release_or_plugin_install_surface(self) -> None:
        script = self._script()
        adapter = PixeloramaBridgeAdapter(self.runtime, self._profile(script))
        for forbidden in (
            "model",
            "generate",
            "run_script",
            "install_plugin",
            "download_extension",
            "verify_task",
            "transition_task",
            "merge",
            "release",
            "sign",
        ):
            self.assertFalse(hasattr(adapter, forbidden))


if __name__ == "__main__":
    unittest.main()
