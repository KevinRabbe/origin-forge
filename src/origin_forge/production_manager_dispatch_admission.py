from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_capability_routing import task_routing_hash
from .production_dispatch_binding import build_builtin_dispatch_binder_registry
from .production_dispatch_binding_models import DispatchBindingCurrentnessStatus
from .production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from .production_dispatch_read import (
    ProductionDispatchReadError,
    _category_dir,
    inspect_dispatch_binding_currentness_readonly,
    read_dispatch_binding,
    read_dispatch_binding_audit,
    read_input_resolution,
)
from .production_dispatch_store import _MAX_OBJECTS_PER_CATEGORY
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime
from .state import TaskStatus
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


_MAX_MANAGER_AUDIT_CHAINS = _MAX_OBJECTS_PER_CATEGORY
_MAX_MANAGER_CANDIDATES = 1_024


class ManagerDispatchAdmissionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"


class ManagerDispatchAdmissionDetail(StrEnum):
    PHASE34_SCAN_LIMIT_EXCEEDED = "PHASE34_SCAN_LIMIT_EXCEEDED"
    CANDIDATE_LIMIT_EXCEEDED = "CANDIDATE_LIMIT_EXCEEDED"
    INVALID_PHASE34_EVIDENCE = "INVALID_PHASE34_EVIDENCE"
    INVALID_CANONICAL_STATE = "INVALID_CANONICAL_STATE"


@dataclass(frozen=True)
class ManagerDispatchCandidate:
    task_id: str
    task_revision: int
    task_content_hash: str
    created_at: str
    input_resolution_id: str
    dispatch_binding_id: str
    binding_audit_id: str
    work_order_hash: str
    selected_adapter_id: str
    selected_adapter_fingerprint: str
    dispatch_contract_id: str
    dispatch_contract_hash: str
    binder_id: str
    binder_fingerprint: str
    request_type_id: str
    request_schema_hash: str
    request_content_hash: str

    def representative_key(self) -> tuple[str, str, str]:
        return (
            self.binding_audit_id,
            self.dispatch_binding_id,
            self.input_resolution_id,
        )

    def authority_key(self) -> tuple[object, ...]:
        return (
            self.task_revision,
            self.task_content_hash,
            self.work_order_hash,
            self.selected_adapter_id,
            self.selected_adapter_fingerprint,
            self.dispatch_contract_id,
            self.dispatch_contract_hash,
            self.binder_id,
            self.binder_fingerprint,
            self.request_type_id,
            self.request_schema_hash,
            self.request_content_hash,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "created_at": self.created_at,
            "input_resolution_id": self.input_resolution_id,
            "dispatch_binding_id": self.dispatch_binding_id,
            "binding_audit_id": self.binding_audit_id,
            "work_order_hash": self.work_order_hash,
            "selected_adapter_id": self.selected_adapter_id,
            "selected_adapter_fingerprint": self.selected_adapter_fingerprint,
            "dispatch_contract_id": self.dispatch_contract_id,
            "dispatch_contract_hash": self.dispatch_contract_hash,
            "binder_id": self.binder_id,
            "binder_fingerprint": self.binder_fingerprint,
            "request_type_id": self.request_type_id,
            "request_schema_hash": self.request_schema_hash,
            "request_content_hash": self.request_content_hash,
        }


@dataclass(frozen=True)
class ManagerDispatchAdmission:
    status: ManagerDispatchAdmissionStatus
    candidates: tuple[ManagerDispatchCandidate, ...]
    scanned_audit_count: int
    current_chain_count: int
    active_claim_exclusion_count: int
    not_ready_exclusion_count: int
    ambiguous_task_ids: tuple[str, ...]
    detail: ManagerDispatchAdmissionDetail | None

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def ambiguous_task_count(self) -> int:
        return len(self.ambiguous_task_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "candidate_count": self.candidate_count,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "scanned_audit_count": self.scanned_audit_count,
            "current_chain_count": self.current_chain_count,
            "active_claim_exclusion_count": self.active_claim_exclusion_count,
            "not_ready_exclusion_count": self.not_ready_exclusion_count,
            "ambiguous_task_count": self.ambiguous_task_count,
            "ambiguous_task_ids": list(self.ambiguous_task_ids),
            "detail": None if self.detail is None else self.detail.value,
            "authority": "read-only",
        }


