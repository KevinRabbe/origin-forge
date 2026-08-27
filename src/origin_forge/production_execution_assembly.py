from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from .adapters.comfyui import ComfyUiProfile
from .audio_profiles import AudioProfileStore, GovernedAudioProfile
from .blender_adapter import BlenderRuntimeProfile
from .config import ProjectConfig, load_config
from .image_workflows import GovernedComfyWorkflowTemplate, ImageWorkflowStore
from .managed_llamacpp_loader import ManagedLlamaCppCpuLoader
from .model_runtime_config import ManagedModelRuntimeProviderConfig
from .model_runtime_registry import (
    ModelRuntimeBinding,
    ModelRuntimeRegistry,
    RuntimeDispatchLoader,
)
from .model_scheduler import ModelRole, ModelSelectionPolicy
from .model_scheduler_factory import ConfiguredModelScheduling, create_model_scheduling
from .orchestration_policy import BoundedRetryPolicy
from .pixelorama_bridge import PixeloramaBridgeProfile
from .pixelorama_cli_export import PixeloramaCliProfile
from .production_blender_profile import (
    ProductionBlenderProfileError,
    blender_runtime_profile_dependency_hash,
    load_infrastructure_blender_runtime_profile,
)
from .production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    inspect_dispatch_claim_currentness_readonly,
    read_dispatch_claim,
)
from .production_dispatch_invocation_ffmpeg import FfmpegInvocationRequest
from .production_dispatch_invocation_image import ImageGenerationInvocationRequest
from .production_dispatch_invocation_piper import PiperInvocationRequest
from .production_dispatch_read import read_dispatch_binding
from .production_execution_owner import (
    ProductionExecutionOwnerDescriptor,
    ProductionExecutionOwnerRegistry,
    build_builtin_execution_owner_registry,
)
from .production_execution_owner_audio import FFMPEG_EXECUTION_OWNER_ID
from .production_execution_owner_image import IMAGE_EXECUTION_OWNER_ID
from .production_ffmpeg_profile import (
    FfmpegInfrastructure,
    load_infrastructure_ffmpeg_profile,
)
from .production_piper_profile import (
    PiperInfrastructure,
    load_infrastructure_piper_profile,
)
from .production_pixelorama_profile import (
    ProductionPixeloramaProfileError,
    load_infrastructure_pixelorama_bridge_profile,
    load_infrastructure_pixelorama_cli_profile,
    pixelorama_bridge_profile_dependency_hash,
    pixelorama_cli_profile_dependency_hash,
)
from .production_playtest_profile import (
    CooperativePlaytestInfrastructure,
    load_cooperative_playtest_infrastructure,
)
from .production_playtest_scenario_store import PlaytestScenarioStore
from .production_runtime_observation_store import RuntimeObservationRequestStore
from .production_runtime_profile import (
    RuntimeObservationInfrastructure,
    load_runtime_observation_infrastructure,
)
from .production_work_order_models import content_hash
from .runtime import OriginForgeRuntime
from .runtime_observation_models import RuntimeObservationRequest
from .sandbox import SandboxBackend
from .sandbox_factory import create_sandbox_backend
from .scheduled_model_adapter import RuntimeModelScheduleRecorder, ScheduledModelAdapter
from .workspaces import GitWorkspaceManager

