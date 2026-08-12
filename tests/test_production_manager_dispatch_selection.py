from __future__ import annotations

import ast
import inspect
import unittest

import origin_forge.production_manager_dispatch_selection as selection_module
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmission,
    ManagerDispatchAdmissionDetail,
    ManagerDispatchAdmissionStatus,
    ManagerDispatchCandidate,
)
from origin_forge.production_manager_dispatch_selection import (
    ManagerDispatchSelection,
    ManagerDispatchSelectionStatus,
    select_manager_dispatch_candidate,
)


H = "a" * 64


def _candidate(task_id: str, created_at: str, suffix: str) -> ManagerDispatchCandidate:
    return ManagerDispatchCandidate(
        task_id=task_id,
        task_revision=1,
        task_content_hash=H,
        created_at=created_at,
        input_resolution_id=f"INRES-00000000-0000-4000-8000-0000000000{suffix}",
        dispatch_binding_id=f"DISPBIND-00000000-0000-4000-8000-0000000000{suffix}",
        binding_audit_id=f"BINDAUD-00000000-0000-4000-8000-0000000000{suffix}",
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


def _admission(
    status: ManagerDispatchAdmissionStatus,
    candidates: tuple[ManagerDispatchCandidate, ...] = (),
    *,
    ambiguous_task_ids: tuple[str, ...] = (),
    detail: ManagerDispatchAdmissionDetail | None = None,
) -> ManagerDispatchAdmission:
    return ManagerDispatchAdmission(
        status=status,
        candidates=candidates,
        scanned_audit_count=len(candidates),
        current_chain_count=len(candidates),
        active_claim_exclusion_count=0,
        not_ready_exclusion_count=0,
        ambiguous_task_ids=ambiguous_task_ids,
        detail=detail,
    )


class ProductionManagerDispatchSelectionTests(unittest.TestCase):
    def test_complete_empty_admission_selects_nothing(self) -> None:
        result = select_manager_dispatch_candidate(
            _admission(ManagerDispatchAdmissionStatus.COMPLETE)
        )
        self.assertEqual(result.status, ManagerDispatchSelectionStatus.NO_ELIGIBLE_TASK)
        self.assertIsNone(result.candidate)

    def test_complete_candidates_select_created_at_then_task_id_only(self) -> None:
        oldest_high_id = _candidate(
            "TASK-00000000-0000-4000-8000-000000000020",
            "2026-08-12T12:00:00Z",
            "20",
        )
        oldest_low_id = _candidate(
            "TASK-00000000-0000-4000-8000-000000000010",
            "2026-08-12T12:00:00Z",
            "10",
        )
        newer = _candidate(
            "TASK-00000000-0000-4000-8000-000000000001",
            "2026-08-12T12:00:01Z",
            "01",
        )
        result = select_manager_dispatch_candidate(
            _admission(
                ManagerDispatchAdmissionStatus.COMPLETE,
                (newer, oldest_high_id, oldest_low_id),
            )
        )
        self.assertEqual(result.status, ManagerDispatchSelectionStatus.ONE_SELECTED)
        self.assertEqual(result.candidate, oldest_low_id)

    def test_ambiguous_admission_never_falls_through_to_valid_candidate(self) -> None:
        candidate = _candidate(
            "TASK-00000000-0000-4000-8000-000000000001",
            "2026-08-12T12:00:00Z",
            "01",
        )
        result = select_manager_dispatch_candidate(
            _admission(
                ManagerDispatchAdmissionStatus.AMBIGUOUS_AUTHORITY,
                (candidate,),
                ambiguous_task_ids=(
                    "TASK-00000000-0000-4000-8000-000000000099",
                ),
            )
        )
        self.assertEqual(result.status, ManagerDispatchSelectionStatus.AMBIGUOUS_AUTHORITY)
        self.assertIsNone(result.candidate)

    def test_limit_and_invalid_admission_never_select(self) -> None:
        for admission, expected in (
            (
                _admission(
                    ManagerDispatchAdmissionStatus.LIMIT_EXCEEDED,
                    detail=ManagerDispatchAdmissionDetail.PHASE34_SCAN_LIMIT_EXCEEDED,
                ),
                ManagerDispatchSelectionStatus.LIMIT_EXCEEDED,
            ),
            (
                _admission(
                    ManagerDispatchAdmissionStatus.INVALID_STATE,
                    detail=ManagerDispatchAdmissionDetail.INVALID_CANONICAL_STATE,
                ),
                ManagerDispatchSelectionStatus.INVALID_STATE,
            ),
        ):
            with self.subTest(status=admission.status):
                result = select_manager_dispatch_candidate(admission)
                self.assertEqual(result.status, expected)
                self.assertIsNone(result.candidate)

    def test_inconsistent_complete_admission_fails_closed(self) -> None:
        result = select_manager_dispatch_candidate(
            _admission(
                ManagerDispatchAdmissionStatus.COMPLETE,
                ambiguous_task_ids=(
                    "TASK-00000000-0000-4000-8000-000000000099",
                ),
            )
        )
        self.assertEqual(result.status, ManagerDispatchSelectionStatus.INVALID_STATE)
        self.assertIsNone(result.candidate)

    def test_selection_model_enforces_candidate_relation(self) -> None:
        candidate = _candidate(
            "TASK-00000000-0000-4000-8000-000000000001",
            "2026-08-12T12:00:00Z",
            "01",
        )
        with self.assertRaises(ValueError):
            ManagerDispatchSelection(ManagerDispatchSelectionStatus.ONE_SELECTED, None)
        with self.assertRaises(ValueError):
            ManagerDispatchSelection(ManagerDispatchSelectionStatus.NO_ELIGIBLE_TASK, candidate)

    def test_selector_surface_is_pure_and_has_no_manager_mutation_authority(self) -> None:
        source = inspect.getsource(selection_module)
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        for forbidden_import in (
            "runtime",
            "sqlite3",
            "pathlib",
            "subprocess",
            "production_dispatch_claims",
            "production_dispatch_invocation",
            "production_task_activation",
        ):
            self.assertTrue(
                all(forbidden_import not in value for value in imports),
                forbidden_import,
            )

        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        forbidden_calls = {
            "activate_dependency_ready_task",
            "acquire_dispatch_claim",
            "dispatch_claim_once",
            "transition_task",
            "start_run",
            "generate",
            "drive",
            "open",
            "execute",
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))
        signature = inspect.signature(select_manager_dispatch_candidate)
        self.assertEqual(tuple(signature.parameters), ("admission",))


if __name__ == "__main__":
    unittest.main()
