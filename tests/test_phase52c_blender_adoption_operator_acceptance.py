from __future__ import annotations

import io
import json
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from origin_forge import blender_admin_cli
from origin_forge.production_blender_adoption_receipt import (
    BlenderProductionAdoptionReceiptError,
    BlenderProductionAdoptionStatus,
    read_blender_production_adoption_receipt,
)
from origin_forge.production_blender_export import BlenderExportService
from test_phase52b_blender_production_adoption import Phase52BBlenderProductionAdoptionTests


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
        with self.assertRaises(BlenderProductionAdoptionReceiptError):
            read_blender_production_adoption_receipt(self.runtime, execution_id)

    def test_cli_rejects_protected_destination_before_reservation(self) -> None:
        completed = self._terminal_execution()
        execution_id = completed.execution.execution_id

        code, payload = self._run_cli(
            execution_id,
            ".origin-forge/forbidden.glb",
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "BlenderProductionAdoptionError")
        self.assertIn("protected", str(payload["detail"]).casefold())
        with self.assertRaises(BlenderProductionAdoptionReceiptError):
            read_blender_production_adoption_receipt(self.runtime, execution_id)

    def test_cli_rejects_malformed_execution_identity(self) -> None:
        code, payload = self._run_cli(
            "not-a-dispatch-execution-id",
            "assets/production/invalid.glb",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "ValueError")
        self.assertIn("DISPEXEC", str(payload["detail"]))

    def test_blender_operator_remains_module_only_and_package_scripts_are_frozen(self) -> None:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
        self.assertEqual(
            project["scripts"],
            {
                "origin-forge": "origin_forge.cli:main",
                "origin-forge-attempt": "origin_forge.orchestration_cli:main",
                "origin-forge-cockpit": "origin_forge.production_interface_cli:main",
            },
        )
        self.assertNotIn("origin-forge-blender", project["scripts"])


if __name__ == "__main__":
    unittest.main()
