from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from origin_forge.production_goal_bootstrap_authority import (
    acquire_current_goal_bootstrap,
    prepare_goal_bootstrap_input,
)
from origin_forge.production_goal_bootstrap_models import (
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from origin_forge.production_goal_bootstrap_planner import (
    GoalBootstrapPlannerInterrupted,
    advance_goal_bootstrap_planner,
    assemble_goal_bootstrap_planner_environment,
)
from origin_forge.production_goal_bootstrap_store import read_goal_bootstrap_receipt
from origin_forge.production_planner import DeterministicPlannerAdapter
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

_RESPONSE = '''{
  "summary": "Implement one bounded code change.",
  "steps": [
    {
      "step_key": "change",
      "objective": "Implement the requested bounded code change.",
      "acceptance_criteria": ["The bounded change is implemented and verified."],
      "constraints": ["Stay within the frozen Goal authority."],
      "required_capabilities": ["code.change"],
      "priority": 0,
      "budget_hint": {"attempts": 1},
      "depends_on": []
    }
  ]
}'''


class SimulatedCrash(BaseException):
    pass


class FakeDispatchLoader:
    def __init__(self, adapter: DeterministicPlannerAdapter):
        self.adapter = adapter
        self.load_count = 0
        self.unload_count = 0

    def load(self, profile, lease):
        self.load_count += 1
        return self.adapter

    def unload(self, instance) -> None:
        self.unload_count += 1
        if instance is not self.adapter:
            raise AssertionError("unexpected model instance")


class FakeManagedLoader:
    def __init__(self, project_root, provider):
        self.provider = provider

    def load(self, profile, lease):
        raise AssertionError("managed runtime load must be replaced by FakeDispatchLoader")

    def unload(self, instance) -> None:
        raise AssertionError("managed runtime unload must be replaced by FakeDispatchLoader")


class GoalBootstrapPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase45c-governed-planner")
        self.goal_id = self.runtime.create_goal("plan one bounded code change")
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _VALID_CONFIG,
            encoding="utf-8",
        )
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        self.bootstrap_id = acquired.bootstrap_id
        self.receipt, self.planning_input = prepare_goal_bootstrap_input(
            self.runtime,
            self.bootstrap_id,
        )
        self.adapter = DeterministicPlannerAdapter(
            _RESPONSE,
            fixture_model_id="test-model",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _environment(self, runtime, receipt, planning_input):
        with patch(
            "origin_forge.production_goal_bootstrap_planner.ManagedLlamaCppCpuLoader",
            FakeManagedLoader,
        ):
            real = assemble_goal_bootstrap_planner_environment(
                runtime,
                receipt,
                planning_input,
            )
        return replace(
            real,
            runtime_dispatch_loader=FakeDispatchLoader(self.adapter),
        )

    def _advance(self, runtime=None):
        runtime = runtime or self.runtime
        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ):
            return advance_goal_bootstrap_planner(runtime, self.bootstrap_id)

    def _count(self, table: str) -> int:
        with self.runtime.store.session() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _marker_run_id(self, runtime=None) -> str:
        runtime = runtime or self.runtime
        with runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT target_id, target_type, evidence_json, run_id
                   FROM verifications
                   WHERE verification_type = 'goal-bootstrap-planner-dispatch'
                   ORDER BY created_at, id"""
            ).fetchall()
        matches = []
        for row in rows:
            evidence = json.loads(row["evidence_json"])
            if evidence.get("goal_bootstrap_id") == self.bootstrap_id:
                matches.append(row)
        self.assertEqual(len(matches), 1)
        row = matches[0]
        self.assertEqual(row["target_type"], "RUN")
        self.assertEqual(row["run_id"], row["target_id"])
        return str(row["target_id"])

    def test_normal_path_commits_marker_before_model_and_stops_at_planner_returned(self) -> None:
        result = self._advance()

        self.assertFalse(result.recovered)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(result.receipt.stage, GoalBootstrapStage.PLANNER_RETURNED)
        self.assertEqual(result.receipt.status, GoalBootstrapStatus.ACTIVE)
        self.assertEqual(result.receipt.planner_run_id, result.planner_run_id)
        self.assertEqual(
            result.receipt.planner_dependency_plan_hash,
            result.planner_dependency_plan_hash,
        )
        self.assertEqual(result.receipt.plan_proposal_id, result.proposal.proposal_id)
        self.assertEqual(result.receipt.plan_proposal_hash, result.proposal.content_hash)
        self.assertEqual(self._marker_run_id(), result.planner_run_id)
        self.assertEqual(self._count("plan_proposals"), 1)
        self.assertEqual(self._count("plan_audits"), 0)
        self.assertEqual(self._count("plan_materializations"), 0)

        run = self.runtime.get_run(result.planner_run_id)
        self.assertEqual(run["role"], "PLANNER")
        self.assertIsNone(run["task_id"])
        self.assertEqual(run["model_profile"], "test-model")
        self.assertEqual(run["status"], "SUCCEEDED")

        verifications = self.runtime.list_verifications("RUN", result.planner_run_id)
        self.assertEqual(
            [row["verification_type"] for row in verifications],
            [
                "goal-bootstrap-planner-dispatch",
                "model-resource-selection",
                "planner-generation",
            ],
        )

    def test_planner_started_keeps_run_null_but_marker_exists_before_model_request(self) -> None:
        observed = {}

        def crash_before_invoke(
            runtime,
            receipt,
            planning_input,
            environment,
            scheduled,
            plan,
            run_id,
        ):
            durable = read_goal_bootstrap_receipt(runtime, receipt.bootstrap_id)
            observed["stage"] = durable.stage
            observed["receipt_run_id"] = durable.planner_run_id
            observed["marker_run_id"] = self._marker_run_id(runtime)
            observed["plan_hash"] = durable.planner_dependency_plan_hash
            observed["expected_run"] = run_id
            observed["expected_hash"] = plan.plan_hash
            observed["model_calls"] = self.adapter.call_count
            raise SimulatedCrash("after dispatch marker before model request")

        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ), patch(
            "origin_forge.production_goal_bootstrap_planner._invoke_reserved_planner",
            side_effect=crash_before_invoke,
        ):
            with self.assertRaises(SimulatedCrash):
                advance_goal_bootstrap_planner(self.runtime, self.bootstrap_id)

        self.assertEqual(observed["stage"], GoalBootstrapStage.PLANNER_STARTED)
        self.assertIsNone(observed["receipt_run_id"])
        self.assertEqual(observed["marker_run_id"], observed["expected_run"])
        self.assertEqual(observed["plan_hash"], observed["expected_hash"])
        self.assertEqual(observed["model_calls"], 0)

    def test_crash_before_durable_planner_started_is_safe_for_fresh_attempt(self) -> None:
        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ), patch(
            "origin_forge.production_goal_bootstrap_planner._checkpoint_planner_started",
            side_effect=SimulatedCrash("before durable PLANNER_STARTED"),
        ):
            with self.assertRaises(SimulatedCrash):
                advance_goal_bootstrap_planner(self.runtime, self.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNING_INPUT_PUBLISHED)
        self.assertIsNone(durable.planner_run_id)
        self.assertIsNone(durable.planner_dependency_plan_hash)
        self.assertEqual(self.adapter.call_count, 0)
        self.assertEqual(self._count("runs"), 0)

        result = self._advance()
        self.assertEqual(result.receipt.stage, GoalBootstrapStage.PLANNER_RETURNED)
        self.assertEqual(self.adapter.call_count, 1)

    def test_started_without_dispatch_marker_is_safe_to_resume_once(self) -> None:
        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ), patch(
            "origin_forge.production_goal_bootstrap_planner._claim_or_load_dispatch_marker",
            side_effect=SimulatedCrash("after PLANNER_STARTED before dispatch marker"),
        ):
            with self.assertRaises(SimulatedCrash):
                advance_goal_bootstrap_planner(self.runtime, self.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNER_STARTED)
        self.assertIsNone(durable.planner_run_id)
        self.assertIsNotNone(durable.planner_dependency_plan_hash)
        self.assertEqual(self._count("runs"), 0)
        self.assertEqual(self.adapter.call_count, 0)

        restarted = OriginForgeRuntime(self.root)
        result = self._advance(restarted)
        self.assertTrue(result.recovered)
        self.assertEqual(result.receipt.stage, GoalBootstrapStage.PLANNER_RETURNED)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(self._count("runs"), 1)

    def test_uncertain_post_call_crash_without_durable_result_interrupts_without_retry(self) -> None:
        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ), patch(
            "origin_forge.production_goal_bootstrap_planner."
            "_publish_proposal_and_generation_proof",
            side_effect=SimulatedCrash("after model call before durable result"),
        ):
            with self.assertRaises(SimulatedCrash):
                advance_goal_bootstrap_planner(self.runtime, self.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNER_STARTED)
        self.assertEqual(durable.status, GoalBootstrapStatus.ACTIVE)
        self.assertIsNone(durable.planner_run_id)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(self._count("plan_proposals"), 0)
        run_id = self._marker_run_id()

        restarted = OriginForgeRuntime(self.root)
        with self.assertRaises(GoalBootstrapPlannerInterrupted):
            self._advance(restarted)
        after = read_goal_bootstrap_receipt(restarted, self.bootstrap_id)
        self.assertEqual(after.stage, GoalBootstrapStage.PLANNER_STARTED)
        self.assertEqual(after.status, GoalBootstrapStatus.INTERRUPTED)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(restarted.get_run(run_id)["status"], "INTERRUPTED")

    def test_crash_after_atomic_result_before_return_checkpoint_recovers_without_model_call(self) -> None:
        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ), patch(
            "origin_forge.production_goal_bootstrap_planner."
            "checkpoint_goal_bootstrap_planner_returned",
            side_effect=SimulatedCrash("after durable result before PLANNER_RETURNED"),
        ):
            with self.assertRaises(SimulatedCrash):
                advance_goal_bootstrap_planner(self.runtime, self.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, self.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNER_STARTED)
        self.assertEqual(durable.status, GoalBootstrapStatus.ACTIVE)
        self.assertIsNone(durable.planner_run_id)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(self._count("plan_proposals"), 1)
        run_id = self._marker_run_id()
        verifications = self.runtime.list_verifications("RUN", run_id)
        self.assertEqual(
            len(
                [
                    row
                    for row in verifications
                    if row["verification_type"] == "planner-generation"
                ]
            ),
            1,
        )

        restarted = OriginForgeRuntime(self.root)
        result = self._advance(restarted)
        self.assertTrue(result.recovered)
        self.assertEqual(result.receipt.stage, GoalBootstrapStage.PLANNER_RETURNED)
        self.assertEqual(result.receipt.planner_run_id, run_id)
        self.assertEqual(result.receipt.plan_proposal_id, result.proposal.proposal_id)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(self._count("plan_proposals"), 1)

    def test_started_attempt_fails_closed_on_protected_config_drift(self) -> None:
        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ), patch(
            "origin_forge.production_goal_bootstrap_planner._invoke_reserved_planner",
            side_effect=SimulatedCrash("started before request"),
        ):
            with self.assertRaises(SimulatedCrash):
                advance_goal_bootstrap_planner(self.runtime, self.bootstrap_id)

        changed = _VALID_CONFIG.replace(
            'model_id = "test-model"',
            'model_id = "different-model"',
        )
        self.runtime.state_dir.joinpath("config.toml").write_text(changed, encoding="utf-8")

        restarted = OriginForgeRuntime(self.root)
        with self.assertRaises(GoalBootstrapPlannerInterrupted):
            advance_goal_bootstrap_planner(restarted, self.bootstrap_id)
        durable = read_goal_bootstrap_receipt(restarted, self.bootstrap_id)
        self.assertEqual(durable.status, GoalBootstrapStatus.INTERRUPTED)
        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNER_STARTED)
        self.assertEqual(self.adapter.call_count, 0)

    def test_concurrent_workers_create_one_marker_and_at_most_one_model_call(self) -> None:
        barrier = threading.Barrier(3)
        outcomes: list[tuple[str, str]] = []
        outcome_lock = threading.Lock()

        def worker() -> None:
            runtime = OriginForgeRuntime(self.root)
            barrier.wait()
            try:
                result = advance_goal_bootstrap_planner(runtime, self.bootstrap_id)
                outcome = ("result", result.receipt.stage.value)
            except BaseException as exc:
                outcome = ("error", type(exc).__name__)
            with outcome_lock:
                outcomes.append(outcome)

        with patch(
            "origin_forge.production_goal_bootstrap_planner."
            "assemble_goal_bootstrap_planner_environment",
            side_effect=self._environment,
        ):
            threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(self._count("runs"), 1)
        self._marker_run_id()
        self.assertLessEqual(self.adapter.call_count, 1)
        with self.runtime.store.session() as conn:
            marker_count = int(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications
                       WHERE verification_type = 'goal-bootstrap-planner-dispatch'"""
                ).fetchone()[0]
            )
        self.assertEqual(marker_count, 1)

    def test_planner_returned_is_idempotent_and_never_calls_model_again(self) -> None:
        first = self._advance()
        second = self._advance()

        self.assertEqual(first.receipt, second.receipt)
        self.assertEqual(first.proposal, second.proposal)
        self.assertTrue(second.recovered)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(self._count("plan_proposals"), 1)
        self.assertEqual(self._count("runs"), 1)


if __name__ == "__main__":
    unittest.main()
