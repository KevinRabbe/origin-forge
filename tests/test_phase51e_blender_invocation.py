from __future__ import annotations

import inspect
import json
import os
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import origin_forge.blender_models as blender_models_module
import origin_forge.production_dispatch_invocation as invocation_module
import origin_forge.production_dispatch_invocation_blender as blender_invocation_module
from origin_forge.blender_adapter import BlenderExecution
from origin_forge.blender_models import BlenderBudget, BlenderJobRequest
from origin_forge.blockbench_glb import inspect_glb
from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.ids import IdKind, validate_id
from origin_forge.model3d_requests import Model3DProductionRequest, Model3DRequestStore
from origin_forge.production_blender_export import BlenderExportService, BlenderExportServiceResult
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_blender import (
    CompletedBlenderDispatchInvocation,
)
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_blender import BLENDER_ADAPTER_ID, BLENDER_REQUEST_ROLE
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus


def _chunk(kind: int, payload: bytes, pad: bytes) -> bytes:
    if len(payload) % 4:
        payload += pad * (4 - len(payload) % 4)
    return struct.pack("<II", len(payload), kind) + payload


def _minimal_glb() -> bytes:
    root = {
        "asset": {"version": "2.0", "generator": "phase51e-fake-blender"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "OF_CUBOID_crate", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}
        ],
        "bufferViews": [{"buffer": 0, "byteLength": 12}],
        "buffers": [{"byteLength": 12}],
    }
    json_chunk = _chunk(
        0x4E4F534A,
        json.dumps(root, separators=(",", ":")).encode("utf-8"),
        b" ",
    )
    bin_chunk = _chunk(0x004E4942, b"\x00" * 12, b"\x00")
    length = 12 + len(json_chunk) + len(bin_chunk)
    return b"glTF" + struct.pack("<II", 2, length) + json_chunk + bin_chunk


class _FakeBlenderAdapter:
    def __init__(self, runtime: OriginForgeRuntime, profile):
        self.runtime = runtime
        self.profile = profile
        self.calls = 0

    def execute(self, request: BlenderJobRequest) -> BlenderExecution:
        self.calls += 1
        workspace = self.runtime.state_dir / "model3d-workspaces" / request.workspace_id
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir(parents=True, exist_ok=True)
        output = workspace / request.output_relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        data = _minimal_glb()
        output.write_bytes(data)
        return BlenderExecution(
            request=request,
            workspace_path=workspace,
            output_path=output,
            inspection=inspect_glb(data),
            blender_version=self.profile.expected_blender_version,
            runtime_hash=self.profile.runtime_hash,
            runner_fingerprint=self.profile.runner_fingerprint,
            stdout=b"fake blender output",
            stderr=b"",
        )


