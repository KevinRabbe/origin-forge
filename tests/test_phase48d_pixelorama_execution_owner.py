from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_execution as execution_module
import origin_forge.production_execution_assembly as assembly_module
from origin_forge.pixelorama_cli_export import PixeloramaCliProfile
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import audit_dispatch_binding_frozen, build_builtin_dispatch_binder_registry, create_dispatch_binding, create_input_resolution_bundle
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution import begin_dispatch_execution
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_assembly import PixeloramaSpritesheetExportExecutionPayload, ProductionExecutionAssemblyError, assemble_production_execution_dependencies
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import build_builtin_dispatch_catalog, build_builtin_dispatch_validator_registry
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.production_work_order_pixelorama import PIXELORAMA_ADAPTER_ID, PIXELORAMA_SOURCE_ARTIFACT_TYPE, PIXELORAMA_SOURCE_ROLE
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.records import create_artifact
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class Phase48DPixeloramaExecutionOwnerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase48d-pixelorama-execution")
        goal = self.runtime.create_goal("execute governed Pixelorama export")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(flow, "export Pixelorama project", required_capabilities=("media.2d.export",))
        activate_dependency_ready_task(self.runtime, self.task_id, 0)
        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create((full.capability("media.2d.export"),), (full.adapter(PIXELORAMA_ADAPTER_ID),))
        policy = CapabilityRoutingPolicy.create(catalog, ordered_adapter_ids=(PIXELORAMA_ADAPTER_ID,), allowed_capability_ids=("media.2d.export",))
        cap_store = ProductionCapabilityStore(self.runtime)
        cap_store.publish_catalog(catalog); cap_store.publish_policy(policy, catalog)
        route = cap_store.resolve_and_publish(self.task_id, catalog.catalog_id, policy.routing_policy_id)
        validators = build_builtin_dispatch_validator_registry(); dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, cap_store, validators); wo_store.publish_dispatch_catalog(dispatch_catalog)
        resolvers = build_dispatch_input_resolver_registry(); binders = build_builtin_dispatch_binder_registry()
        artifact_hash = "a" * 64
        artifact_id = create_artifact(self.runtime.store, self.runtime.project_id(), artifact_type=PIXELORAMA_SOURCE_ARTIFACT_TYPE, path_or_uri="assets/player.pxo", content_hash=artifact_hash)
        ref = WorkOrderInputRef(WorkOrderRefType.ARTIFACT, artifact_id, artifact_hash, PIXELORAMA_SOURCE_ROLE, None)
        work_order = create_current_work_order(self.runtime, cap_store, dispatch_catalog, validators, route.route_decision_id, input_refs=(ref,), payload={})
        wo_audit = audit_work_order_frozen(cap_store, dispatch_catalog, validators, work_order)
        wo_store.publish_work_order(work_order); wo_store.publish_audit(wo_audit)
        bundle = create_input_resolution_bundle(wo_store, resolvers, work_order.work_order_id, wo_audit.work_order_audit_id)
        binding = create_dispatch_binding(wo_store, resolvers, binders, bundle)
        binding_audit = audit_dispatch_binding_frozen(wo_store, resolvers, binders, bundle, binding)
        dispatch_store = ProductionDispatchStore(wo_store, resolvers, binders)
        dispatch_store.publish_input_resolution(bundle); dispatch_store.publish_binding(binding); dispatch_store.publish_audit(binding_audit)
        self.claim = acquire_dispatch_claim(self.runtime, binding.dispatch_binding_id, binding_audit.binding_audit_id, 1)
        self.env = {
            "ORIGIN_FORGE_PIXELORAMA_EXECUTABLE": str((self.root / "tools" / "Pixelorama").resolve()),
            "ORIGIN_FORGE_PIXELORAMA_SHA256": "sha256:" + "1" * 64,
            "ORIGIN_FORGE_PIXELORAMA_VERSION": "v1.2-stable",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def rows(self, table):
        with self.runtime.store.session() as conn:
            return [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE task_id = ?", (self.task_id,)).fetchall()]

    def test_dependencies_receive_only_exact_operator_profile_and_no_coding_stack(self):
        task_before = dict(self.runtime.get_task(self.task_id))
        with patch.dict(os.environ, self.env, clear=False), patch.object(PixeloramaCliProfile, "verify_executable", side_effect=AssertionError("verify executable")), patch.object(assembly_module, "load_config", side_effect=AssertionError("config")), patch.object(assembly_module, "create_model_scheduling", side_effect=AssertionError("model")), patch.object(assembly_module, "create_sandbox_backend", side_effect=AssertionError("sandbox")), patch.object(assembly_module, "GitWorkspaceManager", side_effect=AssertionError("workspace")):
            first = assemble_production_execution_dependencies(self.runtime, self.claim.claim_id)
            second = assemble_production_execution_dependencies(self.runtime, self.claim.claim_id)
        self.assertIsInstance(first.payload, PixeloramaSpritesheetExportExecutionPayload)
        self.assertEqual(first.plan.owner_id, "originforge.execution.pixelorama.spritesheet-export@1")
        self.assertEqual(first.plan.model_strategy_roles, ())
        self.assertEqual(first.plan.runtime_ids, ())
        self.assertEqual(first.plan.sandbox_backend, "not-required")
        self.assertEqual(first.plan.owner_dependency_hash, first.payload.profile_dependency_hash)
        self.assertRegex(first.plan.owner_dependency_hash or "", r"^[0-9a-f]{64}$")
        self.assertEqual(first.payload.profile.pixelorama_fingerprint, self.env["ORIGIN_FORGE_PIXELORAMA_SHA256"])
        self.assertEqual(first.payload.profile.expected_pixelorama_version, "v1.2-stable")
        self.assertEqual(first.plan.to_dict(), second.plan.to_dict())
        self.assertEqual(dict(self.runtime.get_task(self.task_id)), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])
        with patch.dict(os.environ, {**self.env, "ORIGIN_FORGE_PIXELORAMA_SHA256": "sha256:" + "2" * 64}, clear=False):
            changed = assemble_production_execution_dependencies(self.runtime, self.claim.claim_id)
        self.assertNotEqual(changed.plan.plan_hash, first.plan.plan_hash)

    def test_missing_profile_fails_before_started_and_begin_is_atomic_without_invocation(self):
        with patch.dict(os.environ, {key: "" for key in self.env}, clear=False):
            with self.assertRaisesRegex(ProductionExecutionAssemblyError, "profile is unavailable"):
                begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.READY.value)
        self.assertEqual(self.rows("dispatch_executions"), [])
        claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        with patch.dict(os.environ, self.env, clear=False), patch.object(PixeloramaCliProfile, "verify_executable", side_effect=AssertionError("48E verification/invocation")):
            started = begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(started.execution.status, DispatchExecutionStatus.STARTED)
        self.assertEqual(started.execution.execution_owner_id, "originforge.execution.pixelorama.spritesheet-export@1")
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(self.runtime.get_task(self.task_id)["revision"]), 2)
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id), claim_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_task_event_failure_rolls_back_started_and_running_state(self):
        task_before = dict(self.runtime.get_task(self.task_id)); claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        original = self.runtime.store._append_event; count = 0
        def injected(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2: raise RuntimeError("injected Pixelorama task-event failure")
            return original(*args, **kwargs)
        with patch.dict(os.environ, self.env, clear=False), patch.object(self.runtime.store, "_append_event", side_effect=injected):
            with self.assertRaisesRegex(RuntimeError, "task-event failure"):
                begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(dict(self.runtime.get_task(self.task_id)), task_before)
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id), claim_before)
        self.assertEqual(self.rows("dispatch_executions"), [])

    def test_phase48d_begin_surface_has_no_pixelorama_process_call(self):
        source = inspect.getsource(execution_module)
        self.assertNotIn("PixeloramaCliExportAdapter", source)
        tree = ast.parse(source)
        names = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("probe_version", names)


if __name__ == "__main__":
    unittest.main()
