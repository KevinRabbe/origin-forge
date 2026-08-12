from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    ProductionDispatchClaimReadError,
    inspect_dispatch_claim_currentness_readonly,
)
from .production_dispatch_execution_read import (
    DispatchExecutionCurrentnessStatus,
    inspect_dispatch_execution_currentness_readonly,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime


_MAX_DETAIL_CHARS = 1024


class ProductionDispatchInvocationReadError(RuntimeError):
    pass


class DispatchInvocationStatus(StrEnum):
    READY_TO_INVOKE = "READY_TO_INVOKE"
    STARTED_RECOVERY_REQUIRED = "STARTED_RECOVERY_REQUIRED"
    RETURNED = "RETURNED"
    RAISED = "RAISED"
    INTERRUPTED = "INTERRUPTED"
    STALE_OR_INVALID = "STALE_OR_INVALID"


@dataclass(frozen=True)
class DispatchInvocationStatusProjection:
    claim_id: str
    task_id: str | None
    execution_id: str | None
    status: DispatchInvocationStatus
    detail: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not validate_id(
            self.claim_id,
            IdKind.DISPATCH_CLAIM,
        ):
            raise ProductionDispatchInvocationReadError(
                "invocation status requires a valid DISPCLAIM ID"
            )
        if self.task_id is not None and (
            not isinstance(self.task_id, str)
            or not validate_id(self.task_id, IdKind.TASK)
        ):
            raise ProductionDispatchInvocationReadError(
                "invocation status task_id is invalid"
            )
        if self.execution_id is not None and (
            not isinstance(self.execution_id, str)
            or not validate_id(self.execution_id, IdKind.DISPATCH_EXECUTION)
        ):
            raise ProductionDispatchInvocationReadError(
                "invocation status execution_id is invalid"
            )
        if not isinstance(self.status, DispatchInvocationStatus):
            raise ProductionDispatchInvocationReadError(
                "invocation status value is invalid"
            )
        if self.detail is not None and (
            not isinstance(self.detail, str)
            or not self.detail
            or len(self.detail) > _MAX_DETAIL_CHARS
        ):
            raise ProductionDispatchInvocationReadError(
                "invocation status detail is invalid or unbounded"
            )
        if self.status in {
            DispatchInvocationStatus.STARTED_RECOVERY_REQUIRED,
            DispatchInvocationStatus.RETURNED,
            DispatchInvocationStatus.RAISED,
            DispatchInvocationStatus.INTERRUPTED,
        } and self.execution_id is None:
            raise ProductionDispatchInvocationReadError(
                "execution-backed invocation status requires execution_id"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "status": self.status.value,
            "detail": self.detail,
        }


def _bounded_detail(value: object) -> str:
    text = value if isinstance(value, str) and value else "invocation state is stale or invalid"
    if len(text) <= _MAX_DETAIL_CHARS:
        return text
    suffix = "... [truncated]"
    return text[: _MAX_DETAIL_CHARS - len(suffix)] + suffix


def _validate_inputs(runtime: OriginForgeRuntime, claim_id: object) -> str:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(claim_id, str) or not validate_id(
        claim_id,
        IdKind.DISPATCH_CLAIM,
    ):
        raise ProductionDispatchInvocationReadError(
            "claim_id must be a valid DISPCLAIM ID"
        )
    return claim_id


def _execution_ids_for_claim_readonly(
    runtime: OriginForgeRuntime,
    claim_id: str,
) -> tuple[str, ...]:
    try:
        with production_read_connection(runtime) as conn:
            rows = conn.execute(
                """SELECT execution_id
                   FROM dispatch_executions
                   WHERE claim_id = ?
                   ORDER BY created_at ASC, execution_id ASC
                   LIMIT 2""",
                (claim_id,),
            ).fetchall()
    except ProductionReadGuardError as exc:
        raise ProductionDispatchInvocationReadError(str(exc)) from exc
    execution_ids = tuple(row["execution_id"] for row in rows)
    if any(
        not isinstance(execution_id, str)
        or not validate_id(execution_id, IdKind.DISPATCH_EXECUTION)
        for execution_id in execution_ids
    ):
        raise ProductionDispatchInvocationReadError(
            "stored dispatch execution identity is invalid"
        )
    return execution_ids


def inspect_dispatch_invocation_status_readonly(
    runtime: OriginForgeRuntime,
    claim_id: str,
) -> DispatchInvocationStatusProjection:
    """Project one claim into bounded invocation/recovery status without mutation."""

    claim_id = _validate_inputs(runtime, claim_id)
    try:
        claim_currentness = inspect_dispatch_claim_currentness_readonly(
            runtime,
            claim_id,
        )
    except ProductionDispatchClaimReadError as exc:
        return DispatchInvocationStatusProjection(
            claim_id,
            None,
            None,
            DispatchInvocationStatus.STALE_OR_INVALID,
            _bounded_detail(str(exc)),
        )

    try:
        execution_ids = _execution_ids_for_claim_readonly(runtime, claim_id)
    except ProductionDispatchInvocationReadError as exc:
        return DispatchInvocationStatusProjection(
            claim_id,
            claim_currentness.task_id,
            None,
            DispatchInvocationStatus.STALE_OR_INVALID,
            _bounded_detail(str(exc)),
        )

    if len(execution_ids) > 1:
        return DispatchInvocationStatusProjection(
            claim_id,
            claim_currentness.task_id,
            None,
            DispatchInvocationStatus.STALE_OR_INVALID,
            "dispatch claim has more than one execution receipt",
        )

    if not execution_ids:
        if claim_currentness.status is DispatchClaimCurrentnessStatus.CURRENT_ACTIVE:
            return DispatchInvocationStatusProjection(
                claim_id,
                claim_currentness.task_id,
                None,
                DispatchInvocationStatus.READY_TO_INVOKE,
                None,
            )
        return DispatchInvocationStatusProjection(
            claim_id,
            claim_currentness.task_id,
            None,
            DispatchInvocationStatus.STALE_OR_INVALID,
            _bounded_detail(
                claim_currentness.detail
                or f"claim currentness is {claim_currentness.status.value} without execution receipt"
            ),
        )

    execution_id = execution_ids[0]
    execution_currentness = inspect_dispatch_execution_currentness_readonly(
        runtime,
        execution_id,
    )
    if (
        execution_currentness.claim_id is not None
        and execution_currentness.claim_id != claim_id
    ):
        return DispatchInvocationStatusProjection(
            claim_id,
            claim_currentness.task_id,
            execution_id,
            DispatchInvocationStatus.STALE_OR_INVALID,
            "execution currentness does not bind the requested claim",
        )
    task_id = execution_currentness.task_id or claim_currentness.task_id
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
    mapped = mapping.get(execution_currentness.status)
    if mapped is not None:
        return DispatchInvocationStatusProjection(
            claim_id,
            task_id,
            execution_id,
            mapped,
            None,
        )
    return DispatchInvocationStatusProjection(
        claim_id,
        task_id,
        execution_id,
        DispatchInvocationStatus.STALE_OR_INVALID,
        _bounded_detail(
            execution_currentness.detail
            or f"execution currentness is {execution_currentness.status.value}"
        ),
    )
