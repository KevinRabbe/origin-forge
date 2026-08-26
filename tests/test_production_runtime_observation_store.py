from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.production_runtime_observation_store import (
    RuntimeObservationRequestStore,
    RuntimeObservationRequestStoreError,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observation_models import RuntimeObservationRequest


class RuntimeObservationRequestStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(Path(self.tempdir.name))
        self.runtime.initialize("runtime-request-store")
        self.request = RuntimeObservationRequest.create(
            backend_id="runtime-observer",
            backend_version="1",
            target_id="game-build",
            target_version="build-1",
            executable_hash="sha256:" + "1" * 64,
        )
        self.store = RuntimeObservationRequestStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_put_get_is_idempotent_and_content_addressed(self) -> None:
        first = self.store.put(self.request)
        second = self.store.put(self.request)
        self.assertEqual(first, second)
        self.assertEqual(self.store.get(self.request.observation_id, self.request.content_hash), self.request)
        self.assertEqual(len(self.store.list()), 1)

    def test_tampering_and_identity_drift_fail_closed(self) -> None:
        stored = self.store.put(self.request)
        value = json.loads(stored.path.read_text(encoding="utf-8"))
        value["target_version"] = "build-tampered"
        stored.path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(RuntimeObservationRequestStoreError):
            self.store.get(self.request.observation_id, self.request.content_hash)


if __name__ == "__main__":
    unittest.main()
