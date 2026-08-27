from __future__ import annotations

import sqlite3

from .ids import IdKind, new_id, validate_id
from .production_capability_routing import task_routing_hash
from .production_dispatch_binding import (
    build_builtin_dispatch_binder_registry,
    build_pixelorama_source_dispatch_binder_registry,
)
from .production_dispatch_binding_models import DispatchBindingCurrentnessStatus
from .production_dispatch_claim_models import DispatchClaim, DispatchClaimStatus
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
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now
from .state import TaskStatus
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


class DispatchClaimError(RuntimeError):
    pass


def _validate_acquire_args(
    dispatch_binding_id: object,
    binding_audit_id: object,
    expected_task_revision: object,
) -> None:
    if not isinstance(dispatch_binding_id, str) or not validate_id(
        dispatch_binding_id, IdKind.DISPATCH_BINDING
    ):
        raise DispatchClaimError("dispatch_binding_id must be a valid DISPBIND ID")
    if not isinstance(binding_audit_id, str) or not validate_id(
        binding_audit_id, IdKind.DISPATCH_BINDING_AUDIT
    ):
        raise DispatchClaimError("binding_audit_id must be a valid BINDAUD ID")
    if type(expected_task_revision) is not int or expected_task_revision < 0:
        raise DispatchClaimError(
            "expected_task_revision must be a non-negative integer"
        )


