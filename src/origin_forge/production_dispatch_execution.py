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
from .state import TASK_TRANSITIONS, TaskStatus, ensure_transition
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


_MAX_DETAIL_CHARS = 4096
_SIMULATION_EXECUTION_OWNER_ID = "originforge.execution.simulation.deterministic@1"
_PIXELORAMA_EXECUTION_OWNER_ID = "originforge.execution.pixelorama.spritesheet-export@1"


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
            or self.execution.claim_revision_at_start
            != self.dependencies.plan.claim_revision
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


def _expected_revision(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProductionDispatchExecutionError(
            f"{label} must be a non-negative integer"
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


def _validate_transactional_task_currentness(conn, claim: DispatchClaim):
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
    return row


def _transition_simulation_task_running_connection(
    runtime: OriginForgeRuntime,
    conn,
    claim: DispatchClaim,
    execution_id: str,
    now: str,
) -> tuple[int, str]:
    ensure_transition(TaskStatus.READY, TaskStatus.RUNNING, TASK_TRANSITIONS)
    new_revision = claim.task_revision + 1
    cursor = conn.execute(
        """UPDATE tasks
           SET status = ?, revision = ?, updated_at = ?
           WHERE id = ? AND status = ? AND revision = ?""",
        (
            TaskStatus.RUNNING.value,
            new_revision,
            now,
            claim.task_id,
            TaskStatus.READY.value,
            claim.task_revision,
        ),
    )
    if cursor.rowcount != 1:
        raise StaleRevision(f"task {claim.task_id} changed concurrently")

    updated = conn.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (claim.task_id,),
    ).fetchone()
    if updated is None:
        raise ProductionDispatchExecutionError(
            "simulation Task disappeared during execution begin"
        )
    try:
        updated_status = TaskStatus(updated["status"])
        updated_revision = int(updated["revision"])
        updated_hash = task_routing_hash(updated)
    except (TypeError, ValueError) as exc:
        raise ProductionDispatchExecutionError(
            "simulation Task failed canonical validation after RUNNING transition"
        ) from exc
    if updated_status is not TaskStatus.RUNNING or updated_revision != new_revision:
        raise ProductionDispatchExecutionError(
            "simulation Task did not enter exact RUNNING revision"
        )
    if updated_hash == claim.task_content_hash:
        raise ProductionDispatchExecutionError(
            "simulation Task RUNNING transition did not change revision-bound content hash"
        )
    return new_revision, updated_hash


def _transition_pixelorama_task_running_connection(
    runtime: OriginForgeRuntime,
    conn,
    claim: DispatchClaim,
    execution_id: str,
    now: str,
) -> tuple[int, str]:
    ensure_transition(TaskStatus.READY, TaskStatus.RUNNING, TASK_TRANSITIONS)
    new_revision = claim.task_revision + 1
    cursor = conn.execute(
        """UPDATE tasks
           SET status = ?, revision = ?, updated_at = ?
           WHERE id = ? AND status = ? AND revision = ?""",
        (
            TaskStatus.RUNNING.value,
            new_revision,
            now,
            claim.task_id,
            TaskStatus.READY.value,
            claim.task_revision,
        ),
    )
    if cursor.rowcount != 1:
        raise StaleRevision(f"task {claim.task_id} changed concurrently")
    updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (claim.task_id,)).fetchone()
    if updated is None:
        raise ProductionDispatchExecutionError(
            "Pixelorama Task disappeared during execution begin"
        )
    try:
        updated_status = TaskStatus(updated["status"])
        updated_revision = int(updated["revision"])
        updated_hash = task_routing_hash(updated)
    except (TypeError, ValueError) as exc:
        raise ProductionDispatchExecutionError(
            "Pixelorama Task failed canonical validation after RUNNING transition"
        ) from exc
    if updated_status is not TaskStatus.RUNNING or updated_revision != new_revision:
        raise ProductionDispatchExecutionError(
            "Pixelorama Task did not enter exact RUNNING revision"
        )
    if updated_hash == claim.task_content_hash:
        raise ProductionDispatchExecutionError(
            "Pixelorama Task RUNNING transition did not change revision-bound content hash"
        )
    return new_revision, updated_hash


