from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from unittest.mock import patch

import origin_forge.production_work_order_planner as planner_module
from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.model_scheduler import (
    ModelProfileRegistry,
    ModelResourceProfile,
    ModelRole,
    ModelScheduler,
    ModelSelectionPolicy,
)
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_planner import (
    BoundedProductionWorkOrderPlanner,
    DeterministicWorkOrderPlannerAdapter,
    ProductionWorkOrderPlannerError,
    WorkOrderProposal,
    _bind_accepted_design_animation,
)
from origin_forge.production_work_order_models import (
    DispatchContract,
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
)
from origin_forge.production_work_order_pixelorama import PIXELORAMA_SOURCE_ADAPTER_ID
from origin_forge.pixelorama_models import FrameSpec, RasterLayerSpec, SpriteProjectSpec
from origin_forge.resource_scheduler import ResourceCapacity, ResourceRequest, ResourceScheduler
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import (
    RuntimeModelScheduleRecorder,
    ScheduledModelAdapter,
)
from origin_forge.state import RunStatus, TaskStatus


def _proposal_json() -> str:
    return json.dumps(
        {
            "contract_id": "code.bounded-retry@1",
            "input_refs": [],
            "payload": {
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )


class _GenericUnscheduledModel:
    @property
    def model_id(self) -> str:
        return "unscheduled-work-order-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(_proposal_json(), self.model_id)


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
            model_hash="fixture-work-order-model-hash",
            input_tokens=22,
            output_tokens=9,
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


class ProductionWorkOrderPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("work-order-planner")
        goal = self.runtime.create_goal("plan one bounded coding work order")
        self.flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(
            self.flow,
            "change code safely",
            acceptance_criteria=("tests pass",),
            constraints=("use governed context",),
            required_capabilities=("code.change",),
            priority=40,
        )
        self.phase32 = build_builtin_capability_catalog()
        self.policy = CapabilityRoutingPolicy.create(
            self.phase32,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.phase32)
        self.capability_store.publish_policy(self.policy, self.phase32)
        self.route = self.capability_store.resolve_and_publish(
            self.task,
            self.phase32.catalog_id,
            self.policy.routing_policy_id,
        )
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.phase32)
        self.registry = build_builtin_dispatch_validator_registry()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _all_runs(self):
        with self.runtime.store.session() as conn:
            return conn.execute("SELECT * FROM runs ORDER BY started_at, rowid").fetchall()

    def _planner(self, model):
        return BoundedProductionWorkOrderPlanner(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            model,
        )

    def test_source_planner_binds_accepted_design_before_work_order_freeze(self) -> None:
        sprite_spec = SpriteProjectSpec(
            1,
            1,
            (RasterLayerSpec("base", "Base"),),
            (FrameSpec("frame-0"), FrameSpec("frame-1")),
            output_basename="runner",
        )
        payload = {
            "operation": "CREATE_SPRITE_PROJECT",
            "sprite_spec": sprite_spec.to_dict(),
            "export_specs": [],
            "budget": {
                "max_input_bytes": 1024,
                "max_output_bytes": 2048,
                "max_outputs": 2,
                "timeout_seconds": 5,
            },
        }
        reference = WorkOrderInputRef(
            ref_type=WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE,
            ref_id="DESIGNACC-planner",
            content_hash="a" * 64,
            role="accepted_design",
            revision=None,
        )
        proposal = WorkOrderProposal(
            contract_id="pixelorama.source-create@1",
            input_refs=(reference,),
            payload_json=canonical_bytes(payload).decode("utf-8"),
        )
        contract = DispatchContract(
            contract_id="pixelorama.source-create@1",
            contract_version="1",
            adapter_id=PIXELORAMA_SOURCE_ADAPTER_ID,
            adapter_fingerprint="b" * 64,
            validator_id="validator.pixelorama.source-create@1",
            validator_fingerprint="c" * 64,
            payload_schema_id="schema.pixelorama.source-create@1",
            payload_schema_hash="d" * 64,
            allowed_input_ref_types=(WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE,),
            max_payload_bytes=1024 * 1024,
            max_input_refs=1,
        )
        bound_payload = {**payload, "sentinel": "not-valid-for-the-model"}
        with patch(
            "origin_forge.production_work_order_planner.build_pixelorama_source_work_order_payload_from_accepted_design",
            return_value=bound_payload,
        ) as bind:
            result = _bind_accepted_design_animation(self.runtime, contract, proposal)

        bind.assert_called_once()
        self.assertEqual(bind.call_args.args[1], "DESIGNACC-planner")
        self.assertEqual(result.payload["sentinel"], "not-valid-for-the-model")
        self.assertNotEqual(result.content_hash, proposal.content_hash)

    def test_deterministic_worker_makes_one_taskless_call_and_constructs_only_work_order(self) -> None:
        before = self.runtime.get_task(self.task)
        model = DeterministicWorkOrderPlannerAdapter(
            _proposal_json(),
            input_tokens=18,
            output_tokens=7,
        )
        result = self._planner(model).propose(self.route.route_decision_id)

        self.assertEqual(model.call_count, 1)
        self.assertIsNotNone(model.last_request)
        self.assertIsNone(model.last_request.task_id)
        self.assertEqual(model.last_request.run_id, result.run_id)
        self.assertEqual(model.last_request.context["task"]["id"], self.task)
        self.assertEqual(
            model.last_request.context["route"]["route_decision_id"],
            self.route.route_decision_id,
        )
        self.assertEqual(
            model.last_request.context["dispatch_contract"]["contract_id"],
            "code.bounded-retry@1",
        )
        self.assertEqual(
            model.last_request.context["payload_schema"]["schema_id"],
            "schema.code.bounded-retry@1",
        )
        self.assertEqual(
            model.last_request.response_schema["properties"]["contract_id"]["enum"],
            ["code.bounded-retry@1"],
        )

        work_order = result.work_order
        self.assertEqual(work_order.task_id, self.task)
        self.assertEqual(work_order.route_decision_id, self.route.route_decision_id)
        self.assertEqual(work_order.selected_adapter_id, "originforge.code.bounded-retry")
        self.assertEqual(work_order.dispatch_contract_id, "code.bounded-retry@1")
        self.assertEqual(
            work_order.payload,
            {
                "context_mode": "auto",
                "selected_paths": [],
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
                "semantic_context": False,
            },
        )

        run = self.runtime.get_run(result.run_id)
        self.assertIsNone(run["task_id"])
        self.assertEqual(run["role"], "WORK_ORDER_PLANNER")
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(run["input_token_count"], 18)
        self.assertEqual(run["output_token_count"], 7)
        verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(verifications), 1)
        self.assertEqual(
            verifications[0]["verification_type"],
            "work-order-planner-generation",
        )
        evidence = json.loads(verifications[0]["evidence_json"])
        self.assertEqual(evidence["request_hash"], result.request_hash)
        self.assertEqual(evidence["response_hash"], result.response_hash)
        self.assertEqual(evidence["proposal_hash"], result.proposal_hash)
        self.assertEqual(evidence["work_order_id"], work_order.work_order_id)
        self.assertEqual(evidence["work_order_hash"], work_order.content_hash)
        self.assertEqual(evidence["work_order"], work_order.to_dict())
        self.assertFalse(evidence["audited"])
        self.assertFalse(evidence["dispatched"])

        after = self.runtime.get_task(self.task)
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["attempt_count"], after["attempt_count"])
        self.assertIsNone(after["assigned_run_id"])
        self.assertEqual(self.runtime.list_runs(self.task), [])

    def test_real_path_requires_scheduled_adapter_and_records_resource_evidence(self) -> None:
        resources = ResourceScheduler(ResourceCapacity(cpu_slots=4, ram_mib=8192))
        profiles = ModelProfileRegistry(
            (
                ModelResourceProfile(
                    "work-order-strong",
                    ModelRole.CODER_STRONG,
                    "work-order-model",
                    "work-order-fixture-runtime",
                    ResourceRequest(cpu_slots=1, ram_mib=1024),
                    model_hash="fixture-work-order-model-hash",
                ),
            )
        )
        scheduler = ModelScheduler(profiles, resources)
        loaded_model = _ScheduledFixtureModel(_proposal_json(), "work-order-model")
        loader = _ScheduledFixtureLoader(loaded_model)
        adapter = ScheduledModelAdapter(
            scheduler,
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "work-order-strong"),
            loader,
            recorder=RuntimeModelScheduleRecorder(self.runtime),
        )
        result = self._planner(adapter).propose(
            self.route.route_decision_id,
            model_profile="work-order-strong",
        )

        self.assertEqual(loader.loaded, 1)
        self.assertEqual(loader.unloaded, 1)
        self.assertEqual(len(loaded_model.requests), 1)
        self.assertIsNone(loaded_model.requests[0].task_id)
        self.assertEqual(resources.status().active_leases, ())
        verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(
            {value["verification_type"] for value in verifications},
            {"model-resource-selection", "work-order-planner-generation"},
        )

    def test_generic_unscheduled_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "ScheduledModelAdapter"):
            self._planner(_GenericUnscheduledModel())

    def test_stale_route_fails_before_run_or_model_call(self) -> None:
        model = DeterministicWorkOrderPlannerAdapter(_proposal_json())
        self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        with self.assertRaisesRegex(ProductionWorkOrderPlannerError, "stale before"):
            self._planner(model).propose(self.route.route_decision_id)
        self.assertEqual(model.call_count, 0)
        self.assertEqual(self._all_runs(), [])

    def test_authority_fields_duplicate_keys_wrong_contract_and_floats_fail_closed(self) -> None:
        bad_outputs = (
            json.dumps(
                {
                    "contract_id": "code.bounded-retry@1",
                    "input_refs": [],
                    "payload": {"context_mode": "auto"},
                    "task_id": self.task,
                }
            ),
            '{"contract_id":"code.bounded-retry@1","contract_id":"code.bounded-retry@1","input_refs":[],"payload":{"context_mode":"auto"}}',
            json.dumps(
                {
                    "contract_id": "other.contract@1",
                    "input_refs": [],
                    "payload": {"context_mode": "auto"},
                }
            ),
            json.dumps(
                {
                    "contract_id": "code.bounded-retry@1",
                    "input_refs": [],
                    "payload": {
                        "context_mode": "auto",
                        "semantic_context": 0.5,
                    },
                }
            ),
        )
        for index, response_text in enumerate(bad_outputs):
            with self.subTest(index=index):
                model = DeterministicWorkOrderPlannerAdapter(response_text)
                with self.assertRaises(ProductionWorkOrderPlannerError):
                    self._planner(model).propose(self.route.route_decision_id)
                self.assertEqual(model.call_count, 1)
        rows = self._all_runs()
        self.assertEqual(len(rows), len(bad_outputs))
        self.assertTrue(all(row["status"] == RunStatus.FAILED.value for row in rows))
        self.assertEqual(self.runtime.list_runs(self.task), [])

    def test_worker_source_has_no_audit_dispatch_task_transition_or_backend_call_surface(self) -> None:
        source = inspect.getsource(planner_module)
        for forbidden in (
            "subprocess",
            "os.system",
            "importlib",
            "create_sandbox_backend",
            "transition_task(",
            "audit_work_order(",
            "dispatch_work_order(",
            "adopt(",
            "sign_artifact(",
            "merge_pull_request(",
            "release(",
        ):
            self.assertNotIn(forbidden, source)
        tree = ast.parse(source)
        forbidden_method_calls = {"drive", "execute", "dispatch", "audit", "materialize"}
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(forbidden_method_calls.isdisjoint(called_attributes))


if __name__ == "__main__":
    unittest.main()
