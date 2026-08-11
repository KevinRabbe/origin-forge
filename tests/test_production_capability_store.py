from __future__ import annotations

import json
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
from origin_forge.production_capability_routing import CapabilityRouteOutcome
from origin_forge.production_capability_store import (
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


class ProductionCapabilityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("capability-store")
        goal = self.runtime.create_goal("route governed work")
        self.flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(
            self.flow,
            "change code",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        capability = ProductionCapability(
            capability_id="code.change",
            name="Code change",
            summary="bounded coding work",
            media_domain=CapabilityDomain.CODE,
            contract_version="1",
        )
        adapter = TrustedProductionAdapter(
            adapter_id="code.bounded",
            adapter_family="code",
            adapter_version="1",
            implementation_fingerprint="a" * 64,
            capability_ids=("code.change",),
            execution_effect=AdapterExecutionEffect.WORKSPACE_MUTATION,
            replay_class=AdapterReplayClass.REVISION_BOUND,
        )
        self.catalog = CapabilityCatalog.create((capability,), (adapter,))
        self.policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("code.bounded",),
            allowed_capability_ids=("code.change",),
        )
        self.store = ProductionCapabilityStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _publish_authority(self) -> None:
        self.store.publish_catalog(self.catalog)
        self.store.publish_policy(self.policy, self.catalog)

    def test_catalog_and_policy_round_trip_with_exact_hashes(self) -> None:
        self._publish_authority()
        loaded_catalog = self.store.load_catalog(self.catalog.catalog_id)
        loaded_policy = self.store.load_policy(self.policy.routing_policy_id)
        self.assertEqual(loaded_catalog.to_dict(), self.catalog.to_dict())
        self.assertEqual(loaded_catalog.content_hash, self.catalog.content_hash)
        self.assertEqual(loaded_policy.to_dict(), self.policy.to_dict())
        self.assertEqual(loaded_policy.content_hash, self.policy.content_hash)

    def test_immutable_objects_cannot_be_overwritten(self) -> None:
        self.store.publish_catalog(self.catalog)
        with self.assertRaisesRegex(ProductionCapabilityStoreError, "already exists"):
            self.store.publish_catalog(self.catalog)

    def test_policy_requires_exact_persisted_catalog(self) -> None:
        with self.assertRaisesRegex(ProductionCapabilityStoreError, "does not exist"):
            self.store.publish_policy(self.policy, self.catalog)

    def test_route_publication_recomputes_from_canonical_task_without_mutation(self) -> None:
        self._publish_authority()
        before = self.runtime.get_task(self.task)
        decision = self.store.resolve_and_publish(
            self.task,
            self.catalog.catalog_id,
            self.policy.routing_policy_id,
        )
        after = self.runtime.get_task(self.task)
        self.assertEqual(decision.resolution.outcome, CapabilityRouteOutcome.ROUTABLE)
        self.assertEqual(decision.resolution.selected_adapter_id, "code.bounded")
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(self.runtime.list_runs(self.task), [])
        loaded = self.store.load_route(decision.route_decision_id)
        self.assertEqual(loaded.to_dict(), decision.to_dict())
        self.assertEqual(loaded.content_hash, decision.content_hash)

    def test_current_route_rejects_task_revision_drift(self) -> None:
        self._publish_authority()
        decision = self.store.resolve_and_publish(
            self.task,
            self.catalog.catalog_id,
            self.policy.routing_policy_id,
        )
        self.store.require_current_route(decision.route_decision_id)
        self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        with self.assertRaisesRegex(ProductionCapabilityStoreError, "stale"):
            self.store.require_current_route(decision.route_decision_id)
        historical = self.store.load_route(decision.route_decision_id)
        self.assertEqual(historical.route_decision_id, decision.route_decision_id)

    def test_catalog_payload_tamper_is_detected(self) -> None:
        self.store.publish_catalog(self.catalog)
        path = (
            self.store.root
            / "catalogs"
            / f"{self.catalog.catalog_id}.json"
        )
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["capabilities"][0]["summary"] = "tampered"
        path.write_text(
            json.dumps(envelope, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProductionCapabilityStoreError, "content hash drifted"):
            self.store.load_catalog(self.catalog.catalog_id)

    def test_duplicate_json_keys_fail_closed(self) -> None:
        self.store.publish_catalog(self.catalog)
        path = (
            self.store.root
            / "catalogs"
            / f"{self.catalog.catalog_id}.json"
        )
        path.write_text(
            '{"schema_version":1,"schema_version":1,"object_type":"catalogs"}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProductionCapabilityStoreError, "duplicate JSON key"):
            self.store.load_catalog(self.catalog.catalog_id)

    def test_restart_reconstructs_persisted_authority_and_route(self) -> None:
        self._publish_authority()
        decision = self.store.resolve_and_publish(
            self.task,
            self.catalog.catalog_id,
            self.policy.routing_policy_id,
        )
        restarted_runtime = OriginForgeRuntime(self.tempdir.name)
        restarted = ProductionCapabilityStore(restarted_runtime)
        self.assertEqual(
            restarted.load_catalog(self.catalog.catalog_id).content_hash,
            self.catalog.content_hash,
        )
        self.assertEqual(
            restarted.load_policy(self.policy.routing_policy_id).content_hash,
            self.policy.content_hash,
        )
        current = restarted.require_current_route(decision.route_decision_id)
        self.assertEqual(current.to_dict(), decision.to_dict())

    def test_category_symlink_is_rejected(self) -> None:
        self.store._ensure_root()
        outside = self.runtime.project_root / "outside"
        outside.mkdir()
        policies = self.store.root / "policies"
        try:
            policies.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ProductionCapabilityStoreError, "may not be a symlink"):
            self.store.publish_policy(self.policy, self.catalog)


if __name__ == "__main__":
    unittest.main()
