from __future__ import annotations

import inspect
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from origin_forge.production_dispatch_invocation import dispatch_claim_once
from origin_forge.production_pixelorama_adoption import (
    GovernedPixeloramaProductionOutputAdopter,
)
from origin_forge.production_pixelorama_adoption_receipt import (
    read_pixelorama_production_adoption_receipt,
)
from origin_forge.production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from origin_forge.production_pixelorama_export import PixeloramaCliExportService
from origin_forge.production_pixelorama_task_acceptance import (
    PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
    PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION,
    PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    PRODUCTION_TASK_ACCEPTANCE_VERIFIER,
    PixeloramaProductionTaskAcceptanceConflict,
    publish_pixelorama_production_task_acceptance,
    read_pixelorama_production_task_acceptance,
)
from .test_phase48f_pixelorama_invocation import Phase48FPixeloramaInvocationTests


class Phase50APixeloramaProductionTaskAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase48FPixeloramaInvocationTests(
            methodName=(
                "test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _published_inputs(self):
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
        binding = read_pixelorama_dispatch_output_binding(
            fixture.runtime,
            completed.execution_id,
        )
        result = GovernedPixeloramaProductionOutputAdopter(fixture.runtime).adopt_new(
            completed.execution_id,
            "assets/production/phase50a-sprite.png",
        )
        adoption = read_pixelorama_production_adoption_receipt(
            fixture.runtime,
            completed.execution_id,
        )
        self.assertEqual(adoption.adopted_artifact_id, result.adopted_artifact_id)
        task = fixture.runtime.get_task(binding.task_id)
        return binding, adoption, int(task["revision"])

    def test_acceptance_atomically_records_exact_task_pass_and_receipt_without_terminalizing_task(self) -> None:
        runtime = self.fixture.runtime
        binding, adoption, task_revision = self._published_inputs()
        task_before = runtime.get_task(binding.task_id)
        with runtime.store.session() as conn:
            before_verifications = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?""",
                (binding.task_id,),
            ).fetchone()[0]
            before_events = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'""",
                (binding.task_id,),
            ).fetchone()[0]

        receipt = publish_pixelorama_production_task_acceptance(
            runtime,
            binding,
            adoption,
            task_revision_at_acceptance=task_revision,
            actor_id="operator.phase50a",
        )

        self.assertEqual(receipt.execution_id, binding.execution_id)
        self.assertEqual(receipt.task_id, binding.task_id)
        self.assertEqual(receipt.adopted_artifact_id, adoption.adopted_artifact_id)
        self.assertEqual(receipt.adoption_verification_id, adoption.verification_id)
        self.assertEqual(receipt.task_revision_at_acceptance, task_revision)
        self.assertEqual(
            receipt.accepted_content_hash,
            "sha256:" + binding.output_content_hash,
        )
        self.assertEqual(receipt.accepted_byte_count, binding.output_byte_count)
        self.assertEqual(receipt.accepted_destination_path, adoption.destination_path)
        self.assertEqual(receipt.acceptance_authority, PRODUCTION_TASK_ACCEPTANCE_AUTHORITY)
        self.assertEqual(receipt.schema_version, PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION)
        self.assertEqual(
            read_pixelorama_production_task_acceptance(runtime, binding.execution_id),
            receipt,
        )

        with runtime.store.session() as conn:
            verification = conn.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (receipt.task_verification_id,),
            ).fetchone()
            verification_count = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?""",
                (binding.task_id,),
            ).fetchone()[0]
            event = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'
                   ORDER BY rowid DESC LIMIT 1""",
                (binding.task_id,),
            ).fetchone()
            event_count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'""",
                (binding.task_id,),
            ).fetchone()[0]
            acceptance_count = conn.execute(
                "SELECT COUNT(*) FROM pixelorama_production_task_acceptances"
            ).fetchone()[0]

        self.assertEqual(verification_count, before_verifications + 1)
        self.assertEqual(event_count, before_events + 1)
        self.assertEqual(acceptance_count, 1)
        self.assertEqual(verification["target_type"], "TASK")
        self.assertEqual(verification["target_id"], binding.task_id)
        self.assertEqual(
            verification["verification_type"],
            PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
        )
        self.assertEqual(verification["verifier"], PRODUCTION_TASK_ACCEPTANCE_VERIFIER)
        self.assertEqual(verification["status"], "PASS")
        self.assertEqual(verification["run_id"], binding.run_id)
        self.assertEqual(json.loads(verification["metrics_json"]), {})
        evidence = json.loads(verification["evidence_json"])
        self.assertEqual(evidence["acceptance_authority"], "HUMAN_OPERATOR")
        self.assertEqual(evidence["dispatch_execution_id"], binding.execution_id)
        self.assertEqual(evidence["production_claim_id"], binding.claim_id)
        self.assertEqual(evidence["production_run_id"], binding.run_id)
        self.assertEqual(evidence["source_output_artifact_id"], binding.output_artifact_id)
        self.assertEqual(evidence["adopted_artifact_id"], adoption.adopted_artifact_id)
        self.assertEqual(
            evidence["production_adoption_verification_id"],
            adoption.verification_id,
        )
        self.assertTrue(evidence["production_task_verified"])
        self.assertTrue(evidence["semantic_visual_quality_verified"])
        self.assertTrue(evidence["canonical_asset_adopted"])
        self.assertFalse(evidence["provenance_signed"])
        self.assertFalse(evidence["release_authorized"])
        self.assertEqual(event["new_state"], "PASS")
        self.assertEqual(event["actor_type"], "HUMAN")
        self.assertEqual(event["actor_id"], "operator.phase50a")
        self.assertEqual(
            json.loads(event["metadata_json"])["verification_id"],
            receipt.task_verification_id,
        )

        task_after = runtime.get_task(binding.task_id)
        self.assertEqual(task_after["status"], "RUNNING")
        self.assertEqual(task_after["revision"], task_before["revision"])

    def test_exact_replay_reuses_receipt_and_pass_while_changed_revision_conflicts(self) -> None:
        runtime = self.fixture.runtime
        binding, adoption, task_revision = self._published_inputs()
        first = publish_pixelorama_production_task_acceptance(
            runtime,
            binding,
            adoption,
            task_revision_at_acceptance=task_revision,
        )
        second = publish_pixelorama_production_task_acceptance(
            runtime,
            binding,
            adoption,
            task_revision_at_acceptance=task_revision,
        )
        self.assertEqual(second, first)

        with self.assertRaises(PixeloramaProductionTaskAcceptanceConflict):
            publish_pixelorama_production_task_acceptance(
                runtime,
                binding,
                adoption,
                task_revision_at_acceptance=task_revision + 1,
            )

        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM pixelorama_production_task_acceptances"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications
                       WHERE target_type = 'TASK' AND target_id = ?
                             AND verification_type = ?""",
                    (binding.task_id, PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE),
                ).fetchone()[0],
                1,
            )

    def test_acceptance_insert_failure_rolls_back_task_pass_and_event(self) -> None:
        runtime = self.fixture.runtime
        binding, adoption, task_revision = self._published_inputs()
        with runtime.store.session() as conn:
            conn.execute(
                """CREATE TRIGGER phase50a_force_acceptance_failure
                   BEFORE INSERT ON pixelorama_production_task_acceptances
                   BEGIN
                       SELECT RAISE(ABORT, 'forced phase50a acceptance failure');
                   END"""
            )
            before_verifications = conn.execute(
                "SELECT COUNT(*) FROM verifications WHERE target_type = 'TASK' AND target_id = ?",
                (binding.task_id,),
            ).fetchone()[0]
            before_events = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'""",
                (binding.task_id,),
            ).fetchone()[0]

        with self.assertRaises(PixeloramaProductionTaskAcceptanceConflict):
            publish_pixelorama_production_task_acceptance(
                runtime,
                binding,
                adoption,
                task_revision_at_acceptance=task_revision,
            )

        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM pixelorama_production_task_acceptances"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM verifications WHERE target_type = 'TASK' AND target_id = ?",
                    (binding.task_id,),
                ).fetchone()[0],
                before_verifications,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM state_events
                       WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                             AND event_type = 'VERIFICATION_RECORDED'""",
                    (binding.task_id,),
                ).fetchone()[0],
                before_events,
            )

    def test_receipt_is_insert_only_and_acceptance_semantics_are_not_caller_overridable(self) -> None:
        runtime = self.fixture.runtime
        binding, adoption, task_revision = self._published_inputs()
        receipt = publish_pixelorama_production_task_acceptance(
            runtime,
            binding,
            adoption,
            task_revision_at_acceptance=task_revision,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            with runtime.store.session() as conn:
                conn.execute(
                    """UPDATE pixelorama_production_task_acceptances
                       SET acceptance_authority = 'MODEL'
                       WHERE execution_id = ?""",
                    (receipt.execution_id,),
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with runtime.store.session() as conn:
                conn.execute(
                    "DELETE FROM pixelorama_production_task_acceptances WHERE execution_id = ?",
                    (receipt.execution_id,),
                )

        parameters = inspect.signature(
            publish_pixelorama_production_task_acceptance
        ).parameters
        for forbidden in (
            "acceptance_authority",
            "verification_type",
            "verifier",
            "verification_status",
            "target_type",
            "target_id",
        ):
            self.assertNotIn(forbidden, parameters)


if __name__ == "__main__":
    unittest.main()
