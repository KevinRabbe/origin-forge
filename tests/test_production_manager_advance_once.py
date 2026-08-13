from __future__ import annotations

import ast
import inspect
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_manager_advance_once as advance_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmission,
    ManagerAdvanceAdmissionStatus,
    ManagerAdvanceCandidate,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)
from origin_forge.production_manager_dispatch_admission import ManagerDispatchCandidate
from origin_forge.production_manager_dispatch_tick import (
    ManagerDispatchTickDetail,
    ManagerDispatchTickResult,
    ManagerDispatchTickStatus,
)
from origin_forge.production_preparation_admission import PreparationCandidate
from origin_forge.production_preparation_models import (
    PreparationStage,
    TaskPreparationPolicyBinding,
)
from origin_forge.production_preparation_phase34_finalize import PreparationPhase34FinalizeStatus
from origin_forge.production_preparation_tick import PreparationTickResult, PreparationTickStatus
from origin_forge.production_preparation_work_order_finalize import PreparationWorkOrderFinalizeStatus
from origin_forge.runtime import OriginForgeRuntime


H = "a" * 64
OLD = "2026-01-01T00:00:00Z"
NEW = "2026-01-02T00:00:00Z"


class ManagerAdvanceOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = OriginForgeRuntime("/tmp/origin-forge-phase40e-manager-once")

    def _policy(self) -> TaskPreparationPolicyBinding:
        return TaskPreparationPolicyBinding(
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

    def _prepare(self, task_id: str, created_at: str) -> ManagerAdvanceCandidate:
        policy = self._policy()
        candidate = PreparationCandidate(
            task_id=task_id,
            task_revision=0,
            task_content_hash=H,
            created_at=created_at,
            step_key="step",
            required_capabilities=("code.change",),
        )
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.PREPARE,
            task_id,
            created_at,
            preparation_policy=policy,
            preparation_candidate=candidate,
        )

    def _dispatch(self, task_id: str, created_at: str) -> ManagerAdvanceCandidate:
        candidate = ManagerDispatchCandidate(
            task_id=task_id,
            task_revision=1,
            task_content_hash=H,
            created_at=created_at,
            input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
            work_order_hash=H,
            selected_adapter_id="originforge.code.bounded-retry",
            selected_adapter_fingerprint=H,
            dispatch_contract_id="code.bounded-retry@1",
            dispatch_contract_hash=H,
            binder_id="binder.code.bounded-retry@1",
            binder_fingerprint=H,
            request_type_id="BoundedRetryPolicy.drive@1",
            request_schema_hash=H,
            request_content_hash=H,
        )
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.DISPATCH,
            task_id,
            created_at,
            dispatch_candidate=candidate,
        )

    def _recovery(self, task_id: str, created_at: str) -> ManagerAdvanceCandidate:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVERY_REQUIRED,
            task_id,
            created_at,
            preparation_id=new_id(IdKind.TASK_PREPARATION),
            preparation_stage=PreparationStage.CLAIMED,
            detail="explicit recovery required",
        )

    def _finalize_work_order(self, task_id: str, created_at: str) -> ManagerAdvanceCandidate:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.FINALIZE_WORK_ORDER,
            task_id,
            created_at,
            preparation_id=new_id(IdKind.TASK_PREPARATION),
            preparation_stage=PreparationStage.PLANNER_RETURNED,
        )

    def _finalize_phase34(self, task_id: str, created_at: str) -> ManagerAdvanceCandidate:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.FINALIZE_PHASE34,
            task_id,
            created_at,
            preparation_id=new_id(IdKind.TASK_PREPARATION),
            preparation_stage=PreparationStage.WORK_ORDER_AUDITED,
        )

    def _admission(self, *candidates: ManagerAdvanceCandidate) -> ManagerAdvanceAdmission:
        counts = {kind: 0 for kind in ManagerAdvanceActionKind}
        for candidate in candidates:
            counts[candidate.action_kind] += 1
        return ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.COMPLETE,
            candidates=tuple(candidates),
            dispatch_count=counts[ManagerAdvanceActionKind.DISPATCH],
            finalize_work_order_count=counts[ManagerAdvanceActionKind.FINALIZE_WORK_ORDER],
            finalize_phase34_count=counts[ManagerAdvanceActionKind.FINALIZE_PHASE34],
            prepare_count=counts[ManagerAdvanceActionKind.PREPARE],
            recovery_required_count=counts[ManagerAdvanceActionKind.RECOVERY_REQUIRED],
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )

    def _assert_no_action_calls(self):
        return (
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                side_effect=AssertionError("dispatch action attempted"),
            ),
            patch.object(
                advance_module,
                "_prepare_selected_candidate_once",
                side_effect=AssertionError("preparation action attempted"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_work_order_audit",
                side_effect=AssertionError("WorkOrder finalizer attempted"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_phase34",
                side_effect=AssertionError("Phase34 finalizer attempted"),
            ),
        )

    def test_no_actionable_work_performs_zero_action(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    advance_module,
                    "inspect_manager_advance_admission_readonly",
                    return_value=self._admission(),
                )
            )
            for context_manager in self._assert_no_action_calls():
                stack.enter_context(context_manager)
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK)
        self.assertIsNone(result.action_kind)

    def test_selected_recovery_required_performs_zero_action_and_stops(self) -> None:
        candidate = self._recovery(new_id(IdKind.TASK), OLD)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    advance_module,
                    "inspect_manager_advance_admission_readonly",
                    return_value=self._admission(candidate),
                )
            )
            for context_manager in self._assert_no_action_calls():
                stack.enter_context(context_manager)
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.task_id, candidate.task_id)
        self.assertEqual(result.detail, candidate.detail)

    def test_prepare_race_never_falls_through_to_newer_dispatch_candidate(self) -> None:
        first = self._prepare(new_id(IdKind.TASK), OLD)
        second = self._dispatch(new_id(IdKind.TASK), NEW)
        lower = PreparationTickResult(
            PreparationTickStatus.PREPARATION_NOT_ACQUIRED,
            first.preparation_policy.preparation_policy_id,
            None,
            first.task_id,
            None,
            None,
            "lost PREP race",
        )
        with (
            patch.object(
                advance_module,
                "inspect_manager_advance_admission_readonly",
                return_value=self._admission(first, second),
            ),
            patch.object(
                advance_module,
                "_prepare_selected_candidate_once",
                return_value=lower,
            ) as prepare,
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                side_effect=AssertionError("fell through to second Task"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_work_order_audit",
                side_effect=AssertionError("unexpected WorkOrder finalizer"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_phase34",
                side_effect=AssertionError("unexpected Phase34 finalizer"),
            ),
        ):
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.PREPARATION_NOT_ACQUIRED)
        self.assertEqual(result.task_id, first.task_id)
        prepare.assert_called_once_with(
            self.runtime,
            first.preparation_policy,
            first.preparation_candidate,
        )

    def test_dispatch_race_never_falls_through_to_newer_prepare_candidate(self) -> None:
        first = self._dispatch(new_id(IdKind.TASK), OLD)
        second = self._prepare(new_id(IdKind.TASK), NEW)
        lower = ManagerDispatchTickResult(
            ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED,
            ManagerDispatchTickDetail.CLAIM_ACQUISITION_FAILED,
            task_id=first.task_id,
            dispatch_binding_id=first.dispatch_candidate.dispatch_binding_id,
            binding_audit_id=first.dispatch_candidate.binding_audit_id,
        )
        with (
            patch.object(
                advance_module,
                "inspect_manager_advance_admission_readonly",
                return_value=self._admission(first, second),
            ),
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                return_value=lower,
            ) as dispatch,
            patch.object(
                advance_module,
                "_prepare_selected_candidate_once",
                side_effect=AssertionError("fell through to second Task"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_work_order_audit",
                side_effect=AssertionError("unexpected WorkOrder finalizer"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_phase34",
                side_effect=AssertionError("unexpected Phase34 finalizer"),
            ),
        ):
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.DISPATCH_CLAIM_NOT_ACQUIRED)
        self.assertEqual(result.task_id, first.task_id)
        dispatch.assert_called_once_with(self.runtime, first.dispatch_candidate)

    def test_finalize_work_order_calls_existing_finalizer_once(self) -> None:
        candidate = self._finalize_work_order(new_id(IdKind.TASK), OLD)
        lower = SimpleNamespace(
            status=PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED,
            detail=None,
        )
        with (
            patch.object(
                advance_module,
                "inspect_manager_advance_admission_readonly",
                return_value=self._admission(candidate),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_work_order_audit",
                return_value=lower,
            ) as finalize,
            patch.object(
                advance_module,
                "_prepare_selected_candidate_once",
                side_effect=AssertionError("planner replay path entered"),
            ),
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                side_effect=AssertionError("dispatch attempted"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_phase34",
                side_effect=AssertionError("Phase34 finalizer attempted"),
            ),
        ):
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED)
        self.assertEqual(result.lower_status, PreparationWorkOrderFinalizeStatus.WORK_ORDER_AUDITED.value)
        finalize.assert_called_once_with(self.runtime, candidate.preparation_id)

    def test_finalize_phase34_calls_existing_finalizer_once_and_stops_before_dispatch(self) -> None:
        candidate = self._finalize_phase34(new_id(IdKind.TASK), OLD)
        lower = SimpleNamespace(
            status=PreparationPhase34FinalizeStatus.BOUND_READY,
            detail=None,
        )
        with (
            patch.object(
                advance_module,
                "inspect_manager_advance_admission_readonly",
                return_value=self._admission(candidate),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_phase34",
                return_value=lower,
            ) as finalize,
            patch.object(
                advance_module,
                "_dispatch_selected_candidate_once",
                side_effect=AssertionError("same-call dispatch attempted"),
            ),
            patch.object(
                advance_module,
                "_prepare_selected_candidate_once",
                side_effect=AssertionError("preparation attempted"),
            ),
            patch.object(
                advance_module,
                "finalize_preparation_work_order_audit",
                side_effect=AssertionError("WorkOrder finalizer attempted"),
            ),
        ):
            result = advance_production_manager_once(self.runtime)

        self.assertEqual(result.status, ManagerAdvanceOnceStatus.PHASE34_READY)
        self.assertEqual(result.lower_status, PreparationPhase34FinalizeStatus.BOUND_READY.value)
        finalize.assert_called_once_with(self.runtime, candidate.preparation_id)

    def test_manager_source_has_one_admission_one_selection_one_action_sites_and_no_loop(self) -> None:
        source = inspect.getsource(advance_production_manager_once)
        tree = ast.parse(source)
        calls = [
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        ]
        self.assertEqual(calls.count("inspect_manager_advance_admission_readonly"), 1)
        self.assertEqual(calls.count("select_manager_advance_candidate"), 1)
        self.assertEqual(calls.count("_dispatch_selected_candidate_once"), 1)
        self.assertEqual(calls.count("_prepare_selected_candidate_once"), 1)
        self.assertEqual(calls.count("finalize_preparation_work_order_audit"), 1)
        self.assertEqual(calls.count("finalize_preparation_phase34"), 1)
        self.assertNotIn("dispatch_manager_tick", calls)
        self.assertNotIn("prepare_materialization_tick", calls)
        self.assertFalse(any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree)))
        self.assertNotIn(".outcome", source)
        self.assertEqual(
            tuple(inspect.signature(advance_production_manager_once).parameters),
            ("runtime",),
        )


if __name__ == "__main__":
    unittest.main()
