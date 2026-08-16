from __future__ import annotations

import inspect
import tempfile
import unittest

import origin_forge.production_dispatch_read as dispatch_read_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_binding_models import DispatchBindingCurrentnessStatus
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_read import inspect_dispatch_binding_currentness_readonly
from origin_forge.production_dispatch_resolvers import ArtifactInputResolver
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.production_work_order_pixelorama import (
    PIXELORAMA_ADAPTER_ID,
    PIXELORAMA_SOURCE_ARTIFACT_TYPE,
    PIXELORAMA_SOURCE_ROLE,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.records import create_artifact
from origin_forge.runtime import OriginForgeRuntime


class Phase48BPixeloramaReadCurrentnessRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase48b-pixelorama-read-currentness-repair")
        goal_id = self.runtime.create_goal("revalidate persisted Pixelorama input")
        flow_id = self.runtime.create_flow(goal_id)
        self.task_id = self.runtime.create_task(
            flow_id,
            "export governed Pixelorama project",
            required_capabilities=("media.2d.export",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("media.2d.export"),),
            (full.adapter(PIXELORAMA_ADAPTER_ID),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=(PIXELORAMA_ADAPTER_ID,),
            allowed_capability_ids=("media.2d.export",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(policy, catalog)
        route = capability_store.resolve_and_publish(
            self.task_id,
            catalog.catalog_id,
            policy.routing_policy_id,
        )

        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_order_store = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            validators,
        )
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        self.resolvers = build_dispatch_input_resolver_registry()
        self.binders = build_builtin_dispatch_binder_registry()

        self.artifact_hash = "a" * 64
        self.artifact_id = create_artifact(
            self.runtime.store,
            self.runtime.project_id(),
            artifact_type=PIXELORAMA_SOURCE_ARTIFACT_TYPE,
            path_or_uri="assets/player.pxo",
            content_hash=self.artifact_hash,
        )
        ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            self.artifact_id,
            self.artifact_hash,
            PIXELORAMA_SOURCE_ROLE,
            None,
        )
        work_order = create_current_work_order(
            self.runtime,
            capability_store,
            dispatch_catalog,
            validators,
            route.route_decision_id,
            input_refs=(ref,),
            payload={},
        )
        work_order_audit = audit_work_order_frozen(
            capability_store,
            dispatch_catalog,
            validators,
            work_order,
        )
        work_order_store.publish_work_order(work_order)
        work_order_store.publish_audit(work_order_audit)

        bundle = create_input_resolution_bundle(
            work_order_store,
            self.resolvers,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            work_order_store,
            self.resolvers,
            self.binders,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            work_order_store,
            self.resolvers,
            self.binders,
            bundle,
            binding,
        )
        dispatch_store = ProductionDispatchStore(
            work_order_store,
            self.resolvers,
            self.binders,
        )
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.bundle = bundle
        self.binding = binding
        self.binding_audit = binding_audit

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def currentness(self):
        return inspect_dispatch_binding_currentness_readonly(
            self.runtime,
            self.bundle.input_resolution_id,
            self.binding.dispatch_binding_id,
            self.binding_audit.binding_audit_id,
            self.resolvers,
            self.binders,
        )

    def test_persisted_exact_pixelorama_artifact_binding_is_current_ready(self) -> None:
        currentness = self.currentness()
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.CURRENT_READY,
            currentness.to_dict(),
        )
        self.assertIsNone(currentness.detail)

    def test_artifact_metadata_drift_is_stale_input_without_byte_read(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE artifacts SET status = 'REJECTED' WHERE id = ?",
                (self.artifact_id,),
            )
        currentness = self.currentness()
        self.assertEqual(currentness.status, DispatchBindingCurrentnessStatus.STALE_INPUT)
        self.assertIn("differs from frozen input evidence", currentness.detail or "")

    def test_readonly_nonzero_ref_promotion_is_exact_not_generic(self) -> None:
        source = inspect.getsource(dispatch_read_module)
        self.assertIn('binding.selected_adapter_id != "originforge.pixelorama.export"', source)
        self.assertIn('binding.dispatch_contract_id != "pixelorama.spritesheet-export@1"', source)
        self.assertIn('binding.binder_id != "binder.pixelorama.spritesheet-export@1"', source)
        self.assertIn('resolved[0].original_ref.role != "pixelorama_project"', source)
        artifact_resolver_source = inspect.getsource(ArtifactInputResolver)
        self.assertNotIn("read_bytes", artifact_resolver_source)
        self.assertNotIn("open(", artifact_resolver_source)


if __name__ == "__main__":
    unittest.main()
