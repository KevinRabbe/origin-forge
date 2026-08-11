from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace

from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import content_hash
from origin_forge.production_work_order_store import (
    ProductionWorkOrderStore,
    ProductionWorkOrderStoreError,
)
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime


class ProductionWorkOrderStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("work-order-store")
        goal = self.runtime.create_goal("store one governed work order")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(
            flow,
            "change code",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        self.phase32 = build_builtin_capability_catalog()
        self.policy = CapabilityRoutingPolicy.create(
            self.phase32,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.phase32)
        self.capability_store.publish_policy(self.policy, self.phase32)
        self.route = self.capability_store.resolve_and_publish(
            self.task,
            self.phase32.catalog_id,
            self.policy.routing_policy_id,
        )
        self.registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.phase32)
        self.store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.registry,
        )
        self.store.publish_dispatch_catalog(self.dispatch_catalog)
        self.work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            self.route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
            },
        )
        self.audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            self.work_order,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _publish_chain(self) -> None:
        self.store.publish_work_order(self.work_order)
        self.store.publish_audit(self.audit)

    def test_complete_chain_round_trips_and_reconstructs_after_restart(self) -> None:
        self._publish_chain()
        self.assertEqual(
            self.store.load_dispatch_catalog(self.dispatch_catalog.dispatch_catalog_id),
            self.dispatch_catalog,
        )
        self.assertEqual(
            self.store.load_work_order(self.work_order.work_order_id),
            self.work_order,
        )
        self.assertEqual(self.store.load_audit(self.audit.work_order_audit_id), self.audit)

        restarted_runtime = OriginForgeRuntime(self.tempdir.name)
        restarted_capabilities = ProductionCapabilityStore(restarted_runtime)
        restarted = ProductionWorkOrderStore(
            restarted_runtime,
            restarted_capabilities,
            build_builtin_dispatch_validator_registry(),
        )
        self.assertEqual(
            restarted.load_dispatch_catalog(self.dispatch_catalog.dispatch_catalog_id).content_hash,
            self.dispatch_catalog.content_hash,
        )
        self.assertEqual(
            restarted.load_work_order(self.work_order.work_order_id).content_hash,
            self.work_order.content_hash,
        )
        self.assertEqual(
            restarted.load_audit(self.audit.work_order_audit_id).content_hash,
            self.audit.content_hash,
        )

    def test_every_category_is_no_overwrite(self) -> None:
        with self.assertRaisesRegex(ProductionWorkOrderStoreError, "already exists"):
            self.store.publish_dispatch_catalog(self.dispatch_catalog)
        self.store.publish_work_order(self.work_order)
        with self.assertRaisesRegex(ProductionWorkOrderStoreError, "already exists"):
            self.store.publish_work_order(self.work_order)
        self.store.publish_audit(self.audit)
        with self.assertRaisesRegex(ProductionWorkOrderStoreError, "already exists"):
            self.store.publish_audit(self.audit)

    def test_forged_audit_cannot_enter_trusted_store(self) -> None:
        self.store.publish_work_order(self.work_order)
        forged = replace(self.audit, normalized_payload_hash="a" * 64)
        with self.assertRaisesRegex(ProductionWorkOrderStoreError, "does not independently recompute"):
            self.store.publish_audit(forged)
        audit_dir = self.store.root / "audits"
        self.assertFalse(audit_dir.exists() and tuple(audit_dir.glob("*.json")))

    def test_self_consistent_work_order_payload_tamper_is_rejected_on_load(self) -> None:
        self.store.publish_work_order(self.work_order)
        path = self.store.root / "work-orders" / f"{self.work_order.work_order_id}.json"
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["payload"] = {
            "context_mode": "manual",
            "selected_paths": [],
            "context_seed_paths": [],
            "structural_context": False,
            "semantic_context": False,
        }
        envelope["content_hash"] = content_hash(envelope["payload"])
        path.write_text(
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProductionWorkOrderStoreError, "frozen revalidation"):
            self.store.load_work_order(self.work_order.work_order_id)

    def test_second_store_instance_cannot_overwrite_same_dispatch_catalog(self) -> None:
        second_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        with self.assertRaisesRegex(ProductionWorkOrderStoreError, "already exists"):
            second_store.publish_dispatch_catalog(self.dispatch_catalog)

    def test_symlinked_category_is_rejected(self) -> None:
        self.store._ensure_root()
        outside = self.runtime.project_root / "outside-work-orders"
        outside.mkdir()
        work_orders = self.store.root / "work-orders"
        try:
            work_orders.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ProductionWorkOrderStoreError, "may not be a symlink"):
            self.store.publish_work_order(self.work_order)


if __name__ == "__main__":
    unittest.main()
