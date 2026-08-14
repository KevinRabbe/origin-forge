from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_goal_bootstrap_models import (
    GoalBootstrapReceipt,
    GoalBootstrapStage,
    GoalBootstrapStatus,
    ProductionGoalBootstrapModelError,
)


PROJECT = "PROJECT-00000000-0000-4000-8000-000000000001"
GOAL = "GOAL-00000000-0000-4000-8000-000000000002"
GOALBOOT = "GOALBOOT-00000000-0000-4000-8000-000000000003"
CAPCAT = "CAPCAT-00000000-0000-4000-8000-000000000004"
CAPPOL = "CAPPOL-00000000-0000-4000-8000-000000000005"
DISPCAT = "DISPCAT-00000000-0000-4000-8000-000000000006"
PLINPUT = "PLINPUT-00000000-0000-4000-8000-000000000007"
RUN = "RUN-00000000-0000-4000-8000-000000000008"
PLPROP = "PLPROP-00000000-0000-4000-8000-000000000009"
PLAUD = "PLAUD-00000000-0000-4000-8000-000000000010"
PLMAT = "PLMAT-00000000-0000-4000-8000-000000000011"
PREPPOL = "PREPPOL-00000000-0000-4000-8000-000000000012"
NOW = "2026-08-14T18:00:00Z"


def receipt(
    stage: GoalBootstrapStage,
    status: GoalBootstrapStatus = GoalBootstrapStatus.ACTIVE,
) -> GoalBootstrapReceipt:
    rank = list(GoalBootstrapStage).index(stage)
    return GoalBootstrapReceipt(
        bootstrap_id=GOALBOOT,
        project_id=PROJECT,
        goal_id=GOAL,
        goal_revision=3,
        goal_content_hash="1" * 64,
        bootstrap_owner_id="originforge.bootstrap.goal-planner@1",
        bootstrap_owner_fingerprint="2" * 64,
        bootstrap_contract_version="1",
        capability_catalog_id=CAPCAT if rank >= 1 else None,
        capability_catalog_hash="3" * 64 if rank >= 1 else None,
        capability_routing_policy_id=CAPPOL if rank >= 1 else None,
        capability_routing_policy_hash="4" * 64 if rank >= 1 else None,
        dispatch_contract_catalog_id=DISPCAT if rank >= 1 else None,
        dispatch_contract_catalog_hash="5" * 64 if rank >= 1 else None,
        planning_input_id=PLINPUT if rank >= 2 else None,
        planning_input_hash="6" * 64 if rank >= 2 else None,
        planner_dependency_plan_hash="7" * 64 if rank >= 3 else None,
        planner_run_id=RUN if rank >= 4 else None,
        plan_proposal_id=PLPROP if rank >= 4 else None,
        plan_proposal_hash="8" * 64 if rank >= 4 else None,
        plan_audit_id=PLAUD if rank >= 5 else None,
        plan_audit_hash="9" * 64 if rank >= 5 else None,
        materialization_id=PLMAT if rank >= 6 else None,
        materialization_hash="a" * 64 if rank >= 6 else None,
        preparation_policy_id=PREPPOL if rank >= 7 else None,
        preparation_policy_hash="b" * 64 if rank >= 7 else None,
        stage=stage,
        status=status,
        revision=rank,
        created_at=NOW,
        updated_at=NOW,
        terminal_reason=None,
    )


class GoalBootstrapReceiptModelTests(unittest.TestCase):
    def test_goalboot_id_is_infrastructure_owned(self) -> None:
        value = new_id(IdKind.GOAL_BOOTSTRAP)
        self.assertTrue(validate_id(value, IdKind.GOAL_BOOTSTRAP))
        self.assertTrue(value.startswith("GOALBOOT-"))

    def test_every_active_checkpoint_shape_is_valid(self) -> None:
        for stage in GoalBootstrapStage:
            with self.subTest(stage=stage):
                value = receipt(stage)
                self.assertTrue(value.is_active)
                self.assertEqual(value.stage, stage)

    def test_frozen_authority_is_goal_revision_and_owner_exact(self) -> None:
        value = receipt(GoalBootstrapStage.PREPPOL_PUBLISHED)
        self.assertEqual(
            set(value.frozen_authority_dict()),
            {
                "bootstrap_id",
                "project_id",
                "goal_id",
                "goal_revision",
                "goal_content_hash",
                "bootstrap_owner_id",
                "bootstrap_owner_fingerprint",
                "bootstrap_contract_version",
            },
        )

    def test_stage_rejects_missing_required_or_future_checkpoint(self) -> None:
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.AUTHORITY_PUBLISHED),
                dispatch_contract_catalog_id=None,
                dispatch_contract_catalog_hash=None,
            )
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.CLAIMED),
                planning_input_id=PLINPUT,
                planning_input_hash="6" * 64,
            )
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.PLANNER_RETURNED),
                plan_proposal_id=None,
                plan_proposal_hash=None,
            )

    def test_checkpoint_id_hash_pairs_are_atomic(self) -> None:
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.PREPPOL_PUBLISHED),
                preparation_policy_hash=None,
            )
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.PLAN_AUDITED),
                plan_audit_id=None,
            )

    def test_ready_requires_preppol_and_no_terminal_reason(self) -> None:
        ready = replace(
            receipt(GoalBootstrapStage.PREPPOL_PUBLISHED),
            status=GoalBootstrapStatus.READY,
        )
        self.assertEqual(ready.status, GoalBootstrapStatus.READY)
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.MATERIALIZED),
                status=GoalBootstrapStatus.READY,
            )
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(ready, terminal_reason="not allowed")

    def test_failed_pre_planner_cannot_cross_model_boundary(self) -> None:
        failed = replace(
            receipt(GoalBootstrapStage.PLANNING_INPUT_PUBLISHED),
            status=GoalBootstrapStatus.FAILED_PRE_PLANNER,
            terminal_reason="deterministic authority failure",
        )
        self.assertEqual(failed.status, GoalBootstrapStatus.FAILED_PRE_PLANNER)
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.PLANNER_STARTED),
                status=GoalBootstrapStatus.FAILED_PRE_PLANNER,
                terminal_reason="too late",
            )

    def test_planner_started_active_receipt_requires_recovery(self) -> None:
        self.assertTrue(
            receipt(GoalBootstrapStage.PLANNER_STARTED).requires_planner_recovery
        )
        self.assertFalse(
            receipt(GoalBootstrapStage.PLANNING_INPUT_PUBLISHED).requires_planner_recovery
        )
        self.assertFalse(
            receipt(GoalBootstrapStage.PLANNER_RETURNED).requires_planner_recovery
        )

    def test_receipt_rejects_invalid_owner_fingerprint(self) -> None:
        with self.assertRaises(ProductionGoalBootstrapModelError):
            replace(
                receipt(GoalBootstrapStage.CLAIMED),
                bootstrap_owner_fingerprint="not-a-digest",
            )


if __name__ == "__main__":
    unittest.main()