_BOUNDED_RETRY_OWNER_ID = "originforge.execution.bounded-retry@1"
_BUILD_OWNER_ID = "originforge.execution.build.integration@1"
_SIMULATION_OWNER_ID = "originforge.execution.simulation.deterministic@1"
_PIXELORAMA_OWNER_ID = "originforge.execution.pixelorama.spritesheet-export@1"
_PIXELORAMA_SOURCE_OWNER_ID = "originforge.execution.pixelorama.source-create@1"
_BLENDER_OWNER_ID = "originforge.execution.blender.export-glb@1"
_PIPER_OWNER_ID = "originforge.execution.audio.piper-tts@1"
_FFMPEG_OWNER_ID = FFMPEG_EXECUTION_OWNER_ID
_RUNTIME_OBSERVER_OWNER_ID = "originforge.execution.runtime.observe@1"
_PLAYTEST_OWNER_ID = "originforge.execution.playtest.cooperative@1"
_NOT_REQUIRED_RESOURCE_MODEL_HASH = content_hash(
    {"kind": "NO_MODEL_RESOURCE_CONFIG", "version": 1}
)
_NOT_REQUIRED_MODEL_RUNTIME_HASH = content_hash(
    {"kind": "NO_MODEL_RUNTIME_CONFIG", "version": 1}
)
_NOT_REQUIRED_SANDBOX_HASH = content_hash(
    {"kind": "NO_SANDBOX_CONFIG", "version": 1}
)
_NOT_REQUIRED_SANDBOX_BACKEND = "not-required"
_SIMULATION_DEPENDENCY_MODE = "deterministic-simulation-no-runtime@1"


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
    resource_model_config_hash: str
    model_runtime_config_fingerprint: str
    model_strategy_roles: tuple[str, ...]
    model_profile_ids: tuple[str, ...]
    runtime_ids: tuple[str, ...]
    runtime_provider_fingerprints: tuple[tuple[str, str], ...]
    sandbox_backend: str
    sandbox_config_hash: str
    owner_dependency_hash: str | None = None

    def to_dict(self) -> dict[str, object]:
        value = {
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
            "resource_model_config_hash": self.resource_model_config_hash,
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
        if self.owner_dependency_hash is not None:
            value["owner_dependency_hash"] = self.owner_dependency_hash
        return value

    @property
    def plan_hash(self) -> str:
        return content_hash(self.to_dict())


class _CommonPlanFields(TypedDict):
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


@dataclass(frozen=True)
class BoundedRetryExecutionPayload:
    model_scheduling: ConfiguredModelScheduling
    runtime_registry: ModelRuntimeRegistry
    runtime_dispatch_loader: RuntimeDispatchLoader
    managed_loaders: tuple[ManagedLlamaCppCpuLoader, ...]
    models: tuple[ScheduledModelAdapter, ...]
    sandbox_backend: SandboxBackend
    workspaces: GitWorkspaceManager
    bounded_retry_policy: BoundedRetryPolicy


@dataclass(frozen=True)
class BuildIntegrationExecutionPayload:
    sandbox_backend: SandboxBackend
    workspaces: GitWorkspaceManager


@dataclass(frozen=True)
class DeterministicSimulationExecutionPayload:
    dependency_mode: str = _SIMULATION_DEPENDENCY_MODE

    def __post_init__(self) -> None:
        if self.dependency_mode != _SIMULATION_DEPENDENCY_MODE:
            raise ProductionExecutionAssemblyError(
                "simulation dependency payload mode is not current"
            )


@dataclass(frozen=True)
class PixeloramaSpritesheetExportExecutionPayload:
    profile: PixeloramaCliProfile
    profile_dependency_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile, PixeloramaCliProfile):
            raise TypeError("profile must be a PixeloramaCliProfile")
        expected = pixelorama_cli_profile_dependency_hash(self.profile)
        if self.profile_dependency_hash != expected:
            raise ProductionExecutionAssemblyError(
                "Pixelorama profile dependency hash is not current"
            )


@dataclass(frozen=True)
class PixeloramaSourceCreationExecutionPayload:
    profile: PixeloramaBridgeProfile
    profile_dependency_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile, PixeloramaBridgeProfile):
            raise TypeError("profile must be a PixeloramaBridgeProfile")
        expected = pixelorama_bridge_profile_dependency_hash(self.profile)
        if self.profile_dependency_hash != expected:
            raise ProductionExecutionAssemblyError(
                "Pixelorama source profile dependency hash is not current"
            )


@dataclass(frozen=True)
class BlenderExportGLBExecutionPayload:
    profile: BlenderRuntimeProfile
    profile_dependency_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile, BlenderRuntimeProfile):
            raise TypeError("profile must be a BlenderRuntimeProfile")
        expected = blender_runtime_profile_dependency_hash(self.profile)
        if self.profile_dependency_hash != expected:
            raise ProductionExecutionAssemblyError(
                "Blender profile dependency hash is not current"
            )


