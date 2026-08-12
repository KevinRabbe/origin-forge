from __future__ import annotations

from dataclasses import dataclass

from .ids import IdKind, new_id, validate_id
from .production_capability_routing import task_routing_hash
from .production_dispatch_claim_models import (
    DispatchClaim,
    DispatchClaimModelError,
    DispatchClaimStatus,
)
from .production_dispatch_execution_models import (
    DispatchExecution,
    DispatchExecutionModelError,
    DispatchExecutionStatus,
)
from .production_execution_assembly import (
    ProductionExecutionDependencies,
    assemble_production_execution_dependencies,
)
from .production_work_order_models import content_hash
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now
from .state import TaskStatus
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


_MAX_DETAIL_CHARS = 4096


class ProductionDispatchExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class StartedDispatchExecution:
    execution: DispatchExecution
    dependencies: ProductionExecutionDependencies

    def __post_init__(self) -> None:
        if not isinstance(self.execution, DispatchExecution):
            raise TypeError("execution must be a DispatchExecution")
        if not isinstance(self.dependencies, ProductionExecutionDependencies):
            raise TypeError("dependencies must be ProductionExecutionDependencies")
        if self.execution.status is not DispatchExecutionStatus.STARTED:
            raise ProductionDispatchExecutionError(
                "started execution wrapper requires a STARTED receipt"
            )
        if (
            self.execution.claim_id != self.dependencies.plan.claim_id
            or self.execution.task_id != self.dependencies.plan.task_id
            or self.execution.dispatch_binding_id
            != self.dependencies.plan.dispatch_binding_id
            or self.execution.execution_owner_id != self.dependencies.plan.owner_id
            or self.execution.execution_owner_fingerprint
            != self.dependencies.plan.owner_fingerprint
            or self.execution.runtime_dependency_plan_hash
            != self.dependencies.plan.plan_hash
        ):
            raise ProductionDispatchExecutionError(
                "STARTED receipt does not match assembled dependency authority"
            )


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
        raise ProductionDispatchExecutionError(
            "stored dispatch claim failed canonical validation"
        ) from exc


def _execution_from_row(row) -> DispatchExecution:
    try:
        return DispatchExecution(
            execution_id=row["execution_id"],
            project_id=row["project_id"],
            claim_id=row["claim_id"],
            claim_revision_at_start=int(row["claim_revision_at_start"]),
            task_id=row["task_id"],
            task_revision=int(row["task_revision"]),
            task_content_hash=row["task_content_hash"],
            work_order_id=row["work_order_id"],
            work_order_hash=row["work_order_hash"],
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
            execution_owner_id=row["execution_owner_id"],
            execution_owner_fingerprint=row["execution_owner_fingerprint"],
            runtime_dependency_plan_hash=row["runtime_dependency_plan_hash"],
            status=DispatchExecutionStatus(row["status"]),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_detail_hash=row["terminal_detail_hash"],
        )
    except (DispatchExecutionModelError, KeyError, TypeError, ValueError) as exc:
        raise ProductionDispatchExecutionError(
            "stored dispatch execution failed canonical validation"
        ) from exc


