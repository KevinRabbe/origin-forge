from __future__ import annotations

import ast
import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import origin_forge.production_dispatch_claims as claims_module
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
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
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
from origin_forge.service import StaleRevision
from origin_forge.state import TaskStatus


class ProductionDispatchClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dispatch-claims")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _chain(self, *, activate: bool) -> SimpleNamespace:
        goal_id = self.runtime.create_goal("claim exact dispatch")
        flow_id = self.runtime.create_flow(goal_id)
        task_id = self.runtime.create_task(
            flow_id,
            "change code through bounded retry",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        if activate:
            activation = activate_dependency_ready_task(self.runtime, task_id, 0)
            task_revision = activation.new_revision
        else:
            activation = None
            task_revision = 0

        phase32 = build_builtin_capability_catalog()
        policy = CapabilityRoutingPolicy.create(
            phase32,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(phase32)
        capability_store.publish_policy(policy, phase32)
        route = capability_store.resolve_and_publish(
            task_id,
            phase32.catalog_id,
            policy.routing_policy_id,
        )

        validator_registry = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(phase32)
        work_order_store = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            validator_registry,
        )
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        work_order = create_current_work_order(
            self.runtime,
            capability_store,
            dispatch_catalog,
            validator_registry,
            route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
            },
        )
        work_order_audit = audit_work_order_frozen(
            capability_store,
            dispatch_catalog,
            validator_registry,
            work_order,
        )
        work_order_store.publish_work_order(work_order)
        work_order_store.publish_audit(work_order_audit)

        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
        bundle = create_input_resolution_bundle(
            work_order_store,
            resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
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
        dispatch_store = ProductionDispatchStore(
            work_order_store,
            resolver_registry,
            binder_registry,
        )
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)

        return SimpleNamespace(
            task_id=task_id,
            task_revision=task_revision,
            activation=activation,
            route=route,
            work_order=work_order,
            work_order_audit=work_order_audit,
            bundle=bundle,
            binding=binding,
            binding_audit=binding_audit,
            resolver_registry=resolver_registry,
            binder_registry=binder_registry,
        )

    def test_current_ready_chain_acquires_one_exact_claim_without_task_run_or_workspace_mutation(self) -> None:
        chain = self._chain(activate=True)
        task_before = self.runtime.get_task(chain.task_id)
        runs_before = self.runtime.list_runs(chain.task_id)
        with self.runtime.store.session() as conn:
            workspaces_before = conn.execute(
                "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                (chain.task_id,),
            ).fetchone()[0]

        claim = acquire_dispatch_claim(
            self.runtime,
            chain.binding.dispatch_binding_id,
            chain.binding_audit.binding_audit_id,
            chain.task_revision,
        )

        self.assertEqual(claim.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(claim.revision, 0)
        self.assertEqual(claim.task_id, chain.task_id)
        self.assertEqual(claim.task_revision, chain.task_revision)
        self.assertEqual(claim.task_content_hash, chain.binding.task_content_hash)
        self.assertEqual(claim.work_order_id, chain.binding.work_order_id)
        self.assertEqual(claim.work_order_hash, chain.binding.work_order_hash)
        self.assertEqual(
            claim.dispatch_binding_id,
            chain.binding.dispatch_binding_id,
        )
        self.assertEqual(claim.dispatch_binding_hash, chain.binding.content_hash)
        self.assertEqual(claim.binding_audit_id, chain.binding_audit.binding_audit_id)
        self.assertEqual(claim.binding_audit_hash, chain.binding_audit.content_hash)
        self.assertEqual(claim.binder_id, chain.binding.binder_id)
        self.assertEqual(task_before, self.runtime.get_task(chain.task_id))
        self.assertEqual(runs_before, self.runtime.list_runs(chain.task_id))
        with self.runtime.store.session() as conn:
            workspaces_after = conn.execute(
                "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                (chain.task_id,),
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM dispatch_claims WHERE task_id = ?",
                (chain.task_id,),
            ).fetchall()
            events = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = 'DISPATCH_CLAIM'
                     AND aggregate_id = ?
                     AND event_type = 'DISPATCH_CLAIM_ACQUIRED'""",
                (claim.claim_id,),
            ).fetchall()
        self.assertEqual(workspaces_after, workspaces_before)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ACTIVE")
        self.assertEqual(len(events), 1)

    def test_queued_chain_is_not_claimable_even_when_phase34_reports_dependency_ready(self) -> None:
        chain = self._chain(activate=False)
        currentness = inspect_dispatch_binding_currentness_readonly(
            self.runtime,
            chain.bundle.input_resolution_id,
            chain.binding.dispatch_binding_id,
            chain.binding_audit.binding_audit_id,
            chain.resolver_registry,
            chain.binder_registry,
        )
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.CURRENT_READY,
        )
        self.assertEqual(self.runtime.get_task(chain.task_id)["status"], TaskStatus.QUEUED.value)
        with self.assertRaisesRegex(DispatchClaimError, "canonical READY Task"):
            acquire_dispatch_claim(
                self.runtime,
                chain.binding.dispatch_binding_id,
                chain.binding_audit.binding_audit_id,
                0,
            )
        with self.runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM dispatch_claims WHERE task_id = ?",
                (chain.task_id,),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_expected_revision_must_match_exact_binding_revision(self) -> None:
        chain = self._chain(activate=True)
        with self.assertRaises(StaleRevision):
            acquire_dispatch_claim(
                self.runtime,
                chain.binding.dispatch_binding_id,
                chain.binding_audit.binding_audit_id,
                chain.task_revision + 1,
            )
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0],
                0,
            )

    def test_task_drift_after_binding_fails_before_claim(self) -> None:
        chain = self._chain(activate=True)
        self.runtime.transition_task(
            chain.task_id,
            TaskStatus.RUNNING,
            expected_revision=chain.task_revision,
        )
        with self.assertRaises(DispatchClaimError):
            acquire_dispatch_claim(
                self.runtime,
                chain.binding.dispatch_binding_id,
                chain.binding_audit.binding_audit_id,
                chain.task_revision,
            )
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0],
                0,
            )

    def test_second_claim_for_same_task_is_rejected_without_new_event(self) -> None:
        chain = self._chain(activate=True)
        first = acquire_dispatch_claim(
            self.runtime,
            chain.binding.dispatch_binding_id,
            chain.binding_audit.binding_audit_id,
            chain.task_revision,
        )
        with self.assertRaisesRegex(DispatchClaimError, "already has ACTIVE"):
            acquire_dispatch_claim(
                self.runtime,
                chain.binding.dispatch_binding_id,
                chain.binding_audit.binding_audit_id,
                chain.task_revision,
            )
        with self.runtime.store.session() as conn:
            claims = conn.execute(
                "SELECT claim_id FROM dispatch_claims WHERE task_id = ?",
                (chain.task_id,),
            ).fetchall()
            events = conn.execute(
                """SELECT id FROM state_events
                   WHERE aggregate_type = 'DISPATCH_CLAIM'
                     AND event_type = 'DISPATCH_CLAIM_ACQUIRED'"""
            ).fetchall()
        self.assertEqual([row["claim_id"] for row in claims], [first.claim_id])
        self.assertEqual(len(events), 1)

    def test_concurrent_store_instances_create_exactly_one_active_claim(self) -> None:
        chain = self._chain(activate=True)
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
                    chain.binding.dispatch_binding_id,
                    chain.binding_audit.binding_audit_id,
                    chain.task_revision,
                )
            except BaseException as exc:  # exact loser may fail at pre-check or unique index
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
        with self.runtime.store.session() as conn:
            active = conn.execute(
                """SELECT COUNT(*) FROM dispatch_claims
                   WHERE task_id = ? AND status = 'ACTIVE'""",
                (chain.task_id,),
            ).fetchone()[0]
        self.assertEqual(active, 1)

    def test_claim_api_derives_authority_and_exposes_no_execution_surface(self) -> None:
        signature = inspect.signature(acquire_dispatch_claim)
        self.assertEqual(
            tuple(signature.parameters),
            (
                "runtime",
                "dispatch_binding_id",
                "binding_audit_id",
                "expected_task_revision",
            ),
        )
        source = inspect.getsource(claims_module)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("importlib", source)
        self.assertNotIn("orchestration_policy", source)
        tree = ast.parse(source)
        forbidden = {
            "drive",
            "generate",
            "start_run",
            "create_run",
            "finish_run",
            "transition_task",
            "create_workspace",
            "record_verification",
            "publish_work_order",
            "publish_binding",
            "publish_audit",
            "use",
            "lease",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
