from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from dataclasses import replace

import origin_forge.production_dispatch_binding_core as binding_core_module
import origin_forge.production_dispatch_binding_simulation as simulation_binding_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    CodeBoundedRetryInputBinder,
    DeterministicSimulationInputBinder,
    PixeloramaSpritesheetExportInputBinder,
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
    inspect_dispatch_binding_currentness,
)
from origin_forge.production_dispatch_binding_models import (
    BindingAuditStatus,
    DispatchBindingAudit,
    DispatchBindingCurrentnessStatus,
)
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import canonical_bytes
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime


class Phase47BSimulationRequestBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase47b-simulation-binding")
        goal = self.runtime.create_goal("bind deterministic simulation request")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "run deterministic simulation",
            required_capabilities=("simulation.run",),
        )

        full = build_builtin_capability_catalog()
        self.phase32 = CapabilityCatalog.create(
            (full.capability("simulation.run"),),
            (full.adapter("originforge.simulation.deterministic"),),
        )
        self.policy = CapabilityRoutingPolicy.create(
            self.phase32,
            ordered_adapter_ids=("originforge.simulation.deterministic",),
            allowed_capability_ids=("simulation.run",),
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

    @staticmethod
    def _payload() -> dict[str, object]:
        return {
            "seed": 7,
            "replicates": 2,
            "max_steps": 10,
            "stall_steps": 3,
            "initial_state_json": '{"ore":0}',
            "rules_json": '[{"consume":{},"priority":0,"probability_ppm":1000000,"produce":{"ore":1},"requires":{},"rule_id":"mine"}]',
            "invariants_json": "[]",
        }

    def _bound_chain(self):
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            self.route.route_decision_id,
            payload=self._payload(),
        )
        work_order_audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            work_order,
        )
        self.store.publish_work_order(work_order)
        self.store.publish_audit(work_order_audit)
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
        return work_order, bundle, binding, audit

    def test_zero_ref_simulation_chain_reconstructs_exact_semantic_request(self) -> None:
        task_before = self.runtime.get_task(self.task_id)
        runs_before = self.runtime.list_runs(self.task_id)
        work_order, bundle, binding, audit = self._bound_chain()
        currentness = inspect_dispatch_binding_currentness(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            binding,
            audit,
        )

        self.assertEqual(work_order.input_refs, ())
        self.assertEqual(bundle.resolved_inputs, ())
        self.assertEqual(
            binding.request_projection,
            {
                "task_id": self.task_id,
                "engine_id": "origin-forge-deterministic-sim",
                "engine_version": "1",
                "seed": 7,
                "replicates": 2,
                "max_steps": 10,
                "stall_steps": 3,
                "initial_state": {"ore": 0},
                "rules": [
                    {
                        "rule_id": "mine",
                        "priority": 0,
                        "probability_ppm": 1_000_000,
                        "requires": {},
                        "consume": {},
                        "produce": {"ore": 1},
                    }
                ],
                "invariants": [],
            },
        )
        self.assertEqual(binding.binder_id, "binder.simulation.deterministic@1")
        self.assertEqual(binding.request_type_id, "SimulationService.execute@production-v1")
        self.assertEqual(audit.status, BindingAuditStatus.PASS)
        self.assertEqual(currentness.status, DispatchBindingCurrentnessStatus.CURRENT_READY)
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)

    def test_builtin_registry_preserves_code_simulation_pixelorama_and_blender(self) -> None:
        first = build_builtin_dispatch_binder_registry()
        second = build_builtin_dispatch_binder_registry()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.descriptors, second.descriptors)
        self.assertEqual(
            tuple(value.binder_id for value in first.descriptors),
            (
                "binder.audio.piper-tts@1",
                "binder.blender.export-glb@1",
                "binder.code.bounded-retry@1",
                "binder.image.generate@1",
                "binder.pixelorama.spritesheet-export@1",
                "binder.playtest.cooperative@1",
                "binder.runtime.observe@1",
                "binder.simulation.deterministic@1",
            ),
        )
        code = CodeBoundedRetryInputBinder().descriptor
        pixelorama = PixeloramaSpritesheetExportInputBinder().descriptor
        simulation = DeterministicSimulationInputBinder().descriptor
        descriptors = {value.binder_id: value for value in first.descriptors}
        self.assertEqual(descriptors[code.binder_id], code)
        self.assertEqual(descriptors[pixelorama.binder_id], pixelorama)
        self.assertEqual(descriptors[simulation.binder_id], simulation)
        self.assertEqual(pixelorama.accepted_input_roles, ("pixelorama_project",))
        self.assertEqual(simulation.accepted_input_roles, ())
        contract = self.dispatch_catalog.contract("simulation.deterministic@1")
        self.assertEqual(contract.allowed_input_ref_types, ())
        self.assertEqual(contract.max_input_refs, 0)

    def test_frozen_audit_and_currentness_reject_request_and_binder_forgery(self) -> None:
        _, bundle, binding, _ = self._bound_chain()
        forged_projection = {
            **binding.request_projection,
            "seed": 8,
        }
        forged_request = replace(
            binding,
            request_projection_json=canonical_bytes(forged_projection).decode("utf-8"),
        )
        failed = audit_dispatch_binding_frozen(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            forged_request,
        )
        self.assertEqual(failed.status, BindingAuditStatus.FAIL)
        self.assertIn("independently reconstruct", failed.failure_reason or "")

        forged_binder = replace(binding, binder_fingerprint="f" * 64)
        forged_pass = DispatchBindingAudit.pass_for(forged_binder, bundle)
        currentness = inspect_dispatch_binding_currentness(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            forged_binder,
            forged_pass,
        )
        self.assertEqual(currentness.status, DispatchBindingCurrentnessStatus.BINDER_DRIFT)

    def test_simulation_binding_surface_has_no_backend_or_identity_allocation_calls(self) -> None:
        source = "\n".join(
            (
                inspect.getsource(binding_core_module),
                inspect.getsource(simulation_binding_module),
            )
        )
        for forbidden_text in ("subprocess", "importlib", "new_id", "transition_task"):
            self.assertNotIn(forbidden_text, inspect.getsource(simulation_binding_module))
        tree = ast.parse(source)
        forbidden_calls = {
            "execute",
            "run",
            "generate",
            "dispatch",
            "create_run",
            "finish_run",
            "record_verification",
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
        self.assertTrue(forbidden_calls.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
