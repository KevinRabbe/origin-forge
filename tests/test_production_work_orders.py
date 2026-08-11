from __future__ import annotations

import inspect
import tempfile
import unittest

from origin_forge.production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    CapabilityRoutingPolicy,
    ProductionCapability,
    TrustedProductionAdapter,
)
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
    WorkOrderInputRef,
    WorkOrderRefType,
)
from origin_forge.production_work_order_validators import (
    DispatchContractValidatorRegistry,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)
from origin_forge.production_work_orders import (
    ProductionWorkOrderError,
    create_current_work_order,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class ProductionWorkOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("work-orders")
        self.goal = self.runtime.create_goal("produce governed work")
        self.flow = self.runtime.create_flow(self.goal)

        self.code_capability = ProductionCapability(
            "code.change",
            "Code change",
            "bounded coding",
            CapabilityDomain.CODE,
            "1",
        )
        self.observe_capability = ProductionCapability(
            "runtime.observe",
            "Runtime observation",
            "bounded runtime evidence",
            CapabilityDomain.RUNTIME,
            "1",
        )
        self.code_adapter = TrustedProductionAdapter(
            "originforge.code.bounded-retry",
            "originforge.code",
            "1",
            "a" * 64,
            ("code.change",),
            AdapterExecutionEffect.WORKSPACE_MUTATION,
            AdapterReplayClass.REVISION_BOUND,
        )
        self.observe_adapter = TrustedProductionAdapter(
            "originforge.runtime.observe",
            "originforge.runtime",
            "1",
            "b" * 64,
            ("runtime.observe",),
            AdapterExecutionEffect.OBSERVATION_ONLY,
            AdapterReplayClass.RUNTIME_BOUND,
        )
        self.phase32_catalog = CapabilityCatalog.create(
            (self.code_capability, self.observe_capability),
            (self.code_adapter, self.observe_adapter),
        )
        self.phase32_policy = CapabilityRoutingPolicy.create(
            self.phase32_catalog,
            ordered_adapter_ids=(
                "originforge.code.bounded-retry",
                "originforge.runtime.observe",
            ),
            allowed_capability_ids=("code.change", "runtime.observe"),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.phase32_catalog)
        self.capability_store.publish_policy(
            self.phase32_policy,
            self.phase32_catalog,
        )

        self.validator = StaticObjectPayloadValidator(
            validator_id="validator.code.bounded-retry@1",
            payload_schema_id="schema.code.bounded-retry@1",
            fields=(
                PayloadFieldRule(
                    "context_mode",
                    PayloadFieldKind.STRING,
                    allowed_values=("auto", "manual"),
                    max_string_chars=16,
                ),
                PayloadFieldRule(
                    "change_required",
                    PayloadFieldKind.BOOLEAN,
                ),
                PayloadFieldRule(
                    "seed_paths",
                    PayloadFieldKind.STRING_LIST,
                    required=False,
                    max_string_chars=256,
                    max_items=16,
                ),
            ),
        )
        self.registry = DispatchContractValidatorRegistry((self.validator,))
        self.code_contract = DispatchContract(
            "code.bounded-retry@1",
            "1",
            self.code_adapter.adapter_id,
            self.code_adapter.implementation_fingerprint,
            self.validator.validator_id,
            self.validator.validator_fingerprint,
            self.validator.payload_schema_id,
            self.validator.payload_schema_hash,
            (WorkOrderRefType.ARTIFACT,),
            65536,
            8,
        )
        self.dispatch_catalog = DispatchContractCatalog.create(
            self.phase32_catalog,
            (self.code_contract,),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _routable_task_and_route(self) -> tuple[str, str]:
        task = self.runtime.create_task(
            self.flow,
            "change code safely",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        route = self.capability_store.resolve_and_publish(
            task,
            self.phase32_catalog.catalog_id,
            self.phase32_policy.routing_policy_id,
        )
        return task, route.route_decision_id

    def _payload(self) -> dict[str, object]:
        return {
            "context_mode": "auto",
            "change_required": True,
            "seed_paths": ["src/example.py"],
        }

    def test_current_routable_task_constructs_exact_immutable_work_order(self) -> None:
        task, route_id = self._routable_task_and_route()
        artifact = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            "ART-11111111-1111-4111-8111-111111111111",
            "c" * 64,
            "seed_context",
        )
        before = self.runtime.get_task(task)
        payload = self._payload()
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            route_id,
            input_refs=(artifact,),
            payload=payload,
        )
        after = self.runtime.get_task(task)

        route = self.capability_store.require_current_route(route_id)
        self.assertTrue(work_order.work_order_id.startswith("WORKORD-"))
        self.assertEqual(work_order.task_id, task)
        self.assertEqual(work_order.task_revision, route.resolution.route_input.task_revision)
        self.assertEqual(
            work_order.task_content_hash,
            route.resolution.route_input.task_content_hash,
        )
        self.assertEqual(work_order.route_decision_id, route_id)
        self.assertEqual(work_order.route_decision_hash, route.content_hash)
        self.assertEqual(
            work_order.selected_adapter_id,
            "originforge.code.bounded-retry",
        )
        self.assertEqual(
            work_order.dispatch_contract_id,
            "code.bounded-retry@1",
        )
        self.assertEqual(work_order.payload, payload)
        self.assertEqual(len(work_order.payload_hash), 64)
        self.assertEqual(len(work_order.content_hash), 64)
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(self.runtime.list_runs(task), [])

        payload["context_mode"] = "manual"
        exposed = work_order.payload
        exposed["context_mode"] = "manual"
        self.assertEqual(work_order.payload["context_mode"], "auto")

    def test_api_does_not_accept_selected_adapter_or_contract_authority(self) -> None:
        parameters = inspect.signature(create_current_work_order).parameters
        self.assertNotIn("selected_adapter_id", parameters)
        self.assertNotIn("selected_adapter_fingerprint", parameters)
        self.assertNotIn("dispatch_contract_id", parameters)
        self.assertIn("route_decision_id", parameters)

    def test_stale_phase32_route_rejects_work_order_creation(self) -> None:
        task, route_id = self._routable_task_and_route()
        self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        with self.assertRaisesRegex(ProductionWorkOrderError, "unavailable or stale"):
            create_current_work_order(
                self.runtime,
                self.capability_store,
                self.dispatch_catalog,
                self.registry,
                route_id,
                payload=self._payload(),
            )

    def test_non_routable_route_rejects_work_order_creation(self) -> None:
        task = self.runtime.create_task(
            self.flow,
            "needs two distinct adapters",
            required_capabilities=("code.change", "runtime.observe"),
        )
        route = self.capability_store.resolve_and_publish(
            task,
            self.phase32_catalog.catalog_id,
            self.phase32_policy.routing_policy_id,
        )
        with self.assertRaisesRegex(ProductionWorkOrderError, "not ROUTABLE"):
            create_current_work_order(
                self.runtime,
                self.capability_store,
                self.dispatch_catalog,
                self.registry,
                route.route_decision_id,
                payload=self._payload(),
            )

    def test_dispatch_catalog_from_different_phase32_snapshot_is_rejected(self) -> None:
        _, route_id = self._routable_task_and_route()
        other_catalog = CapabilityCatalog.create(
            (self.code_capability, self.observe_capability),
            (self.code_adapter, self.observe_adapter),
        )
        other_dispatch = DispatchContractCatalog.create(
            other_catalog,
            (self.code_contract,),
        )
        with self.assertRaisesRegex(ProductionWorkOrderError, "not valid"):
            create_current_work_order(
                self.runtime,
                self.capability_store,
                other_dispatch,
                self.registry,
                route_id,
                payload=self._payload(),
            )

    def test_dispatch_catalog_without_selected_adapter_contract_fails_closed(self) -> None:
        _, route_id = self._routable_task_and_route()
        observe_validator = StaticObjectPayloadValidator(
            validator_id="validator.runtime.observe@1",
            payload_schema_id="schema.runtime.observe@1",
            fields=(
                PayloadFieldRule("mode", PayloadFieldKind.STRING, max_string_chars=16),
            ),
        )
        observe_contract = DispatchContract(
            "runtime.observe@1",
            "1",
            self.observe_adapter.adapter_id,
            self.observe_adapter.implementation_fingerprint,
            observe_validator.validator_id,
            observe_validator.validator_fingerprint,
            observe_validator.payload_schema_id,
            observe_validator.payload_schema_hash,
            (),
            1024,
            0,
        )
        other_dispatch = DispatchContractCatalog.create(
            self.phase32_catalog,
            (observe_contract,),
        )
        registry = DispatchContractValidatorRegistry((self.validator, observe_validator))
        with self.assertRaisesRegex(ProductionWorkOrderError, "no contract"):
            create_current_work_order(
                self.runtime,
                self.capability_store,
                other_dispatch,
                registry,
                route_id,
                payload=self._payload(),
            )

    def test_payload_and_input_refs_must_pass_exact_selected_contract(self) -> None:
        _, route_id = self._routable_task_and_route()
        bad_payload = self._payload()
        bad_payload["shell"] = "echo no"
        with self.assertRaisesRegex(ProductionWorkOrderError, "failed dispatch contract"):
            create_current_work_order(
                self.runtime,
                self.capability_store,
                self.dispatch_catalog,
                self.registry,
                route_id,
                payload=bad_payload,
            )

        verification = WorkOrderInputRef(
            WorkOrderRefType.VERIFICATION,
            "VERIFY-11111111-1111-4111-8111-111111111111",
            "d" * 64,
            "verification",
        )
        with self.assertRaisesRegex(ProductionWorkOrderError, "failed dispatch contract"):
            create_current_work_order(
                self.runtime,
                self.capability_store,
                self.dispatch_catalog,
                self.registry,
                route_id,
                input_refs=(verification,),
                payload=self._payload(),
            )

    def test_cross_project_capability_store_is_rejected(self) -> None:
        _, route_id = self._routable_task_and_route()
        with tempfile.TemporaryDirectory() as other_temp:
            other_runtime = OriginForgeRuntime(other_temp)
            other_runtime.initialize("other")
            other_store = ProductionCapabilityStore(other_runtime)
            with self.assertRaisesRegex(ProductionWorkOrderError, "different project root"):
                create_current_work_order(
                    self.runtime,
                    other_store,
                    self.dispatch_catalog,
                    self.registry,
                    route_id,
                    payload=self._payload(),
                )


if __name__ == "__main__":
    unittest.main()
