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
from origin_forge.production_goal_bootstrap_finalize import (
    GoalBootstrapFinalizeInterrupted,
    GoalBootstrapFinalizeStatus,
    _checkpoint_locked,
    finalize_goal_bootstrap,
)
from origin_forge.production_goal_bootstrap_models import (
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from origin_forge.production_goal_bootstrap_store import (
    checkpoint_goal_bootstrap_planner_returned,
    checkpoint_goal_bootstrap_planner_started,
    read_goal_bootstrap_receipt,
)
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import StaleRevision


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


class SimulatedCrash(BaseException):
    pass


class GoalBootstrapFinalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase45d-finalization")
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _VALID_CONFIG,
            encoding="utf-8",
        )
        self.goal_id = self.runtime.create_goal("materialize one bounded code change")
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        self.bootstrap_id = acquired.bootstrap_id
        receipt, planning_input = prepare_goal_bootstrap_input(
            self.runtime,
            self.bootstrap_id,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="One bounded code task.",
            steps=(
                PlanStep(
                    step_key="change",
                    objective="Implement the bounded code change.",
                    acceptance_criteria=("The change is verified.",),
                    constraints=("Stay inside frozen Goal authority.",),
                    required_capabilities=("code.change",),
                    priority=0,
                    max_attempts=1,
                    depends_on=(),
                ),
            ),
        )
        ProductionPlanningEvidenceStore(self.runtime).publish_proposal(proposal)
        started = checkpoint_goal_bootstrap_planner_started(
            self.runtime,
            receipt.bootstrap_id,
            receipt.revision,
            planner_dependency_plan_hash="d" * 64,
        )
        self.planner_run_id = new_id(IdKind.RUN)
        self.receipt = checkpoint_goal_bootstrap_planner_returned(
            self.runtime,
            started.bootstrap_id,
            started.revision,
            planner_run_id=self.planner_run_id,
            plan_proposal_id=proposal.proposal_id,
            plan_proposal_hash=proposal.content_hash,
        )
        self.proposal = proposal

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _count(self, table: str) -> int:
        with self.runtime.store.session() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _policy_files(self) -> tuple[Path, ...]:
        root = self.runtime.state_dir / "production-preparation" / "policies"
        if not root.exists():
            return ()
        return tuple(sorted(root.glob("PREPPOL-*.json")))

    def test_full_finalization_reaches_ready_and_stops_before_manager(self) -> None:
        result = finalize_goal_bootstrap(self.runtime, self.bootstrap_id)

        self.assertEqual(result.status, GoalBootstrapFinalizeStatus.READY)
        self.assertEqual(result.receipt.status, GoalBootstrapStatus.READY)
        self.assertEqual(result.receipt.stage, GoalBootstrapStage.PREPPOL_PUBLISHED)
        self.assertEqual(result.plan_audit.status.value, "PASS")
        self.assertEqual(result.materialization.audit_id, result.plan_audit.audit_id)
        self.assertEqual(
            result.preparation_policy.materialization_id,
            result.materialization.materialization_id,
        )
        self.assertEqual(self._count("plan_audits"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(len(self._policy_files()), 1)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)
        with self.runtime.store.session() as conn:
            task_rows = conn.execute("SELECT status FROM tasks ORDER BY id").fetchall()
            flow_rows = conn.execute("SELECT status FROM flows ORDER BY id").fetchall()
        self.assertEqual([row["status"] for row in task_rows], ["QUEUED"])
        self.assertEqual([row["status"] for row in flow_rows], ["QUEUED"])

    def test_audit_insert_and_checkpoint_are_one_transaction(self) -> None:
        real_checkpoint = _checkpoint_locked

        def crash_on_audit(conn, **kwargs):
            if kwargs["target_stage"] is GoalBootstrapStage.PLAN_AUDITED:
                raise SimulatedCrash("after audit insert before GOALBOOT audit checkpoint")
            return real_checkpoint(conn, **kwargs)

        with patch(
            "origin_forge.production_goal_bootstrap_finalize._checkpoint_locked",
            side_effect=crash_on_audit,
        ):
            with self.assertRaises(SimulatedCrash):
                finalize_goal_bootstrap(self.runtime, self.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNER_RETURNED)
        self.assertEqual(durable.status, GoalBootstrapStatus.ACTIVE)
        self.assertEqual(self._count("plan_audits"), 0)

        result = finalize_goal_bootstrap(self.runtime, self.bootstrap_id)
        self.assertEqual(result.receipt.status, GoalBootstrapStatus.READY)
        self.assertEqual(self._count("plan_audits"), 1)

    def test_crash_after_materialization_before_checkpoint_reuses_exact_plmat(self) -> None:
        from origin_forge import production_goal_bootstrap_finalize as module

        real_checkpoint = module.checkpoint_goal_bootstrap_materialized
        seen = {"calls": 0}

        def crash_once(*args, **kwargs):
            seen["calls"] += 1
            if seen["calls"] == 1:
                raise SimulatedCrash("after PLMAT commit before GOALBOOT checkpoint")
            return real_checkpoint(*args, **kwargs)

        with patch.object(module, "checkpoint_goal_bootstrap_materialized", side_effect=crash_once):
            with self.assertRaises(SimulatedCrash):
                finalize_goal_bootstrap(self.runtime, self.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLAN_AUDITED)
        self.assertEqual(self._count("plan_materializations"), 1)
        with self.runtime.store.session() as conn:
            plmat_id = conn.execute(
                "SELECT materialization_id FROM plan_materializations WHERE proposal_id = ?",
                (self.proposal.proposal_id,),
            ).fetchone()["materialization_id"]

        result = finalize_goal_bootstrap(self.runtime, self.bootstrap_id)
        self.assertEqual(result.receipt.status, GoalBootstrapStatus.READY)
        self.assertEqual(result.materialization.materialization_id, plmat_id)
        self.assertTrue(result.reused_materialization)
        self.assertEqual(self._count("plan_materializations"), 1)

    def test_crash_after_preppol_publish_before_checkpoint_reuses_exact_policy(self) -> None:
        from origin_forge import production_goal_bootstrap_finalize as module

        real_checkpoint = module.checkpoint_goal_bootstrap_preppol_published
        seen = {"calls": 0}

        def crash_once(*args, **kwargs):
            seen["calls"] += 1
            if seen["calls"] == 1:
                raise SimulatedCrash("after PREPPOL publish before READY checkpoint")
            return real_checkpoint(*args, **kwargs)

        with patch.object(
            module,
            "checkpoint_goal_bootstrap_preppol_published",
            side_effect=crash_once,
        ):
            with self.assertRaises(SimulatedCrash):
                finalize_goal_bootstrap(self.runtime, self.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.MATERIALIZED)
        self.assertEqual(durable.status, GoalBootstrapStatus.ACTIVE)
        self.assertEqual(len(self._policy_files()), 1)
        orphan_name = self._policy_files()[0].stem

        result = finalize_goal_bootstrap(self.runtime, self.bootstrap_id)
        self.assertEqual(result.receipt.status, GoalBootstrapStatus.READY)
        self.assertEqual(result.preparation_policy.preparation_policy_id, orphan_name)
        self.assertTrue(result.reused_preparation_policy)
        self.assertEqual(len(self._policy_files()), 1)

    def test_ready_state_is_idempotent_and_creates_no_new_authority(self) -> None:
        first = finalize_goal_bootstrap(self.runtime, self.bootstrap_id)
        before = (
            self._count("plan_audits"),
            self._count("plan_materializations"),
            len(self._policy_files()),
            self._count("flows"),
            self._count("tasks"),
        )
        second = finalize_goal_bootstrap(self.runtime, self.bootstrap_id)
        after = (
            self._count("plan_audits"),
            self._count("plan_materializations"),
            len(self._policy_files()),
            self._count("flows"),
            self._count("tasks"),
        )

        self.assertEqual(second.status, GoalBootstrapFinalizeStatus.ALREADY_READY)
        self.assertEqual(first.receipt, second.receipt)
        self.assertEqual(first.plan_audit, second.plan_audit)
        self.assertEqual(first.materialization, second.materialization)
        self.assertEqual(first.preparation_policy, second.preparation_policy)
        self.assertEqual(before, after)

    def test_goal_revision_drift_interrupts_before_audit_or_materialization(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE goals SET revision = revision + 1, updated_at = updated_at WHERE id = ?",
                (self.goal_id,),
            )

        with self.assertRaises(GoalBootstrapFinalizeInterrupted):
            finalize_goal_bootstrap(self.runtime, self.bootstrap_id)
        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNER_RETURNED)
        self.assertEqual(durable.status, GoalBootstrapStatus.INTERRUPTED)
        self.assertEqual(self._count("plan_audits"), 0)
        self.assertEqual(self._count("plan_materializations"), 0)
        self.assertEqual(len(self._policy_files()), 0)

    def test_concurrent_workers_publish_one_audit_plmat_and_preppol(self) -> None:
        barrier = threading.Barrier(3)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            runtime = OriginForgeRuntime(self.root)
            barrier.wait()
            try:
                result = finalize_goal_bootstrap(runtime, self.bootstrap_id)
                outcome = result.receipt.status.value
            except BaseException as exc:
                outcome = type(exc).__name__
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=15)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(outcomes), 2)
        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(
            durable.status,
            GoalBootstrapStatus.READY,
            msg=f"concurrent finalization outcomes: {outcomes!r}; stage={durable.stage.value}",
        )
        self.assertEqual(self._count("plan_audits"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(len(self._policy_files()), 1)
        self.assertEqual(self._count("flows"), 1)
        self.assertEqual(self._count("tasks"), 1)

    def test_checkpoint_contention_does_not_interrupt_valid_bootstrap(self) -> None:
        from origin_forge import production_goal_bootstrap_finalize as module

        real_checkpoint = module._checkpoint_locked
        seen = {"calls": 0}

        def contend_once(*args, **kwargs):
            seen["calls"] += 1
            if seen["calls"] == 1:
                raise StaleRevision("GOALBOOT changed during locked checkpoint")
            return real_checkpoint(*args, **kwargs)

        with patch.object(module, "_checkpoint_locked", side_effect=contend_once):
            result = finalize_goal_bootstrap(self.runtime, self.bootstrap_id)

        self.assertEqual(result.receipt.status, GoalBootstrapStatus.READY)
        self.assertEqual(seen["calls"], 2)
        self.assertEqual(self._count("plan_audits"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(len(self._policy_files()), 1)


if __name__ == "__main__":
    unittest.main()
