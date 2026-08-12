from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_invocation_read as invocation_read_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_claim_read import (
    DispatchClaimCurrentness,
    DispatchClaimCurrentnessStatus,
)
from origin_forge.production_dispatch_execution_read import (
    DispatchExecutionCurrentness,
    DispatchExecutionCurrentnessStatus,
)
from origin_forge.production_dispatch_invocation_read import (
    DispatchInvocationStatus,
    DispatchInvocationStatusProjection,
    ProductionDispatchInvocationReadError,
    _execution_ids_for_claim_readonly,
    inspect_dispatch_invocation_status_readonly,
)
from origin_forge.runtime import OriginForgeRuntime


class ProductionDispatchInvocationReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase37-read")
        self.claim_id = new_id(IdKind.DISPATCH_CLAIM)
        self.task_id = new_id(IdKind.TASK)
        self.execution_id = new_id(IdKind.DISPATCH_EXECUTION)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _state_snapshot(self):
        state = self.runtime.state_dir
        result = {}
        for path in sorted(state.rglob("*")):
            relative = path.relative_to(state).as_posix()
            if path.is_symlink():
                result[relative] = ("symlink", path.readlink().as_posix())
            elif path.is_file():
                result[relative] = ("file", path.read_bytes())
            elif path.is_dir():
                result[relative] = ("dir", None)
        return result

    def _claim_currentness(
        self,
        status: DispatchClaimCurrentnessStatus,
        detail: str | None = None,
    ) -> DispatchClaimCurrentness:
        return DispatchClaimCurrentness(
            claim_id=self.claim_id,
            task_id=self.task_id,
            status=status,
            detail=detail,
        )

    def _execution_currentness(
        self,
        status: DispatchExecutionCurrentnessStatus,
        detail: str | None = None,
    ) -> DispatchExecutionCurrentness:
        return DispatchExecutionCurrentness(
            execution_id=self.execution_id,
            claim_id=self.claim_id,
            task_id=self.task_id,
            status=status,
            detail=detail,
        )

    def test_ready_to_invoke_requires_current_active_claim_and_no_execution(self) -> None:
        with (
            patch.object(
                invocation_read_module,
                "inspect_dispatch_claim_currentness_readonly",
                return_value=self._claim_currentness(
                    DispatchClaimCurrentnessStatus.CURRENT_ACTIVE
                ),
            ),
            patch.object(
                invocation_read_module,
                "_execution_ids_for_claim_readonly",
                return_value=(),
            ),
        ):
            status = inspect_dispatch_invocation_status_readonly(
                self.runtime,
                self.claim_id,
            )
        self.assertEqual(status.status, DispatchInvocationStatus.READY_TO_INVOKE)
        self.assertEqual(status.claim_id, self.claim_id)
        self.assertEqual(status.task_id, self.task_id)
        self.assertIsNone(status.execution_id)
        self.assertIsNone(status.detail)

    def test_execution_currentness_maps_exactly_to_invocation_status(self) -> None:
        mapping = {
            DispatchExecutionCurrentnessStatus.CURRENT_STARTED:
                DispatchInvocationStatus.STARTED_RECOVERY_REQUIRED,
            DispatchExecutionCurrentnessStatus.RETURNED:
                DispatchInvocationStatus.RETURNED,
            DispatchExecutionCurrentnessStatus.RAISED:
                DispatchInvocationStatus.RAISED,
            DispatchExecutionCurrentnessStatus.INTERRUPTED:
                DispatchInvocationStatus.INTERRUPTED,
        }
        for execution_status, expected in mapping.items():
            with self.subTest(execution_status=execution_status.value):
                with (
                    patch.object(
                        invocation_read_module,
                        "inspect_dispatch_claim_currentness_readonly",
                        return_value=self._claim_currentness(
                            DispatchClaimCurrentnessStatus.CURRENT_ACTIVE
                        ),
                    ),
                    patch.object(
                        invocation_read_module,
                        "_execution_ids_for_claim_readonly",
                        return_value=(self.execution_id,),
                    ),
                    patch.object(
                        invocation_read_module,
                        "inspect_dispatch_execution_currentness_readonly",
                        return_value=self._execution_currentness(execution_status),
                    ),
                ):
                    status = inspect_dispatch_invocation_status_readonly(
                        self.runtime,
                        self.claim_id,
                    )
                self.assertEqual(status.status, expected)
                self.assertEqual(status.execution_id, self.execution_id)
                self.assertEqual(status.task_id, self.task_id)
                self.assertIsNone(status.detail)

    def test_stale_execution_and_claim_states_fail_closed(self) -> None:
        with (
            patch.object(
                invocation_read_module,
                "inspect_dispatch_claim_currentness_readonly",
                return_value=self._claim_currentness(
                    DispatchClaimCurrentnessStatus.CURRENT_ACTIVE
                ),
            ),
            patch.object(
                invocation_read_module,
                "_execution_ids_for_claim_readonly",
                return_value=(self.execution_id,),
            ),
            patch.object(
                invocation_read_module,
                "inspect_dispatch_execution_currentness_readonly",
                return_value=self._execution_currentness(
                    DispatchExecutionCurrentnessStatus.STALE_DEPENDENCY_PLAN,
                    "protected execution dependency plan drifted",
                ),
            ),
        ):
            status = inspect_dispatch_invocation_status_readonly(
                self.runtime,
                self.claim_id,
            )
        self.assertEqual(status.status, DispatchInvocationStatus.STALE_OR_INVALID)
        self.assertEqual(status.execution_id, self.execution_id)
        self.assertIn("dependency plan drifted", status.detail or "")

        with (
            patch.object(
                invocation_read_module,
                "inspect_dispatch_claim_currentness_readonly",
                return_value=self._claim_currentness(
                    DispatchClaimCurrentnessStatus.RELEASED,
                    "claim released before invocation",
                ),
            ),
            patch.object(
                invocation_read_module,
                "_execution_ids_for_claim_readonly",
                return_value=(),
            ),
        ):
            released = inspect_dispatch_invocation_status_readonly(
                self.runtime,
                self.claim_id,
            )
        self.assertEqual(released.status, DispatchInvocationStatus.STALE_OR_INVALID)
        self.assertIsNone(released.execution_id)
        self.assertEqual(released.detail, "claim released before invocation")

    def test_multiple_execution_receipts_fail_closed_before_execution_inspection(self) -> None:
        other_execution_id = new_id(IdKind.DISPATCH_EXECUTION)
        with (
            patch.object(
                invocation_read_module,
                "inspect_dispatch_claim_currentness_readonly",
                return_value=self._claim_currentness(
                    DispatchClaimCurrentnessStatus.CURRENT_ACTIVE
                ),
            ),
            patch.object(
                invocation_read_module,
                "_execution_ids_for_claim_readonly",
                return_value=(self.execution_id, other_execution_id),
            ),
            patch.object(
                invocation_read_module,
                "inspect_dispatch_execution_currentness_readonly",
            ) as inspect_execution,
        ):
            status = inspect_dispatch_invocation_status_readonly(
                self.runtime,
                self.claim_id,
            )
        inspect_execution.assert_not_called()
        self.assertEqual(status.status, DispatchInvocationStatus.STALE_OR_INVALID)
        self.assertIsNone(status.execution_id)

    def test_unknown_claim_is_stale_invalid_and_read_is_byte_stable(self) -> None:
        before = self._state_snapshot()
        status = inspect_dispatch_invocation_status_readonly(
            self.runtime,
            self.claim_id,
        )
        after = self._state_snapshot()
        self.assertEqual(after, before)
        self.assertEqual(status.status, DispatchInvocationStatus.STALE_OR_INVALID)
        self.assertIsNone(status.task_id)
        self.assertIsNone(status.execution_id)
        self.assertFalse(self.runtime.store.db_path.with_name("project.db-wal").exists())
        self.assertFalse(self.runtime.store.db_path.with_name("project.db-shm").exists())
        self.assertFalse(self.runtime.store.db_path.with_name("project.db-journal").exists())

    def test_execution_lookup_is_select_only_and_noncreating(self) -> None:
        before = self._state_snapshot()
        self.assertEqual(
            _execution_ids_for_claim_readonly(self.runtime, self.claim_id),
            (),
        )
        self.assertEqual(self._state_snapshot(), before)
        source = inspect.getsource(_execution_ids_for_claim_readonly).upper()
        self.assertIn("SELECT EXECUTION_ID", source)
        for forbidden in (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "REPLACE ",
            "CREATE ",
            "DROP ",
            "ALTER ",
            "VACUUM",
            "CHECKPOINT",
        ):
            self.assertNotIn(forbidden, source)

    def test_projection_bounds_detail_and_requires_execution_identity(self) -> None:
        with self.assertRaises(ProductionDispatchInvocationReadError):
            DispatchInvocationStatusProjection(
                self.claim_id,
                self.task_id,
                None,
                DispatchInvocationStatus.STARTED_RECOVERY_REQUIRED,
                None,
            )
        with self.assertRaises(ProductionDispatchInvocationReadError):
            DispatchInvocationStatusProjection(
                self.claim_id,
                self.task_id,
                None,
                DispatchInvocationStatus.STALE_OR_INVALID,
                "x" * 1025,
            )

    def test_read_surface_has_no_invocation_recovery_or_task_outcome_authority(self) -> None:
        signature = inspect.signature(inspect_dispatch_invocation_status_readonly)
        self.assertEqual(tuple(signature.parameters), ("runtime", "claim_id"))
        source = inspect.getsource(invocation_read_module)
        tree = ast.parse(source)
        forbidden_calls = {
            "dispatch_claim_once",
            "drive",
            "begin_dispatch_execution",
            "interrupt_dispatch_execution",
            "mark_dispatch_execution_returned",
            "mark_dispatch_execution_raised",
            "release_dispatch_claim",
            "interrupt_dispatch_claim",
            "acquire_dispatch_claim",
            "start_run",
            "finish_run",
            "transition_task",
            "initialize",
            "migrate",
            "checkpoint",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))
        self.assertNotIn("PolicyOutcome", source)
        self.assertNotIn("PolicyResult", source)


if __name__ == "__main__":
    unittest.main()
