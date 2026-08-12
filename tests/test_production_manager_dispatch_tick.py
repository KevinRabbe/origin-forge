from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import replace
from unittest.mock import patch

import origin_forge.production_manager_dispatch_tick as tick_module
from origin_forge.ids import IdKind, new_id
from origin_forge.orchestration_policy import PolicyAction, PolicyOutcome, PolicyResult
from origin_forge.production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
from origin_forge.production_dispatch_claims import DispatchClaimError
from origin_forge.production_dispatch_execution_models import (
    DispatchExecution,
    DispatchExecutionStatus,
)
from origin_forge.production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from origin_forge.production_dispatch_invocation_read import (
    DispatchInvocationStatus,
    DispatchInvocationStatusProjection,
)
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmission,
    ManagerDispatchAdmissionStatus,
    ManagerDispatchCandidate,
)
from origin_forge.production_manager_dispatch_tick import (
    ManagerDispatchTickStatus,
    dispatch_manager_tick,
)
from origin_forge.runtime import OriginForgeRuntime


H = "a" * 64
NOW = "2026-08-12T18:00:00Z"


class ProductionManagerDispatchTickTests(unittest.TestCase):
    def setUp(self) -> None:
        # Runtime construction is non-creating; all Manager dependencies are patched
        # in these mechanics tests. Cross-phase persistence is covered in 38E.
        self.runtime = OriginForgeRuntime("/tmp/origin-forge-phase38-tick-test")
        self.project_id = new_id(IdKind.PROJECT)
        self.task_id = new_id(IdKind.TASK)
        self.work_order_id = new_id(IdKind.PRODUCTION_WORK_ORDER)
        self.work_order_audit_id = new_id(IdKind.WORK_ORDER_AUDIT)
        self.input_resolution_id = new_id(IdKind.INPUT_RESOLUTION_BUNDLE)
        self.binding_id = new_id(IdKind.DISPATCH_BINDING)
        self.binding_audit_id = new_id(IdKind.DISPATCH_BINDING_AUDIT)
        self.claim_id = new_id(IdKind.DISPATCH_CLAIM)
        self.execution_id = new_id(IdKind.DISPATCH_EXECUTION)
        self.candidate = ManagerDispatchCandidate(
            task_id=self.task_id,
            task_revision=1,
            task_content_hash=H,
            created_at=NOW,
            input_resolution_id=self.input_resolution_id,
            dispatch_binding_id=self.binding_id,
            binding_audit_id=self.binding_audit_id,
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
        self.claim = DispatchClaim(
            claim_id=self.claim_id,
            project_id=self.project_id,
            task_id=self.task_id,
            task_revision=1,
            task_content_hash=H,
            work_order_id=self.work_order_id,
            work_order_hash=H,
            work_order_audit_id=self.work_order_audit_id,
            work_order_audit_hash=H,
            input_resolution_id=self.input_resolution_id,
            input_resolution_hash=H,
            dispatch_binding_id=self.binding_id,
            dispatch_binding_hash=H,
            binding_audit_id=self.binding_audit_id,
            binding_audit_hash=H,
            selected_adapter_id="originforge.code.bounded-retry",
            selected_adapter_fingerprint=H,
            dispatch_contract_id="code.bounded-retry@1",
            dispatch_contract_hash=H,
            binder_id="binder.code.bounded-retry@1",
            binder_fingerprint=H,
            status=DispatchClaimStatus.ACTIVE,
            revision=0,
            created_at=NOW,
            updated_at=NOW,
            terminal_reason=None,
        )

    def _admission(
        self,
        *candidates: ManagerDispatchCandidate,
        status: ManagerDispatchAdmissionStatus = ManagerDispatchAdmissionStatus.COMPLETE,
    ) -> ManagerDispatchAdmission:
        return ManagerDispatchAdmission(
            status=status,
            candidates=tuple(candidates),
            scanned_audit_count=len(candidates),
            current_chain_count=len(candidates),
            active_claim_exclusion_count=0,
            not_ready_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )

    def _completed(self) -> CompletedDispatchInvocation:
        execution = DispatchExecution(
            execution_id=self.execution_id,
            project_id=self.project_id,
            claim_id=self.claim_id,
            claim_revision_at_start=0,
            task_id=self.task_id,
            task_revision=1,
            task_content_hash=H,
            work_order_id=self.work_order_id,
            work_order_hash=H,
            input_resolution_id=self.input_resolution_id,
            input_resolution_hash=H,
            dispatch_binding_id=self.binding_id,
            dispatch_binding_hash=H,
            binding_audit_id=self.binding_audit_id,
            binding_audit_hash=H,
            selected_adapter_id="originforge.code.bounded-retry",
            selected_adapter_fingerprint=H,
            dispatch_contract_id="code.bounded-retry@1",
            dispatch_contract_hash=H,
            binder_id="binder.code.bounded-retry@1",
            binder_fingerprint=H,
            execution_owner_id="originforge.execution.bounded-retry@1",
            execution_owner_fingerprint=H,
            runtime_dependency_plan_hash=H,
            status=DispatchExecutionStatus.RETURNED,
            revision=1,
            created_at=NOW,
            updated_at=NOW,
            terminal_detail_hash=H,
        )
        # BLOCKED is intentionally used to prove the Manager does not reinterpret
        # PolicyOutcome: the Python invocation returned normally, so Manager status
        # is DISPATCH_RETURNED.
        policy = PolicyResult(
            task_id=self.task_id,
            outcome=PolicyOutcome.BLOCKED,
            action=PolicyAction.STOP,
            reason="downstream policy result remains canonical elsewhere",
            executor_attempts=0,
            attempts_started=0,
        )
        return CompletedDispatchInvocation(execution, policy)

    def test_no_eligible_task_stops_before_claim_and_dispatch(self) -> None:
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(),
            ),
            patch.object(
                tick_module,
                "acquire_dispatch_claim",
                side_effect=AssertionError("claim attempted"),
            ),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=AssertionError("dispatch attempted"),
            ),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.NO_ELIGIBLE_TASK)
        self.assertIsNone(result.claim_id)
        self.assertIsNone(result.execution_id)

    def test_claim_failure_does_not_fall_through_or_invoke(self) -> None:
        second = replace(
            self.candidate,
            task_id=new_id(IdKind.TASK),
            created_at="2026-08-12T18:00:01Z",
            input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
        )
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(self.candidate, second),
            ),
            patch.object(
                tick_module,
                "acquire_dispatch_claim",
                side_effect=DispatchClaimError("lost race"),
            ) as acquire,
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=AssertionError("dispatch attempted"),
            ),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED)
        acquire.assert_called_once_with(
            self.runtime,
            self.binding_id,
            self.binding_audit_id,
            1,
        )

    def test_claim_relation_mismatch_stops_before_dispatch(self) -> None:
        forged = replace(self.claim, binder_id="binder.other@1")
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(self.candidate),
            ),
            patch.object(tick_module, "acquire_dispatch_claim", return_value=forged),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=AssertionError("dispatch attempted"),
            ),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.CLAIM_RELATION_INVALID)
        self.assertEqual(result.claim_id, self.claim_id)

    def test_successful_claim_calls_phase37_exactly_once_and_reports_returned(self) -> None:
        completed = self._completed()
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(self.candidate),
            ),
            patch.object(tick_module, "acquire_dispatch_claim", return_value=self.claim),
            patch.object(tick_module, "dispatch_claim_once", return_value=completed) as dispatch,
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.DISPATCH_RETURNED)
        self.assertEqual(result.claim_id, self.claim_id)
        self.assertEqual(result.execution_id, self.execution_id)
        dispatch.assert_called_once_with(self.runtime, self.claim_id, 0)

    def test_phase37_raised_is_projected_without_retry(self) -> None:
        projection = DispatchInvocationStatusProjection(
            self.claim_id,
            self.task_id,
            self.execution_id,
            DispatchInvocationStatus.RAISED,
            None,
        )
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(self.candidate),
            ),
            patch.object(tick_module, "acquire_dispatch_claim", return_value=self.claim),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=ProductionDispatchInvocationError("owner raised"),
            ) as dispatch,
            patch.object(
                tick_module,
                "inspect_dispatch_invocation_status_readonly",
                return_value=projection,
            ),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.DISPATCH_RAISED)
        self.assertEqual(result.execution_id, self.execution_id)
        self.assertEqual(dispatch.call_count, 1)

    def test_phase37_recovery_required_is_surfaced_without_replay(self) -> None:
        recovery = ProductionDispatchInvocationRecoveryRequired(
            self.execution_id,
            "RETURNED_TERMINALIZATION_FAILED",
        )
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(self.candidate),
            ),
            patch.object(tick_module, "acquire_dispatch_claim", return_value=self.claim),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=recovery,
            ) as dispatch,
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.execution_id, self.execution_id)
        self.assertEqual(dispatch.call_count, 1)

    def test_phase37_prestart_failure_leaves_active_claim_and_no_second_attempt(self) -> None:
        projection = DispatchInvocationStatusProjection(
            self.claim_id,
            self.task_id,
            None,
            DispatchInvocationStatus.READY_TO_INVOKE,
            None,
        )
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(self.candidate),
            ),
            patch.object(tick_module, "acquire_dispatch_claim", return_value=self.claim),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=ProductionDispatchInvocationError("prestart"),
            ) as dispatch,
            patch.object(
                tick_module,
                "inspect_dispatch_invocation_status_readonly",
                return_value=projection,
            ),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(result.status, ManagerDispatchTickStatus.DISPATCH_NOT_STARTED)
        self.assertEqual(result.claim_id, self.claim_id)
        self.assertIsNone(result.execution_id)
        self.assertEqual(dispatch.call_count, 1)

    def test_tick_source_has_one_claim_and_one_dispatch_call_site_and_no_loop_or_outcome_logic(self) -> None:
        source = inspect.getsource(dispatch_manager_tick)
        tree = ast.parse(source)
        calls = [
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        ]
        self.assertEqual(calls.count("acquire_dispatch_claim"), 1)
        self.assertEqual(calls.count("dispatch_claim_once"), 1)
        self.assertNotIn("activate_dependency_ready_task", calls)
        self.assertFalse(any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree)))
        self.assertNotIn(".outcome", source)
        signature = inspect.signature(dispatch_manager_tick)
        self.assertEqual(tuple(signature.parameters), ("runtime",))


if __name__ == "__main__":
    unittest.main()
