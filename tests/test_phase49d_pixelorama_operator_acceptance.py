from __future__ import annotations

import json
import os
import sqlite3
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from . import test_phase49c_pixelorama_production_adoption as phase49c
from origin_forge.ids import IdKind, new_id
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_admin_cli import main as pixelorama_admin_main
from origin_forge.production_pixelorama_adoption import (
    GovernedPixeloramaProductionOutputAdopter,
    PixeloramaProductionAdoptionError,
)
from origin_forge.production_pixelorama_adoption_receipt import (
    PixeloramaProductionAdoptionStatus,
    read_pixelorama_production_adoption_receipt,
)
from origin_forge.production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from origin_forge.production_pixelorama_export import PixeloramaCliExportService


class Phase49DPixeloramaOperatorAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = phase49c.Phase49CPixeloramaProductionAdoptionTests(
            methodName=(
                "test_exact_terminal_dispatch_output_is_published_once_without_task_or_signing_authority"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    @property
    def runtime(self):
        return self.fixture.fixture.runtime

    def _invoke_successfully(self):
        return self.fixture._invoke_successfully()

    def _cli(self, *args: str) -> tuple[int, dict[str, object]]:
        output = StringIO()
        with redirect_stdout(output):
            code = pixelorama_admin_main(
                ["--project-root", str(self.runtime.project_root), *args]
            )
        return code, json.loads(output.getvalue())

    @staticmethod
    def _tree_bytes(root: Path) -> dict[str, bytes]:
        if not root.exists():
            return {}
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

    def test_real_dispatch_to_explicit_cli_adoption_has_no_replay_task_or_signing_authority(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.runtime
        binding = read_pixelorama_dispatch_output_binding(runtime, completed.execution_id)
        lineage = OriginForgeLineage(runtime)
        source_bytes = lineage.local_artifact_path(binding.output_artifact_id).read_bytes()
        task_before = runtime.get_task(binding.task_id)
        provenance_root = runtime.state_dir / "provenance"
        provenance_before = self._tree_bytes(provenance_root)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            code, payload = self._cli(
                "adopt-production-new",
                completed.execution_id,
                "assets/production/operator-sprite.png",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(code, 0)
        self.assertEqual(payload["execution_id"], completed.execution_id)
        self.assertEqual(payload["claim_id"], binding.claim_id)
        self.assertEqual(payload["task_id"], binding.task_id)
        self.assertEqual(payload["run_id"], binding.run_id)
        self.assertEqual(payload["source_artifact_id"], binding.output_artifact_id)
        self.assertEqual(
            payload["content_hash"],
            "sha256:" + binding.output_content_hash,
        )
        self.assertEqual(payload["byte_count"], binding.output_byte_count)
        self.assertFalse(payload["existing_asset_overwritten"])
        self.assertTrue(payload["production_dispatch_output_bound"])
        self.assertFalse(payload["production_task_verified"])
        self.assertFalse(payload["semantic_visual_quality_verified"])
        self.assertFalse(payload["provenance_signed"])
        self.assertEqual(
            (runtime.project_root / str(payload["destination_path"])).read_bytes(),
            source_bytes,
        )
        task_after = runtime.get_task(binding.task_id)
        self.assertEqual(task_after["status"], "RUNNING")
        self.assertEqual(task_after["revision"], task_before["revision"])
        self.assertEqual(runtime.list_verifications("TASK", binding.task_id), [])
        self.assertEqual(self._tree_bytes(provenance_root), provenance_before)

    def test_cli_fails_closed_on_missing_binding_protected_path_symlink_and_byte_limit(self) -> None:
        runtime = self.runtime
        missing_execution = new_id(IdKind.DISPATCH_EXECUTION)
        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            code, payload = self._cli(
                "adopt-production-new",
                missing_execution,
                "assets/missing.png",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(code, 2)
        self.assertIn("binding does not exist", str(payload["detail"]))
        self.assertFalse((runtime.project_root / "assets/missing.png").exists())

        completed = self._invoke_successfully()
        for destination in (".git/forbidden.png", ".origin-forge/forbidden.png"):
            with self.subTest(destination=destination):
                code, payload = self._cli(
                    "adopt-production-new",
                    completed.execution_id,
                    destination,
                )
                self.assertEqual(code, 2)
                self.assertFalse((runtime.project_root / destination).exists())

        outside = runtime.project_root / "outside-target"
        outside.mkdir(exist_ok=True)
        alias = runtime.project_root / "asset-alias"
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            alias = None
        if alias is not None:
            code, payload = self._cli(
                "adopt-production-new",
                completed.execution_id,
                "asset-alias/escaped.png",
            )
            self.assertEqual(code, 2)
            self.assertFalse((outside / "escaped.png").exists())

        code, payload = self._cli(
            "adopt-production-new",
            completed.execution_id,
            "assets/too-large.png",
            "--max-source-bytes",
            "4",
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            payload["detail"],
            "bound Pixelorama production source cannot be prepared for adoption",
        )
        self.assertFalse((runtime.project_root / "assets/too-large.png").exists())
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM pixelorama_production_adoptions"
                ).fetchone()[0],
                0,
            )

    def test_cli_revalidates_binding_and_verification_durable_truth_before_publication(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.runtime
        binding = read_pixelorama_dispatch_output_binding(runtime, completed.execution_id)
        conn = sqlite3.connect(runtime.store.db_path)
        try:
            conn.execute(
                "UPDATE verifications SET status = 'FAIL' WHERE id = ?",
                (binding.output_verification_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            code, payload = self._cli(
                "adopt-production-new",
                completed.execution_id,
                "assets/verification-drift.png",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse(
            (runtime.project_root / "assets/verification-drift.png").exists()
        )
        with runtime.store.session() as read_conn:
            self.assertEqual(
                read_conn.execute(
                    "SELECT COUNT(*) FROM pixelorama_production_adoptions"
                ).fetchone()[0],
                0,
            )

    def test_concurrent_same_execution_destination_race_publishes_at_most_once(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.runtime
        binding = read_pixelorama_dispatch_output_binding(runtime, completed.execution_id)
        destination = "assets/concurrent.png"

        def worker() -> tuple[str, object]:
            try:
                result = GovernedPixeloramaProductionOutputAdopter(runtime).adopt_new(
                    completed.execution_id,
                    destination,
                )
                return "ok", result
            except PixeloramaProductionAdoptionError as exc:
                return "error", str(exc)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay, ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(replay.call_count, 0)
        successes = [value for status, value in outcomes if status == "ok"]
        failures = [value for status, value in outcomes if status == "error"]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertTrue((runtime.project_root / destination).is_file())
        receipt = read_pixelorama_production_adoption_receipt(
            runtime,
            completed.execution_id,
        )
        self.assertEqual(receipt.status, PixeloramaProductionAdoptionStatus.PUBLISHED)
        with runtime.store.session() as conn:
            adopted_children = conn.execute(
                """SELECT COUNT(*) FROM artifacts
                   WHERE parent_artifact_id = ? AND status = 'ADOPTED'""",
                (binding.output_artifact_id,),
            ).fetchone()[0]
            receipts = conn.execute(
                "SELECT COUNT(*) FROM pixelorama_production_adoptions WHERE execution_id = ?",
                (completed.execution_id,),
            ).fetchone()[0]
        self.assertEqual(adopted_children, 1)
        self.assertEqual(receipts, 1)

    def test_post_link_crash_is_ambiguous_and_retry_never_overwrites_or_replays(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.runtime
        binding = read_pixelorama_dispatch_output_binding(runtime, completed.execution_id)
        source_bytes = OriginForgeLineage(runtime).local_artifact_path(
            binding.output_artifact_id
        ).read_bytes()
        destination = runtime.project_root / "assets/crash-window.png"
        adopter = GovernedPixeloramaProductionOutputAdopter(runtime)

        with patch.object(
            OriginForgeLineage,
            "create_artifact",
            autospec=True,
            side_effect=RuntimeError("injected post-link crash"),
        ):
            with self.assertRaisesRegex(RuntimeError, "post-link crash"):
                adopter.adopt_new(
                    completed.execution_id,
                    "assets/crash-window.png",
                )
        self.assertEqual(destination.read_bytes(), source_bytes)
        receipt = read_pixelorama_production_adoption_receipt(
            runtime,
            completed.execution_id,
        )
        self.assertEqual(receipt.status, PixeloramaProductionAdoptionStatus.PREPARED)
        self.assertIsNone(receipt.adopted_artifact_id)
        self.assertIsNone(receipt.verification_id)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            with self.assertRaisesRegex(
                PixeloramaProductionAdoptionError,
                "recovery required",
            ):
                GovernedPixeloramaProductionOutputAdopter(runtime).adopt_new(
                    completed.execution_id,
                    "assets/crash-window.png",
                )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(destination.read_bytes(), source_bytes)
        self.assertEqual(
            read_pixelorama_production_adoption_receipt(
                runtime,
                completed.execution_id,
            ).status,
            PixeloramaProductionAdoptionStatus.PREPARED,
        )

    def test_operator_surface_adds_no_package_script_or_hidden_execution_signing_authority(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(
            config["project"]["scripts"],
            {
                "origin-forge": "origin_forge.cli:main",
                "origin-forge-attempt": "origin_forge.orchestration_cli:main",
                "origin-forge-cockpit": "origin_forge.production_interface_cli:main",
            },
        )
        coordinator_source = (
            root / "src/origin_forge/production_pixelorama_adoption.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "PixeloramaCliExportService",
            "sign_artifact",
            "ProvenanceService",
            "transition_task",
            "mark_dispatch_execution",
            "dispatch_claim_once",
        ):
            self.assertNotIn(forbidden, coordinator_source)


if __name__ == "__main__":
    unittest.main()
