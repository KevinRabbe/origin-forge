from __future__ import annotations

import hashlib
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from origin_forge.blockbench_bridge import (
    BlockbenchBridgeAdapter,
    BlockbenchBridgeIntegrityError,
    BlockbenchBridgeProfile,
    BlockbenchBridgeUnavailable,
)
from origin_forge.blockbench_models import (
    BlockbenchBridgeRequest,
    BlockbenchOperation,
    BlockbenchProjectSpec,
    BoneSpec,
    CuboidSpec,
    Vec3,
)
from origin_forge.runtime import OriginForgeRuntime


FAKE_BRIDGE = r'''#!/usr/bin/env python3
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if len(args) != 4 or args[0] != "--request" or args[2] != "--result":
    raise SystemExit(9)
request_path = Path(args[1])
result_path = Path(args[3])
request = json.loads(request_path.read_text(encoding="utf-8"))
mode = Path(__file__).stem
if "timeout" in mode:
    time.sleep(5)

root = {
    "asset": {"version": "2.0", "generator": "fake-blockbench-bridge"},
    "scene": 0,
    "scenes": [{"nodes": [0]}],
    "nodes": [{"name": "Root", "mesh": 0}],
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
    "accessors": [{"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}],
    "bufferViews": [{"buffer": 0, "byteLength": 12}],
    "buffers": [{"byteLength": 12}],
}
json_payload = json.dumps(root, separators=(",", ":")).encode("utf-8")
while len(json_payload) % 4:
    json_payload += b" "
bin_payload = b"\x00" * 12
json_chunk = struct.pack("<II", len(json_payload), 0x4E4F534A) + json_payload
bin_chunk = struct.pack("<II", len(bin_payload), 0x004E4942) + bin_payload
glb = b"glTF" + struct.pack("<II", 2, 12 + len(json_chunk) + len(bin_chunk)) + json_chunk + bin_chunk
if "invalid" in mode:
    glb = b"not-a-glb"

workspace = request_path.parent.parent
output = workspace / request["output_relative_path"]
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(glb)
if "extra" in mode:
    (output.parent / "extra.glb").write_bytes(glb)

digest = "sha256:" + hashlib.sha256(glb).hexdigest()
result = {
    "protocol_version": 1,
    "operation_id": request["operation_id"],
    "workspace_id": request["workspace_id"],
    "request_hash": request["content_hash"],
    "status": "SUCCEEDED",
    "blockbench_version": request["expected_blockbench_version"],
    "bridge_fingerprint": request["bridge_fingerprint"],
    "outputs": [{
        "output_type": "GLB",
        "relative_path": request["output_relative_path"],
        "content_hash": digest,
        "byte_count": len(glb),
    }],
    "diagnostics": [],
}
if "wrong_result" in mode:
    result["task_verified"] = True
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(json.dumps(result), encoding="utf-8")
'''


