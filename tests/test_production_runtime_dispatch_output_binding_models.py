from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.production_runtime_dispatch_output_binding_models import (
    RuntimeDispatchCapture,
    RuntimeDispatchOutputBindingModelError,
)


class RuntimeDispatchOutputBindingModelTests(unittest.TestCase):
    def test_capture_rejects_unsafe_paths_and_binding_preserves_evidence_only_shape(self) -> None:
        kwargs = {
            "capture_id": "shot",
            "artifact_id": new_id(IdKind.ARTIFACT),
            "integrity_verification_id": new_id(IdKind.VERIFICATION),
            "visual_verification_id": None,
            "relative_path": "captures/shot.png",
            "content_hash": "a" * 64,
            "pixel_hash": "b" * 64,
            "byte_count": 10,
            "width": 1,
            "height": 1,
        }
        capture = RuntimeDispatchCapture(**kwargs)
        with self.assertRaises(RuntimeDispatchOutputBindingModelError):
            RuntimeDispatchCapture(**{**kwargs, "relative_path": "captures/../shot.png"})
        self.assertEqual(capture.relative_path, "captures/shot.png")


if __name__ == "__main__":
    unittest.main()
