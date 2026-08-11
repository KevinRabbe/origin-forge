from __future__ import annotations

import ast
import inspect
import tempfile
import threading
import unittest

import origin_forge.production_dispatch_claim_lifecycle as lifecycle_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_claim_lifecycle import (
    DispatchClaimLifecycleError,
    interrupt_dispatch_claim,
    release_dispatch_claim,
)
from origin_forge.production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import StaleRevision


class ProductionDispatchClaimLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("dispatch-claim-lifecycle")
        goal_id = self.runtime.create_goal("claim lifecycle")
        flow_id = self.runtime.create_flow(goal_id)
        self.task_id = self.runtime.create_task(flow_id, "owned dispatch")
        self.project_id = self.runtime.project_id()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _claim(self, *, claim_id: str | None = None) -> DispatchClaim:
        return DispatchClaim(
            claim_id=claim_id or new_id(IdKind.DISPATCH_CLAIM),
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
            created_at="2026-08-11T18:00:00Z",
            updated_at="2026-08-11T18:00:00Z",
            terminal_reason=None,
        )

    def _insert(self, claim: DispatchClaim) -> None:
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

    def _row(self, claim_id: str):
        with self.runtime.store.session() as conn:
            return dict(
                conn.execute(
                    "SELECT * FROM dispatch_claims WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
            )

    def test_release_terminalizes_only_claim_and_preserves_frozen_authority(self) -> None:
        active = self._claim()
        self._insert(active)
        task_before = self.runtime.get_task(self.task_id)

        released = release_dispatch_claim(self.runtime, active.claim_id, 0)

        self.assertEqual(released.status, DispatchClaimStatus.RELEASED)
        self.assertEqual(released.revision, 1)
        self.assertEqual(
            released.terminal_reason,
            "claim released before execution authority was consumed",
        )
        self.assertEqual(active.frozen_authority_dict(), released.frozen_authority_dict())
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task_id), [])

        with self.runtime.store.session() as conn:
            events = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = 'DISPATCH_CLAIM'
                     AND aggregate_id = ?
                     AND event_type = 'DISPATCH_CLAIM_RELEASED'""",
                (active.claim_id,),
            ).fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["old_state"], "ACTIVE")
        self.assertEqual(events[0]["new_state"], "RELEASED")
        self.assertEqual(events[0]["revision"], 1)

    def test_interrupt_requires_explicit_bounded_reason_and_changes_no_task_state(self) -> None:
        active = self._claim()
        self._insert(active)
        task_before = self.runtime.get_task(self.task_id)

        with self.assertRaises(DispatchClaimLifecycleError):
            interrupt_dispatch_claim(self.runtime, active.claim_id, 0, "")
        with self.assertRaises(DispatchClaimLifecycleError):
            interrupt_dispatch_claim(self.runtime, active.claim_id, 0, " lost owner ")
        with self.assertRaises(DispatchClaimLifecycleError):
            interrupt_dispatch_claim(self.runtime, active.claim_id, 0, "x" * 4097)
        self.assertEqual(self._row(active.claim_id)["status"], "ACTIVE")

        interrupted = interrupt_dispatch_claim(
            self.runtime,
            active.claim_id,
            0,
            "owning process was explicitly confirmed lost",
        )
        self.assertEqual(interrupted.status, DispatchClaimStatus.INTERRUPTED)
        self.assertEqual(interrupted.revision, 1)
        self.assertEqual(
            interrupted.terminal_reason,
            "owning process was explicitly confirmed lost",
        )
        self.assertEqual(active.frozen_authority_dict(), interrupted.frozen_authority_dict())
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task_id), [])

    def test_stale_revision_and_terminal_rewrites_fail_closed(self) -> None:
        active = self._claim()
        self._insert(active)
        before = self._row(active.claim_id)
        with self.assertRaises(StaleRevision):
            release_dispatch_claim(self.runtime, active.claim_id, 7)
        self.assertEqual(self._row(active.claim_id), before)

        released = release_dispatch_claim(self.runtime, active.claim_id, 0)
        self.assertEqual(released.status, DispatchClaimStatus.RELEASED)
        terminal_row = self._row(active.claim_id)
        with self.assertRaises(DispatchClaimLifecycleError):
            release_dispatch_claim(self.runtime, active.claim_id, 1)
        with self.assertRaises(DispatchClaimLifecycleError):
            interrupt_dispatch_claim(
                self.runtime,
                active.claim_id,
                1,
                "cannot rewrite terminal claim",
            )
        self.assertEqual(self._row(active.claim_id), terminal_row)

    def test_active_claim_survives_restart_and_blocks_duplicate_until_explicit_interruption(self) -> None:
        active = self._claim()
        self._insert(active)

        restarted = OriginForgeRuntime(self.tempdir.name)
        with restarted.store.session() as conn:
            persisted = conn.execute(
                "SELECT status, revision FROM dispatch_claims WHERE claim_id = ?",
                (active.claim_id,),
            ).fetchone()
            self.assertEqual((persisted["status"], persisted["revision"]), ("ACTIVE", 0))

        duplicate = self._claim()
        with self.assertRaises(Exception):
            self._insert(duplicate)

        interrupted = interrupt_dispatch_claim(
            restarted,
            active.claim_id,
            0,
            "explicit restart recovery",
        )
        self.assertEqual(interrupted.status, DispatchClaimStatus.INTERRUPTED)
        self._insert(duplicate)
        self.assertEqual(self._row(duplicate.claim_id)["status"], "ACTIVE")

    def test_concurrent_terminalization_has_exactly_one_winner(self) -> None:
        active = self._claim()
        self._insert(active)
        barrier = threading.Barrier(2)
        successes: list[DispatchClaim] = []
        failures: list[BaseException] = []
        lock = threading.Lock()

        def release_worker() -> None:
            barrier.wait()
            try:
                result = release_dispatch_claim(self.runtime, active.claim_id, 0)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    successes.append(result)

        def interrupt_worker() -> None:
            barrier.wait()
            try:
                result = interrupt_dispatch_claim(
                    self.runtime,
                    active.claim_id,
                    0,
                    "concurrent explicit interruption",
                )
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    successes.append(result)

        threads = [
            threading.Thread(target=release_worker),
            threading.Thread(target=interrupt_worker),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(
            failures[0],
            (DispatchClaimLifecycleError, StaleRevision),
        )
        row = self._row(active.claim_id)
        self.assertIn(row["status"], {"RELEASED", "INTERRUPTED"})
        self.assertEqual(row["revision"], 1)

        with self.runtime.store.session() as conn:
            events = conn.execute(
                """SELECT event_type FROM state_events
                   WHERE aggregate_type = 'DISPATCH_CLAIM'
                     AND aggregate_id = ?
                     AND event_type IN (
                         'DISPATCH_CLAIM_RELEASED',
                         'DISPATCH_CLAIM_INTERRUPTED'
                     )""",
                (active.claim_id,),
            ).fetchall()
        self.assertEqual(len(events), 1)

    def test_lifecycle_surface_contains_no_execution_authority(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(release_dispatch_claim).parameters),
            ("runtime", "claim_id", "expected_revision"),
        )
        self.assertEqual(
            tuple(inspect.signature(interrupt_dispatch_claim).parameters),
            ("runtime", "claim_id", "expected_revision", "reason"),
        )
        source = inspect.getsource(lifecycle_module)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("importlib", source)
        tree = ast.parse(source)
        forbidden = {
            "drive",
            "generate",
            "dispatch",
            "start_run",
            "create_run",
            "finish_run",
            "record_verification",
            "create_workspace",
            "transition_task",
            "transition_flow",
            "transition_goal",
            "acquire_dispatch_claim",
            "lease",
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
        self.assertTrue(forbidden.isdisjoint(called))
        execute_receivers = [
            node.func.value.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and isinstance(node.func.value, ast.Name)
        ]
        self.assertTrue(execute_receivers)
        self.assertEqual(set(execute_receivers), {"conn"})


if __name__ == "__main__":
    unittest.main()
