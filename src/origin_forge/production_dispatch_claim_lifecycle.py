from __future__ import annotations

from .ids import IdKind, validate_id
from .production_dispatch_claim_models import (
    DispatchClaim,
    DispatchClaimModelError,
    DispatchClaimStatus,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


_MAX_REASON_CHARS = 4096


class DispatchClaimLifecycleError(RuntimeError):
    pass


def _validate_claim_args(claim_id: object, expected_revision: object) -> None:
    if not isinstance(claim_id, str) or not validate_id(
        claim_id, IdKind.DISPATCH_CLAIM
    ):
        raise DispatchClaimLifecycleError("claim_id must be a valid DISPCLAIM ID")
    if type(expected_revision) is not int or expected_revision < 0:
        raise DispatchClaimLifecycleError(
            "expected_revision must be a non-negative integer"
        )


def _interrupt_reason(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip() != value
        or len(value) > _MAX_REASON_CHARS
    ):
        raise DispatchClaimLifecycleError(
            "interruption reason must be bounded non-empty text"
        )
    return value


def _claim_from_row(row) -> DispatchClaim:
    try:
        return DispatchClaim(
            claim_id=row["claim_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            task_revision=int(row["task_revision"]),
            task_content_hash=row["task_content_hash"],
            work_order_id=row["work_order_id"],
            work_order_hash=row["work_order_hash"],
            work_order_audit_id=row["work_order_audit_id"],
            work_order_audit_hash=row["work_order_audit_hash"],
            input_resolution_id=row["input_resolution_id"],
            input_resolution_hash=row["input_resolution_hash"],
            dispatch_binding_id=row["dispatch_binding_id"],
            dispatch_binding_hash=row["dispatch_binding_hash"],
            binding_audit_id=row["binding_audit_id"],
            binding_audit_hash=row["binding_audit_hash"],
            selected_adapter_id=row["selected_adapter_id"],
            selected_adapter_fingerprint=row["selected_adapter_fingerprint"],
            dispatch_contract_id=row["dispatch_contract_id"],
            dispatch_contract_hash=row["dispatch_contract_hash"],
            binder_id=row["binder_id"],
            binder_fingerprint=row["binder_fingerprint"],
            status=DispatchClaimStatus(row["status"]),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_reason=row["terminal_reason"],
        )
    except (DispatchClaimModelError, KeyError, TypeError, ValueError) as exc:
        raise DispatchClaimLifecycleError(
            "stored dispatch claim failed canonical validation"
        ) from exc


def _terminalize_dispatch_claim(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_revision: int,
    *,
    target: DispatchClaimStatus,
    terminal_reason: str,
    event_type: str,
) -> DispatchClaim:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    _validate_claim_args(claim_id, expected_revision)
    if target not in {
        DispatchClaimStatus.RELEASED,
        DispatchClaimStatus.INTERRUPTED,
    }:
        raise DispatchClaimLifecycleError("claim lifecycle target must be terminal")

    project_id = runtime.project_id()
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM dispatch_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise DispatchClaimLifecycleError("dispatch claim does not exist")
        claim = _claim_from_row(row)
        if claim.project_id != project_id:
            raise DispatchClaimLifecycleError(
                "dispatch claim does not belong to the current project"
            )
        if claim.status is not DispatchClaimStatus.ACTIVE:
            raise DispatchClaimLifecycleError(
                f"dispatch claim is terminal: {claim.status.value}"
            )
        if claim.revision != expected_revision:
            raise StaleRevision(
                f"dispatch claim {claim_id} revision {claim.revision} != expected {expected_revision}"
            )

        new_revision = claim.revision + 1
        cursor = conn.execute(
            """UPDATE dispatch_claims
               SET status = ?, revision = ?, updated_at = ?, terminal_reason = ?
               WHERE claim_id = ? AND project_id = ?
                 AND status = 'ACTIVE' AND revision = ?""",
            (
                target.value,
                new_revision,
                now,
                terminal_reason,
                claim_id,
                project_id,
                claim.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision(
                f"dispatch claim {claim_id} changed concurrently"
            )

        runtime.store._append_event(
            conn,
            "DISPATCH_CLAIM",
            claim_id,
            event_type,
            DispatchClaimStatus.ACTIVE.value,
            target.value,
            new_revision,
            "SYSTEM",
            None,
            {
                "task_id": claim.task_id,
                "dispatch_binding_id": claim.dispatch_binding_id,
                "terminal_reason": terminal_reason,
            },
            now,
        )
        updated = conn.execute(
            "SELECT * FROM dispatch_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if updated is None:
            raise DispatchClaimLifecycleError(
                "dispatch claim disappeared during lifecycle transition"
            )
        result = _claim_from_row(updated)
        if result.frozen_authority_dict() != claim.frozen_authority_dict():
            raise DispatchClaimLifecycleError(
                "dispatch claim frozen authority changed during lifecycle transition"
            )
        return result


def release_dispatch_claim(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_revision: int,
) -> DispatchClaim:
    """Release one unused ACTIVE claim without changing Task or execution state."""

    return _terminalize_dispatch_claim(
        runtime,
        claim_id,
        expected_revision,
        target=DispatchClaimStatus.RELEASED,
        terminal_reason="claim released before execution authority was consumed",
        event_type="DISPATCH_CLAIM_RELEASED",
    )


def interrupt_dispatch_claim(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_revision: int,
    reason: str,
) -> DispatchClaim:
    """Explicitly interrupt one lost/abandoned ACTIVE claim after recovery review."""

    return _terminalize_dispatch_claim(
        runtime,
        claim_id,
        expected_revision,
        target=DispatchClaimStatus.INTERRUPTED,
        terminal_reason=_interrupt_reason(reason),
        event_type="DISPATCH_CLAIM_INTERRUPTED",
    )
