from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from origin_forge.dream_store import DreamStore


class DreamStoreAtomicPublishTests(unittest.TestCase):
    def test_competing_publishers_never_replace_same_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "object.json"
            barrier = threading.Barrier(2)
            results: list[tuple[bool, bytes]] = []
            errors: list[BaseException] = []
            lock = threading.Lock()

            def publish(data: bytes) -> None:
                try:
                    barrier.wait(timeout=5)
                    created = DreamStore._atomic_write(target, data)
                    with lock:
                        results.append((created, data))
                except BaseException as exc:  # capture thread failures for the main assertion
                    with lock:
                        errors.append(exc)

            first = threading.Thread(target=publish, args=(b"first\n",))
            second = threading.Thread(target=publish, args=(b"second\n",))
            first.start()
            second.start()
            first.join(timeout=10)
            second.join(timeout=10)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            winners = [data for created, data in results if created]
            losers = [data for created, data in results if not created]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(losers), 1)
            self.assertNotEqual(winners[0], losers[0])
            self.assertEqual(target.read_bytes(), winners[0])

    def test_later_publish_cannot_replace_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "object.json"
            self.assertTrue(DreamStore._atomic_write(target, b"original\n"))
            self.assertFalse(DreamStore._atomic_write(target, b"replacement\n"))
            self.assertEqual(target.read_bytes(), b"original\n")


if __name__ == "__main__":
    unittest.main()
