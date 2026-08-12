from __future__ import annotations

import unittest
from unittest.mock import patch

import origin_forge.production_manager_dispatch_tick as tick_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
from origin_forge.production_dispatch_invocation import ProductionDispatchInvocationError
from origin_forge.production_dispatch_invocation_read import (
    DispatchInvocationStatus,
    DispatchInvocationStatusProjection,
    ProductionDispatchInvocationReadError,
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


class ProductionManagerDispatchTickFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = OriginForgeRuntime("/tmp/origin-forge-phase38-tick-fail-closed")
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
        self.admission = ManagerDispatchAdmission(
            status=ManagerDispatchAdmissionStatus.COMPLETE,
            candidates=(self.candidate,),
            scanned_audit_count=1,
            current_chain_count=1,
            active_claim_exclusion_count=0,
            not_ready_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )

    def _run_with_projection(self, projection):
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self.admission,
            ),
            patch.object(tick_module, "acquire_dispatch_claim", return_value=self.claim),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=ProductionDispatchInvocationError("phase37 failed"),
            ) as dispatch,
            patch.object(
                tick_module,
                "inspect_dispatch_invocation_status_readonly",
                return_value=projection,
            ),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(dispatch.call_count, 1)
        return result

    def test_generic_phase37_error_with_durable_returned_requires_recovery(self) -> None:
        projection = DispatchInvocationStatusProjection(
            self.claim_id,
            self.task_id,
            self.execution_id,
            DispatchInvocationStatus.RETURNED,
            None,
        )
        result = self._run_with_projection(projection)
        self.assertEqual(result.status, ManagerDispatchTickStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.execution_id, self.execution_id)

    def test_generic_phase37_error_with_started_receipt_requires_recovery(self) -> None:
        projection = DispatchInvocationStatusProjection(
            self.claim_id,
            self.task_id,
            self.execution_id,
            DispatchInvocationStatus.STARTED_RECOVERY_REQUIRED,
            None,
        )
        result = self._run_with_projection(projection)
        self.assertEqual(result.status, ManagerDispatchTickStatus.RECOVERY_REQUIRED)
        self.assertEqual(result.execution_id, self.execution_id)

    def test_generic_phase37_error_with_unreadable_status_requires_recovery(self) -> None:
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self.admission,
            ),
            patch.object(tick_module, "acquire_dispatch_claim", return_value=self.claim),
            patch.object(
                tick_module,
                "dispatch_claim_once",
                side_effect=ProductionDispatchInvocationError("phase37 failed"),
            ) as dispatch,
            patch.object(
                tick_module,
                "inspect_dispatch_invocation_status_readonly",
                side_effect=ProductionDispatchInvocationReadError("unreadable"),
            ),
        ):
            result = dispatch_manager_tick(self.runtime)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(result.status, ManagerDispatchTickStatus.RECOVERY_REQUIRED)
        self.assertIsNone(result.execution_id)

    def test_only_proven_ready_to_invoke_is_classified_not_started(self) -> None:
        projection = DispatchInvocationStatusProjection(
            self.claim_id,
            self.task_id,
            None,
            DispatchInvocationStatus.READY_TO_INVOKE,
            None,
        )
        result = self._run_with_projection(projection)
        self.assertEqual(result.status, ManagerDispatchTickStatus.DISPATCH_NOT_STARTED)
        self.assertIsNone(result.execution_id)


if __name__ == "__main__":
    unittest.main()