def _empty_result(
    status: ManagerDispatchAdmissionStatus,
    *,
    scanned_audit_count: int,
    current_chain_count: int = 0,
    active_claim_exclusion_count: int = 0,
    not_ready_exclusion_count: int = 0,
    ambiguous_task_ids: tuple[str, ...] = (),
    detail: ManagerDispatchAdmissionDetail | None,
) -> ManagerDispatchAdmission:
    return ManagerDispatchAdmission(
        status=status,
        candidates=(),
        scanned_audit_count=scanned_audit_count,
        current_chain_count=current_chain_count,
        active_claim_exclusion_count=active_claim_exclusion_count,
        not_ready_exclusion_count=not_ready_exclusion_count,
        ambiguous_task_ids=ambiguous_task_ids,
        detail=detail,
    )


def _enumerate_binding_audit_ids(
    runtime: OriginForgeRuntime,
) -> tuple[tuple[str, ...], int, ManagerDispatchAdmissionDetail | None]:
    directory = _category_dir(runtime, "binding-audits", required=False)
    if directory is None:
        return (), 0, None

    audit_ids: list[str] = []
    count = 0
    for path in directory.iterdir():
        count += 1
        if count > _MAX_MANAGER_AUDIT_CHAINS:
            return (), count, ManagerDispatchAdmissionDetail.PHASE34_SCAN_LIMIT_EXCEEDED
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ProductionDispatchReadError(
                "binding-audits contains an undeclared or aliased entry"
            )
        audit_id = path.stem
        if path.name != f"{audit_id}.json" or not validate_id(
            audit_id,
            IdKind.DISPATCH_BINDING_AUDIT,
        ):
            raise ProductionDispatchReadError(
                "binding-audits contains an invalid evidence filename"
            )
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionDispatchReadError(
                "binding audit evidence path could not be resolved"
            ) from exc
        if resolved != path:
            raise ProductionDispatchReadError(
                "binding audit evidence path is aliased"
            )
        audit_ids.append(audit_id)

    audit_ids.sort()
    return tuple(audit_ids), count, None


def _candidate_from_current_chain(runtime: OriginForgeRuntime, audit_id: str):
    audit = read_dispatch_binding_audit(runtime, audit_id)
    binding = read_dispatch_binding(runtime, audit.dispatch_binding_id)
    bundle = read_input_resolution(runtime, audit.input_resolution_id)
    if (
        binding.input_resolution_id != bundle.input_resolution_id
        or audit.input_resolution_id != bundle.input_resolution_id
        or audit.dispatch_binding_id != binding.dispatch_binding_id
    ):
        raise ProductionDispatchReadError(
            "binding audit does not form one exact Phase-34 chain"
        )

    currentness = inspect_dispatch_binding_currentness_readonly(
        runtime,
        bundle.input_resolution_id,
        binding.dispatch_binding_id,
        audit.binding_audit_id,
        build_dispatch_input_resolver_registry(),
        build_builtin_dispatch_binder_registry(),
    )
    if currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
        return None

    return ManagerDispatchCandidate(
        task_id=binding.task_id,
        task_revision=binding.task_revision,
        task_content_hash=binding.task_content_hash,
        created_at="",
        input_resolution_id=bundle.input_resolution_id,
        dispatch_binding_id=binding.dispatch_binding_id,
        binding_audit_id=audit.binding_audit_id,
        work_order_hash=binding.work_order_hash,
        selected_adapter_id=binding.selected_adapter_id,
        selected_adapter_fingerprint=binding.selected_adapter_fingerprint,
        dispatch_contract_id=binding.dispatch_contract_id,
        dispatch_contract_hash=binding.dispatch_contract_hash,
        binder_id=binding.binder_id,
        binder_fingerprint=binding.binder_fingerprint,
        request_type_id=binding.request_type_id,
        request_schema_hash=binding.request_schema_hash,
        request_content_hash=binding.request_content_hash,
    )


def _project_id_connection(conn, runtime: OriginForgeRuntime) -> str:
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?",
        (str(runtime.project_root),),
    ).fetchone()
    if row is None:
        raise ValueError("project is not initialized")
    project_id = row["id"]
    if not isinstance(project_id, str) or not validate_id(project_id, IdKind.PROJECT):
        raise ValueError("project has invalid canonical ID")
    return project_id