@dataclass(frozen=True)
class ImageGenerationExecutionPayload:
    request: ImageGenerationInvocationRequest
    profile: ComfyUiProfile
    template: GovernedComfyWorkflowTemplate
    profile_dependency_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, ImageGenerationInvocationRequest):
            raise TypeError("request must be an ImageGenerationInvocationRequest")
        if not isinstance(self.profile, ComfyUiProfile):
            raise TypeError("profile must be a ComfyUiProfile")
        if not isinstance(self.template, GovernedComfyWorkflowTemplate):
            raise TypeError("template must be a governed image workflow template")
        expected = content_hash(
            {
                "base_url": self.profile.base_url,
                "expected_version": self.profile.expected_version,
                "allow_remote": self.profile.allow_remote,
                "request_timeout_seconds": self.profile.request_timeout_seconds,
                "poll_interval_seconds": self.profile.poll_interval_seconds,
                "max_json_bytes": self.profile.max_json_bytes,
                "max_image_bytes": self.profile.max_image_bytes,
                "workflow_id": self.template.workflow_id,
                "workflow_hash": self.template.workflow_hash,
            }
        )
        if self.profile_dependency_hash != expected:
            raise ProductionExecutionAssemblyError(
                "ComfyUI profile/workflow dependency hash is not current"
            )
        if (
            self.template.workflow_id != self.request.workflow_id
            or self.template.workflow_hash != self.request.workflow_hash
            or self.template.model_id != self.request.model_id
            or self.template.model_hash != self.request.model_hash
            or self.template.backend_version != self.request.backend_version
        ):
            raise ProductionExecutionAssemblyError(
                "trusted image workflow does not match the frozen invocation"
            )


@dataclass(frozen=True)
class PiperExecutionPayload:
    request: PiperInvocationRequest
    profile: GovernedAudioProfile
    infrastructure: PiperInfrastructure

    def __post_init__(self) -> None:
        if not isinstance(self.request, PiperInvocationRequest):
            raise TypeError("request must be a PiperInvocationRequest")
        if not isinstance(self.profile, GovernedAudioProfile):
            raise TypeError("profile must be a GovernedAudioProfile")
        if not isinstance(self.infrastructure, PiperInfrastructure):
            raise TypeError("infrastructure must be PiperInfrastructure")
        if self.profile.profile_id != self.request.profile_id or self.profile.profile_hash != "sha256:" + self.request.profile_hash:
            raise ProductionExecutionAssemblyError("Piper profile does not match frozen request")


@dataclass(frozen=True)
class FfmpegExecutionPayload:
    request: FfmpegInvocationRequest
    profile: GovernedAudioProfile
    infrastructure: FfmpegInfrastructure

    def __post_init__(self) -> None:
        if not isinstance(self.request, FfmpegInvocationRequest):
            raise TypeError("request must be a FfmpegInvocationRequest")
        if not isinstance(self.profile, GovernedAudioProfile):
            raise TypeError("profile must be a GovernedAudioProfile")
        if not isinstance(self.infrastructure, FfmpegInfrastructure):
            raise TypeError("infrastructure must be FfmpegInfrastructure")
        if self.profile.profile_id != self.request.profile_id or self.profile.profile_hash != "sha256:" + self.request.profile_hash:
            raise ProductionExecutionAssemblyError("FFmpeg profile does not match frozen request")


@dataclass(frozen=True)
class RuntimeObservationExecutionPayload:
    request: RuntimeObservationRequest
    infrastructure: RuntimeObservationInfrastructure

    def __post_init__(self) -> None:
        if not isinstance(self.request, RuntimeObservationRequest):
            raise TypeError("request must be a RuntimeObservationRequest")
        if not isinstance(self.infrastructure, RuntimeObservationInfrastructure):
            raise TypeError("infrastructure must be RuntimeObservationInfrastructure")
        if self.request.executable_hash != self.infrastructure.executable_hash:
            raise ProductionExecutionAssemblyError(
                "runtime executable does not match frozen observation request"
            )


@dataclass(frozen=True)
class CooperativePlaytestExecutionPayload:
    scenario: object
    infrastructure: CooperativePlaytestInfrastructure

    def __post_init__(self) -> None:
        from .playtest_models import PlaytestScenario

        if not isinstance(self.scenario, PlaytestScenario):
            raise TypeError("scenario must be a PlaytestScenario")
        if not isinstance(self.infrastructure, CooperativePlaytestInfrastructure):
            raise TypeError("infrastructure must be CooperativePlaytestInfrastructure")
        if self.scenario.harness_hash != self.infrastructure.executable_hash:
            raise ProductionExecutionAssemblyError(
                "playtest harness does not match frozen scenario"
            )


