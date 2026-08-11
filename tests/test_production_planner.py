from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_planner as production_planner_module
from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.model_scheduler import (
    ModelProfileRegistry,
    ModelResourceProfile,
    ModelRole,
    ModelScheduler,
    ModelSelectionPolicy,
)
from origin_forge.production_planner import (
    BoundedProductionPlanner,
    DeterministicPlannerAdapter,
)
from origin_forge.production_planning_evidence import (
    ProductionPlanningEvidenceStore,
    freeze_planning_input,
)
from origin_forge.resource_scheduler import ResourceCapacity, ResourceRequest, ResourceScheduler
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import (
    RuntimeModelScheduleRecorder,
    ScheduledModelAdapter,
)
from origin_forge.state import GoalStatus, RunStatus


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _plan_json() -> str:
    return json.dumps(
        {
            "summary": "Implement and observe the feature.",
            "steps": [
                {
                    "step_key": "code",
                    "objective": "Implement the feature.",
                    "acceptance_criteria": ["Implementation tests pass."],
                    "constraints": [],
                    "required_capabilities": ["code"],
                    "priority": 50,
                    "budget_hint": {"attempts": 2},
                    "depends_on": [],
                },
                {
                    "step_key": "runtime",
                    "objective": "Observe the feature.",
                    "acceptance_criteria": ["Runtime evidence is captured."],
                    "constraints": [],
                    "required_capabilities": ["runtime-observation"],
                    "priority": 40,
                    "budget_hint": {"attempts": 1},
                    "depends_on": ["code"],
                },
            ],
        }
    )


class _GenericUnscheduledModel:
    @property
    def model_id(self) -> str:
        return "unscheduled"

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(_plan_json(), self.model_id)


class _ScheduledFixtureModel:
    def __init__(self, response_text: str, model_id: str):
        self.response_text = response_text
        self._model_id = model_id
        self.requests: list[ModelRequest] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            self.response_text,
            self._model_id,
            model_hash="fixture-hash",
            input_tokens=30,
            output_tokens=12,
        )


class _ScheduledFixtureLoader:
    def __init__(self, model: _ScheduledFixtureModel):
        self.model = model
        self.loaded = 0
        self.unloaded = 0

    def load(self, profile, lease):
        self.loaded += 1
        return self.model

    def unload(self, instance):
        self.unloaded += 1


class ProductionPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("planner-test")
        self.goal = self.runtime.create_goal(
            "Build a planned feature",
            success_criteria=("Feature behavior is verified.",),
            constraints=("Use only governed capabilities.",),
        )
        self.evidence = ProductionPlanningEvidenceStore(self.runtime)
        self.planning_input = freeze_planning_input(
            self.runtime,
            self.goal,
            project_intelligence_hash=_sha("project-intelligence"),
            capability_catalog_hash=_sha("catalog"),
            capability_ids=("code", "runtime-observation"),
            model_policy_hash=_sha("model-policy"),
            resource_policy_hash=_sha("resource-policy"),
        )
        self.evidence.publish_input(self.planning_input)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run_rows(self):
        with self.runtime.store.session() as conn:
            return conn.execute("SELECT * FROM runs ORDER BY started_at, rowid").fetchall()

    def test_deterministic_planner_makes_one_taskless_call_and_persists_proposal_evidence(self) -> None:
        model = DeterministicPlannerAdapter(
            _plan_json(),
            input_tokens=25,
            output_tokens=10,
        )
        planner = BoundedProductionPlanner(
            self.runtime,
            model,
            evidence_store=self.evidence,
        )
        result = planner.propose(self.planning_input.planning_input_id)

        self.assertEqual(model.call_count, 1)
        self.assertIsNotNone(model.last_request)
        self.assertIsNone(model.last_request.task_id)
        self.assertEqual(model.last_request.run_id, result.run_id)
        self.assertEqual(
            model.last_request.context["goal"]["objective"],
            "Build a planned feature",
        )
        self.assertEqual(
            model.last_request.context["goal"]["success_criteria"],
            ["Feature behavior is verified."],
        )
        self.assertEqual(
            model.last_request.context["planning_input"]["planning_input_id"],
            self.planning_input.planning_input_id,
        )

        run = self.runtime.get_run(result.run_id)
        self.assertIsNone(run["task_id"])
        self.assertEqual(run["role"], "PLANNER")
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(run["input_token_count"], 25)
        self.assertEqual(run["output_token_count"], 10)

        persisted = self.evidence.load_proposal(result.proposal.proposal_id)
        self.assertEqual(persisted, result.proposal)
        verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["verification_type"], "planner-generation")
        evidence = json.loads(verifications[0]["evidence_json"])
        self.assertEqual(evidence["planning_input_hash"], self.planning_input.content_hash)
        self.assertEqual(evidence["request_hash"], result.request_hash)
        self.assertEqual(evidence["response_hash"], result.response_hash)
        self.assertEqual(evidence["proposal_hash"], result.proposal.content_hash)
        self.assertFalse(evidence["materialized"])

        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM plan_audits").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM plan_materializations").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM flows").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_real_path_requires_scheduled_adapter_and_records_resource_evidence(self) -> None:
        resources = ResourceScheduler(ResourceCapacity(cpu_slots=4, ram_mib=8192))
        registry = ModelProfileRegistry(
            (
                ModelResourceProfile(
                    "planner-strong",
                    ModelRole.CODER_STRONG,
                    "planner-model",
                    "planner-fixture-runtime",
                    ResourceRequest(cpu_slots=1, ram_mib=1024),
                    model_hash="fixture-hash",
                ),
            )
        )
        scheduler = ModelScheduler(registry, resources)
        loaded_model = _ScheduledFixtureModel(_plan_json(), "planner-model")
        loader = _ScheduledFixtureLoader(loaded_model)
        adapter = ScheduledModelAdapter(
            scheduler,
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "planner-strong"),
            loader,
            recorder=RuntimeModelScheduleRecorder(self.runtime),
        )
        planner = BoundedProductionPlanner(
            self.runtime,
            adapter,
            evidence_store=self.evidence,
        )
        result = planner.propose(
            self.planning_input.planning_input_id,
            model_profile="planner-strong",
        )

        self.assertEqual(loader.loaded, 1)
        self.assertEqual(loader.unloaded, 1)
        self.assertEqual(len(loaded_model.requests), 1)
        self.assertIsNone(loaded_model.requests[0].task_id)
        self.assertEqual(resources.status().active_leases, ())
        verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(
            {value["verification_type"] for value in verifications},
            {"model-resource-selection", "planner-generation"},
        )

    def test_generic_unscheduled_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "ScheduledModelAdapter"):
            BoundedProductionPlanner(
                self.runtime,
                _GenericUnscheduledModel(),
                evidence_store=self.evidence,
            )

    def test_invalid_model_output_fails_run_without_proposal_or_materialization(self) -> None:
        model = DeterministicPlannerAdapter('{"summary":"bad","steps":[]}')
        planner = BoundedProductionPlanner(
            self.runtime,
            model,
            evidence_store=self.evidence,
        )
        with self.assertRaises(Exception):
            planner.propose(self.planning_input.planning_input_id)

        rows = self._run_rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["task_id"])
        self.assertEqual(rows[0]["status"], RunStatus.FAILED.value)
        self.assertIn("PlanProposalParseError", rows[0]["failure_reason"])
        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM plan_proposals").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM plan_materializations").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM flows").fetchone()[0], 0)

    def test_stale_input_fails_before_a_planner_run_or_model_call(self) -> None:
        model = DeterministicPlannerAdapter(_plan_json())
        planner = BoundedProductionPlanner(
            self.runtime,
            model,
            evidence_store=self.evidence,
        )
        self.runtime.transition_goal(self.goal, GoalStatus.ACTIVE, expected_revision=0)
        with self.assertRaisesRegex(Exception, "became stale"):
            planner.propose(self.planning_input.planning_input_id)
        self.assertEqual(model.call_count, 0)
        self.assertEqual(self._run_rows(), [])

    def test_planner_source_has_no_materialization_or_production_mutation_authority(self) -> None:
        source = inspect.getsource(production_planner_module)
        for forbidden in (
            ".materialize(",
            "create_flow(",
            "create_task(",
            "transition_goal(",
            "transition_flow(",
            "transition_task(",
            "adopt",
            "sign_artifact",
            "merge_pull_request",
            "release",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
