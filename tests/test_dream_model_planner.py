from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_model_planner import ModelDreamPlanningCoordinator
from origin_forge.dream_models import DreamBudget, DreamCandidateType, DreamDownstreamGate
from origin_forge.dream_planner import DreamPlanningError
from origin_forge.dream_roles import DreamAuditStatus
from origin_forge.dream_store import DreamStore
from origin_forge.model import ModelResponse
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class FakeDreamModel:
    def __init__(
        self,
        payload: object,
        *,
        input_tokens: int | None = 100,
        output_tokens: int | None = 25,
    ):
        self.payload = payload
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.requests = []

    @property
    def model_id(self) -> str:
        return "dream-planner-model"

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            text=json.dumps(self.payload),
            model_id=self.model_id,
            model_hash="sha256:dream-planner-model",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class ModelDreamPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("model-dream-planner-test")
        self.store = DreamStore(self.runtime)

        goal = self.runtime.create_goal("Completed evidence")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Produce terminal evidence")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        self.evidence_run = self.runtime.start_run(task, role="EXECUTOR")
        self.runtime.finish_run(
            self.evidence_run,
            RunStatus.FAILED,
            failure_reason="repeatable failure",
        )
        task_row = self.runtime.get_task(task)
        self.runtime.transition_task(
            task,
            TaskStatus.FAILED,
            expected_revision=int(task_row["revision"]),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _active_model_run(self, *, role: str = "DREAM_ANALYZER") -> tuple[str, str]:
        goal = self.runtime.create_goal("Offline Dream analysis")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Analyze frozen completed work")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        run = self.runtime.start_run(task, role=role, model_profile="dream-model")
        return task, run

    def _payload(self):
        return {
            "candidates": [
                {
                    "candidate_type": "SKILL",
                    "summary": "Repeated terminal failures suggest a reusable debugging procedure.",
                    "proposed_action": "Benchmark a governed debugging Skill candidate.",
                    "evidence_ref_ids": [self.evidence_run],
                    "contradiction_ref_ids": [],
                }
            ]
        }

    def test_model_plan_is_audited_persisted_proposal_only(self) -> None:
        task, model_run = self._active_model_run()
        model = FakeDreamModel(self._payload())
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        before_generations = self.store.list_generation_ids()

        result = planner.plan(
            (self.evidence_run,),
            model_run_id=model_run,
            model_task_id=task,
        )

        self.assertEqual(len(model.requests), 1)
        self.assertEqual(len(result.plan.candidates), 1)
        candidate = result.plan.candidates[0]
        audit = result.plan.audits[0]
        self.assertEqual(candidate.candidate_type, DreamCandidateType.SKILL)
        self.assertEqual(candidate.required_gate, DreamDownstreamGate.SKILL_EVALUATION)
        self.assertEqual(audit.status, DreamAuditStatus.STRUCTURALLY_VALID)
        self.assertTrue(audit.semantic_review_required)
        self.assertEqual(result.model_analysis.candidates, (candidate,))
        self.assertEqual(result.model_analysis.input_tokens, 100)
        self.assertEqual(result.model_analysis.output_tokens, 25)
        self.assertEqual(self.store.load_candidate(candidate.candidate_id), candidate)
        self.assertEqual(self.store.list_generation_ids(), before_generations)
        self.assertEqual(self.runtime.get_run(model_run)["status"], RunStatus.RUNNING.value)
        self.assertFalse(result.to_dict()["memory_generation_created"])
        self.assertFalse(result.to_dict()["canonical_project_state_changed"])

    def test_zero_model_call_budget_fails_before_model_or_persistence(self) -> None:
        task, model_run = self._active_model_run()
        model = FakeDreamModel(self._payload())
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        before = self.store.list_manifest_ids()
        with self.assertRaisesRegex(DreamPlanningError, "disabled by the frozen budget"):
            planner.plan(
                (self.evidence_run,),
                model_run_id=model_run,
                model_task_id=task,
                budget=DreamBudget(max_model_calls=0),
            )
        self.assertEqual(model.requests, [])
        self.assertEqual(self.store.list_manifest_ids(), before)

    def test_wrong_model_role_fails_before_model_or_persistence(self) -> None:
        task, model_run = self._active_model_run(role="EXECUTOR")
        model = FakeDreamModel(self._payload())
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        before = self.store.list_manifest_ids()
        with self.assertRaisesRegex(DreamPlanningError, "exactly DREAM_ANALYZER"):
            planner.plan(
                (self.evidence_run,),
                model_run_id=model_run,
                model_task_id=task,
            )
        self.assertEqual(model.requests, [])
        self.assertEqual(self.store.list_manifest_ids(), before)

    def test_model_run_must_belong_to_supplied_task(self) -> None:
        first_task, model_run = self._active_model_run()
        second_task, second_run = self._active_model_run()
        self.assertNotEqual(first_task, second_task)
        self.assertNotEqual(model_run, second_run)
        model = FakeDreamModel(self._payload())
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        with self.assertRaisesRegex(DreamPlanningError, "does not belong"):
            planner.plan(
                (self.evidence_run,),
                model_run_id=model_run,
                model_task_id=second_task,
            )
        self.assertEqual(model.requests, [])

    def test_missing_token_accounting_fails_closed_without_partial_persistence(self) -> None:
        task, model_run = self._active_model_run()
        model = FakeDreamModel(self._payload(), input_tokens=None, output_tokens=None)
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        before = self.store.list_manifest_ids()
        with self.assertRaisesRegex(DreamPlanningError, "requires reported input/output token counts"):
            planner.plan(
                (self.evidence_run,),
                model_run_id=model_run,
                model_task_id=task,
            )
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(self.store.list_manifest_ids(), before)
        self.assertEqual(self.store.list_candidate_ids(), ())

    def test_token_overflow_fails_closed_without_partial_persistence(self) -> None:
        task, model_run = self._active_model_run()
        model = FakeDreamModel(self._payload(), input_tokens=8, output_tokens=5)
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        with self.assertRaisesRegex(DreamPlanningError, "exceeded frozen token budget"):
            planner.plan(
                (self.evidence_run,),
                model_run_id=model_run,
                model_task_id=task,
                budget=DreamBudget(max_analysis_tokens=12),
            )
        self.assertEqual(self.store.list_manifest_ids(), ())
        self.assertEqual(self.store.list_candidate_ids(), ())

    def test_semantically_duplicate_model_candidates_are_deduplicated(self) -> None:
        task, model_run = self._active_model_run()
        item = self._payload()["candidates"][0]
        model = FakeDreamModel({"candidates": [dict(item), dict(item)]})
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        result = planner.plan(
            (self.evidence_run,),
            model_run_id=model_run,
            model_task_id=task,
        )
        self.assertEqual(len(result.plan.candidates), 1)
        self.assertEqual(len(result.model_analysis.candidates), 1)
        self.assertEqual(len(self.store.list_candidate_ids()), 1)

    def test_model_planner_exposes_no_generation_promotion_or_project_mutation_operation(self) -> None:
        model = FakeDreamModel({"candidates": []})
        planner = ModelDreamPlanningCoordinator(self.runtime, model, self.store)
        for forbidden in (
            "build_generation",
            "promote",
            "apply",
            "write_source",
            "change_policy",
            "merge",
            "finish_run",
        ):
            self.assertFalse(hasattr(planner, forbidden))


if __name__ == "__main__":
    unittest.main()