ExecutionDependencyPayload = (
    BoundedRetryExecutionPayload
    | BuildIntegrationExecutionPayload
    | DeterministicSimulationExecutionPayload
    | PixeloramaSpritesheetExportExecutionPayload
    | PixeloramaSourceCreationExecutionPayload
    | BlenderExportGLBExecutionPayload
    | ImageGenerationExecutionPayload
    | PiperExecutionPayload
    | FfmpegExecutionPayload
    | RuntimeObservationExecutionPayload
    | CooperativePlaytestExecutionPayload
)


@dataclass(frozen=True)
class ProductionExecutionDependencies:
    plan: ProductionExecutionDependencyPlan
    owner: ProductionExecutionOwnerDescriptor
    payload: ExecutionDependencyPayload

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ProductionExecutionDependencyPlan):
            raise TypeError("plan must be a ProductionExecutionDependencyPlan")
        if not isinstance(self.owner, ProductionExecutionOwnerDescriptor):
            raise TypeError("owner must be a ProductionExecutionOwnerDescriptor")
        if self.plan.owner_id != self.owner.owner_id:
            raise ProductionExecutionAssemblyError(
                "dependency payload owner does not match dependency plan"
            )
        if self.plan.owner_fingerprint != self.owner.fingerprint:
            raise ProductionExecutionAssemblyError(
                "dependency payload owner fingerprint does not match dependency plan"
            )
        if self.owner.owner_id == _BOUNDED_RETRY_OWNER_ID:
            if not isinstance(self.payload, BoundedRetryExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "bounded-retry owner requires bounded execution payload"
                )
        elif self.owner.owner_id == _BUILD_OWNER_ID:
            if not isinstance(self.payload, BuildIntegrationExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "build owner requires sandbox/workspace execution payload"
                )
        elif self.owner.owner_id == _SIMULATION_OWNER_ID:
            if not isinstance(self.payload, DeterministicSimulationExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "simulation owner requires no-runtime simulation payload"
                )
        elif self.owner.owner_id == _PIXELORAMA_OWNER_ID:
            if not isinstance(self.payload, PixeloramaSpritesheetExportExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "Pixelorama owner requires trusted CLI profile payload"
                )
        elif self.owner.owner_id == _PIXELORAMA_SOURCE_OWNER_ID:
            if not isinstance(self.payload, PixeloramaSourceCreationExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "Pixelorama source owner requires trusted bridge profile payload"
                )
        elif self.owner.owner_id == _BLENDER_OWNER_ID:
            if not isinstance(self.payload, BlenderExportGLBExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "Blender owner requires trusted runtime profile payload"
                )
        elif self.owner.owner_id == IMAGE_EXECUTION_OWNER_ID:
            if not isinstance(self.payload, ImageGenerationExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "image owner requires trusted ComfyUI workflow/profile payload"
                )
        elif self.owner.owner_id == _PIPER_OWNER_ID:
            if not isinstance(self.payload, PiperExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "Piper owner requires trusted profile/infrastructure payload"
                )
        elif self.owner.owner_id == _FFMPEG_OWNER_ID:
            if not isinstance(self.payload, FfmpegExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "FFmpeg owner requires trusted profile/infrastructure payload"
                )
        elif self.owner.owner_id == _RUNTIME_OBSERVER_OWNER_ID:
            if not isinstance(self.payload, RuntimeObservationExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "runtime observer owner requires trusted request/infrastructure payload"
                )
        elif self.owner.owner_id == _PLAYTEST_OWNER_ID:
            if not isinstance(self.payload, CooperativePlaytestExecutionPayload):
                raise ProductionExecutionAssemblyError(
                    "playtest owner requires trusted scenario/infrastructure payload"
                )
        else:
            raise ProductionExecutionAssemblyError(
                "execution dependency payload has unsupported owner"
            )

    def _bounded_payload(self) -> BoundedRetryExecutionPayload:
        if not isinstance(self.payload, BoundedRetryExecutionPayload):
            raise ProductionExecutionAssemblyError(
                "execution dependencies do not contain bounded-retry runtime authority"
            )
        return self.payload

    @property
    def model_scheduling(self) -> ConfiguredModelScheduling:
        return self._bounded_payload().model_scheduling

    @property
    def runtime_registry(self) -> ModelRuntimeRegistry:
        return self._bounded_payload().runtime_registry

    @property
    def runtime_dispatch_loader(self) -> RuntimeDispatchLoader:
        return self._bounded_payload().runtime_dispatch_loader

    @property
    def managed_loaders(self) -> tuple[ManagedLlamaCppCpuLoader, ...]:
        return self._bounded_payload().managed_loaders

    @property
    def models(self) -> tuple[ScheduledModelAdapter, ...]:
        return self._bounded_payload().models

    @property
    def sandbox_backend(self) -> SandboxBackend:
        return self._bounded_payload().sandbox_backend

    @property
    def workspaces(self) -> GitWorkspaceManager:
        return self._bounded_payload().workspaces

    @property
    def bounded_retry_policy(self) -> BoundedRetryPolicy:
        return self._bounded_payload().bounded_retry_policy


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


