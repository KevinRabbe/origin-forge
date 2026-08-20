from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.blender_adapter as blender_adapter_module
import origin_forge.production_dispatch_execution as execution_module
import origin_forge.production_execution_assembly as assembly_module
from origin_forge.blender_adapter import BlenderRuntimeProfile
from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.model3d_requests import Model3DProductionRequest, Model3DRequestStore
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution import begin_dispatch_execution
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_assembly import (
    BlenderExportGLBExecutionPayload,
    ProductionExecutionAssemblyError,
    assemble_production_execution_dependencies,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_blender import (
    BLENDER_ADAPTER_ID,
    BLENDER_REQUEST_ROLE,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class Phase51DBlenderExecutionOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51d-blender-execution")
        goal = self.runtime.create_goal("execute governed Blender export")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "export Blender GLB",
            required_capabilities=("media.3d.blender",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("media.3d.blender"),),
            (full.adapter(BLENDER_ADAPTER_ID),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=(BLENDER_ADAPTER_ID,),
            allowed_capability_ids=("media.3d.blender",),
        )
        cap_store = ProductionCapabilityStore(self.runtime)
        cap_store.publish_catalog(catalog)
        cap_store.publish_policy(policy, catalog)
        route = cap_store.resolve_and_publish(
            self.task_id,
            catalog.catalog_id,
            policy.routing_policy_id,
        )

        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)
        resolvers = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()

        project = BlockbenchProjectSpec(
            project_name="crate",
            bones=(),
            cuboids=(
                CuboidSpec(
                    element_id="body",
                    name="Body",
                    from_point=Vec3(0, 0, 0),
                    to_point=Vec3(2, 3, 4),
                    origin=Vec3(0, 0, 0),
                    rotation=Vec3(0, 0, 0),
                ),
            ),
        )
        request = Model3DProductionRequest.create(project=project)
        Model3DRequestStore(self.runtime).put(request)
        ref = WorkOrderInputRef(
            WorkOrderRefType.MODEL3D_REQUEST,
            request.request_id,
            request.request_hash.removeprefix("sha256:"),
            BLENDER_REQUEST_ROLE,
            None,
        )
        work_order = create_current_work_order(
            self.runtime,
            cap_store,
            dispatch_catalog,
            validators,
            route.route_decision_id,
            input_refs=(ref,),
            payload={},
        )
        wo_audit = audit_work_order_frozen(
            cap_store,
            dispatch_catalog,
            validators,
            work_order,
        )
        wo_store.publish_work_order(work_order)
        wo_store.publish_audit(wo_audit)
        bundle = create_input_resolution_bundle(
            wo_store,
            resolvers,
            work_order.work_order_id,
            wo_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(wo_store, resolvers, binders, bundle)
        binding_audit = audit_dispatch_binding_frozen(
            wo_store,
            resolvers,
            binders,
            bundle,
            binding,
        )
        dispatch_store = ProductionDispatchStore(wo_store, resolvers, binders)
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.claim = acquire_dispatch_claim(
            self.runtime,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            1,
        )

        runtime_root = (self.root / "tools" / "blender-runtime").resolve()
        self.env = {
            "ORIGIN_FORGE_BLENDER_RUNTIME_ROOT": str(runtime_root),
            "ORIGIN_FORGE_BLENDER_EXECUTABLE": str(runtime_root / "blender"),
            "ORIGIN_FORGE_BLENDER_RUNTIME_SHA256": "sha256:" + "1" * 64,
            "ORIGIN_FORGE_BLENDER_VERSION": "4.3.2",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def rows(self, table: str) -> list[dict[str, object]]:
        with self.runtime.store.session() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM {table} WHERE task_id = ?",
                    (self.task_id,),
                ).fetchall()
            ]

    def test_dependencies_receive_only_trusted_blender_profile_and_no_coding_stack(self) -> None:
        task_before = dict(self.runtime.get_task(self.task_id))
        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(
                BlenderRuntimeProfile,
                "verify",
                side_effect=AssertionError("runtime verification belongs after STARTED"),
            ),
            patch.object(
                blender_adapter_module,
                "blender_runtime_tree_hash",
                side_effect=AssertionError("runtime tree read belongs after STARTED"),
            ),
            patch.object(assembly_module, "load_config", side_effect=AssertionError("config")),
            patch.object(
                assembly_module,
                "create_model_scheduling",
                side_effect=AssertionError("model"),
            ),
            patch.object(
                assembly_module,
                "create_sandbox_backend",
                side_effect=AssertionError("sandbox"),
            ),
            patch.object(
                assembly_module,
                "GitWorkspaceManager",
                side_effect=AssertionError("workspace"),
            ),
        ):
            first = assemble_production_execution_dependencies(
                self.runtime,
                self.claim.claim_id,
            )
            second = assemble_production_execution_dependencies(
                self.runtime,
                self.claim.claim_id,
            )

        self.assertIsInstance(first.payload, BlenderExportGLBExecutionPayload)
        self.assertEqual(
            first.plan.owner_id,
            "originforge.execution.blender.export-glb@1",
        )
        self.assertEqual(first.plan.model_strategy_roles, ())
        self.assertEqual(first.plan.model_profile_ids, ())
        self.assertEqual(first.plan.runtime_ids, ())
        self.assertEqual(first.plan.runtime_provider_fingerprints, ())
        self.assertEqual(first.plan.sandbox_backend, "not-required")
        self.assertEqual(
            first.plan.owner_dependency_hash,
            first.payload.profile_dependency_hash,
        )
        self.assertRegex(first.plan.owner_dependency_hash or "", r"^[0-9a-f]{64}$")
        self.assertEqual(
            first.payload.profile.runtime_hash,
            self.env["ORIGIN_FORGE_BLENDER_RUNTIME_SHA256"],
        )
        self.assertEqual(first.payload.profile.expected_blender_version, "4.3.2")
        self.assertEqual(first.plan.to_dict(), second.plan.to_dict())
        self.assertEqual(dict(self.runtime.get_task(self.task_id)), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])
        self.assertFalse((self.runtime.state_dir / "model3d-workspaces").exists())

        changed_env = {
            **self.env,
            "ORIGIN_FORGE_BLENDER_RUNTIME_SHA256": "sha256:" + "2" * 64,
        }
        with patch.dict(os.environ, changed_env, clear=False):
            changed = assemble_production_execution_dependencies(
                self.runtime,
                self.claim.claim_id,
            )
        self.assertNotEqual(changed.plan.plan_hash, first.plan.plan_hash)

    def test_missing_profile_fails_before_started_and_begin_is_atomic_without_invocation(self) -> None:
        with patch.dict(
            os.environ,
            {key: "" for key in self.env},
            clear=False,
        ):
            with self.assertRaisesRegex(
                ProductionExecutionAssemblyError,
                "profile is unavailable",
            ):
                begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.READY.value,
        )
        self.assertEqual(self.rows("dispatch_executions"), [])

        claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(
                BlenderRuntimeProfile,
                "verify",
                side_effect=AssertionError("51E runtime verification/invocation"),
            ),
        ):
            started = begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(started.execution.status, DispatchExecutionStatus.STARTED)
        self.assertEqual(
            started.execution.execution_owner_id,
            "originforge.execution.blender.export-glb@1",
        )
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.RUNNING.value,
        )
        self.assertEqual(int(self.runtime.get_task(self.task_id)["revision"]), 2)
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id),
            claim_before,
        )
        self.assertEqual(self.runtime.list_runs(self.task_id), [])
        self.assertFalse((self.runtime.state_dir / "model3d-workspaces").exists())

        with patch.dict(os.environ, self.env, clear=False):
            with self.assertRaises(ProductionExecutionAssemblyError):
                begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(len(self.rows("dispatch_executions")), 1)
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.RUNNING.value,
        )

    def test_task_event_failure_rolls_back_started_and_running_state(self) -> None:
        task_before = dict(self.runtime.get_task(self.task_id))
        claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        original = self.runtime.store._append_event
        count = 0

        def injected(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("injected Blender task-event failure")
            return original(*args, **kwargs)

        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(
                self.runtime.store,
                "_append_event",
                side_effect=injected,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "task-event failure"):
                begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(dict(self.runtime.get_task(self.task_id)), task_before)
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id),
            claim_before,
        )
        self.assertEqual(self.rows("dispatch_executions"), [])

    def test_phase51d_begin_surface_has_no_blender_invocation_or_runtime_id_allocation(self) -> None:
        source = inspect.getsource(execution_module)
        self.assertNotIn("BlenderAdapter", source)
        self.assertNotIn("BoundedBlenderSubprocessRunner", source)
        self.assertNotIn("BLENDER_OPERATION", source)
        self.assertNotIn("MODEL3D", source)
        tree = ast.parse(source)
        names = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("verify", names)
        self.assertNotIn("run", names)


if __name__ == "__main__":
    unittest.main()
