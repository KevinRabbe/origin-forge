from __future__ import annotations

import os
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
    PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    publish_pixelorama_production_task_acceptance,
    read_pixelorama_production_task_acceptance,
)
from origin_forge.production_pixelorama_task_acceptance_currentness import (
    PixeloramaProductionTaskAcceptanceCurrentnessStatus,
    inspect_pixelorama_production_task_acceptance_currentness_readonly,
)
from origin_forge.production_pixelorama_task_acceptor import (
    GovernedPixeloramaProductionTaskAcceptor,
    PixeloramaProductionTaskAcceptorError,
)
from .test_phase48f_pixelorama_invocation import Phase48FPixeloramaInvocationTests


class Phase50BPixeloramaProductionTaskAcceptanceCurrentnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase48FPixeloramaInvocationTests(
            methodName=(
                "test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _published_inputs(self, destination: str = "assets/production/phase50b-sprite.png"):
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
        adopted = GovernedPixeloramaProductionOutputAdopter(fixture.runtime).adopt_new(
            completed.execution_id,
            destination,
        )
        adoption = read_pixelorama_production_adoption_receipt(
            fixture.runtime,
            completed.execution_id,
        )
        self.assertEqual(adoption.adopted_artifact_id, adopted.adopted_artifact_id)
        return completed.execution_id, binding, adoption

    def _phase50_counts(self, task_id: str) -> tuple[int, int]:
        runtime = self.fixture.runtime
        with runtime.store.session() as conn:
            verification_count = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?
                         AND verification_type = ?""",
                (task_id, PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE),
            ).fetchone()[0]
            transition_count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                         AND event_type = 'TASK_STATUS_CHANGED'
                         AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'""",
                (task_id,),
            ).fetchone()[0]
        return int(verification_count), int(transition_count)

    def test_exact_current_production_result_accepts_once_and_terminalizes_through_runtime(self) -> None:
        execution_id, binding, adoption = self._published_inputs()
        runtime = self.fixture.runtime
        destination = runtime.project_root / adoption.destination_path
        before_bytes = destination.read_bytes()

        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED,
        )
        self.assertTrue(current.acceptance_eligible)
        self.assertFalse(current.accepted)
        self.assertEqual(current.task_revision, binding.task_revision + 1)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            result = GovernedPixeloramaProductionTaskAcceptor(runtime).accept(
                execution_id,
                actor_id="operator.phase50b",
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(result.execution_id, execution_id)
        self.assertEqual(result.task_id, binding.task_id)
        self.assertEqual(result.adopted_artifact_id, adoption.adopted_artifact_id)
        self.assertEqual(result.adoption_verification_id, adoption.verification_id)
        self.assertEqual(result.task_status, "SUCCEEDED")
        self.assertEqual(result.task_revision_at_acceptance, binding.task_revision + 1)
        self.assertEqual(result.task_revision, binding.task_revision + 2)
        self.assertEqual(destination.read_bytes(), before_bytes)

        task = runtime.get_task(binding.task_id)
        self.assertEqual(task["status"], "SUCCEEDED")
        self.assertEqual(int(task["revision"]), binding.task_revision + 2)
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1))

        final = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            final.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
        )
        self.assertTrue(final.accepted)
        self.assertFalse(final.acceptance_eligible)
        self.assertEqual(final.task_verification_id, result.task_verification_id)

    def test_durable_pass_plus_running_task_retry_reuses_pass_and_finishes_terminalization(self) -> None:
        execution_id, binding, adoption = self._published_inputs(
            "assets/production/phase50b-recovery.png"
        )
        runtime = self.fixture.runtime
        task = runtime.get_task(binding.task_id)
        receipt = publish_pixelorama_production_task_acceptance(
            runtime,
            binding,
            adoption,
            task_revision_at_acceptance=int(task["revision"]),
            actor_id="operator.before-crash",
        )
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        pending = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            pending.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
        )
        self.assertEqual(pending.task_verification_id, receipt.task_verification_id)
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 0))

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            recovered = GovernedPixeloramaProductionTaskAcceptor(runtime).accept(execution_id)
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(recovered.task_verification_id, receipt.task_verification_id)
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1))
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")

    def test_exact_already_succeeded_duplicate_is_idempotent(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50b-idempotent.png"
        )
        runtime = self.fixture.runtime
        acceptor = GovernedPixeloramaProductionTaskAcceptor(runtime)
        first = acceptor.accept(execution_id)
        before_counts = self._phase50_counts(binding.task_id)
        first_receipt = read_pixelorama_production_task_acceptance(runtime, execution_id)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            second = acceptor.accept(execution_id)
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(second, first)
        self.assertEqual(
            read_pixelorama_production_task_acceptance(runtime, execution_id),
            first_receipt,
        )
        self.assertEqual(self._phase50_counts(binding.task_id), before_counts)
        self.assertEqual(before_counts, (1, 1))

    def test_adopted_destination_drift_fails_closed_before_pass_or_task_transition(self) -> None:
        execution_id, binding, adoption = self._published_inputs(
            "assets/production/phase50b-drift.png"
        )
        runtime = self.fixture.runtime
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(b"tampered-after-production-adoption")

        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        self.assertIn("bytes drifted", current.detail or "")
        with self.assertRaises(PixeloramaProductionTaskAcceptorError):
            GovernedPixeloramaProductionTaskAcceptor(runtime).accept(execution_id)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        self.assertEqual(self._phase50_counts(binding.task_id), (0, 0))
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM pixelorama_production_task_acceptances"
                ).fetchone()[0],
                0,
            )

    def test_incomplete_child_fails_before_phase50_pass(self) -> None:
        execution_id, binding, _ = self._published_inputs(
            "assets/production/phase50b-child.png"
        )
        runtime = self.fixture.runtime
        parent = runtime.get_task(binding.task_id)
        child_id = runtime.create_task(
            parent["flow_id"],
            "unfinished child blocks production acceptance",
            parent_task_id=binding.task_id,
        )
        self.assertEqual(runtime.get_task(child_id)["status"], "QUEUED")

        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        self.assertIn("child Tasks incompatible", current.detail or "")
        with self.assertRaises(PixeloramaProductionTaskAcceptorError):
            GovernedPixeloramaProductionTaskAcceptor(runtime).accept(execution_id)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        self.assertEqual(self._phase50_counts(binding.task_id), (0, 0))

    def test_terminal_acceptance_is_historical_after_later_asset_drift(self) -> None:
        execution_id, binding, adoption = self._published_inputs(
            "assets/production/phase50b-terminal-history.png"
        )
        runtime = self.fixture.runtime
        acceptor = GovernedPixeloramaProductionTaskAcceptor(runtime)
        first = acceptor.accept(execution_id)
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(b"later-terminal-asset-drift")

        current = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            execution_id,
        )
        self.assertEqual(
            current.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
        )
        second = acceptor.accept(execution_id)
        self.assertEqual(second, first)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")
        self.assertEqual(self._phase50_counts(binding.task_id), (1, 1))


if __name__ == "__main__":
    unittest.main()
