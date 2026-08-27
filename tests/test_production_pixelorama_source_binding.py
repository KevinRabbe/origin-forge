from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.pixelorama_models import BridgeOutputType
from origin_forge.production_pixelorama_source_dispatch_output_binding_models import (
    PIXELORAMA_SOURCE_EXECUTION_OWNER_ID,
    PixeloramaSourceDispatchOutput,
    PixeloramaSourceDispatchOutputBinding,
    PixeloramaSourceOutputBindingModelError,
)


class PixeloramaSourceBindingModelTests(unittest.TestCase):
    def _output(self, path: str, output_type: BridgeOutputType) -> PixeloramaSourceDispatchOutput:
        return PixeloramaSourceDispatchOutput(
            output_type=output_type,
            relative_path=path,
            artifact_id=new_id(IdKind.ARTIFACT),
            verification_id=new_id(IdKind.VERIFICATION),
            content_hash="a" * 64,
            byte_count=10,
            width=16 if output_type is BridgeOutputType.PNG else None,
            height=16 if output_type is BridgeOutputType.PNG else None,
        )

    def _binding(self, outputs):
        return PixeloramaSourceDispatchOutputBinding(
            execution_id=new_id(IdKind.DISPATCH_EXECUTION),
            claim_id=new_id(IdKind.DISPATCH_CLAIM),
            task_id=new_id(IdKind.TASK),
            task_revision=2,
            task_content_hash="b" * 64,
            work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
            work_order_hash="c" * 64,
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            dispatch_binding_hash="d" * 64,
            execution_owner_id=PIXELORAMA_SOURCE_EXECUTION_OWNER_ID,
            run_id=new_id(IdKind.RUN),
            request_artifact_id=new_id(IdKind.ARTIFACT),
            result_artifact_id=new_id(IdKind.ARTIFACT),
            outputs=tuple(outputs),
            run_verification_id=new_id(IdKind.VERIFICATION),
            backend_result_hash="e" * 64,
            schema_version=1,
            created_at="2026-08-27T00:00:00Z",
        )

    def test_binding_supports_project_and_animation_png_outputs(self) -> None:
        binding = self._binding(
            (
                self._output("project/player.pxo", BridgeOutputType.PIXELORAMA_PROJECT),
                self._output("exports/player.png", BridgeOutputType.PNG),
            )
        )
        self.assertEqual(len(binding.outputs), 2)

    def test_binding_rejects_duplicate_paths(self) -> None:
        first = self._output("project/player.pxo", BridgeOutputType.PIXELORAMA_PROJECT)
        second = self._output("project/player.pxo", BridgeOutputType.PIXELORAMA_PROJECT)
        with self.assertRaisesRegex(PixeloramaSourceOutputBindingModelError, "paths"):
            self._binding((first, second))


if __name__ == "__main__":
    unittest.main()
