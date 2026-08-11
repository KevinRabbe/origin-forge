from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from dataclasses import replace

import origin_forge.production_dispatch_binding as binding_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    CodeBoundedRetryInputBinder,
    DispatchBindingError,
    DispatchInputBinderRegistry,
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
    inspect_dispatch_binding_currentness,
)
from origin_forge.production_dispatch_binding_models import (
    BindingAuditStatus,
    DispatchBinderDescriptor,
    DispatchBindingAudit,
    DispatchBindingCurrentnessStatus,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_resolvers import build_core_input_resolver_registry
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import canonical_bytes
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class _BinderWithDescriptor:
    def __init__(self, descriptor: DispatchBinderDescriptor):
        self._descriptor = descriptor
        self._delegate = CodeBoundedRetryInputBinder()

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._descriptor

    def bind(self, work_order, bundle):
        return self._delegate.bind(work_order, bundle)


class ProductionDispatchBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("dispatch-binding")
        goal = self.runtime.create_goal("bind one governed code request")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "change code through the bounded retry path",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
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
            self.task_id,
            self.phase32.catalog_id,
            self.policy.routing_policy_id,
        )

        self.validator_registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.phase32)
        self.store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validator_registry,
        )
        self.store.publish_dispatch_catalog(self.dispatch_catalog)
        self.resolver_registry = build_dispatch_input_resolver_registry()
        self.binder_registry = build_builtin_dispatch_binder_registry()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _publish_work_order_chain(self, payload: dict[str, object]):
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            self.route.route_decision_id,
            payload=payload,
        )
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            work_order,
        )
        self.store.publish_work_order(work_order)
        self.store.publish_audit(audit)
        return work_order, audit

    def _bound_auto_chain(self):
        work_order, work_order_audit = self._publish_work_order_chain(
            {
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
            }
        )
        bundle = create_input_resolution_bundle(
            self.store,
            self.resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
        )
        audit = audit_dispatch_binding_frozen(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            binding,
        )
        return work_order, work_order_audit, bundle, binding, audit

    def test_zero_ref_code_chain_reconstructs_exact_drive_projection_without_state_transition(self) -> None:
        task_before = self.runtime.get_task(self.task_id)
        runs_before = self.runtime.list_runs(self.task_id)

        work_order, _, bundle, binding, audit = self._bound_auto_chain()
        currentness = inspect_dispatch_binding_currentness(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            binding,
            audit,
        )

        self.assertEqual(bundle.resolved_inputs, ())
        self.assertEqual(
            binding.request_projection,
            {
                "task_id": self.task_id,
                "selected_paths": [],
                "auto_context": True,
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
                "semantic_context": False,
            },
        )
        self.assertEqual(binding.work_order_id, work_order.work_order_id)
        self.assertEqual(audit.status, BindingAuditStatus.PASS)
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.CURRENT_READY,
        )
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)

    def test_manual_context_maps_to_existing_drive_signature_exactly(self) -> None:
        work_order, work_order_audit = self._publish_work_order_chain(
            {
                "context_mode": "manual",
                "selected_paths": ["src/origin_forge/runtime.py"],
                "semantic_context": True,
            }
        )
        bundle = create_input_resolution_bundle(
            self.store,
            self.resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
        )
        self.assertEqual(
            binding.request_projection,
            {
                "task_id": self.task_id,
                "selected_paths": ["src/origin_forge/runtime.py"],
                "auto_context": False,
                "context_seed_paths": [],
                "structural_context": False,
                "semantic_context": True,
            },
        )

    def test_forged_bundle_is_rejected_before_binding(self) -> None:
        work_order, work_order_audit = self._publish_work_order_chain(
            {"context_mode": "auto"}
        )
        bundle = create_input_resolution_bundle(
            self.store,
            self.resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        forged = replace(bundle, resolver_registry_fingerprint="a" * 64)
        with self.assertRaisesRegex(
            DispatchBindingError,
            "does not independently reconstruct",
        ):
            create_dispatch_binding(
                self.store,
                self.resolver_registry,
                self.binder_registry,
                forged,
            )

    def test_binding_audit_recomputes_request_and_rejects_forgery(self) -> None:
        _, _, bundle, binding, _ = self._bound_auto_chain()
        forged = replace(
            binding,
            request_projection_json=canonical_bytes(
                {
                    **binding.request_projection,
                    "semantic_context": True,
                }
            ).decode("utf-8"),
        )
        audit = audit_dispatch_binding_frozen(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            forged,
        )
        self.assertEqual(audit.status, BindingAuditStatus.FAIL)
        self.assertIn("independently reconstruct", audit.failure_reason or "")

    def test_self_consistent_forged_binding_and_pass_audit_still_fail_currentness(self) -> None:
        _, _, bundle, binding, _ = self._bound_auto_chain()
        forged_binding = replace(
            binding,
            request_projection_json=canonical_bytes(
                {
                    **binding.request_projection,
                    "semantic_context": True,
                }
            ).decode("utf-8"),
        )
        forged_audit = DispatchBindingAudit.pass_for(forged_binding, bundle)

        currentness = inspect_dispatch_binding_currentness(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            forged_binding,
            forged_audit,
        )
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.INVALID_AUDIT,
        )
        self.assertIn("independently reconstruct", currentness.detail or "")

    def test_live_registry_drift_is_separate_from_historical_pass_audit(self) -> None:
        _, _, bundle, binding, audit = self._bound_auto_chain()
        currentness = inspect_dispatch_binding_currentness(
            self.store,
            build_core_input_resolver_registry(),
            self.binder_registry,
            bundle,
            binding,
            audit,
        )
        self.assertEqual(audit.status, BindingAuditStatus.PASS)
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.RESOLVER_DRIFT,
        )

        original = CodeBoundedRetryInputBinder().descriptor
        drifted = replace(original, binder_fingerprint="b" * 64)
        drifted_registry = DispatchInputBinderRegistry((_BinderWithDescriptor(drifted),))
        currentness = inspect_dispatch_binding_currentness(
            self.store,
            self.resolver_registry,
            drifted_registry,
            bundle,
            binding,
            audit,
        )
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.BINDER_DRIFT,
        )

    def test_task_revision_drift_marks_work_order_stale_without_rewriting_historical_audit(self) -> None:
        _, _, bundle, binding, audit = self._bound_auto_chain()
        task = self.runtime.get_task(self.task_id)
        self.runtime.transition_task(
            self.task_id,
            TaskStatus.RUNNING,
            expected_revision=int(task["revision"]),
        )
        currentness = inspect_dispatch_binding_currentness(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            binding,
            audit,
        )
        self.assertEqual(audit.status, BindingAuditStatus.PASS)
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.STALE_WORK_ORDER,
        )

    def test_binder_registry_is_deterministic_and_rejects_ambiguous_relation(self) -> None:
        first = build_builtin_dispatch_binder_registry()
        second = build_builtin_dispatch_binder_registry()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.descriptors, second.descriptors)
        descriptor = CodeBoundedRetryInputBinder().descriptor
        alias = replace(
            descriptor,
            binder_id="binder.code.alias@1",
            binder_fingerprint="c" * 64,
        )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            DispatchInputBinderRegistry(
                (CodeBoundedRetryInputBinder(), _BinderWithDescriptor(alias))
            )

    def test_binder_source_has_no_adapter_task_run_or_dynamic_execution_calls(self) -> None:
        source = inspect.getsource(binding_module)
        self.assertNotIn("importlib", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("orchestration_policy", source)
        tree = ast.parse(source)
        forbidden = {
            "drive",
            "execute",
            "generate",
            "dispatch",
            "transition_task",
            "start_run",
            "create_run",
            "finish_run",
            "record_verification",
            "publish_work_order",
            "publish_audit",
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden.isdisjoint(called_attributes | called_names))


if __name__ == "__main__":
    unittest.main()
