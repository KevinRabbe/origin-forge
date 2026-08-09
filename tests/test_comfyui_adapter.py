from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from origin_forge.adapters.comfyui import (
    ComfyBinding,
    ComfyUiAdapter,
    ComfyUiIntegrityError,
    ComfyUiProfile,
    ComfyWorkflowBindings,
    ComfyWorkflowTemplate,
)
from origin_forge.image_vision_models import ImageOperation, ImageOperationRequest
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png, inspect_rgba8_png
from origin_forge.runtime import OriginForgeRuntime


MODEL_HASH = "sha256:" + "e" * 64
VERSION = "0.9.1-test"


def _workflow() -> dict[str, object]:
    return {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 0, "steps": 1, "cfg": 1.0},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 16, "height": 16},
        },
        "5": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "placeholder"},
        },
    }


def _template() -> ComfyWorkflowTemplate:
    return ComfyWorkflowTemplate(
        workflow_id="concept-v1",
        backend_version=VERSION,
        model_id="local-image-model",
        model_hash=MODEL_HASH,
        workflow=_workflow(),
        bindings=ComfyWorkflowBindings(
            positive_prompt=ComfyBinding("1", "text"),
            negative_prompt=ComfyBinding("2", "text"),
            seed=ComfyBinding("3", "seed"),
            steps=ComfyBinding("3", "steps"),
            guidance=ComfyBinding("3", "cfg"),
            width=ComfyBinding("4", "width"),
            height=ComfyBinding("4", "height"),
            output_prefix=ComfyBinding("5", "filename_prefix"),
        ),
        output_node_id="5",
    )


def _request(template: ComfyWorkflowTemplate) -> ImageOperationRequest:
    return ImageOperationRequest.create(
        operation=ImageOperation.GENERATE,
        backend_id="comfyui",
        backend_version=VERSION,
        workflow_id=template.workflow_id,
        workflow_hash=template.workflow_hash,
        model_id=template.model_id,
        model_hash=template.model_hash,
        prompt="slow armored factory enemy with a mechanical hammer",
        negative_prompt="text artifacts",
        width=16,
        height=16,
        seed=123,
        steps=7,
        guidance_scale=4.5,
        output_relative_paths=("exports/concept.png",),
    )


