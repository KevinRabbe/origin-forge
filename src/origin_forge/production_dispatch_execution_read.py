from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .config import load_config
from .ids import IdKind, validate_id
from .model_scheduler_factory import create_model_scheduling
from .production_dispatch_binding import build_builtin_dispatch_binder_registry
from .production_dispatch_binding_models import DispatchBindingCurrentnessStatus
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_claim_read import read_dispatch_claim
from .production_dispatch_execution_models import (
    DispatchExecution,
    DispatchExecutionModelError,
    DispatchExecutionStatus,
)
from .production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from .production_dispatch_read import (
    ProductionDispatchReadError,
    inspect_dispatch_binding_currentness_readonly,
    read_dispatch_binding,
)
from .production_execution_assembly import (
    ProductionExecutionDependencyPlan,
    _resource_model_config_hash,
    _role_policies,
    _sandbox_config_hash,
)
from .production_execution_owner import build_builtin_execution_owner_registry
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime


class ProductionDispatchExecutionReadError(RuntimeError):
    pass


class DispatchExecutionCurrentnessStatus(StrEnum):
    CURRENT_STARTED = "CURRENT_STARTED"
    RETURNED = "RETURNED"
    RAISED = "RAISED"
    INTERRUPTED = "INTERRUPTED"
    STALE_CLAIM = "STALE_CLAIM"
    STALE_BINDING = "STALE_BINDING"
    STALE_DEPENDENCY_PLAN = "STALE_DEPENDENCY_PLAN"
    INVALID = "INVALID"


@dataclass(frozen=True)
class DispatchExecutionCurrentness:
    execution_id: str
    claim_id: str | None
    task_id: str | None
    status: DispatchExecutionCurrentnessStatus
    detail: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.execution_id, str) or not validate_id(
            self.execution_id,
            IdKind.DISPATCH_EXECUTION,
        ):
            raise ProductionDispatchExecutionReadError(
                "execution currentness requires a valid DISPEXEC ID"
            )
        if self.claim_id is not None and (
            not isinstance(self.claim_id, str)
            or not validate_id(self.claim_id, IdKind.DISPATCH_CLAIM)
        ):
            raise ProductionDispatchExecutionReadError(
                "execution currentness claim_id is invalid"
            )
        if self.task_id is not None and (
            not isinstance(self.task_id, str)
            or not validate_id(self.task_id, IdKind.TASK)
        ):
            raise ProductionDispatchExecutionReadError(
                "execution currentness task_id is invalid"
            )
        if not isinstance(self.status, DispatchExecutionCurrentnessStatus):
            raise ProductionDispatchExecutionReadError(
                "execution currentness status is invalid"
            )
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail
        ):
            raise ProductionDispatchExecutionReadError(
                "execution currentness detail is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "detail": self.detail,
        }


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
        raise ProductionDispatchExecutionReadError(
            "stored dispatch execution failed canonical validation"
        ) from exc


def _validate_execution_id(execution_id: object) -> str:
    if not isinstance(execution_id, str) or not validate_id(
        execution_id,
        IdKind.DISPATCH_EXECUTION,
    ):
        raise ProductionDispatchExecutionReadError(
            "execution_id must be a valid DISPEXEC ID"
        )
    return execution_id


def _project_id_connection(conn, runtime: OriginForgeRuntime) -> str:
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?",
        (str(runtime.project_root),),
    ).fetchone()
    if row is None:
        raise ProductionDispatchExecutionReadError(
            "project is not initialized for current repository root"
        )
    project_id = row["id"]
    if not isinstance(project_id, str) or not validate_id(project_id, IdKind.PROJECT):
        raise ProductionDispatchExecutionReadError(
            "project has invalid canonical ID"
        )
    return project_id


