from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import TaskPreparationPolicyBinding
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import utc_now
from origin_forge.state import TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase39b-admission")
        self.goal = self.runtime.create_goal("prepare governed dependency-ready work")

        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.routing_policy, self.catalog)

        self.planning_input = freeze_governed_planning_input(
            self.runtime,
            self.goal,
            capability_store=self.capability_store,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        self.proposal = PlanProposal.create(
            planning_input=self.planning_input,
            summary="Materialize two roots and one dependent task.",
            steps=(
                PlanStep(
                    step_key="alpha",
                    objective="Implement alpha.",
                    acceptance_criteria=("Alpha is verified.",),
                    required_capabilities=("code.change",),
                ),
                PlanStep(
                    step_key="bravo",
                    objective="Implement bravo after alpha.",
                    acceptance_criteria=("Bravo is verified.",),
                    required_capabilities=("code.change",),
                    depends_on=("alpha",),
                ),
                PlanStep(
                    step_key="charlie",
                    objective="Implement independent charlie.",
                    acceptance_criteria=("Charlie is verified.",),
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
        self.task_by_step = {
            binding.step_key: binding.task_id
            for binding in self.materialization.task_bindings
        }

        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        work_orders = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(self.dispatch_catalog)

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

    def _insert_active_preparation(self, task_id: str, revision: int, task_hash: str) -> None:
        now = utc_now()
        with self.runtime.store.session() as conn:
            conn.execute(
                """INSERT INTO task_preparations(
                       preparation_id, project_id,
                       preparation_policy_id, preparation_policy_hash,
                       materialization_id, materialization_hash,
                       planning_input_id, planning_input_hash,
                       task_id, queued_task_revision, queued_task_hash,
                       stage, status, revision, created_at, updated_at, terminal_reason
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLAIMED', 'ACTIVE', 0, ?, ?, NULL)""",
                (
                    new_id(IdKind.TASK_PREPARATION),
                    self.runtime.project_id(),
                    self.policy.preparation_policy_id,
                    self.policy.content_hash,
                    self.materialization.materialization_id,
                    self.materialization.content_hash,
                    self.planning_input.planning_input_id,
                    self.planning_input.content_hash,
                    task_id,
                    revision,
                    task_hash,
                    now,
                    now,
                ),
            )

    def test_only_dependency_ready_queued_tasks_from_exact_plmat_are_candidates(self) -> None:
        result = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(result.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(result.dependency_exclusion_count, 1)
        self.assertEqual(result.not_queued_exclusion_count, 0)
        self.assertEqual(
            {candidate.task_id for candidate in result.candidates},
            {self.task_by_step["alpha"], self.task_by_step["charlie"]},
        )
        self.assertNotIn(self.task_by_step["bravo"], {c.task_id for c in result.candidates})
        self.assertEqual(
            [(candidate.created_at, candidate.task_id) for candidate in result.candidates],
            sorted(
                (candidate.created_at, candidate.task_id)
                for candidate in result.candidates
            ),
        )
        self.assertTrue(
            all(candidate.required_capabilities == ("code.change",) for candidate in result.candidates)
        )

    def test_active_preparation_excludes_task_without_falling_through_authority(self) -> None:
        baseline = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        candidate = baseline.candidates[0]
        self._insert_active_preparation(
            candidate.task_id,
            candidate.task_revision,
            candidate.task_content_hash,
        )
        result = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(result.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(result.active_preparation_exclusion_count, 1)
        self.assertNotIn(candidate.task_id, {value.task_id for value in result.candidates})
        self.assertEqual(result.candidate_count, baseline.candidate_count - 1)

    def test_non_queued_materialized_task_is_excluded(self) -> None:
        task_id = self.task_by_step["alpha"]
        self.runtime.transition_task(task_id, TaskStatus.READY, expected_revision=0)
        result = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(result.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(result.not_queued_exclusion_count, 1)
        self.assertNotIn(task_id, {candidate.task_id for candidate in result.candidates})

    def test_invalid_preppol_provenance_fails_closed_before_candidate_admission(self) -> None:
        forged = replace(self.policy, capability_routing_policy_hash="0" * 64)
        result = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            forged,
        )
        self.assertEqual(
            result.status,
            PreparationAdmissionStatus.INVALID_POLICY_PROVENANCE,
        )
        self.assertEqual(result.candidate_count, 0)

    def test_materialized_task_contract_drift_fails_closed(self) -> None:
        task_id = self.task_by_step["alpha"]
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE tasks SET required_capabilities_json = ? WHERE id = ?",
                ('["image.generate"]', task_id),
            )
        result = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        self.assertEqual(
            result.status,
            PreparationAdmissionStatus.INVALID_POLICY_PROVENANCE,
        )
        self.assertEqual(result.candidate_count, 0)

    def test_eligibility_inspection_does_not_mutate_tasks_or_create_preparations(self) -> None:
        before_tasks = {
            task_id: self.runtime.get_task(task_id)["status"]
            for task_id in self.task_by_step.values()
        }
        with self.runtime.store.session() as conn:
            before_preparations = conn.execute(
                "SELECT COUNT(*) FROM task_preparations"
            ).fetchone()[0]
        result = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            self.policy,
        )
        with self.runtime.store.session() as conn:
            after_preparations = conn.execute(
                "SELECT COUNT(*) FROM task_preparations"
            ).fetchone()[0]
        after_tasks = {
            task_id: self.runtime.get_task(task_id)["status"]
            for task_id in self.task_by_step.values()
        }
        self.assertEqual(result.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(before_preparations, after_preparations)
        self.assertEqual(before_tasks, after_tasks)
        self.assertTrue(all(value == TaskStatus.QUEUED.value for value in after_tasks.values()))


if __name__ == "__main__":
    unittest.main()
