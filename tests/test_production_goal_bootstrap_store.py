from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from origin_forge.production_goal_bootstrap_models import (
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from origin_forge.production_goal_bootstrap_store import (
    GoalBootstrapStoreError,
    acquire_goal_bootstrap_receipt,
    checkpoint_goal_bootstrap_authority_published,
    checkpoint_goal_bootstrap_materialized,
    checkpoint_goal_bootstrap_plan_audited,
    checkpoint_goal_bootstrap_planner_returned,
    checkpoint_goal_bootstrap_planner_started,
    checkpoint_goal_bootstrap_planning_input_published,
    checkpoint_goal_bootstrap_preppol_published,
    interrupt_goal_bootstrap,
    read_goal_bootstrap_receipt,
)
from origin_forge.production_planning_evidence import goal_planning_hash
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import StaleRevision


OWNER_ID = "originforge.bootstrap.goal-planner@1"
OWNER_FINGERPRINT = "1" * 64
CAPCAT = "CAPCAT-00000000-0000-4000-8000-000000000101"
CAPPOL = "CAPPOL-00000000-0000-4000-8000-000000000102"
DISPCAT = "DISPCAT-00000000-0000-4000-8000-000000000103"
PLINPUT = "PLINPUT-00000000-0000-4000-8000-000000000104"
RUN = "RUN-00000000-0000-4000-8000-000000000105"
PLPROP = "PLPROP-00000000-0000-4000-8000-000000000106"
PLAUD = "PLAUD-00000000-0000-4000-8000-000000000107"
PLMAT = "PLMAT-00000000-0000-4000-8000-000000000108"
PREPPOL = "PREPPOL-00000000-0000-4000-8000-000000000109"


class GoalBootstrapStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase45a-goal-bootstrap")
        self.goal_id = self.runtime.create_goal("bootstrap one exact Goal")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _acquire(self):
        return acquire_goal_bootstrap_receipt(
            self.runtime,
            self.goal_id,
            bootstrap_owner_id=OWNER_ID,
            bootstrap_owner_fingerprint=OWNER_FINGERPRINT,
            bootstrap_contract_version="1",
        )

    def _authority(self, receipt):
        return checkpoint_goal_bootstrap_authority_published(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            capability_catalog_id=CAPCAT,
            capability_catalog_hash="2" * 64,
            capability_routing_policy_id=CAPPOL,
            capability_routing_policy_hash="3" * 64,
            dispatch_contract_catalog_id=DISPCAT,
            dispatch_contract_catalog_hash="4" * 64,
        )

    def test_acquisition_freezes_canonical_goal_revision_and_hash(self) -> None:
        receipt = self._acquire()
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE id = ?",
                (self.goal_id,),
            ).fetchone()
            expected_hash = goal_planning_hash(row)
        self.assertEqual(receipt.goal_revision, 0)
        self.assertEqual(receipt.goal_content_hash, expected_hash)
        self.assertEqual(receipt.stage, GoalBootstrapStage.CLAIMED)
        self.assertEqual(receipt.status, GoalBootstrapStatus.ACTIVE)
        self.assertEqual(receipt.revision, 0)

    def test_duplicate_current_owner_for_exact_goal_revision_is_rejected(self) -> None:
        first = self._acquire()
        with self.assertRaisesRegex(
            GoalBootstrapStoreError,
            "already has current bootstrap",
        ):
            self._acquire()
        durable = read_goal_bootstrap_receipt(self.runtime, first.bootstrap_id)
        self.assertEqual(durable, first)

    def test_interrupted_attempt_retains_history_and_allows_new_owner(self) -> None:
        first = self._acquire()
        interrupted = interrupt_goal_bootstrap(
            self.runtime,
            first.bootstrap_id,
            first.revision,
            GoalBootstrapStage.CLAIMED,
            "operator-reviewed interruption",
        )
        second = self._acquire()
        self.assertEqual(interrupted.status, GoalBootstrapStatus.INTERRUPTED)
        self.assertNotEqual(first.bootstrap_id, second.bootstrap_id)
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT bootstrap_id, status FROM goal_bootstraps
                   WHERE goal_id = ? ORDER BY rowid""",
                (self.goal_id,),
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "INTERRUPTED")
        self.assertEqual(rows[1]["status"], "ACTIVE")

    def test_restart_reads_exact_durable_receipt(self) -> None:
        acquired = self._acquire()
        restarted = OriginForgeRuntime(self.root)
        durable = read_goal_bootstrap_receipt(restarted, acquired.bootstrap_id)
        self.assertEqual(durable, acquired)

    def test_goal_revision_drift_blocks_next_checkpoint(self) -> None:
        acquired = self._acquire()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE goals SET revision = revision + 1 WHERE id = ?",
                (self.goal_id,),
            )
        with self.assertRaisesRegex(StaleRevision, "Goal changed"):
            self._authority(acquired)
        durable = read_goal_bootstrap_receipt(
            self.runtime,
            acquired.bootstrap_id,
        )
        self.assertEqual(durable.stage, GoalBootstrapStage.CLAIMED)
        self.assertEqual(durable.revision, 0)

    def test_concurrent_checkpoint_has_one_cas_winner(self) -> None:
        acquired = self._acquire()

        def attempt():
            try:
                result = self._authority(acquired)
            except Exception as exc:
                return ("error", type(exc).__name__)
            return ("ok", result.stage.value)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(lambda _: attempt(), range(2)))

        self.assertEqual(sum(outcome[0] == "ok" for outcome in outcomes), 1)
        self.assertEqual(sum(outcome[0] == "error" for outcome in outcomes), 1)
        durable = read_goal_bootstrap_receipt(
            self.runtime,
            acquired.bootstrap_id,
        )
        self.assertEqual(durable.stage, GoalBootstrapStage.AUTHORITY_PUBLISHED)
        self.assertEqual(durable.revision, 1)

    def test_checkpoint_lifecycle_reaches_ready_without_invoking_planner(self) -> None:
        receipt = self._authority(self._acquire())
        receipt = checkpoint_goal_bootstrap_planning_input_published(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            planning_input_id=PLINPUT,
            planning_input_hash="5" * 64,
        )
        receipt = checkpoint_goal_bootstrap_planner_started(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            planner_dependency_plan_hash="6" * 64,
        )
        self.assertTrue(receipt.requires_planner_recovery)
        receipt = checkpoint_goal_bootstrap_planner_returned(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            planner_run_id=RUN,
            plan_proposal_id=PLPROP,
            plan_proposal_hash="7" * 64,
        )
        receipt = checkpoint_goal_bootstrap_plan_audited(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            plan_audit_id=PLAUD,
            plan_audit_hash="8" * 64,
        )
        receipt = checkpoint_goal_bootstrap_materialized(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            materialization_id=PLMAT,
            materialization_hash="9" * 64,
        )
        receipt = checkpoint_goal_bootstrap_preppol_published(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            preparation_policy_id=PREPPOL,
            preparation_policy_hash="a" * 64,
        )
        self.assertEqual(receipt.stage, GoalBootstrapStage.PREPPOL_PUBLISHED)
        self.assertEqual(receipt.status, GoalBootstrapStatus.READY)
        self.assertEqual(receipt.revision, 7)
        self.assertFalse(receipt.requires_planner_recovery)


if __name__ == "__main__":
    unittest.main()
