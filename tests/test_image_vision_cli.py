from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.image_vision_cli import build_parser, main
from origin_forge.image_workflows import GovernedComfyWorkflowTemplate, ImageWorkflowStore
from origin_forge.adapters.comfyui import ComfyBinding, ComfyWorkflowBindings
from origin_forge.runtime import OriginForgeRuntime


MODEL_HASH = "sha256:" + "e" * 64


def _template() -> GovernedComfyWorkflowTemplate:
    workflow = {
        "1": {"class_type": "Text", "inputs": {"text": ""}},
        "2": {"class_type": "Text", "inputs": {"text": ""}},
        "3": {
            "class_type": "Sampler",
            "inputs": {"seed": 0, "steps": 1, "cfg": 1.0},
        },
        "4": {"class_type": "Latent", "inputs": {"width": 16, "height": 16}},
        "5": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x"}},
    }
    return GovernedComfyWorkflowTemplate(
        workflow_id="concept-v1",
        backend_version="0.9.1",
        model_id="image-model",
        model_hash=MODEL_HASH,
        workflow=workflow,
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


class ImageVisionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("image-vision-cli-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str) -> tuple[int, object]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_surface_is_strictly_read_only(self) -> None:
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if action.dest == "command"
        )
        commands = set(subparsers.choices)
        self.assertEqual(
            commands,
            {
                "status",
                "workflow-list",
                "workflow-show",
                "artifact-show",
                "generation-runs",
                "vision-runs",
            },
        )
        for forbidden in (
            "generate",
            "edit",
            "inspect",
            "adopt",
            "install",
            "download-model",
            "promote",
            "verify-task",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_and_empty_catalogs_are_deterministic_and_non_mutating(self) -> None:
        before = self.runtime.status()
        code, value = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "OK")
        self.assertEqual(value["approved_workflow_count"], 0)
        self.assertEqual(value["image_generation_run_count"], 0)
        self.assertEqual(value["vision_inspection_run_count"], 0)
        self.assertFalse(value["model_execution_enabled"])
        self.assertFalse(value["workflow_install_enabled"])
        self.assertFalse(value["model_download_enabled"])
        self.assertFalse(value["canonical_asset_adoption_enabled"])
        self.assertFalse(value["task_mutation_enabled"])
        self.assertEqual(self.runtime.status(), before)

    def test_workflow_list_and_show_read_exact_stored_template(self) -> None:
        template = _template()
        ImageWorkflowStore(self.runtime).put(template)
        code, listing = self._call("workflow-list")
        self.assertEqual(code, 0)
        self.assertEqual(len(listing["workflows"]), 1)
        self.assertEqual(listing["workflows"][0]["workflow_hash"], template.workflow_hash)
        code, shown = self._call(
            "workflow-show", template.workflow_id, template.workflow_hash
        )
        self.assertEqual(code, 0)
        self.assertEqual(shown, template.to_dict())

    def test_unknown_workflow_and_invalid_artifact_are_structured_errors(self) -> None:
        code, value = self._call(
            "workflow-show", "missing", "sha256:" + "a" * 64
        )
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")
        code, value = self._call("artifact-show", "not-an-artifact")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
