from __future__ import annotations

import hashlib
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
from origin_forge.production_capability_read import (
    ProductionCapabilityReadError,
    read_capability_route,
)
from origin_forge.production_capability_store import (
    ProductionCapabilityStore,
    _canonical_bytes,
)
from origin_forge.runtime import OriginForgeRuntime


class ProductionCapabilityReadTamperTests(unittest.TestCase):
    def test_self_consistently_rehashed_forged_route_outcome_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("capability-route-tamper")
            goal = runtime.create_goal("route work")
            flow = runtime.create_flow(goal)
            task = runtime.create_task(
                flow,
                "change code",
                required_capabilities=("code.change",),
            )
            capability = ProductionCapability(
                "code.change",
                "Code change",
                "bounded coding",
                CapabilityDomain.CODE,
                "1",
            )
            adapter = TrustedProductionAdapter(
                "code.bounded",
                "code",
                "1",
                "a" * 64,
                ("code.change",),
                AdapterExecutionEffect.WORKSPACE_MUTATION,
                AdapterReplayClass.REVISION_BOUND,
            )
            catalog = CapabilityCatalog.create((capability,), (adapter,))
            policy = CapabilityRoutingPolicy.create(
                catalog,
                ordered_adapter_ids=("code.bounded",),
                allowed_capability_ids=("code.change",),
            )
            store = ProductionCapabilityStore(runtime)
            store.publish_catalog(catalog)
            store.publish_policy(policy, catalog)
            decision = store.resolve_and_publish(
                task,
                catalog.catalog_id,
                policy.routing_policy_id,
            )
            path = (
                store.root
                / "routes"
                / f"{decision.route_decision_id}.json"
            )
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["resolution"]["selected_adapter_fingerprint"] = "b" * 64
            envelope["content_hash"] = hashlib.sha256(
                _canonical_bytes(envelope["payload"])
            ).hexdigest()
            path.write_bytes(_canonical_bytes(envelope))

            with self.assertRaisesRegex(
                ProductionCapabilityReadError,
                "does not match frozen routing inputs",
            ):
                read_capability_route(runtime, decision.route_decision_id)


if __name__ == "__main__":
    unittest.main()