def _common_plan_fields(
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry: ProductionExecutionOwnerRegistry,
) -> _CommonPlanFields:
    return {
        "claim_id": claim.claim_id,
        "claim_revision": claim.revision,
        "task_id": claim.task_id,
        "task_revision": claim.task_revision,
        "task_content_hash": claim.task_content_hash,
        "dispatch_binding_id": binding.dispatch_binding_id,
        "dispatch_binding_hash": binding.content_hash,
        "request_type_id": binding.request_type_id,
        "request_schema_hash": binding.request_schema_hash,
        "request_content_hash": binding.request_content_hash,
        "owner_id": owner.owner_id,
        "owner_fingerprint": owner.fingerprint,
        "owner_registry_fingerprint": owner_registry.fingerprint,
    }


def _assemble_simulation_dependencies(
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _SIMULATION_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "simulation dependency assembler received an unexpected owner"
        )
    if owner.model_strategy_roles:
        raise ProductionExecutionAssemblyError(
            "deterministic simulation owner must not require model strategy roles"
        )
    if owner.requires_sandbox or owner.requires_workspace_manager:
        raise ProductionExecutionAssemblyError(
            "deterministic simulation owner must not require sandbox or workspace authority"
        )

    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(),
        model_profile_ids=(),
        runtime_ids=(),
        runtime_provider_fingerprints=(),
        sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=DeterministicSimulationExecutionPayload(),
    )


def _assemble_pixelorama_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _PIXELORAMA_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "Pixelorama dependency assembler received an unexpected owner"
        )
    if owner.model_strategy_roles:
        raise ProductionExecutionAssemblyError(
            "Pixelorama export owner must not require model strategy roles"
        )
    if owner.requires_sandbox or owner.requires_workspace_manager:
        raise ProductionExecutionAssemblyError(
            "Pixelorama export owner must not require coding sandbox or Git workspace authority"
        )
    try:
        profile = load_infrastructure_pixelorama_cli_profile(runtime.project_root)
    except ProductionPixeloramaProfileError as exc:
        raise ProductionExecutionAssemblyError(
            "trusted Pixelorama CLI profile is unavailable"
        ) from exc
    profile_hash = pixelorama_cli_profile_dependency_hash(profile)
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(),
        model_profile_ids=(),
        runtime_ids=(),
        runtime_provider_fingerprints=(),
        sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=profile_hash,
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=PixeloramaSpritesheetExportExecutionPayload(
            profile=profile,
            profile_dependency_hash=profile_hash,
        ),
    )


