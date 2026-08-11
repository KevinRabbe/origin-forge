from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_read import DreamReadError, DreamReadService
from origin_forge.runtime import OriginForgeRuntime


class DreamReadContainmentTests(unittest.TestCase):
    def test_intermediate_memory_symlink_is_rejected_before_missing_child_is_treated_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("dream-read-intermediate-symlink-test")
            dream = runtime.state_dir / "dream"
            dream.mkdir()
            outside = root / "outside-memory"
            outside.mkdir()
            (dream / "memory").symlink_to(outside, target_is_directory=True)
            reader = DreamReadService(runtime)
            with self.assertRaises(DreamReadError):
                reader.memory_entry_ids()
            with self.assertRaises(DreamReadError):
                reader.generation_ids()


if __name__ == "__main__":
    unittest.main()
