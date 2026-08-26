from __future__ import annotations

import io
import json
import sqlite3
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from origin_forge import blender_admin_cli
from origin_forge.lineage import OriginForgeLineage
from origin_forge.production_blender_adoption import (
    BlenderProductionAdoptionError,
    GovernedBlenderProductionOutputAdopter,
)
from origin_forge.production_blender_adoption_receipt import (
    BlenderProductionAdoptionReceiptError,
    BlenderProductionAdoptionStatus,
    read_blender_production_adoption_receipt,
)
from origin_forge.production_blender_dispatch_output_binding import (
    read_blender_dispatch_output_binding,
)
from origin_forge.production_blender_export import BlenderExportService
from .test_phase52b_blender_production_adoption import Phase52BBlenderProductionAdoptionTests


class Phase52CBlenderAdoptionOperatorAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phase52b = Phase52BBlenderProductionAdoptionTests(
            methodName=(
                "test_exact_terminal_blender_output_is_published_once_without_replay_or_task_authority"
            )
        )
        self.phase52b.setUp()

    def tearDown(self) -> None:
        self.phase52b.tearDown()

    @property
    def runtime(self):
        return self.phase52b.fixture.runtime

    def _terminal_execution(self):
        return self.phase52b._invoke_successfully()

    def _run_cli(
        self,
        execution_id: str,
        destination: str,
        *,
        max_source_bytes: int | None = None,
    ) -> tuple[int, dict[str, object]]:
        argv = [
            "--project-root",
            str(self.runtime.project_root),
            "adopt-production-new",
            "--execution-id",
            execution_id,
            "--destination",
            destination,
        ]
        if max_source_bytes is not None:
            argv.extend(["--max-source-bytes", str(max_source_bytes)])
        output = io.StringIO()
        with redirect_stdout(output):
            code = blender_admin_cli.main(argv)
        return code, json.loads(output.getvalue())

    def _mutate(self, sql: str, parameters: tuple[object, ...]) -> None:
        conn = sqlite3.connect(self.runtime.store.db_path)
        try:
            conn.execute(sql, parameters)
            conn.commit()
        finally:
            conn.close()

    def _assert_no_receipt(self, execution_id: str) -> None:
        with self.assertRaises(BlenderProductionAdoptionReceiptError):
            read_blender_production_adoption_receipt(self.runtime, execution_id)

    def test_module_cli_adopts_exact_terminal_output_without_replay_or_task_authority(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        task_before = self.runtime.get_task(completed.execution.task_id)

        with patch.object(BlenderExportService, "execute", autospec=True) as replay:
            code, payload = self._run_cli(
                execution_id,
                "assets/production/operator-crate.glb",
            )

        self.assertEqual(code, 0)
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(payload["execution_id"], execution_id)
        self.assertEqual(payload["destination_path"], "assets/production/operator-crate.glb")
        self.assertTrue(payload["production_dispatch_output_bound"])
        self.assertFalse(payload["existing_asset_overwritten"])
        self.assertFalse(payload["production_task_verified"])
        self.assertFalse(payload["semantic_geometry_verified"])
        self.assertFalse(payload["provenance_signed"])
        self.assertTrue((self.runtime.project_root / payload["destination_path"]).is_file())

        receipt = read_blender_production_adoption_receipt(self.runtime, execution_id)
        self.assertEqual(receipt.status, BlenderProductionAdoptionStatus.PUBLISHED)
        task_after = self.runtime.get_task(completed.execution.task_id)
        self.assertEqual(task_after["status"], "RUNNING")
        self.assertEqual(task_after["revision"], task_before["revision"])
        self.assertEqual(
            self.runtime.list_verifications("TASK", completed.execution.task_id),
            [],
        )

    def test_cli_fails_closed_when_binding_is_missing(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        self._mutate(
            "DELETE FROM blender_dispatch_output_bindings WHERE execution_id = ?",
            (execution_id,),
        )

        with patch.object(BlenderExportService, "execute", autospec=True) as replay:
            code, payload = self._run_cli(execution_id, "assets/production/missing.glb")

        self.assertEqual(replay.call_count, 0)
        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/missing.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_binding_is_tampered(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        self._mutate(
            "UPDATE blender_dispatch_output_bindings SET output_content_hash = ? WHERE execution_id = ?",
            ("0" * 64, execution_id),
        )

        code, payload = self._run_cli(execution_id, "assets/production/tampered-binding.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse(
            (self.runtime.project_root / "assets/production/tampered-binding.glb").exists()
        )
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_execution_is_not_returned(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        self._mutate(
            """UPDATE dispatch_executions
               SET status = 'STARTED', revision = 0, terminal_detail_hash = NULL
               WHERE execution_id = ?""",
            (execution_id,),
        )

        code, payload = self._run_cli(execution_id, "assets/production/not-returned.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/not-returned.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_claim_is_not_consumed(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        self._mutate(
            "UPDATE dispatch_claims SET status = 'ACTIVE', terminal_reason = NULL WHERE claim_id = ?",
            (completed.execution.claim_id,),
        )

        code, payload = self._run_cli(execution_id, "assets/production/not-consumed.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/not-consumed.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_execution_owner_drifts(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        self._mutate(
            "UPDATE dispatch_executions SET execution_owner_id = ? WHERE execution_id = ?",
            ("originforge.execution.pixelorama.export@1", execution_id),
        )

        code, payload = self._run_cli(execution_id, "assets/production/wrong-owner.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/wrong-owner.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_task_revision_is_stale(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        task_id = completed.execution.task_id
        self._mutate(
            "UPDATE tasks SET revision = revision + 1 WHERE id = ?",
            (task_id,),
        )

        code, payload = self._run_cli(execution_id, "assets/production/stale-task.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/stale-task.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_run_is_no_longer_succeeded(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        self._mutate(
            "UPDATE runs SET status = 'FAILED' WHERE id = ?",
            (binding.run_id,),
        )

        code, payload = self._run_cli(execution_id, "assets/production/stale-run.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/stale-run.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_output_artifact_lineage_drifts(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        self._mutate(
            "UPDATE artifacts SET parent_artifact_id = ? WHERE id = ?",
            (binding.request_artifact_id, binding.output_artifact_id),
        )

        code, payload = self._run_cli(execution_id, "assets/production/lineage-drift.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/lineage-drift.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_terminal_glb_bytes_drift(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        source = OriginForgeLineage(self.runtime).local_artifact_path(binding.output_artifact_id)
        source.write_bytes(b"tampered-terminal-glb")

        with patch.object(BlenderExportService, "execute", autospec=True) as replay:
            code, payload = self._run_cli(execution_id, "assets/production/mutable-output.glb")

        self.assertEqual(replay.call_count, 0)
        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse(
            (self.runtime.project_root / "assets/production/mutable-output.glb").exists()
        )
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_bound_source_is_symlinked(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        source = OriginForgeLineage(self.runtime).local_artifact_path(binding.output_artifact_id)
        source_bytes = source.read_bytes()
        target = source.with_name("symlink-target.glb")
        target.write_bytes(source_bytes)
        source.unlink()
        source.symlink_to(target)

        code, payload = self._run_cli(execution_id, "assets/production/source-symlink.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / "assets/production/source-symlink.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_fails_closed_when_bound_verification_drifts(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        self._mutate(
            "UPDATE verifications SET status = 'FAIL' WHERE id = ?",
            (binding.output_verification_id,),
        )

        code, payload = self._run_cli(execution_id, "assets/production/verification-drift.glb")

        self.assertEqual(code, 2)
        self.assertIn("not adoption eligible", str(payload["detail"]))
        self.assertFalse(
            (self.runtime.project_root / "assets/production/verification-drift.glb").exists()
        )
        self._assert_no_receipt(execution_id)

    def test_cli_byte_limit_fails_before_reservation_or_publication(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        destination = "assets/production/too-large.glb"

        code, payload = self._run_cli(
            execution_id,
            destination,
            max_source_bytes=1,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "BlenderProductionAdoptionError")
        self.assertIn("byte limit", str(payload["detail"]))
        self.assertFalse((self.runtime.project_root / destination).exists())
        self._assert_no_receipt(execution_id)

    def test_cli_rejects_protected_traversal_and_symlink_destinations(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        for destination in (
            ".origin-forge/forbidden.glb",
            ".git/forbidden.glb",
            "assets/../escaped.glb",
        ):
            with self.subTest(destination=destination):
                code, payload = self._run_cli(execution_id, destination)
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"], "BlenderProductionAdoptionError")

        outside = self.runtime.project_root / "outside-target"
        outside.mkdir(exist_ok=True)
        alias = self.runtime.project_root / "asset-alias"
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            alias = None
        if alias is not None:
            code, payload = self._run_cli(
                execution_id,
                "asset-alias/escaped.glb",
            )
            self.assertEqual(code, 2)
            self.assertEqual(payload["error"], "BlenderProductionAdoptionError")
            self.assertFalse((outside / "escaped.glb").exists())
        self._assert_no_receipt(execution_id)

    def test_cli_refuses_destination_that_already_exists_without_reserving(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        destination = self.runtime.project_root / "assets/production/existing.glb"
        destination.parent.mkdir(parents=True, exist_ok=True)
        sentinel = b"do-not-overwrite"
        destination.write_bytes(sentinel)

        code, payload = self._run_cli(execution_id, "assets/production/existing.glb")

        self.assertEqual(code, 2)
        self.assertIn("create-only", str(payload["detail"]))
        self.assertEqual(destination.read_bytes(), sentinel)
        self._assert_no_receipt(execution_id)

    def test_cli_rejects_malformed_execution_identity(self) -> None:
        code, payload = self._run_cli(
            "not-a-dispatch-execution-id",
            "assets/production/invalid.glb",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "ValueError")
        self.assertIn("DISPEXEC", str(payload["detail"]))

    def test_concurrent_same_execution_destination_publishes_at_most_once(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        destination = "assets/production/concurrent.glb"

        def worker() -> tuple[str, object]:
            try:
                result = GovernedBlenderProductionOutputAdopter(self.runtime).adopt_new(
                    execution_id,
                    destination,
                )
                return "ok", result
            except BlenderProductionAdoptionError as exc:
                return "error", str(exc)

        with patch.object(BlenderExportService, "execute", autospec=True) as replay, ThreadPoolExecutor(
            max_workers=2
        ) as pool:
            outcomes = list(pool.map(lambda _: worker(), range(2)))

        self.assertEqual(replay.call_count, 0)
        self.assertEqual(len([value for status, value in outcomes if status == "ok"]), 1)
        self.assertEqual(len([value for status, value in outcomes if status == "error"]), 1)
        self.assertTrue((self.runtime.project_root / destination).is_file())
        receipt = read_blender_production_adoption_receipt(self.runtime, execution_id)
        self.assertEqual(receipt.status, BlenderProductionAdoptionStatus.PUBLISHED)
        with self.runtime.store.session() as conn:
            adopted_children = conn.execute(
                """SELECT COUNT(*) FROM artifacts
                   WHERE parent_artifact_id = ? AND status = 'ADOPTED'""",
                (binding.output_artifact_id,),
            ).fetchone()[0]
            receipts = conn.execute(
                "SELECT COUNT(*) FROM blender_production_adoptions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()[0]
        self.assertEqual(adopted_children, 1)
        self.assertEqual(receipts, 1)

    def test_repeated_fan_out_is_rejected_after_canonical_publication(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id

        first_code, first = self._run_cli(execution_id, "assets/production/primary.glb")
        second_code, second = self._run_cli(execution_id, "assets/production/fan-out.glb")

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 2)
        self.assertIn("already been canonically adopted", str(second["detail"]))
        self.assertTrue((self.runtime.project_root / first["destination_path"]).is_file())
        self.assertFalse((self.runtime.project_root / "assets/production/fan-out.glb").exists())
        receipt = read_blender_production_adoption_receipt(self.runtime, execution_id)
        self.assertEqual(receipt.destination_path, "assets/production/primary.glb")
        self.assertEqual(receipt.status, BlenderProductionAdoptionStatus.PUBLISHED)

    def test_pre_link_crash_leaves_prepared_receipt_and_safe_cli_retry_completes_once(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        destination = "assets/production/pre-link-retry.glb"

        with patch.object(
            GovernedBlenderProductionOutputAdopter,
            "_publish_new",
            autospec=True,
            side_effect=OSError("injected pre-link crash"),
        ), patch.object(BlenderExportService, "execute", autospec=True) as replay:
            first_code, first = self._run_cli(execution_id, destination)

        self.assertEqual(replay.call_count, 0)
        self.assertEqual(first_code, 2)
        self.assertEqual(first["error"], "OSError")
        self.assertFalse((self.runtime.project_root / destination).exists())
        prepared = read_blender_production_adoption_receipt(self.runtime, execution_id)
        self.assertEqual(prepared.status, BlenderProductionAdoptionStatus.PREPARED)

        with patch.object(BlenderExportService, "execute", autospec=True) as replay:
            retry_code, retry = self._run_cli(execution_id, destination)
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(retry_code, 0)
        self.assertEqual(retry["destination_path"], destination)
        self.assertTrue((self.runtime.project_root / destination).is_file())
        self.assertEqual(
            read_blender_production_adoption_receipt(self.runtime, execution_id).status,
            BlenderProductionAdoptionStatus.PUBLISHED,
        )

    def test_post_link_crash_is_ambiguous_and_cli_retry_never_overwrites_or_replays(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        source_bytes = OriginForgeLineage(self.runtime).local_artifact_path(
            binding.output_artifact_id
        ).read_bytes()
        destination = self.runtime.project_root / "assets/production/crash-window.glb"

        with patch.object(
            OriginForgeLineage,
            "create_artifact",
            autospec=True,
            side_effect=RuntimeError("injected post-link crash"),
        ):
            with self.assertRaisesRegex(RuntimeError, "post-link crash"):
                GovernedBlenderProductionOutputAdopter(self.runtime).adopt_new(
                    execution_id,
                    "assets/production/crash-window.glb",
                )

        self.assertEqual(destination.read_bytes(), source_bytes)
        receipt = read_blender_production_adoption_receipt(self.runtime, execution_id)
        self.assertEqual(receipt.status, BlenderProductionAdoptionStatus.PREPARED)
        self.assertIsNone(receipt.adopted_artifact_id)
        self.assertIsNone(receipt.verification_id)

        with patch.object(BlenderExportService, "execute", autospec=True) as replay:
            code, payload = self._run_cli(
                execution_id,
                "assets/production/crash-window.glb",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(code, 2)
        self.assertIn("recovery required", str(payload["detail"]))
        self.assertEqual(destination.read_bytes(), source_bytes)
        self.assertEqual(
            read_blender_production_adoption_receipt(self.runtime, execution_id).status,
            BlenderProductionAdoptionStatus.PREPARED,
        )

    def test_non_pass_adoption_integrity_fails_receipt_finalization_closed(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id
        destination = "assets/production/non-pass-integrity.glb"
        original = OriginForgeLineage.record_artifact_verification

        def record_fail(lineage, artifact_id, **kwargs):
            kwargs["status"] = "FAIL"
            return original(lineage, artifact_id, **kwargs)

        with patch.object(
            OriginForgeLineage,
            "record_artifact_verification",
            autospec=True,
            side_effect=record_fail,
        ):
            with self.assertRaisesRegex(
                BlenderProductionAdoptionError,
                "receipt finalization requires operator recovery",
            ):
                GovernedBlenderProductionOutputAdopter(self.runtime).adopt_new(
                    execution_id,
                    destination,
                )

        self.assertTrue((self.runtime.project_root / destination).is_file())
        receipt = read_blender_production_adoption_receipt(self.runtime, execution_id)
        self.assertEqual(receipt.status, BlenderProductionAdoptionStatus.PREPARED)
        self.assertIsNone(receipt.adopted_artifact_id)
        self.assertIsNone(receipt.verification_id)
        with self.runtime.store.session() as conn:
            fail_count = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE verification_type = 'blender-production-adoption-integrity'
                     AND status = 'FAIL'"""
            ).fetchone()[0]
        self.assertEqual(fail_count, 1)

    def test_blender_operator_remains_module_only_and_pixelorama_authority_is_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(
            project["scripts"],
            {
                "origin-forge": "origin_forge.cli:main",
                "origin-forge-attempt": "origin_forge.orchestration_cli:main",
                "origin-forge-cockpit": "origin_forge.production_interface_cli:main",
            },
        )
        self.assertNotIn("origin-forge-blender", project["scripts"])
        pixelorama_cli = (root / "src/origin_forge/pixelorama_admin_cli.py").read_text(
            encoding="utf-8"
        )
        pixelorama_adoption = (
            root / "src/origin_forge/production_pixelorama_adoption.py"
        ).read_text(encoding="utf-8")
        self.assertIn("adopt-production-new", pixelorama_cli)
        self.assertNotIn("blender_admin_cli", pixelorama_cli)
        self.assertNotIn("BlenderProduction", pixelorama_adoption)


if __name__ == "__main__":
    unittest.main()
