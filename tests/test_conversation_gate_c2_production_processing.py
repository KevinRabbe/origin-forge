from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.conversation_production_processing as processing_module
from origin_forge.conversation_production import admit_conversation_goal
from origin_forge.conversation_production_processing import (
    ConversationProductionRecoveryRequired,
    process_production_submission,
    recover_production_submission,
)
from origin_forge.conversation_service import (
    ConversationActorType,
    ConversationSubmissionStatus,
    create_conversation_session,
    list_conversation_turns,
    read_conversation_submission,
    submit_human_turn,
)
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
    inspect_goal_bootstrap_status_readonly,
)
from origin_forge.production_goal_bootstrap_store import (
    checkpoint_goal_bootstrap_planner_returned,
    checkpoint_goal_bootstrap_planner_started,
)
from origin_forge.production_materialization_read import read_plan_materialization
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


class ConversationGateC2ProductionProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("conversation-gate-c2-test")
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _VALID_CONFIG,
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _accepted_submission(
        self,
        content: str = "Implement one bounded governed production change.",
        *,
        client_submission_id: str = "client-gate-c2",
    ):
        session = create_conversation_session(self.runtime)
        receipt = submit_human_turn(
            self.runtime,
            session.id,
            content,
            client_submission_id,
            expected_revision=0,
        )
        return session, receipt

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
            summary="One bounded conversation production task.",
            steps=(
                PlanStep(
                    step_key="change",
                    objective="Implement the exact bounded conversation request.",
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

    def test_fresh_production_submission_reaches_only_ready_for_manager(self) -> None:
        session, submission = self._accepted_submission()

        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=self._fake_planner_return,
        ) as planner:
            result = process_production_submission(self.runtime, submission.id)

        self.assertEqual(result.submission.status, ConversationSubmissionStatus.RESPONDED)
        self.assertEqual(result.response_turn.actor_type, ConversationActorType.FORGE)
        self.assertEqual(planner.call_count, 1)
        turns = list_conversation_turns(self.runtime, session.id)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].actor_type, ConversationActorType.HUMAN)
        self.assertEqual(turns[1], result.response_turn)

        with self.runtime.store.session() as conn:
            goal_event = conn.execute(
                """SELECT aggregate_id FROM state_events
                   WHERE event_type = 'GOAL_CREATED'
                     AND actor_type = 'CONVERSATION' AND actor_id = ?""",
                (submission.id,),
            ).fetchone()
        self.assertIsNotNone(goal_event)
        goal_id = str(goal_event["aggregate_id"])
        projection = inspect_goal_bootstrap_status_readonly(self.runtime, goal_id)
        self.assertEqual(projection.decision, GoalBootstrapDecision.READY_FOR_MANAGER)
        self.assertIsNotNone(projection.receipt)
        bootstrap = projection.receipt
        self.assertEqual(bootstrap.status, GoalBootstrapStatus.READY)
        self.assertEqual(bootstrap.stage, GoalBootstrapStage.PREPPOL_PUBLISHED)
        materialization = read_plan_materialization(
            self.runtime,
            str(bootstrap.materialization_id),
        )
        task_ids = tuple(binding.task_id for binding in materialization.task_bindings)

        with self.runtime.store.session() as conn:
            references = {
                (str(row["reference_type"]), str(row["reference_id"]), str(row["relation"]))
                for row in conn.execute(
                    """SELECT reference_type, reference_id, relation
                       FROM conversation_turn_references
                       WHERE turn_id = ?""",
                    (submission.human_turn_id,),
                ).fetchall()
            }
        self.assertEqual(
            references,
            {
                ("GOAL", goal_id, "RESULT"),
                ("FLOW", materialization.flow_id, "RESULT"),
                *(("TASK", task_id, "RESULT") for task_id in task_ids),
            },
        )
        self.assertIn(goal_id, result.response_turn.content)
        self.assertIn(str(bootstrap.bootstrap_id), result.response_turn.content)
        self.assertIn(materialization.flow_id, result.response_turn.content)
        self.assertIn("READY_FOR_MANAGER", result.response_turn.content)
        for task_id in task_ids:
            self.assertIn(task_id, result.response_turn.content)
        self.assertEqual(self.runtime.count_goals(), 1)
        self.assertEqual(self.runtime.count_flows(), 1)
        self.assertEqual(self.runtime.count_tasks(), len(task_ids))
        self.assertEqual(self.runtime.count_runs(), 0)
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)

    def test_responded_retry_never_replays_bootstrap_or_recovery(self) -> None:
        _, submission = self._accepted_submission()
        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=self._fake_planner_return,
        ):
            first = process_production_submission(self.runtime, submission.id)

        with patch.object(
            processing_module,
            "bootstrap_goal_once",
            side_effect=AssertionError("responded retry must not bootstrap"),
        ) as bootstrap, patch.object(
            processing_module,
            "recover_goal_once",
            side_effect=AssertionError("responded retry must not recover"),
        ) as recover:
            second = process_production_submission(self.runtime, submission.id)

        self.assertEqual(second, first)
        bootstrap.assert_not_called()
        recover.assert_not_called()
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(self.runtime.count_flows(), 1)
        self.assertEqual(self.runtime.count_tasks(), 1)

    def test_restart_after_ready_before_response_finishes_without_production_replay(self) -> None:
        _, submission = self._accepted_submission()
        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=self._fake_planner_return,
        ), patch.object(
            processing_module,
            "_complete_conversation_submission",
            side_effect=RuntimeError("simulated interruption after READY handoff"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                process_production_submission(self.runtime, submission.id)

        self.assertEqual(
            read_conversation_submission(self.runtime, submission.id).status,
            ConversationSubmissionStatus.PROCESSING,
        )
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(self.runtime.count_flows(), 1)
        self.assertEqual(self.runtime.count_tasks(), 1)

        restarted = OriginForgeRuntime(self.root)
        restarted.initialize("conversation-gate-c2-test")
        with patch.object(
            processing_module,
            "bootstrap_goal_once",
            side_effect=AssertionError("READY retry must not bootstrap"),
        ) as bootstrap, patch.object(
            processing_module,
            "recover_goal_once",
            side_effect=AssertionError("READY retry must not recover"),
        ) as recover:
            result = process_production_submission(restarted, submission.id)

        self.assertEqual(result.submission.status, ConversationSubmissionStatus.RESPONDED)
        bootstrap.assert_not_called()
        recover.assert_not_called()
        self.assertEqual(restarted.count_flows(), 1)
        self.assertEqual(restarted.count_tasks(), 1)
        with restarted.store.session() as conn:
            self.assertEqual(
                int(
                    conn.execute(
                        """SELECT COUNT(*) FROM conversation_turn_references
                           WHERE turn_id = ? AND relation = 'RESULT'""",
                        (submission.human_turn_id,),
                    ).fetchone()[0]
                ),
                3,
            )

    def test_existing_active_bootstrap_requires_explicit_recovery(self) -> None:
        _, submission = self._accepted_submission()
        admission = admit_conversation_goal(self.runtime, submission.id)
        acquired = acquire_current_goal_bootstrap(self.runtime, admission.goal_id)

        with self.assertRaises(ConversationProductionRecoveryRequired):
            process_production_submission(self.runtime, submission.id)

        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 0)
        self.assertEqual(self.runtime.count_flows(), 0)
        self.assertEqual(self.runtime.count_tasks(), 0)
        with patch(
            "origin_forge.production_goal_bootstrap_operator.advance_goal_bootstrap_planner",
            side_effect=self._fake_planner_return,
        ) as planner:
            result = recover_production_submission(self.runtime, submission.id)

        self.assertEqual(result.submission.status, ConversationSubmissionStatus.RESPONDED)
        self.assertEqual(planner.call_count, 1)
        projection = inspect_goal_bootstrap_status_readonly(
            self.runtime,
            admission.goal_id,
        )
        self.assertEqual(projection.decision, GoalBootstrapDecision.READY_FOR_MANAGER)
        self.assertEqual(projection.receipt.bootstrap_id, acquired.bootstrap_id)
        self.assertEqual(self._count("goal_bootstraps"), 1)
        self.assertEqual(self._count("plan_materializations"), 1)
        self.assertEqual(self.runtime.count_flows(), 1)
        self.assertEqual(self.runtime.count_tasks(), 1)
        self.assertEqual(self._count("dispatch_claims"), 0)
        self.assertEqual(self._count("dispatch_executions"), 0)

    def test_production_processing_is_project_scoped(self) -> None:
        _, submission = self._accepted_submission()
        with tempfile.TemporaryDirectory() as other_temp:
            other = OriginForgeRuntime(Path(other_temp))
            other.initialize("other-project")
            other.state_dir.joinpath("config.toml").write_text(
                _VALID_CONFIG,
                encoding="utf-8",
            )
            with self.assertRaises(KeyError):
                process_production_submission(other, submission.id)
            self.assertEqual(other.count_goals(), 0)
            self.assertEqual(other.count_flows(), 0)
            self.assertEqual(other.count_tasks(), 0)

        self.assertEqual(
            read_conversation_submission(self.runtime, submission.id).status,
            ConversationSubmissionStatus.ACCEPTED,
        )
        self.assertEqual(self.runtime.count_goals(), 0)

    def test_gate_c2_contains_no_manager_dispatch_execution_verification_or_adoption_shortcut(self) -> None:
        source = inspect.getsource(processing_module)
        for forbidden in (
            "production_manager_",
            "advance_production_manager",
            "dispatch_claim",
            "dispatch_execution",
            "BoundedTaskOrchestrator",
            "record_verification(",
            "adopt_",
            "start_run(",
            "create_flow(",
            "create_task(",
            "INSERT INTO flows",
            "INSERT INTO tasks",
            "subprocess",
            "http.server",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
