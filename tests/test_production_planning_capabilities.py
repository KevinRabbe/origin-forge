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
from origin_forge.production_planning_capabilities import (
    GovernedPlanningCapabilityError,
    freeze_governed_planning_input,
)
from origin_forge.production_planning_models import PlanningEvidenceRef
from origin_forge.runtime import OriginForgeRuntime


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64


class GovernedPlanningCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("planning-capabilities")
        self.goal = self.runtime.create_goal("produce a governed feature")
        code = ProductionCapability(
            "code.change",
            "Code change",
            "bounded code mutation",
            CapabilityDomain.CODE,
            "1",
        )
        image = ProductionCapability(
            "image.generate",
            "Image generation",
            "bounded image generation",
            CapabilityDomain.IMAGE,
            "1",
        )
        code_adapter = TrustedProductionAdapter(
            "code.bounded",
            "code",
            "1",
            _HASH_A,
            ("code.change",),
            AdapterExecutionEffect.WORKSPACE_MUTATION,
            AdapterReplayClass.REVISION_BOUND,
        )
        image_adapter = TrustedProductionAdapter(
            "image.generator",
            "image",
            "1",
            _HASH_B,
            ("image.generate",),
            AdapterExecutionEffect.MEDIA_WORKSPACE_MUTATION,
            AdapterReplayClass.RUNTIME_BOUND,
        )
        self.catalog = CapabilityCatalog.create(
            (code, image),
            (code_adapter, image_adapter),
        )
        self.policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("code.bounded",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.policy, self.catalog)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _freeze(self, **overrides):
        arguments = {
            "capability_store": self.capability_store,
            "catalog_id": self.catalog.catalog_id,
            "routing_policy_id": self.policy.routing_policy_id,
            "project_intelligence_hash": _HASH_C,
            "model_policy_hash": _HASH_D,
            "resource_policy_hash": _HASH_A,
        }
        arguments.update(overrides)
        return freeze_governed_planning_input(
            self.runtime,
            self.goal,
            **arguments,
        )

    def test_governed_freeze_derives_catalog_hash_and_policy_capability_subset(self) -> None:
        planning_input = self._freeze()
        self.assertEqual(
            planning_input.capability_catalog_hash,
            self.catalog.content_hash,
        )
        self.assertEqual(planning_input.capability_ids, ("code.change",))
        refs = {value.ref_id: value.content_hash for value in planning_input.verified_state_refs}
        self.assertEqual(refs[self.catalog.catalog_id], self.catalog.content_hash)
        self.assertEqual(refs[self.policy.routing_policy_id], self.policy.content_hash)
        self.assertNotIn("image.generate", planning_input.capability_ids)

    def test_existing_verified_refs_are_preserved_beside_governed_authority(self) -> None:
        existing = PlanningEvidenceRef("VERIFY-example", _HASH_B)
        planning_input = self._freeze(verified_state_refs=(existing,))
        refs = {value.ref_id for value in planning_input.verified_state_refs}
        self.assertEqual(
            refs,
            {"VERIFY-example", self.catalog.catalog_id, self.policy.routing_policy_id},
        )

    def test_caller_cannot_prebind_catalog_or_policy_refs(self) -> None:
        forged = PlanningEvidenceRef(self.catalog.catalog_id, self.catalog.content_hash)
        with self.assertRaisesRegex(GovernedPlanningCapabilityError, "may not pre-bind"):
            self._freeze(verified_state_refs=(forged,))

    def test_governed_api_has_no_caller_capability_hash_or_id_arguments(self) -> None:
        parameters = inspect.signature(freeze_governed_planning_input).parameters
        self.assertNotIn("capability_catalog_hash", parameters)
        self.assertNotIn("capability_ids", parameters)
        self.assertIn("catalog_id", parameters)
        self.assertIn("routing_policy_id", parameters)

    def test_missing_persisted_policy_fails_closed(self) -> None:
        other_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("code.bounded",),
            allowed_capability_ids=("code.change",),
        )
        with self.assertRaisesRegex(
            GovernedPlanningCapabilityError,
            "could not be loaded",
        ):
            self._freeze(routing_policy_id=other_policy.routing_policy_id)

    def test_capability_store_from_another_project_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as other_temp:
            other_runtime = OriginForgeRuntime(other_temp)
            other_runtime.initialize("other")
            other_store = ProductionCapabilityStore(other_runtime)
            with self.assertRaisesRegex(
                GovernedPlanningCapabilityError,
                "different project root",
            ):
                self._freeze(capability_store=other_store)


if __name__ == "__main__":
    unittest.main()