def read_dispatch_execution(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> DispatchExecution:
    """Read one execution receipt through the immutable production SQLite boundary."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    execution_id = _validate_execution_id(execution_id)
    try:
        with production_read_connection(runtime) as conn:
            project_id = _project_id_connection(conn, runtime)
            row = conn.execute(
                "SELECT * FROM dispatch_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise ProductionDispatchExecutionReadError(
                    "dispatch execution does not exist"
                )
            execution = _execution_from_row(row)
            if execution.project_id != project_id:
                raise ProductionDispatchExecutionReadError(
                    "dispatch execution does not belong to current project"
                )
            return execution
    except ProductionDispatchExecutionReadError:
        raise
    except ProductionReadGuardError as exc:
        raise ProductionDispatchExecutionReadError(str(exc)) from exc


def _consumed_claim_matches_execution(runtime: OriginForgeRuntime, execution: DispatchExecution):
    try:
        claim = read_dispatch_claim(runtime, execution.claim_id)
    except Exception as exc:
        raise ProductionDispatchExecutionReadError(
            "execution claim cannot be read canonically"
        ) from exc
    if claim.status is not DispatchClaimStatus.CONSUMED:
        raise ProductionDispatchExecutionReadError(
            f"execution claim is not CONSUMED: {claim.status.value}"
        )
    if claim.revision != execution.claim_revision_at_start + 1:
        raise ProductionDispatchExecutionReadError(
            "consumed claim revision does not match execution start boundary"
        )
    if claim.terminal_reason != f"claim consumed by dispatch execution {execution.execution_id}":
        raise ProductionDispatchExecutionReadError(
            "consumed claim reason does not bind exact execution ID"
        )
    if (
        claim.project_id != execution.project_id
        or claim.claim_id != execution.claim_id
        or claim.task_id != execution.task_id
        or claim.task_revision != execution.task_revision
        or claim.task_content_hash != execution.task_content_hash
        or claim.work_order_id != execution.work_order_id
        or claim.work_order_hash != execution.work_order_hash
        or claim.input_resolution_id != execution.input_resolution_id
        or claim.input_resolution_hash != execution.input_resolution_hash
        or claim.dispatch_binding_id != execution.dispatch_binding_id
        or claim.dispatch_binding_hash != execution.dispatch_binding_hash
        or claim.binding_audit_id != execution.binding_audit_id
        or claim.binding_audit_hash != execution.binding_audit_hash
        or claim.selected_adapter_id != execution.selected_adapter_id
        or claim.selected_adapter_fingerprint
        != execution.selected_adapter_fingerprint
        or claim.dispatch_contract_id != execution.dispatch_contract_id
        or claim.dispatch_contract_hash != execution.dispatch_contract_hash
        or claim.binder_id != execution.binder_id
        or claim.binder_fingerprint != execution.binder_fingerprint
    ):
        raise ProductionDispatchExecutionReadError(
            "execution receipt does not match frozen consumed-claim authority"
        )
    return claim


def _reconstruct_dependency_plan(
    runtime: OriginForgeRuntime,
    execution: DispatchExecution,
) -> ProductionExecutionDependencyPlan:
    try:
        binding = read_dispatch_binding(runtime, execution.dispatch_binding_id)
    except ProductionDispatchReadError as exc:
        raise ProductionDispatchExecutionReadError(
            "execution dispatch binding cannot be read canonically"
        ) from exc
    if (
        binding.content_hash != execution.dispatch_binding_hash
        or binding.task_id != execution.task_id
        or binding.task_revision != execution.task_revision
        or binding.task_content_hash != execution.task_content_hash
        or binding.work_order_id != execution.work_order_id
        or binding.work_order_hash != execution.work_order_hash
        or binding.selected_adapter_id != execution.selected_adapter_id
        or binding.selected_adapter_fingerprint
        != execution.selected_adapter_fingerprint
        or binding.dispatch_contract_id != execution.dispatch_contract_id
        or binding.dispatch_contract_hash != execution.dispatch_contract_hash
        or binding.binder_id != execution.binder_id
        or binding.binder_fingerprint != execution.binder_fingerprint
    ):
        raise ProductionDispatchExecutionReadError(
            "current dispatch binding does not match execution receipt"
        )

    owner_registry = build_builtin_execution_owner_registry()
    try:
        owner = owner_registry.owner_for(
            adapter_id=binding.selected_adapter_id,
            adapter_fingerprint=binding.selected_adapter_fingerprint,
            dispatch_contract_id=binding.dispatch_contract_id,
            binder_id=binding.binder_id,
            binder_fingerprint=binding.binder_fingerprint,
            request_type_id=binding.request_type_id,
            request_schema_hash=binding.request_schema_hash,
        )
    except RuntimeError as exc:
        raise ProductionDispatchExecutionReadError(
            "current trusted execution-owner registry no longer accepts binding"
        ) from exc
    if (
        owner.owner_id != execution.execution_owner_id
        or owner.fingerprint != execution.execution_owner_fingerprint
    ):
        raise ProductionDispatchExecutionReadError(
            "execution owner identity/fingerprint drifted"
        )

    config = load_config(runtime.project_root)
    if config.version < 6:
        raise ProductionDispatchExecutionReadError(
            "current protected config version cannot reconstruct managed execution"
        )
    if owner.requires_sandbox and (
        config.sandbox_backend.lower() != "podman" or not config.sandbox_image
    ):
        raise ProductionDispatchExecutionReadError(
            "current protected sandbox configuration no longer satisfies execution owner"
        )
    try:
        scheduling = create_model_scheduling(config.resource_models)
        policies = _role_policies(config, owner)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise ProductionDispatchExecutionReadError(
            "current protected model scheduling cannot reconstruct execution plan"
        ) from exc

    profile_ids: list[str] = []
    runtime_ids: set[str] = set()
    provider_by_runtime: dict[str, object] = {}
    for policy in policies:
        for profile_id in policy.ordered_profile_ids:
            try:
                profile = scheduling.registry.profile(profile_id)
                provider = config.model_runtimes.provider_for_profile(profile.profile_id)
            except Exception as exc:
                raise ProductionDispatchExecutionReadError(
                    f"current model profile {profile_id} lacks exact runtime authority"
                ) from exc
            if provider.runtime_id != profile.runtime_id:
                raise ProductionDispatchExecutionReadError(
                    f"current model profile {profile_id} runtime/provider relation drifted"
                )
            existing = provider_by_runtime.get(provider.runtime_id)
            if existing is not None and existing != provider:
                raise ProductionDispatchExecutionReadError(
                    "current runtime_id resolves to conflicting protected providers"
                )
            profile_ids.append(profile.profile_id)
            runtime_ids.add(provider.runtime_id)
            provider_by_runtime[provider.runtime_id] = provider

    return ProductionExecutionDependencyPlan(
        claim_id=execution.claim_id,
        claim_revision=execution.claim_revision_at_start,
        task_id=execution.task_id,
        task_revision=execution.task_revision,
        task_content_hash=execution.task_content_hash,
        dispatch_binding_id=binding.dispatch_binding_id,
        dispatch_binding_hash=binding.content_hash,
        request_type_id=binding.request_type_id,
        request_schema_hash=binding.request_schema_hash,
        request_content_hash=binding.request_content_hash,
        owner_id=owner.owner_id,
        owner_fingerprint=owner.fingerprint,
        owner_registry_fingerprint=owner_registry.fingerprint,
        config_version=config.version,
        resource_model_config_hash=_resource_model_config_hash(config),
        model_runtime_config_fingerprint=config.model_runtimes.fingerprint,
        model_strategy_roles=tuple(role.value for role in owner.model_strategy_roles),
        model_profile_ids=tuple(profile_ids),
        runtime_ids=tuple(sorted(runtime_ids)),
        runtime_provider_fingerprints=tuple(
            (runtime_id, provider_by_runtime[runtime_id].fingerprint)
            for runtime_id in sorted(runtime_ids)
        ),
        sandbox_backend=config.sandbox_backend.lower(),
        sandbox_config_hash=_sandbox_config_hash(config),
    )


def inspect_dispatch_execution_currentness_readonly(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> DispatchExecutionCurrentness:
    """Revalidate one receipt for pre-dispatch use without executing anything."""

    execution_id = _validate_execution_id(execution_id)

    def result(
        execution: DispatchExecution | None,
        status: DispatchExecutionCurrentnessStatus,
        detail: str | None,
    ) -> DispatchExecutionCurrentness:
        return DispatchExecutionCurrentness(
            execution_id,
            None if execution is None else execution.claim_id,
            None if execution is None else execution.task_id,
            status,
            detail,
        )

    try:
        execution = read_dispatch_execution(runtime, execution_id)
    except ProductionDispatchExecutionReadError as exc:
        return result(None, DispatchExecutionCurrentnessStatus.INVALID, str(exc))

    try:
        _consumed_claim_matches_execution(runtime, execution)
    except ProductionDispatchExecutionReadError as exc:
        return result(
            execution,
            DispatchExecutionCurrentnessStatus.STALE_CLAIM,
            str(exc),
        )

    if execution.status is DispatchExecutionStatus.RETURNED:
        return result(execution, DispatchExecutionCurrentnessStatus.RETURNED, None)
    if execution.status is DispatchExecutionStatus.RAISED:
        return result(execution, DispatchExecutionCurrentnessStatus.RAISED, None)
    if execution.status is DispatchExecutionStatus.INTERRUPTED:
        return result(execution, DispatchExecutionCurrentnessStatus.INTERRUPTED, None)
    if execution.status is not DispatchExecutionStatus.STARTED:
        return result(
            execution,
            DispatchExecutionCurrentnessStatus.INVALID,
            "dispatch execution has unsupported lifecycle state",
        )

    resolver_registry = build_dispatch_input_resolver_registry()
    binder_registry = build_builtin_dispatch_binder_registry()
    try:
        binding_currentness = inspect_dispatch_binding_currentness_readonly(
            runtime,
            execution.input_resolution_id,
            execution.dispatch_binding_id,
            execution.binding_audit_id,
            resolver_registry,
            binder_registry,
        )
    except ProductionDispatchReadError as exc:
        return result(
            execution,
            DispatchExecutionCurrentnessStatus.STALE_BINDING,
            f"Phase-34 currentness could not be read: {exc}",
        )
    if binding_currentness.status is not DispatchBindingCurrentnessStatus.CURRENT_READY:
        return result(
            execution,
            DispatchExecutionCurrentnessStatus.STALE_BINDING,
            f"Phase-34 binding currentness is {binding_currentness.status.value}",
        )

    try:
        plan = _reconstruct_dependency_plan(runtime, execution)
    except ProductionDispatchExecutionReadError as exc:
        return result(
            execution,
            DispatchExecutionCurrentnessStatus.STALE_DEPENDENCY_PLAN,
            str(exc),
        )
    if plan.plan_hash != execution.runtime_dependency_plan_hash:
        return result(
            execution,
            DispatchExecutionCurrentnessStatus.STALE_DEPENDENCY_PLAN,
            "current protected execution dependency plan hash no longer matches STARTED receipt",
        )
    return result(
        execution,
        DispatchExecutionCurrentnessStatus.CURRENT_STARTED,
        None,
    )
