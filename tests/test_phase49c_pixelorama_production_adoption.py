from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_adoption import (
    GovernedPixeloramaOutputAdopter,
    PixeloramaAdoptionError,
)
from origin_forge.production_dispatch_invocation import dispatch_claim_once
from origin_forge.production_pixelorama_adoption import (
    GovernedPixeloramaProductionOutputAdopter,
    PixeloramaProductionAdoptionError,
)
from origin_forge.production_pixelorama_adoption_receipt import (
    PRODUCTION_ADOPTION_VERIFICATION_TYPE,
    PRODUCTION_ADOPTION_VERIFIER,
    PixeloramaProductionAdoptionStatus,
    read_pixelorama_production_adoption_receipt,
    reserve_pixelorama_production_adoption,
)
from origin_forge.production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from origin_forge.production_pixelorama_export import PixeloramaCliExportService
from origin_forge.service import utc_now
from test_phase48f_pixelorama_invocation import Phase48FPixeloramaInvocationTests


class Phase49CPixeloramaProductionAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase48FPixeloramaInvocationTests(
            methodName=(
                "test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _invoke_successfully(self):
        fixture = self.fixture
        fixture.original_service_execute = PixeloramaCliExportService.execute
        with patch.dict(os.environ, fixture.env, clear=False), patch.object(
            PixeloramaCliExportService,
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

    def test_exact_terminal_dispatch_output_is_published_once_without_task_or_signing_authority(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        binding = read_pixelorama_dispatch_output_binding(
            runtime,
            completed.execution_id,
        )
        lineage = OriginForgeLineage(runtime)
        source_path = lineage.local_artifact_path(binding.output_artifact_id)
        task_before = runtime.get_task(binding.task_id)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            result = GovernedPixeloramaProductionOutputAdopter(runtime).adopt_new(
                completed.execution_id,
                "assets/production/sprite.png",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(result.execution_id, completed.execution_id)
        self.assertEqual(result.claim_id, binding.claim_id)
        self.assertEqual(result.task_id, binding.task_id)
        self.assertEqual(result.run_id, binding.run_id)
        self.assertEqual(result.source_artifact_id, binding.output_artifact_id)
        self.assertEqual(result.content_hash, "sha256:" + binding.output_content_hash)
        self.assertEqual(result.byte_count, binding.output_byte_count)
        self.assertEqual(
            (runtime.project_root / result.destination_path).read_bytes(),
            source_path.read_bytes(),
        )

        adopted = lineage.get_artifact(result.adopted_artifact_id)
        self.assertEqual(adopted["type"], "SPRITESHEET_EXPORT")
        self.assertEqual(adopted["status"], "ADOPTED")
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
            PRODUCTION_ADOPTION_VERIFICATION_TYPE,
        )
        self.assertEqual(verification["verifier"], PRODUCTION_ADOPTION_VERIFIER)
        self.assertEqual(verification["status"], "PASS")
        self.assertEqual(verification["run_id"], binding.run_id)
        evidence = json.loads(verification["evidence_json"])
        self.assertEqual(evidence["source_artifact_id"], binding.output_artifact_id)
        self.assertEqual(evidence["source_content_hash"], result.content_hash)
        self.assertEqual(evidence["source_byte_count"], binding.output_byte_count)
        self.assertEqual(evidence["destination_path"], result.destination_path)
        self.assertEqual(evidence["destination_content_hash"], result.content_hash)
        self.assertFalse(evidence["existing_asset_overwritten"])
        self.assertTrue(evidence["production_dispatch_output_bound"])
        self.assertEqual(evidence["dispatch_execution_id"], binding.execution_id)
        self.assertEqual(evidence["dispatch_claim_id"], binding.claim_id)
        self.assertEqual(evidence["production_run_id"], binding.run_id)
        self.assertFalse(evidence["production_task_verified"])
        self.assertFalse(evidence["semantic_visual_quality_verified"])
        self.assertFalse(evidence["provenance_signed"])

        receipt = read_pixelorama_production_adoption_receipt(
            runtime,
            completed.execution_id,
        )
        self.assertEqual(receipt.status, PixeloramaProductionAdoptionStatus.PUBLISHED)
        self.assertEqual(receipt.output_artifact_id, binding.output_artifact_id)
        self.assertEqual(receipt.destination_path, result.destination_path)
        self.assertEqual(receipt.adopted_artifact_id, result.adopted_artifact_id)
        self.assertEqual(receipt.verification_id, result.verification_id)

        task_after = runtime.get_task(binding.task_id)
        self.assertEqual(task_after["status"], "RUNNING")
        self.assertEqual(task_after["revision"], task_before["revision"])
        self.assertEqual(runtime.list_verifications("TASK", binding.task_id), [])
        self.assertFalse(result.to_dict()["production_task_verified"])
        self.assertFalse(result.to_dict()["semantic_visual_quality_verified"])
        self.assertFalse(result.to_dict()["provenance_signed"])

    def test_phase48_output_does_not_gain_legacy_phase19_adoption_eligibility(self) -> None:
        completed = self._invoke_successfully()
        binding = read_pixelorama_dispatch_output_binding(
            self.fixture.runtime,
            completed.execution_id,
        )
        with self.assertRaisesRegex(PixeloramaAdoptionError, "lacks PASS"):
            GovernedPixeloramaOutputAdopter(self.fixture.runtime).adopt_new(
                binding.output_artifact_id,
                "assets/legacy-bypass.png",
            )
        self.assertFalse((self.fixture.runtime.project_root / "assets/legacy-bypass.png").exists())

    def test_one_execution_cannot_fan_out_to_second_destination(self) -> None:
        completed = self._invoke_successfully()
        adopter = GovernedPixeloramaProductionOutputAdopter(self.fixture.runtime)
        adopter.adopt_new(completed.execution_id, "assets/first.png")
        with self.assertRaisesRegex(PixeloramaProductionAdoptionError, "already"):
            adopter.adopt_new(completed.execution_id, "assets/second.png")
        self.assertFalse((self.fixture.runtime.project_root / "assets/second.png").exists())
        with self.fixture.runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM pixelorama_production_adoptions WHERE execution_id = ?",
                (completed.execution_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_exact_prepared_reservation_is_retryable_only_before_destination_publication(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        binding = read_pixelorama_dispatch_output_binding(runtime, completed.execution_id)
        reserved = reserve_pixelorama_production_adoption(
            runtime,
            binding,
            "assets/retry.png",
            utc_now(),
        )
        self.assertEqual(reserved.status, PixeloramaProductionAdoptionStatus.PREPARED)

        result = GovernedPixeloramaProductionOutputAdopter(runtime).adopt_new(
            completed.execution_id,
            "assets/retry.png",
        )
        self.assertEqual(result.destination_path, "assets/retry.png")
        self.assertEqual(
            read_pixelorama_production_adoption_receipt(
                runtime,
                completed.execution_id,
            ).status,
            PixeloramaProductionAdoptionStatus.PUBLISHED,
        )

    def test_prepared_receipt_plus_existing_destination_requires_operator_recovery(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        binding = read_pixelorama_dispatch_output_binding(runtime, completed.execution_id)
        reserve_pixelorama_production_adoption(
            runtime,
            binding,
            "assets/ambiguous.png",
            utc_now(),
        )
        destination = runtime.project_root / "assets/ambiguous.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"ambiguous-existing-file")

        with self.assertRaisesRegex(PixeloramaProductionAdoptionError, "recovery required"):
            GovernedPixeloramaProductionOutputAdopter(runtime).adopt_new(
                completed.execution_id,
                "assets/ambiguous.png",
            )
        self.assertEqual(destination.read_bytes(), b"ambiguous-existing-file")
        receipt = read_pixelorama_production_adoption_receipt(
            runtime,
            completed.execution_id,
        )
        self.assertEqual(receipt.status, PixeloramaProductionAdoptionStatus.PREPARED)
        self.assertIsNone(receipt.adopted_artifact_id)
        self.assertIsNone(receipt.verification_id)

    def test_durable_output_drift_fails_before_reservation_or_destination_publication(self) -> None:
        completed = self._invoke_successfully()
        runtime = self.fixture.runtime
        binding = read_pixelorama_dispatch_output_binding(runtime, completed.execution_id)
        output = OriginForgeLineage(runtime).local_artifact_path(binding.output_artifact_id)
        output.write_bytes(b"tampered-before-production-adoption")
        with self.assertRaisesRegex(PixeloramaProductionAdoptionError, "not adoption eligible"):
            GovernedPixeloramaProductionOutputAdopter(runtime).adopt_new(
                completed.execution_id,
                "assets/tampered.png",
            )
        self.assertFalse((runtime.project_root / "assets/tampered.png").exists())
        with runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM pixelorama_production_adoptions WHERE execution_id = ?",
                (completed.execution_id,),
            ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
