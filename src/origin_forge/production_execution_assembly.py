from __future__ import annotations

from dataclasses import dataclass

from .config import ProjectConfig, load_config
from .managed_llamacpp_loader import ManagedLlamaCppCpuLoader
from .model_runtime_registry import ModelRuntimeBinding, ModelRuntimeRegistry, RuntimeDispatchLoader
from .model_scheduler import ModelRole, ModelSelectionPolicy
from .model_scheduler_factory import ConfiguredModelScheduling, create_model_scheduling
from .orchestration_policy import BoundedRetryPolicy
from .production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    inspect_dispatch_claim_currentness_readonly,
    read_dispatch_claim,
)
from .production_dispatch_read import read_dispatch_binding
from .production_execution_owner import (
    ProductionExecutionOwnerDescriptor,
    build_builtin_execution_owner_registry,
)
from .production_work_order_models import content_hash
from .runtime import OriginForgeRuntime
from .sandbox import SandboxBackend
from .sandbox_factory import create_sandbox_backend
from .scheduled_model_adapter import RuntimeModelScheduleRecorder, ScheduledModelAdapter
from .workspaces import GitWorkspaceManager


class ProductionExecutionAssemblyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductionExecutionDependencyPlan:
    claim_id: str
    claim_revision: int
    task_id: str
    task_revision: int
    task_content_hash: str
    dispatch_binding_id: str
    dispatch_binding_hash: str
    request_type_id: str
    request_schema_hash: str
    request_content_hash: str
    owner_id: str
    owner_fingerprint: str
    owner_registry_fingerprint: str
    config_version: int
    model_runtime_config_fingerprint: str
    model_strategy_roles: tuple[str, ...]
    model_profile_ids: tuple[str, ...]
    runtime_ids: tuple[str, ...]
    runtime_provider_fingerprints: tuple[tuple[str, str], ...]
    sandbox_backend: str
    sandbox_config_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "claim_revision": self.claim_revision,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "dispatch_binding_id": self.dispatch_binding_id,
            "dispatch_binding_hash": self.dispatch_binding_hash,
            "request_type_id": self.request_type_id,
            "request_schema_hash": self.request_schema_hash,
            "request_content_hash": self.request_content_hash,
            "owner_id": self.owner_id,
            "owner_fingerprint": self.owner_fingerprint,
            "owner_registry_fingerprint": self.owner_registry_fingerprint,
            "config_version": self.config_version,
            "model_runtime_config_fingerprint": self.model_runtime_config_fingerprint,
            "model_strategy_roles": list(self.model_strategy_roles),
            "model_profile_ids": list(self.model_profile_ids),
            "runtime_ids": list(self.runtime_ids),
            "runtime_provider_fingerprints": [
                {"runtime_id": runtime_id, "provider_fingerprint": fingerprint}
                for runtime_id, fingerprint in self.runtime_provider_fingerprints
            ],
            "sandbox_backend": self.sandbox_backend,
            "sandbox_config_hash": self.sandbox_config_hash,
        }

    @property
    def plan_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class ProductionExecutionDependencies:
    plan: ProductionExecutionDependencyPlan
    owner: ProductionExecutionOwnerDescriptor
    model_scheduling: ConfiguredModelScheduling
    runtime_registry: ModelRuntimeRegistry
    runtime_dispatch_loader: RuntimeDispatchLoader
    managed_loaders: tuple[ManagedLlamaCppCpuLoader, ...]
    models: tuple[ScheduledModelAdapter, ...]
    sandbox_backend: SandboxBackend
    workspaces: GitWorkspaceManager
    bounded_retry_policy: BoundedRetryPolicy


def _sandbox_config_hash(config: ProjectConfig) -> str:
    return content_hash(
        {
            "backend": config.sandbox_backend,
            "image": config.sandbox_image,
            "network": config.sandbox_network,
            "memory": config.sandbox_memory,
            "cpus": config.sandbox_cpus,
            "pids_limit": config.sandbox_pids_limit,
        }
    )


def _require_executable_sandbox(config: ProjectConfig) -> None:
    if config.sandbox_backend.lower() != "podman" or not config.sandbox_image:
        raise ProductionExecutionAssemblyError(
            "trusted execution owner requires an explicitly configured Podman sandbox"
        )


def _role_policies(
    config: ProjectConfig,
    owner: ProductionExecutionOwnerDescriptor,
) -> tuple[ModelSelectionPolicy, ...]:
    result: list[ModelSelectionPolicy] = []
    for role in owner.model_strategy_roles:
        if not isinstance(role, ModelRole):
            raise ProductionExecutionAssemblyError("execution owner model role is invalid")
        try:
            result.append(config.resource_models.policy(role))
        except KeyError as exc:
            raise ProductionExecutionAssemblyError(
                f"protected model configuration has no policy for execution role {role.value}"
            ) from exc
    return tuple(result)


