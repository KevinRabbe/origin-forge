from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import patch

import origin_forge.production_preparation_tick as tick_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_preparation_admission import (
    MaterializationPreparationAdmission,
    PreparationAdmissionStatus,
    PreparationCandidate,
)
from origin_forge.production_preparation_models import TaskPreparationPolicyBinding
from origin_forge.production_preparation_receipts import PreparationReceiptError
from origin_forge.production_preparation_tick import (
    PreparationTickResult,
    PreparationTickStatus,
    _prepare_selected_candidate_once,
    prepare_materialization_tick,
)
from origin_forge.runtime import OriginForgeRuntime


H = "a" * 64
NOW = "2026-08-13T01:00:00Z"


class ProductionPreparationPinnedCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = OriginForgeRuntime("/tmp/origin-forge-phase40d2-pinned-preparation")
        self.policy = TaskPreparationPolicyBinding(
            preparation_policy_id=new_id(IdKind.TASK_PREPARATION_POLICY),
            project_id=new_id(IdKind.PROJECT),
            materialization_id=new_id(IdKind.PLAN_MATERIALIZATION),
            materialization_hash=H,
            planning_input_id=new_id(IdKind.PLANNING_INPUT),
            planning_input_hash=H,
            capability_catalog_id=new_id(IdKind.CAPABILITY_CATALOG),
            capability_catalog_hash=H,
            capability_routing_policy_id=new_id(IdKind.CAPABILITY_ROUTING_POLICY),
            capability_routing_policy_hash=H,
            dispatch_contract_catalog_id=new_id(IdKind.DISPATCH_CONTRACT_CATALOG),
            dispatch_contract_catalog_hash=H,
            preparation_owner_id="originforge.preparation.owner.test",
            preparation_owner_fingerprint=H,
            planner_request_version="phase40-test-v1",
            planner_contract_id="originforge.planner.contract.test",
            model_strategy_roles=("WORK_ORDER_PLANNER",),
        )
        self.candidate = PreparationCandidate(
            task_id=new_id(IdKind.TASK),
            task_revision=0,
            task_content_hash=H,
            created_at=NOW,
            step_key="step",
            required_capabilities=("code.change",),
        )

    def _admission(self) -> MaterializationPreparationAdmission:
        return MaterializationPreparationAdmission(
            status=PreparationAdmissionStatus.COMPLETE,
            preparation_policy_id=self.policy.preparation_policy_id,
            materialization_id=self.policy.materialization_id,
            candidates=(self.candidate,),
            not_queued_exclusion_count=0,
            dependency_exclusion_count=0,
            active_preparation_exclusion_count=0,
            phase38_admissible_exclusion_count=0,
            detail=None,
        )

    def test_pinned_helper_never_readmits_or_reselects(self) -> None:
        with (
            patch.object(
                tick_module,
                "inspect_materialization_preparation_eligibility_readonly",
                side_effect=AssertionError("pinned helper re-admitted"),
            ),
            patch.object(
                tick_module,
                "select_preparation_candidate",
                side_effect=AssertionError("pinned helper reselected"),
            ),
            patch.object(
                tick_module,
                "acquire_preparation_receipt",
                side_effect=PreparationReceiptError("selected candidate lost race"),
            ) as acquire,
        ):
            result = _prepare_selected_candidate_once(
                self.runtime,
                self.policy,
                self.candidate,
            )

        self.assertEqual(result.status, PreparationTickStatus.PREPARATION_NOT_ACQUIRED)
        self.assertEqual(result.task_id, self.candidate.task_id)
        self.assertEqual(result.preparation_policy_id, self.policy.preparation_policy_id)
        acquire.assert_called_once_with(self.runtime, self.policy, self.candidate)

    def test_public_tick_delegates_exact_selected_policy_and_candidate(self) -> None:
        projected = PreparationTickResult(
            PreparationTickStatus.PREPARATION_NOT_ACQUIRED,
            self.policy.preparation_policy_id,
            None,
            self.candidate.task_id,
            None,
            None,
            "simulated pinned result",
        )
        with (
            patch.object(
                tick_module,
                "read_preparation_policy",
                return_value=self.policy,
            ),
            patch.object(
                tick_module,
                "inspect_materialization_preparation_eligibility_readonly",
                return_value=self._admission(),
            ),
            patch.object(
                tick_module,
                "_prepare_selected_candidate_once",
                return_value=projected,
            ) as pinned,
        ):
            result = prepare_materialization_tick(
                self.runtime,
                self.policy.preparation_policy_id,
            )

        self.assertIs(result, projected)
        pinned.assert_called_once_with(self.runtime, self.policy, self.candidate)

    def test_pinned_helper_source_delegates_shared_planner_once_and_never_plans_directly(self) -> None:
        source = inspect.getsource(_prepare_selected_candidate_once)
        tree = ast.parse(source)
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        } | {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("inspect_materialization_preparation_eligibility_readonly", calls)
        self.assertNotIn("select_preparation_candidate", calls)
        self.assertEqual(calls.count("resume_routed_preparation_planner_once") if hasattr(calls, "count") else int("resume_routed_preparation_planner_once" in calls), 1)
        self.assertEqual(
            sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "resume_routed_preparation_planner_once"
            ),
            1,
        )
        self.assertEqual(
            sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "propose"
            ),
            0,
        )
        self.assertNotIn("checkpoint_preparation_planner_started", calls)
        self.assertNotIn("checkpoint_preparation_planner_returned", calls)
        self.assertFalse(any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree)))
        self.assertEqual(
            tuple(inspect.signature(_prepare_selected_candidate_once).parameters),
            ("runtime", "policy", "candidate"),
        )
        self.assertEqual(
            tuple(inspect.signature(prepare_materialization_tick).parameters),
            ("runtime", "preparation_policy_id"),
        )


if __name__ == "__main__":
    unittest.main()