class _ComfyHandler(BaseHTTPRequestHandler):
    expected_version = VERSION
    output_png = encode_rgba8_png(
        PixelPlane(16, 16, bytes([10, 20, 30, 255] * (16 * 16)))
    )
    queued_payload = None
    prompt_id = None
    system_stats_hits = 0
    prompt_hits = 0
    history_hits = 0
    view_hits = 0

    @classmethod
    def reset(cls) -> None:
        cls.expected_version = VERSION
        cls.output_png = encode_rgba8_png(
            PixelPlane(16, 16, bytes([10, 20, 30, 255] * (16 * 16)))
        )
        cls.queued_payload = None
        cls.prompt_id = None
        cls.system_stats_hits = 0
        cls.prompt_hits = 0
        cls.history_hits = 0
        cls.view_hits = 0

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/system_stats":
            type(self).system_stats_hits += 1
            self._json({"system": {"comfyui_version": type(self).expected_version}})
            return
        if parsed.path.startswith("/history/"):
            type(self).history_hits += 1
            prompt_id = parsed.path.rsplit("/", 1)[-1]
            self._json(
                {
                    prompt_id: {
                        "outputs": {
                            "5": {
                                "images": [
                                    {
                                        "filename": "generated.png",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        }
                    }
                }
            )
            return
        if parsed.path == "/view":
            type(self).view_hits += 1
            query = parse_qs(parsed.query)
            if (
                query.get("filename") != ["generated.png"]
                or query.get("type") != ["output"]
            ):
                self.send_response(400)
                self.end_headers()
                return
            body = type(self).output_png
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/prompt":
            self.send_response(404)
            self.end_headers()
            return
        type(self).prompt_hits += 1
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        type(self).queued_payload = payload
        type(self).prompt_id = payload.get("prompt_id")
        self._json(
            {
                "prompt_id": payload.get("prompt_id"),
                "number": 1,
                "node_errors": {},
            }
        )

    def log_message(self, format, *args):
        pass


class ComfyUiAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        _ComfyHandler.reset()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("comfy-test")
        self.template = _template()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ComfyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _adapter(self, server: ThreadingHTTPServer) -> ComfyUiAdapter:
        return ComfyUiAdapter(
            self.runtime,
            ComfyUiProfile(
                base_url=f"http://127.0.0.1:{server.server_port}",
                expected_version=VERSION,
                request_timeout_seconds=2,
                poll_interval_seconds=0.01,
            ),
            self.template,
        )

    def test_remote_endpoint_requires_explicit_opt_in(self) -> None:
        with self.assertRaises(ValueError):
            ComfyUiProfile(
                base_url="https://example.com",
                expected_version=VERSION,
            )

    def test_trusted_workflow_bindings_drive_generation_and_output_is_reinspected(self) -> None:
        request = _request(self.template)
        server, thread = self._server()
        try:
            execution = self._adapter(server).execute(request)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        payload = _ComfyHandler.queued_payload
        self.assertIsInstance(payload, dict)
        workflow = payload["prompt"]
        self.assertEqual(workflow["1"]["inputs"]["text"], request.prompt)
        self.assertEqual(workflow["2"]["inputs"]["text"], request.negative_prompt)
        self.assertEqual(workflow["3"]["inputs"]["seed"], request.seed)
        self.assertEqual(workflow["3"]["inputs"]["steps"], request.steps)
        self.assertEqual(workflow["3"]["inputs"]["cfg"], request.guidance_scale)
        self.assertEqual(workflow["4"]["inputs"]["width"], request.width)
        self.assertEqual(workflow["4"]["inputs"]["height"], request.height)
        self.assertTrue(
            workflow["5"]["inputs"]["filename_prefix"].startswith("origin_forge_")
        )
        self.assertEqual(_ComfyHandler.system_stats_hits, 1)
        self.assertEqual(_ComfyHandler.prompt_hits, 1)
        self.assertGreaterEqual(_ComfyHandler.history_hits, 1)
        self.assertEqual(_ComfyHandler.view_hits, 1)

        result = execution.result
        result.bind_request(request)
        self.assertEqual(len(result.outputs), 1)
        output = result.outputs[0]
        expected = inspect_rgba8_png(_ComfyHandler.output_png)
        self.assertEqual(output.pixel_hash, expected.pixel_hash)
        self.assertEqual(output.width, 16)
        self.assertEqual(output.height, 16)
        written = execution.workspace_path / "exports" / "concept.png"
        self.assertEqual(written.read_bytes(), _ComfyHandler.output_png)
        self.assertFalse(execution.to_dict()["production_verification_changed"])
        self.assertFalse(execution.to_dict()["canonical_asset_adopted"])

    def test_version_mismatch_fails_before_workspace_or_queue(self) -> None:
        request = _request(self.template)
        _ComfyHandler.expected_version = "wrong-version"
        server, thread = self._server()
        try:
            with self.assertRaises(ComfyUiIntegrityError):
                self._adapter(server).execute(request)
            self.assertEqual(_ComfyHandler.prompt_hits, 0)
            workspace_root = self.runtime.state_dir / "image-workspaces"
            self.assertFalse(workspace_root.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_request_cannot_substitute_workflow_or_model_identity(self) -> None:
        request = _request(self.template)
        with self.assertRaises(ComfyUiIntegrityError):
            self.template.render(
                ImageOperationRequest(
                    operation_id=request.operation_id,
                    workspace_id=request.workspace_id,
                    operation=request.operation,
                    backend_id=request.backend_id,
                    backend_version=request.backend_version,
                    workflow_id=request.workflow_id,
                    workflow_hash="sha256:" + "f" * 64,
                    model_id=request.model_id,
                    model_hash=request.model_hash,
                    prompt=request.prompt,
                    negative_prompt=request.negative_prompt,
                    width=request.width,
                    height=request.height,
                    seed=request.seed,
                    steps=request.steps,
                    guidance_scale=request.guidance_scale,
                    output_relative_paths=request.output_relative_paths,
                )
            )
        with self.assertRaises(ComfyUiIntegrityError):
            self.template.render(
                ImageOperationRequest(
                    operation_id=request.operation_id,
                    workspace_id=request.workspace_id,
                    operation=request.operation,
                    backend_id=request.backend_id,
                    backend_version=request.backend_version,
                    workflow_id=request.workflow_id,
                    workflow_hash=request.workflow_hash,
                    model_id="other-model",
                    model_hash=request.model_hash,
                    prompt=request.prompt,
                    negative_prompt=request.negative_prompt,
                    width=request.width,
                    height=request.height,
                    seed=request.seed,
                    steps=request.steps,
                    guidance_scale=request.guidance_scale,
                    output_relative_paths=request.output_relative_paths,
                )
            )

    def test_invalid_or_wrong_dimension_png_fails_closed(self) -> None:
        request = _request(self.template)
        for payload in (
            b"not-png",
            encode_rgba8_png(PixelPlane(8, 8, bytes([1, 2, 3, 255] * 64))),
        ):
            with self.subTest(size=len(payload)):
                _ComfyHandler.reset()
                _ComfyHandler.output_png = payload
                server, thread = self._server()
                try:
                    with self.assertRaises(ComfyUiIntegrityError):
                        self._adapter(server).execute(request)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
                # Each execution gets a new isolated workspace, so use a fresh request.
                request = _request(self.template)

    def test_output_count_mismatch_and_edit_operation_are_blocked(self) -> None:
        base = _request(self.template)
        two_outputs = ImageOperationRequest(
            operation_id=base.operation_id,
            workspace_id=base.workspace_id,
            operation=base.operation,
            backend_id=base.backend_id,
            backend_version=base.backend_version,
            workflow_id=base.workflow_id,
            workflow_hash=base.workflow_hash,
            model_id=base.model_id,
            model_hash=base.model_hash,
            prompt=base.prompt,
            negative_prompt=base.negative_prompt,
            width=base.width,
            height=base.height,
            seed=base.seed,
            steps=base.steps,
            guidance_scale=base.guidance_scale,
            output_relative_paths=("exports/a.png", "exports/b.png"),
        )
        server, thread = self._server()
        try:
            with self.assertRaises(ComfyUiIntegrityError):
                self._adapter(server).execute(two_outputs)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        from origin_forge.image_vision_models import RasterInputRef

        edit = ImageOperationRequest.create(
            operation=ImageOperation.EDIT,
            backend_id="comfyui",
            backend_version=VERSION,
            workflow_id=self.template.workflow_id,
            workflow_hash=self.template.workflow_hash,
            model_id=self.template.model_id,
            model_hash=self.template.model_hash,
            prompt="edit",
            negative_prompt="",
            width=16,
            height=16,
            seed=1,
            steps=1,
            guidance_scale=1.0,
            output_relative_paths=("exports/edit.png",),
            input_images=(
                RasterInputRef(
                    image_id="source",
                    relative_path="inputs/source.png",
                    content_hash="sha256:" + "a" * 64,
                    pixel_hash="sha256:" + "b" * 64,
                    byte_count=1,
                    width=1,
                    height=1,
                ),
            ),
        )
        server, thread = self._server()
        try:
            with self.assertRaises(ComfyUiIntegrityError):
                self._adapter(server).execute(edit)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_adapter_exposes_no_task_merge_release_or_arbitrary_workflow_surface(self) -> None:
        public = {name for name in dir(ComfyUiAdapter) if not name.startswith("_")}
        for forbidden in (
            "complete_task",
            "verify_task",
            "merge",
            "release",
            "install_node",
            "install_plugin",
            "execute_workflow_json",
            "run_javascript",
        ):
            self.assertNotIn(forbidden, public)


if __name__ == "__main__":
    unittest.main()
