from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

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
from origin_forge.production_work_order_audit import (
    WorkOrderAuditStatus,
    WorkOrderCurrentnessStatus,
    audit_work_order_frozen,
    inspect_work_order_currentness,
)
from origin_forge.production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
)
from origin_forge.production_work_order_validators import (
    DispatchContractValidatorRegistry,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus
from origin_forge.task_dependencies import add_task_dependency
from origin_forge.task_readiness import DependencyReadinessStatus


class ProductionWorkOrderAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("work-order-audit")
        goal = self.runtime.create_goal("governed production")
        self.flow = self.runtime.create_flow(goal)

        capability = ProductionCapability(
            "code.change",
            "Code change",
            "bounded coding",
            CapabilityDomain.CODE,
            "1",
        )
        self.adapter = TrustedProductionAdapter(
            "originforge.code.bounded-retry",
            "originforge.code",
            "1",
            "a" * 64,
            ("code.change",),
            AdapterExecutionEffect.WORKSPACE_MUTATION,
            AdapterReplayClass.REVISION_BOUND,
        )
        self.phase32_catalog = CapabilityCatalog.create((capability,), (self.adapter,))
        self.phase32_policy = CapabilityRoutingPolicy.create(
            self.phase32_catalog,
            ordered_adapter_ids=(self.adapter.adapter_id,),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.phase32_catalog)
        self.capability_store.publish_policy(self.phase32_policy, self.phase32_catalog)

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
                PayloadFieldRule("change_required", PayloadFieldKind.BOOLEAN),
            ),
        )
        self.registry = DispatchContractValidatorRegistry((self.validator,))
        self.contract = DispatchContract(
            "code.bounded-retry@1",
            "1",
            self.adapter.adapter_id,
            self.adapter.implementation_fingerprint,
            self.validator.validator_id,
            self.validator.validator_fingerprint,
            self.validator.payload_schema_id,
            self.validator.payload_schema_hash,
            (),
            4096,
            0,
        )
        self.dispatch_catalog = DispatchContractCatalog.create(
            self.phase32_catalog,
            (self.contract,),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task_route_work_order(self):
        task = self.runtime.create_task(
            self.flow,
            "change code",
            required_capabilities=("code.change",),
        )
        route = self.capability_store.resolve_and_publish(
            task,
            self.phase32_catalog.catalog_id,
            self.phase32_policy.routing_policy_id,
        )
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            route.route_decision_id,
            payload={"context_mode": "auto", "change_required": True},
        )
        return task, route, work_order

    def test_frozen_audit_independently_passes_exact_work_order(self) -> None:
        task, route, work_order = self._task_route_work_order()
        before = self.runtime.get_task(task)
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
        )
        after = self.runtime.get_task(task)
        self.assertEqual(audit.status, WorkOrderAuditStatus.PASS)
        self.assertTrue(audit.work_order_audit_id.startswith("WORKAUD-"))
        self.assertEqual(audit.work_order_id, work_order.work_order_id)
        self.assertEqual(audit.work_order_hash, work_order.content_hash)
        self.assertEqual(audit.route_decision_id, route.route_decision_id)
        self.assertEqual(audit.validator_id, self.validator.validator_id)
        self.assertEqual(
            audit.validator_fingerprint,
            self.validator.validator_fingerprint,
        )
        self.assertEqual(audit.normalized_payload_hash, work_order.payload_hash)
        self.assertIsNone(audit.failure_reason)
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(self.runtime.list_runs(task), [])

    def test_forged_work_order_adapter_binding_fails_frozen_audit(self) -> None:
        _, _, work_order = self._task_route_work_order()
        forged = replace(
            work_order,
            selected_adapter_fingerprint="b" * 64,
        )
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            forged,
        )
        self.assertEqual(audit.status, WorkOrderAuditStatus.FAIL)
        self.assertIn("selected adapter", audit.failure_reason or "")

    def test_forged_route_hash_fails_frozen_audit(self) -> None:
        _, _, work_order = self._task_route_work_order()
        forged = replace(work_order, route_decision_hash="c" * 64)
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            forged,
        )
        self.assertEqual(audit.status, WorkOrderAuditStatus.FAIL)
        self.assertIn("route decision hash", audit.failure_reason or "")

    def test_historical_frozen_audit_remains_pass_after_task_revision_changes(self) -> None:
        task, _, work_order = self._task_route_work_order()
        before = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
        )
        self.assertEqual(before.status, WorkOrderAuditStatus.PASS)

        self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)

        historical = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
        )
        self.assertEqual(historical.status, WorkOrderAuditStatus.PASS)
        currentness = inspect_work_order_currentness(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
            before,
        )
        self.assertEqual(
            currentness.status,
            WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
        )
        self.assertIsNone(currentness.dependency_readiness_status)

    def test_currentness_reuses_phase31_waiting_and_ready_semantics(self) -> None:
        prerequisite = self.runtime.create_task(
            self.flow,
            "prepare prerequisite",
            required_capabilities=("code.change",),
        )
        task, _, work_order = self._task_route_work_order()
        add_task_dependency(self.runtime.store, task, prerequisite)
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
        )
        self.assertEqual(audit.status, WorkOrderAuditStatus.PASS)

        waiting = inspect_work_order_currentness(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
            audit,
        )
        self.assertEqual(
            waiting.status,
            WorkOrderCurrentnessStatus.WAITING_ON_DEPENDENCIES,
        )
        self.assertEqual(
            waiting.dependency_readiness_status,
            DependencyReadinessStatus.WAITING_ON_DEPENDENCIES,
        )

        revision = self.runtime.transition_task(
            prerequisite,
            TaskStatus.READY,
            expected_revision=0,
        )
        revision = self.runtime.transition_task(
            prerequisite,
            TaskStatus.RUNNING,
            expected_revision=revision,
        )
        self.runtime.record_verification(
            "TASK",
            prerequisite,
            verification_type="acceptance",
            verifier="work-order-audit-test",
            status="PASS",
        )
        self.runtime.transition_task(
            prerequisite,
            TaskStatus.SUCCEEDED,
            expected_revision=revision,
        )

        ready = inspect_work_order_currentness(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
            audit,
        )
        self.assertEqual(ready.status, WorkOrderCurrentnessStatus.CURRENT_READY)
        self.assertEqual(
            ready.dependency_readiness_status,
            DependencyReadinessStatus.READY,
        )

    def test_forged_pass_audit_is_recomputed_and_rejected_for_currentness(self) -> None:
        _, _, work_order = self._task_route_work_order()
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
        )
        self.assertEqual(audit.status, WorkOrderAuditStatus.PASS)
        forged = replace(audit, normalized_payload_hash="f" * 64)
        result = inspect_work_order_currentness(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            work_order,
            forged,
        )
        self.assertEqual(result.status, WorkOrderCurrentnessStatus.INVALID_AUDIT)
        self.assertIsNone(result.dependency_readiness_status)

    def test_failed_audit_is_never_current_dispatch_eligible(self) -> None:
        _, _, work_order = self._task_route_work_order()
        forged_work_order = replace(
            work_order,
            dispatch_contract_hash="e" * 64,
        )
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            forged_work_order,
        )
        self.assertEqual(audit.status, WorkOrderAuditStatus.FAIL)
        result = inspect_work_order_currentness(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            forged_work_order,
            audit,
        )
        self.assertEqual(result.status, WorkOrderCurrentnessStatus.INVALID_AUDIT)


if __name__ == "__main__":
    unittest.main()