def _expected_revision(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ProductionDispatchExecutionError(
            "expected_revision must be a non-negative integer"
        )
    return value


def _bounded_detail(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip() != value
        or len(value) > _MAX_DETAIL_CHARS
        or any(ord(char) < 32 and char not in "\n\t" for char in value)
        or any(ord(char) == 127 for char in value)
    ):
        raise ProductionDispatchExecutionError(
            f"{label} must be bounded non-empty text"
        )
    return value


def _terminal_detail_hash(status: DispatchExecutionStatus, detail: str) -> str:
    return content_hash({"status": status.value, "detail": detail})


def _validate_transactional_task_currentness(conn, claim: DispatchClaim) -> None:
    row = conn.execute(
        """SELECT t.*, g.project_id
           FROM tasks t
           JOIN flows f ON f.id = t.flow_id
           JOIN goals g ON g.id = f.goal_id
           WHERE t.id = ?""",
        (claim.task_id,),
    ).fetchone()
    if row is None or row["project_id"] != claim.project_id:
        raise ProductionDispatchExecutionError(
            "claim Task no longer belongs to the current project"
        )
    try:
        task_status = TaskStatus(row["status"])
        readiness = resolve_task_dependency_readiness_connection(conn, claim.task_id)
        current_hash = task_routing_hash(row)
    except (TaskReadinessError, TypeError, ValueError) as exc:
        raise ProductionDispatchExecutionError(
            "claim Task currentness could not be derived transactionally"
        ) from exc
    if (
        int(row["revision"]) != claim.task_revision
        or current_hash != claim.task_content_hash
    ):
        raise ProductionDispatchExecutionError(
            "claim Task revision/content changed before execution ownership"
        )
    if (
        task_status is not TaskStatus.READY
        or readiness.task_status is not TaskStatus.READY
        or readiness.status is not DependencyReadinessStatus.READY
    ):
        raise ProductionDispatchExecutionError(
            "claim Task is no longer READY and dependency-ready"
        )


def begin_dispatch_execution(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_revision: int,
) -> StartedDispatchExecution:
    """Consume one exact current claim and create one STARTED receipt atomically.

    Dependencies are assembled before the transaction but are never invoked.
    The returned wrapper retains those exact lazy dependencies for the later
    execution boundary; this function itself stops before model/sandbox policy
    execution.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(claim_id, str) or not validate_id(
        claim_id,
        IdKind.DISPATCH_CLAIM,
    ):
        raise ProductionDispatchExecutionError(
            "claim_id must be a valid DISPCLAIM ID"
        )
    expected_revision = _expected_revision(expected_revision)

    dependencies = assemble_production_execution_dependencies(runtime, claim_id)
    if dependencies.plan.claim_revision != expected_revision:
        raise StaleRevision(
            f"dispatch claim {claim_id} dependency plan revision "
            f"{dependencies.plan.claim_revision} != expected {expected_revision}"
        )

    project_id = runtime.project_id()
    execution_id = new_id(IdKind.DISPATCH_EXECUTION)
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM dispatch_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise ProductionDispatchExecutionError("dispatch claim does not exist")
        claim = _claim_from_row(row)
        if claim.project_id != project_id:
            raise ProductionDispatchExecutionError(
                "dispatch claim does not belong to the current project"
            )
        if claim.status is not DispatchClaimStatus.ACTIVE:
            raise ProductionDispatchExecutionError(
                f"dispatch claim is not ACTIVE: {claim.status.value}"
            )
        if claim.revision != expected_revision:
            raise StaleRevision(
                f"dispatch claim {claim_id} revision {claim.revision} != expected {expected_revision}"
            )
        if (
            claim.task_id != dependencies.plan.task_id
            or claim.task_revision != dependencies.plan.task_revision
            or claim.task_content_hash != dependencies.plan.task_content_hash
            or claim.dispatch_binding_id != dependencies.plan.dispatch_binding_id
            or claim.dispatch_binding_hash != dependencies.plan.dispatch_binding_hash
        ):
            raise ProductionDispatchExecutionError(
                "assembled dependency plan no longer matches exact claim authority"
            )
        _validate_transactional_task_currentness(conn, claim)

        existing = conn.execute(
            "SELECT execution_id FROM dispatch_executions WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if existing is not None:
            raise ProductionDispatchExecutionError(
                "dispatch claim already has an execution receipt"
            )

        consumed_revision = claim.revision + 1
        terminal_reason = f"claim consumed by dispatch execution {execution_id}"
        cursor = conn.execute(
            """UPDATE dispatch_claims
               SET status = 'CONSUMED', revision = ?, updated_at = ?, terminal_reason = ?
               WHERE claim_id = ? AND project_id = ?
                 AND status = 'ACTIVE' AND revision = ?""",
            (
                consumed_revision,
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
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   'STARTED', 0, ?, ?, NULL
               )""",
            (
                execution_id,
                project_id,
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
                dependencies.plan.owner_id,
                dependencies.plan.owner_fingerprint,
                dependencies.plan.plan_hash,
                now,
                now,
            ),
        )

        runtime.store._append_event(
            conn,
            "DISPATCH_CLAIM",
            claim.claim_id,
            "DISPATCH_CLAIM_CONSUMED",
            DispatchClaimStatus.ACTIVE.value,
            DispatchClaimStatus.CONSUMED.value,
            consumed_revision,
            "SYSTEM",
            None,
            {
                "task_id": claim.task_id,
                "execution_id": execution_id,
                "runtime_dependency_plan_hash": dependencies.plan.plan_hash,
            },
            now,
        )
        runtime.store._append_event(
            conn,
            "DISPATCH_EXECUTION",
            execution_id,
            "DISPATCH_EXECUTION_STARTED",
            None,
            DispatchExecutionStatus.STARTED.value,
            0,
            "SYSTEM",
            None,
            {
                "claim_id": claim.claim_id,
                "task_id": claim.task_id,
                "execution_owner_id": dependencies.plan.owner_id,
                "execution_owner_fingerprint": dependencies.plan.owner_fingerprint,
                "runtime_dependency_plan_hash": dependencies.plan.plan_hash,
            },
            now,
        )
        execution_row = conn.execute(
            "SELECT * FROM dispatch_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if execution_row is None:
            raise ProductionDispatchExecutionError(
                "dispatch execution disappeared during begin transaction"
            )
        result = _execution_from_row(execution_row)

    return StartedDispatchExecution(result, dependencies)


def _validate_execution_id(execution_id: object) -> str:
    if not isinstance(execution_id, str) or not validate_id(
        execution_id,
        IdKind.DISPATCH_EXECUTION,
    ):
        raise ProductionDispatchExecutionError(
            "execution_id must be a valid DISPEXEC ID"
        )
    return execution_id


def _terminalize_dispatch_execution(
    runtime: OriginForgeRuntime,
    execution_id: str,
    expected_revision: int,
    *,
    target: DispatchExecutionStatus,
    detail: str,
) -> DispatchExecution:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    execution_id = _validate_execution_id(execution_id)
    expected_revision = _expected_revision(expected_revision)
    if target not in {
        DispatchExecutionStatus.RETURNED,
        DispatchExecutionStatus.RAISED,
        DispatchExecutionStatus.INTERRUPTED,
    }:
        raise ProductionDispatchExecutionError(
            "execution terminal target is unsupported"
        )
    detail = _bounded_detail(detail, "terminal detail")
    detail_hash = _terminal_detail_hash(target, detail)
    project_id = runtime.project_id()
    now = utc_now()

    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM dispatch_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise ProductionDispatchExecutionError(
                "dispatch execution does not exist"
            )
        execution = _execution_from_row(row)
        if execution.project_id != project_id:
            raise ProductionDispatchExecutionError(
                "dispatch execution does not belong to current project"
            )
        if execution.status is not DispatchExecutionStatus.STARTED:
            raise ProductionDispatchExecutionError(
                f"dispatch execution is terminal: {execution.status.value}"
            )
        if execution.revision != expected_revision:
            raise StaleRevision(
                f"dispatch execution {execution_id} revision {execution.revision} "
                f"!= expected {expected_revision}"
            )
        new_revision = execution.revision + 1
        cursor = conn.execute(
            """UPDATE dispatch_executions
               SET status = ?, revision = ?, updated_at = ?, terminal_detail_hash = ?
               WHERE execution_id = ? AND project_id = ?
                 AND status = 'STARTED' AND revision = ?""",
            (
                target.value,
                new_revision,
                now,
                detail_hash,
                execution_id,
                project_id,
                execution.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRevision(
                f"dispatch execution {execution_id} changed concurrently"
            )
        runtime.store._append_event(
            conn,
            "DISPATCH_EXECUTION",
            execution_id,
            f"DISPATCH_EXECUTION_{target.value}",
            DispatchExecutionStatus.STARTED.value,
            target.value,
            new_revision,
            "SYSTEM",
            None,
            {
                "claim_id": execution.claim_id,
                "task_id": execution.task_id,
                "terminal_detail_hash": detail_hash,
            },
            now,
        )
        updated = conn.execute(
            "SELECT * FROM dispatch_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if updated is None:
            raise ProductionDispatchExecutionError(
                "dispatch execution disappeared during terminal transition"
            )
        result = _execution_from_row(updated)
        if result.frozen_authority_dict() != execution.frozen_authority_dict():
            raise ProductionDispatchExecutionError(
                "dispatch execution frozen authority changed during terminal transition"
            )
        return result


def mark_dispatch_execution_returned(
    runtime: OriginForgeRuntime,
    execution_id: str,
    expected_revision: int,
    detail: str,
) -> DispatchExecution:
    return _terminalize_dispatch_execution(
        runtime,
        execution_id,
        expected_revision,
        target=DispatchExecutionStatus.RETURNED,
        detail=detail,
    )


def mark_dispatch_execution_raised(
    runtime: OriginForgeRuntime,
    execution_id: str,
    expected_revision: int,
    detail: str,
) -> DispatchExecution:
    return _terminalize_dispatch_execution(
        runtime,
        execution_id,
        expected_revision,
        target=DispatchExecutionStatus.RAISED,
        detail=detail,
    )


def interrupt_dispatch_execution(
    runtime: OriginForgeRuntime,
    execution_id: str,
    expected_revision: int,
    reason: str,
) -> DispatchExecution:
    return _terminalize_dispatch_execution(
        runtime,
        execution_id,
        expected_revision,
        target=DispatchExecutionStatus.INTERRUPTED,
        detail=reason,
    )
