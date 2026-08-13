from __future__ import annotations

import inspect
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_planner_resume as resume_module
from origin_forge.model import ModelResponse
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_activation import activate_and_checkpoint_preparation
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_planner_resume import (
    PreparationPlannerResumeStatus,
    resume_routed_preparation_planner_once,
)
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_receipts import acquire_preparation_receipt
from origin_forge.production_preparation_route_recovery import recover_and_checkpoint_preparation_route
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationPlannerResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase41d2-planner-resume")
        goal = self.runtime.create_goal("resume one routed preparation")
        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(self.catalog)
        capability_store.publish_policy(self.routing_policy, self.catalog)
        planning_input = freeze_governed_planning_input(
            self.runtime,
            goal,
            capability_store=capability_store,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Materialize one Task for planner resumption.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement one bounded code change.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(self.runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        ).publish_dispatch_catalog(dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=self.catalog.catalog_id,
            capability_routing_policy_id=self.routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(self.runtime, self.policy)
        self._write_model_config()

        admission = inspect_materialization_preparation_eligibility_readonly(
            self.runtime, self.policy
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        claimed = acquire_preparation_receipt(
            self.runtime, self.policy, admission.candidates[0]
        )
        activated = activate_and_checkpoint_preparation(
            self.runtime, claimed.preparation_id, claimed.revision
        )
        self.routed = recover_and_checkpoint_preparation_route(
            self.runtime, activated.preparation_id, activated.revision
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_model_config(self) -> None:
        self.runtime.state_dir.joinpath("config.toml").write_text(
            '''version = 6
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
''',
            encoding="utf-8",
        )

    @staticmethod
    def _response() -> ModelResponse:
        return ModelResponse(
            text=json.dumps(
                {
                    "contract_id": "code.bounded-retry@1",
                    "input_refs": [],
                    "payload": {"context_mode": "auto"},
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            model_id="test-model",
            model_hash="a" * 64,
            input_tokens=10,
            output_tokens=5,
        )

    def test_routed_resume_commits_marker_then_calls_planner_once(self) -> None:
        calls = 0

        def generate(*args, **kwargs):
            nonlocal calls
            calls += 1
            return self._response()

        with patch.object(ScheduledModelAdapter, "generate", side_effect=generate):
            result = resume_routed_preparation_planner_once(
                self.runtime, self.routed.preparation_id, self.routed.revision
            )
        self.assertEqual(result.status, PreparationPlannerResumeStatus.PLANNER_RETURNED)
        self.assertEqual(calls, 1)
        assert result.receipt is not None
        self.assertEqual(result.receipt.stage, PreparationStage.PLANNER_RETURNED)
        self.assertEqual(result.receipt.status, PreparationStatus.ACTIVE)
        self.assertIsNotNone(result.receipt.planner_dependency_plan_hash)
        self.assertIsNotNone(result.receipt.planner_run_id)

    def test_ordinary_failure_after_marker_never_replays(self) -> None:
        calls = 0

        def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise RuntimeError("uncertain planner transport")

        with patch.object(ScheduledModelAdapter, "generate", side_effect=fail):
            first = resume_routed_preparation_planner_once(
                self.runtime, self.routed.preparation_id, self.routed.revision
            )
        self.assertEqual(first.status, PreparationPlannerResumeStatus.PLANNER_RECOVERY_REQUIRED)
        self.assertEqual(calls, 1)
        assert first.receipt is not None
        self.assertEqual(first.receipt.stage, PreparationStage.PLANNER_STARTED)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("planner replayed after durable marker"),
        ):
            second = resume_routed_preparation_planner_once(
                self.runtime, self.routed.preparation_id, self.routed.revision
            )
        self.assertEqual(second.status, PreparationPlannerResumeStatus.PLANNER_RECOVERY_REQUIRED)
        self.assertEqual(calls, 1)

    def test_concurrent_routed_resume_has_at_most_one_model_call(self) -> None:
        real_checkpoint = resume_module.checkpoint_preparation_planner_started
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        model_calls = 0
        results = []
        failures: list[BaseException] = []

        def racing_checkpoint(*args, **kwargs):
            barrier.wait(timeout=15)
            return real_checkpoint(*args, **kwargs)

        def generate(*args, **kwargs):
            nonlocal model_calls
            with lock:
                model_calls += 1
            return self._response()

        def worker() -> None:
            runtime = OriginForgeRuntime(self.root)
            try:
                value = resume_routed_preparation_planner_once(
                    runtime, self.routed.preparation_id, self.routed.revision
                )
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(resume_module, "checkpoint_preparation_planner_started", side_effect=racing_checkpoint),
            patch.object(ScheduledModelAdapter, "generate", side_effect=generate),
        ):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=25)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(model_calls, 1)
        self.assertEqual(
            sum(value.status is PreparationPlannerResumeStatus.PLANNER_RETURNED for value in results),
            1,
        )
        self.assertTrue(
            all(
                value.status
                in {
                    PreparationPlannerResumeStatus.PLANNER_RETURNED,
                    PreparationPlannerResumeStatus.PLANNER_RECOVERY_REQUIRED,
                    PreparationPlannerResumeStatus.INVALID_AUTHORITY,
                }
                for value in results
            )
        )

    def test_source_orders_durable_marker_before_only_planner_call(self) -> None:
        source = inspect.getsource(resume_module)
        self.assertEqual(source.count("planner.propose("), 1)
        self.assertLess(
            source.index("checkpoint_preparation_planner_started("),
            source.index("planner.propose("),
        )
        for forbidden in (
            "dispatch_claim_once",
            "acquire_dispatch_claim",
            "dispatch_manager_tick",
            "advance_production_manager_once",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
