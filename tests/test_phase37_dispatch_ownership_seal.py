from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest

import origin_forge.production_dispatch_claim_lifecycle as claim_lifecycle_module
from origin_forge.ids import IdKind, new_id
from origin_forge.migrations import LATEST_SCHEMA_VERSION, MIGRATION_010
from origin_forge.production_dispatch_claim_lifecycle import (
    DispatchClaimLifecycleError,
    interrupt_dispatch_claim,
    release_dispatch_claim,
)
from origin_forge.production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
from origin_forge.production_dispatch_execution import (
    interrupt_dispatch_execution,
    mark_dispatch_execution_returned,
)
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.runtime import OriginForgeRuntime


_TRIGGER = "dispatch_claims_started_execution_seals_legacy_terminalization"


class Phase37DispatchOwnershipSealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("phase37-ownership-seal")
        goal_id = self.runtime.create_goal("seal dispatch execution ownership")
        flow_id = self.runtime.create_flow(goal_id)
        self.task_id = self.runtime.create_task(flow_id, "owned dispatch")
        self.project_id = self.runtime.project_id()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _claim(self) -> DispatchClaim:
        return DispatchClaim(
            claim_id=new_id(IdKind.DISPATCH_CLAIM),
            project_id=self.project_id,
            task_id=self.task_id,
            task_revision=0,
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
            status=DispatchClaimStatus.ACTIVE,
            revision=0,
            created_at="2026-08-12T12:00:00Z",
            updated_at="2026-08-12T12:00:00Z",
            terminal_reason=None,
        )

    def _insert_claim(self, claim: DispatchClaim) -> None:
        values = claim.to_dict()
        with self.runtime.store.session() as conn:
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

    def _insert_started_execution(self, claim: DispatchClaim) -> str:
        execution_id = new_id(IdKind.DISPATCH_EXECUTION)
        with self.runtime.store.session() as conn:
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
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, 'STARTED', 0, ?, ?, NULL
                )""",
                (
                    execution_id,
                    claim.project_id,
                    claim.claim_id,
                    claim.revision,
                    claim.task_id,
                    claim.task_revision,
                    claim.task_content_hash,
                    claim.work_order_id,
                    claim.work_order_hash,
                    claim.input_resolution_id,
                    claim.input_resolution_hash,
                    claim.dispatch_binding_id,
                    claim.dispatch_binding_hash,
                    claim.binding_audit_id,
                    claim.binding_audit_hash,
                    claim.selected_adapter_id,
                    claim.selected_adapter_fingerprint,
                    claim.dispatch_contract_id,
                    claim.dispatch_contract_hash,
                    claim.binder_id,
                    claim.binder_fingerprint,
                    "originforge.execution.bounded-retry@1",
                    "4" * 64,
                    "5" * 64,
                    claim.created_at,
                    claim.updated_at,
                ),
            )
        return execution_id

    def _claim_row(self, claim_id: str) -> dict:
        with self.runtime.store.session() as conn:
            return dict(
                conn.execute(
                    "SELECT * FROM dispatch_claims WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
            )

    def _execution_row(self, execution_id: str) -> dict:
        with self.runtime.store.session() as conn:
            return dict(
                conn.execute(
                    "SELECT * FROM dispatch_executions WHERE execution_id = ?",
                    (execution_id,),
                ).fetchone()
            )

    def test_schema_v10_installs_exact_ownership_trigger(self) -> None:
        self.assertEqual(LATEST_SCHEMA_VERSION, 10)
        with self.runtime.store.session() as conn:
            version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            trigger = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                (_TRIGGER,),
            ).fetchone()
        self.assertEqual(version, 10)
        self.assertIsNotNone(trigger)
        self.assertIn("status = 'STARTED'", trigger["sql"])
        self.assertIn("'RELEASED', 'INTERRUPTED'", trigger["sql"])

    def test_migration_010_is_row_preserving_trigger_only(self) -> None:
        claim = self._claim()
        self._insert_claim(claim)
        execution_id = self._insert_started_execution(claim)
        claim_before = self._claim_row(claim.claim_id)
        execution_before = self._execution_row(execution_id)

        upper = MIGRATION_010.upper()
        self.assertEqual(upper.count("CREATE TRIGGER"), 1)
        for forbidden in ("INSERT INTO", "DELETE FROM", "DROP TABLE", "ALTER TABLE"):
            self.assertNotIn(forbidden, upper)

        with self.runtime.store.session() as conn:
            conn.execute(f"DROP TRIGGER {_TRIGGER}")
            conn.executescript(MIGRATION_010)

        self.assertEqual(self._claim_row(claim.claim_id), claim_before)
        self.assertEqual(self._execution_row(execution_id), execution_before)

    def test_legacy_release_and_interrupt_refuse_started_execution(self) -> None:
        claim = self._claim()
        self._insert_claim(claim)
        execution_id = self._insert_started_execution(claim)
        claim_before = self._claim_row(claim.claim_id)
        execution_before = self._execution_row(execution_id)

        with self.assertRaisesRegex(
            DispatchClaimLifecycleError,
            "STARTED execution",
        ):
            release_dispatch_claim(self.runtime, claim.claim_id, 0)
        with self.assertRaisesRegex(
            DispatchClaimLifecycleError,
            "STARTED execution",
        ):
            interrupt_dispatch_claim(
                self.runtime,
                claim.claim_id,
                0,
                "legacy recovery must not break execution ownership",
            )

        self.assertEqual(self._claim_row(claim.claim_id), claim_before)
        self.assertEqual(self._execution_row(execution_id), execution_before)

    def test_database_trigger_blocks_direct_legacy_terminalization(self) -> None:
        for target in ("RELEASED", "INTERRUPTED"):
            with self.subTest(target=target):
                claim = self._claim()
                self._insert_claim(claim)
                execution_id = self._insert_started_execution(claim)
                with self.assertRaisesRegex(
                    sqlite3.IntegrityError,
                    "STARTED execution must use execution lifecycle terminalization",
                ):
                    with self.runtime.store.session() as conn:
                        conn.execute(
                            """UPDATE dispatch_claims
                               SET status = ?, revision = 1,
                                   terminal_reason = 'forged legacy terminalization'
                               WHERE claim_id = ?""",
                            (target, claim.claim_id),
                        )
                self.assertEqual(self._claim_row(claim.claim_id)["status"], "ACTIVE")
                self.assertEqual(self._execution_row(execution_id)["status"], "STARTED")

                interrupt_dispatch_execution(
                    self.runtime,
                    execution_id,
                    0,
                    0,
                    "cleanup after direct trigger proof",
                )

    def test_execution_specific_interruption_remains_legal_through_trigger(self) -> None:
        claim = self._claim()
        self._insert_claim(claim)
        execution_id = self._insert_started_execution(claim)

        execution = interrupt_dispatch_execution(
            self.runtime,
            execution_id,
            0,
            0,
            "explicit execution recovery",
        )

        self.assertEqual(execution.status, DispatchExecutionStatus.INTERRUPTED)
        self.assertEqual(execution.revision, 1)
        claim_after = self._claim_row(claim.claim_id)
        self.assertEqual(claim_after["status"], "INTERRUPTED")
        self.assertEqual(claim_after["revision"], 1)
        self.assertEqual(self._execution_row(execution_id)["status"], "INTERRUPTED")

    def test_returned_terminalization_remains_legal_and_consumes_claim(self) -> None:
        claim = self._claim()
        self._insert_claim(claim)
        execution_id = self._insert_started_execution(claim)

        execution = mark_dispatch_execution_returned(
            self.runtime,
            execution_id,
            0,
            0,
            "trusted execution owner returned",
        )

        self.assertEqual(execution.status, DispatchExecutionStatus.RETURNED)
        claim_after = self._claim_row(claim.claim_id)
        self.assertEqual(claim_after["status"], "CONSUMED")
        self.assertEqual(claim_after["revision"], 1)

    def test_legacy_lifecycle_without_execution_keeps_phase35_semantics(self) -> None:
        claim = self._claim()
        self._insert_claim(claim)
        released = release_dispatch_claim(self.runtime, claim.claim_id, 0)
        self.assertEqual(released.status, DispatchClaimStatus.RELEASED)

        second = self._claim()
        self._insert_claim(second)
        interrupted = interrupt_dispatch_claim(
            self.runtime,
            second.claim_id,
            0,
            "explicit pre-execution recovery",
        )
        self.assertEqual(interrupted.status, DispatchClaimStatus.INTERRUPTED)

    def test_37a_modules_contain_no_owner_invocation(self) -> None:
        source = inspect.getsource(claim_lifecycle_module)
        self.assertNotIn(".drive(", source)
        self.assertNotIn(".generate(", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("importlib", source)


if __name__ == "__main__":
    unittest.main()
