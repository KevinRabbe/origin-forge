from __future__ import annotations

from dataclasses import dataclass

from .config import ProjectConfig, load_config
from .managed_llamacpp_loader import ManagedLlamaCppCpuLoader
from .model_runtime_registry import (
    ModelRuntimeBinding,
    ModelRuntimeRegistry,
    RuntimeDispatchLoader,
)
from .model_scheduler import ModelRole, ModelSelectionPolicy
from .model_scheduler_factory import ConfiguredModelScheduling, create_model_scheduling
from .production_preparation_models import TaskPreparationPolicyBinding
from .production_preparation_owner import (
    ProductionPreparationOwnerDescriptor,
    ProductionPreparationOwnerError,
    build_builtin_preparation_owner_registry,
    require_current_preparation_owner,
)
from .production_preparation_provenance import (
    ProductionPreparationProvenanceError,
    resolve_preparation_policy_provenance,
)
from .production_work_order_models import content_hash
from .runtime import OriginForgeRuntime
from .scheduled_model_adapter import RuntimeModelScheduleRecorder, ScheduledModelAdapter


class ProductionPreparationAssemblyError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparationPlannerDependencyPlan:
    preparation_policy_id: str
    preparation_policy_hash: str
    preparation_owner_id: str
    preparation_owner_fingerprint: str
    owner_registry_fingerprint: str
    planner_request_version: str
    planner_contract_id: str
    config_version: int
    resource_model_config_hash: str
    model_runtime_config_fingerprint: str
    model_strategy_roles: tuple[str, ...]
    model_policy_chain: tuple[tuple[str, str, tuple[str, ...]], ...]
    model_profile_ids: tuple[str, ...]
    runtime_ids: tuple[str, ...]
    runtime_provider_fingerprints: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "preparation_policy_id": self.preparation_policy_id,
            "preparation_policy_hash": self.preparation_policy_hash,
            "preparation_owner_id": self.preparation_owner_id,
            "preparation_owner_fingerprint": self.preparation_owner_fingerprint,
            "owner_registry_fingerprint": self.owner_registry_fingerprint,
            "planner_request_version": self.planner_request_version,
            "planner_contract_id": self.planner_contract_id,
            "config_version": self.config_version,
            "resource_model_config_hash": self.resource_model_config_hash,
            "model_runtime_config_fingerprint": self.model_runtime_config_fingerprint,
            "model_strategy_roles": list(self.model_strategy_roles),
            "model_policy_chain": [
                {
                    "role": role,
                    "primary_profile_id": primary,
                    "fallback_profile_ids": list(fallbacks),
                }
                for role, primary, fallbacks in self.model_policy_chain
            ],
            "model_profile_ids": list(self.model_profile_ids),
            "runtime_ids": list(self.runtime_ids),
            "runtime_provider_fingerprints": [
                {"runtime_id": runtime_id, "provider_fingerprint": fingerprint}
                for runtime_id, fingerprint in self.runtime_provider_fingerprints
            ],
        }

    @property
    def plan_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class PreparationPlannerDependencies:
    plan: PreparationPlannerDependencyPlan
    owner: ProductionPreparationOwnerDescriptor
    model_scheduling: ConfiguredModelScheduling
    runtime_registry: ModelRuntimeRegistry
    runtime_dispatch_loader: RuntimeDispatchLoader
    managed_loaders: tuple[ManagedLlamaCppCpuLoader, ...]
    model: ScheduledModelAdapter


def _resource_model_config_hash(config: ProjectConfig) -> str:
    resource_models = config.resource_models
    capacity = resource_models.capacity
    capacity_payload = None
    if capacity is not None:
        capacity_payload = {
            "cpu_slots": capacity.cpu_slots,
            "ram_mib": capacity.ram_mib,
            "max_active_leases": capacity.max_active_leases,
            "gpus": [
                {
                    "device_id": gpu.device_id,
                    "vram_mib": gpu.vram_mib,
                    "reserve_vram_mib": gpu.reserve_vram_mib,
                    "compute_slots": gpu.compute_slots,
                }
                for gpu in sorted(capacity.gpus, key=lambda value: value.device_id)
            ],
        }
    return content_hash(
        {
            "enabled": resource_models.enabled,
            "capacity": capacity_payload,
            "profiles": [
                profile.to_dict()
                for profile in sorted(
                    resource_models.profiles,
                    key=lambda value: value.profile_id,
                )
            ],
            "policies": [
                {
                    "role": policy.role.value,
                    "primary_profile_id": policy.primary_profile_id,
                    "fallback_profile_ids": list(policy.fallback_profile_ids),
                }
                for policy in sorted(
                    resource_models.policies,
                    key=lambda value: value.role.value,
                )
            ],
        }
    )


