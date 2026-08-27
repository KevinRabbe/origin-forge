from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from origin_forge.image_vision_models import (
    ImageOperationRequest,
    ImageOperationResult,
    ImageOutputEvidence,
    ImageResultStatus,
    canonical_bytes,
)
from origin_forge.image_vision_service import ImageGenerationServiceResult
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import encode_rgba8_png, inspect_rgba8_png
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import (
    CapabilityCatalog,
    CapabilityRoutingPolicy,
)
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_image_owner import (
    recover_image_dispatch_execution_once,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_owner_image import IMAGE_EXECUTION_OWNER_ID
from origin_forge.production_image_dispatch_output_binding import (
    read_image_dispatch_output_binding,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from tests.test_image_workflows import _template


class _FakeComfyUiAdapter:
    calls = 0

    def __init__(self, runtime, profile, template):
        self.runtime = runtime
        self.profile = profile
        self.template = template

    def execute(self, request: ImageOperationRequest):
        type(self).calls += 1
        workspace = self.runtime.state_dir / "image-workspaces" / request.workspace_id
        (workspace / "request").mkdir(parents=True)
        (workspace / "inputs").mkdir()
        (workspace / "exports").mkdir()
        (workspace / "runtime").mkdir()
        (workspace / "request" / "request.json").write_bytes(canonical_bytes(request.to_dict()))
        data = encode_rgba8_png(PixelPlane(2, 2, bytes([20, 30, 40, 255] * 4)))
        output_path = workspace / request.output_relative_paths[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        inspection = inspect_rgba8_png(data)
        output = ImageOutputEvidence(
            relative_path=request.output_relative_paths[0],
            content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
            pixel_hash=inspection.pixel_hash,
            byte_count=len(data), width=2, height=2,
        )
        result = ImageOperationResult(
            operation_id=request.operation_id, workspace_id=request.workspace_id,
            request_hash=request.content_hash, status=ImageResultStatus.SUCCEEDED,
            backend_id=request.backend_id, backend_version=request.backend_version,
            workflow_hash=request.workflow_hash, model_id=request.model_id,
            model_hash=request.model_hash, outputs=(output,),
        )
        return SimpleNamespace(request=request, result=result, workspace_path=workspace)


class ImageDispatchVerticalTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeComfyUiAdapter.calls = 0
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(Path(self.tempdir.name))
        self.runtime.initialize("image-dispatch-vertical")
        goal = self.runtime.create_goal("generate one governed image")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow, "generate a governed image", required_capabilities=("image.generate",)
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)
        template = _template()
        from origin_forge.image_workflows import ImageWorkflowStore
        ImageWorkflowStore(self.runtime).put(template)

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("image.generate"),),
            (full.adapter("originforge.image.generate"),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog, ordered_adapter_ids=("originforge.image.generate",),
            allowed_capability_ids=("image.generate",),
        )
        self.cap_store = ProductionCapabilityStore(self.runtime)
        self.cap_store.publish_catalog(catalog)
        self.cap_store.publish_policy(policy, catalog)
        route = self.cap_store.resolve_and_publish(
            self.task_id, catalog.catalog_id, policy.routing_policy_id
        )
        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, self.cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)
        resolvers = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()
        payload = {
            "operation": "GENERATE", "backend_version": template.backend_version,
            "workflow_id": template.workflow_id, "workflow_hash": template.workflow_hash,
            "model_id": template.model_id, "model_hash": template.model_hash,
            "prompt": "a small blue robot", "negative_prompt": "blurry",
            "width": 2, "height": 2, "seed": 7, "steps": 2,
            "guidance_scale": "7.5", "output_relative_paths": ["exports/robot.png"],
            "timeout_seconds": 30, "max_output_bytes": 1024 * 1024,
            "max_history_bytes": 1024 * 1024,
        }
        work_order = create_current_work_order(
            self.runtime, self.cap_store, dispatch_catalog, validators,
            route.route_decision_id, payload=payload,
        )
        work_audit = audit_work_order_frozen(
            self.cap_store, dispatch_catalog, validators, work_order
        )
        self.assertEqual(work_audit.status.value, "PASS", work_audit.to_dict())
        wo_store.publish_work_order(work_order)
        wo_store.publish_audit(work_audit)
        bundle = create_input_resolution_bundle(
            wo_store, resolvers, work_order.work_order_id, work_audit.work_order_audit_id
        )
        binding = create_dispatch_binding(wo_store, resolvers, binders, bundle)
        binding_audit = audit_dispatch_binding_frozen(
            wo_store, resolvers, binders, bundle, binding
        )
        dispatch_store = ProductionDispatchStore(wo_store, resolvers, binders)
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.claim = acquire_dispatch_claim(
            self.runtime, binding.dispatch_binding_id, binding_audit.binding_audit_id, 1
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_claim_runs_image_service_and_recovery_materializes_without_replay(self) -> None:
        with patch(
            "origin_forge.production_dispatch_invocation_image_owner.ComfyUiAdapter",
            _FakeComfyUiAdapter,
        ):
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertIsInstance(completed.image_result, ImageGenerationServiceResult)
        self.assertEqual(_FakeComfyUiAdapter.calls, 1)
        self.assertEqual(completed.execution.status.value, "RETURNED")
        binding = read_image_dispatch_output_binding(
            self.runtime, completed.execution.execution_id
        )
        self.assertEqual(binding.execution_owner_id, IMAGE_EXECUTION_OWNER_ID)
        self.assertEqual(len(binding.outputs), 1)
        self.assertEqual(binding.outputs[0].relative_path, "exports/robot.png")
        recovered = recover_image_dispatch_execution_once(
            self.runtime, completed.execution.execution_id
        )
        self.assertEqual(recovered.image_result, completed.image_result)
        self.assertEqual(_FakeComfyUiAdapter.calls, 1)

    def test_recovery_rejects_tampered_png_without_reinvoking_comfy(self) -> None:
        with patch(
            "origin_forge.production_dispatch_invocation_image_owner.ComfyUiAdapter",
            _FakeComfyUiAdapter,
        ):
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        binding = read_image_dispatch_output_binding(
            self.runtime, completed.execution.execution_id
        )
        output_path = OriginForgeLineage(self.runtime).local_artifact_path(
            binding.outputs[0].artifact_id
        )
        output_path.write_bytes(encode_rgba8_png(PixelPlane(1, 1, bytes((0, 0, 255, 255)))))
        with self.assertRaises(ProductionDispatchInvocationRecoveryRequired):
            recover_image_dispatch_execution_once(
                self.runtime, completed.execution.execution_id
            )
        self.assertEqual(_FakeComfyUiAdapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
