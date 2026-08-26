from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.ids import IdKind, new_id
from origin_forge.model3d_requests import Model3DProductionRequest, Model3DRequestStore
from origin_forge.production_capability_builtin import (
    builtin_production_capabilities,
    builtin_trusted_production_adapters,
)
from origin_forge.production_capability_models import CapabilityCatalog
from origin_forge.production_dispatch_binding import build_builtin_dispatch_binder_registry
from origin_forge.production_dispatch_binding_blender import BlenderExportGLBInputBinder
from origin_forge.production_dispatch_binding_core import DispatchBindingError
from origin_forge.production_dispatch_phase_resolvers import (
    Model3DRequestInputResolver,
    PhaseSpecificResolverReviewStatus,
    build_dispatch_input_resolver_registry,
    phase_specific_resolver_review,
)
from origin_forge.production_dispatch_resolution_models import InputResolutionBundle
from origin_forge.production_dispatch_resolvers import DispatchInputResolutionError
from origin_forge.production_work_order_blender import (
    BLENDER_ADAPTER_ID,
    BLENDER_CONTRACT_ID,
    BLENDER_OPERATION,
    BLENDER_REQUEST_ROLE,
    BlenderExportGLBDispatchValidator,
)
from origin_forge.production_work_order_builtin import (
    BuiltinDispatchReviewStatus,
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
    builtin_dispatch_review,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
)
from origin_forge.production_work_order_validators import DispatchValidatorError
from origin_forge.production_work_orders import ProductionWorkOrder
from origin_forge.runtime import OriginForgeRuntime


