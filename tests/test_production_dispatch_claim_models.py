from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_dispatch_claim_models import (
    DispatchClaim,
    DispatchClaimModelError,
    DispatchClaimStatus,
)
from origin_forge.runtime import OriginForgeRuntime


_HASH = "a" * 64


def _claim(**overrides: object) -> DispatchClaim:
    values: dict[str, object] = {
        "claim_id": new_id(IdKind.DISPATCH_CLAIM),
        "project_id": new_id(IdKind.PROJECT),
        "task_id": new_id(IdKind.TASK),
        "task_revision": 3,
        "task_content_hash": _HASH,
        "work_order_id": new_id(IdKind.PRODUCTION_WORK_ORDER),
        "work_order_hash": "b" * 64,
        "work_order_audit_id": new_id(IdKind.WORK_ORDER_AUDIT),
        "work_order_audit_hash": "c" * 64,
        "input_resolution_id": new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
        "input_resolution_hash": "d" * 64,
        "dispatch_binding_id": new_id(IdKind.DISPATCH_BINDING),
        "dispatch_binding_hash": "e" * 64,
        "binding_audit_id": new_id(IdKind.DISPATCH_BINDING_AUDIT),
        "binding_audit_hash": "f" * 64,
        "selected_adapter_id": "originforge.code.bounded-retry",
        "selected_adapter_fingerprint": "1" * 64,
        "dispatch_contract_id": "code.bounded-retry@1",
        "dispatch_contract_hash": "2" * 64,
        "binder_id": "binder.code.bounded-retry@1",
        "binder_fingerprint": "3" * 64,
        "status": DispatchClaimStatus.ACTIVE,
        "revision": 0,
        "created_at": "2026-08-11T18:00:00Z",
        "updated_at": "2026-08-11T18:00:00Z",
        "terminal_reason": None,
    }
    values.update(overrides)
    return DispatchClaim(**values)


