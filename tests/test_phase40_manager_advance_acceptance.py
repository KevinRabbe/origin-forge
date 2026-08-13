from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_manager_dispatch_tick as dispatch_tick_module
import origin_forge.production_preparation_tick as preparation_tick_module
from origin_forge.ids import IdKind, new_id
from origin_forge.model import ModelResponse
from origin_forge.orchestration_policy import PolicyAction, PolicyOutcome, PolicyResult
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution_models import DispatchExecution, DispatchExecutionStatus
from origin_forge.production_dispatch_invocation import CompletedDispatchInvocation
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmissionStatus,
    inspect_manager_advance_admission_readonly,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_models import PreparationStage
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
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
_NOW = "2026-08-13T00:00:00Z"


class Phase40ManagerAdvanceAcceptanceTests(unittest.TestCase):
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
            model_hash=_HASH_A,
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

    def _preparation_scenario(self, *, steps: int = 1):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        runtime = OriginForgeRuntime(root)
        runtime.initialize(f"phase40g-preparation-{steps}")
        goal_id = runtime.create_goal("prove one-shot Manager preparation authority")

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
            goal_id,
            capability_store=capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Prepare bounded code Tasks through the one-shot Manager.",
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
        work_order_store = ProductionWorkOrderStore(runtime, capability_store, validators)
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

    def _dispatch_scenario(self, *, tasks: int = 2):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        runtime = OriginForgeRuntime(root)
        runtime.initialize(f"phase40g-dispatch-{tasks}")
        goal_id = runtime.create_goal("prove one-shot Manager dispatch authority")
        flow_id = runtime.create_flow(goal_id)
        catalog = build_builtin_capability_catalog()
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(routing_policy, catalog)
        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_order_store = ProductionWorkOrderStore(runtime, capability_store, validators)
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
        dispatch_store = ProductionDispatchStore(work_order_store, resolver_registry, binder_registry)

        task_ids: list[str] = []
        for index in range(tasks):
            task_id = runtime.create_task(
                flow_id,
                f"dispatch candidate {index}",
                acceptance_criteria=("tests pass",),
                constraints=("bounded",),
                required_capabilities=("code.change",),
            )
            activate_dependency_ready_task(runtime, task_id, 0)
            route = capability_store.resolve_and_publish(
                task_id,
                catalog.catalog_id,
                routing_policy.routing_policy_id,
            )
            work_order = create_current_work_order(
                runtime,
                capability_store,
                dispatch_catalog,
                validators,
                route.route_decision_id,
                payload={"context_mode": "auto", "context_seed_paths": [f"src/task{index}.py"]},
            )
            audit = audit_work_order_frozen(capability_store, dispatch_catalog, validators, work_order)
            work_order_store.publish_work_order(work_order)
            work_order_store.publish_audit(audit)
            bundle = create_input_resolution_bundle(
                work_order_store,
                resolver_registry,
                work_order.work_order_id,
                audit.work_order_audit_id,
            )
            binding = create_dispatch_binding(
                work_order_store,
                resolver_registry,
                binder_registry,
                bundle,
            )
            binding_audit = audit_dispatch_binding_frozen(
                work_order_store,
                resolver_registry,
                binder_registry,
                bundle,
                binding,
            )
            dispatch_store.publish_input_resolution(bundle)
            dispatch_store.publish_binding(binding)
            dispatch_store.publish_audit(binding_audit)
            task_ids.append(task_id)

        return SimpleNamespace(root=root, runtime=runtime, task_ids=tuple(task_ids))

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
        audit = audit_work_order_frozen(
            scenario.capability_store,
            scenario.dispatch_catalog,
            scenario.validators,
            work_order,
        )
        scenario.work_order_store.publish_work_order(work_order)
        scenario.work_order_store.publish_audit(audit)
        resolvers = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()
        dispatch_store = ProductionDispatchStore(scenario.work_order_store, resolvers, binders)
        bundle = create_input_resolution_bundle(
            scenario.work_order_store,
            resolvers,
            work_order.work_order_id,
            audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(scenario.work_order_store, resolvers, binders, bundle)
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

    @staticmethod
    def _completed_for_claim(claim) -> CompletedDispatchInvocation:
        execution = DispatchExecution(
            execution_id=new_id(IdKind.DISPATCH_EXECUTION),
            project_id=claim.project_id,
            claim_id=claim.claim_id,
            claim_revision_at_start=claim.revision,
            task_id=claim.task_id,
            task_revision=claim.task_revision,
            task_content_hash=claim.task_content_hash,
            work_order_id=claim.work_order_id,
            work_order_hash=claim.work_order_hash,
            input_resolution_id=claim.input_resolution_id,
            input_resolution_hash=claim.input_resolution_hash,
            dispatch_binding_id=claim.dispatch_binding_id,
            dispatch_binding_hash=claim.dispatch_binding_hash,
            binding_audit_id=claim.binding_audit_id,
            binding_audit_hash=claim.binding_audit_hash,
            selected_adapter_id=claim.selected_adapter_id,
            selected_adapter_fingerprint=claim.selected_adapter_fingerprint,
            dispatch_contract_id=claim.dispatch_contract_id,
            dispatch_contract_hash=claim.dispatch_contract_hash,
            binder_id=claim.binder_id,
            binder_fingerprint=claim.binder_fingerprint,
            execution_owner_id="originforge.execution.bounded-retry@1",
            execution_owner_fingerprint=_HASH_A,
            runtime_dependency_plan_hash=_HASH_A,
            status=DispatchExecutionStatus.RETURNED,
            revision=1,
            created_at=_NOW,
            updated_at=_NOW,
            terminal_detail_hash=_HASH_A,
        )
        policy = PolicyResult(
            task_id=claim.task_id,
            outcome=PolicyOutcome.BLOCKED,
            action=PolicyAction.STOP,
            reason="Manager must not reinterpret policy outcome",
            executor_attempts=0,
            attempts_started=0,
        )
        return CompletedDispatchInvocation(execution, policy)

    def test_concurrent_managers_prepare_one_oldest_task_once_and_never_fall_through(self) -> None:
        scenario = self._preparation_scenario(steps=2)
        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(admission.prepare_count, 2)
        selected, other = admission.candidates
        self.assertEqual(selected.action_kind, ManagerAdvanceActionKind.PREPARE)
        self.assertEqual(other.action_kind, ManagerAdvanceActionKind.PREPARE)

        real_acquire = preparation_tick_module.acquire_preparation_receipt
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        results = []
        failures: list[BaseException] = []
        model_calls = 0

        def racing_acquire(runtime, policy, candidate):
            self.assertEqual(candidate.task_id, selected.task_id)
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
                value = advance_production_manager_once(runtime)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(preparation_tick_module, "acquire_preparation_receipt", side_effect=racing_acquire),
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
            sum(result.status is ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED for result in results),
            1,
        )
        self.assertEqual(
            sum(result.status is ManagerAdvanceOnceStatus.PREPARATION_NOT_ACQUIRED for result in results),
            1,
        )
        with scenario.runtime.store.session() as conn:
            preps = conn.execute("SELECT task_id, stage FROM task_preparations").fetchall()
        self.assertEqual(len(preps), 1)
        self.assertEqual(preps[0]["task_id"], selected.task_id)
        self.assertEqual(preps[0]["stage"], PreparationStage.PLANNER_RETURNED.value)
        other_task = scenario.runtime.get_task(other.task_id)
        self.assertEqual(other_task["status"], TaskStatus.QUEUED.value)
        self.assertEqual(other_task["revision"], 0)

    def test_concurrent_managers_dispatch_one_oldest_task_once_and_never_fall_through(self) -> None:
        scenario = self._dispatch_scenario(tasks=2)
        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(admission.dispatch_count, 2)
        selected, other = admission.candidates
        self.assertEqual(selected.action_kind, ManagerAdvanceActionKind.DISPATCH)
        self.assertEqual(other.action_kind, ManagerAdvanceActionKind.DISPATCH)

        real_acquire = acquire_dispatch_claim
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        results = []
        failures: list[BaseException] = []
        claims_by_id = {}

        def racing_acquire(runtime, binding_id, audit_id, revision):
            barrier.wait(timeout=15)
            claim = real_acquire(runtime, binding_id, audit_id, revision)
            with lock:
                claims_by_id[claim.claim_id] = claim
            return claim

        def fake_dispatch(runtime, claim_id, expected_revision):
            self.assertEqual(expected_revision, 0)
            with lock:
                claim = claims_by_id[claim_id]
            self.assertEqual(claim.task_id, selected.task_id)
            return self._completed_for_claim(claim)

        def worker() -> None:
            runtime = OriginForgeRuntime(scenario.root)
            try:
                value = advance_production_manager_once(runtime)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.object(dispatch_tick_module, "acquire_dispatch_claim", side_effect=racing_acquire),
            patch.object(dispatch_tick_module, "dispatch_claim_once", side_effect=fake_dispatch) as dispatch,
        ):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=25)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(
            sum(result.status is ManagerAdvanceOnceStatus.DISPATCH_RETURNED for result in results),
            1,
        )
        self.assertEqual(
            sum(result.status is ManagerAdvanceOnceStatus.DISPATCH_CLAIM_NOT_ACQUIRED for result in results),
            1,
        )
        with scenario.runtime.store.session() as conn:
            selected_claims = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (selected.task_id,),
            ).fetchone()[0]
            other_claims = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (other.task_id,),
            ).fetchone()[0]
        self.assertEqual(selected_claims, 1)
        self.assertEqual(other_claims, 0)

    def test_planner_uncertainty_requires_recovery_and_manager_never_replays_model(self) -> None:
        scenario = self._preparation_scenario()
        model_calls = 0

        def uncertain_generate(*args, **kwargs):
            nonlocal model_calls
            model_calls += 1
            raise RuntimeError("simulated uncertain planner transport")

        with patch.object(ScheduledModelAdapter, "generate", side_effect=uncertain_generate):
            first = advance_production_manager_once(scenario.runtime)
        self.assertEqual(first.status, ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RECOVERY_REQUIRED)
        self.assertEqual(model_calls, 1)
        self.assertIsNotNone(first.preparation_id)

        with patch.object(
            ScheduledModelAdapter,
            "generate",
            side_effect=AssertionError("Manager replayed uncertain planner"),
        ):
            second = advance_production_manager_once(scenario.runtime)
        self.assertEqual(second.status, ManagerAdvanceOnceStatus.RECOVERY_REQUIRED)
        self.assertEqual(second.action_kind, ManagerAdvanceActionKind.FINALIZE_WORK_ORDER)
        self.assertEqual(second.preparation_id, first.preparation_id)
        self.assertEqual(model_calls, 1)

    def test_four_external_calls_use_fresh_post_activation_authority_and_dispatch_once(self) -> None:
        scenario = self._preparation_scenario()
        task_id = scenario.task_ids[0]
        old_route, old_work_order, old_bundle, old_binding, old_audit = self._publish_pre_activation_chain(
            scenario,
            task_id,
        )
        self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.QUEUED.value)

        with patch.object(ScheduledModelAdapter, "generate", return_value=self._response()) as generate:
            first = advance_production_manager_once(scenario.runtime)
        self.assertEqual(first.status, ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED)
        self.assertEqual(first.action_kind, ManagerAdvanceActionKind.PREPARE)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.READY.value)

        second = advance_production_manager_once(scenario.runtime)
        self.assertEqual(second.status, ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED)
        self.assertEqual(second.action_kind, ManagerAdvanceActionKind.FINALIZE_WORK_ORDER)
        self.assertEqual(second.preparation_id, first.preparation_id)

        third = advance_production_manager_once(scenario.runtime)
        self.assertEqual(third.status, ManagerAdvanceOnceStatus.PHASE34_READY)
        self.assertEqual(third.action_kind, ManagerAdvanceActionKind.FINALIZE_PHASE34)
        self.assertEqual(third.preparation_id, first.preparation_id)

        admission = inspect_manager_advance_admission_readonly(scenario.runtime)
        self.assertEqual(admission.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        fresh = admission.candidates[0]
        self.assertEqual(fresh.action_kind, ManagerAdvanceActionKind.DISPATCH)
        self.assertEqual(fresh.task_id, task_id)
        assert fresh.dispatch_candidate is not None
        self.assertNotEqual(fresh.dispatch_candidate.dispatch_binding_id, old_binding.dispatch_binding_id)
        self.assertNotEqual(fresh.dispatch_candidate.binding_audit_id, old_audit.binding_audit_id)
        self.assertNotEqual(fresh.dispatch_candidate.input_resolution_id, old_bundle.input_resolution_id)

        claims_by_id = {}

        def capture_claim(runtime, binding_id, audit_id, revision):
            claim = acquire_dispatch_claim(runtime, binding_id, audit_id, revision)
            claims_by_id[claim.claim_id] = claim
            return claim

        def fake_dispatch(runtime, claim_id, expected_revision):
            self.assertEqual(expected_revision, 0)
            return self._completed_for_claim(claims_by_id[claim_id])

        with (
            patch.object(dispatch_tick_module, "acquire_dispatch_claim", side_effect=capture_claim),
            patch.object(dispatch_tick_module, "dispatch_claim_once", side_effect=fake_dispatch) as dispatch,
            patch.object(
                ScheduledModelAdapter,
                "generate",
                side_effect=AssertionError("later Manager call replayed planner"),
            ),
        ):
            fourth = advance_production_manager_once(scenario.runtime)

        self.assertEqual(fourth.status, ManagerAdvanceOnceStatus.DISPATCH_RETURNED)
        self.assertEqual(fourth.action_kind, ManagerAdvanceActionKind.DISPATCH)
        self.assertEqual(fourth.task_id, task_id)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(generate.call_count, 1)
        self.assertIsNotNone(old_route.route_decision_id)
        self.assertIsNotNone(old_work_order.work_order_id)


if __name__ == "__main__":
    unittest.main()
