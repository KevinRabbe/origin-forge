from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.context_discovery import (
    ContextDiscoveryError,
    DiscoverySettings,
    TaskContextDiscoverer,
)
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class ContextDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")

        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "src" / "payment_service.py").write_text(
            "class PaymentService:\n"
            "    def refund_invoice(self, invoice_id):\n"
            "        return self.gateway.refund(invoice_id)\n",
            encoding="utf-8",
        )
        (self.root / "src" / "inventory.py").write_text(
            "class Inventory:\n    def reserve_stock(self, sku):\n        return sku\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_payment_service.py").write_text(
            "def test_refund_invoice():\n    assert PaymentService\n",
            encoding="utf-8",
        )
        (self.root / "docs" / "architecture.md").write_text(
            "The service architecture uses repositories and queues.\n",
            encoding="utf-8",
        )
        git(self.root, "add", "src", "tests", "docs")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("context-discovery-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task(
        self,
        objective: str,
        *,
        acceptance: tuple[str, ...] = (),
        constraints: tuple[str, ...] = (),
    ) -> str:
        goal = self.runtime.create_goal("context discovery")
        flow = self.runtime.create_flow(goal)
        return self.runtime.create_task(
            flow,
            objective,
            acceptance_criteria=acceptance,
            constraints=constraints,
        )

    def _discoverer(self, **settings) -> TaskContextDiscoverer:
        return TaskContextDiscoverer(
            self.runtime,
            RepositoryReader(self.root),
            settings=DiscoverySettings(**settings) if settings else None,
        )

    def test_ranks_task_relevant_source_and_test_files(self) -> None:
        task = self._task(
            "Fix PaymentService refund invoice behavior",
            acceptance=("refund invoice test passes",),
        )
        result = self._discoverer().discover(task)

        self.assertGreaterEqual(len(result.selected), 2)
        self.assertEqual(
            set(result.paths[:2]),
            {"src/payment_service.py", "tests/test_payment_service.py"},
        )
        self.assertIn("payment", result.query_terms)
        self.assertIn("refund", result.query_terms)
        self.assertGreater(result.selected[0].score, 0)
        self.assertGreater(result.selected[1].score, 0)

    def test_untracked_files_are_never_discovered(self) -> None:
        (self.root / "secret_payment_notes.py").write_text(
            "refund invoice PaymentService secret\n", encoding="utf-8"
        )
        task = self._task("Fix PaymentService refund invoice")
        result = self._discoverer().discover(task)

        self.assertNotIn("secret_payment_notes.py", result.paths)
        self.assertIn("src/payment_service.py", result.paths)

    def test_unrelated_task_returns_no_arbitrary_context(self) -> None:
        task = self._task("Implement quantum banana telemetry")
        result = self._discoverer().discover(task)
        self.assertEqual(result.paths, ())

    def test_selected_file_and_byte_budgets_are_hard(self) -> None:
        task = self._task("payment refund invoice")
        result = self._discoverer(max_files=1, max_total_bytes=200).discover(task)
        self.assertEqual(len(result.selected), 1)
        self.assertLessEqual(result.selected[0].byte_count, 200)

    def test_scan_byte_budget_limits_indexing(self) -> None:
        task = self._task("payment refund invoice inventory stock")
        result = self._discoverer(
            max_scan_bytes=130,
            max_scan_files=100,
            max_files=10,
            max_total_bytes=1000,
        ).discover(task)
        self.assertLessEqual(result.scanned_bytes, 130)

    def test_path_matches_are_prioritized_before_scan_file_cap(self) -> None:
        (self.root / "aaa_unrelated.txt").write_text("nothing useful\n", encoding="utf-8")
        (self.root / "zzz_needlewidget.py").write_text("VALUE = 1\n", encoding="utf-8")
        git(self.root, "add", "aaa_unrelated.txt", "zzz_needlewidget.py")
        git(self.root, "commit", "-qm", "add scan priority fixtures")

        task = self._task("Fix needlewidget behavior")
        result = self._discoverer(
            max_scan_files=1,
            max_scan_bytes=1000,
            max_files=3,
            max_total_bytes=1000,
        ).discover(task)
        self.assertEqual(result.scanned_files, 1)
        self.assertEqual(result.paths, ("zzz_needlewidget.py",))

    def test_seed_paths_are_included_even_without_query_match(self) -> None:
        task = self._task("payment refund invoice")
        result = self._discoverer(max_files=3, max_total_bytes=1000).discover(
            task,
            seed_paths=["docs/architecture.md"],
        )
        self.assertEqual(result.paths[0], "docs/architecture.md")
        self.assertTrue(result.selected[0].seeded)
        self.assertIn("src/payment_service.py", result.paths)

    def test_invalid_seed_is_rejected(self) -> None:
        task = self._task("payment refund")
        with self.assertRaises(ContextDiscoveryError):
            self._discoverer().discover(task, seed_paths=["not-there.py"])

    def test_seed_budget_overflow_is_rejected(self) -> None:
        task = self._task("payment refund")
        with self.assertRaisesRegex(ContextDiscoveryError, "selected-file budget"):
            self._discoverer(max_files=1).discover(
                task,
                seed_paths=["docs/architecture.md", "src/inventory.py"],
            )

    def test_tracked_symlink_is_not_followed_for_discovery(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        outside_dir = Path(self.tempdir.name).parent / f"{self.root.name}-outside"
        outside_dir.mkdir(exist_ok=False)
        try:
            outside = outside_dir / "payment_secret.py"
            outside.write_text("PaymentService refund invoice\n", encoding="utf-8")
            link = self.root / "src" / "linked_payment.py"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            git(self.root, "add", "src/linked_payment.py")
            git(self.root, "commit", "-qm", "track symlink")

            task = self._task("PaymentService refund invoice")
            result = self._discoverer().discover(task)
            self.assertNotIn("src/linked_payment.py", result.paths)
        finally:
            for child in outside_dir.iterdir():
                child.unlink()
            outside_dir.rmdir()

    def test_discovery_is_deterministic(self) -> None:
        task = self._task("payment refund invoice")
        discoverer = self._discoverer()
        first = discoverer.discover(task)
        second = discoverer.discover(task)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
