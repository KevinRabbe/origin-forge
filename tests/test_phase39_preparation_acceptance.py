from __future__ import annotations

import inspect
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_preparation_tick as tick_module
from origin_forge.model import ModelResponse
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_binding_models import DispatchBindingCurrentnessStatus
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_read import inspect_dispatch_binding_currentness_readonly
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmissionStatus,
    inspect_manager_dispatch_admission_readonly,
)
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage
from origin_forge.production_preparation_phase34_finalize import (
    PreparationPhase34FinalizeStatus,
    finalize_preparation_phase34,
)
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_status import (
    PreparationInspectionState,
    inspect_preparation_receipt_status_readonly,
)
from origin_forge.production_preparation_tick import (
    PreparationTickStatus,
    prepare_materialization_tick,
)
from origin_forge.production_preparation_work_order_finalize import (
    PreparationWorkOrderFinalizeStatus,
    finalize_preparation_work_order_audit,
)
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class Phase39PreparationAcceptanceTests(unittest.TestCase):
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

    @staticmethod
    def _write_model_config(runtime: OriginForgeRuntime) -> None:
        runtime.state_dir.joinpath("config.toml").write_text(
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

    def _scenario(self, *, steps: int = 1):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        runtime = OriginForgeRuntime(root)
        runtime.initialize(f"phase39g-acceptance-{steps}")
        goal = runtime.create_goal("prove governed preparation cross-phase authority")

        catalog = build_builtin_capability_catalog()
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(routing_policy, catalog)
        planning_input = freeze_governed_planning_input(
            runtime,
            goal,
            capability_store=capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Prepare bounded code Tasks without dispatching them.",
            steps=tuple(
                PlanStep(
                    step_key=f"code{index}",
                    objective=f"Implement bounded change {index}.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                )
                for index in range(steps)
            ),
        )
        plan_audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(plan_audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=plan_audit.audit_id,
        )

        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_order_store = ProductionWorkOrderStore(
            runtime,
            capability_store,
            validators,
        )
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        preparation_policy = create_preparation_policy_binding(
            runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=catalog.catalog_id,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(runtime, preparation_policy)
        self._write_model_config(runtime)
        return SimpleNamespace(
            root=root,
            runtime=runtime,
            catalog=catalog,
            routing_policy=routing_policy,
            capability_store=capability_store,
            validators=validators,
            dispatch_catalog=dispatch_catalog,
            work_order_store=work_order_store,
            preparation_policy=preparation_policy,
            materialization=materialization,
            task_ids=tuple(binding.task_id for binding in materialization.task_bindings),
        )

    @staticmethod
    def _assert_no_dispatch(runtime: OriginForgeRuntime) -> None:
        with runtime.store.session() as conn:
            assert conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0] == 0

    def _publish_pre_activation_chain(self, scenario, task_id: str):
        route = scenario.capability_store.resolve_and_publish(
            task_id,
            scenario.catalog.catalog_id,
            scenario.routing_policy.routing_policy_id,
        )
        work_order = create_current_work_order(
            scenario.runtime,
            scenario.capability_store,
            scenario.dispatch_catalog,
            scenario.validators,
            route.route_decision_id,
            payload={"context_mode": "auto"},
        )
        work_order_audit = audit_work_order_frozen(
            scenario.capability_store,
            scenario.dispatch_catalog,
            scenario.validators,
            work_order,
        )
        scenario.work_order_store.publish_work_order(work_order)
        scenario.work_order_store.publish_audit(work_order_audit)
        resolvers = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()
        dispatch_store = ProductionDispatchStore(
            scenario.work_order_store,
            resolvers,
            binders,
        )
        bundle = create_input_resolution_bundle(
            scenario.work_order_store,
            resolvers,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            scenario.work_order_store,
            resolvers,
            binders,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            scenario.work_order_store,
            resolvers,
            binders,
            bundle,
            binding,
        )
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        return route, work_order, bundle, binding, binding_audit

    def test_two_concurrent_ticks_have_one_real_preparation_owner_and_one_model_call(self) -> None:
        scenario = self._scenario()
        real_acquire = tick_module.acquire_preparation_receipt
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        results = []
        failures: list[BaseException] = []
        model_calls = 0

        def racing_acquire(runtime, policy, candidate):
            barrier.wait(timeout=15)
            return real_acquire(runtime, policy, candidate)

        def fake_generate(*args, **kwargs):
            nonlocal model_calls
            with lock:
                model_calls += 1
            return self._response()

        def worker() -> None:
            runtime = OriginForgeRuntime(scenario.root)
            try:
                value = prepare_materialization_tick(
                    runtime,
                    scenario.preparation_policy.preparation_policy_id,
                )
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(tick_module, "acquire_preparation_receipt", side_effect=racing_acquire),
            patch.object(ScheduledModelAdapter, "generate", side_effect=fake_generate),
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
            sum(result.status is PreparationTickStatus.PLANNER_RETURNED for result in results),
            1,
        )
        self.assertEqual(
            sum(result.status is PreparationTickStatus.PREPARATION_NOT_ACQUIRED for result in results),
            1,
        )
        with scenario.runtime.store.session() as conn:
            rows = conn.execute("SELECT * FROM task_preparations").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], PreparationStage.PLANNER_RETURNED.value)
        self.assertEqual(rows[0]["status"], "ACTIVE")
        self._assert_no_dispatch(scenario.runtime)

    def test_selected_candidate_race_never_falls_through_to_second_task(self) -> None:
        scenario = self._scenario(steps=2)
        admission = inspect_materialization_preparation_eligibility_readonly(
            scenario.runtime,
            scenario.preparation_policy,
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 2)
        selected, other = admission.candidates
        real_acquire = tick_module.acquire_preparation_receipt
        acquire_calls = []

        def stale_before_acquire(runtime, policy, candidate):
            acquire_calls.append(candidate.task_id)
            self.assertEqual(candidate.task_id, selected.task_id)
            current = runtime.get_task(candidate.task_id)
            runtime.transition_task(
                candidate.task_id,
                TaskStatus.CANCELLED,
                expected_revision=int(current["revision"]),
            )
            return real_acquire(runtime, policy, candidate)

        with (
            patch.object(tick_module, "acquire_preparation_receipt", side_effect=stale_before_acquire),
            patch.object(
                ScheduledModelAdapter,
                "generate",
                side_effect=AssertionError("race loser fell through to model boundary"),
            ),
        ):
            result = prepare_materialization_tick(
                scenario.runtime,
                scenario.preparation_policy.preparation_policy_id,
            )

        self.assertEqual(result.status, PreparationTickStatus.PREPARATION_NOT_ACQUIRED)
        self.assertEqual(acquire_calls, [selected.task_id])
        self.assertEqual(
            scenario.runtime.get_task(selected.task_id)["status"],
            TaskStatus.CANCELLED.value,
        )
        other_task = scenario.runtime.get_task(other.task_id)
        self.assertEqual(other_task["status"], TaskStatus.QUEUED.value)
        self.assertEqual(other_task["revision"], 0)
        with scenario.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM task_preparations").fetchone()[0], 0)
        self._assert_no_dispatch(scenario.runtime)

    def test_activation_invalidates_pre_activation_authority_and_only_fresh_chain_reaches_phase38(self) -> None:
        scenario = self._scenario()
        task_id = scenario.task_ids[0]
        old_route, old_work_order, old_bundle, old_binding, old_audit = (
            self._publish_pre_activation_chain(scenario, task_id)
        )
        self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.QUEUED.value)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            return_value=self._response(),
        ):
            tick = prepare_materialization_tick(
                scenario.runtime,
                scenario.preparation_policy.preparation_policy_id,
            )
        self.assertEqual(tick.status, PreparationTickStatus.PLANNER_RETURNED)
        assert tick.receipt is not None
        self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.READY.value)
        self.assertNotEqual(tick.receipt.route_decision_id, old_route.route_decision_id)
        self.assertNotEqual(tick.receipt.work_order_id, old_work_order.work_order_id)

        old_currentness = inspect_dispatch_binding_currentness_readonly(
            scenario.runtime,
            old_bundle.input_resolution_id,
            old_binding.dispatch_binding_id,
            old_audit.binding_audit_id,
            build_dispatch_input_resolver_registry(),
            build_builtin_dispatch_binder_registry(),
        )
        self.assertIsNot(old_currentness.status, DispatchBindingCurrentnessStatus.CURRENT_READY)

        work_order_final = finalize_preparation_work_order_audit(
            scenario.runtime,
            tick.receipt.preparation_id,
        )
        self.assertEqual(
            work_order_final.status,
            PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
        )
        ready = finalize_preparation_phase34(
            scenario.runtime,
            tick.receipt.preparation_id,
        )
        self.assertEqual(ready.status, PreparationPhase34FinalizeStatus.BOUND_READY)
        self.assertEqual(ready.receipt.stage, PreparationStage.BOUND)
        self.assertEqual(ready.receipt.status.value, "READY")
        self.assertNotEqual(ready.receipt.input_resolution_id, old_bundle.input_resolution_id)
        self.assertNotEqual(ready.receipt.dispatch_binding_id, old_binding.dispatch_binding_id)
        self.assertNotEqual(ready.receipt.binding_audit_id, old_audit.binding_audit_id)

        manager = inspect_manager_dispatch_admission_readonly(scenario.runtime)
        self.assertEqual(manager.status, ManagerDispatchAdmissionStatus.COMPLETE)
        task_candidates = [candidate for candidate in manager.candidates if candidate.task_id == task_id]
        self.assertEqual(len(task_candidates), 1)
        self.assertEqual(task_candidates[0].binding_audit_id, ready.receipt.binding_audit_id)
        self._assert_no_dispatch(scenario.runtime)

    def test_planner_started_uncertainty_is_reported_and_never_auto_replayed(self) -> None:
        scenario = self._scenario()
        calls = 0

        def uncertain_generate(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise RuntimeError("simulated uncertain planner transport")

        with patch.object(ScheduledModelAdapter, "generate", side_effect=uncertain_generate):
            first = prepare_materialization_tick(
                scenario.runtime,
                scenario.preparation_policy.preparation_policy_id,
            )
        self.assertEqual(first.status, PreparationTickStatus.PLANNER_RECOVERY_REQUIRED)
        self.assertEqual(calls, 1)
        assert first.receipt is not None
        self.assertEqual(first.receipt.stage, PreparationStage.PLANNER_STARTED)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("second tick replayed uncertain planner"),
        ):
            second = prepare_materialization_tick(
                scenario.runtime,
                scenario.preparation_policy.preparation_policy_id,
            )
        self.assertEqual(second.status, PreparationTickStatus.NO_ELIGIBLE_TASK)
        status = inspect_preparation_receipt_status_readonly(
            scenario.runtime,
            first.receipt.preparation_id,
        )
        self.assertEqual(status.state, PreparationInspectionState.PLANNER_RECOVERY_REQUIRED)
        self.assertTrue(status.current)
        self._assert_no_dispatch(scenario.runtime)

    def test_tick_caller_surface_contains_no_task_model_runtime_or_binding_authority(self) -> None:
        signature = inspect.signature(prepare_materialization_tick)
        self.assertEqual(tuple(signature.parameters), ("runtime", "preparation_policy_id"))
        self.assertTrue(
            all(
                parameter.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
                for parameter in signature.parameters.values()
            )
        )


if __name__ == "__main__":
    unittest.main()