def _with_created_at(candidate: ManagerDispatchCandidate, created_at: str) -> ManagerDispatchCandidate:
    return ManagerDispatchCandidate(
        task_id=candidate.task_id,
        task_revision=candidate.task_revision,
        task_content_hash=candidate.task_content_hash,
        created_at=created_at,
        input_resolution_id=candidate.input_resolution_id,
        dispatch_binding_id=candidate.dispatch_binding_id,
        binding_audit_id=candidate.binding_audit_id,
        work_order_hash=candidate.work_order_hash,
        selected_adapter_id=candidate.selected_adapter_id,
        selected_adapter_fingerprint=candidate.selected_adapter_fingerprint,
        dispatch_contract_id=candidate.dispatch_contract_id,
        dispatch_contract_hash=candidate.dispatch_contract_hash,
        binder_id=candidate.binder_id,
        binder_fingerprint=candidate.binder_fingerprint,
        request_type_id=candidate.request_type_id,
        request_schema_hash=candidate.request_schema_hash,
        request_content_hash=candidate.request_content_hash,
    )


def inspect_manager_dispatch_admission_readonly(
    runtime: OriginForgeRuntime,
) -> ManagerDispatchAdmission:
    """Build one complete bounded scheduling admission without mutation.

    Phase 38A observes only already-existing Phase-34 evidence and canonical Task /
    claim state. It never activates a Task, constructs authority, acquires a claim,
    or invokes an adapter.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    try:
        audit_ids, scanned_count, scan_detail = _enumerate_binding_audit_ids(runtime)
    except (ProductionDispatchReadError, ProductionReadGuardError):
        return _empty_result(
            ManagerDispatchAdmissionStatus.INVALID_STATE,
            scanned_audit_count=0,
            detail=ManagerDispatchAdmissionDetail.INVALID_PHASE34_EVIDENCE,
        )
    if scan_detail is not None:
        return _empty_result(
            ManagerDispatchAdmissionStatus.LIMIT_EXCEEDED,
            scanned_audit_count=scanned_count,
            detail=scan_detail,
        )

    current_chains: list[ManagerDispatchCandidate] = []
    try:
        resolver_registry = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
        for audit_id in audit_ids:
            audit = read_dispatch_binding_audit(runtime, audit_id)
            binding = read_dispatch_binding(runtime, audit.dispatch_binding_id)
            bundle = read_input_resolution(runtime, audit.input_resolution_id)
            if (
                binding.input_resolution_id != bundle.input_resolution_id
                or audit.input_resolution_id != bundle.input_resolution_id
                or audit.dispatch_binding_id != binding.dispatch_binding_id
            ):
                raise ProductionDispatchReadError(
                    "binding audit does not form one exact Phase-34 chain"
                )
            currentness = inspect_dispatch_binding_currentness_readonly(
                runtime,
                bundle.input_resolution_id,
                binding.dispatch_binding_id,
                audit.binding_audit_id,
                resolver_registry,
                binder_registry,
            )
            if currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
                continue
            current_chains.append(
                ManagerDispatchCandidate(
                    task_id=binding.task_id,
                    task_revision=binding.task_revision,
                    task_content_hash=binding.task_content_hash,
                    created_at="",
                    input_resolution_id=bundle.input_resolution_id,
                    dispatch_binding_id=binding.dispatch_binding_id,
                    binding_audit_id=audit.binding_audit_id,
                    work_order_hash=binding.work_order_hash,
                    selected_adapter_id=binding.selected_adapter_id,
                    selected_adapter_fingerprint=binding.selected_adapter_fingerprint,
                    dispatch_contract_id=binding.dispatch_contract_id,
                    dispatch_contract_hash=binding.dispatch_contract_hash,
                    binder_id=binding.binder_id,
                    binder_fingerprint=binding.binder_fingerprint,
                    request_type_id=binding.request_type_id,
                    request_schema_hash=binding.request_schema_hash,
                    request_content_hash=binding.request_content_hash,
                )
            )
    except (ProductionDispatchReadError, ProductionReadGuardError, TypeError, ValueError):
        return _empty_result(
            ManagerDispatchAdmissionStatus.INVALID_STATE,
            scanned_audit_count=scanned_count,
            current_chain_count=len(current_chains),
            detail=ManagerDispatchAdmissionDetail.INVALID_PHASE34_EVIDENCE,
        )

    grouped: dict[str, list[ManagerDispatchCandidate]] = {}
    for candidate in current_chains:
        grouped.setdefault(candidate.task_id, []).append(candidate)
    if len(grouped) > _MAX_MANAGER_CANDIDATES:
        return _empty_result(
            ManagerDispatchAdmissionStatus.LIMIT_EXCEEDED,
            scanned_audit_count=scanned_count,
            current_chain_count=len(current_chains),
            detail=ManagerDispatchAdmissionDetail.CANDIDATE_LIMIT_EXCEEDED,
        )

    representatives: dict[str, ManagerDispatchCandidate] = {}
    ambiguous_task_ids: list[str] = []
    for task_id, chains in grouped.items():
        authority_keys = {chain.authority_key() for chain in chains}
        if len(authority_keys) != 1:
            ambiguous_task_ids.append(task_id)
            continue
        representatives[task_id] = min(
            chains,
            key=ManagerDispatchCandidate.representative_key,
        )
    ambiguous_task_ids.sort()

    admitted: list[ManagerDispatchCandidate] = []
    active_claim_exclusion_count = 0
    not_ready_exclusion_count = 0
    try:
        with production_read_connection(runtime) as conn:
            project_id = _project_id_connection(conn, runtime)
            for task_id in sorted(representatives):
                candidate = representatives[task_id]
                row = conn.execute(
                    """SELECT t.*, g.project_id
                       FROM tasks t
                       JOIN flows f ON f.id = t.flow_id
                       JOIN goals g ON g.id = f.goal_id
                       WHERE t.id = ?""",
                    (task_id,),
                ).fetchone()
                if row is None or row["project_id"] != project_id:
                    raise ValueError("candidate Task is outside current project")
                try:
                    task_status = TaskStatus(row["status"])
                    readiness = resolve_task_dependency_readiness_connection(
                        conn,
                        task_id,
                    )
                    current_hash = task_routing_hash(row)
                except (TaskReadinessError, TypeError, ValueError) as exc:
                    raise ValueError("candidate Task state is invalid") from exc

                if (
                    task_status is not TaskStatus.READY
                    or readiness.task_status is not TaskStatus.READY
                    or readiness.status is not DependencyReadinessStatus.READY
                    or int(row["revision"]) != candidate.task_revision
                    or current_hash != candidate.task_content_hash
                ):
                    not_ready_exclusion_count += 1
                    continue

                active_claim = conn.execute(
                    """SELECT claim_id FROM dispatch_claims
                       WHERE task_id = ? AND status = 'ACTIVE'
                       LIMIT 1""",
                    (task_id,),
                ).fetchone()
                if active_claim is not None:
                    active_claim_exclusion_count += 1
                    continue

                created_at = row["created_at"]
                if not isinstance(created_at, str) or not created_at:
                    raise ValueError("candidate Task created_at is invalid")
                admitted.append(_with_created_at(candidate, created_at))
    except (ProductionReadGuardError, ValueError, TypeError):
        return _empty_result(
            ManagerDispatchAdmissionStatus.INVALID_STATE,
            scanned_audit_count=scanned_count,
            current_chain_count=len(current_chains),
            active_claim_exclusion_count=active_claim_exclusion_count,
            not_ready_exclusion_count=not_ready_exclusion_count,
            ambiguous_task_ids=tuple(ambiguous_task_ids),
            detail=ManagerDispatchAdmissionDetail.INVALID_CANONICAL_STATE,
        )

    admitted.sort(key=lambda candidate: (candidate.created_at, candidate.task_id))
    status = (
        ManagerDispatchAdmissionStatus.AMBIGUOUS_AUTHORITY
        if ambiguous_task_ids
        else ManagerDispatchAdmissionStatus.COMPLETE
    )
    return ManagerDispatchAdmission(
        status=status,
        candidates=tuple(admitted),
        scanned_audit_count=scanned_count,
        current_chain_count=len(current_chains),
        active_claim_exclusion_count=active_claim_exclusion_count,
        not_ready_exclusion_count=not_ready_exclusion_count,
        ambiguous_task_ids=tuple(ambiguous_task_ids),
        detail=None,
    )