def _assemble_blender_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _BLENDER_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "Blender dependency assembler received an unexpected owner"
        )
    if owner.model_strategy_roles:
        raise ProductionExecutionAssemblyError(
            "Blender export owner must not require model strategy roles"
        )
    if owner.requires_sandbox or owner.requires_workspace_manager:
        raise ProductionExecutionAssemblyError(
            "Blender export owner must not require coding sandbox or Git workspace authority"
        )
    try:
        profile = load_infrastructure_blender_runtime_profile(runtime.project_root)
    except ProductionBlenderProfileError as exc:
        raise ProductionExecutionAssemblyError(
            "trusted Blender runtime profile is unavailable"
        ) from exc
    profile_hash = blender_runtime_profile_dependency_hash(profile)
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(),
        model_profile_ids=(),
        runtime_ids=(),
        runtime_provider_fingerprints=(),
        sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=profile_hash,
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=BlenderExportGLBExecutionPayload(
            profile=profile,
            profile_dependency_hash=profile_hash,
        ),
    )


def _assemble_image_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != IMAGE_EXECUTION_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "image dependency assembler received an unexpected owner"
        )
    if owner.model_strategy_roles or owner.requires_sandbox or owner.requires_workspace_manager:
        raise ProductionExecutionAssemblyError(
            "image generation owner must not require coding model or workspace authority"
        )
    try:
        request = ImageGenerationInvocationRequest.from_projection(
            binding.request_projection,
            binding.request_content_hash,
        )
        template = ImageWorkflowStore(runtime).get(
            request.workflow_id,
            request.workflow_hash,
        )
        profile = ComfyUiProfile(expected_version=template.backend_version)
    except Exception as exc:
        raise ProductionExecutionAssemblyError(
            "trusted ComfyUI workflow/profile dependencies are unavailable"
        ) from exc
    dependency_hash = content_hash(
        {
            "base_url": profile.base_url,
            "expected_version": profile.expected_version,
            "allow_remote": profile.allow_remote,
            "request_timeout_seconds": profile.request_timeout_seconds,
            "poll_interval_seconds": profile.poll_interval_seconds,
            "max_json_bytes": profile.max_json_bytes,
            "max_image_bytes": profile.max_image_bytes,
            "workflow_id": template.workflow_id,
            "workflow_hash": template.workflow_hash,
        }
    )
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(),
        model_profile_ids=(),
        runtime_ids=(),
        runtime_provider_fingerprints=(),
        sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=dependency_hash,
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=ImageGenerationExecutionPayload(
            request=request,
            profile=profile,
            template=template,
            profile_dependency_hash=dependency_hash,
        ),
    )


def _assemble_pixelorama_source_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _PIXELORAMA_SOURCE_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "Pixelorama source dependency assembler received an unexpected owner"
        )
    if owner.model_strategy_roles or owner.requires_sandbox or owner.requires_workspace_manager:
        raise ProductionExecutionAssemblyError(
            "Pixelorama source owner must not require model, sandbox, or Git workspace authority"
        )
    try:
        profile = load_infrastructure_pixelorama_bridge_profile(runtime.project_root)
    except ProductionPixeloramaProfileError as exc:
        raise ProductionExecutionAssemblyError(
            "trusted Pixelorama CLI profile is unavailable"
        ) from exc
    profile_hash = pixelorama_bridge_profile_dependency_hash(profile)
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(),
        model_profile_ids=(),
        runtime_ids=(),
        runtime_provider_fingerprints=(),
        sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=profile_hash,
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=PixeloramaSourceCreationExecutionPayload(
            profile=profile,
            profile_dependency_hash=profile_hash,
        ),
    )


def _assemble_piper_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _PIPER_OWNER_ID:
        raise ProductionExecutionAssemblyError("Piper dependency assembler received an unexpected owner")
    if owner.model_strategy_roles or owner.requires_sandbox or owner.requires_workspace_manager:
        raise ProductionExecutionAssemblyError("Piper owner must not require coding or workspace authority")
    try:
        request = PiperInvocationRequest.from_projection(
            binding.request_projection,
            binding.request_content_hash,
        )
        profile = AudioProfileStore(runtime).get(
            request.profile_id, "sha256:" + request.profile_hash
        )
        infrastructure = load_infrastructure_piper_profile()
    except Exception as exc:
        raise ProductionExecutionAssemblyError(
            "trusted Piper profile/infrastructure dependencies are unavailable"
        ) from exc
    dependency_hash = content_hash({
        "profile_hash": profile.profile_hash,
        "infrastructure_hash": infrastructure.dependency_hash,
    })
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(), model_profile_ids=(), runtime_ids=(),
        runtime_provider_fingerprints=(), sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=dependency_hash,
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=PiperExecutionPayload(request, profile, infrastructure),
    )


