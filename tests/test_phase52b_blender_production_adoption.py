from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from origin_forge.lineage import OriginForgeLineage
from origin_forge.production_blender_adoption import (
    BlenderProductionAdoptionError,
    GovernedBlenderProductionOutputAdopter,
)
from origin_forge.production_blender_adoption_receipt import (
    BLENDER_PRODUCTION_ADOPTION_VERIFICATION_TYPE,
    BLENDER_PRODUCTION_ADOPTION_VERIFIER,
    BlenderProductionAdoptionStatus,
    expected_blender_production_adoption_evidence,
    read_blender_production_adoption_receipt,
    reserve_blender_production_adoption,
)
from origin_forge.production_blender_dispatch_output_binding import (
    read_blender_dispatch_output_binding,
)
from origin_forge.production_blender_export import BlenderExportService
from origin_forge.production_dispatch_invocation import dispatch_claim_once
from origin_forge.service import utc_now
from test_phase51e_blender_invocation import Phase51EBlenderInvocationTests


class Phase52BBlenderProductionAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase51EBlenderInvocationTests(
            methodName=(
                "test_runtime_ids_allocate_only_after_started_service_runs_once_and_returns"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _invoke_successfully(self):
        fixture = self.fixture
        fixture.original_service_execute = BlenderExportService.execute
        with patch.dict(os.environ, fixture.env, clear=False), patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
            side_effect=fixture._real_service_with_fake_adapter,
        ) as execute:
            completed = dispatch_claim_once(
                fixture.runtime,
                fixture.claim.claim_id,
                0,
            )
        self.assertEqual(execute.call_count, 1)
        return completed

    def test_exact_terminal_blender_output_is_published_once_without_replay_or_task_authority(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(runtime, execution_id)
        lineage = OriginForgeLineage(runtime)
        source_path = lineage.local_artifact_path(binding.output_artifact_id)
        source_bytes = source_path.read_bytes()
        task_before = runtime.get_task(binding.task_id)

        with patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
        ) as replay:
            result = GovernedBlenderProductionOutputAdopter(runtime).adopt_new(
                execution_id,
                "assets/production/crate.glb",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(result.execution_id, execution_id)
        self.assertEqual(result.claim_id, binding.claim_id)
        self.assertEqual(result.task_id, binding.task_id)
        self.assertEqual(result.run_id, binding.run_id)
        self.assertEqual(result.source_artifact_id, binding.output_artifact_id)
        self.assertEqual(result.content_hash, "sha256:" + binding.output_content_hash)
        self.assertEqual(result.byte_count, binding.output_byte_count)
        self.assertEqual(
            (runtime.project_root / result.destination_path).read_bytes(),
            source_bytes,
        )

        adopted = lineage.get_artifact(result.adopted_artifact_id)
        self.assertEqual(adopted["type"], "BLENDER_GLB_EXPORT")
        self.assertEqual(adopted["status"], "ADOPTED")
        self.assertEqual(adopted["path_or_uri"], result.destination_path)
        self.assertEqual(adopted["parent_artifact_id"], binding.output_artifact_id)
        self.assertEqual(adopted["created_by_run_id"], binding.run_id)
        self.assertEqual(adopted["content_hash"], result.content_hash)

        matches = [
            item
            for item in lineage.list_artifact_verifications(result.adopted_artifact_id)
            if item["id"] == result.verification_id
        ]
        self.assertEqual(len(matches), 1)
        verification = matches[0]
        self.assertEqual(
            verification["verification_type"],
            BLENDER_PRODUCTION_ADOPTION_VERIFICATION_TYPE,
        )
        self.assertEqual(verification["verifier"], BLENDER_PRODUCTION_ADOPTION_VERIFIER)
        self.assertEqual(verification["status"], "PASS")
        self.assertEqual(verification["run_id"], binding.run_id)
        self.assertEqual(
            json.loads(verification["evidence_json"]),
            expected_blender_production_adoption_evidence(
                binding,
                result.destination_path,
            ),
        )

        receipt = read_blender_production_adoption_receipt(runtime, execution_id)
        self.assertEqual(receipt.status, BlenderProductionAdoptionStatus.PUBLISHED)
        self.assertEqual(receipt.output_artifact_id, binding.output_artifact_id)
        self.assertEqual(receipt.destination_path, result.destination_path)
        self.assertEqual(receipt.adopted_artifact_id, result.adopted_artifact_id)
        self.assertEqual(receipt.verification_id, result.verification_id)

        task_after = runtime.get_task(binding.task_id)
        self.assertEqual(task_after["status"], "RUNNING")
        self.assertEqual(task_after["revision"], task_before["revision"])
        self.assertEqual(runtime.list_verifications("TASK", binding.task_id), [])
        projection = result.to_dict()
        self.assertFalse(projection["production_task_verified"])
        self.assertFalse(projection["semantic_geometry_verified"])
        self.assertFalse(projection["provenance_signed"])
        self.assertFalse(projection["existing_asset_overwritten"])
        self.assertTrue(projection["production_dispatch_output_bound"])

    def test_one_execution_cannot_fan_out_to_second_destination(self) -> None:
        completed = self._invoke_successfully()
        execution_id = completed.execution.execution_id
        adopter = GovernedBlenderProductionOutputAdopter(self.fixture.runtime)
        adopter.adopt_new(execution_id, "assets/first.glb")

        with self.assertRaisesRegex(BlenderProductionAdoptionError, "already"):
            adopter.adopt_new(execution_id, "assets/second.glb")
        self.assertFalse((self.fixture.runtime.project_root / "assets/second.glb").exists())
        with self.fixture.runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM blender_production_adoptions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_exact_prepared_reservation_retries_only_while_destination_is_absent(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(runtime, execution_id)
        reserved = reserve_blender_production_adoption(
            runtime,
            binding,
            "assets/retry.glb",
            utc_now(),
        )
        self.assertEqual(reserved.status, BlenderProductionAdoptionStatus.PREPARED)

        result = GovernedBlenderProductionOutputAdopter(runtime).adopt_new(
            execution_id,
            "assets/retry.glb",
        )
        self.assertEqual(result.destination_path, "assets/retry.glb")
        self.assertEqual(
            read_blender_production_adoption_receipt(runtime, execution_id).status,
            BlenderProductionAdoptionStatus.PUBLISHED,
        )

    def test_prepared_receipt_plus_existing_destination_requires_operator_recovery(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(runtime, execution_id)
        reserve_blender_production_adoption(
            runtime,
            binding,
            "assets/ambiguous.glb",
            utc_now(),
        )
        destination = runtime.project_root / "assets/ambiguous.glb"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"ambiguous-existing-file")

        with self.assertRaisesRegex(BlenderProductionAdoptionError, "recovery required"):
            GovernedBlenderProductionOutputAdopter(runtime).adopt_new(
                execution_id,
                "assets/ambiguous.glb",
            )
        self.assertEqual(destination.read_bytes(), b"ambiguous-existing-file")
        receipt = read_blender_production_adoption_receipt(runtime, execution_id)
        self.assertEqual(receipt.status, BlenderProductionAdoptionStatus.PREPARED)
        self.assertIsNone(receipt.adopted_artifact_id)
        self.assertIsNone(receipt.verification_id)

    def test_durable_glb_drift_fails_before_reservation_or_publication(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        execution_id = completed.execution.execution_id
        binding = read_blender_dispatch_output_binding(runtime, execution_id)
        source = OriginForgeLineage(runtime).local_artifact_path(binding.output_artifact_id)
        source.write_bytes(b"tampered-before-production-adoption")

        with self.assertRaisesRegex(BlenderProductionAdoptionError, "not adoption eligible"):
            GovernedBlenderProductionOutputAdopter(runtime).adopt_new(
                execution_id,
                "assets/tampered.glb",
            )
        self.assertFalse((runtime.project_root / "assets/tampered.glb").exists())
        with runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM blender_production_adoptions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_existing_destination_and_byte_limit_fail_without_overwrite_or_receipt(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        execution_id = completed.execution.execution_id
        destination = runtime.project_root / "assets/existing.glb"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"keep-me")

        with self.assertRaisesRegex(BlenderProductionAdoptionError, "create-only"):
            GovernedBlenderProductionOutputAdopter(runtime).adopt_new(
                execution_id,
                "assets/existing.glb",
            )
        self.assertEqual(destination.read_bytes(), b"keep-me")
        with runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM blender_production_adoptions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()[0]
        self.assertEqual(count, 0)

        with self.assertRaisesRegex(BlenderProductionAdoptionError, "byte limit"):
            GovernedBlenderProductionOutputAdopter(
                runtime,
                max_source_bytes=1,
            ).adopt_new(
                execution_id,
                "assets/too-large.glb",
            )
        self.assertFalse((runtime.project_root / "assets/too-large.glb").exists())
        with runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM blender_production_adoptions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
