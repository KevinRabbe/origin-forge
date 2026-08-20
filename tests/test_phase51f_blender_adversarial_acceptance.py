from __future__ import annotations

import json
import os
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_invocation as invocation_module
from origin_forge.blender_adapter import BlenderExecution
from origin_forge.blender_models import BlenderJobRequest
from origin_forge.blockbench_glb import inspect_glb
from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.lineage import OriginForgeLineage
from origin_forge.model3d_requests import Model3DProductionRequest, Model3DRequestStore
from origin_forge.production_blender_dispatch_output_binding import (
    read_blender_dispatch_output_binding,
)
from origin_forge.production_blender_export import BlenderExportService
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
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_blender import CompletedBlenderDispatchInvocation
from origin_forge.production_dispatch_invocation_blender_recovery import (
    recover_blender_dispatch_execution_once,
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
        "asset": {"version": "2.0", "generator": "phase51f-fake-blender"},
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

    def execute(self, request: BlenderJobRequest) -> BlenderExecution:
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
            stdout=b"phase51f fake blender output",
            stderr=b"",
        )


class Phase51FBlenderAdversarialAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51f-blender-adversarial-acceptance")
        goal = self.runtime.create_goal("race one governed Blender export")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "export one governed Blender GLB exactly once",
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

    def _execute_with_fake_adapter(self, service, task_id, request):
        service.adapter = _FakeBlenderAdapter(self.runtime, service.profile)
        return self._original_service_execute(service, task_id, request)

    def _leave_durable_output_before_terminalization(self) -> str:
        self._original_service_execute = BlenderExportService.execute
        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(
                BlenderExportService,
                "execute",
                autospec=True,
                side_effect=self._execute_with_fake_adapter,
            ) as execute,
            patch.object(
                invocation_module,
                "mark_dispatch_execution_returned",
                side_effect=RuntimeError("injected dispatch finalization failure"),
            ),
        ):
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(caught.exception.reason_code, "RETURNED_TERMINALIZATION_FAILED")
        rows = self._execution_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], DispatchExecutionStatus.STARTED.value)
        execution_id = rows[0]["execution_id"]
        read_blender_dispatch_output_binding(self.runtime, execution_id)
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)
        return execution_id

    def test_two_workers_race_same_claim_and_only_one_reaches_blender(self) -> None:
        original_execute = BlenderExportService.execute
        service_entered = threading.Event()
        release_service = threading.Event()
        call_lock = threading.Lock()
        service_calls = 0

        def blocked_real_execute(service, task_id, request):
            nonlocal service_calls
            with call_lock:
                service_calls += 1
                ordinal = service_calls
            if ordinal != 1:
                raise AssertionError("a competing worker reached Blender service execution")
            service_entered.set()
            if not release_service.wait(timeout=10):
                raise AssertionError("timed out holding the winning Blender execution")
            service.adapter = _FakeBlenderAdapter(self.runtime, service.profile)
            return original_execute(service, task_id, request)

        first_result: list[object] = []
        first_error: list[BaseException] = []
        second_result: list[object] = []
        second_error: list[BaseException] = []

        def invoke(result: list[object], errors: list[BaseException]) -> None:
            try:
                result.append(dispatch_claim_once(self.runtime, self.claim.claim_id, 0))
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=invoke, args=(first_result, first_error))
        second = threading.Thread(target=invoke, args=(second_result, second_error))
        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(
                BlenderExportService,
                "execute",
                autospec=True,
                side_effect=blocked_real_execute,
            ) as execute,
        ):
            first.start()
            self.assertTrue(service_entered.wait(timeout=10))
            self.assertEqual(
                self._execution_rows()[0]["status"],
                DispatchExecutionStatus.STARTED.value,
            )
            second.start()
            second.join(timeout=10)
            try:
                self.assertFalse(
                    second.is_alive(),
                    "losing worker blocked instead of failing closed",
                )
                self.assertEqual(second_result, [])
                self.assertEqual(len(second_error), 1)
                self.assertIsInstance(second_error[0], ProductionDispatchInvocationError)
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(service_calls, 1)
            finally:
                release_service.set()
            first.join(timeout=10)

        self.assertFalse(first.is_alive(), "winning worker did not finish")
        self.assertEqual(first_error, [])
        self.assertEqual(len(first_result), 1)
        self.assertIsInstance(first_result[0], CompletedBlenderDispatchInvocation)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(service_calls, 1)

        rows = self._execution_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], DispatchExecutionStatus.RETURNED.value)
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

    def test_durable_output_recovers_terminalization_without_blender_replay(self) -> None:
        execution_id = self._leave_durable_output_before_terminalization()
        with patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
            side_effect=AssertionError("recovery must not replay Blender"),
        ) as replay:
            recovered = recover_blender_dispatch_execution_once(
                self.runtime,
                execution_id,
            )
        self.assertEqual(replay.call_count, 0)
        self.assertIsInstance(recovered, CompletedBlenderDispatchInvocation)
        self.assertEqual(recovered.execution.status, DispatchExecutionStatus.RETURNED)
        claim = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(claim.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(claim.revision, 1)
        task = self.runtime.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task["revision"]), 2)
        self.assertEqual(len(self.runtime.list_runs(self.task_id)), 1)

    def test_recovery_rejects_bound_glb_drift_without_blender_replay(self) -> None:
        execution_id = self._leave_durable_output_before_terminalization()
        binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        lineage = OriginForgeLineage(self.runtime)
        output_path = lineage.local_artifact_path(binding.output_artifact_id)
        output_path.write_bytes(b"not-a-glb")

        with patch.object(
            BlenderExportService,
            "execute",
            autospec=True,
            side_effect=AssertionError("drift recovery must not replay Blender"),
        ) as replay:
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
                recover_blender_dispatch_execution_once(self.runtime, execution_id)
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(caught.exception.reason_code, "OWNER_RETURN_CONTRACT_MISMATCH")
        self.assertEqual(
            self._execution_rows()[0]["status"],
            DispatchExecutionStatus.STARTED.value,
        )
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )


if __name__ == "__main__":
    unittest.main()
