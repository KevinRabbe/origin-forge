from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_capability_routing import task_routing_hash
from .production_dispatch_binding import (
    build_builtin_dispatch_binder_registry,
    build_pixelorama_source_dispatch_binder_registry,
)
from .production_dispatch_binding_models import DispatchBindingCurrentnessStatus
from .production_dispatch_claim_models import (
    DispatchClaim,
    DispatchClaimModelError,
    DispatchClaimStatus,
)
from .production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
    build_source_dispatch_input_resolver_registry,
)
from .production_dispatch_read import (
    ProductionDispatchReadError,
    inspect_dispatch_binding_currentness_readonly,
    read_dispatch_binding,
    read_dispatch_binding_audit,
    read_input_resolution,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime
from .state import TaskStatus
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


class ProductionDispatchClaimReadError(RuntimeError):
    pass


class DispatchClaimCurrentnessStatus(StrEnum):
    CURRENT_ACTIVE = "CURRENT_ACTIVE"
    STALE_TASK = "STALE_TASK"
    STALE_BINDING = "STALE_BINDING"
    NOT_READY = "NOT_READY"
    RELEASED = "RELEASED"
    INTERRUPTED = "INTERRUPTED"
    CONSUMED = "CONSUMED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class DispatchClaimCurrentness:
    claim_id: str
    task_id: str | None
    status: DispatchClaimCurrentnessStatus
    detail: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not validate_id(
            self.claim_id, IdKind.DISPATCH_CLAIM
        ):
            raise ProductionDispatchClaimReadError(
                "claim currentness requires a valid DISPCLAIM ID"
            )
        if self.task_id is not None and (
            not isinstance(self.task_id, str)
            or not validate_id(self.task_id, IdKind.TASK)
        ):
            raise ProductionDispatchClaimReadError(
                "claim currentness task_id is invalid"
            )
        if not isinstance(self.status, DispatchClaimCurrentnessStatus):
            raise ProductionDispatchClaimReadError(
                "claim currentness status is invalid"
            )
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail
        ):
            raise ProductionDispatchClaimReadError(
                "claim currentness detail is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TaskActivationEligibility:
    task_id: str
    task_revision: int
    task_content_hash: str
    task_status: TaskStatus
    dependency_readiness_status: DependencyReadinessStatus
    eligible: bool
    detail: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "task_status": self.task_status.value,
            "dependency_readiness_status": self.dependency_readiness_status.value,
            "eligible": self.eligible,
            "detail": self.detail,
        }


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
        raise ProductionDispatchClaimReadError(
            "stored dispatch claim failed canonical validation"
        ) from exc


def _validate_runtime_and_claim_id(
    runtime: OriginForgeRuntime,
    claim_id: object,
) -> None:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(claim_id, str) or not validate_id(
        claim_id, IdKind.DISPATCH_CLAIM
    ):
        raise ProductionDispatchClaimReadError(
            "claim_id must be a valid DISPCLAIM ID"
        )


def _project_id_connection(conn, runtime: OriginForgeRuntime) -> str:
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?",
        (str(runtime.project_root),),
    ).fetchone()
    if row is None:
        raise ProductionDispatchClaimReadError(
            "project is not initialized for the current repository root"
        )
    project_id = row["id"]
    if not isinstance(project_id, str) or not validate_id(project_id, IdKind.PROJECT):
        raise ProductionDispatchClaimReadError("project has invalid canonical ID")
    return project_id


def read_dispatch_claim(
    runtime: OriginForgeRuntime,
    claim_id: str,
) -> DispatchClaim:
    """Read one durable claim through the immutable production SQLite boundary."""

    _validate_runtime_and_claim_id(runtime, claim_id)
    try:
        with production_read_connection(runtime) as conn:
            project_id = _project_id_connection(conn, runtime)
            row = conn.execute(
                "SELECT * FROM dispatch_claims WHERE claim_id = ?",
                (claim_id,),
            ).fetchone()
            if row is None:
                raise ProductionDispatchClaimReadError(
                    "dispatch claim does not exist"
                )
            claim = _claim_from_row(row)
            if claim.project_id != project_id:
                raise ProductionDispatchClaimReadError(
                    "dispatch claim does not belong to the current project"
                )
            return claim
    except ProductionDispatchClaimReadError:
        raise
    except ProductionReadGuardError as exc:
        raise ProductionDispatchClaimReadError(str(exc)) from exc


