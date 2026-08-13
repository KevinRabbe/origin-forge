from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_manager_advance_status as status_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_manager_advance_admission import (
    ManagerAdvanceActionKind,
    ManagerAdvanceAdmission,
    ManagerAdvanceAdmissionStatus,
    ManagerAdvanceCandidate,
)
from origin_forge.production_manager_advance_selection import ManagerAdvanceSelectionStatus
from origin_forge.production_manager_advance_status import inspect_manager_advance_status_readonly
from origin_forge.production_manager_dispatch_admission import ManagerDispatchCandidate
from origin_forge.production_preparation_models import PreparationStage
from origin_forge.runtime import OriginForgeRuntime


H = "a" * 64
NOW = "2026-08-13T01:00:00Z"


class ManagerAdvanceStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(Path(self.tempdir.name))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _dispatch_candidate(self) -> ManagerAdvanceCandidate:
        task_id = new_id(IdKind.TASK)
        dispatch = ManagerDispatchCandidate(
            task_id=task_id,
            task_revision=2,
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
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.DISPATCH,
            task_id,
            NOW,
            dispatch_candidate=dispatch,
        )

    def _recovery_candidate(self) -> ManagerAdvanceCandidate:
        return ManagerAdvanceCandidate(
            ManagerAdvanceActionKind.RECOVERY_REQUIRED,
            new_id(IdKind.TASK),
            NOW,
            preparation_id=new_id(IdKind.TASK_PREPARATION),
            preparation_stage=PreparationStage.CLAIMED,
            detail="explicit recovery required",
        )

    def _complete(self, candidate: ManagerAdvanceCandidate) -> ManagerAdvanceAdmission:
        counts = {kind: 0 for kind in ManagerAdvanceActionKind}
        counts[candidate.action_kind] += 1
        return ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.COMPLETE,
            candidates=(candidate,),
            dispatch_count=counts[ManagerAdvanceActionKind.DISPATCH],
            finalize_work_order_count=counts[ManagerAdvanceActionKind.FINALIZE_WORK_ORDER],
            finalize_phase34_count=counts[ManagerAdvanceActionKind.FINALIZE_PHASE34],
            prepare_count=counts[ManagerAdvanceActionKind.PREPARE],
            recovery_required_count=counts[ManagerAdvanceActionKind.RECOVERY_REQUIRED],
            terminal_retry_suppression_count=2,
            active_claim_exclusion_count=1,
            ambiguous_task_ids=(),
            detail=None,
        )

    def test_status_projects_exact_selected_dispatch_authority(self) -> None:
        candidate = self._dispatch_candidate()
        with patch.object(
            status_module,
            "inspect_manager_advance_admission_readonly",
            return_value=self._complete(candidate),
        ):
            projection = inspect_manager_advance_status_readonly(self.runtime)

        self.assertEqual(projection.admission_status, ManagerAdvanceAdmissionStatus.COMPLETE)
        self.assertEqual(projection.selection_status, ManagerAdvanceSelectionStatus.ONE_SELECTED)
        self.assertEqual(projection.selected_task_id, candidate.task_id)
        self.assertEqual(projection.selected_task_created_at, candidate.task_created_at)
        self.assertEqual(projection.selected_action_kind, ManagerAdvanceActionKind.DISPATCH)
        self.assertEqual(
            projection.selected_dispatch_binding_id,
            candidate.dispatch_candidate.dispatch_binding_id,
        )
        self.assertEqual(
            projection.selected_binding_audit_id,
            candidate.dispatch_candidate.binding_audit_id,
        )
        self.assertEqual(projection.dispatch_count, 1)
        self.assertEqual(projection.terminal_retry_suppression_count, 2)
        self.assertEqual(projection.active_claim_exclusion_count, 1)
        self.assertIsNone(projection.selected_preparation_id)

    def test_status_projects_recovery_candidate_without_mutating_it(self) -> None:
        candidate = self._recovery_candidate()
        with patch.object(
            status_module,
            "inspect_manager_advance_admission_readonly",
            return_value=self._complete(candidate),
        ):
            projection = inspect_manager_advance_status_readonly(self.runtime)

        self.assertEqual(projection.selection_status, ManagerAdvanceSelectionStatus.ONE_SELECTED)
        self.assertEqual(projection.selected_action_kind, ManagerAdvanceActionKind.RECOVERY_REQUIRED)
        self.assertEqual(projection.selected_preparation_id, candidate.preparation_id)
        self.assertEqual(projection.selected_preparation_stage, PreparationStage.CLAIMED.value)
        self.assertIsNone(projection.selected_dispatch_binding_id)

    def test_failed_admission_exposes_no_selected_authority(self) -> None:
        admission = ManagerAdvanceAdmission(
            status=ManagerAdvanceAdmissionStatus.AMBIGUOUS_AUTHORITY,
            candidates=(),
            dispatch_count=0,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=0,
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            ambiguous_task_ids=(new_id(IdKind.TASK),),
            detail="ambiguous policy authority",
        )
        with patch.object(
            status_module,
            "inspect_manager_advance_admission_readonly",
            return_value=admission,
        ):
            projection = inspect_manager_advance_status_readonly(self.runtime)

        self.assertEqual(
            projection.selection_status,
            ManagerAdvanceSelectionStatus.AMBIGUOUS_AUTHORITY,
        )
        self.assertIsNone(projection.selected_task_id)
        self.assertIsNone(projection.selected_action_kind)
        self.assertEqual(projection.ambiguous_task_ids, admission.ambiguous_task_ids)
        self.assertEqual(projection.detail, admission.detail)

    def test_status_source_has_no_action_or_mutation_authority(self) -> None:
        source = Path(status_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_modules = {
            "production_manager_advance_once",
            "production_manager_dispatch_tick",
            "production_preparation_tick",
            "production_preparation_receipts",
            "production_preparation_work_order_finalize",
            "production_preparation_phase34_finalize",
            "production_dispatch_claims",
            "production_dispatch_invocation",
            "production_task_activation",
            "scheduled_model_adapter",
        }
        forbidden_calls = {
            "advance_production_manager_once",
            "_dispatch_selected_candidate_once",
            "_prepare_selected_candidate_once",
            "dispatch_manager_tick",
            "prepare_materialization_tick",
            "finalize_preparation_work_order_audit",
            "finalize_preparation_phase34",
            "acquire_dispatch_claim",
            "dispatch_claim_once",
            "activate_dependency_ready_task",
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
