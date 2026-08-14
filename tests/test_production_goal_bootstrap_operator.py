from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.ids import IdKind, new_id
from origin_forge.production_goal_bootstrap_authority import (
    acquire_current_goal_bootstrap,
    prepare_goal_bootstrap_input,
)
from origin_forge.production_goal_bootstrap_models import (
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from origin_forge.production_goal_bootstrap_operator import (
    GoalBootstrapDecision,
    GoalBootstrapOperatorAction,
    GoalBootstrapOperatorBlocked,
    GoalBootstrapOperatorStatus,
    bootstrap_goal_once,
    inspect_goal_bootstrap_status_readonly,
    recover_goal_once,
)
from origin_forge.production_goal_bootstrap_store import (
    checkpoint_goal_bootstrap_planner_returned,
    checkpoint_goal_bootstrap_planner_started,
    interrupt_goal_bootstrap,
    read_goal_bootstrap_receipt,
)
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep
from origin_forge.runtime import OriginForgeRuntime


_VALID_CONFIG = '''version = 6
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "unconfigured"
image = ""
network = false
memory = "2g"
cpus = 2.0
pids_limit = 256

[commands]
build = []
test = []

[code_intelligence]
lsp_servers = []

[resources]
enabled = true
cpu_slots = 8
ram_mib = 16384
max_active_leases = 8
gpus = []

[models]
profiles = [
  { profile_id = "strong", role = "coder_strong", model_id = "test-model", model_hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", runtime_id = "llamacpp-cpu", resources = { cpu_slots = 2, ram_mib = 4096 } }
]
policies = [
  { role = "coder_strong", primary_profile_id = "strong", fallback_profile_ids = [] }
]

[model_runtimes]
providers = [
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18081, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]
'''


class GoalBootstrapOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase45e-operator")
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _VALID_CONFIG,
            encoding="utf-8",
        )
        self.goal_id = self.runtime.create_goal("bootstrap exactly one current goal")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _count(self, table: str) -> int:
        with self.runtime.store.session() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _fake_planner_return(self, runtime: OriginForgeRuntime, bootstrap_id: str) -> None:
        receipt, planning_input = prepare_goal_bootstrap_input(runtime, bootstrap_id)
        if receipt.stage in (
            GoalBootstrapStage.PLANNER_RETURNED,
            GoalBootstrapStage.PLAN_AUDITED,
            GoalBootstrapStage.MATERIALIZED,
            GoalBootstrapStage.PREPPOL_PUBLISHED,
        ):
            return
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="One bounded code task.",
            steps=(
                PlanStep(
                    step_key="change",
                    objective="Implement exactly the bounded Goal change.",
                    acceptance_criteria=("The bounded change is verified.",),
                    constraints=("Remain inside current Goal authority.",),
                    required_capabilities=("code.change",),
                    priority=0,
                    max_attempts=1,
                    depends_on=(),
                ),
            ),
        )
        ProductionPlanningEvidenceStore(runtime).publish_proposal(proposal)
        started = checkpoint_goal_bootstrap_planner_started(
            runtime,
            receipt.bootstrap_id,
            receipt.revision,
            planner_dependency_plan_hash="d" * 64,
        )
        checkpoint_goal_bootstrap_planner_returned(
            runtime,
            started.bootstrap_id,
            started.revision,
            planner_run_id=new_id(IdKind.RUN),
            plan_proposal_id=proposal.proposal_id,
            plan_proposal_hash=proposal.content_hash,
        )

    def test_readonly_status_starts_eligible_without_sqlite_sidecars(self) -> None:
        sidecars = tuple(
            Path(str(self.runtime.store.db_path) + suffix)
            for suffix in ("-wal", "-shm", "-journal")
        )
        self.assertTrue(all(not path.exists() for path in sidecars))

        projection = inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id)

        self.assertEqual(projection.decision, GoalBootstrapDecision.ELIGIBLE)
        self.assertEqual(projection.exact_revision_receipt_count, 0)
        self.assertIsNone(projection.receipt)
        self.assertTrue(all(not path.exists() for path in sidecars))

    def test_fresh_bootstrap_reaches_ready_and_repeated_call_is_idempotent(self) -> None:
        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=self._fake_planner_return,
        ) as planner:
            first = bootstrap_goal_once(self.runtime, self.goal_id)
            second = bootstrap_goal_once(self.runtime, self.goal_id)

        self.assertEqual(first.action, GoalBootstrapOperatorAction.BOOTSTRAP)
        self.assertEqual(first.status, GoalBootstrapOperatorStatus.READY)
        self.assertEqual(first.receipt.status, GoalBootstrapStatus.READY)
        self.assertEqual(second.status, GoalBootstrapOperatorStatus.ALREADY_READY)
        self.assertEqual(first.receipt.bootstrap_id, second.receipt.bootstrap_id)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)

        projection = inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id)
        self.assertEqual(projection.decision, GoalBootstrapDecision.READY_FOR_MANAGER)
        self.assertEqual(projection.receipt, first.receipt)

    def test_existing_active_receipt_requires_explicit_recovery(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        self.assertEqual(
            inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id).decision,
            GoalBootstrapDecision.ACTIVE_PRE_PLANNER,
        )

        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=self._fake_planner_return,
        ) as planner:
            with self.assertRaises(GoalBootstrapOperatorBlocked) as blocked:
                bootstrap_goal_once(self.runtime, self.goal_id)
            recovered = recover_goal_once(self.runtime, self.goal_id)

        self.assertEqual(blocked.exception.decision, GoalBootstrapDecision.ACTIVE_PRE_PLANNER)
        self.assertEqual(recovered.action, GoalBootstrapOperatorAction.RECOVER)
        self.assertEqual(recovered.status, GoalBootstrapOperatorStatus.READY)
        self.assertEqual(recovered.receipt.bootstrap_id, acquired.bootstrap_id)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(self._count("goal_bootstraps"), 1)

    def test_post_planner_recovery_does_not_call_planner_again(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        self._fake_planner_return(self.runtime, acquired.bootstrap_id)
        projection = inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id)
        self.assertEqual(projection.decision, GoalBootstrapDecision.POST_PLANNER_RESUMABLE)

        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=AssertionError("Planner must not be replayed after PLANNER_RETURNED"),
        ) as planner:
            recovered = recover_goal_once(self.runtime, self.goal_id)

        self.assertEqual(recovered.status, GoalBootstrapOperatorStatus.READY)
        planner.assert_not_called()

    def test_interrupted_same_revision_blocks_fresh_replay(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        receipt, _ = prepare_goal_bootstrap_input(self.runtime, acquired.bootstrap_id)
        started = checkpoint_goal_bootstrap_planner_started(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            planner_dependency_plan_hash="e" * 64,
        )
        interrupted = interrupt_goal_bootstrap(
            self.runtime,
            started.bootstrap_id,
            started.revision,
            GoalBootstrapStage.PLANNER_STARTED,
            "uncertain planner boundary",
        )
        self.assertEqual(interrupted.status, GoalBootstrapStatus.INTERRUPTED)

        projection = inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id)
        self.assertEqual(projection.decision, GoalBootstrapDecision.INTERRUPTED)
        with self.assertRaises(GoalBootstrapOperatorBlocked) as blocked:
            bootstrap_goal_once(self.runtime, self.goal_id)
        self.assertEqual(blocked.exception.decision, GoalBootstrapDecision.INTERRUPTED)
        self.assertEqual(self._count("goal_bootstraps"), 1)

    def test_multiple_exact_terminal_receipts_fail_closed_as_ambiguous(self) -> None:
        for index in range(2):
            acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
            interrupt_goal_bootstrap(
                self.runtime,
                acquired.bootstrap_id,
                acquired.revision,
                GoalBootstrapStage.CLAIMED,
                f"terminal pre-planner attempt {index}",
            )

        projection = inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id)
        self.assertEqual(projection.decision, GoalBootstrapDecision.AMBIGUOUS_AUTHORITY)
        self.assertEqual(projection.exact_revision_receipt_count, 2)
        self.assertIsNone(projection.receipt)
        with self.assertRaises(GoalBootstrapOperatorBlocked):
            bootstrap_goal_once(self.runtime, self.goal_id)
        with self.assertRaises(GoalBootstrapOperatorBlocked):
            recover_goal_once(self.runtime, self.goal_id)

    def test_same_revision_hash_drift_is_stale_goal(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        interrupt_goal_bootstrap(
            self.runtime,
            acquired.bootstrap_id,
            acquired.revision,
            GoalBootstrapStage.CLAIMED,
            "preserve historical authority",
        )
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE goals SET objective = ? WHERE id = ?",
                ("mutated without revision for adversarial test", self.goal_id),
            )

        projection = inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id)
        self.assertEqual(projection.decision, GoalBootstrapDecision.STALE_GOAL)
        with self.assertRaises(GoalBootstrapOperatorBlocked):
            bootstrap_goal_once(self.runtime, self.goal_id)

    def test_later_goal_revision_is_a_distinct_eligible_authority_question(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        interrupt_goal_bootstrap(
            self.runtime,
            acquired.bootstrap_id,
            acquired.revision,
            GoalBootstrapStage.CLAIMED,
            "old revision stopped before planner",
        )
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE goals SET objective = ?, revision = revision + 1 WHERE id = ?",
                ("new current revision", self.goal_id),
            )

        projection = inspect_goal_bootstrap_status_readonly(self.runtime, self.goal_id)
        self.assertEqual(projection.decision, GoalBootstrapDecision.ELIGIBLE)
        self.assertEqual(projection.exact_revision_receipt_count, 0)
        self.assertEqual(projection.historical_receipt_count, 1)

    def test_concurrent_fresh_calls_never_cross_planner_twice(self) -> None:
        barrier = threading.Barrier(3)
        planner_calls = 0
        planner_lock = threading.Lock()
        outcomes: list[str] = []
        outcomes_lock = threading.Lock()

        def fake_planner(runtime: OriginForgeRuntime, bootstrap_id: str) -> None:
            nonlocal planner_calls
            with planner_lock:
                planner_calls += 1
            self._fake_planner_return(runtime, bootstrap_id)

        def worker() -> None:
            runtime = OriginForgeRuntime(self.root)
            barrier.wait()
            try:
                result = bootstrap_goal_once(runtime, self.goal_id)
                outcome = result.status.value
            except Exception as exc:
                outcome = type(exc).__name__
            with outcomes_lock:
                outcomes.append(outcome)

        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=fake_planner,
        ):
            threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=20)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(planner_calls, 1)
        self.assertEqual(self._count("goal_bootstraps"), 1)
        receipt_id = inspect_goal_bootstrap_status_readonly(
            self.runtime,
            self.goal_id,
        ).receipt.bootstrap_id
        durable = read_goal_bootstrap_receipt(self.runtime, receipt_id)
        self.assertEqual(durable.status, GoalBootstrapStatus.READY)


if __name__ == "__main__":
    unittest.main()
