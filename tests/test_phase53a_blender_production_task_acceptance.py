from __future__ import annotations

import inspect
import json
import sqlite3
import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id
from origin_forge.production_blender_adoption import (
    GovernedBlenderProductionOutputAdopter,
)
from origin_forge.production_blender_adoption_receipt import (
    read_blender_production_adoption_receipt,
)
from origin_forge.production_blender_dispatch_output_binding import (
    read_blender_dispatch_output_binding,
)
from origin_forge.production_blender_task_acceptance import (
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION,
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFIER,
    BlenderProductionTaskAcceptanceConflict,
    BlenderProductionTaskAcceptanceError,
    publish_blender_production_task_acceptance,
    read_blender_production_task_acceptance,
)
from origin_forge.production_dispatch_read import read_dispatch_binding
from test_phase52b_blender_production_adoption import (
    Phase52BBlenderProductionAdoptionTests,
)


class Phase53ABlenderProductionTaskAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase52BBlenderProductionAdoptionTests(
            methodName=(
                "test_exact_terminal_blender_output_is_published_once_without_replay_or_task_authority"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _published_inputs(self):
        completed = self.fixture._invoke_successfully()
        runtime = self.fixture.fixture.runtime
        execution_id = completed.execution.execution_id
        output_binding = read_blender_dispatch_output_binding(runtime, execution_id)
        GovernedBlenderProductionOutputAdopter(runtime).adopt_new(
            execution_id,
            "assets/production/phase53a-model.glb",
        )
        adoption = read_blender_production_adoption_receipt(runtime, execution_id)
        dispatch_binding = read_dispatch_binding(
            runtime,
            output_binding.dispatch_binding_id,
        )
        task = runtime.get_task(output_binding.task_id)
        return (
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            int(task["revision"]),
        )

    def test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task(self) -> None:
        (
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision,
        ) = self._published_inputs()
        task_before = runtime.get_task(output_binding.task_id)
        projection = dispatch_binding.request_projection
        with runtime.store.session() as conn:
            before_verifications = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?""",
                (output_binding.task_id,),
            ).fetchone()[0]
            before_events = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'""",
                (output_binding.task_id,),
            ).fetchone()[0]

        receipt = publish_blender_production_task_acceptance(
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision_at_acceptance=task_revision,
            actor_id="operator.phase53a",
        )

        self.assertEqual(receipt.execution_id, output_binding.execution_id)
        self.assertEqual(receipt.task_id, output_binding.task_id)
        self.assertEqual(receipt.adopted_artifact_id, adoption.adopted_artifact_id)
        self.assertEqual(receipt.adoption_verification_id, adoption.verification_id)
        self.assertEqual(receipt.task_revision_at_acceptance, task_revision)
        self.assertEqual(
            receipt.accepted_content_hash,
            "sha256:" + output_binding.output_content_hash,
        )
        self.assertEqual(receipt.accepted_byte_count, output_binding.output_byte_count)
        self.assertEqual(receipt.accepted_destination_path, adoption.destination_path)
        self.assertEqual(
            receipt.acceptance_authority,
            BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
        )
        self.assertEqual(
            receipt.schema_version,
            BLENDER_PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION,
        )
        self.assertEqual(
            read_blender_production_task_acceptance(
                runtime,
                output_binding.execution_id,
            ),
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
                (output_binding.task_id,),
            ).fetchone()[0]
            event = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'
                   ORDER BY rowid DESC LIMIT 1""",
                (output_binding.task_id,),
            ).fetchone()
            event_count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'""",
                (output_binding.task_id,),
            ).fetchone()[0]
            acceptance_count = conn.execute(
                "SELECT COUNT(*) FROM blender_production_task_acceptances"
            ).fetchone()[0]

        self.assertEqual(verification_count, before_verifications + 1)
        self.assertEqual(event_count, before_events + 1)
        self.assertEqual(acceptance_count, 1)
        self.assertEqual(verification["target_type"], "TASK")
        self.assertEqual(verification["target_id"], output_binding.task_id)
        self.assertEqual(
            verification["verification_type"],
            BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
        )
        self.assertEqual(
            verification["verifier"],
            BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFIER,
        )
        self.assertEqual(verification["status"], "PASS")
        self.assertEqual(verification["run_id"], output_binding.run_id)
        self.assertEqual(json.loads(verification["metrics_json"]), {})
        evidence = json.loads(verification["evidence_json"])
        self.assertTrue(evidence["production_task_verified"])
        self.assertTrue(evidence["semantic_geometry_verified"])
        self.assertEqual(evidence["acceptance_authority"], "HUMAN_OPERATOR")
        self.assertTrue(evidence["production_dispatch_output_bound"])
        self.assertTrue(evidence["canonical_asset_adopted"])
        self.assertFalse(evidence["existing_asset_overwritten"])
        self.assertFalse(evidence["provenance_signed"])
        self.assertFalse(evidence["release_authorized"])
        self.assertEqual(evidence["dispatch_execution_id"], output_binding.execution_id)
        self.assertEqual(evidence["production_claim_id"], output_binding.claim_id)
        self.assertEqual(evidence["production_run_id"], output_binding.run_id)
        self.assertEqual(evidence["work_order_id"], output_binding.work_order_id)
        self.assertEqual(
            evidence["model3d_request_id"],
            projection["model3d_request_id"],
        )
        self.assertEqual(
            evidence["model3d_request_hash"],
            projection["model3d_request_hash"],
        )
        self.assertEqual(
            evidence["source_output_artifact_id"],
            output_binding.output_artifact_id,
        )
        self.assertEqual(
            evidence["production_adoption_verification_id"],
            adoption.verification_id,
        )
        self.assertEqual(evidence["adopted_artifact_id"], adoption.adopted_artifact_id)
        self.assertEqual(evidence["adopted_destination_path"], adoption.destination_path)
        self.assertEqual(evidence["task_content_hash"], output_binding.task_content_hash)
        self.assertEqual(evidence["task_revision_at_acceptance"], task_revision)
        self.assertEqual(event["new_state"], "PASS")
        self.assertEqual(event["actor_type"], "HUMAN")
        self.assertEqual(event["actor_id"], "operator.phase53a")
        self.assertEqual(
            json.loads(event["metadata_json"])["verification_id"],
            receipt.task_verification_id,
        )

        task_after = runtime.get_task(output_binding.task_id)
        self.assertEqual(task_after["status"], "RUNNING")
        self.assertEqual(task_after["revision"], task_before["revision"])

    def test_exact_replay_reuses_receipt_and_changed_revision_conflicts(self) -> None:
        (
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision,
        ) = self._published_inputs()
        first = publish_blender_production_task_acceptance(
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision_at_acceptance=task_revision,
        )
        second = publish_blender_production_task_acceptance(
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision_at_acceptance=task_revision,
        )
        self.assertEqual(second, first)

        with self.assertRaises(BlenderProductionTaskAcceptanceConflict):
            publish_blender_production_task_acceptance(
                runtime,
                output_binding,
                adoption,
                dispatch_binding,
                task_revision_at_acceptance=task_revision + 1,
            )

        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications
                       WHERE target_type = 'TASK' AND target_id = ?
                             AND verification_type = ?""",
                    (
                        output_binding.task_id,
                        BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    ),
                ).fetchone()[0],
                1,
            )

    def test_receipt_insert_failure_rolls_back_task_pass_and_event(self) -> None:
        (
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision,
        ) = self._published_inputs()
        with runtime.store.session() as conn:
            conn.execute(
                """CREATE TRIGGER phase53a_force_acceptance_failure
                   BEFORE INSERT ON blender_production_task_acceptances
                   BEGIN
                       SELECT RAISE(ABORT, 'forced phase53a acceptance failure');
                   END"""
            )
            before_verifications = conn.execute(
                "SELECT COUNT(*) FROM verifications WHERE target_type = 'TASK' AND target_id = ?",
                (output_binding.task_id,),
            ).fetchone()[0]
            before_events = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'VERIFICATION_RECORDED'""",
                (output_binding.task_id,),
            ).fetchone()[0]

        with self.assertRaises(BlenderProductionTaskAcceptanceConflict):
            publish_blender_production_task_acceptance(
                runtime,
                output_binding,
                adoption,
                dispatch_binding,
                task_revision_at_acceptance=task_revision,
            )

        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM verifications WHERE target_type = 'TASK' AND target_id = ?",
                    (output_binding.task_id,),
                ).fetchone()[0],
                before_verifications,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM state_events
                       WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                             AND event_type = 'VERIFICATION_RECORDED'""",
                    (output_binding.task_id,),
                ).fetchone()[0],
                before_events,
            )

    def test_receipt_is_immutable_and_acceptance_semantics_are_not_caller_overridable(self) -> None:
        (
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision,
        ) = self._published_inputs()
        receipt = publish_blender_production_task_acceptance(
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision_at_acceptance=task_revision,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            with runtime.store.session() as conn:
                conn.execute(
                    """UPDATE blender_production_task_acceptances
                       SET acceptance_authority = 'MODEL'
                       WHERE execution_id = ?""",
                    (receipt.execution_id,),
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with runtime.store.session() as conn:
                conn.execute(
                    "DELETE FROM blender_production_task_acceptances WHERE execution_id = ?",
                    (receipt.execution_id,),
                )

        parameters = inspect.signature(
            publish_blender_production_task_acceptance
        ).parameters
        for forbidden in (
            "acceptance_authority",
            "verification_type",
            "verifier",
            "verification_status",
            "target_type",
            "target_id",
            "model3d_request_id",
            "model3d_request_hash",
        ):
            self.assertNotIn(forbidden, parameters)

    def test_semantic_request_identity_cannot_be_substituted_outside_frozen_dispatch_binding(self) -> None:
        (
            runtime,
            output_binding,
            adoption,
            dispatch_binding,
            task_revision,
        ) = self._published_inputs()
        projection = dict(dispatch_binding.request_projection)
        projection["model3d_request_id"] = new_id(IdKind.MODEL3D_REQUEST)
        forged = replace(
            dispatch_binding,
            request_projection_json=json.dumps(
                projection,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

        with self.assertRaisesRegex(
            BlenderProductionTaskAcceptanceError,
            "does not match the exact Blender production relation",
        ):
            publish_blender_production_task_acceptance(
                runtime,
                output_binding,
                adoption,
                forged,
                task_revision_at_acceptance=task_revision,
            )

        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications
                       WHERE target_type = 'TASK' AND target_id = ?
                             AND verification_type = ?""",
                    (
                        output_binding.task_id,
                        BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    ),
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
