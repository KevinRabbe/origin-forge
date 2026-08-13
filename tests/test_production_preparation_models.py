from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    ProductionPreparationModelError,
    TaskPreparationPolicyBinding,
    TaskPreparationReceipt,
)


PROJECT = "PROJECT-00000000-0000-4000-8000-000000000001"
PLMAT = "PLMAT-00000000-0000-4000-8000-000000000002"
PLINPUT = "PLINPUT-00000000-0000-4000-8000-000000000003"
CAPCAT = "CAPCAT-00000000-0000-4000-8000-000000000004"
CAPPOL = "CAPPOL-00000000-0000-4000-8000-000000000005"
DISPCAT = "DISPCAT-00000000-0000-4000-8000-000000000006"
PREPPOL = "PREPPOL-00000000-0000-4000-8000-000000000007"
PREP = "PREP-00000000-0000-4000-8000-000000000008"
TASK = "TASK-00000000-0000-4000-8000-000000000009"
CAPROUTE = "CAPROUTE-00000000-0000-4000-8000-000000000010"
RUN = "RUN-00000000-0000-4000-8000-000000000011"
WORKORD = "WORKORD-00000000-0000-4000-8000-000000000012"
WORKAUD = "WORKAUD-00000000-0000-4000-8000-000000000013"
INRES = "INRES-00000000-0000-4000-8000-000000000014"
DISPBIND = "DISPBIND-00000000-0000-4000-8000-000000000015"
BINDAUD = "BINDAUD-00000000-0000-4000-8000-000000000016"
NOW = "2026-08-12T21:00:00Z"


def policy() -> TaskPreparationPolicyBinding:
    return TaskPreparationPolicyBinding(
        preparation_policy_id=PREPPOL,
        project_id=PROJECT,
        materialization_id=PLMAT,
        materialization_hash="a" * 64,
        planning_input_id=PLINPUT,
        planning_input_hash="b" * 64,
        capability_catalog_id=CAPCAT,
        capability_catalog_hash="c" * 64,
        capability_routing_policy_id=CAPPOL,
        capability_routing_policy_hash="d" * 64,
        dispatch_contract_catalog_id=DISPCAT,
        dispatch_contract_catalog_hash="e" * 64,
        preparation_owner_id="originforge.preparation.work-order-planner@1",
        preparation_owner_fingerprint="f" * 64,
        planner_request_version="1",
        planner_contract_id="BoundedProductionWorkOrderPlanner.propose@1",
        model_strategy_roles=("CODER_STRONG",),
    )


def receipt(stage: PreparationStage, status: PreparationStatus = PreparationStatus.ACTIVE) -> TaskPreparationReceipt:
    rank = list(PreparationStage).index(stage)
    return TaskPreparationReceipt(
        preparation_id=PREP,
        project_id=PROJECT,
        preparation_policy_id=PREPPOL,
        preparation_policy_hash="1" * 64,
        materialization_id=PLMAT,
        materialization_hash="2" * 64,
        planning_input_id=PLINPUT,
        planning_input_hash="3" * 64,
        task_id=TASK,
        queued_task_revision=0,
        queued_task_hash="4" * 64,
        ready_task_revision=1 if rank >= 1 else None,
        ready_task_hash="5" * 64 if rank >= 1 else None,
        route_decision_id=CAPROUTE if rank >= 2 else None,
        route_decision_hash="6" * 64 if rank >= 2 else None,
        planner_dependency_plan_hash="7" * 64 if rank >= 3 else None,
        planner_run_id=RUN if rank >= 4 else None,
        work_order_id=WORKORD if rank >= 4 else None,
        work_order_hash="8" * 64 if rank >= 4 else None,
        work_order_audit_id=WORKAUD if rank >= 5 else None,
        work_order_audit_hash="9" * 64 if rank >= 5 else None,
        input_resolution_id=INRES if rank >= 6 else None,
        input_resolution_hash="a" * 64 if rank >= 6 else None,
        dispatch_binding_id=DISPBIND if rank >= 6 else None,
        dispatch_binding_hash="b" * 64 if rank >= 6 else None,
        binding_audit_id=BINDAUD if rank >= 6 else None,
        binding_audit_hash="c" * 64 if rank >= 6 else None,
        stage=stage,
        status=status,
        revision=rank,
        created_at=NOW,
        updated_at=NOW,
        terminal_reason=None,
    )


