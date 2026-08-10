from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime_observation_service import (
    RuntimeObservationService,
    RuntimeObservationServiceError,
)


class RuntimeObservationBoundTests(unittest.TestCase):
    def test_bound_file_rejects_claim_above_budget_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "capture.png"
            with path.open("wb") as handle:
                handle.truncate(128 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(RuntimeObservationServiceError, "exceeds byte budget"):
                RuntimeObservationService._read_bound_file(
                    path,
                    content_hash="sha256:" + "0" * 64,
                    byte_count=128 * 1024 * 1024 + 1,
                    label="capture",
                    max_bytes=128 * 1024 * 1024,
                )

    def test_bound_file_rejects_actual_size_drift_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "capture.png"
            with path.open("wb") as handle:
                handle.truncate(128 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(RuntimeObservationServiceError, "bytes drifted"):
                RuntimeObservationService._read_bound_file(
                    path,
                    content_hash="sha256:" + "0" * 64,
                    byte_count=1,
                    label="capture",
                    max_bytes=128 * 1024 * 1024,
                )


if __name__ == "__main__":
    unittest.main()
