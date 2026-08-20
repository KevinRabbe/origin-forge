from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.blender_adapter import BlenderExecution
from origin_forge.blender_models import BlenderJobRequest
from origin_forge.blockbench_glb import inspect_glb
from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.ids import IdKind, new_id
from origin_forge.model3d_requests import Model3DProductionRequest, Model3DRequestStore
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
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_blender import CompletedBlenderDispatchInvocation
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_planning_models import PlanningEvidenceRef, PlanningInput
from origin_forge.production_preparation_input_authority import planner_allowed_input_refs
from origin_forge.production_preparation_owner import build_builtin_preparation_owner_registry
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_blender import BLENDER_ADAPTER_ID
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.production_work_order_planner import (
    ProductionWorkOrderPlannerError,
    parse_work_order_proposal,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_HASH_E = "e" * 64
_BLENDER_PREPARATION_OWNER_ID = "originforge.preparation.blender-export-glb@1"


def _chunk(kind: int, payload: bytes, pad: bytes) -> bytes:
    if len(payload) % 4:
        payload += pad * (4 - len(payload) % 4)
    return struct.pack("<II", len(payload), kind) + payload


def _minimal_glb() -> bytes:
    root = {
        "asset": {"version": "2.0", "generator": "phase51f-preparation-fake-blender"},
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
            stdout=b"phase51f preparation fake blender output",
            stderr=b"",
        )


class Phase51FBlenderPreparationCurrentnessAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51f-blender-preparation-currentness")
        self.env = self._blender_env()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _blender_env(self) -> dict[str, str]:
        runtime_root = (self.root / "tools" / "blender-runtime").resolve()
        return {
            "ORIGIN_FORGE_BLENDER_RUNTIME_ROOT": str(runtime_root),
            "ORIGIN_FORGE_BLENDER_EXECUTABLE": str(runtime_root / "blender"),
            "ORIGIN_FORGE_BLENDER_RUNTIME_SHA256": "sha256:" + "1" * 64,
            "ORIGIN_FORGE_BLENDER_VERSION": "Blender 5.2.0",
        }

    @staticmethod
    def _project() -> BlockbenchProjectSpec:
        return BlockbenchProjectSpec(
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

    def _preparation_context(self):
        goal_id = self.runtime.create_goal("prepare one governed Blender semantic request")
        flow_id = self.runtime.create_flow(goal_id)
        task_id = self.runtime.create_task(
            flow_id,
            "prepare and export one governed Blender GLB",
            required_capabilities=("media.3d.blender",),
        )
        activate_dependency_ready_task(self.runtime, task_id, 0)

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
            task_id,
            catalog.catalog_id,
            policy.routing_policy_id,
        )

        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)

        request = Model3DProductionRequest.create(project=self._project())
        stored_request = Model3DRequestStore(self.runtime).put(request)
        planning_input = PlanningInput.create(
            project_id=self.runtime.project_id(),
            goal_id=goal_id,
            goal_revision=0,
            goal_content_hash=_HASH_A,
            verified_state_refs=(
                PlanningEvidenceRef(
                    ref_id=request.request_id,
                    content_hash=request.request_hash.removeprefix("sha256:"),
                    revision=None,
                ),
                PlanningEvidenceRef(
                    ref_id=new_id(IdKind.ARTIFACT),
                    content_hash=_HASH_E,
                    revision=None,
                ),
            ),
            active_design_rule_refs=(),
            project_intelligence_hash=_HASH_B,
            capability_catalog_hash=_HASH_C,
            capability_ids=("media.3d.blender",),
            model_policy_hash=_HASH_D,
            resource_policy_hash=_HASH_E,
        )
        owner = build_builtin_preparation_owner_registry().owner(
            _BLENDER_PREPARATION_OWNER_ID
        )
        contract = dispatch_catalog.contract_for_adapter(BLENDER_ADAPTER_ID)
        allowed = planner_allowed_input_refs(
            planning_input,
            owner.owner_id,
            contract,
        )
        proposal = parse_work_order_proposal(
            json.dumps(
                {
                    "contract_id": contract.contract_id,
                    "input_refs": [allowed[0].to_dict()],
                    "payload": {},
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            contract=contract,
            allowed_input_refs=allowed,
        )
        return {
            "goal_id": goal_id,
            "task_id": task_id,
            "cap_store": cap_store,
            "route": route,
            "validators": validators,
            "dispatch_catalog": dispatch_catalog,
            "wo_store": wo_store,
            "request": request,
            "stored_request": stored_request,
            "planning_input": planning_input,
            "owner": owner,
            "contract": contract,
            "allowed": allowed,
            "proposal": proposal,
        }

    def _claim_chain(self):
        context = self._preparation_context()
        work_order = create_current_work_order(
            self.runtime,
            context["cap_store"],
            context["dispatch_catalog"],
            context["validators"],
            context["route"].route_decision_id,
            input_refs=context["proposal"].input_refs,
            payload=context["proposal"].payload,
        )
        wo_audit = audit_work_order_frozen(
            context["cap_store"],
            context["dispatch_catalog"],
            context["validators"],
            work_order,
        )
        context["wo_store"].publish_work_order(work_order)
        context["wo_store"].publish_audit(wo_audit)

        resolvers = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()
        bundle = create_input_resolution_bundle(
            context["wo_store"],
            resolvers,
            work_order.work_order_id,
            wo_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(context["wo_store"], resolvers, binders, bundle)
        binding_audit = audit_dispatch_binding_frozen(
            context["wo_store"],
            resolvers,
            binders,
            bundle,
            binding,
        )
        dispatch_store = ProductionDispatchStore(context["wo_store"], resolvers, binders)
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        claim = acquire_dispatch_claim(
            self.runtime,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            1,
        )
        context.update(
            {
                "work_order": work_order,
                "work_order_audit": wo_audit,
                "bundle": bundle,
                "binding": binding,
                "binding_audit": binding_audit,
                "claim": claim,
            }
        )
        return context

    def _execute_with_fake_adapter(self, original_execute, service, task_id, request):
        service.adapter = _FakeBlenderAdapter(self.runtime, service.profile)
        return original_execute(service, task_id, request)

    def test_actual_preparation_authority_reaches_one_governed_blender_return(self) -> None:
        context = self._claim_chain()
        self.assertEqual(context["proposal"].input_refs, context["allowed"])
        self.assertEqual(context["work_order"].input_refs, context["allowed"])
        self.assertFalse((self.runtime.state_dir / "model3d-workspaces").exists())
        self.assertEqual(self.runtime.list_runs(context["task_id"]), [])

        original_execute = BlenderExportService.execute
        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(
                BlenderExportService,
                "execute",
                autospec=True,
                side_effect=lambda service, task_id, request: self._execute_with_fake_adapter(
                    original_execute, service, task_id, request
                ),
            ) as execute,
        ):
            completed = dispatch_claim_once(
                self.runtime,
                context["claim"].claim_id,
                0,
            )

        self.assertEqual(execute.call_count, 1)
        self.assertIsInstance(completed, CompletedBlenderDispatchInvocation)
        claim = read_dispatch_claim(self.runtime, context["claim"].claim_id)
        self.assertEqual(claim.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(claim.revision, 1)
        task = self.runtime.get_task(context["task_id"])
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task["revision"]), 2)
        runs = self.runtime.list_runs(context["task_id"])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["role"], BlenderExportService.RUN_ROLE)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)

    def test_phase_specific_wrong_role_and_extra_ref_substitution_fail_before_authority(self) -> None:
        context = self._preparation_context()
        allowed = context["allowed"]
        request = context["request"]
        forbidden = (
            (
                WorkOrderInputRef(
                    WorkOrderRefType.PHASE_SPECIFIC_EVIDENCE,
                    request.request_id,
                    request.request_hash.removeprefix("sha256:"),
                    "model3d_request",
                    None,
                ),
            ),
            (
                WorkOrderInputRef(
                    WorkOrderRefType.MODEL3D_REQUEST,
                    request.request_id,
                    request.request_hash.removeprefix("sha256:"),
                    "source",
                    None,
                ),
            ),
            (
                allowed[0],
                WorkOrderInputRef(
                    WorkOrderRefType.PHASE_SPECIFIC_EVIDENCE,
                    request.request_id,
                    request.request_hash.removeprefix("sha256:"),
                    "phase_specific",
                    None,
                ),
            ),
        )
        for refs in forbidden:
            with self.subTest(refs=tuple(value.to_dict() for value in refs)):
                with self.assertRaises(ProductionWorkOrderPlannerError):
                    parse_work_order_proposal(
                        json.dumps(
                            {
                                "contract_id": context["contract"].contract_id,
                                "input_refs": [value.to_dict() for value in refs],
                                "payload": {},
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        contract=context["contract"],
                        allowed_input_refs=allowed,
                    )

        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatch_claims").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM dispatch_executions").fetchone()[0],
                0,
            )
        self.assertEqual(self.runtime.list_runs(context["task_id"]), [])
        self.assertEqual(
            self.runtime.get_task(context["task_id"])["status"],
            TaskStatus.READY.value,
        )

    def test_deleted_protected_request_after_claim_fails_before_started_or_blender(self) -> None:
        context = self._claim_chain()
        context["stored_request"].path.unlink()
        self.assertFalse(context["stored_request"].path.exists())

        with (
            patch.dict(os.environ, self.env, clear=False),
            patch.object(
                BlenderExportService,
                "execute",
                autospec=True,
                side_effect=AssertionError("stale request must fail before Blender"),
            ) as execute,
        ):
            with self.assertRaises(ProductionDispatchInvocationError) as caught:
                dispatch_claim_once(
                    self.runtime,
                    context["claim"].claim_id,
                    0,
                )

        self.assertIn("CURRENT_ACTIVE", str(caught.exception))
        self.assertEqual(execute.call_count, 0)
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM dispatch_executions WHERE claim_id = ?",
                    (context["claim"].claim_id,),
                ).fetchone()[0],
                0,
            )
        self.assertEqual(self.runtime.list_runs(context["task_id"]), [])
        self.assertFalse((self.runtime.state_dir / "model3d-workspaces").exists())
        self.assertEqual(
            read_dispatch_claim(self.runtime, context["claim"].claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )
        task = self.runtime.get_task(context["task_id"])
        self.assertEqual(task["status"], TaskStatus.READY.value)
        self.assertEqual(int(task["revision"]), 1)


if __name__ == "__main__":
    unittest.main()
