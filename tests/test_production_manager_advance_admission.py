from __future__ import annotations

import ast
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_manager_advance_admission as admission_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmissionStatus,
    inspect_manager_advance_admission_readonly,
)
from origin_forge.production_manager_advance_inventory import (
    ManagerAdvanceInventoryStatus,
    PreparationPolicyInventory,
    PreparationReceiptInventory,
    PreparationReceiptInventoryEntry,
)
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmission,
    ManagerDispatchAdmissionStatus,
    ManagerDispatchCandidate,
)
from origin_forge.production_preparation_admission import (
    MaterializationPreparationAdmission,
    PreparationAdmissionStatus,
    PreparationCandidate,
)
from origin_forge.production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    TaskPreparationPolicyBinding,
    TaskPreparationReceipt,
)
from origin_forge.production_preparation_status import (
    PreparationInspectionState,
    PreparationReceiptStatusProjection,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


_HASH = "a" * 64
_HASH_B = "b" * 64


class ManagerAdvanceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase40b-admission")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _policy(self) -> TaskPreparationPolicyBinding:
        return TaskPreparationPolicyBinding(
            preparation_policy_id=new_id(IdKind.TASK_PREPARATION_POLICY),
            project_id=new_id(IdKind.PROJECT),
            materialization_id=new_id(IdKind.PLAN_MATERIALIZATION),
            materialization_hash=_HASH,
            planning_input_id=new_id(IdKind.PLANNING_INPUT),
            planning_input_hash=_HASH,
            capability_catalog_id=new_id(IdKind.CAPABILITY_CATALOG),
            capability_catalog_hash=_HASH,
            capability_routing_policy_id=new_id(IdKind.CAPABILITY_ROUTING_POLICY),
            capability_routing_policy_hash=_HASH,
            dispatch_contract_catalog_id=new_id(IdKind.DISPATCH_CONTRACT_CATALOG),
            dispatch_contract_catalog_hash=_HASH,
            preparation_owner_id="originforge.preparation.owner.test",
            preparation_owner_fingerprint=_HASH,
            planner_request_version="phase40-test-v1",
            planner_contract_id="originforge.planner.contract.test",
            model_strategy_roles=("WORK_ORDER_PLANNER",),
        )

    def _prepare_candidate(
        self,
        task_id: str,
        created_at: str = "2026-01-01T00:00:00+00:00",
    ) -> PreparationCandidate:
        return PreparationCandidate(
            task_id=task_id,
            task_revision=0,
            task_content_hash=_HASH,
            created_at=created_at,
            step_key="step",
            required_capabilities=("code.change",),
        )

    def _dispatch_candidate(
        self,
        task_id: str,
        created_at: str,
    ) -> ManagerDispatchCandidate:
        return ManagerDispatchCandidate(
            task_id=task_id,
            task_revision=1,
            task_content_hash=_HASH,
            created_at=created_at,
            input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
            work_order_hash=_HASH,
            selected_adapter_id="originforge.code.bounded-retry",
            selected_adapter_fingerprint=_HASH,
            dispatch_contract_id="originforge.dispatch.contract.test",
            dispatch_contract_hash=_HASH,
            binder_id="originforge.dispatch.binder.test",
            binder_fingerprint=_HASH,
            request_type_id="originforge.request.test",
            request_schema_hash=_HASH,
            request_content_hash=_HASH,
        )

    def _receipt(
        self,
        task_id: str,
        policy: TaskPreparationPolicyBinding,
        *,
        stage: PreparationStage,
        status: PreparationStatus,
        created_at: str = "2026-01-01T00:00:00+00:00",
    ) -> TaskPreparationReceipt:
        rank = {
            PreparationStage.CLAIMED: 0,
            PreparationStage.ACTIVATED: 1,
            PreparationStage.ROUTED: 2,
            PreparationStage.PLANNER_STARTED: 3,
            PreparationStage.PLANNER_RETURNED: 4,
            PreparationStage.WORK_ORDER_AUDITED: 5,
            PreparationStage.BOUND: 6,
        }[stage]
        return TaskPreparationReceipt(
            preparation_id=new_id(IdKind.TASK_PREPARATION),
            project_id=policy.project_id,
            preparation_policy_id=policy.preparation_policy_id,
            preparation_policy_hash=policy.content_hash,
            materialization_id=policy.materialization_id,
            materialization_hash=policy.materialization_hash,
            planning_input_id=policy.planning_input_id,
            planning_input_hash=policy.planning_input_hash,
            task_id=task_id,
            queued_task_revision=0,
            queued_task_hash=_HASH,
            ready_task_revision=1 if rank >= 1 else None,
            ready_task_hash=_HASH if rank >= 1 else None,
            route_decision_id=(new_id(IdKind.CAPABILITY_ROUTE_DECISION) if rank >= 2 else None),
            route_decision_hash=_HASH if rank >= 2 else None,
            planner_dependency_plan_hash=_HASH if rank >= 3 else None,
            planner_run_id=new_id(IdKind.RUN) if rank >= 4 else None,
            work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER) if rank >= 4 else None,
            work_order_hash=_HASH if rank >= 4 else None,
            work_order_audit_id=new_id(IdKind.WORK_ORDER_AUDIT) if rank >= 5 else None,
            work_order_audit_hash=_HASH if rank >= 5 else None,
            input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE) if rank >= 6 else None,
            input_resolution_hash=_HASH if rank >= 6 else None,
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING) if rank >= 6 else None,
            dispatch_binding_hash=_HASH if rank >= 6 else None,
            binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT) if rank >= 6 else None,
            binding_audit_hash=_HASH if rank >= 6 else None,
            stage=stage,
            status=status,
            revision=rank,
            created_at=created_at,
            updated_at=created_at,
            terminal_reason=(
                "terminal test evidence"
                if status in {PreparationStatus.FAILED_PRE_PLANNER, PreparationStatus.INTERRUPTED}
                else None
            ),
        )

    def _entry(
        self,
        receipt: TaskPreparationReceipt,
        task_created_at: str,
    ) -> PreparationReceiptInventoryEntry:
        status = TaskStatus.QUEUED if receipt.stage is PreparationStage.CLAIMED else TaskStatus.READY
        revision = receipt.queued_task_revision if receipt.stage is PreparationStage.CLAIMED else receipt.ready_task_revision
        assert revision is not None
        return PreparationReceiptInventoryEntry(
            receipt=receipt,
            task_created_at=task_created_at,
            current_task_status=status,
            current_task_revision=revision,
        )

    def _projection(
        self,
        receipt: TaskPreparationReceipt,
        *,
        state: PreparationInspectionState,
        current: bool = True,
        detail: str | None = None,
    ) -> PreparationReceiptStatusProjection:
        return PreparationReceiptStatusProjection(
            state=state,
            preparation_id=receipt.preparation_id,
            preparation_policy_id=receipt.preparation_policy_id,
            preparation_policy_hash=receipt.preparation_policy_hash,
            task_id=receipt.task_id,
            receipt_status=receipt.status,
            stage=receipt.stage,
            revision=receipt.revision,
            current=current,
            route_decision_id=receipt.route_decision_id,
            work_order_id=receipt.work_order_id,
            work_order_audit_id=receipt.work_order_audit_id,
            input_resolution_id=receipt.input_resolution_id,
            dispatch_binding_id=receipt.dispatch_binding_id,
            binding_audit_id=receipt.binding_audit_id,
            detail=detail,
        )

    def _dispatch_admission(
        self,
        candidates: tuple[ManagerDispatchCandidate, ...] = (),
    ) -> ManagerDispatchAdmission:
        return ManagerDispatchAdmission(
            status=ManagerDispatchAdmissionStatus.COMPLETE,
            candidates=candidates,
            scanned_audit_count=len(candidates),
            current_chain_count=len(candidates),
            active_claim_exclusion_count=0,
            not_ready_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )

    def _policy_admission(
        self,
        policy: TaskPreparationPolicyBinding,
        candidates: tuple[PreparationCandidate, ...],
    ) -> MaterializationPreparationAdmission:
        return MaterializationPreparationAdmission(
            status=PreparationAdmissionStatus.COMPLETE,
            preparation_policy_id=policy.preparation_policy_id,
            materialization_id=policy.materialization_id,
            candidates=candidates,
            not_queued_exclusion_count=0,
            dependency_exclusion_count=0,
            active_preparation_exclusion_count=0,
            phase38_admissible_exclusion_count=0,
            detail=None,
        )

    def _run(
        self,
        *,
        policies: tuple[TaskPreparationPolicyBinding, ...] = (),
        receipt_entries: tuple[PreparationReceiptInventoryEntry, ...] = (),
        projections: dict[str, PreparationReceiptStatusProjection] | None = None,
        dispatch_candidates: tuple[ManagerDispatchCandidate, ...] = (),
        policy_candidates: dict[str, tuple[PreparationCandidate, ...]] | None = None,
        active_claim: bool = False,
    ):
        projections = projections or {}
        policy_candidates = policy_candidates or {}
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    admission_module,
                    "inspect_preparation_policy_inventory_readonly",
                    return_value=PreparationPolicyInventory(
                        ManagerAdvanceInventoryStatus.COMPLETE,
                        policies,
                        len(policies),
                        None,
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    admission_module,
                    "inspect_preparation_receipt_inventory_readonly",
                    return_value=PreparationReceiptInventory(
                        ManagerAdvanceInventoryStatus.COMPLETE,
                        receipt_entries,
                        len(receipt_entries),
                        None,
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    admission_module,
                    "inspect_manager_dispatch_admission_readonly",
                    return_value=self._dispatch_admission(dispatch_candidates),
                )
            )
            stack.enter_context(
                patch.object(
                    admission_module,
                    "inspect_preparation_receipt_status_readonly",
                    side_effect=lambda runtime, preparation_id: projections[preparation_id],
                )
            )
            stack.enter_context(
                patch.object(
                    admission_module,
                    "inspect_materialization_preparation_eligibility_readonly",
                    side_effect=lambda runtime, policy: self._policy_admission(
                        policy,
                        policy_candidates.get(policy.preparation_policy_id, ()),
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    admission_module,
                    "_active_claim_exists_readonly",
                    return_value=active_claim,
                )
            )
            return inspect_manager_advance_admission_readonly(self.runtime)

    def test_cross_state_candidates_are_ordered_only_by_task_age_and_id(self) -> None:
        policy = self._policy()
        older_task = new_id(IdKind.TASK)
        newer_task = new_id(IdKind.TASK)
        receipt = self._receipt(
            older_task,
            policy,
            stage=PreparationStage.CLAIMED,
            status=PreparationStatus.ACTIVE,
        )
        entry = self._entry(receipt, "2026-01-01T00:00:00+00:00")
        dispatch = self._dispatch_candidate(newer_task, "2026-01-02T00:00:00+00:00")

        result = self._run(
            receipt_entries=(entry,),
            projections={
                receipt.preparation_id: self._projection(
                    receipt,
                    state=PreparationInspectionState.ACTIVE_PRE_PLANNER,
                )
            },
            dispatch_candidates=(dispatch,),
        )

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(
            tuple(candidate.action_kind for candidate in result.candidates),
            (ManagerAdvanceActionKind.RECOVER_PREPARATION, ManagerAdvanceActionKind.DISPATCH),
        )
        self.assertEqual(result.recover_preparation_count, 1)
        self.assertEqual(result.recovery_required_count, 0)
        self.assertEqual(result.candidates[0].task_id, older_task)

    def test_active_preparation_and_dispatch_same_task_fail_closed(self) -> None:
        policy = self._policy()
        task_id = new_id(IdKind.TASK)
        receipt = self._receipt(
            task_id,
            policy,
            stage=PreparationStage.CLAIMED,
            status=PreparationStatus.ACTIVE,
        )
        entry = self._entry(receipt, "2026-01-01T00:00:00+00:00")
        dispatch = self._dispatch_candidate(task_id, entry.task_created_at)

        result = self._run(
            receipt_entries=(entry,),
            projections={
                receipt.preparation_id: self._projection(
                    receipt,
                    state=PreparationInspectionState.ACTIVE_PRE_PLANNER,
                )
            },
            dispatch_candidates=(dispatch,),
        )

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.INVALID_STATE)
        self.assertEqual(result.candidates, ())

    def test_planner_started_maps_to_existing_evidence_finalization_only(self) -> None:
        policy = self._policy()
        task_id = new_id(IdKind.TASK)
        receipt = self._receipt(
            task_id,
            policy,
            stage=PreparationStage.PLANNER_STARTED,
            status=PreparationStatus.ACTIVE,
        )
        entry = self._entry(receipt, "2026-01-01T00:00:00+00:00")

        result = self._run(
            receipt_entries=(entry,),
            projections={
                receipt.preparation_id: self._projection(
                    receipt,
                    state=PreparationInspectionState.PLANNER_RECOVERY_REQUIRED,
                )
            },
        )

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.candidates[0].action_kind, ManagerAdvanceActionKind.FINALIZE_WORK_ORDER)
        self.assertEqual(result.candidates[0].preparation_id, receipt.preparation_id)

    def test_semantically_equivalent_preparation_policies_collapse(self) -> None:
        first = self._policy()
        second = replace(
            first,
            preparation_policy_id=new_id(IdKind.TASK_PREPARATION_POLICY),
        )
        task_id = new_id(IdKind.TASK)
        candidate = self._prepare_candidate(task_id)

        result = self._run(
            policies=(first, second),
            policy_candidates={
                first.preparation_policy_id: (candidate,),
                second.preparation_policy_id: (candidate,),
            },
        )

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(result.prepare_count, 1)
        selected = result.candidates[0]
        self.assertEqual(selected.action_kind, ManagerAdvanceActionKind.PREPARE)
        self.assertEqual(
            selected.preparation_policy.preparation_policy_id,
            min(first.preparation_policy_id, second.preparation_policy_id),
        )

    def test_semantically_different_preparation_policies_are_ambiguous(self) -> None:
        first = self._policy()
        second = replace(
            first,
            preparation_policy_id=new_id(IdKind.TASK_PREPARATION_POLICY),
            planner_contract_id="originforge.planner.contract.other",
        )
        task_id = new_id(IdKind.TASK)
        candidate = self._prepare_candidate(task_id)

        result = self._run(
            policies=(first, second),
            policy_candidates={
                first.preparation_policy_id: (candidate,),
                second.preparation_policy_id: (candidate,),
            },
        )

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.ambiguous_task_ids, (task_id,))

    def test_current_terminal_receipt_suppresses_implicit_prepare_retry(self) -> None:
        policy = self._policy()
        task_id = new_id(IdKind.TASK)
        receipt = self._receipt(
            task_id,
            policy,
            stage=PreparationStage.CLAIMED,
            status=PreparationStatus.FAILED_PRE_PLANNER,
        )
        entry = self._entry(receipt, "2026-01-01T00:00:00+00:00")
        candidate = self._prepare_candidate(task_id, entry.task_created_at)

        result = self._run(
            policies=(policy,),
            receipt_entries=(entry,),
            projections={
                receipt.preparation_id: self._projection(
                    receipt,
                    state=PreparationInspectionState.FAILED_PRE_PLANNER,
                    current=True,
                )
            },
            policy_candidates={policy.preparation_policy_id: (candidate,)},
        )

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.terminal_retry_suppression_count, 1)

    def test_stale_terminal_history_does_not_gain_retry_blocking_authority(self) -> None:
        policy = self._policy()
        task_id = new_id(IdKind.TASK)
        receipt = self._receipt(
            task_id,
            policy,
            stage=PreparationStage.CLAIMED,
            status=PreparationStatus.FAILED_PRE_PLANNER,
        )
        entry = self._entry(receipt, "2026-01-01T00:00:00+00:00")
        candidate = self._prepare_candidate(task_id, entry.task_created_at)

        result = self._run(
            policies=(policy,),
            receipt_entries=(entry,),
            projections={
                receipt.preparation_id: self._projection(
                    receipt,
                    state=PreparationInspectionState.FAILED_PRE_PLANNER,
                    current=False,
                    detail="historical revision",
                )
            },
            policy_candidates={policy.preparation_policy_id: (candidate,)},
        )

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(result.prepare_count, 1)
        self.assertEqual(result.candidates[0].action_kind, ManagerAdvanceActionKind.PREPARE)

    def test_candidate_limit_fails_closed_without_partial_admission(self) -> None:
        first = self._dispatch_candidate(new_id(IdKind.TASK), "2026-01-01T00:00:00+00:00")
        second = self._dispatch_candidate(new_id(IdKind.TASK), "2026-01-02T00:00:00+00:00")
        with patch.object(admission_module, "_MAX_MANAGER_ADVANCE_CANDIDATES", 1):
            result = self._run(dispatch_candidates=(first, second))

        self.assertEqual(result.status, ManagerAdvanceAdmissionStatus.LIMIT_EXCEEDED)
        self.assertEqual(result.candidates, ())

    def test_admission_source_has_no_selection_or_mutation_authority(self) -> None:
        source = Path(admission_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_modules = {
            "production_manager_dispatch_tick",
            "production_preparation_tick",
            "production_preparation_receipts",
            "production_preparation_work_order_finalize",
            "production_preparation_phase34_finalize",
            "production_task_activation",
            "production_dispatch_claims",
            "production_dispatch_invocation",
            "scheduled_model_adapter",
        }
        forbidden_calls = {
            "dispatch_manager_tick",
            "prepare_materialization_tick",
            "acquire_preparation_receipt",
            "activate_dependency_ready_task",
            "finalize_preparation_work_order_audit",
            "finalize_preparation_phase34",
            "acquire_dispatch_claim",
            "dispatch_claim_once",
            "generate",
            "propose",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                self.assertNotIn(node.module.rsplit(".", 1)[-1], forbidden_modules)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr
                else:
                    continue
                self.assertNotIn(call_name, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
