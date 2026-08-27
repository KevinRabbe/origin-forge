from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from dataclasses import replace

import origin_forge.production_dispatch_binding_core as binding_core_module
import origin_forge.production_dispatch_binding_pixelorama as pixelorama_binding_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import (
    CapabilityCatalog,
    CapabilityRoutingPolicy,
)
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
    DispatchBindingCurrentnessStatus,
)
from origin_forge.production_dispatch_binding_pixelorama import (
    PIXELORAMA_BINDER_ID,
    PIXELORAMA_REQUEST_TYPE_ID,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
)
from origin_forge.production_work_order_pixelorama import (
    PIXELORAMA_ADAPTER_ID,
    PIXELORAMA_CONTRACT_ID,
    PIXELORAMA_EXPORT_PATH,
    PIXELORAMA_OPERATION,
    PIXELORAMA_SOURCE_ARTIFACT_TYPE,
    PIXELORAMA_SOURCE_ROLE,
    PIXELORAMA_STAGED_SOURCE_PATH,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.records import create_artifact
from origin_forge.runtime import OriginForgeRuntime


class Phase48BPixeloramaRequestBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase48b-pixelorama-binding")
        goal = self.runtime.create_goal("bind Pixelorama export request")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "export governed Pixelorama project",
            required_capabilities=("media.2d.export",),
        )

        full = build_builtin_capability_catalog()
        self.phase32 = CapabilityCatalog.create(
            (full.capability("media.2d.export"),),
            (full.adapter(PIXELORAMA_ADAPTER_ID),),
        )
        self.policy = CapabilityRoutingPolicy.create(
            self.phase32,
            ordered_adapter_ids=(PIXELORAMA_ADAPTER_ID,),
            allowed_capability_ids=("media.2d.export",),
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
        self.source_hash = "a" * 64
        self.source_artifact_id = create_artifact(
            self.runtime.store,
            self.runtime.project_id(),
            artifact_type=PIXELORAMA_SOURCE_ARTIFACT_TYPE,
            path_or_uri="assets/player.pxo",
            content_hash=self.source_hash,
        )
        self.source_ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            self.source_artifact_id,
            self.source_hash,
            PIXELORAMA_SOURCE_ROLE,
            None,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _bound_chain(self, *, source_ref: WorkOrderInputRef | None = None):
        ref = self.source_ref if source_ref is None else source_ref
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            self.route.route_decision_id,
            input_refs=(ref,),
            payload={},
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

    def test_exact_artifact_chain_reconstructs_inert_pixelorama_export_request(self) -> None:
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

        self.assertEqual(work_order.payload, {})
        self.assertEqual(work_order.input_refs, (self.source_ref,))
        self.assertEqual(len(bundle.resolved_inputs), 1)
        resolved = bundle.resolved_inputs[0]
        self.assertEqual(resolved.projection["type"], PIXELORAMA_SOURCE_ARTIFACT_TYPE)
        self.assertEqual(resolved.projection["status"], "PRODUCED")
        self.assertEqual(resolved.projection["path_or_uri"], "assets/player.pxo")
        self.assertNotIn("artifact_bytes", resolved.projection)
        self.assertEqual(
            binding.request_projection,
            {
                "task_id": self.task_id,
                "source_artifact_id": self.source_artifact_id,
                "source_artifact_hash": self.source_hash,
                "source_artifact_type": PIXELORAMA_SOURCE_ARTIFACT_TYPE,
                "source_artifact_status": "PRODUCED",
                "source_path_or_uri": "assets/player.pxo",
                "operation": PIXELORAMA_OPERATION,
                "staged_source_relative_path": PIXELORAMA_STAGED_SOURCE_PATH,
                "output_relative_path": PIXELORAMA_EXPORT_PATH,
            },
        )
        self.assertEqual(binding.binder_id, PIXELORAMA_BINDER_ID)
        self.assertEqual(binding.request_type_id, PIXELORAMA_REQUEST_TYPE_ID)
        self.assertEqual(audit.status, BindingAuditStatus.PASS)
        self.assertEqual(currentness.status, DispatchBindingCurrentnessStatus.CURRENT_READY)
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)

    def test_builtin_registry_preserves_pixelorama_with_blender_addition(self) -> None:
        first = build_builtin_dispatch_binder_registry()
        second = build_builtin_dispatch_binder_registry()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.descriptors, second.descriptors)
        self.assertEqual(
            tuple(value.binder_id for value in first.descriptors),
            (
                "binder.audio.ffmpeg-process@1",
                "binder.audio.piper-tts@1",
                "binder.blender.export-glb@1",
                "binder.build.integration@1",
                "binder.code.bounded-retry@1",
                "binder.image.generate@1",
                PIXELORAMA_BINDER_ID,
                "binder.playtest.cooperative@1",
                "binder.runtime.observe@1",
                "binder.simulation.deterministic@1",
            ),
        )
        descriptors = {value.binder_id: value for value in first.descriptors}
        self.assertEqual(
            descriptors["binder.code.bounded-retry@1"],
            CodeBoundedRetryInputBinder().descriptor,
        )
        self.assertEqual(
            descriptors[PIXELORAMA_BINDER_ID],
            PixeloramaSpritesheetExportInputBinder().descriptor,
        )
        self.assertEqual(
            descriptors["binder.simulation.deterministic@1"],
            DeterministicSimulationInputBinder().descriptor,
        )
        self.assertEqual(
            descriptors[PIXELORAMA_BINDER_ID].accepted_input_roles,
            (PIXELORAMA_SOURCE_ROLE,),
        )
        self.assertEqual(
            descriptors[PIXELORAMA_BINDER_ID].dispatch_contract_id,
            PIXELORAMA_CONTRACT_ID,
        )

    def test_wrong_artifact_type_or_status_fails_before_binding(self) -> None:
        wrong_type_id = create_artifact(
            self.runtime.store,
            self.runtime.project_id(),
            artifact_type="TEXT",
            path_or_uri="assets/not-project.pxo",
            content_hash="b" * 64,
        )
        wrong_type_ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            wrong_type_id,
            "b" * 64,
            PIXELORAMA_SOURCE_ROLE,
            None,
        )
        with self.assertRaisesRegex(RuntimeError, "wrong canonical Artifact type"):
            self._bound_chain(source_ref=wrong_type_ref)

        wrong_status_id = create_artifact(
            self.runtime.store,
            self.runtime.project_id(),
            artifact_type=PIXELORAMA_SOURCE_ARTIFACT_TYPE,
            path_or_uri="assets/stale.pxo",
            content_hash="c" * 64,
            status="REJECTED",
        )
        wrong_status_ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            wrong_status_id,
            "c" * 64,
            PIXELORAMA_SOURCE_ROLE,
            None,
        )
        with self.assertRaisesRegex(RuntimeError, "accepted PRODUCED state"):
            self._bound_chain(source_ref=wrong_status_ref)

    def test_artifact_hash_drift_fails_in_existing_resolver_before_binding(self) -> None:
        drifted = replace(self.source_ref, content_hash="d" * 64)
        with self.assertRaisesRegex(RuntimeError, "hash drifted"):
            self._bound_chain(source_ref=drifted)

    def test_frozen_audit_rejects_request_projection_forgery(self) -> None:
        _, bundle, binding, _ = self._bound_chain()
        forged = replace(
            binding,
            request_projection_json=canonical_bytes(
                {
                    **binding.request_projection,
                    "source_path_or_uri": "assets/other.pxo",
                }
            ).decode("utf-8"),
        )
        failed = audit_dispatch_binding_frozen(
            self.store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            forged,
        )
        self.assertEqual(failed.status, BindingAuditStatus.FAIL)
        self.assertIn("independently reconstruct", failed.failure_reason or "")

    def test_pixelorama_binding_surface_has_no_bytes_backend_or_identity_allocation(self) -> None:
        module_source = inspect.getsource(pixelorama_binding_module)
        for forbidden in (
            "open(",
            "read_bytes",
            "subprocess",
            "PixeloramaCliExportAdapter",
            "PixeloramaCliProfile",
            "new_id",
            "transition_task",
        ):
            self.assertNotIn(forbidden, module_source)
        source = "\n".join(
            (
                inspect.getsource(binding_core_module),
                module_source,
            )
        )
        tree = ast.parse(source)
        forbidden_calls = {
            "execute",
            "run",
            "drive",
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
