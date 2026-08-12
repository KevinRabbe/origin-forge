from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    create_preparation_policy_binding,
    publish_preparation_policy,
    read_preparation_policy,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationPolicyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase39c-policy-store")
        goal = self.runtime.create_goal("prepare one immutable policy")
        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(self.catalog)
        capability_store.publish_policy(self.routing_policy, self.catalog)
        self.planning_input = freeze_governed_planning_input(
            self.runtime,
            goal,
            capability_store=capability_store,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=self.planning_input,
            summary="One code task.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement code.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        audit = audit_plan(self.planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(self.runtime)
        planning.publish_input(self.planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(audit)
        self.materialization = planning.materialize(
            planning_input_id=self.planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        work_orders = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(self.dispatch_catalog)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _create(self):
        return create_preparation_policy_binding(
            self.runtime,
            materialization_id=self.materialization.materialization_id,
            capability_catalog_id=self.catalog.catalog_id,
            capability_routing_policy_id=self.routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=self.dispatch_catalog.dispatch_catalog_id,
        )

    def test_builder_exposes_only_exact_evidence_ids_not_owner_or_model_authority(self) -> None:
        signature = inspect.signature(create_preparation_policy_binding)
        self.assertEqual(
            tuple(signature.parameters),
            (
                "runtime",
                "materialization_id",
                "capability_catalog_id",
                "capability_routing_policy_id",
                "dispatch_contract_catalog_id",
            ),
        )
        forbidden = {
            "owner",
            "owner_fingerprint",
            "planner_contract",
            "model_role",
            "model_profile",
            "runtime_provider",
            "runtime_id",
            "endpoint",
            "loader",
            "sandbox",
            "workspace",
            "task_id",
        }
        self.assertTrue(forbidden.isdisjoint(signature.parameters))
        policy = self._create()
        self.assertEqual(
            policy.preparation_owner_id,
            "originforge.preparation.work-order-planner@1",
        )
        self.assertEqual(policy.model_strategy_roles, ("CODER_STRONG",))

    def test_publish_once_and_read_revalidate_exact_policy(self) -> None:
        policy = self._create()
        path = publish_preparation_policy(self.runtime, policy)
        self.assertTrue(path.is_file())
        self.assertEqual(read_preparation_policy(self.runtime, policy.preparation_policy_id), policy)
        with self.assertRaisesRegex(ProductionPreparationPolicyStoreError, "already exists"):
            publish_preparation_policy(self.runtime, policy)

    def test_forged_owner_cannot_be_published(self) -> None:
        policy = replace(self._create(), preparation_owner_fingerprint="0" * 64)
        with self.assertRaisesRegex(
            ProductionPreparationPolicyStoreError,
            "full authority validation",
        ):
            publish_preparation_policy(self.runtime, policy)
        store = self.runtime.state_dir / "production-preparation" / "policies"
        if store.exists():
            self.assertEqual(list(store.iterdir()), [])

    def test_tampered_stored_policy_fails_closed(self) -> None:
        policy = self._create()
        path = publish_preparation_policy(self.runtime, policy)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["preparation_owner_fingerprint"] = "0" * 64
        path.write_text(
            json.dumps(
                envelope,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ProductionPreparationPolicyStoreError):
            read_preparation_policy(self.runtime, policy.preparation_policy_id)

    def test_read_missing_policy_does_not_create_store_directories(self) -> None:
        other_root = self.root / "other"
        other_runtime = OriginForgeRuntime(other_root)
        other_runtime.initialize("phase39c-empty-store")
        store = other_runtime.state_dir / "production-preparation"
        self.assertFalse(store.exists())
        with self.assertRaisesRegex(
            ProductionPreparationPolicyStoreError,
            "store does not exist",
        ):
            read_preparation_policy(
                other_runtime,
                "PREPPOL-00000000-0000-4000-8000-000000000000",
            )
        self.assertFalse(store.exists())

    def test_builder_rejects_policy_outside_planning_input_evidence(self) -> None:
        outside = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_policy(outside, self.catalog)
        with self.assertRaisesRegex(
            ProductionPreparationPolicyStoreError,
            "exact current evidence",
        ):
            create_preparation_policy_binding(
                self.runtime,
                materialization_id=self.materialization.materialization_id,
                capability_catalog_id=self.catalog.catalog_id,
                capability_routing_policy_id=outside.routing_policy_id,
                dispatch_contract_catalog_id=self.dispatch_catalog.dispatch_catalog_id,
            )


if __name__ == "__main__":
    unittest.main()