class Phase51EBlenderInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51e-blender-invocation")
        goal = self.runtime.create_goal("invoke governed Blender export")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "export one governed Blender GLB",
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

        self.project = BlockbenchProjectSpec(
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
        semantic_request = Model3DProductionRequest.create(project=self.project)
        Model3DRequestStore(self.runtime).put(semantic_request)
        self.semantic_request = semantic_request
        ref = WorkOrderInputRef(
            WorkOrderRefType.MODEL3D_REQUEST,
            semantic_request.request_id,
            semantic_request.request_hash.removeprefix("sha256:"),
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
            "ORIGIN_FORGE_BLENDER_VERSION": "Blender 5.2.0",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _execution_rows(self) -> list[dict[str, object]]:
        with self.runtime.store.session() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM dispatch_executions WHERE claim_id = ?",
                    (self.claim.claim_id,),
                ).fetchall()
            ]

    def _real_service_with_fake_adapter(self, service, task_id, request):
        rows = self._execution_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], DispatchExecutionStatus.STARTED.value)
        task = self.runtime.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task["revision"]), 2)
        self.assertTrue(validate_id(request.operation_id, IdKind.BLENDER_OPERATION))
        self.assertTrue(validate_id(request.workspace_id, IdKind.MODEL3D_WORKSPACE))
        self.assertEqual(request.project, self.project)
        self.assertEqual(request.output_relative_path, "exports/model.glb")
        self.assertEqual(request.runtime_hash, self.env["ORIGIN_FORGE_BLENDER_RUNTIME_SHA256"])
        self.assertEqual(request.expected_blender_version, self.env["ORIGIN_FORGE_BLENDER_VERSION"])
        self.assertEqual(request.budget, BlenderBudget())
        service.adapter = _FakeBlenderAdapter(self.runtime, service.profile)
        return self.original_service_execute(service, task_id, request)

    def test_runtime_ids_allocate_only_after_started_service_runs_once_and_returns(self) -> None:
        self.original_service_execute = BlenderExportService.execute
        original_new_id = blender_models_module.new_id
        allocated: list[IdKind] = []

        def guarded_new_id(kind: IdKind) -> str:
            if kind in {IdKind.BLENDER_OPERATION, IdKind.MODEL3D_WORKSPACE}:
                rows = self._execution_rows()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], DispatchExecutionStatus.STARTED.value)
                self.assertEqual(
                    self.runtime.get_task(self.task_id)["status"],
                    TaskStatus.RUNNING.value,
                )
                allocated.append(kind)
            return original_new_id(kind)

        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(blender_models_module, "new_id", side_effect=guarded_new_id),
            patch.object(
                BlenderExportService,
                "execute",
                autospec=True,
                side_effect=self._real_service_with_fake_adapter,
            ) as execute,
        ):
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

        self.assertEqual(
            allocated,
            [IdKind.BLENDER_OPERATION, IdKind.MODEL3D_WORKSPACE],
        )
        self.assertEqual(execute.call_count, 1)
        self.assertIsInstance(completed, CompletedDispatchInvocation)
        self.assertIsInstance(completed, CompletedBlenderDispatchInvocation)
        self.assertIsInstance(completed.blender_result, BlenderExportServiceResult)
        self.assertIsNone(completed.policy_result)
        self.assertIsNone(completed.simulation_result)
        self.assertIsNone(completed.pixelorama_result)
        self.assertEqual(completed.execution.status, DispatchExecutionStatus.RETURNED)
        self.assertEqual(
            completed.execution.execution_owner_id,
            "originforge.execution.blender.export-glb@1",
        )
        claim = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(claim.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(claim.revision, 1)
        task = self.runtime.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task["revision"]), 2)
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["role"], BlenderExportService.RUN_ROLE)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task_id), [])

    def test_ordinary_service_exception_records_raised_consumes_claim_and_keeps_task_running(self) -> None:
        class BlenderFailure(RuntimeError):
            pass

        with patch.dict(os.environ, self.env, clear=False), patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
            side_effect=BlenderFailure("sensitive Blender process text"),
        ) as execute:
            with self.assertRaises(ProductionDispatchInvocationError) as caught:
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertNotIn("sensitive Blender process text", str(caught.exception))
        self.assertIn("BlenderFailure", str(caught.exception))
        self.assertEqual(
            self._execution_rows()[0]["status"],
            DispatchExecutionStatus.RAISED.value,
        )
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id).status,
            DispatchClaimStatus.CONSUMED,
        )
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.RUNNING.value,
        )
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_base_exception_leaves_started_active_running_and_second_call_never_replays(self) -> None:
        with patch.dict(os.environ, self.env, clear=False), patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
            side_effect=KeyboardInterrupt(),
        ) as execute:
            with self.assertRaises(KeyboardInterrupt):
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(
            self._execution_rows()[0]["status"],
            DispatchExecutionStatus.STARTED.value,
        )
        claim = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(claim.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(claim.revision, 0)
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.RUNNING.value,
        )

        with patch.dict(os.environ, self.env, clear=False), patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
        ) as replay:
            with self.assertRaises(ProductionDispatchInvocationError):
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(len(self._execution_rows()), 1)

    def test_forged_typed_service_return_requires_recovery_without_false_returned(self) -> None:
        self.original_service_execute = BlenderExportService.execute

        def forged(service, task_id, request):
            result = self._real_service_with_fake_adapter(service, task_id, request)
            return replace(result, output_artifact_id=result.request_artifact_id)

        with patch.dict(os.environ, self.env, clear=False), patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
            side_effect=forged,
        ) as execute:
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(caught.exception.reason_code, "OWNER_RETURN_CONTRACT_MISMATCH")
        self.assertEqual(
            self._execution_rows()[0]["status"],
            DispatchExecutionStatus.STARTED.value,
        )
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.RUNNING.value,
        )
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)

    def test_blender_fanout_is_closed_single_shot_and_allocates_after_started_in_source(self) -> None:
        helper_source = inspect.getsource(
            blender_invocation_module.dispatch_blender_claim_once_if_applicable
        )
        public_source = inspect.getsource(invocation_module.dispatch_claim_once)
        self.assertLess(
            helper_source.index("started = legacy.begin_dispatch_execution"),
            helper_source.index("BlenderJobRequest.create("),
        )
        self.assertEqual(
            helper_source.count("BlenderExportService(runtime, payload.profile).execute("),
            1,
        )
        self.assertEqual(
            public_source.count("dispatch_blender_claim_once_if_applicable("),
            1,
        )
        for forbidden in ("importlib", "getattr(", "callable(", "while ", "for "):
            self.assertNotIn(forbidden, helper_source)
        self.assertNotIn("adopt", helper_source.lower())
        self.assertNotIn("sign", helper_source.lower())
        self.assertNotIn("transition_task", helper_source)


if __name__ == "__main__":
    unittest.main()
