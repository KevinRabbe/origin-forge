from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from origin_forge.ids import IdKind, new_id
from origin_forge.pixelorama_models import (
    BridgeBudget,
    BridgeOutputType,
    ExportSpec,
    FrameSpec,
    RasterLayerSpec,
    SpriteProjectSpec,
)
from origin_forge.production_actions import (
    accept_production_execution,
    adopt_production_execution,
    inspect_production_execution,
)
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import (
    CapabilityCatalog,
    CapabilityRoutingPolicy,
)
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_pixelorama_source_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_invocation import dispatch_claim_once
from origin_forge.production_dispatch_phase_resolvers import (
    build_source_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_recovery import recover_dispatch_execution_once
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_pixelorama_source_dispatch_output_binding import (
    read_pixelorama_source_dispatch_output_binding,
)
from origin_forge.production_pixelorama_source_task_acceptance import (
    PixeloramaSourceTaskAcceptanceError,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime

BRIDGE = r'''
import binascii, hashlib, json, struct, sys, zlib
from pathlib import Path

def chunk(kind, data):
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xffffffff
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

def png(width, height):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(
        b"\0" + b"".join(
            bytes((255, 0, 0, 255)) if x == 0 and y == 0 else bytes((0, 0, 0, 0))
            for x in range(width)
        )
        for y in range(height)
    )
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")

args = sys.argv[1:]
args = args[args.index("--") + 1:]
request_path = Path(args[args.index("--origin-forge-request") + 1])
result_path = Path(args[args.index("--origin-forge-result") + 1])
request = json.loads(request_path.read_text(encoding="utf-8"))
spec = request["sprite_spec"]
project = Path("project") / (spec["output_basename"] + ".pxo")
project.parent.mkdir(parents=True, exist_ok=True)
project.write_bytes(b"pxo-created-by-test")
outputs = [{"output_type": "PIXELORAMA_PROJECT", "relative_path": project.as_posix(), "content_hash": "sha256:" + hashlib.sha256(project.read_bytes()).hexdigest(), "byte_count": project.stat().st_size, "width": None, "height": None}]
for export in request["export_specs"]:
    path = Path(export["relative_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    data = png(spec["width"], spec["height"])
    path.write_bytes(data)
    outputs.append({"output_type": export["output_type"], "relative_path": path.as_posix(), "content_hash": "sha256:" + hashlib.sha256(data).hexdigest(), "byte_count": len(data), "width": spec["width"], "height": spec["height"]})
result = {"protocol_version": 1, "operation_id": request["operation_id"], "request_hash": request["content_hash"], "status": "SUCCEEDED", "pixelorama_version": "test", "bridge_version": "1", "bridge_fingerprint": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "outputs": sorted(outputs, key=lambda value: value["relative_path"]), "diagnostics": [], "elapsed_ms": 1}
result["content_hash"] = "sha256:" + hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
result_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")), encoding="utf-8")
'''


class PixeloramaSourceDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-source-dispatch")
        goal = self.runtime.create_goal("create governed 2D source")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow, "create player source", required_capabilities=("media.2d.source",)
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)
        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("media.2d.source"),),
            (full.adapter("originforge.pixelorama.source"),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.pixelorama.source",),
            allowed_capability_ids=("media.2d.source",),
        )
        capabilities = ProductionCapabilityStore(self.runtime)
        capabilities.publish_catalog(catalog)
        capabilities.publish_policy(policy, catalog)
        route = capabilities.resolve_and_publish(
            self.task_id, catalog.catalog_id, policy.routing_policy_id
        )
        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_orders = ProductionWorkOrderStore(self.runtime, capabilities, validators)
        work_orders.publish_dispatch_catalog(dispatch_catalog)
        self.acceptance_id = new_id(IdKind.DESIGN_SPECIFICATION_ACCEPTANCE)
        inspection = SimpleNamespace(
            acceptance=SimpleNamespace(
                acceptance_id=self.acceptance_id,
                content_hash="sha256:" + "a" * 64,
                project_id=self.runtime.project_id(),
            ),
            design_input=SimpleNamespace(
                design_input_id="DESIGNIN-source-test",
                content_hash="sha256:" + "b" * 64,
                goal_id=goal,
                goal_revision=0,
                goal_content_hash="sha256:" + "e" * 64,
            ),
            specification=SimpleNamespace(
                design_specification_id="DESIGNSPEC-source-test",
                content_hash="sha256:" + "c" * 64,
            ),
            current=True,
            stale_reason=None,
        )
        projection = {
            "acceptance_id": self.acceptance_id,
            "acceptance_hash": inspection.acceptance.content_hash,
            "design_input_id": inspection.design_input.design_input_id,
            "design_input_hash": inspection.design_input.content_hash,
            "design_specification_id": inspection.specification.design_specification_id,
            "design_specification_hash": inspection.specification.content_hash,
            "goal_id": goal,
            "goal_revision": 0,
            "goal_content_hash": "sha256:" + "e" * 64,
        }
        ref = WorkOrderInputRef(
            WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE,
            self.acceptance_id,
            content_hash(projection),
            "accepted_design",
        )
        spec = SpriteProjectSpec(
            2,
            2,
            (RasterLayerSpec("base", "Base"),),
            (FrameSpec("idle-0"),),
            output_basename="player",
        )
        payload = {
            "operation": "CREATE_SPRITE_PROJECT",
            "sprite_spec": spec.to_dict(),
            "export_specs": [ExportSpec(BridgeOutputType.PNG, "exports/player.png").to_dict()],
            "budget": BridgeBudget(timeout_seconds=10).to_dict(),
        }
        work_order = create_current_work_order(
            self.runtime,
            capabilities,
            dispatch_catalog,
            validators,
            route.route_decision_id,
            input_refs=(ref,),
            payload=payload,
        )
        work_audit = audit_work_order_frozen(
            capabilities, dispatch_catalog, validators, work_order
        )
        work_orders.publish_work_order(work_order)
        work_orders.publish_audit(work_audit)
        resolvers = build_source_dispatch_input_resolver_registry()
        binders = build_pixelorama_source_dispatch_binder_registry()
        with patch(
            "origin_forge.production_dispatch_resolvers.inspect_accepted_design",
            return_value=inspection,
        ):
            bundle = create_input_resolution_bundle(
                work_orders, resolvers, work_order.work_order_id, work_audit.work_order_audit_id
            )
        with patch(
            "origin_forge.production_dispatch_resolvers.inspect_accepted_design",
            return_value=inspection,
        ):
            binding = create_dispatch_binding(work_orders, resolvers, binders, bundle)
            binding_audit = audit_dispatch_binding_frozen(
                work_orders, resolvers, binders, bundle, binding
            )
        dispatch_store = ProductionDispatchStore(work_orders, resolvers, binders)
        with patch(
            "origin_forge.production_dispatch_resolvers.inspect_accepted_design",
            return_value=inspection,
        ):
            dispatch_store.publish_input_resolution(bundle)
            dispatch_store.publish_binding(binding)
            dispatch_store.publish_audit(binding_audit)
        with patch(
            "origin_forge.production_dispatch_resolvers.inspect_accepted_design",
            return_value=inspection,
        ):
            self.claim = acquire_dispatch_claim(
                self.runtime, binding.dispatch_binding_id, binding_audit.binding_audit_id, 1
            )
        self.inspection = inspection
        self.bridge = self.root / "bridge.py"
        self.bridge.write_text(BRIDGE, encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_source_dispatch_publishes_binding_and_recovers_without_replay(self) -> None:
        bridge_hash = "sha256:" + hashlib.sha256(self.bridge.read_bytes()).hexdigest()
        env = {
            "ORIGIN_FORGE_PIXELORAMA_EXECUTABLE": sys.executable,
            "ORIGIN_FORGE_PIXELORAMA_BRIDGE_ID": "source-test-bridge",
            "ORIGIN_FORGE_PIXELORAMA_BRIDGE_VERSION": "1",
            "ORIGIN_FORGE_PIXELORAMA_BRIDGE_SHA256": bridge_hash,
            "ORIGIN_FORGE_PIXELORAMA_BRIDGE_PACKAGE": str(self.bridge),
            "ORIGIN_FORGE_PIXELORAMA_BRIDGE_ARGS_JSON": json.dumps([str(self.bridge)]),
        }
        planning = SimpleNamespace(
            planning_input_id="PLAN-source-test",
            content_hash="sha256:" + "d" * 64,
        )
        with (
            patch.dict("os.environ", env),
            patch(
                "origin_forge.production_dispatch_resolvers.inspect_accepted_design",
                return_value=self.inspection,
            ),
            patch(
                "origin_forge.production_design_specification_currentness.bridge_accepted_design_to_planning_input",
                return_value=planning,
            ),
        ):
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
            self.assertEqual(completed.execution.status.value, "RETURNED")
            inspected = inspect_production_execution(self.runtime, completed.execution.execution_id)
            self.assertTrue(inspected["supported_actions"]["adopt"])
            self.assertTrue(inspected["supported_actions"]["accept"])
            adopted = adopt_production_execution(
                self.runtime, completed.execution.execution_id, "assets/player.pxo"
            )
            self.assertTrue((self.root / "assets" / "player.pxo").is_file())
            with self.assertRaises(PixeloramaSourceTaskAcceptanceError):
                accept_production_execution(
                    self.runtime, completed.execution.execution_id
                )
            self.assertEqual(self.runtime.get_task(self.task_id)["status"], "RUNNING")
            accepted = accept_production_execution(
                self.runtime, completed.execution.execution_id, actor_id="operator-test"
            )
            self.assertEqual(accepted.task_id, self.task_id)
            self.assertEqual(self.runtime.get_task(self.task_id)["status"], "SUCCEEDED")
            self.assertEqual(adopted.source_artifact_id, next(
                value.artifact_id
                for value in read_pixelorama_source_dispatch_output_binding(
                    self.runtime, completed.execution.execution_id
                ).outputs
                if value.output_type is BridgeOutputType.PIXELORAMA_PROJECT
            ))
            binding = read_pixelorama_source_dispatch_output_binding(
                self.runtime, completed.execution.execution_id
            )
            self.assertEqual(len(binding.outputs), 2)
            recovered = recover_dispatch_execution_once(
                self.runtime, completed.execution.execution_id
            )
        self.assertEqual(recovered.execution.execution_id, completed.execution.execution_id)
        self.assertEqual(recovered.pixelorama_source_result.run_id, completed.pixelorama_source_result.run_id)


if __name__ == "__main__":
    unittest.main()
