from __future__ import annotations

import sqlite3
import tempfile
import unittest

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_dispatch_claim_models import (
    DispatchClaim,
    DispatchClaimModelError,
    DispatchClaimStatus,
)
from origin_forge.production_dispatch_execution_models import (
    DispatchExecution,
    DispatchExecutionModelError,
    DispatchExecutionStatus,
)
from origin_forge.runtime import OriginForgeRuntime


class ProductionDispatchExecutionModelTests(unittest.TestCase):
    def _claim(self, status: DispatchClaimStatus = DispatchClaimStatus.ACTIVE) -> DispatchClaim:
        terminal = None if status is DispatchClaimStatus.ACTIVE else "terminal claim evidence"
        return DispatchClaim(
            claim_id=new_id(IdKind.DISPATCH_CLAIM),
            project_id=new_id(IdKind.PROJECT),
            task_id=new_id(IdKind.TASK),
            task_revision=4,
            task_content_hash="a" * 64,
            work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
            work_order_hash="b" * 64,
            work_order_audit_id=new_id(IdKind.WORK_ORDER_AUDIT),
            work_order_audit_hash="c" * 64,
            input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
            input_resolution_hash="d" * 64,
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            dispatch_binding_hash="e" * 64,
            binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
            binding_audit_hash="f" * 64,
            selected_adapter_id="originforge.code.bounded-retry",
            selected_adapter_fingerprint="1" * 64,
            dispatch_contract_id="code.bounded-retry@1",
            dispatch_contract_hash="2" * 64,
            binder_id="binder.code.bounded-retry@1",
            binder_fingerprint="3" * 64,
            status=status,
            revision=0 if status is DispatchClaimStatus.ACTIVE else 1,
            created_at="2026-08-11T18:00:00Z",
            updated_at="2026-08-11T18:00:00Z",
            terminal_reason=terminal,
        )

    def _execution(
        self,
        *,
        status: DispatchExecutionStatus = DispatchExecutionStatus.STARTED,
        execution_id: str | None = None,
        claim_id: str | None = None,
        task_id: str | None = None,
    ) -> DispatchExecution:
        terminal = None if status is DispatchExecutionStatus.STARTED else "9" * 64
        return DispatchExecution(
            execution_id=execution_id or new_id(IdKind.DISPATCH_EXECUTION),
            project_id=new_id(IdKind.PROJECT),
            claim_id=claim_id or new_id(IdKind.DISPATCH_CLAIM),
            claim_revision_at_start=0,
            task_id=task_id or new_id(IdKind.TASK),
            task_revision=4,
            task_content_hash="a" * 64,
            work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
            work_order_hash="b" * 64,
            input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
            input_resolution_hash="d" * 64,
            dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
            dispatch_binding_hash="e" * 64,
            binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
            binding_audit_hash="f" * 64,
            selected_adapter_id="originforge.code.bounded-retry",
            selected_adapter_fingerprint="1" * 64,
            dispatch_contract_id="code.bounded-retry@1",
            dispatch_contract_hash="2" * 64,
            binder_id="binder.code.bounded-retry@1",
            binder_fingerprint="3" * 64,
            execution_owner_id="originforge.execution.bounded-retry@1",
            execution_owner_fingerprint="4" * 64,
            runtime_dependency_plan_hash="5" * 64,
            status=status,
            revision=0 if status is DispatchExecutionStatus.STARTED else 1,
            created_at="2026-08-11T18:00:00Z",
            updated_at="2026-08-11T18:00:00Z",
            terminal_detail_hash=terminal,
        )

    def test_dispatch_execution_id_and_consumed_claim_identity_are_typed(self) -> None:
        execution_id = new_id(IdKind.DISPATCH_EXECUTION)
        self.assertTrue(validate_id(execution_id, IdKind.DISPATCH_EXECUTION))
        self.assertTrue(execution_id.startswith("DISPEXEC-"))

        consumed = self._claim(DispatchClaimStatus.CONSUMED)
        self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
        self.assertFalse(consumed.is_active)
        self.assertEqual(consumed.terminal_reason, "terminal claim evidence")
        with self.assertRaises(DispatchClaimModelError):
            DispatchClaim(
                **{
                    **consumed.to_dict(),
                    "status": DispatchClaimStatus.CONSUMED,
                    "terminal_reason": None,
                }
            )

    def test_started_execution_is_inert_frozen_authority(self) -> None:
        execution = self._execution()
        self.assertTrue(execution.is_started)
        self.assertFalse(execution.is_terminal)
        self.assertEqual(execution.status, DispatchExecutionStatus.STARTED)
        self.assertEqual(execution.revision, 0)
        self.assertIsNone(execution.terminal_detail_hash)
        self.assertEqual(
            set(execution.to_dict()),
            set(execution.frozen_authority_dict())
            | {
                "status",
                "revision",
                "created_at",
                "updated_at",
                "terminal_detail_hash",
            },
        )
        for forbidden in (
            "callable",
            "import_path",
            "argv",
            "shell",
            "endpoint",
            "api_key",
            "environment",
            "pid",
        ):
            self.assertNotIn(forbidden, execution.to_dict())

    def test_terminal_execution_statuses_require_revision_one_and_detail_hash(self) -> None:
        for status in (
            DispatchExecutionStatus.RETURNED,
            DispatchExecutionStatus.RAISED,
            DispatchExecutionStatus.INTERRUPTED,
        ):
            execution = self._execution(status=status)
            self.assertTrue(execution.is_terminal)
            self.assertEqual(execution.revision, 1)
            self.assertEqual(execution.terminal_detail_hash, "9" * 64)

        started = self._execution()
        with self.assertRaisesRegex(DispatchExecutionModelError, "revision 0"):
            DispatchExecution(**{**started.to_dict(), "status": DispatchExecutionStatus.STARTED, "revision": 1})
        with self.assertRaisesRegex(DispatchExecutionModelError, "cannot have"):
            DispatchExecution(
                **{
                    **started.to_dict(),
                    "status": DispatchExecutionStatus.STARTED,
                    "terminal_detail_hash": "9" * 64,
                }
            )
        with self.assertRaisesRegex(DispatchExecutionModelError, "revision 1"):
            DispatchExecution(
                **{
                    **started.to_dict(),
                    "status": DispatchExecutionStatus.RETURNED,
                    "revision": 0,
                    "terminal_detail_hash": "9" * 64,
                }
            )
        with self.assertRaisesRegex(DispatchExecutionModelError, "terminal_detail_hash"):
            DispatchExecution(
                **{
                    **started.to_dict(),
                    "status": DispatchExecutionStatus.RETURNED,
                    "revision": 1,
                    "terminal_detail_hash": None,
                }
            )

    def test_malformed_authority_fields_fail_closed(self) -> None:
        execution = self._execution()
        cases = (
            ("execution_id", new_id(IdKind.DISPATCH_CLAIM)),
            ("claim_id", new_id(IdKind.DISPATCH_EXECUTION)),
            ("task_revision", -1),
            ("task_content_hash", "A" * 64),
            ("selected_adapter_id", " bad"),
            ("execution_owner_id", ""),
            ("execution_owner_fingerprint", "x" * 64),
            ("runtime_dependency_plan_hash", "5" * 63),
        )
        for field, value in cases:
            with self.subTest(field=field):
                with self.assertRaises(DispatchExecutionModelError):
                    DispatchExecution(**{**execution.to_dict(), field: value})

    def test_database_enforces_one_execution_per_claim_and_one_started_per_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("dispatch execution constraints")
            goal = runtime.create_goal("execution constraints")
            flow = runtime.create_flow(goal)
            task = runtime.create_task(flow, "one execution owner")
            project = runtime.project_id()

            def claim_values(status: str) -> dict[str, object]:
                claim = self._claim(
                    DispatchClaimStatus.ACTIVE
                    if status == "ACTIVE"
                    else DispatchClaimStatus.RELEASED
                )
                values = claim.to_dict()
                values["project_id"] = project
                values["task_id"] = task
                return values

            active = claim_values("ACTIVE")
            released = claim_values("RELEASED")
            with runtime.store.session() as conn:
                for values in (active, released):
                    conn.execute(
                        """INSERT INTO dispatch_claims(
                            claim_id, project_id, task_id, task_revision, task_content_hash,
                            work_order_id, work_order_hash,
                            work_order_audit_id, work_order_audit_hash,
                            input_resolution_id, input_resolution_hash,
                            dispatch_binding_id, dispatch_binding_hash,
                            binding_audit_id, binding_audit_hash,
                            selected_adapter_id, selected_adapter_fingerprint,
                            dispatch_contract_id, dispatch_contract_hash,
                            binder_id, binder_fingerprint,
                            status, revision, created_at, updated_at, terminal_reason
                        ) VALUES (
                            :claim_id, :project_id, :task_id, :task_revision, :task_content_hash,
                            :work_order_id, :work_order_hash,
                            :work_order_audit_id, :work_order_audit_hash,
                            :input_resolution_id, :input_resolution_hash,
                            :dispatch_binding_id, :dispatch_binding_hash,
                            :binding_audit_id, :binding_audit_hash,
                            :selected_adapter_id, :selected_adapter_fingerprint,
                            :dispatch_contract_id, :dispatch_contract_hash,
                            :binder_id, :binder_fingerprint,
                            :status, :revision, :created_at, :updated_at, :terminal_reason
                        )""",
                        values,
                    )

                first = self._execution(claim_id=str(active["claim_id"]), task_id=task)
                first_values = first.to_dict()
                first_values["project_id"] = project
                conn.execute(
                    """INSERT INTO dispatch_executions(
                        execution_id, project_id, claim_id, claim_revision_at_start,
                        task_id, task_revision, task_content_hash,
                        work_order_id, work_order_hash,
                        input_resolution_id, input_resolution_hash,
                        dispatch_binding_id, dispatch_binding_hash,
                        binding_audit_id, binding_audit_hash,
                        selected_adapter_id, selected_adapter_fingerprint,
                        dispatch_contract_id, dispatch_contract_hash,
                        binder_id, binder_fingerprint,
                        execution_owner_id, execution_owner_fingerprint,
                        runtime_dependency_plan_hash,
                        status, revision, created_at, updated_at, terminal_detail_hash
                    ) VALUES (
                        :execution_id, :project_id, :claim_id, :claim_revision_at_start,
                        :task_id, :task_revision, :task_content_hash,
                        :work_order_id, :work_order_hash,
                        :input_resolution_id, :input_resolution_hash,
                        :dispatch_binding_id, :dispatch_binding_hash,
                        :binding_audit_id, :binding_audit_hash,
                        :selected_adapter_id, :selected_adapter_fingerprint,
                        :dispatch_contract_id, :dispatch_contract_hash,
                        :binder_id, :binder_fingerprint,
                        :execution_owner_id, :execution_owner_fingerprint,
                        :runtime_dependency_plan_hash,
                        :status, :revision, :created_at, :updated_at, :terminal_detail_hash
                    )""",
                    first_values,
                )

                duplicate_claim = self._execution(
                    claim_id=str(active["claim_id"]),
                    task_id=task,
                )
                duplicate_values = duplicate_claim.to_dict()
                duplicate_values["project_id"] = project
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """INSERT INTO dispatch_executions(
                            execution_id, project_id, claim_id, claim_revision_at_start,
                            task_id, task_revision, task_content_hash,
                            work_order_id, work_order_hash,
                            input_resolution_id, input_resolution_hash,
                            dispatch_binding_id, dispatch_binding_hash,
                            binding_audit_id, binding_audit_hash,
                            selected_adapter_id, selected_adapter_fingerprint,
                            dispatch_contract_id, dispatch_contract_hash,
                            binder_id, binder_fingerprint,
                            execution_owner_id, execution_owner_fingerprint,
                            runtime_dependency_plan_hash,
                            status, revision, created_at, updated_at, terminal_detail_hash
                        ) VALUES (
                            :execution_id, :project_id, :claim_id, :claim_revision_at_start,
                            :task_id, :task_revision, :task_content_hash,
                            :work_order_id, :work_order_hash,
                            :input_resolution_id, :input_resolution_hash,
                            :dispatch_binding_id, :dispatch_binding_hash,
                            :binding_audit_id, :binding_audit_hash,
                            :selected_adapter_id, :selected_adapter_fingerprint,
                            :dispatch_contract_id, :dispatch_contract_hash,
                            :binder_id, :binder_fingerprint,
                            :execution_owner_id, :execution_owner_fingerprint,
                            :runtime_dependency_plan_hash,
                            :status, :revision, :created_at, :updated_at, :terminal_detail_hash
                        )""",
                        duplicate_values,
                    )

                second_claim = self._execution(
                    claim_id=str(released["claim_id"]),
                    task_id=task,
                )
                second_values = second_claim.to_dict()
                second_values["project_id"] = project
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """INSERT INTO dispatch_executions(
                            execution_id, project_id, claim_id, claim_revision_at_start,
                            task_id, task_revision, task_content_hash,
                            work_order_id, work_order_hash,
                            input_resolution_id, input_resolution_hash,
                            dispatch_binding_id, dispatch_binding_hash,
                            binding_audit_id, binding_audit_hash,
                            selected_adapter_id, selected_adapter_fingerprint,
                            dispatch_contract_id, dispatch_contract_hash,
                            binder_id, binder_fingerprint,
                            execution_owner_id, execution_owner_fingerprint,
                            runtime_dependency_plan_hash,
                            status, revision, created_at, updated_at, terminal_detail_hash
                        ) VALUES (
                            :execution_id, :project_id, :claim_id, :claim_revision_at_start,
                            :task_id, :task_revision, :task_content_hash,
                            :work_order_id, :work_order_hash,
                            :input_resolution_id, :input_resolution_hash,
                            :dispatch_binding_id, :dispatch_binding_hash,
                            :binding_audit_id, :binding_audit_hash,
                            :selected_adapter_id, :selected_adapter_fingerprint,
                            :dispatch_contract_id, :dispatch_contract_hash,
                            :binder_id, :binder_fingerprint,
                            :execution_owner_id, :execution_owner_fingerprint,
                            :runtime_dependency_plan_hash,
                            :status, :revision, :created_at, :updated_at, :terminal_detail_hash
                        )""",
                        second_values,
                    )

                conn.execute(
                    """UPDATE dispatch_executions
                       SET status = 'RETURNED', revision = 1,
                           terminal_detail_hash = ?
                       WHERE execution_id = ?""",
                    ("9" * 64, first.execution_id),
                )
                conn.execute(
                    """INSERT INTO dispatch_executions(
                        execution_id, project_id, claim_id, claim_revision_at_start,
                        task_id, task_revision, task_content_hash,
                        work_order_id, work_order_hash,
                        input_resolution_id, input_resolution_hash,
                        dispatch_binding_id, dispatch_binding_hash,
                        binding_audit_id, binding_audit_hash,
                        selected_adapter_id, selected_adapter_fingerprint,
                        dispatch_contract_id, dispatch_contract_hash,
                        binder_id, binder_fingerprint,
                        execution_owner_id, execution_owner_fingerprint,
                        runtime_dependency_plan_hash,
                        status, revision, created_at, updated_at, terminal_detail_hash
                    ) VALUES (
                        :execution_id, :project_id, :claim_id, :claim_revision_at_start,
                        :task_id, :task_revision, :task_content_hash,
                        :work_order_id, :work_order_hash,
                        :input_resolution_id, :input_resolution_hash,
                        :dispatch_binding_id, :dispatch_binding_hash,
                        :binding_audit_id, :binding_audit_hash,
                        :selected_adapter_id, :selected_adapter_fingerprint,
                        :dispatch_contract_id, :dispatch_contract_hash,
                        :binder_id, :binder_fingerprint,
                        :execution_owner_id, :execution_owner_fingerprint,
                        :runtime_dependency_plan_hash,
                        :status, :revision, :created_at, :updated_at, :terminal_detail_hash
                    )""",
                    second_values,
                )

            with runtime.store.session() as conn:
                rows = conn.execute(
                    "SELECT claim_id, status FROM dispatch_executions ORDER BY claim_id"
                ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["status"] for row in rows}, {"RETURNED", "STARTED"})


if __name__ == "__main__":
    unittest.main()