def assemble_production_execution_dependencies(
    runtime: OriginForgeRuntime,
    claim_id: str,
) -> ProductionExecutionDependencies:
    """Assemble one exact execution dependency graph without invoking it."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    currentness = inspect_dispatch_claim_currentness_readonly(runtime, claim_id)
    if currentness.status is not DispatchClaimCurrentnessStatus.CURRENT_ACTIVE:
        raise ProductionExecutionAssemblyError(
            f"dispatch claim is not CURRENT_ACTIVE: {currentness.status.value}"
        )
    claim = read_dispatch_claim(runtime, claim_id)
    binding = read_dispatch_binding(runtime, claim.dispatch_binding_id)
    if binding.content_hash != claim.dispatch_binding_hash:
        raise ProductionExecutionAssemblyError(
            "dispatch claim binding hash no longer matches exact Phase-34 binding"
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
        raise ProductionExecutionAssemblyError(
            "no trusted execution owner matches the exact current dispatch binding"
        ) from exc

    config = load_config(runtime.project_root)
    if config.version < 6:
        raise ProductionExecutionAssemblyError(
            "managed production execution requires protected config version 6"
        )
    if owner.requires_sandbox:
        _require_executable_sandbox(config)

    try:
        scheduling = create_model_scheduling(config.resource_models)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise ProductionExecutionAssemblyError(
            "protected resource/model scheduling is not executable"
        ) from exc
    policies = _role_policies(config, owner)

    profile_ids: list[str] = []
    runtime_ids: set[str] = set()
    provider_by_runtime: dict[str, object] = {}
    for policy in policies:
        for profile_id in policy.ordered_profile_ids:
            profile = scheduling.registry.profile(profile_id)
            profile_ids.append(profile.profile_id)
            try:
                provider = config.model_runtimes.provider_for_profile(profile.profile_id)
            except KeyError as exc:
                raise ProductionExecutionAssemblyError(
                    f"model profile {profile.profile_id} has no protected runtime provider binding"
                ) from exc
            if provider.runtime_id != profile.runtime_id:
                raise ProductionExecutionAssemblyError(
                    f"model profile {profile.profile_id} runtime/provider relation drifted"
                )
            existing = provider_by_runtime.get(provider.runtime_id)
            if existing is not None and existing != provider:
                raise ProductionExecutionAssemblyError(
                    "one runtime_id resolved to conflicting protected providers"
                )
            provider_by_runtime[provider.runtime_id] = provider
            runtime_ids.add(provider.runtime_id)

    managed_loaders = tuple(
        ManagedLlamaCppCpuLoader(runtime.project_root, provider_by_runtime[runtime_id])
        for runtime_id in sorted(runtime_ids)
    )
    loader_by_runtime = {
        loader.provider.runtime_id: loader for loader in managed_loaders
    }
    runtime_registry = ModelRuntimeRegistry(
        tuple(
            ModelRuntimeBinding(runtime_id, loader_by_runtime[runtime_id])
            for runtime_id in sorted(runtime_ids)
        )
    )
    runtime_dispatch_loader = runtime_registry.dispatch_loader()
    recorder = RuntimeModelScheduleRecorder(runtime)
    models = tuple(
        ScheduledModelAdapter(
            scheduling.scheduler,
            policy,
            runtime_dispatch_loader,
            recorder=recorder,
        )
        for policy in policies
    )

    sandbox_backend = create_sandbox_backend(runtime, config)
    workspaces = GitWorkspaceManager(runtime)
    bounded_retry_policy = BoundedRetryPolicy(
        runtime,
        models,
        sandbox_backend,
        workspaces=workspaces,
    )

    provider_fingerprints = tuple(
        (runtime_id, provider_by_runtime[runtime_id].fingerprint)
        for runtime_id in sorted(runtime_ids)
    )
    plan = ProductionExecutionDependencyPlan(
        claim_id=claim.claim_id,
        claim_revision=claim.revision,
        task_id=claim.task_id,
        task_revision=claim.task_revision,
        task_content_hash=claim.task_content_hash,
        dispatch_binding_id=binding.dispatch_binding_id,
        dispatch_binding_hash=binding.content_hash,
        request_type_id=binding.request_type_id,
        request_schema_hash=binding.request_schema_hash,
        request_content_hash=binding.request_content_hash,
        owner_id=owner.owner_id,
        owner_fingerprint=owner.fingerprint,
        owner_registry_fingerprint=owner_registry.fingerprint,
        config_version=config.version,
        model_runtime_config_fingerprint=config.model_runtimes.fingerprint,
        model_strategy_roles=tuple(role.value for role in owner.model_strategy_roles),
        model_profile_ids=tuple(profile_ids),
        runtime_ids=tuple(sorted(runtime_ids)),
        runtime_provider_fingerprints=provider_fingerprints,
        sandbox_backend=config.sandbox_backend.lower(),
        sandbox_config_hash=_sandbox_config_hash(config),
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        model_scheduling=scheduling,
        runtime_registry=runtime_registry,
        runtime_dispatch_loader=runtime_dispatch_loader,
        managed_loaders=managed_loaders,
        models=models,
        sandbox_backend=sandbox_backend,
        workspaces=workspaces,
        bounded_retry_policy=bounded_retry_policy,
    )
