from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from origin_forge.adapters.comfyui import (
    ComfyBinding,
    ComfyUiAdapter,
    ComfyUiProfile,
    ComfyWorkflowBindings,
)
from origin_forge.image_vision_models import ImageOperation, ImageOperationRequest
from origin_forge.image_workflows import GovernedComfyWorkflowTemplate, ImageWorkflowStore
from origin_forge.pixelorama_png import inspect_rgba8_png
from origin_forge.runtime import OriginForgeRuntime


class RealComfyUiGenerationIntegrationTests(unittest.TestCase):
    def _required_env(self) -> dict[str, str]:
        names = (
            "ORIGIN_FORGE_COMFY_REAL_URL",
            "ORIGIN_FORGE_COMFY_VERSION",
            "ORIGIN_FORGE_COMFY_RUNTIME_COMMIT",
            "ORIGIN_FORGE_COMFY_MODEL_ID",
            "ORIGIN_FORGE_COMFY_MODEL_FILE",
            "ORIGIN_FORGE_COMFY_MODEL_SHA256",
            "ORIGIN_FORGE_COMFY_CHECKPOINT_NAME",
        )
        values = {name: os.environ.get(name, "").strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            self.skipTest(
                "real ComfyUI runtime/model external pins not configured"
            )
        return values

    @staticmethod
    def _verify_model(path: Path, expected_sha256: str) -> None:
        if not path.is_file() or path.is_symlink():
            raise AssertionError("generation model must be a regular non-symlink file")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        actual = "sha256:" + digest.hexdigest()
        if actual != expected_sha256:
            raise AssertionError(f"generation model SHA-256 mismatch: {actual}")

    @staticmethod
    def _template(env: dict[str, str]) -> GovernedComfyWorkflowTemplate:
        checkpoint_name = env["ORIGIN_FORGE_COMFY_CHECKPOINT_NAME"]
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint_name},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["1", 1]},
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 64, "height": 64, "batch_size": 1},
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 0,
                    "steps": 1,
                    "cfg": 1.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {"images": ["6", 0], "filename_prefix": "placeholder"},
            },
        }
        return GovernedComfyWorkflowTemplate(
            workflow_id="phase21-sd15-core-generate-v1",
            backend_version=env["ORIGIN_FORGE_COMFY_VERSION"],
            model_id=env["ORIGIN_FORGE_COMFY_MODEL_ID"],
            model_hash=env["ORIGIN_FORGE_COMFY_MODEL_SHA256"],
            workflow=workflow,
            bindings=ComfyWorkflowBindings(
                positive_prompt=ComfyBinding("2", "text"),
                negative_prompt=ComfyBinding("3", "text"),
                seed=ComfyBinding("5", "seed"),
                steps=ComfyBinding("5", "steps"),
                guidance=ComfyBinding("5", "cfg"),
                width=ComfyBinding("4", "width"),
                height=ComfyBinding("4", "height"),
                output_prefix=ComfyBinding("7", "filename_prefix"),
            ),
            output_node_id="7",
            operation=ImageOperation.GENERATE,
        )

    def test_real_pinned_comfyui_sd15_generates_canonical_validated_png(self) -> None:
        env = self._required_env()
        self.assertEqual(env["ORIGIN_FORGE_COMFY_VERSION"], "0.28.0")
        self.assertEqual(
            env["ORIGIN_FORGE_COMFY_RUNTIME_COMMIT"],
            "700821e1364eaab0e8f21c538a2131719fec57bf",
        )
        model_path = Path(env["ORIGIN_FORGE_COMFY_MODEL_FILE"])
        self._verify_model(model_path, env["ORIGIN_FORGE_COMFY_MODEL_SHA256"])

        with tempfile.TemporaryDirectory() as tempdir:
            runtime = OriginForgeRuntime(Path(tempdir))
            runtime.initialize("phase21-real-comfy")
            template = self._template(env)
            store = ImageWorkflowStore(runtime)
            stored = store.put(template)
            trusted = store.get(stored.workflow_id, stored.workflow_hash)
            request = ImageOperationRequest.create(
                operation=ImageOperation.GENERATE,
                backend_id="comfyui",
                backend_version=env["ORIGIN_FORGE_COMFY_VERSION"],
                workflow_id=trusted.workflow_id,
                workflow_hash=trusted.workflow_hash,
                model_id=trusted.model_id,
                model_hash=trusted.model_hash,
                prompt="a simple red cube centered on a dark background",
                negative_prompt="text, watermark",
                width=64,
                height=64,
                seed=123456789,
                steps=1,
                guidance_scale=1.0,
                output_relative_paths=("exports/proof.png",),
            )
            execution = ComfyUiAdapter(
                runtime,
                ComfyUiProfile(
                    base_url=env["ORIGIN_FORGE_COMFY_REAL_URL"],
                    expected_version=env["ORIGIN_FORGE_COMFY_VERSION"],
                    request_timeout_seconds=30,
                    poll_interval_seconds=0.25,
                    max_json_bytes=4 * 1024 * 1024,
                    max_image_bytes=16 * 1024 * 1024,
                ),
                trusted,
            ).execute(request)
            execution.result.bind_request(request)
            self.assertEqual(len(execution.result.outputs), 1)
            output = execution.result.outputs[0]
            path = execution.workspace_path / output.relative_path
            data = path.read_bytes()
            inspection = inspect_rgba8_png(data)
            self.assertEqual((inspection.width, inspection.height), (64, 64))
            self.assertEqual(output.pixel_hash, inspection.pixel_hash)
            self.assertEqual(
                output.content_hash,
                "sha256:" + hashlib.sha256(data).hexdigest(),
            )
            self.assertFalse(execution.to_dict()["production_verification_changed"])
            self.assertFalse(execution.to_dict()["canonical_asset_adopted"])


if __name__ == "__main__":
    unittest.main()