def inspect_task_activation_eligibility_readonly(
    runtime: OriginForgeRuntime,
    task_id: str,
) -> TaskActivationEligibility:
    """Derive exact Phase-35 activation eligibility without mutating state."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(task_id, str) or not validate_id(task_id, IdKind.TASK):
        raise ProductionDispatchClaimReadError("task_id must be a valid TASK ID")
    try:
        with production_read_connection(runtime) as conn:
            project_id = _project_id_connection(conn, runtime)
            row = conn.execute(
                """SELECT t.*, g.project_id
                   FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE t.id = ?""",
                (task_id,),
            ).fetchone()
            if row is None or row["project_id"] != project_id:
                raise ProductionDispatchClaimReadError(
                    "Task does not belong to the current project"
                )
            try:
                task_status = TaskStatus(row["status"])
                readiness = resolve_task_dependency_readiness_connection(
                    conn,
                    task_id,
                )
                content_hash = task_routing_hash(row)
            except (TaskReadinessError, TypeError, ValueError) as exc:
                raise ProductionDispatchClaimReadError(
                    "Task activation eligibility could not be derived"
                ) from exc
            eligible = (
                task_status is TaskStatus.QUEUED
                and readiness.task_status is TaskStatus.QUEUED
                and readiness.status is DependencyReadinessStatus.READY
            )
            if eligible:
                detail = None
            elif task_status is not TaskStatus.QUEUED:
                detail = f"canonical Task status is {task_status.value}, not QUEUED"
            else:
                detail = (
                    "dependency readiness is "
                    f"{readiness.status.value}, not READY"
                )
            return TaskActivationEligibility(
                task_id=task_id,
                task_revision=int(row["revision"]),
                task_content_hash=content_hash,
                task_status=task_status,
                dependency_readiness_status=readiness.status,
                eligible=eligible,
                detail=detail,
            )
    except ProductionDispatchClaimReadError:
        raise
    except ProductionReadGuardError as exc:
        raise ProductionDispatchClaimReadError(str(exc)) from exc


def _validate_frozen_phase34_relation(
    runtime: OriginForgeRuntime,
    claim: DispatchClaim,
) -> None:
    try:
        bundle = read_input_resolution(runtime, claim.input_resolution_id)
        binding = read_dispatch_binding(runtime, claim.dispatch_binding_id)
        audit = read_dispatch_binding_audit(runtime, claim.binding_audit_id)
    except ProductionDispatchReadError as exc:
        raise ProductionDispatchClaimReadError(
            "claim Phase-34 evidence could not be revalidated"
        ) from exc
    if (
        bundle.content_hash != claim.input_resolution_hash
        or binding.content_hash != claim.dispatch_binding_hash
        or audit.content_hash != claim.binding_audit_hash
        or binding.input_resolution_id != bundle.input_resolution_id
        or audit.input_resolution_id != bundle.input_resolution_id
        or audit.dispatch_binding_id != binding.dispatch_binding_id
        or claim.task_id != binding.task_id
        or claim.task_revision != binding.task_revision
        or claim.task_content_hash != binding.task_content_hash
        or claim.work_order_id != binding.work_order_id
        or claim.work_order_hash != binding.work_order_hash
        or claim.work_order_audit_id != binding.work_order_audit_id
        or claim.work_order_audit_hash != binding.work_order_audit_hash
        or claim.selected_adapter_id != binding.selected_adapter_id
        or claim.selected_adapter_fingerprint
        != binding.selected_adapter_fingerprint
        or claim.dispatch_contract_id != binding.dispatch_contract_id
        or claim.dispatch_contract_hash != binding.dispatch_contract_hash
        or claim.binder_id != binding.binder_id
        or claim.binder_fingerprint != binding.binder_fingerprint
    ):
        raise ProductionDispatchClaimReadError(
            "claim frozen authority does not match exact Phase-34 evidence"
        )


def inspect_dispatch_claim_currentness_readonly(
    runtime: OriginForgeRuntime,
    claim_id: str,
) -> DispatchClaimCurrentness:
    """Inspect whether one claim remains eligible without acquiring authority."""

    _validate_runtime_and_claim_id(runtime, claim_id)

    def result(
        task_id: str | None,
        status: DispatchClaimCurrentnessStatus,
        detail: str | None,
    ) -> DispatchClaimCurrentness:
        return DispatchClaimCurrentness(claim_id, task_id, status, detail)

    try:
        claim = read_dispatch_claim(runtime, claim_id)
    except ProductionDispatchClaimReadError as exc:
        return result(None, DispatchClaimCurrentnessStatus.INVALID, str(exc))

    try:
        _validate_frozen_phase34_relation(runtime, claim)
    except ProductionDispatchClaimReadError as exc:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.INVALID,
            str(exc),
        )

    if claim.status is DispatchClaimStatus.RELEASED:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.RELEASED,
            claim.terminal_reason,
        )
    if claim.status is DispatchClaimStatus.INTERRUPTED:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.INTERRUPTED,
            claim.terminal_reason,
        )
    if claim.status is DispatchClaimStatus.CONSUMED:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.CONSUMED,
            claim.terminal_reason,
        )
    if claim.status is not DispatchClaimStatus.ACTIVE:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.INVALID,
            "dispatch claim has unsupported lifecycle state",
        )

    try:
        with production_read_connection(runtime) as conn:
            project_id = _project_id_connection(conn, runtime)
            row = conn.execute(
                """SELECT t.*, g.project_id
                   FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE t.id = ?""",
                (claim.task_id,),
            ).fetchone()
            if row is None or row["project_id"] != project_id:
                return result(
                    claim.task_id,
                    DispatchClaimCurrentnessStatus.STALE_TASK,
                    "bound Task no longer belongs to the current project",
                )
            try:
                task_status = TaskStatus(row["status"])
                current_hash = task_routing_hash(row)
                readiness = resolve_task_dependency_readiness_connection(
                    conn,
                    claim.task_id,
                )
            except (TaskReadinessError, TypeError, ValueError) as exc:
                return result(
                    claim.task_id,
                    DispatchClaimCurrentnessStatus.INVALID,
                    f"Task currentness could not be derived: {type(exc).__name__}: {exc}",
                )
            if (
                int(row["revision"]) != claim.task_revision
                or current_hash != claim.task_content_hash
            ):
                return result(
                    claim.task_id,
                    DispatchClaimCurrentnessStatus.STALE_TASK,
                    "Task revision/content no longer matches frozen claim authority",
                )
            if (
                task_status is not TaskStatus.READY
                or readiness.task_status is not TaskStatus.READY
                or readiness.status is not DependencyReadinessStatus.READY
            ):
                return result(
                    claim.task_id,
                    DispatchClaimCurrentnessStatus.NOT_READY,
                    "bound Task is not canonical READY and dependency-ready",
                )
    except ProductionReadGuardError as exc:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.INVALID,
            str(exc),
        )

    try:
        binding = read_dispatch_binding(runtime, claim.dispatch_binding_id)
    except ProductionDispatchReadError as exc:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.INVALID,
            f"Phase-34 binding could not be read: {exc}",
        )
    if (
        binding.selected_adapter_id == "originforge.pixelorama.source"
        and binding.dispatch_contract_id == "pixelorama.source-create@1"
    ):
        resolver_registry = build_source_dispatch_input_resolver_registry()
        binder_registry = build_pixelorama_source_dispatch_binder_registry()
    else:
        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
    try:
        binding_currentness = inspect_dispatch_binding_currentness_readonly(
            runtime,
            claim.input_resolution_id,
            claim.dispatch_binding_id,
            claim.binding_audit_id,
            resolver_registry,
            binder_registry,
        )
    except ProductionDispatchReadError as exc:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.INVALID,
            f"Phase-34 currentness could not be read: {exc}",
        )
    if binding_currentness.status is DispatchBindingCurrentnessStatus.CURRENT_READY:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.CURRENT_ACTIVE,
            None,
        )
    if binding_currentness.status is DispatchBindingCurrentnessStatus.NOT_READY:
        return result(
            claim.task_id,
            DispatchClaimCurrentnessStatus.NOT_READY,
            "Phase-34 binding is NOT_READY",
        )
    return result(
        claim.task_id,
        DispatchClaimCurrentnessStatus.STALE_BINDING,
        f"Phase-34 binding currentness is {binding_currentness.status.value}",
    )
