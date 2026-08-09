from __future__ import annotations

import hashlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from origin_forge.adapters.llamacpp_vision import (
    LLAMA_CPP_VISION_REPORT_SCHEMA,
    LlamaCppVisionAdapter,
    LlamaCppVisionError,
)
from origin_forge.image_vision_models import VISION_REPORT_SCHEMA, VisionImageRef, VisionInspectionRequest
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png, inspect_rgba8_png


MODEL_HASH = "sha256:" + "d" * 64


def _fixture() -> tuple[bytes, VisionInspectionRequest]:
    png = encode_rgba8_png(PixelPlane(2, 2, bytes([255, 0, 0, 255] * 4)))
    inspection = inspect_rgba8_png(png)
    ref = VisionImageRef(
        image_id="concept",
        content_hash="sha256:" + hashlib.sha256(png).hexdigest(),
        pixel_hash=inspection.pixel_hash,
        byte_count=len(png),
        width=inspection.width,
        height=inspection.height,
    )
    request = VisionInspectionRequest.create(
        images=(ref,),
        objective="Inspect silhouette readability",
        criteria=("readability", "artifacts"),
        expected_model_id="vision-model",
        expected_model_hash=MODEL_HASH,
        max_output_tokens=512,
    )
    return png, request


class _VisionHandler(BaseHTTPRequestHandler):
    request_json = None
    hits = 0

    def do_POST(self):
        type(self).hits += 1
        length = int(self.headers["Content-Length"])
        type(self).request_json = json.loads(self.rfile.read(length))
        body = json.dumps(
            {
                "model": "vision-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "summary": "Readable.",
                                    "findings": [
                                        {
                                            "category": "readability",
                                            "severity": "LOW",
                                            "image_id": "concept",
                                            "description": "Minor silhouette crowding.",
                                        }
                                    ],
                                }
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 20},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class LlamaCppVisionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        _VisionHandler.request_json = None
        _VisionHandler.hits = 0

    def test_remote_endpoint_requires_explicit_opt_in(self) -> None:
        with self.assertRaises(ValueError):
            LlamaCppVisionAdapter(
                base_url="https://example.com",
                model="vision-model",
                model_hash=MODEL_HASH,
            )

    def test_valid_png_is_rehashed_then_sent_as_schema_constrained_multimodal_input(self) -> None:
        png, request = _fixture()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _VisionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = LlamaCppVisionAdapter(
                base_url=f"http://127.0.0.1:{server.server_port}",
                model="vision-model",
                model_hash=MODEL_HASH,
                timeout_seconds=2,
            )
            report = adapter.inspect(request, {"concept": png})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertTrue(report.advisory_only)
        self.assertFalse(report.semantic_findings_verified)
        self.assertEqual(report.input_tokens, 40)
        self.assertEqual(report.output_tokens, 20)
        payload = _VisionHandler.request_json
        self.assertEqual(payload["response_format"]["type"], "json_object")
        self.assertEqual(
            payload["response_format"]["schema"], LLAMA_CPP_VISION_REPORT_SCHEMA
        )
        self.assertEqual(
            LLAMA_CPP_VISION_REPORT_SCHEMA["properties"]["summary"]["maxLength"],
            1024,
        )
        self.assertEqual(
            LLAMA_CPP_VISION_REPORT_SCHEMA["properties"]["findings"]["items"]["properties"]["description"]["maxLength"],
            1024,
        )
        self.assertEqual(VISION_REPORT_SCHEMA["properties"]["summary"]["maxLength"], 8192)
        self.assertEqual(
            VISION_REPORT_SCHEMA["properties"]["findings"]["items"]["properties"]["description"]["maxLength"],
            4096,
        )
        self.assertFalse(payload["stream"])
        user_content = payload["messages"][1]["content"]
        urls = [
            item["image_url"]["url"]
            for item in user_content
            if item.get("type") == "image_url"
        ]
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].startswith("data:image/png;base64,"))

    def test_image_drift_fails_before_model_request(self) -> None:
        png, request = _fixture()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _VisionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = LlamaCppVisionAdapter(
                base_url=f"http://127.0.0.1:{server.server_port}",
                model="vision-model",
                model_hash=MODEL_HASH,
                timeout_seconds=2,
            )
            with self.assertRaises(LlamaCppVisionError):
                adapter.inspect(request, {"concept": png + b"drift"})
            self.assertEqual(_VisionHandler.hits, 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_exact_image_set_and_model_identity_are_mandatory(self) -> None:
        png, request = _fixture()
        adapter = LlamaCppVisionAdapter(
            model="vision-model",
            model_hash=MODEL_HASH,
            timeout_seconds=0.1,
        )
        with self.assertRaises(LlamaCppVisionError):
            adapter.inspect(request, {})
        wrong_model = VisionInspectionRequest(
            inspection_id=request.inspection_id,
            images=request.images,
            objective=request.objective,
            criteria=request.criteria,
            expected_model_id="other-model",
            expected_model_hash=request.expected_model_hash,
            max_output_tokens=request.max_output_tokens,
        )
        with self.assertRaises(LlamaCppVisionError):
            adapter.inspect(wrong_model, {"concept": png})

    def test_model_cannot_return_verification_authority_field(self) -> None:
        class AuthorityHandler(_VisionHandler):
            def do_POST(self):
                type(self).hits += 1
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                content = json.dumps(
                    {"summary": "ok", "findings": [], "verified": True}
                )
                body = json.dumps(
                    {
                        "model": "vision-model",
                        "choices": [{"message": {"content": content}}],
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        png, request = _fixture()
        server = ThreadingHTTPServer(("127.0.0.1", 0), AuthorityHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = LlamaCppVisionAdapter(
                base_url=f"http://127.0.0.1:{server.server_port}",
                model="vision-model",
                model_hash=MODEL_HASH,
                timeout_seconds=2,
            )
            with self.assertRaises(LlamaCppVisionError):
                adapter.inspect(request, {"concept": png})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
