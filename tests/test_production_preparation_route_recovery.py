from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_route_recovery as route_recovery_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_activation import (
    activate_and_checkpoint_preparation,
)
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_receipts import (
    acquire_preparation_receipt,
    read_preparation_receipt,
)
from origin_forge.production_preparation_recovery import (
    PreparationRecoveryState,
    inspect_preparation_recovery_readonly,
)
from origin_forge.production_preparation_route_recovery import (
    PreparationRouteRecoveryError,
    recover_and_checkpoint_preparation_route,
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


class PreparationRouteRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase41c-route-recovery")
        goal = self.runtime.create_goal("recover one exact Phase-32 route")

        catalog = build_builtin_capability_catalog()
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(catalog)
        self.capability_store.publish_policy(routing_policy, catalog)

        planning_input = freeze_governed_planning_input(
            self.runtime,
            goal,
            capability_store=self.capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Materialize one Task for route recovery.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement one bounded route recovery fixture.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(self.runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        self.task_id = materialization.task_bindings[0].task_id

        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        ).publish_dispatch_catalog(dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=catalog.catalog_id,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(self.runtime, self.policy)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _activated_receipt(self):
        admission = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        claimed = acquire_preparation_receipt(
            self.runtime,
            self.policy,
            admission.candidates[0],
        )
        return activate_and_checkpoint_preparation(
            self.runtime,
            claimed.preparation_id,
            claimed.revision,
        )

    def _routes_dir(self) -> Path:
        return self.runtime.state_dir / "production-capabilities" / "routes"

    def _route_files(self) -> tuple[Path, ...]:
        directory = self._routes_dir()
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("*.json")))

    def _publish_current_route(self):
        return self.capability_store.resolve_and_publish(
            self.task_id,
            self.policy.capability_catalog_id,
            self.policy.capability_routing_policy_id,
        )

    def test_no_existing_route_publishes_one_and_checkpoints_routed(self) -> None:
        activated = self._activated_receipt()
        self.assertEqual(self._route_files(), ())

        routed = recover_and_checkpoint_preparation_route(
            self.runtime,
            activated.preparation_id,
            activated.revision,
        )

        self.assertEqual(routed.status, PreparationStatus.ACTIVE)
        self.assertEqual(routed.stage, PreparationStage.ROUTED)
        self.assertEqual(routed.revision, activated.revision + 1)
        self.assertIsNotNone(routed.route_decision_id)
        self.assertIsNotNone(routed.route_decision_hash)
        self.assertEqual(len(self._route_files()), 1)
        projection = inspect_preparation_recovery_readonly(
            self.runtime,
            routed.preparation_id,
        )
        self.assertEqual(projection.state, PreparationRecoveryState.RESUMABLE_ROUTED)

    def test_crash_after_route_publication_reuses_exact_existing_route(self) -> None:
        activated = self._activated_receipt()
        published = self._publish_current_route()
        self.assertEqual(len(self._route_files()), 1)
        durable_before = read_preparation_receipt(
            self.runtime,
            activated.preparation_id,
        )
        self.assertEqual(durable_before.stage, PreparationStage.ACTIVATED)

        routed = recover_and_checkpoint_preparation_route(
            self.runtime,
            activated.preparation_id,
            activated.revision,
        )

        self.assertEqual(routed.stage, PreparationStage.ROUTED)
        self.assertEqual(routed.route_decision_id, published.route_decision_id)
        self.assertEqual(len(self._route_files()), 1)

    def test_semantically_identical_duplicate_routes_collapse_by_route_id(self) -> None:
        activated = self._activated_receipt()
        first = self._publish_current_route()
        second = self._publish_current_route()
        self.assertNotEqual(first.route_decision_id, second.route_decision_id)
        expected_id = min(first.route_decision_id, second.route_decision_id)
        self.assertEqual(len(self._route_files()), 2)

        routed = recover_and_checkpoint_preparation_route(
            self.runtime,
            activated.preparation_id,
            activated.revision,
        )

        self.assertEqual(routed.route_decision_id, expected_id)
        self.assertEqual(len(self._route_files()), 2)

    def test_non_route_entry_fails_closed_without_publication_or_checkpoint(self) -> None:
        activated = self._activated_receipt()
        directory = self._routes_dir()
        directory.mkdir(exist_ok=True)
        (directory / "unexpected.txt").write_text("not route evidence", encoding="utf-8")

        with self.assertRaisesRegex(
            PreparationRouteRecoveryError,
            "non-route evidence entry",
        ):
            recover_and_checkpoint_preparation_route(
                self.runtime,
                activated.preparation_id,
                activated.revision,
            )

        durable = read_preparation_receipt(self.runtime, activated.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.ACTIVATED)
        self.assertEqual(durable.revision, activated.revision)
        self.assertEqual(self._route_files(), ())

    def test_malformed_existing_route_fails_closed(self) -> None:
        activated = self._activated_receipt()
        published = self._publish_current_route()
        path = self._routes_dir() / f"{published.route_decision_id}.json"
        path.write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(
            PreparationRouteRecoveryError,
            "malformed or invalid",
        ):
            recover_and_checkpoint_preparation_route(
                self.runtime,
                activated.preparation_id,
                activated.revision,
            )

        durable = read_preparation_receipt(self.runtime, activated.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.ACTIVATED)
        self.assertEqual(durable.revision, activated.revision)

    def test_route_object_limit_fails_closed_before_adopting_any_candidate(self) -> None:
        activated = self._activated_receipt()
        self._publish_current_route()
        self._publish_current_route()
        self.assertEqual(len(self._route_files()), 2)

        with patch.object(route_recovery_module, "_MAX_ROUTE_OBJECTS", 1):
            with self.assertRaisesRegex(
                PreparationRouteRecoveryError,
                "object-count limit exceeded",
            ):
                recover_and_checkpoint_preparation_route(
                    self.runtime,
                    activated.preparation_id,
                    activated.revision,
                )

        durable = read_preparation_receipt(self.runtime, activated.preparation_id)
        self.assertEqual(durable.stage, PreparationStage.ACTIVATED)
        self.assertEqual(durable.revision, activated.revision)
        self.assertEqual(len(self._route_files()), 2)

    def test_stale_expected_revision_cannot_reuse_or_publish_route(self) -> None:
        activated = self._activated_receipt()

        with self.assertRaisesRegex(
            PreparationRouteRecoveryError,
            "changed after immutable recovery classification",
        ):
            recover_and_checkpoint_preparation_route(
                self.runtime,
                activated.preparation_id,
                activated.revision + 1,
            )

        self.assertEqual(self._route_files(), ())
        self.assertEqual(
            read_preparation_receipt(self.runtime, activated.preparation_id).stage,
            PreparationStage.ACTIVATED,
        )

    def test_public_route_recovery_surface_contains_no_model_or_dispatch_authority(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(recover_and_checkpoint_preparation_route).parameters),
            ("runtime", "preparation_id", "expected_revision"),
        )
        source = inspect.getsource(route_recovery_module)
        for forbidden in (
            "BoundedProductionWorkOrderPlanner",
            ".propose(",
            "dispatch_claim",
            "dispatch_manager",
            "advance_production_manager_once",
            "checkpoint_preparation_planner_started",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
