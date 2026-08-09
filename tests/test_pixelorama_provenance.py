from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from origin_forge.pixelorama_bridge import PixeloramaBridgeProfile
from origin_forge.pixelorama_media import PixeloramaMediaService, PixeloramaOutputAdopter
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
from origin_forge.provenance_crypto import OpenSslEd25519Backend
from origin_forge.provenance_service import ProvenanceService
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, TaskStatus


BRIDGE = r'''import binascii
import hashlib
import json
import struct
import sys
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
outputs = [{
    "output_type": "PIXELORAMA_PROJECT",
    "relative_path": project.as_posix(),
    "content_hash": "sha256:" + hashlib.sha256(project.read_bytes()).hexdigest(),
    "byte_count": project.stat().st_size,
    "width": None,
    "height": None,
}]
for export in request["export_specs"]:
    path = Path(export["relative_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    data = png(spec["width"], spec["height"])
    path.write_bytes(data)
    outputs.append({
        "output_type": export["output_type"],
        "relative_path": path.as_posix(),
        "content_hash": "sha256:" + hashlib.sha256(data).hexdigest(),
        "byte_count": len(data),
        "width": spec["width"],
        "height": spec["height"],
    })
outputs.sort(key=lambda value: value["relative_path"])
result = {
    "protocol_version": 1,
    "operation_id": request["operation_id"],
    "request_hash": request["content_hash"],
    "status": "SUCCEEDED",
    "pixelorama_version": "fake-pixelorama",
    "bridge_version": "test-bridge-1",
    "bridge_fingerprint": fingerprint,
    "outputs": outputs,
    "diagnostics": [],
    "elapsed_ms": 1,
}
result["content_hash"] = canonical_hash(result)
result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
'''


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for provenance integration")
class PixeloramaProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_temp = tempfile.TemporaryDirectory()
        self.secret_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.project_temp.name)
        self.secret_root = Path(self.secret_temp.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-provenance-test")
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.bridge = self.tools / "bridge.py"
        self.bridge.write_text(textwrap.dedent(BRIDGE), encoding="utf-8")
        self.profile = PixeloramaBridgeProfile(
            bridge_id="origin-forge-pixelorama-test",
            bridge_version="test-bridge-1",
            bridge_fingerprint="sha256:" + hashlib.sha256(self.bridge.read_bytes()).hexdigest(),
            pixelorama_executable=Path(sys.executable).resolve(),
            bridge_package=self.bridge,
            allowed_operations=(BridgeOperation.CREATE_SPRITE_PROJECT,),
            launcher_args=(str(self.bridge),),
            timeout_seconds=5,
        )
        self.goal = self.runtime.create_goal("Create signed 2D asset")
        self.flow = self.runtime.create_flow(self.goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "Create sprite")
        revision = self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(self.task, TaskStatus.RUNNING, expected_revision=revision)
        self.root_key = self._key("root.pem")
        self.operational_key = self._key("operational.pem")

    def tearDown(self) -> None:
        self.project_temp.cleanup()
        self.secret_temp.cleanup()

    def _key(self, name: str) -> Path:
        path = self.secret_root / name
        openssl = shutil.which("openssl")
        assert openssl is not None
        subprocess.run(
            [openssl, "genpkey", "-algorithm", "ED25519", "-out", str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if os.name != "nt":
            path.chmod(0o600)
        return path

    @staticmethod
    def _request() -> PixeloramaBridgeRequest:
        spec = SpriteProjectSpec(
            2,
            2,
            (RasterLayerSpec("base", "Base"),),
            (FrameSpec("idle-0"),),
            output_basename="signed-sprite",
        )
        return PixeloramaBridgeRequest.create(
            operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            sprite_spec=spec,
            export_specs=(ExportSpec(BridgeOutputType.PNG, "exports/frame.png"),),
            budget=BridgeBudget(timeout_seconds=5),
        )

    def test_adopted_png_can_be_signed_by_phase18_without_media_key_access(self) -> None:
        media = PixeloramaMediaService(self.runtime, self.profile).execute(
            self.task,
            self._request(),
        )
        source = next(
            value for value in media.output_evidence if value.output_type == BridgeOutputType.PNG
        )
        adopted = PixeloramaOutputAdopter(self.runtime).adopt_new(
            source.artifact_id,
            "assets/sprites/signed-sprite.png",
        )
        task_before_signing = self.runtime.get_task(self.task)

        backend = OpenSslEd25519Backend(self.root)
        provenance = ProvenanceService(self.runtime, backend=backend)
        root_identity = provenance.trust_root_public(
            "Origin Forge Test",
            backend.public_key_der(self.root_key),
            created_at="2026-08-08T20:00:00Z",
        )
        certificate = provenance.issue_operational_certificate(
            backend.public_key_der(self.operational_key),
            root_private_key_handle=self.root_key,
            issued_at="2026-08-08T20:01:00Z",
        )
        signed = provenance.sign_artifact(
            adopted.adopted_artifact_id,
            certificate.certificate.certificate_id,
            operational_private_key_handle=self.operational_key,
            created_at="2026-08-08T20:02:00Z",
        )
        inspection = provenance.verify_manifest(signed.manifest.manifest_id)

        self.assertTrue(inspection.cryptographic.trusted)
        self.assertTrue(inspection.freshness.current)
        self.assertEqual(signed.manifest.artifact_ref.record_id, adopted.adopted_artifact_id)
        self.assertEqual(signed.manifest.artifact_content_hash, adopted.content_hash)
        self.assertEqual(self.runtime.get_task(self.task), task_before_signing)
        self.assertEqual(provenance.store.load_root(root_identity.company_id), root_identity)

        media_service = PixeloramaMediaService(self.runtime, self.profile)
        adopter = PixeloramaOutputAdopter(self.runtime)
        for obj in (media_service, adopter):
            for forbidden in (
                "private_key",
                "sign",
                "issue_operational_certificate",
                "revoke_operational_certificate",
                "trust_root_public",
            ):
                self.assertFalse(hasattr(obj, forbidden))


if __name__ == "__main__":
    unittest.main()