class Phase51BBlenderWorkOrderBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51b-blender-binding-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _project(*, rotation: Vec3 | None = None) -> BlockbenchProjectSpec:
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
                    rotation=rotation or Vec3(0, 0, 0),
                ),
            ),
        )

    def _stored_request(self, *, rotation: Vec3 | None = None) -> Model3DProductionRequest:
        request = Model3DProductionRequest.create(project=self._project(rotation=rotation))
        Model3DRequestStore(self.runtime).put(request)
        return request

    @staticmethod
    def _ref(request: Model3DProductionRequest) -> WorkOrderInputRef:
        return WorkOrderInputRef(
            WorkOrderRefType.MODEL3D_REQUEST,
            request.request_id,
            request.request_hash.removeprefix("sha256:"),
            BLENDER_REQUEST_ROLE,
            None,
        )

    @staticmethod
    def _work_order(ref: WorkOrderInputRef) -> ProductionWorkOrder:
        return ProductionWorkOrder(
            work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
            task_id=new_id(IdKind.TASK),
            task_revision=7,
            task_content_hash="1" * 64,
            flow_id=new_id(IdKind.FLOW),
            route_decision_id=new_id(IdKind.CAPABILITY_ROUTE_DECISION),
            route_decision_hash="2" * 64,
            selected_adapter_id=BLENDER_ADAPTER_ID,
            selected_adapter_fingerprint="3" * 64,
            dispatch_catalog_id=new_id(IdKind.DISPATCH_CONTRACT_CATALOG),
            dispatch_catalog_hash="4" * 64,
            dispatch_contract_id=BLENDER_CONTRACT_ID,
            dispatch_contract_hash="5" * 64,
            input_refs=(ref,),
            payload_json="{}",
        )

    @staticmethod
    def _bundle(work_order: ProductionWorkOrder, resolved) -> InputResolutionBundle:
        return InputResolutionBundle.create(
            work_order_id=work_order.work_order_id,
            work_order_hash=work_order.content_hash,
            work_order_audit_id=new_id(IdKind.WORK_ORDER_AUDIT),
            work_order_audit_hash="6" * 64,
            task_id=work_order.task_id,
            task_revision=work_order.task_revision,
            task_content_hash=work_order.task_content_hash,
            route_decision_id=work_order.route_decision_id,
            route_decision_hash=work_order.route_decision_hash,
            selected_adapter_id=work_order.selected_adapter_id,
            selected_adapter_fingerprint=work_order.selected_adapter_fingerprint,
            dispatch_catalog_id=work_order.dispatch_catalog_id,
            dispatch_catalog_hash=work_order.dispatch_catalog_hash,
            dispatch_contract_id=work_order.dispatch_contract_id,
            dispatch_contract_hash=work_order.dispatch_contract_hash,
            resolver_registry_fingerprint="7" * 64,
            resolved_inputs=(resolved,),
        )

    def test_exact_model3d_ref_resolves_from_protected_store(self) -> None:
        request = self._stored_request()
        ref = self._ref(request)
        resolved = Model3DRequestInputResolver().resolve(self.runtime, ref)
        self.assertEqual(resolved.source_object_type, "MODEL3D_REQUEST")
        self.assertEqual(resolved.resolution_class, "PROTECTED_MODEL3D_REQUEST")
        self.assertEqual(resolved.source_id, request.request_id)
        self.assertEqual(resolved.source_content_hash, ref.content_hash)
        self.assertEqual(resolved.projection, request.to_dict())

        registry = build_dispatch_input_resolver_registry()
        resolved_all = registry.resolve_all(self.runtime, (ref,))
        self.assertEqual(resolved_all, (resolved,))

    def test_model3d_resolver_is_exact_noncreating_and_tamper_closed(self) -> None:
        request = Model3DProductionRequest.create(project=self._project())
        ref = self._ref(request)
        registry_root = self.runtime.state_dir / "model3d-requests"
        self.assertFalse(registry_root.exists())
        with self.assertRaises(DispatchInputResolutionError):
            Model3DRequestInputResolver().resolve(self.runtime, ref)
        self.assertFalse(registry_root.exists())

        stored = Model3DRequestStore(self.runtime).put(request)
        value = request.to_dict()
        value["project_hash"] = "sha256:" + "9" * 64
        stored.path.write_bytes(canonical_bytes(value))
        with self.assertRaises(DispatchInputResolutionError):
            Model3DRequestInputResolver().resolve(self.runtime, ref)

    def test_work_order_contract_is_exact_inert_and_typed(self) -> None:
        request = self._stored_request()
        ref = self._ref(request)
        validator = BlenderExportGLBDispatchValidator()
        self.assertEqual(validator.validate({}, (ref,)), {})
        self.assertEqual(validator.payload_schema_id, "schema.blender.export-glb@1")

        with self.assertRaises(DispatchValidatorError):
            validator.validate({"output_relative_path": "exports/evil.glb"}, (ref,))
        with self.assertRaises(DispatchValidatorError):
            validator.validate({}, ())
        wrong_role = WorkOrderInputRef(
            WorkOrderRefType.MODEL3D_REQUEST,
            ref.ref_id,
            ref.content_hash,
            "source",
        )
        with self.assertRaises(DispatchValidatorError):
            validator.validate({}, (wrong_role,))

    def test_blender_binding_is_deterministic_semantic_and_runtime_free(self) -> None:
        request = self._stored_request()
        ref = self._ref(request)
        resolved = Model3DRequestInputResolver().resolve(self.runtime, ref)
        work_order = self._work_order(ref)
        bundle = self._bundle(work_order, resolved)
        binder = BlenderExportGLBInputBinder()

        first = binder.bind(work_order, bundle)
        second = binder.bind(work_order, bundle)
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            {
                "task_id": work_order.task_id,
                "model3d_request_id": request.request_id,
                "model3d_request_hash": request.request_hash,
                "operation": BLENDER_OPERATION,
                "project": request.project.to_dict(),
                "project_hash": request.project.content_hash,
            },
        )
        serialized = json.dumps(first, sort_keys=True)
        for forbidden in (
            "operation_id",
            "workspace_id",
            "output_relative_path",
            "runner_fingerprint",
            "runtime_hash",
            "expected_blender_version",
            "timeout_seconds",
            "max_output_bytes",
            "executable",
            "argv",
            "environment",
            "claim",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_binding_rejects_blender_v1_incompatible_semantics(self) -> None:
        request = self._stored_request(rotation=Vec3(0, 45, 0))
        ref = self._ref(request)
        resolved = Model3DRequestInputResolver().resolve(self.runtime, ref)
        work_order = self._work_order(ref)
        bundle = self._bundle(work_order, resolved)
        with self.assertRaisesRegex(DispatchBindingError, "incompatible"):
            BlenderExportGLBInputBinder().bind(work_order, bundle)

    def test_review_and_builtin_registries_promote_only_blender_boundary(self) -> None:
        resolver_rows = {row.evidence_family: row for row in phase_specific_resolver_review()}
        self.assertIs(
            resolver_rows["model3d-request"].status,
            PhaseSpecificResolverReviewStatus.SUPPORTED,
        )
        review_rows = {row.adapter_id: row for row in builtin_dispatch_review()}
        self.assertIs(
            review_rows[BLENDER_ADAPTER_ID].status,
            BuiltinDispatchReviewStatus.SUPPORTED,
        )
        self.assertEqual(len(build_builtin_dispatch_binder_registry().descriptors), 5)
        validator = build_builtin_dispatch_validator_registry().validator(
            "validator.blender.export-glb@1"
        )
        self.assertEqual(validator.validator_id, "validator.blender.export-glb@1")

    def test_blender_only_catalog_gets_exact_contract_and_mixed_non_code_fails_closed(self) -> None:
        capabilities = {
            value.capability_id: value for value in builtin_production_capabilities()
        }
        adapters = {
            value.adapter_id: value for value in builtin_trusted_production_adapters()
        }
        blender_catalog = CapabilityCatalog.create(
            (capabilities["media.3d.blender"],),
            (adapters[BLENDER_ADAPTER_ID],),
        )
        dispatch = build_builtin_dispatch_catalog(blender_catalog)
        contract = dispatch.contract_for_adapter(BLENDER_ADAPTER_ID)
        self.assertEqual(contract.contract_id, BLENDER_CONTRACT_ID)
        self.assertEqual(
            contract.allowed_input_ref_types,
            (WorkOrderRefType.MODEL3D_REQUEST,),
        )
        self.assertEqual(contract.max_input_refs, 1)

        mixed = CapabilityCatalog.create(
            (capabilities["media.3d.blender"], capabilities["media.2d.export"]),
            (adapters[BLENDER_ADAPTER_ID], adapters["originforge.pixelorama.export"]),
        )
        with self.assertRaisesRegex(ValueError, "multiple reviewed non-code"):
            build_builtin_dispatch_catalog(mixed)


if __name__ == "__main__":
    unittest.main()