class PreparationPolicyModelTests(unittest.TestCase):
    def test_policy_hash_is_stable_and_authority_sensitive(self) -> None:
        value = policy()
        self.assertEqual(value.content_hash, value.content_hash)
        self.assertEqual(len(value.content_hash), 64)
        changed = replace(value, capability_routing_policy_hash="0" * 64)
        self.assertNotEqual(value.content_hash, changed.content_hash)
        self.assertEqual(value.to_dict()["model_strategy_roles"], ["CODER_STRONG"])

    def test_policy_rejects_untyped_identity_and_duplicate_roles(self) -> None:
        with self.assertRaises(ProductionPreparationModelError):
            replace(policy(), preparation_policy_id=PREP)
        with self.assertRaises(ProductionPreparationModelError):
            replace(policy(), model_strategy_roles=("CODER_STRONG", "CODER_STRONG"))


class PreparationReceiptModelTests(unittest.TestCase):
    def test_every_active_checkpoint_shape_is_valid(self) -> None:
        for stage in PreparationStage:
            with self.subTest(stage=stage):
                value = receipt(stage)
                self.assertTrue(value.is_active)
                self.assertEqual(value.stage, stage)

    def test_frozen_authority_excludes_later_checkpoint_fields(self) -> None:
        value = receipt(PreparationStage.BOUND)
        self.assertEqual(
            set(value.frozen_authority_dict()),
            {
                "preparation_id",
                "project_id",
                "preparation_policy_id",
                "preparation_policy_hash",
                "materialization_id",
                "materialization_hash",
                "planning_input_id",
                "planning_input_hash",
                "task_id",
                "queued_task_revision",
                "queued_task_hash",
            },
        )

    def test_planner_started_active_receipt_is_recovery_required(self) -> None:
        self.assertTrue(
            receipt(PreparationStage.PLANNER_STARTED).requires_planner_recovery
        )
        self.assertFalse(receipt(PreparationStage.ROUTED).requires_planner_recovery)
        self.assertFalse(receipt(PreparationStage.PLANNER_RETURNED).requires_planner_recovery)

    def test_stage_rejects_missing_required_or_future_checkpoint(self) -> None:
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.ACTIVATED),
                ready_task_revision=None,
                ready_task_hash=None,
            )
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.ROUTED),
                planner_dependency_plan_hash="d" * 64,
            )
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.PLANNER_RETURNED),
                work_order_id=None,
                work_order_hash=None,
            )

    def test_checkpoint_id_hash_pairs_are_atomic(self) -> None:
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.BOUND),
                binding_audit_hash=None,
            )
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.ACTIVATED),
                ready_task_hash=None,
            )

    def test_ready_requires_bound_and_no_terminal_reason(self) -> None:
        ready = replace(
            receipt(PreparationStage.BOUND),
            status=PreparationStatus.READY,
        )
        self.assertEqual(ready.status, PreparationStatus.READY)
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.WORK_ORDER_AUDITED),
                status=PreparationStatus.READY,
            )
        with self.assertRaises(ProductionPreparationModelError):
            replace(ready, terminal_reason="not allowed")

    def test_failed_pre_planner_cannot_cross_model_boundary(self) -> None:
        failed = replace(
            receipt(PreparationStage.ROUTED),
            status=PreparationStatus.FAILED_PRE_PLANNER,
            terminal_reason="deterministic routing preparation failure",
        )
        self.assertEqual(failed.status, PreparationStatus.FAILED_PRE_PLANNER)
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.PLANNER_STARTED),
                status=PreparationStatus.FAILED_PRE_PLANNER,
                terminal_reason="too late",
            )

    def test_interruption_requires_bounded_reason(self) -> None:
        interrupted = replace(
            receipt(PreparationStage.PLANNER_STARTED),
            status=PreparationStatus.INTERRUPTED,
            terminal_reason="operator-reviewed interruption",
        )
        self.assertEqual(interrupted.status, PreparationStatus.INTERRUPTED)
        with self.assertRaises(ProductionPreparationModelError):
            replace(
                receipt(PreparationStage.CLAIMED),
                status=PreparationStatus.INTERRUPTED,
                terminal_reason=None,
            )


if __name__ == "__main__":
    unittest.main()