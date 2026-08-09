from __future__ import annotations

import hashlib
import json
import os
import urllib.request
import unittest
from pathlib import Path

from origin_forge.adapters.llamacpp_vision import LlamaCppVisionAdapter
from origin_forge.image_vision_models import VisionImageRef, VisionInspectionRequest
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png, inspect_rgba8_png


class RealLlamaCppVisionIntegrationTests(unittest.TestCase):
    def _required_env(self) -> dict[str, str]:
        names = (
            "ORIGIN_FORGE_VISION_REAL_URL",
            "ORIGIN_FORGE_VISION_MODEL_ID",
            "ORIGIN_FORGE_VISION_MODEL_FILE",
            "ORIGIN_FORGE_VISION_MODEL_SHA256",
            "ORIGIN_FORGE_VISION_PROJECTOR_FILE",
            "ORIGIN_FORGE_VISION_PROJECTOR_SHA256",
            "ORIGIN_FORGE_VISION_RUNTIME_COMMIT",
        )
        values = {name: os.environ.get(name, "").strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            self.skipTest(
                "real llama.cpp vision runtime/model/projector external pins not configured"
            )
        return values

    @staticmethod
    def _verify_file(path: Path, expected_sha256: str, label: str) -> bytes:
        if not path.is_file() or path.is_symlink():
            raise AssertionError(f"{label} must be a regular non-symlink file")
        data = path.read_bytes()
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual != expected_sha256:
            raise AssertionError(f"{label} SHA-256 mismatch: {actual}")
        return data

    @staticmethod
    def _synthetic_request(env: dict[str, str]) -> tuple[bytes, VisionInspectionRequest]:
        width = 32
        height = 32
        pixels = bytearray([20, 20, 20, 255] * (width * height))
        for y in range(8, 24):
            for x in range(8, 24):
                index = (y * width + x) * 4
                pixels[index : index + 4] = bytes((220, 20, 20, 255))
        png = encode_rgba8_png(PixelPlane(width, height, bytes(pixels)))
        inspection = inspect_rgba8_png(png)
        ref = VisionImageRef(
            image_id="synthetic",
            content_hash="sha256:" + hashlib.sha256(png).hexdigest(),
            pixel_hash=inspection.pixel_hash,
            byte_count=len(png),
            width=inspection.width,
            height=inspection.height,
        )
        request = VisionInspectionRequest.create(
            images=(ref,),
            objective=(
                "Inspect the supplied synthetic image. Return only the required JSON. "
                "Describe obvious visible structure; do not claim verification or acceptance."
            ),
            criteria=("composition", "artifact"),
            expected_model_id=env["ORIGIN_FORGE_VISION_MODEL_ID"],
            expected_model_hash=env["ORIGIN_FORGE_VISION_MODEL_SHA256"],
            max_output_tokens=256,
        )
        return png, request

    @staticmethod
    def _capture_raw_completion(
        adapter: LlamaCppVisionAdapter,
        request: VisionInspectionRequest,
        png: bytes,
    ) -> str:
        images = adapter._validate_image_bytes(
            request,
            {"synthetic": png},
            max_total_image_bytes=adapter.settings.max_total_image_bytes,
        )
        body = json.dumps(
            adapter._payload(request, images), separators=(",", ":")
        ).encode("utf-8")
        http_request = urllib.request.Request(
            f"{adapter.settings.base_url}/v1/chat/completions",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(
            http_request, timeout=adapter.settings.timeout_seconds
        ) as response:
            raw = response.read(adapter.settings.max_response_bytes + 1)
        if len(raw) > adapter.settings.max_response_bytes:
            raise AssertionError("diagnostic vision completion exceeded response bound")
        value = json.loads(raw)
        content = value["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise AssertionError("diagnostic vision completion content is not text")
        bounded = content.encode("utf-8")[:16384]
        evidence_path = os.environ.get(
            "ORIGIN_FORGE_VISION_RESPONSE_EVIDENCE", ""
        ).strip()
        if evidence_path:
            Path(evidence_path).write_bytes(bounded)
        print("ORIGIN_FORGE_VISION_RAW_RESPONSE=" + repr(bounded.decode("utf-8", errors="replace")))
        return content

    def test_real_pinned_llamacpp_smolvlm_returns_advisory_structured_report(self) -> None:
        env = self._required_env()
        model_path = Path(env["ORIGIN_FORGE_VISION_MODEL_FILE"])
        projector_path = Path(env["ORIGIN_FORGE_VISION_PROJECTOR_FILE"])
        self._verify_file(
            model_path,
            env["ORIGIN_FORGE_VISION_MODEL_SHA256"],
            "vision model",
        )
        self._verify_file(
            projector_path,
            env["ORIGIN_FORGE_VISION_PROJECTOR_SHA256"],
            "vision projector",
        )
        self.assertEqual(
            env["ORIGIN_FORGE_VISION_RUNTIME_COMMIT"],
            "aedb2a5e9ca3d4064148bbb919e0ddc0c1b70ab3",
        )

        png, request = self._synthetic_request(env)
        adapter = LlamaCppVisionAdapter(
            base_url=env["ORIGIN_FORGE_VISION_REAL_URL"],
            model=env["ORIGIN_FORGE_VISION_MODEL_ID"],
            model_hash=env["ORIGIN_FORGE_VISION_MODEL_SHA256"],
            timeout_seconds=120,
            temperature=0.0,
            max_response_bytes=1024 * 1024,
            max_total_image_bytes=1024 * 1024,
        )

        # Synthetic-input-only diagnostic evidence. The strict adapter call below
        # remains the actual integration gate and is not relaxed by this capture.
        self._capture_raw_completion(adapter, request, png)

        report = adapter.inspect(request, {"synthetic": png})
        report.bind_request(request)
        self.assertTrue(report.advisory_only)
        self.assertFalse(report.semantic_findings_verified)
        self.assertEqual(report.model_hash, env["ORIGIN_FORGE_VISION_MODEL_SHA256"])
        self.assertTrue(
            all(finding.image_id == "synthetic" for finding in report.findings)
        )


if __name__ == "__main__":
    unittest.main()
