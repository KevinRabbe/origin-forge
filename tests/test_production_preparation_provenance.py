from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import (
    PlanProposal,
    PlanStep,
    PlanningEvidenceRef,
    audit_plan,
)
from origin_forge.production_preparation_models import TaskPreparationPolicyBinding
from origin_forge.production_preparation_provenance import (
    ProductionPreparationProvenanceError,
    resolve_preparation_policy_provenance,
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


class PreparationProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase39b-provenance")
        self.goal = self.runtime.create_goal("prepare one governed code task")

        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.alternate_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.routing_policy, self.catalog)
        self.capability_store.publish_policy(self.alternate_policy, self.catalog)

        self.planning_input = freeze_governed_planning_input(
            self.runtime,
            self.goal,
            capability_store=self.capability_store,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.routing_policy.routing_policy_id,
            verified_state_refs=(
                PlanningEvidenceRef(
                    self.alternate_policy.routing_policy_id,
                    self.alternate_policy.content_hash,
                ),
            ),
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        self.proposal = PlanProposal.create(
            planning_input=self.planning_input,
            summary="Prepare one bounded code task.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement the bounded change.",
                    acceptance_criteria=("The requested change is verified.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        self.audit = audit_plan(self.planning_input, self.proposal)
        evidence = ProductionPlanningEvidenceStore(self.runtime)
        evidence.publish_input(self.planning_input)
        evidence.publish_proposal(self.proposal)
        evidence.publish_audit(self.audit)
        self.materialization = evidence.materialize(
            planning_input_id=self.planning_input.planning_input_id,
            proposal_id=self.proposal.proposal_id,
            audit_id=self.audit.audit_id,
        )

        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)

        self.policy = TaskPreparationPolicyBinding.create(
            project_id=self.runtime.project_id(),
            materialization_id=self.materialization.materialization_id,
            materialization_hash=self.materialization.content_hash,
            planning_input_id=self.planning_input.planning_input_id,
            planning_input_hash=self.planning_input.content_hash,
            capability_catalog_id=self.catalog.catalog_id,
            capability_catalog_hash=self.catalog.content_hash,
            capability_routing_policy_id=self.routing_policy.routing_policy_id,
            capability_routing_policy_hash=self.routing_policy.content_hash,
            dispatch_contract_catalog_id=self.dispatch_catalog.dispatch_catalog_id,
            dispatch_contract_catalog_hash=self.dispatch_catalog.content_hash,
            preparation_owner_id="originforge.preparation.work-order-planner@1",
            preparation_owner_fingerprint="f" * 64,
            planner_request_version="1",
            planner_contract_id="BoundedProductionWorkOrderPlanner.propose@1",
            model_strategy_roles=("CODER_STRONG",),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_exact_preppol_resolves_planning_capability_and_dispatch_provenance(self) -> None:
        result = resolve_preparation_policy_provenance(self.runtime, self.policy)
        self.assertEqual(result.materialization, self.materialization)
        self.assertEqual(result.planning_input, self.planning_input)
        self.assertEqual(result.capability_catalog, self.catalog)
        self.assertEqual(result.capability_routing_policy, self.routing_policy)
        self.assertEqual(result.dispatch_contract_catalog, self.dispatch_catalog)
        self.assertEqual(result.to_dict()["owner_currentness"], "DEFERRED_TO_PHASE_39C")

    def test_additional_cappol_evidence_does_not_create_ambiguity_when_preppol_is_exact(self) -> None:
        refs = {
            ref.ref_id: ref.content_hash
            for ref in self.planning_input.verified_state_refs
            if ref.ref_id.startswith("CAPPOL-")
        }
        self.assertEqual(
            refs,
            {
                self.routing_policy.routing_policy_id: self.routing_policy.content_hash,
                self.alternate_policy.routing_policy_id: self.alternate_policy.content_hash,
            },
        )
        result = resolve_preparation_policy_provenance(self.runtime, self.policy)
        self.assertEqual(
            result.capability_routing_policy.routing_policy_id,
            self.routing_policy.routing_policy_id,
        )

    def test_preppol_cannot_bind_policy_outside_frozen_planning_evidence(self) -> None:
        outside = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store.publish_policy(outside, self.catalog)
        forged = replace(
            self.policy,
            capability_routing_policy_id=outside.routing_policy_id,
            capability_routing_policy_hash=outside.content_hash,
        )
        with self.assertRaisesRegex(
            ProductionPreparationProvenanceError,
            "exactly one frozen PlanningInput evidence relation",
        ):
            resolve_preparation_policy_provenance(self.runtime, forged)

    def test_preppol_rejects_materialization_or_planning_hash_drift(self) -> None:
        with self.assertRaisesRegex(
            ProductionPreparationProvenanceError,
            "materialization relation drifted",
        ):
            resolve_preparation_policy_provenance(
                self.runtime,
                replace(self.policy, materialization_hash="0" * 64),
            )
        with self.assertRaisesRegex(
            ProductionPreparationProvenanceError,
            "materialization relation drifted|PlanningInput relation drifted",
        ):
            resolve_preparation_policy_provenance(
                self.runtime,
                replace(self.policy, planning_input_hash="1" * 64),
            )

    def test_preppol_rejects_capability_or_dispatch_catalog_hash_drift(self) -> None:
        with self.assertRaisesRegex(
            ProductionPreparationProvenanceError,
            "capability catalog relation drifted",
        ):
            resolve_preparation_policy_provenance(
                self.runtime,
                replace(self.policy, capability_catalog_hash="0" * 64),
            )
        with self.assertRaisesRegex(
            ProductionPreparationProvenanceError,
            "dispatch catalog relation drifted",
        ):
            resolve_preparation_policy_provenance(
                self.runtime,
                replace(self.policy, dispatch_contract_catalog_hash="0" * 64),
            )


if __name__ == "__main__":
    unittest.main()
