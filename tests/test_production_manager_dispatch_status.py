from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_manager_dispatch_status as status_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_manager_dispatch_admission import (
    ManagerDispatchAdmission,
    ManagerDispatchAdmissionStatus,
    ManagerDispatchCandidate,
)
from origin_forge.production_manager_dispatch_selection import (
    ManagerDispatchSelectionStatus,
)
from origin_forge.production_manager_dispatch_status import (
    ManagerDispatchStatusProjection,
    inspect_manager_dispatch_status_readonly,
)
from origin_forge.runtime import OriginForgeRuntime


H = "a" * 64


def _snapshot(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    if not root.exists():
        return ()
    rows = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows.append((relative, "symlink", path.readlink().as_posix().encode()))
        elif path.is_file():
            rows.append((relative, "file", path.read_bytes()))
        elif path.is_dir():
            rows.append((relative, "dir", None))
    return tuple(rows)


def _candidate() -> ManagerDispatchCandidate:
    return ManagerDispatchCandidate(
        task_id=new_id(IdKind.TASK),
        task_revision=1,
        task_content_hash=H,
        created_at="2026-08-12T18:00:00Z",
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


class ProductionManagerDispatchStatusTests(unittest.TestCase):
    def test_uninitialized_status_does_not_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            before = _snapshot(root)
            result = inspect_manager_dispatch_status_readonly(runtime)
            self.assertEqual(result.selection_status, ManagerDispatchSelectionStatus.INVALID_STATE)
            self.assertEqual(before, _snapshot(root))
            self.assertFalse((root / ".origin-forge").exists())

    def test_initialized_empty_status_is_byte_stable_and_creates_no_sqlite_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("phase38-status")
            before = _snapshot(runtime.state_dir)

            result = inspect_manager_dispatch_status_readonly(runtime)

            self.assertEqual(result.admission_status, ManagerDispatchAdmissionStatus.COMPLETE)
            self.assertEqual(result.selection_status, ManagerDispatchSelectionStatus.NO_ELIGIBLE_TASK)
            self.assertEqual(result.candidate_count, 0)
            self.assertEqual(before, _snapshot(runtime.state_dir))
            names = {path.name for path in runtime.state_dir.iterdir()}
            self.assertFalse(any(name.endswith(("-wal", "-shm", "-journal")) for name in names))

    def test_projection_carries_exact_selected_ids_only_for_one_selected(self) -> None:
        candidate = _candidate()
        admission = ManagerDispatchAdmission(
            status=ManagerDispatchAdmissionStatus.COMPLETE,
            candidates=(candidate,),
            scanned_audit_count=1,
            current_chain_count=1,
            active_claim_exclusion_count=0,
            not_ready_exclusion_count=0,
            ambiguous_task_ids=(),
            detail=None,
        )
        runtime = OriginForgeRuntime("/tmp/origin-forge-phase38-status-projection")
        with patch.object(
            status_module,
            "inspect_manager_dispatch_admission_readonly",
            return_value=admission,
        ):
            result = inspect_manager_dispatch_status_readonly(runtime)
        self.assertEqual(result.selection_status, ManagerDispatchSelectionStatus.ONE_SELECTED)
        self.assertEqual(result.selected_task_id, candidate.task_id)
        self.assertEqual(result.selected_dispatch_binding_id, candidate.dispatch_binding_id)
        self.assertEqual(result.selected_binding_audit_id, candidate.binding_audit_id)

    def test_projection_model_rejects_selected_ids_without_selection(self) -> None:
        candidate = _candidate()
        with self.assertRaises(ValueError):
            ManagerDispatchStatusProjection(
                admission_status=ManagerDispatchAdmissionStatus.COMPLETE,
                selection_status=ManagerDispatchSelectionStatus.NO_ELIGIBLE_TASK,
                candidate_count=0,
                scanned_audit_count=0,
                current_chain_count=0,
                active_claim_exclusion_count=0,
                not_ready_exclusion_count=0,
                ambiguous_task_count=0,
                selected_task_id=candidate.task_id,
                selected_dispatch_binding_id=None,
                selected_binding_audit_id=None,
                detail=None,
            )

    def test_status_surface_has_no_manager_mutation_authority(self) -> None:
        source = inspect.getsource(status_module)
        tree = ast.parse(source)
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        for forbidden in (
            "activate_dependency_ready_task",
            "acquire_dispatch_claim",
            "release_dispatch_claim",
            "interrupt_dispatch_claim",
            "begin_dispatch_execution",
            "dispatch_claim_once",
            "drive",
            "generate",
            "start_run",
            "transition_task",
            "execute",
            "open",
        ):
            self.assertNotIn(forbidden, called)
        self.assertNotIn("production_manager_dispatch_tick", source)
        signature = inspect.signature(inspect_manager_dispatch_status_readonly)
        self.assertEqual(tuple(signature.parameters), ("runtime",))


if __name__ == "__main__":
    unittest.main()
