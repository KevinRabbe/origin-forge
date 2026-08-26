from __future__ import annotations

import os
import sqlite3
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
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
    PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    publish_pixelorama_production_task_acceptance,
)
from origin_forge.production_pixelorama_task_acceptance_currentness import (
    PixeloramaProductionTaskAcceptanceCurrentnessStatus,
    inspect_pixelorama_production_task_acceptance_currentness_readonly,
)
from origin_forge.production_pixelorama_task_acceptor import (
    GovernedPixeloramaProductionTaskAcceptor,
    PixeloramaProductionTaskAcceptorError,
)
from origin_forge.service import StaleRevision
from origin_forge.state import RunStatus
from test_phase48f_pixelorama_invocation import Phase48FPixeloramaInvocationTests


class Phase50DPixeloramaProductionTaskAcceptanceAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase48FPixeloramaInvocationTests(
            methodName=(
                "test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _executed_inputs(self):
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
        return completed.execution_id, binding

    def _published_inputs(self, destination: str):
        execution_id, binding = self._executed_inputs()
        adopted = GovernedPixeloramaProductionOutputAdopter(
            self.fixture.runtime
        ).adopt_new(execution_id, destination)
        adoption = read_pixelorama_production_adoption_receipt(
            self.fixture.runtime,
            execution_id,
        )
        self.assertEqual(adoption.adopted_artifact_id, adopted.adopted_artifact_id)
        return execution_id, binding, adoption

    def _phase50_counts(self, task_id: str) -> tuple[int, int, int]:
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            verification_count = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?
                         AND verification_type = ?""",
                (task_id, PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE),
            ).fetchone()[0]
            acceptance_count = conn.execute(
                "SELECT COUNT(*) FROM pixelorama_production_task_acceptances"
            ).fetchone()[0]
            transition_count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'TASK_STATUS_CHANGED'
                         AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'""",
                (task_id,),
            ).fetchone()[0]
        return int(verification_count), int(acceptance_count), int(transition_count)

    def _assert_stale_rejected(self, execution_id: str, task_id: str) -> str:
        runtime = self.fixture.runtime
        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        with self.assertRaises(PixeloramaProductionTaskAcceptorError):
            GovernedPixeloramaProductionTaskAcceptor(runtime).accept(execution_id)
        self.assertEqual(self._phase50_counts(task_id), (0, 0, 0))
        return current.detail or ""

    def test_missing_dispatch_output_binding_fails_closed_before_phase50_authority(self) -> None:
        execution_id, binding = self._executed_inputs()
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                "DELETE FROM pixelorama_dispatch_output_bindings WHERE execution_id = ?",
                (execution_id,),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertIn("binding does not exist", detail)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")

    def test_tampered_frozen_dispatch_execution_task_identity_fails_closed(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-dispatch-tamper.png"
        )
        runtime = self.fixture.runtime
        task = runtime.get_task(binding.task_id)
        wrong_task_id = runtime.create_task(task["flow_id"], "unrelated production task")
        with runtime.store.session() as conn:
            conn.execute(
                "UPDATE dispatch_executions SET task_id = ? WHERE execution_id = ?",
                (wrong_task_id, execution_id),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertIn("frozen dispatch execution authority", detail)

    def test_non_returned_execution_and_non_consumed_claim_are_not_acceptance_authority(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-dispatch-state.png"
        )
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                """UPDATE dispatch_executions
                   SET status = 'STARTED', revision = 0, terminal_detail_hash = NULL
                   WHERE execution_id = ?""",
                (execution_id,),
            )
            conn.execute(
                """UPDATE dispatch_claims
                   SET status = 'ACTIVE', revision = 0, terminal_reason = NULL
                   WHERE claim_id = ?""",
                (binding.claim_id,),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertTrue("RETURNED" in detail or "dispatch" in detail)

    def test_stale_task_revision_fails_before_acceptance_publication(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-task-revision.png"
        )
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                "UPDATE tasks SET revision = revision + 1 WHERE id = ?",
                (binding.task_id,),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertTrue("revision" in detail or "lifecycle" in detail)

    def test_valid_but_wrong_run_and_wrong_output_lineage_fail_closed(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-wrong-run.png"
        )
        runtime = self.fixture.runtime
        wrong_run_id = runtime.start_run(
            binding.task_id,
            role=PixeloramaCliExportService.RUN_ROLE,
        )
        runtime.finish_run(wrong_run_id, RunStatus.SUCCEEDED)
        with runtime.store.session() as conn:
            conn.execute(
                """UPDATE pixelorama_dispatch_output_bindings
                   SET run_id = ? WHERE execution_id = ?""",
                (wrong_run_id, execution_id),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertTrue(detail)

    def test_wrong_output_artifact_parent_is_rejected_as_lineage_drift(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-output-lineage.png"
        )
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                "UPDATE artifacts SET parent_artifact_id = ? WHERE id = ?",
                (binding.request_artifact_id, binding.output_artifact_id),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertIn("lineage", detail)

    def test_missing_and_non_published_adoption_receipts_cannot_authorize_acceptance(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-missing-adoption.png"
        )
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                "DELETE FROM pixelorama_production_adoptions WHERE execution_id = ?",
                (execution_id,),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertIn("adoption receipt does not exist", detail)

    def test_prepared_adoption_receipt_cannot_authorize_acceptance(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-prepared-adoption.png"
        )
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                """UPDATE pixelorama_production_adoptions
                   SET status = 'PREPARED', adopted_artifact_id = NULL,
                       verification_id = NULL, published_at = NULL
                   WHERE execution_id = ?""",
                (execution_id,),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertIn("PUBLISHED", detail)

    def test_wrong_adopted_artifact_and_wrong_adoption_verification_fail_closed(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-wrong-adoption.png"
        )
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                """UPDATE pixelorama_production_adoptions
                   SET adopted_artifact_id = ? WHERE execution_id = ?""",
                (binding.output_artifact_id, execution_id),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertTrue("Artifact" in detail or "relation" in detail)

    def test_wrong_adoption_verification_identity_fails_closed(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-wrong-verification.png"
        )
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            conn.execute(
                """UPDATE pixelorama_production_adoptions
                   SET verification_id = ? WHERE execution_id = ?""",
                (binding.output_verification_id, execution_id),
            )
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertIn("Verification", detail)

    def test_canonical_destination_symlink_drift_fails_before_phase50_pass(self) -> None:
        execution_id, binding, adoption = self._published_inputs(
            "assets/production/phase50d-symlink.png"
        )
        runtime = self.fixture.runtime
        destination = runtime.project_root / adoption.destination_path
        original = destination.read_bytes()
        alternate = runtime.project_root / "assets" / "production" / "phase50d-symlink-target.png"
        alternate.write_bytes(original)
        destination.unlink()
        try:
            os.symlink(alternate, destination)
        except OSError as exc:
            self.skipTest(f"symlink capability unavailable: {exc}")
        detail = self._assert_stale_rejected(execution_id, binding.task_id)
        self.assertIn("symlink", detail)

    def test_malformed_and_structurally_conflicting_acceptance_rows_never_terminalize(self) -> None:
        execution_id, binding, adoption = self._published_inputs(
            "assets/production/phase50d-malformed-acceptance.png"
        )
        runtime = self.fixture.runtime
        task = runtime.get_task(binding.task_id)
        publish_pixelorama_production_task_acceptance(
            runtime,
            binding,
            adoption,
            task_revision_at_acceptance=int(task["revision"]),
            actor_id="operator.phase50d-preseed",
        )
        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "pixelorama production task acceptances are immutable",
        ):
            with runtime.store.session() as conn:
                conn.execute(
                    """UPDATE pixelorama_production_task_acceptances
                       SET adopted_artifact_id = ? WHERE execution_id = ?""",
                    (binding.output_artifact_id, execution_id),
                )
        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
        )
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1, 0))

    def test_malformed_acceptance_scalar_is_detected_without_duplicate_pass(self) -> None:
        execution_id, binding, adoption = self._published_inputs(
            "assets/production/phase50d-malformed-scalar.png"
        )
        runtime = self.fixture.runtime
        task = runtime.get_task(binding.task_id)
        publish_pixelorama_production_task_acceptance(
            runtime,
            binding,
            adoption,
            task_revision_at_acceptance=int(task["revision"]),
        )
        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "pixelorama production task acceptances are immutable",
        ):
            with runtime.store.session() as conn:
                conn.execute(
                    """UPDATE pixelorama_production_task_acceptances
                       SET accepted_byte_count = 0 WHERE execution_id = ?""",
                    (execution_id,),
                )
        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
        )
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1, 0))

    def test_concurrent_identical_acceptance_yields_one_pass_one_receipt_one_transition(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-concurrent.png"
        )
        runtime = self.fixture.runtime
        barrier = Barrier(2)

        def accept_once():
            barrier.wait()
            try:
                return GovernedPixeloramaProductionTaskAcceptor(runtime).accept(execution_id)
            except PixeloramaProductionTaskAcceptorError as exc:
                return exc

        with patch.object(PixeloramaCliExportService, "execute", autospec=True) as replay:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(accept_once) for _ in range(2)]
                outcomes = [future.result() for future in futures]
        self.assertEqual(replay.call_count, 0)
        successes = [
            outcome
            for outcome in outcomes
            if not isinstance(outcome, PixeloramaProductionTaskAcceptorError)
        ]
        failures = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, PixeloramaProductionTaskAcceptorError)
        ]
        self.assertGreaterEqual(len(successes), 1)
        for result in successes[1:]:
            self.assertEqual(result, successes[0])
        for failure in failures:
            self.assertTrue(str(failure))
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1, 1))

    def test_concurrent_task_revision_change_after_publication_fails_without_force_transition(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50d-stale-transition.png"
        )
        runtime = self.fixture.runtime

        def race_transition(task_id, target, *, expected_revision):
            self.assertEqual(task_id, binding.task_id)
            with runtime.store.session() as conn:
                conn.execute(
                    "UPDATE tasks SET revision = revision + 1 WHERE id = ?",
                    (task_id,),
                )
            raise StaleRevision("simulated concurrent Task revision change")

        with patch.object(runtime, "transition_task", side_effect=race_transition):
            with self.assertRaises(PixeloramaProductionTaskAcceptorError):
                GovernedPixeloramaProductionTaskAcceptor(runtime).accept(execution_id)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1, 0))

    def test_unrelated_and_advisory_passes_do_not_bypass_explicit_human_acceptance(self) -> None:
        execution_id, binding, adoption = self._published_inputs(
            "assets/production/phase50d-advisory.png"
        )
        runtime = self.fixture.runtime
        destination = runtime.project_root / adoption.destination_path
        before_bytes = destination.read_bytes()
        task = runtime.get_task(binding.task_id)
        flow = runtime.get_flow(task["flow_id"])
        goal = runtime.get_goal(flow["goal_id"])
        before_flow_status = flow["status"]
        before_goal_status = goal["status"]

        unrelated = runtime.record_verification(
            "TASK",
            binding.task_id,
            verification_type="pre-existing-unrelated-pass",
            verifier="test.phase50d.unrelated",
            status="PASS",
            evidence={"production_task_verified": False},
            run_id=binding.run_id,
        )
        vision = runtime.record_verification(
            "TASK",
            binding.task_id,
            verification_type="vision-structural-pass",
            verifier="test.phase50d.vision-advisory",
            status="PASS",
            evidence={
                "structural_quality": "favorable",
                "production_task_verified": False,
            },
            run_id=binding.run_id,
        )
        specialist = runtime.record_verification(
            "TASK",
            binding.task_id,
            verification_type="specialist-advisory-pass",
            verifier="test.phase50d.specialist-advisory",
            status="PASS",
            evidence={
                "recommendation": "accept",
                "production_task_verified": False,
            },
            run_id=binding.run_id,
        )
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        self.assertEqual(self._phase50_counts(binding.task_id), (0, 0, 0))
        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED,
        )
        self.assertNotIn(unrelated, {current.task_verification_id})
        self.assertNotIn(vision, {current.task_verification_id})
        self.assertNotIn(specialist, {current.task_verification_id})

        with patch.object(PixeloramaCliExportService, "execute", autospec=True) as replay:
            result = GovernedPixeloramaProductionTaskAcceptor(runtime).accept(
                execution_id,
                actor_id="operator.phase50d",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(destination.read_bytes(), before_bytes)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1, 1))
        self.assertEqual(runtime.get_flow(task["flow_id"])["status"], before_flow_status)
        self.assertEqual(runtime.get_goal(flow["goal_id"])["status"], before_goal_status)
        rendered = result.to_dict()
        self.assertTrue(rendered["production_task_verified"])
        self.assertTrue(rendered["semantic_visual_quality_verified"])
        self.assertEqual(rendered["acceptance_authority"], "HUMAN_OPERATOR")
        self.assertTrue(rendered["canonical_asset_adopted"])
        self.assertFalse(rendered["provenance_signed"])
        self.assertFalse(rendered["release_authorized"])

    def test_installed_package_scripts_remain_exactly_the_existing_three(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with (repo_root / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(
            set(config["project"]["scripts"]),
            {"origin-forge", "origin-forge-attempt", "origin-forge-cockpit"},
        )


if __name__ == "__main__":
    unittest.main()
