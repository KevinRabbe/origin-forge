from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from origin_forge import cli
from origin_forge.ids import IdKind, new_id
from origin_forge.production_goal_bootstrap_authority import (
    acquire_current_goal_bootstrap,
    prepare_goal_bootstrap_input,
)
from origin_forge.production_goal_bootstrap_models import (
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from origin_forge.production_goal_bootstrap_planner import (
    advance_goal_bootstrap_planner,
    assemble_goal_bootstrap_planner_environment,
)
from origin_forge.production_goal_bootstrap_store import (
    checkpoint_goal_bootstrap_planner_returned,
    checkpoint_goal_bootstrap_planner_started,
    read_goal_bootstrap_receipt,
)
from origin_forge.production_planner import DeterministicPlannerAdapter
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

    def load(self, profile, lease):
        return self.adapter

    def unload(self, instance) -> None:
        if instance is not self.adapter:
            raise AssertionError("unexpected Planner model instance")


class FakeManagedLoader:
    def __init__(self, project_root, provider):
        self.provider = provider

    def load(self, profile, lease):
        raise AssertionError("managed runtime load must be replaced by FakeDispatchLoader")

    def unload(self, instance) -> None:
        raise AssertionError("managed runtime unload must be replaced by FakeDispatchLoader")


class GoalBootstrapCliAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase46b-cli-acceptance")
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _VALID_CONFIG,
            encoding="utf-8",
        )
        self.goal_id = self.runtime.create_goal("bootstrap one exact Goal from the CLI")
        self.adapter = DeterministicPlannerAdapter(
            _RESPONSE,
            fixture_model_id="test-model",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _count(self, table: str) -> int:
        with self.runtime.store.session() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _run_cli(self, operation: str) -> tuple[int, dict[str, object] | None, dict[str, object] | None]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(
                [
                    "--project-root",
                    str(self.root),
                    "goal",
                    "bootstrap",
                    operation,
                    self.goal_id,
                ]
            )
        out = json.loads(stdout.getvalue()) if stdout.getvalue() else None
        err = json.loads(stderr.getvalue()) if stderr.getvalue() else None
        return code, out, err

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
        return replace(real, runtime_dispatch_loader=FakeDispatchLoader(self.adapter))

    def test_cli_fresh_start_reaches_ready_and_second_start_is_idempotent(self) -> None:
        with (
            patch(
                "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
                side_effect=self._fake_planner_return,
            ) as planner,
            patch(
                "origin_forge.cli.advance_production_manager_bounded",
                side_effect=AssertionError("bootstrap CLI must not invoke Manager"),
            ) as manager,
        ):
            first_code, first, first_error = self._run_cli("start")
            second_code, second, second_error = self._run_cli("start")
            status_code, status, status_error = self._run_cli("status")

        self.assertEqual(first_code, 0)
        self.assertIsNone(first_error)
        self.assertEqual(first["action"], "BOOTSTRAP")
        self.assertEqual(first["status"], "READY")
        self.assertEqual(first["receipt"]["status"], "READY")

        self.assertEqual(second_code, 0)
        self.assertIsNone(second_error)
        self.assertEqual(second["action"], "BOOTSTRAP")
        self.assertEqual(second["status"], "ALREADY_READY")
        self.assertEqual(
            second["receipt"]["bootstrap_id"],
            first["receipt"]["bootstrap_id"],
        )

        self.assertEqual(status_code, 0)
        self.assertIsNone(status_error)
        self.assertEqual(status["decision"], "READY_FOR_MANAGER")
        self.assertEqual(
            status["receipt"]["bootstrap_id"],
            first["receipt"]["bootstrap_id"],
        )

        self.assertEqual(planner.call_count, 1)
        manager.assert_not_called()
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)

    def test_cli_start_blocks_existing_authority_then_explicit_recover_reuses_it(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)

        with (
            patch(
                "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
                side_effect=self._fake_planner_return,
            ) as planner,
            patch(
                "origin_forge.cli.advance_production_manager_bounded",
                side_effect=AssertionError("bootstrap CLI must not invoke Manager"),
            ) as manager,
        ):
            start_code, start_out, start_error = self._run_cli("start")
            recover_code, recovered, recover_error = self._run_cli("recover")

        self.assertEqual(start_code, 4)
        self.assertIsNone(start_out)
        self.assertEqual(start_error["error"], "GOAL_BOOTSTRAP_BLOCKED")
        self.assertEqual(start_error["decision"], "ACTIVE_PRE_PLANNER")

        self.assertEqual(recover_code, 0)
        self.assertIsNone(recover_error)
        self.assertEqual(recovered["action"], "RECOVER")
        self.assertEqual(recovered["status"], "READY")
        self.assertEqual(recovered["receipt"]["bootstrap_id"], acquired.bootstrap_id)
        self.assertEqual(planner.call_count, 1)
        manager.assert_not_called()
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)

    def test_cli_recover_on_eligible_goal_does_not_auto_start_replacement_authority(self) -> None:
        with patch(
            "origin_forge.cli.advance_production_manager_bounded",
            side_effect=AssertionError("bootstrap CLI must not invoke Manager"),
        ) as manager:
            code, out, error = self._run_cli("recover")

        self.assertEqual(code, 4)
        self.assertIsNone(out)
        self.assertEqual(error["error"], "GOAL_BOOTSTRAP_BLOCKED")
        self.assertEqual(error["decision"], "ELIGIBLE")
        manager.assert_not_called()
        self.assertEqual(self._count("goal_bootstraps"), 0)
        self.assertEqual(self._count("plan_materializations"), 0)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)

    def test_cli_uncertain_planner_recovery_interrupts_without_model_replay_or_replacement(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        prepare_goal_bootstrap_input(self.runtime, acquired.bootstrap_id)

        with (
            patch(
                "origin_forge.production_goal_bootstrap_planner."
                "assemble_goal_bootstrap_planner_environment",
                side_effect=self._environment,
            ),
            patch(
                "origin_forge.production_goal_bootstrap_planner."
                "_publish_proposal_and_generation_proof",
                side_effect=SimulatedCrash("after model call before durable result"),
            ),
        ):
            with self.assertRaises(SimulatedCrash):
                advance_goal_bootstrap_planner(self.runtime, acquired.bootstrap_id)

        uncertain = read_goal_bootstrap_receipt(self.runtime, acquired.bootstrap_id)
        self.assertEqual(uncertain.stage, GoalBootstrapStage.PLANNER_STARTED)
        self.assertEqual(uncertain.status, GoalBootstrapStatus.ACTIVE)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertEqual(self._count("plan_proposals"), 0)
        self.assertEqual(self._count("goal_bootstraps"), 1)

        with (
            patch(
                "origin_forge.production_goal_bootstrap_planner."
                "assemble_goal_bootstrap_planner_environment",
                side_effect=self._environment,
            ),
            patch(
                "origin_forge.cli.advance_production_manager_bounded",
                side_effect=AssertionError("bootstrap CLI must not invoke Manager"),
            ) as manager,
        ):
            recover_code, recover_out, recover_error = self._run_cli("recover")
            start_code, start_out, start_error = self._run_cli("start")

        self.assertEqual(recover_code, 5)
        self.assertIsNone(recover_out)
        self.assertEqual(recover_error["error"], "GOAL_BOOTSTRAP_ERROR")
        self.assertEqual(self.adapter.call_count, 1)

        interrupted = read_goal_bootstrap_receipt(self.runtime, acquired.bootstrap_id)
        self.assertEqual(interrupted.stage, GoalBootstrapStage.PLANNER_STARTED)
        self.assertEqual(interrupted.status, GoalBootstrapStatus.INTERRUPTED)

        self.assertEqual(start_code, 4)
        self.assertIsNone(start_out)
        self.assertEqual(start_error["error"], "GOAL_BOOTSTRAP_BLOCKED")
        self.assertEqual(start_error["decision"], "INTERRUPTED")
        manager.assert_not_called()
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 0)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)


if __name__ == "__main__":
    unittest.main()
