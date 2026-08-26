from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.adapters.comfyui import ComfyBinding, ComfyWorkflowBindings
from origin_forge.image_vision_models import ImageOperation, ImageOperationRequest
from origin_forge.image_workflows import (
    GovernedComfyWorkflowTemplate,
    ImageWorkflowError,
    ImageWorkflowStore,
)
from origin_forge.runtime import OriginForgeRuntime


MODEL_HASH = "sha256:" + "e" * 64


def _bindings(*, prompt_node: str = "1") -> ComfyWorkflowBindings:
    return ComfyWorkflowBindings(
        positive_prompt=ComfyBinding(prompt_node, "text"),
        negative_prompt=ComfyBinding("2", "text"),
        seed=ComfyBinding("3", "seed"),
        steps=ComfyBinding("3", "steps"),
        guidance=ComfyBinding("3", "cfg"),
        width=ComfyBinding("4", "width"),
        height=ComfyBinding("4", "height"),
        output_prefix=ComfyBinding("5", "filename_prefix"),
    )


def _workflow() -> dict[str, object]:
    return {
        "1": {"class_type": "Text", "inputs": {"text": ""}},
        "2": {"class_type": "Text", "inputs": {"text": ""}},
        "3": {
            "class_type": "Sampler",
            "inputs": {"seed": 0, "steps": 1, "cfg": 1.0},
        },
        "4": {
            "class_type": "Latent",
            "inputs": {"width": 16, "height": 16},
        },
        "5": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "placeholder"},
        },
    }


def _template(*, bindings: ComfyWorkflowBindings | None = None) -> GovernedComfyWorkflowTemplate:
    return GovernedComfyWorkflowTemplate(
        workflow_id="concept-v1",
        backend_version="0.9.1",
        model_id="image-model",
        model_hash=MODEL_HASH,
        workflow=_workflow(),
        bindings=bindings or _bindings(),
        output_node_id="5",
        operation=ImageOperation.GENERATE,
    )


class ImageWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("image-workflow-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_template_hash_covers_graph_bindings_output_and_model_identity(self) -> None:
        base = _template()
        graph_changed = _workflow()
        graph_changed["3"]["inputs"]["steps"] = 2
        variants = (
            GovernedComfyWorkflowTemplate(
                workflow_id=base.workflow_id,
                backend_version=base.backend_version,
                model_id=base.model_id,
                model_hash=base.model_hash,
                workflow=graph_changed,
                bindings=base.bindings,
                output_node_id=base.output_node_id,
            ),
            _template(bindings=_bindings(prompt_node="2")),
            GovernedComfyWorkflowTemplate(
                workflow_id=base.workflow_id,
                backend_version=base.backend_version,
                model_id="different-model",
                model_hash=base.model_hash,
                workflow=base.workflow,
                bindings=base.bindings,
                output_node_id=base.output_node_id,
            ),
            GovernedComfyWorkflowTemplate(
                workflow_id=base.workflow_id,
                backend_version=base.backend_version,
                model_id=base.model_id,
                model_hash=base.model_hash,
                workflow=base.workflow,
                bindings=base.bindings,
                output_node_id="4",
            ),
        )
        for variant in variants:
            self.assertNotEqual(base.workflow_hash, variant.workflow_hash)

    def test_request_binds_full_governed_template_identity_and_render_uses_only_bindings(self) -> None:
        template = _template()
        request = ImageOperationRequest.create(
            operation=ImageOperation.GENERATE,
            backend_id="comfyui",
            backend_version=template.backend_version,
            workflow_id=template.workflow_id,
            workflow_hash=template.workflow_hash,
            model_id=template.model_id,
            model_hash=template.model_hash,
            prompt="armored enemy",
            negative_prompt="text",
            width=32,
            height=32,
            seed=9,
            steps=8,
            guidance_scale=3.0,
            output_relative_paths=("exports/out.png",),
        )
        rendered = template.render(request)
        self.assertEqual(rendered["1"]["inputs"]["text"], "armored enemy")
        self.assertEqual(rendered["2"]["inputs"]["text"], "text")
        self.assertEqual(rendered["3"]["inputs"]["seed"], 9)
        self.assertEqual(rendered["4"]["inputs"]["width"], 32)
        self.assertEqual(template.workflow["1"]["inputs"]["text"], "")

    def test_store_round_trip_is_content_addressed_and_idempotent(self) -> None:
        template = _template()
        store = ImageWorkflowStore(self.runtime)
        first = store.put(template)
        second = store.put(template)
        self.assertEqual(first.workflow_hash, second.workflow_hash)
        self.assertEqual(first.path, second.path)
        loaded = store.get(template.workflow_id, template.workflow_hash)
        self.assertEqual(loaded.workflow_hash, template.workflow_hash)
        self.assertEqual(loaded.to_dict(), template.to_dict())
        listed = store.list()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].workflow_hash, template.workflow_hash)

    def test_store_detects_tamper_and_symlinked_root(self) -> None:
        template = _template()
        store = ImageWorkflowStore(self.runtime)
        stored = store.put(template)
        value = json.loads(stored.path.read_text(encoding="utf-8"))
        value["output_node_id"] = "4"
        stored.path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ImageWorkflowError):
            store.get(template.workflow_id, template.workflow_hash)

        other_root = Path(self.tempdir.name) / "other"
        other_root.mkdir()
        workflow_root = self.runtime.state_dir / "image-workflows"
        for child in workflow_root.iterdir():
            child.unlink()
        workflow_root.rmdir()
        try:
            workflow_root.symlink_to(other_root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink capability unavailable: {exc}")
        with self.assertRaises(ImageWorkflowError):
            store.list()

    def test_store_refuses_undeclared_entries_and_has_no_install_or_model_download_surface(self) -> None:
        store = ImageWorkflowStore(self.runtime)
        store.put(_template())
        (store.root / "unexpected.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(ImageWorkflowError):
            store.list()
        public = {name for name in dir(store) if not name.startswith("_")}
        for forbidden in (
            "install_custom_node",
            "download_model",
            "execute",
            "promote_task",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, public)


if __name__ == "__main__":
    unittest.main()
