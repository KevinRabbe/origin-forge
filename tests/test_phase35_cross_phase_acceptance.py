from __future__ import annotations

import ast
import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import origin_forge.production_dispatch_claim_lifecycle as lifecycle_module
import origin_forge.production_dispatch_claim_read as read_module
import origin_forge.production_dispatch_claims as claims_module
import origin_forge.production_task_activation as activation_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_binding_models import (
    DispatchBindingCurrentnessStatus,
)
from origin_forge.production_dispatch_claim_lifecycle import (
    interrupt_dispatch_claim,
    release_dispatch_claim,
)
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    inspect_dispatch_claim_currentness_readonly,
)
from origin_forge.production_dispatch_claims import (
    DispatchClaimError,
    acquire_dispatch_claim,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_read import (
    inspect_dispatch_binding_currentness_readonly,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class Phase35CrossPhaseAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase35-cross-phase")
        self.goal_id = self.runtime.create_goal("govern one dispatch owner")
        self.flow_id = self.runtime.create_flow(self.goal_id)
        self.task_id = self.runtime.create_task(
            self.flow_id,
            "change code through bounded retry",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )

        self.catalog = build_builtin_capability_catalog()
        self.policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.policy, self.catalog)
        self.validator_registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validator_registry,
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)
        self.resolver_registry = build_dispatch_input_resolver_registry()
        self.binder_registry = build_builtin_dispatch_binder_registry()
        self.dispatch_store = ProductionDispatchStore(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _build_chain(self) -> SimpleNamespace:
        route = self.capability_store.resolve_and_publish(
            self.task_id,
            self.catalog.catalog_id,
            self.policy.routing_policy_id,
        )
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
            },
        )
        work_order_audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            work_order,
        )
        self.work_order_store.publish_work_order(work_order)
        self.work_order_store.publish_audit(work_order_audit)
        bundle = create_input_resolution_bundle(
            self.work_order_store,
            self.resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            binding,
        )
        self.dispatch_store.publish_input_resolution(bundle)
        self.dispatch_store.publish_binding(binding)
        self.dispatch_store.publish_audit(binding_audit)
        return SimpleNamespace(
            route=route,
            work_order=work_order,
            work_order_audit=work_order_audit,
            bundle=bundle,
            binding=binding,
            binding_audit=binding_audit,
        )

    def _binding_currentness(self, chain: SimpleNamespace):
        return inspect_dispatch_binding_currentness_readonly(
            self.runtime,
            chain.bundle.input_resolution_id,
            chain.binding.dispatch_binding_id,
            chain.binding_audit.binding_audit_id,
            self.resolver_registry,
            self.binder_registry,
        )

    def _workspace_count(self) -> int:
        with self.runtime.store.session() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                    (self.task_id,),
                ).fetchone()[0]
            )

    def test_exact_authority_ordering_from_activation_through_restart_recovery(self) -> None:
        pre_activation = self._build_chain()
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.QUEUED.value)
        self.assertEqual(
            self._binding_currentness(pre_activation).status,
            DispatchBindingCurrentnessStatus.CURRENT_READY,
        )

        activation = activate_dependency_ready_task(self.runtime, self.task_id, 0)
        self.assertEqual(activation.previous_revision, 0)
        self.assertEqual(activation.new_revision, 1)
        self.assertNotEqual(
            activation.previous_task_content_hash,
            activation.new_task_content_hash,
        )
        activated_task = self.runtime.get_task(self.task_id)
        self.assertEqual(activated_task["status"], TaskStatus.READY.value)
        self.assertEqual(activated_task["revision"], 1)

        stale = self._binding_currentness(pre_activation)
        self.assertIsNot(stale.status, DispatchBindingCurrentnessStatus.CURRENT_READY)
        with self.assertRaises(DispatchClaimError):
            acquire_dispatch_claim(
                self.runtime,
                pre_activation.binding.dispatch_binding_id,
                pre_activation.binding_audit.binding_audit_id,
                0,
            )

        fresh = self._build_chain()
        self.assertEqual(fresh.binding.task_revision, 1)
        self.assertEqual(
            fresh.binding.task_content_hash,
            activation.new_task_content_hash,
        )
        self.assertEqual(
            self._binding_currentness(fresh).status,
            DispatchBindingCurrentnessStatus.CURRENT_READY,
        )

        runs_before = self.runtime.list_runs(self.task_id)
        workspaces_before = self._workspace_count()
        task_before_claim = self.runtime.get_task(self.task_id)
        barrier = threading.Barrier(2)
        successes: list[object] = []
        failures: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            runtime = OriginForgeRuntime(self.root)
            barrier.wait()
            try:
                value = acquire_dispatch_claim(
                    runtime,
                    fresh.binding.dispatch_binding_id,
                    fresh.binding_audit.binding_audit_id,
                    1,
                )
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    successes.append(value)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], DispatchClaimError)
        claim = successes[0]
        self.assertEqual(claim.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(claim.task_revision, 1)
        self.assertEqual(
            inspect_dispatch_claim_currentness_readonly(
                self.runtime,
                claim.claim_id,
            ).status,
            DispatchClaimCurrentnessStatus.CURRENT_ACTIVE,
        )
        self.assertEqual(self.runtime.get_task(self.task_id), task_before_claim)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)
        self.assertEqual(self._workspace_count(), workspaces_before)

        restarted = OriginForgeRuntime(self.root)
        self.assertEqual(
            inspect_dispatch_claim_currentness_readonly(
                restarted,
                claim.claim_id,
            ).status,
            DispatchClaimCurrentnessStatus.CURRENT_ACTIVE,
        )
        with self.assertRaises(DispatchClaimError):
            acquire_dispatch_claim(
                restarted,
                fresh.binding.dispatch_binding_id,
                fresh.binding_audit.binding_audit_id,
                1,
            )

        interrupted = interrupt_dispatch_claim(
            restarted,
            claim.claim_id,
            0,
            "explicit cross-process recovery",
        )
        self.assertEqual(interrupted.status, DispatchClaimStatus.INTERRUPTED)
        self.assertEqual(
            inspect_dispatch_claim_currentness_readonly(
                restarted,
                claim.claim_id,
            ).status,
            DispatchClaimCurrentnessStatus.INTERRUPTED,
        )
        self.assertEqual(self.runtime.get_task(self.task_id), task_before_claim)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)
        self.assertEqual(self._workspace_count(), workspaces_before)

        replacement = acquire_dispatch_claim(
            self.runtime,
            fresh.binding.dispatch_binding_id,
            fresh.binding_audit.binding_audit_id,
            1,
        )
        released = release_dispatch_claim(
            self.runtime,
            replacement.claim_id,
            0,
        )
        self.assertEqual(released.status, DispatchClaimStatus.RELEASED)
        self.assertEqual(
            inspect_dispatch_claim_currentness_readonly(
                self.runtime,
                replacement.claim_id,
            ).status,
            DispatchClaimCurrentnessStatus.RELEASED,
        )
        self.assertEqual(self.runtime.get_task(self.task_id), task_before_claim)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)
        self.assertEqual(self._workspace_count(), workspaces_before)

    def test_phase35_source_tree_stops_before_executor_invocation(self) -> None:
        modules = (
            activation_module,
            claims_module,
            lifecycle_module,
            read_module,
        )
        forbidden_text = (
            "BoundedRetryPolicy",
            "BoundedTaskOrchestrator",
            "subprocess",
            "importlib",
            "create_sandbox_backend",
            "ScheduledModelAdapter",
            "ModelScheduler",
            "ArtifactAdoption",
        )
        forbidden_calls = {
            "drive",
            "generate",
            "start_run",
            "create_run",
            "finish_run",
            "create_workspace",
            "record_verification",
            "transition_flow",
            "transition_goal",
            "lease",
            "use",
        }
        for module in modules:
            source = inspect.getsource(module)
            for forbidden in forbidden_text:
                self.assertNotIn(forbidden, source)
            tree = ast.parse(source)
            called = {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            } | {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            self.assertTrue(
                forbidden_calls.isdisjoint(called),
                f"{module.__name__} contains forbidden execution call",
            )


if __name__ == "__main__":
    unittest.main()