def _assemble_ffmpeg_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _FFMPEG_OWNER_ID:
        raise ProductionExecutionAssemblyError("FFmpeg dependency assembler received an unexpected owner")
    try:
        request = FfmpegInvocationRequest.from_projection(
            binding.request_projection, binding.request_content_hash
        )
        profile = AudioProfileStore(runtime).get(
            request.profile_id, "sha256:" + request.profile_hash
        )
        infrastructure = load_infrastructure_ffmpeg_profile(runtime, profile.runtime_hash)
    except Exception as exc:
        raise ProductionExecutionAssemblyError(
            "trusted FFmpeg profile/infrastructure dependencies are unavailable"
        ) from exc
    dependency_hash = content_hash({
        "profile_hash": profile.profile_hash,
        "infrastructure_hash": infrastructure.dependency_hash,
    })
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(), model_profile_ids=(), runtime_ids=(),
        runtime_provider_fingerprints=(), sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=dependency_hash,
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=FfmpegExecutionPayload(request, profile, infrastructure),
    )


def _assemble_runtime_observation_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _RUNTIME_OBSERVER_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "runtime observer assembler received an unexpected owner"
        )
    try:
        projection = binding.request_projection
        request = RuntimeObservationRequestStore(runtime).get(
            projection["request_id"], "sha256:" + projection["request_hash"]
        )
        infrastructure = load_runtime_observation_infrastructure()
    except Exception as exc:
        raise ProductionExecutionAssemblyError(
            "trusted runtime observation request/infrastructure is unavailable"
        ) from exc
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(),
        model_profile_ids=(),
        runtime_ids=(),
        runtime_provider_fingerprints=(),
        sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=content_hash(
            {
                "request_hash": request.content_hash,
                "infrastructure_hash": infrastructure.dependency_hash,
            }
        ),
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=RuntimeObservationExecutionPayload(request, infrastructure),
    )


def _assemble_playtest_dependencies(
    runtime: OriginForgeRuntime, claim, binding, owner, owner_registry
) -> ProductionExecutionDependencies:
    if owner.owner_id != _PLAYTEST_OWNER_ID:
        raise ProductionExecutionAssemblyError("playtest assembler received an unexpected owner")
    try:
        projection = binding.request_projection
        scenario = PlaytestScenarioStore(runtime).get(
            projection["scenario_id"], "sha256:" + projection["scenario_hash"]
        )
        infrastructure = load_cooperative_playtest_infrastructure()
    except Exception as exc:
        raise ProductionExecutionAssemblyError(
            "trusted playtest scenario/harness infrastructure is unavailable"
        ) from exc
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=0,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(), model_profile_ids=(), runtime_ids=(),
        runtime_provider_fingerprints=(), sandbox_backend=_NOT_REQUIRED_SANDBOX_BACKEND,
        sandbox_config_hash=_NOT_REQUIRED_SANDBOX_HASH,
        owner_dependency_hash=content_hash({"scenario_hash": scenario.content_hash, "infrastructure_hash": infrastructure.dependency_hash}),
    )
    return ProductionExecutionDependencies(plan, owner, CooperativePlaytestExecutionPayload(scenario, infrastructure))


def _assemble_build_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _BUILD_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "build dependency assembler received an unexpected owner"
        )
    config = load_config(runtime.project_root)
    if config.version < 2:
        raise ProductionExecutionAssemblyError(
            "build integration requires protected config version 2"
        )
    _require_executable_sandbox(config)
    if not any(command.required for command in config.approved_build_commands):
        raise ProductionExecutionAssemblyError(
            "build integration requires at least one approved build command"
        )
    try:
        backend = create_sandbox_backend(runtime, config)
    except Exception as exc:
        raise ProductionExecutionAssemblyError(
            "configured build sandbox backend is unavailable"
        ) from exc
    command_projection = [
        {
            "name": command.name,
            "argv": list(command.argv),
            "timeout_seconds": command.timeout_seconds,
            "max_output_bytes": command.max_output_bytes,
            "required": command.required,
        }
        for command in config.approved_build_commands
    ]
    plan = ProductionExecutionDependencyPlan(
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=config.version,
        resource_model_config_hash=_NOT_REQUIRED_RESOURCE_MODEL_HASH,
        model_runtime_config_fingerprint=_NOT_REQUIRED_MODEL_RUNTIME_HASH,
        model_strategy_roles=(),
        model_profile_ids=(),
        runtime_ids=(),
        runtime_provider_fingerprints=(),
        sandbox_backend=config.sandbox_backend.lower(),
        sandbox_config_hash=_sandbox_config_hash(config),
        owner_dependency_hash=content_hash({"build_commands": command_projection}),
    )
    return ProductionExecutionDependencies(
        plan=plan,
        owner=owner,
        payload=BuildIntegrationExecutionPayload(
            sandbox_backend=backend,
            workspaces=GitWorkspaceManager(runtime),
        ),
    )


