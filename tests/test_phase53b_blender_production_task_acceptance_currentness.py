from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

import origin_forge.production_blender_task_acceptor as acceptor_module
from origin_forge.production_blender_task_acceptance import (
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    read_blender_production_task_acceptance,
)
from origin_forge.production_blender_task_acceptance_currentness import (
    BlenderProductionTaskAcceptanceCurrentnessStatus,
    inspect_blender_production_task_acceptance_currentness_readonly,
)
from origin_forge.production_blender_task_acceptor import (
    BlenderProductionTaskAcceptorError,
    GovernedBlenderProductionTaskAcceptor,
)
from origin_forge.service import StaleRevision
from test_phase53a_blender_production_task_acceptance import (
    Phase53ABlenderProductionTaskAcceptanceTests,
)


class Phase53BBlenderProductionTaskAcceptanceCurrentnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase53ABlenderProductionTaskAcceptanceTests(
            methodName=(
                "test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _ready(self):
        return self.fixture._published_inputs()

    def test_current_exact_blender_adoption_is_not_accepted_but_eligible(self) -> None:
        runtime, binding, adoption, _, task_revision = self._ready()

        currentness = inspect_blender_production_task_acceptance_currentness_readonly(
            runtime,
            binding.execution_id,
        )

        self.assertEqual(
            currentness.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED,
        )
        self.assertTrue(currentness.acceptance_eligible)
        self.assertFalse(currentness.accepted)
        self.assertEqual(currentness.task_id, binding.task_id)
        self.assertEqual(currentness.adopted_artifact_id, adoption.adopted_artifact_id)
        self.assertEqual(currentness.task_revision, task_revision)
        self.assertIsNone(currentness.task_verification_id)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")

    def test_governed_acceptance_terminalizes_once_and_exact_replay_is_idempotent(self) -> None:
        runtime, binding, adoption, _, task_revision = self._ready()
        acceptor = GovernedBlenderProductionTaskAcceptor(runtime)

        first = acceptor.accept(
            binding.execution_id,
            actor_id="operator.phase53b",
        )
        second = acceptor.accept(
            binding.execution_id,
            actor_id="ignored.on.exact.replay",
        )

        self.assertEqual(second, first)
        self.assertEqual(first.execution_id, binding.execution_id)
        self.assertEqual(first.task_id, binding.task_id)
        self.assertEqual(first.adopted_artifact_id, adoption.adopted_artifact_id)
        self.assertEqual(first.task_revision_at_acceptance, task_revision)
        self.assertEqual(first.task_revision, task_revision + 1)
        self.assertEqual(first.task_status, "SUCCEEDED")
        payload = first.to_dict()
        self.assertTrue(payload["production_task_verified"])
        self.assertTrue(payload["semantic_geometry_verified"])
        self.assertEqual(payload["acceptance_authority"], "HUMAN_OPERATOR")
        self.assertTrue(payload["canonical_asset_adopted"])
        self.assertFalse(payload["provenance_signed"])
        self.assertFalse(payload["release_authorized"])

        task = runtime.get_task(binding.task_id)
        self.assertEqual(task["status"], "SUCCEEDED")
        self.assertEqual(task["revision"], task_revision + 1)
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
                        binding.task_id,
                        BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    ),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM state_events
                       WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                             AND event_type = 'TASK_STATUS_CHANGED'
                             AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'""",
                    (binding.task_id,),
                ).fetchone()[0],
                1,
            )

    def test_durable_pass_recovers_terminalization_without_republishing_or_reexecution(self) -> None:
        runtime, binding, _, _, task_revision = self._ready()
        acceptor = GovernedBlenderProductionTaskAcceptor(runtime)

        with patch.object(
            runtime,
            "transition_task",
            side_effect=RuntimeError("simulated crash after durable acceptance"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                acceptor.accept(binding.execution_id, actor_id="operator.phase53b")

        receipt = read_blender_production_task_acceptance(
            runtime,
            binding.execution_id,
        )
        self.assertEqual(receipt.task_revision_at_acceptance, task_revision)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        pending = acceptor.inspect(binding.execution_id)
        self.assertEqual(
            pending.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
        )
        with runtime.store.session() as conn:
            verification_count = conn.execute(
                """SELECT COUNT(*) FROM verifications
                   WHERE target_type = 'TASK' AND target_id = ?
                         AND verification_type = ?""",
                (
                    binding.task_id,
                    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                ),
            ).fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

        recovered = acceptor.accept(binding.execution_id)

        self.assertEqual(recovered.task_status, "SUCCEEDED")
        self.assertEqual(recovered.task_verification_id, receipt.task_verification_id)
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications
                       WHERE target_type = 'TASK' AND target_id = ?
                             AND verification_type = ?""",
                    (
                        binding.task_id,
                        BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    ),
                ).fetchone()[0],
                verification_count,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                run_count,
            )

    def test_stale_revision_race_converges_on_exact_concurrent_winner(self) -> None:
        runtime, binding, _, _, task_revision = self._ready()
        acceptor = GovernedBlenderProductionTaskAcceptor(runtime)
        original_transition = runtime.transition_task

        def concurrent_winner(task_id, target, *, expected_revision):
            original_transition(
                task_id,
                target,
                expected_revision=expected_revision,
            )
            raise StaleRevision("simulated losing acceptor after concurrent winner")

        with patch.object(
            runtime,
            "transition_task",
            side_effect=concurrent_winner,
        ):
            accepted = acceptor.accept(
                binding.execution_id,
                actor_id="operator.phase53b.race",
            )

        self.assertEqual(accepted.task_status, "SUCCEEDED")
        self.assertEqual(accepted.task_revision_at_acceptance, task_revision)
        self.assertEqual(accepted.task_revision, task_revision + 1)
        final = acceptor.inspect(binding.execution_id)
        self.assertEqual(
            final.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
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
                        binding.task_id,
                        BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    ),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM state_events
                       WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                             AND event_type = 'TASK_STATUS_CHANGED'
                             AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'""",
                    (binding.task_id,),
                ).fetchone()[0],
                1,
            )

    def test_live_adopted_byte_drift_blocks_first_acceptance(self) -> None:
        runtime, binding, adoption, _, _ = self._ready()
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(destination.read_bytes() + b"drift")

        currentness = inspect_blender_production_task_acceptance_currentness_readonly(
            runtime,
            binding.execution_id,
        )
        self.assertEqual(
            currentness.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        self.assertIn("destination bytes drifted", currentness.detail or "")
        with self.assertRaises(BlenderProductionTaskAcceptorError):
            GovernedBlenderProductionTaskAcceptor(runtime).accept(binding.execution_id)
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                0,
            )
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")

    def test_incomplete_child_fails_before_phase53_pass(self) -> None:
        runtime, binding, _, _, _ = self._ready()
        parent = runtime.get_task(binding.task_id)
        child_id = runtime.create_task(
            parent["flow_id"],
            "unfinished child blocks Blender production acceptance",
            parent_task_id=binding.task_id,
        )
        self.assertEqual(runtime.get_task(child_id)["status"], "QUEUED")

        currentness = inspect_blender_production_task_acceptance_currentness_readonly(
            runtime,
            binding.execution_id,
        )
        self.assertEqual(
            currentness.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        self.assertIn("child Tasks incompatible", currentness.detail or "")
        with self.assertRaises(BlenderProductionTaskAcceptorError):
            GovernedBlenderProductionTaskAcceptor(runtime).accept(binding.execution_id)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
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
                        binding.task_id,
                        BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    ),
                ).fetchone()[0],
                0,
            )

    def test_post_success_asset_drift_does_not_rewrite_historical_acceptance(self) -> None:
        runtime, binding, adoption, _, _ = self._ready()
        acceptor = GovernedBlenderProductionTaskAcceptor(runtime)
        accepted = acceptor.accept(binding.execution_id)
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(b"later unrelated workspace drift")

        currentness = acceptor.inspect(binding.execution_id)
        replay = acceptor.accept(binding.execution_id)

        self.assertEqual(
            currentness.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
        )
        self.assertEqual(replay, accepted)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")

    def test_task_revision_drift_fails_closed_before_acceptance(self) -> None:
        runtime, binding, _, _, task_revision = self._ready()
        with runtime.store.session() as conn:
            conn.execute(
                "UPDATE tasks SET revision = ? WHERE id = ?",
                (task_revision + 1, binding.task_id),
            )

        currentness = inspect_blender_production_task_acceptance_currentness_readonly(
            runtime,
            binding.execution_id,
        )
        self.assertEqual(
            currentness.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        )
        with self.assertRaises(BlenderProductionTaskAcceptorError):
            GovernedBlenderProductionTaskAcceptor(runtime).accept(binding.execution_id)
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                0,
            )

    def test_public_mutation_surface_is_execution_scoped_and_has_no_external_execution_hooks(self) -> None:
        parameters = inspect.signature(
            GovernedBlenderProductionTaskAcceptor.accept
        ).parameters
        self.assertEqual(
            set(parameters),
            {"self", "execution_id", "actor_id"},
        )
        source = inspect.getsource(acceptor_module)
        for forbidden in (
            "BlenderExportService",
            "subprocess",
            "ModelAdapter",
            "conversation",
            "manager",
            "browser",
            "model3d_request_id=",
            "model3d_request_hash=",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
