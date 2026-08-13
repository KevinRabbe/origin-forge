from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import patch

import origin_forge.production_manager_dispatch_tick as tick_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_claims import DispatchClaimError
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmission,
    ManagerDispatchAdmissionStatus,
    ManagerDispatchCandidate,
)
from origin_forge.production_manager_dispatch_tick import (
    ManagerDispatchTickDetail,
    ManagerDispatchTickResult,
    ManagerDispatchTickStatus,
    _dispatch_selected_candidate_once,
    dispatch_manager_tick,
)
from origin_forge.runtime import OriginForgeRuntime


H = "a" * 64
NOW = "2026-08-13T01:00:00Z"


class ProductionManagerDispatchPinnedCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = OriginForgeRuntime("/tmp/origin-forge-phase40d1-pinned-dispatch")
        self.candidate = ManagerDispatchCandidate(
            task_id=new_id(IdKind.TASK),
            task_revision=3,
            task_content_hash=H,
            created_at=NOW,
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

    def _admission(self) -> ManagerDispatchAdmission:
        return ManagerDispatchAdmission(
            status=ManagerDispatchAdmissionStatus.COMPLETE,
            candidates=(self.candidate,),
            scanned_audit_count=1,
            current_chain_count=1,
            active_claim_exclusion_count=0,
            not_ready_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )

    def test_pinned_helper_never_readmits_or_reselects(self) -> None:
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                side_effect=AssertionError("pinned helper re-admitted"),
            ),
            patch.object(
                tick_module,
                "select_manager_dispatch_candidate",
                side_effect=AssertionError("pinned helper reselected"),
            ),
            patch.object(
                tick_module,
                "acquire_dispatch_claim",
                side_effect=DispatchClaimError("selected candidate lost race"),
            ) as acquire,
        ):
            result = _dispatch_selected_candidate_once(self.runtime, self.candidate)

        self.assertEqual(result.status, ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED)
        self.assertEqual(result.task_id, self.candidate.task_id)
        acquire.assert_called_once_with(
            self.runtime,
            self.candidate.dispatch_binding_id,
            self.candidate.binding_audit_id,
            self.candidate.task_revision,
        )

    def test_public_tick_delegates_exact_selected_candidate(self) -> None:
        projected = ManagerDispatchTickResult(
            ManagerDispatchTickStatus.CLAIM_NOT_ACQUIRED,
            ManagerDispatchTickDetail.CLAIM_ACQUISITION_FAILED,
            task_id=self.candidate.task_id,
            dispatch_binding_id=self.candidate.dispatch_binding_id,
            binding_audit_id=self.candidate.binding_audit_id,
        )
        with (
            patch.object(
                tick_module,
                "inspect_manager_dispatch_admission_readonly",
                return_value=self._admission(),
            ),
            patch.object(
                tick_module,
                "_dispatch_selected_candidate_once",
                return_value=projected,
            ) as pinned,
        ):
            result = dispatch_manager_tick(self.runtime)

        self.assertIs(result, projected)
        pinned.assert_called_once_with(self.runtime, self.candidate)

    def test_pinned_helper_source_contains_no_admission_or_selection_call(self) -> None:
        tree = ast.parse(inspect.getsource(_dispatch_selected_candidate_once))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        } | {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("inspect_manager_dispatch_admission_readonly", called)
        self.assertNotIn("select_manager_dispatch_candidate", called)


if __name__ == "__main__":
    unittest.main()