def _role_policies(
    config: ProjectConfig,
    owner: ProductionPreparationOwnerDescriptor,
) -> tuple[ModelSelectionPolicy, ...]:
    result: list[ModelSelectionPolicy] = []
    for role in owner.model_strategy_roles:
        if not isinstance(role, ModelRole):
            raise ProductionPreparationAssemblyError(
                "preparation owner model role is invalid"
            )
        try:
            result.append(config.resource_models.policy(role))
        except KeyError as exc:
            raise ProductionPreparationAssemblyError(
                f"protected model configuration has no policy for preparation role {role.value}"
            ) from exc
    return tuple(result)


def assemble_preparation_planner_dependencies(
    runtime: OriginForgeRuntime,
    policy: TaskPreparationPolicyBinding,
) -> PreparationPlannerDependencies:
    """Assemble exact WorkOrder-planner dependencies without crossing model authority.

    Construction validates protected model policy/runtime-provider relations and
    creates only lazy loader/scheduler objects. Resource leases, model loads,
    subprocesses, Runs, WorkOrders, sandboxes, and Workspaces remain absent until
    a later explicit planner invocation.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(policy, TaskPreparationPolicyBinding):
        raise TypeError("policy must be a TaskPreparationPolicyBinding")

    try:
        provenance = resolve_preparation_policy_provenance(runtime, policy)
        owner_registry = build_builtin_preparation_owner_registry()
        owner = require_current_preparation_owner(
            policy,
            provenance.dispatch_contract_catalog,
            registry=owner_registry,
        )
    except (
        ProductionPreparationProvenanceError,
        ProductionPreparationOwnerError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionPreparationAssemblyError(
            "PREPPOL is not current code-owned preparation authority"
        ) from exc

    config = load_config(runtime.project_root)
    if config.version < 6:
        raise ProductionPreparationAssemblyError(
            "managed WorkOrder planning requires protected config version 6"
        )
    try:
        scheduling = create_model_scheduling(config.resource_models)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise ProductionPreparationAssemblyError(
            "protected resource/model scheduling is not executable"
        ) from exc
    policies = _role_policies(config, owner)
    if len(policies) != 1:
        raise ProductionPreparationAssemblyError(
            "v1 WorkOrder planning requires exactly one semantic model role"
        )

    profile_ids: list[str] = []
    runtime_ids: set[str] = set()
    provider_by_runtime: dict[str, object] = {}
    model_policy_chain: list[tuple[str, str, tuple[str, ...]]] = []
    for selection in policies:
        model_policy_chain.append(
            (
                selection.role.value,
                selection.primary_profile_id,
                tuple(selection.fallback_profile_ids),
            )
        )
        for profile_id in selection.ordered_profile_ids:
            profile = scheduling.registry.profile(profile_id)
            profile_ids.append(profile.profile_id)
            try:
                provider = config.model_runtimes.provider_for_profile(profile.profile_id)
            except KeyError as exc:
                raise ProductionPreparationAssemblyError(
                    f"model profile {profile.profile_id} has no protected runtime provider binding"
                ) from exc
            if provider.runtime_id != profile.runtime_id:
                raise ProductionPreparationAssemblyError(
                    f"model profile {profile.profile_id} runtime/provider relation drifted"
                )
            existing = provider_by_runtime.get(provider.runtime_id)
            if existing is not None and existing != provider:
                raise ProductionPreparationAssemblyError(
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
    dispatch_loader = runtime_registry.dispatch_loader()
    recorder = RuntimeModelScheduleRecorder(runtime)
    model = ScheduledModelAdapter(
        scheduling.scheduler,
        policies[0],
        dispatch_loader,
        recorder=recorder,
    )

    provider_fingerprints = tuple(
        (runtime_id, provider_by_runtime[runtime_id].fingerprint)
        for runtime_id in sorted(runtime_ids)
    )
    plan = PreparationPlannerDependencyPlan(
        preparation_policy_id=policy.preparation_policy_id,
        preparation_policy_hash=policy.content_hash,
        preparation_owner_id=owner.owner_id,
        preparation_owner_fingerprint=owner.fingerprint,
        owner_registry_fingerprint=owner_registry.fingerprint,
        planner_request_version=owner.planner_request_version,
        planner_contract_id=owner.planner_contract_id,
        config_version=config.version,
        resource_model_config_hash=_resource_model_config_hash(config),
        model_runtime_config_fingerprint=config.model_runtimes.fingerprint,
        model_strategy_roles=tuple(role.value for role in owner.model_strategy_roles),
        model_policy_chain=tuple(model_policy_chain),
        model_profile_ids=tuple(profile_ids),
        runtime_ids=tuple(sorted(runtime_ids)),
        runtime_provider_fingerprints=provider_fingerprints,
    )
    return PreparationPlannerDependencies(
        plan=plan,
        owner=owner,
        model_scheduling=scheduling,
        runtime_registry=runtime_registry,
        runtime_dispatch_loader=dispatch_loader,
        managed_loaders=managed_loaders,
        model=model,
    )