@unittest.skipIf(os.name == "nt", "fake shebang bridge is POSIX-only")
class BlockbenchBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("blockbench-bridge-test")
        self.tools = self.root / "tools"
        self.tools.mkdir()
        project = BlockbenchProjectSpec(
            project_name="crate",
            bones=(BoneSpec("root", "Root", Vec3(0, 0, 0)),),
            cuboids=(
                CuboidSpec(
                    element_id="crate",
                    name="Crate",
                    from_point=Vec3(0, 0, 0),
                    to_point=Vec3(2, 2, 2),
                    origin=Vec3(1, 1, 1),
                    parent_bone_id="root",
                ),
            ),
        )
        self.project = project

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _bridge(self, name: str = "fake_blockbench_bridge") -> Path:
        path = self.tools / name
        path.write_text(textwrap.dedent(FAKE_BRIDGE), encoding="utf-8")
        path.chmod(0o755)
        return path

    @staticmethod
    def _hash(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def _profile(self, bridge: Path, **overrides) -> BlockbenchBridgeProfile:
        values = dict(
            bridge_executable=bridge,
            bridge_fingerprint=self._hash(bridge),
            expected_blockbench_version="5.1.4",
        )
        values.update(overrides)
        return BlockbenchBridgeProfile(**values)

    def _request(self, fingerprint: str, timeout: int = 2) -> BlockbenchBridgeRequest:
        from origin_forge.blockbench_models import BlockbenchBridgeBudget

        return BlockbenchBridgeRequest.create(
            operation=BlockbenchOperation.EXPORT_GLB,
            project=self.project,
            output_relative_path="exports/model.glb",
            bridge_fingerprint=fingerprint,
            expected_blockbench_version="5.1.4",
            budget=BlockbenchBridgeBudget(timeout_seconds=timeout),
        )

    def test_successful_one_shot_bridge_rehashes_and_reinspects_glb(self) -> None:
        bridge = self._bridge()
        profile = self._profile(bridge)
        before_runs = self.runtime.list_runs()
        execution = BlockbenchBridgeAdapter(self.runtime, profile).execute(
            self._request(profile.bridge_fingerprint)
        )
        self.assertEqual(execution.result.status.value, "SUCCEEDED")
        self.assertTrue(
            (execution.workspace_path / "exports" / "model.glb").is_file()
        )
        self.assertFalse(execution.to_dict()["production_verification_changed"])
        self.assertFalse(execution.to_dict()["canonical_asset_adopted"])
        self.assertEqual(self.runtime.list_runs(), before_runs)

    def test_bridge_fingerprint_mismatch_fails_before_launch(self) -> None:
        bridge = self._bridge()
        profile = self._profile(bridge)
        with self.assertRaisesRegex(BlockbenchBridgeIntegrityError, "fingerprint"):
            BlockbenchBridgeAdapter(self.runtime, profile).execute(
                self._request("sha256:" + "0" * 64)
            )

    def test_undeclared_output_and_invalid_glb_fail_closed(self) -> None:
        extra = self._bridge("extra_blockbench_bridge")
        profile = self._profile(extra)
        with self.assertRaisesRegex(BlockbenchBridgeIntegrityError, "declared outputs"):
            BlockbenchBridgeAdapter(self.runtime, profile).execute(
                self._request(profile.bridge_fingerprint)
            )

        invalid = self._bridge("invalid_blockbench_bridge")
        runtime = OriginForgeRuntime(self.root / "invalid-case")
        runtime.initialize("invalid")
        profile = self._profile(invalid)
        with self.assertRaisesRegex(BlockbenchBridgeIntegrityError, "GLB output"):
            BlockbenchBridgeAdapter(runtime, profile).execute(
                self._request(profile.bridge_fingerprint)
            )

    def test_extra_authority_result_field_fails_strict_binding(self) -> None:
        bridge = self._bridge("wrong_result_blockbench_bridge")
        profile = self._profile(bridge)
        with self.assertRaisesRegex(BlockbenchBridgeIntegrityError, "strict binding"):
            BlockbenchBridgeAdapter(self.runtime, profile).execute(
                self._request(profile.bridge_fingerprint)
            )

    def test_timeout_is_bounded(self) -> None:
        bridge = self._bridge("timeout_blockbench_bridge")
        profile = self._profile(bridge)
        with self.assertRaisesRegex(BlockbenchBridgeUnavailable, "exceeded timeout"):
            BlockbenchBridgeAdapter(self.runtime, profile).execute(
                self._request(profile.bridge_fingerprint, timeout=1)
            )

    def test_adapter_has_no_task_model_merge_release_or_plugin_install_surface(self) -> None:
        bridge = self._bridge()
        adapter = BlockbenchBridgeAdapter(self.runtime, self._profile(bridge))
        for forbidden in (
            "verify_task",
            "transition_task",
            "model",
            "generate",
            "merge",
            "release",
            "install_plugin",
            "download",
        ):
            self.assertFalse(hasattr(adapter, forbidden))


if __name__ == "__main__":
    unittest.main()