class ProductionDispatchClaimModelTests(unittest.TestCase):
    def test_phase35_id_family_uses_existing_opaque_id_contract(self) -> None:
        claim_id = new_id(IdKind.DISPATCH_CLAIM)
        self.assertTrue(validate_id(claim_id, IdKind.DISPATCH_CLAIM))
        self.assertTrue(claim_id.startswith("DISPCLAIM-"))

    def test_active_claim_is_exact_typed_frozen_authority(self) -> None:
        claim = _claim()
        self.assertTrue(claim.is_active)
        self.assertEqual(claim.status, DispatchClaimStatus.ACTIVE)
        frozen = claim.frozen_authority_dict()
        self.assertEqual(frozen["task_revision"], 3)
        self.assertEqual(frozen["task_content_hash"], _HASH)
        self.assertEqual(
            frozen["selected_adapter_id"],
            "originforge.code.bounded-retry",
        )
        self.assertEqual(claim.to_dict()["terminal_reason"], None)
        self.assertNotIn("pid", claim.to_dict())
        self.assertNotIn("hostname", claim.to_dict())
        self.assertNotIn("expires_at", claim.to_dict())
        self.assertNotIn("callable", claim.to_dict())

    def test_terminal_claim_requires_reason_and_active_claim_forbids_one(self) -> None:
        with self.assertRaisesRegex(DispatchClaimModelError, "ACTIVE"):
            _claim(terminal_reason="should not exist")
        with self.assertRaisesRegex(DispatchClaimModelError, "terminal claim"):
            _claim(status=DispatchClaimStatus.RELEASED)
        released = _claim(
            status=DispatchClaimStatus.RELEASED,
            revision=1,
            terminal_reason="claim released before execution",
        )
        self.assertFalse(released.is_active)
        self.assertEqual(released.revision, 1)

    def test_ids_hashes_revisions_and_identity_text_fail_closed(self) -> None:
        bad_cases = (
            {"claim_id": new_id(IdKind.RUN)},
            {"task_id": new_id(IdKind.FLOW)},
            {"dispatch_binding_id": new_id(IdKind.WORK_ORDER_AUDIT)},
            {"binding_audit_id": new_id(IdKind.DISPATCH_BINDING)},
            {"task_revision": False},
            {"revision": -1},
            {"work_order_hash": "A" * 64},
            {"binder_fingerprint": "short"},
            {"selected_adapter_id": " originforge.code.bounded-retry"},
            {"binder_id": "binder\ncode"},
        )
        for values in bad_cases:
            with self.subTest(values=values):
                with self.assertRaises(DispatchClaimModelError):
                    _claim(**values)

    def test_status_must_be_typed_not_caller_string(self) -> None:
        with self.assertRaisesRegex(DispatchClaimModelError, "DispatchClaimStatus"):
            _claim(status="ACTIVE")

    def test_lifecycle_change_does_not_rewrite_frozen_authority_fields(self) -> None:
        active = _claim()
        released = replace(
            active,
            status=DispatchClaimStatus.RELEASED,
            revision=1,
            updated_at="2026-08-11T18:01:00Z",
            terminal_reason="unused claim released",
        )
        self.assertEqual(active.frozen_authority_dict(), released.frozen_authority_dict())

    def test_database_enforces_one_active_claim_per_task_but_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = OriginForgeRuntime(directory)
            runtime.initialize("dispatch-claim-index")
            goal_id = runtime.create_goal("claim concurrency")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(flow_id, "one dispatch owner")
            project_id = runtime.project_id()

            def row(claim_id: str, status: str, terminal_reason: str | None):
                return (
                    claim_id,
                    project_id,
                    task_id,
                    0,
                    "a" * 64,
                    new_id(IdKind.PRODUCTION_WORK_ORDER),
                    "b" * 64,
                    new_id(IdKind.WORK_ORDER_AUDIT),
                    "c" * 64,
                    new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
                    "d" * 64,
                    new_id(IdKind.DISPATCH_BINDING),
                    "e" * 64,
                    new_id(IdKind.DISPATCH_BINDING_AUDIT),
                    "f" * 64,
                    "originforge.code.bounded-retry",
                    "1" * 64,
                    "code.bounded-retry@1",
                    "2" * 64,
                    "binder.code.bounded-retry@1",
                    "3" * 64,
                    status,
                    0,
                    "2026-08-11T18:00:00Z",
                    "2026-08-11T18:00:00Z",
                    terminal_reason,
                )

            sql = """INSERT INTO dispatch_claims(
                claim_id, project_id, task_id, task_revision, task_content_hash,
                work_order_id, work_order_hash, work_order_audit_id, work_order_audit_hash,
                input_resolution_id, input_resolution_hash,
                dispatch_binding_id, dispatch_binding_hash,
                binding_audit_id, binding_audit_hash,
                selected_adapter_id, selected_adapter_fingerprint,
                dispatch_contract_id, dispatch_contract_hash,
                binder_id, binder_fingerprint,
                status, revision, created_at, updated_at, terminal_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

            first_id = new_id(IdKind.DISPATCH_CLAIM)
            second_id = new_id(IdKind.DISPATCH_CLAIM)
            with runtime.store.session() as conn:
                conn.execute(sql, row(first_id, "ACTIVE", None))
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql, row(second_id, "ACTIVE", None))

            with runtime.store.session() as conn:
                conn.execute(
                    """UPDATE dispatch_claims
                       SET status = 'RELEASED', revision = 1,
                           updated_at = '2026-08-11T18:01:00Z',
                           terminal_reason = 'unused claim released'
                       WHERE claim_id = ?""",
                    (first_id,),
                )
                conn.execute(sql, row(second_id, "ACTIVE", None))
                states = [
                    tuple(value)
                    for value in conn.execute(
                        "SELECT claim_id, status FROM dispatch_claims WHERE task_id = ? ORDER BY claim_id",
                        (task_id,),
                    ).fetchall()
                ]
            self.assertEqual(len(states), 2)
            self.assertEqual({status for _, status in states}, {"ACTIVE", "RELEASED"})


if __name__ == "__main__":
    unittest.main()