def acquire_dispatch_claim(
    runtime: OriginForgeRuntime,
    dispatch_binding_id: str,
    binding_audit_id: str,
    expected_task_revision: int,
) -> DispatchClaim:
    """Acquire one durable exclusive claim over an exact current Phase-34 chain.

    This operation does not invoke the selected adapter. The caller supplies only
    the persisted binding/audit IDs and expected Task revision; all authority
    identities/hashes are derived from trusted Phase-34 evidence.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    _validate_acquire_args(
        dispatch_binding_id,
        binding_audit_id,
        expected_task_revision,
    )

    try:
        binding = read_dispatch_binding(runtime, dispatch_binding_id)
        audit = read_dispatch_binding_audit(runtime, binding_audit_id)
        bundle = read_input_resolution(runtime, binding.input_resolution_id)
    except ProductionDispatchReadError as exc:
        raise DispatchClaimError(
            "dispatch claim requires exact revalidated Phase-34 evidence"
        ) from exc

    if (
        binding.selected_adapter_id == "originforge.pixelorama.source"
        and binding.dispatch_contract_id == "pixelorama.source-create@1"
    ):
        resolver_registry = build_source_dispatch_input_resolver_registry()
        binder_registry = build_pixelorama_source_dispatch_binder_registry()
    else:
        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()

    if (
        audit.dispatch_binding_id != binding.dispatch_binding_id
        or audit.input_resolution_id != bundle.input_resolution_id
        or binding.input_resolution_id != bundle.input_resolution_id
    ):
        raise DispatchClaimError(
            "binding and binding audit do not form one exact Phase-34 chain"
        )
    if binding.task_revision != expected_task_revision:
        raise StaleRevision(
            f"binding task revision {binding.task_revision} != expected {expected_task_revision}"
        )

    try:
        currentness = inspect_dispatch_binding_currentness_readonly(
            runtime,
            bundle.input_resolution_id,
            binding.dispatch_binding_id,
            audit.binding_audit_id,
            resolver_registry,
            binder_registry,
        )
    except ProductionDispatchReadError as exc:
        raise DispatchClaimError(
            "dispatch binding currentness could not be revalidated"
        ) from exc
    if currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
        raise DispatchClaimError(
            f"dispatch binding is {currentness.status.value}, not CURRENT_READY"
        )

    project_id = runtime.project_id()
    claim_id = new_id(IdKind.DISPATCH_CLAIM)
    now = utc_now()
    try:
        with runtime.store.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT t.*, g.project_id
                   FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE t.id = ?""",
                (binding.task_id,),
            ).fetchone()
            if row is None:
                raise DispatchClaimError("bound Task does not exist")
            if row["project_id"] != project_id:
                raise DispatchClaimError(
                    "bound Task does not belong to the current project"
                )
            try:
                task_status = TaskStatus(row["status"])
            except ValueError as exc:
                raise DispatchClaimError("bound Task has invalid canonical status") from exc
            actual_revision = int(row["revision"])
            if actual_revision != expected_task_revision:
                raise StaleRevision(
                    f"task {binding.task_id} revision {actual_revision} != expected {expected_task_revision}"
                )
            if task_status is not TaskStatus.READY:
                raise DispatchClaimError(
                    "dispatch claim requires canonical READY Task"
                )
            current_task_hash = task_routing_hash(row)
            if current_task_hash != binding.task_content_hash:
                raise DispatchClaimError(
                    "dispatch binding Task content hash is stale"
                )

            try:
                readiness = resolve_task_dependency_readiness_connection(
                    conn,
                    binding.task_id,
                )
            except TaskReadinessError as exc:
                raise DispatchClaimError(
                    "bound Task dependency readiness is invalid"
                ) from exc
            if (
                readiness.task_status is not TaskStatus.READY
                or readiness.status is not DependencyReadinessStatus.READY
            ):
                raise DispatchClaimError(
                    "bound Task is no longer dependency-ready for dispatch"
                )

            existing = conn.execute(
                """SELECT claim_id FROM dispatch_claims
                   WHERE task_id = ? AND status = 'ACTIVE'
                   LIMIT 1""",
                (binding.task_id,),
            ).fetchone()
            if existing is not None:
                raise DispatchClaimError(
                    f"Task already has ACTIVE dispatch claim {existing['claim_id']}"
                )

            claim = DispatchClaim(
                claim_id=claim_id,
                project_id=project_id,
                task_id=binding.task_id,
                task_revision=actual_revision,
                task_content_hash=current_task_hash,
                work_order_id=binding.work_order_id,
                work_order_hash=binding.work_order_hash,
                work_order_audit_id=binding.work_order_audit_id,
                work_order_audit_hash=binding.work_order_audit_hash,
                input_resolution_id=bundle.input_resolution_id,
                input_resolution_hash=bundle.content_hash,
                dispatch_binding_id=binding.dispatch_binding_id,
                dispatch_binding_hash=binding.content_hash,
                binding_audit_id=audit.binding_audit_id,
                binding_audit_hash=audit.content_hash,
                selected_adapter_id=binding.selected_adapter_id,
                selected_adapter_fingerprint=binding.selected_adapter_fingerprint,
                dispatch_contract_id=binding.dispatch_contract_id,
                dispatch_contract_hash=binding.dispatch_contract_hash,
                binder_id=binding.binder_id,
                binder_fingerprint=binding.binder_fingerprint,
                status=DispatchClaimStatus.ACTIVE,
                revision=0,
                created_at=now,
                updated_at=now,
                terminal_reason=None,
            )
            values = claim.to_dict()
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
            runtime.store._append_event(
                conn,
                "DISPATCH_CLAIM",
                claim.claim_id,
                "DISPATCH_CLAIM_ACQUIRED",
                None,
                DispatchClaimStatus.ACTIVE.value,
                0,
                "SYSTEM",
                None,
                {
                    "task_id": claim.task_id,
                    "task_revision": claim.task_revision,
                    "task_content_hash": claim.task_content_hash,
                    "dispatch_binding_id": claim.dispatch_binding_id,
                    "dispatch_binding_hash": claim.dispatch_binding_hash,
                    "binding_audit_id": claim.binding_audit_id,
                    "binding_audit_hash": claim.binding_audit_hash,
                },
                now,
            )
    except sqlite3.IntegrityError as exc:
        raise DispatchClaimError(
            "dispatch claim lost the durable exclusivity race"
        ) from exc

    return claim