def _claim_matches_execution(claim: DispatchClaim, execution: DispatchExecution) -> bool:
    return (
        claim.project_id == execution.project_id
        and claim.claim_id == execution.claim_id
        and claim.task_id == execution.task_id
        and claim.task_revision == execution.task_revision
        and claim.task_content_hash == execution.task_content_hash
        and claim.work_order_id == execution.work_order_id
        and claim.work_order_hash == execution.work_order_hash
        and claim.input_resolution_id == execution.input_resolution_id
        and claim.input_resolution_hash == execution.input_resolution_hash
        and claim.dispatch_binding_id == execution.dispatch_binding_id
        and claim.dispatch_binding_hash == execution.dispatch_binding_hash
        and claim.binding_audit_id == execution.binding_audit_id
        and claim.binding_audit_hash == execution.binding_audit_hash
        and claim.selected_adapter_id == execution.selected_adapter_id
        and claim.selected_adapter_fingerprint
        == execution.selected_adapter_fingerprint
        and claim.dispatch_contract_id == execution.dispatch_contract_id
        and claim.dispatch_contract_hash == execution.dispatch_contract_hash
        and claim.binder_id == execution.binder_id
        and claim.binder_fingerprint == execution.binder_fingerprint
    )


def begin_dispatch_execution(
    runtime: OriginForgeRuntime,
    claim_id: str,
    expected_revision: int,
) -> StartedDispatchExecution:
    """Create one STARTED execution receipt while retaining the ACTIVE claim.

    Dependencies are assembled before the transaction but never invoked. The
    ACTIVE claim remains the durable exclusivity lock throughout the STARTED
    execution window. Deterministic simulation additionally transitions its exact
    READY Task to RUNNING in this same transaction; bounded-code behavior remains
    unchanged. Only a later terminalization may consume or interrupt the claim.
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
    expected_revision = _expected_revision(expected_revision, "expected_revision")

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
        competing = conn.execute(
            """SELECT execution_id FROM dispatch_executions
               WHERE task_id = ? AND status = 'STARTED'""",
            (claim.task_id,),
        ).fetchone()
        if competing is not None:
            raise ProductionDispatchExecutionError(
                "Task already has a STARTED dispatch execution"
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

        task_transition: tuple[int, str] | None = None
        task_transition_reason: str | None = None
        if dependencies.plan.owner_id == _SIMULATION_EXECUTION_OWNER_ID:
            task_transition = _transition_simulation_task_running_connection(
                runtime,
                conn,
                claim,
                execution_id,
                now,
            )
            task_transition_reason = "SIMULATION_DISPATCH_EXECUTION_STARTED"
        elif dependencies.plan.owner_id == _PIXELORAMA_EXECUTION_OWNER_ID:
            task_transition = _transition_pixelorama_task_running_connection(
                runtime,
                conn,
                claim,
                execution_id,
                now,
            )
            task_transition_reason = "PIXELORAMA_DISPATCH_EXECUTION_STARTED"

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
                "claim_revision": claim.revision,
                "task_id": claim.task_id,
                "execution_owner_id": dependencies.plan.owner_id,
                "execution_owner_fingerprint": dependencies.plan.owner_fingerprint,
                "runtime_dependency_plan_hash": dependencies.plan.plan_hash,
            },
            now,
        )
        if task_transition is not None:
            new_task_revision, new_task_hash = task_transition
            runtime.store._append_event(
                conn,
                "TASK",
                claim.task_id,
                "TASK_STATUS_CHANGED",
                TaskStatus.READY.value,
                TaskStatus.RUNNING.value,
                new_task_revision,
                "SYSTEM",
                None,
                {
                    "reason": task_transition_reason,
                    "claim_id": claim.claim_id,
                    "execution_id": execution_id,
                    "previous_task_content_hash": claim.task_content_hash,
                    "new_task_content_hash": new_task_hash,
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
        claim_after = conn.execute(
            "SELECT * FROM dispatch_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if claim_after is None:
            raise ProductionDispatchExecutionError(
                "dispatch claim disappeared during begin transaction"
            )
        unchanged_claim = _claim_from_row(claim_after)
        if unchanged_claim != claim:
            raise ProductionDispatchExecutionError(
                "begin transaction changed ACTIVE claim authority or lifecycle"
            )
        if task_transition is not None:
            task_after = conn.execute(
                "SELECT status, revision FROM tasks WHERE id = ?",
                (claim.task_id,),
            ).fetchone()
            if (
                task_after is None
                or task_after["status"] != TaskStatus.RUNNING.value
                or int(task_after["revision"]) != claim.task_revision + 1
            ):
                raise ProductionDispatchExecutionError(
                    "managed non-code begin transaction lost atomic RUNNING Task state"
                )

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
    expected_execution_revision: int,
    expected_claim_revision: int,
    *,
    target: DispatchExecutionStatus,
    detail: str,
) -> DispatchExecution:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    execution_id = _validate_execution_id(execution_id)
    expected_execution_revision = _expected_revision(
        expected_execution_revision,
        "expected_execution_revision",
    )
    expected_claim_revision = _expected_revision(
        expected_claim_revision,
        "expected_claim_revision",
    )
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

    if target is DispatchExecutionStatus.INTERRUPTED:
        claim_target = DispatchClaimStatus.INTERRUPTED
        claim_event = "DISPATCH_CLAIM_INTERRUPTED"
        claim_reason = f"claim interrupted with dispatch execution {execution_id}"
    else:
        claim_target = DispatchClaimStatus.CONSUMED
        claim_event = "DISPATCH_CLAIM_CONSUMED"
        claim_reason = (
            f"claim consumed by dispatch execution {execution_id} "
            f"after {target.value.lower()}"
        )

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
        if execution.revision != expected_execution_revision:
            raise StaleRevision(
                f"dispatch execution {execution_id} revision {execution.revision} "
                f"!= expected {expected_execution_revision}"
            )

        claim_row = conn.execute(
            "SELECT * FROM dispatch_claims WHERE claim_id = ?",
            (execution.claim_id,),
        ).fetchone()
        if claim_row is None:
            raise ProductionDispatchExecutionError(
                "dispatch execution claim does not exist"
            )
        claim = _claim_from_row(claim_row)
        if claim.project_id != project_id or not _claim_matches_execution(claim, execution):
            raise ProductionDispatchExecutionError(
                "dispatch execution no longer matches exact claim authority"
            )
        if claim.status is not DispatchClaimStatus.ACTIVE:
            raise ProductionDispatchExecutionError(
                f"dispatch execution claim is not ACTIVE: {claim.status.value}"
            )
        if claim.revision != expected_claim_revision:
            raise StaleRevision(
                f"dispatch claim {claim.claim_id} revision {claim.revision} "
                f"!= expected {expected_claim_revision}"
            )
        if claim.revision != execution.claim_revision_at_start:
            raise ProductionDispatchExecutionError(
                "STARTED execution no longer owns its original ACTIVE claim revision"
            )

        new_execution_revision = execution.revision + 1
        new_claim_revision = claim.revision + 1
        execution_cursor = conn.execute(
            """UPDATE dispatch_executions
               SET status = ?, revision = ?, updated_at = ?, terminal_detail_hash = ?
               WHERE execution_id = ? AND project_id = ?
                 AND status = 'STARTED' AND revision = ?""",
            (
                target.value,
                new_execution_revision,
                now,
                detail_hash,
                execution_id,
                project_id,
                execution.revision,
            ),
        )
        if execution_cursor.rowcount != 1:
            raise StaleRevision(
                f"dispatch execution {execution_id} changed concurrently"
            )
        claim_cursor = conn.execute(
            """UPDATE dispatch_claims
               SET status = ?, revision = ?, updated_at = ?, terminal_reason = ?
               WHERE claim_id = ? AND project_id = ?
                 AND status = 'ACTIVE' AND revision = ?""",
            (
                claim_target.value,
                new_claim_revision,
                now,
                claim_reason,
                claim.claim_id,
                project_id,
                claim.revision,
            ),
        )
        if claim_cursor.rowcount != 1:
            raise StaleRevision(
                f"dispatch claim {claim.claim_id} changed concurrently"
            )

        runtime.store._append_event(
            conn,
            "DISPATCH_EXECUTION",
            execution_id,
            f"DISPATCH_EXECUTION_{target.value}",
            DispatchExecutionStatus.STARTED.value,
            target.value,
            new_execution_revision,
            "SYSTEM",
            None,
            {
                "claim_id": execution.claim_id,
                "task_id": execution.task_id,
                "terminal_detail_hash": detail_hash,
            },
            now,
        )
        runtime.store._append_event(
            conn,
            "DISPATCH_CLAIM",
            claim.claim_id,
            claim_event,
            DispatchClaimStatus.ACTIVE.value,
            claim_target.value,
            new_claim_revision,
            "SYSTEM",
            None,
            {
                "task_id": claim.task_id,
                "execution_id": execution_id,
                "execution_status": target.value,
                "terminal_detail_hash": detail_hash,
            },
            now,
        )

        updated_execution_row = conn.execute(
            "SELECT * FROM dispatch_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        updated_claim_row = conn.execute(
            "SELECT * FROM dispatch_claims WHERE claim_id = ?",
            (claim.claim_id,),
        ).fetchone()
        if updated_execution_row is None or updated_claim_row is None:
            raise ProductionDispatchExecutionError(
                "execution or claim disappeared during terminal transition"
            )
        result = _execution_from_row(updated_execution_row)
        updated_claim = _claim_from_row(updated_claim_row)
        if result.frozen_authority_dict() != execution.frozen_authority_dict():
            raise ProductionDispatchExecutionError(
                "dispatch execution frozen authority changed during terminal transition"
            )
        if updated_claim.frozen_authority_dict() != claim.frozen_authority_dict():
            raise ProductionDispatchExecutionError(
                "dispatch claim frozen authority changed during terminal transition"
            )
        return result


def mark_dispatch_execution_returned(
    runtime: OriginForgeRuntime,
    execution_id: str,
    expected_execution_revision: int,
    expected_claim_revision: int,
    detail: str,
) -> DispatchExecution:
    return _terminalize_dispatch_execution(
        runtime,
        execution_id,
        expected_execution_revision,
        expected_claim_revision,
        target=DispatchExecutionStatus.RETURNED,
        detail=detail,
    )


def mark_dispatch_execution_raised(
    runtime: OriginForgeRuntime,
    execution_id: str,
    expected_execution_revision: int,
    expected_claim_revision: int,
    detail: str,
) -> DispatchExecution:
    return _terminalize_dispatch_execution(
        runtime,
        execution_id,
        expected_execution_revision,
        expected_claim_revision,
        target=DispatchExecutionStatus.RAISED,
        detail=detail,
    )


def interrupt_dispatch_execution(
    runtime: OriginForgeRuntime,
    execution_id: str,
    expected_execution_revision: int,
    expected_claim_revision: int,
    reason: str,
) -> DispatchExecution:
    return _terminalize_dispatch_execution(
        runtime,
        execution_id,
        expected_execution_revision,
        expected_claim_revision,
        target=DispatchExecutionStatus.INTERRUPTED,
        detail=reason,
    )