def _assemble_bounded_retry_dependencies(
    runtime: OriginForgeRuntime,
    claim,
    binding,
    owner: ProductionExecutionOwnerDescriptor,
    owner_registry,
) -> ProductionExecutionDependencies:
    if owner.owner_id != _BOUNDED_RETRY_OWNER_ID:
        raise ProductionExecutionAssemblyError(
            "bounded execution dependency assembler received an unexpected owner"
        )

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
    provider_by_runtime: dict[str, ManagedModelRuntimeProviderConfig] = {}
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
        **_common_plan_fields(claim, binding, owner, owner_registry),
        config_version=config.version,
        resource_model_config_hash=_resource_model_config_hash(config),
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
        payload=BoundedRetryExecutionPayload(
            model_scheduling=scheduling,
            runtime_registry=runtime_registry,
            runtime_dispatch_loader=runtime_dispatch_loader,
            managed_loaders=managed_loaders,
            models=models,
            sandbox_backend=sandbox_backend,
            workspaces=workspaces,
            bounded_retry_policy=bounded_retry_policy,
        ),
    )


def assemble_production_execution_dependencies(
    runtime: OriginForgeRuntime,
    claim_id: str,
) -> ProductionExecutionDependencies:
    """Assemble one exact owner-specific dependency graph without invoking it."""

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

    if owner.owner_id == _BUILD_OWNER_ID:
        return _assemble_build_dependencies(
            runtime, claim, binding, owner, owner_registry
        )
    if owner.owner_id == _BLENDER_OWNER_ID:
        return _assemble_blender_dependencies(
            runtime,
            claim,
            binding,
            owner,
            owner_registry,
        )
    if owner.owner_id == IMAGE_EXECUTION_OWNER_ID:
        return _assemble_image_dependencies(
            runtime,
            claim,
            binding,
            owner,
            owner_registry,
        )
    if owner.owner_id == _PIPER_OWNER_ID:
        return _assemble_piper_dependencies(runtime, claim, binding, owner, owner_registry)
    if owner.owner_id == _FFMPEG_OWNER_ID:
        return _assemble_ffmpeg_dependencies(runtime, claim, binding, owner, owner_registry)
    if owner.owner_id == _RUNTIME_OBSERVER_OWNER_ID:
        return _assemble_runtime_observation_dependencies(
            runtime, claim, binding, owner, owner_registry
        )
    if owner.owner_id == _PLAYTEST_OWNER_ID:
        return _assemble_playtest_dependencies(runtime, claim, binding, owner, owner_registry)
    if owner.owner_id == _PIXELORAMA_OWNER_ID:
        return _assemble_pixelorama_dependencies(
            runtime,
            claim,
            binding,
            owner,
            owner_registry,
        )
    if owner.owner_id == _PIXELORAMA_SOURCE_OWNER_ID:
        return _assemble_pixelorama_source_dependencies(
            runtime, claim, binding, owner, owner_registry
        )
    if owner.owner_id == _SIMULATION_OWNER_ID:
        return _assemble_simulation_dependencies(
            claim,
            binding,
            owner,
            owner_registry,
        )
    if owner.owner_id == _BOUNDED_RETRY_OWNER_ID:
        return _assemble_bounded_retry_dependencies(
            runtime,
            claim,
            binding,
            owner,
            owner_registry,
        )
    raise ProductionExecutionAssemblyError(
        "trusted execution owner has no dependency assembler"
    )
