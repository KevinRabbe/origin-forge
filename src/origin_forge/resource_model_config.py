from __future__ import annotations

from dataclasses import dataclass

from .model_scheduler import (
    ModelProfileError,
    ModelProfileRegistry,
    ModelResourceProfile,
    ModelRole,
    ModelSelectionPolicy,
)
from .resource_scheduler import (
    GpuCapacity,
    GpuResourceRequest,
    ResourceCapacity,
    ResourceRequest,
)


MAX_CONFIGURED_GPUS = 32
MAX_MODEL_PROFILES = 128
MAX_MODEL_POLICIES = len(ModelRole)
MAX_CPU_SLOTS = 4096
MAX_RAM_MIB = 16 * 1024 * 1024
MAX_VRAM_MIB = 1024 * 1024
MAX_ACTIVE_LEASES = 4096


@dataclass(frozen=True)
class ResourceModelConfig:
    enabled: bool
    capacity: ResourceCapacity | None
    profiles: tuple[ModelResourceProfile, ...]
    policies: tuple[ModelSelectionPolicy, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("resource model config enabled must be boolean")
        if self.enabled != (self.capacity is not None):
            raise ValueError("enabled resource model config requires exactly one capacity")

    @classmethod
    def disabled(cls) -> "ResourceModelConfig":
        return cls(False, None, (), ())

    def registry(self) -> ModelProfileRegistry:
        return ModelProfileRegistry(self.profiles)

    def policy(self, role: ModelRole) -> ModelSelectionPolicy:
        for policy in self.policies:
            if policy.role == role:
                return policy
        raise KeyError(f"no configured model policy for role: {role.value}")


def _table(raw: object, label: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a TOML table")
    return raw


def _array_of_tables(raw: object, label: str, *, maximum: int) -> tuple[dict, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError(f"{label} must be an array of tables")
    if len(raw) > maximum:
        raise ValueError(f"{label} exceeds count limit ({len(raw)} > {maximum})")
    return tuple(raw)


def _int(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if len(value) > 256:
        raise ValueError(f"{label} exceeds 256 characters")
    return value.strip()


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _resource_request(raw: object, label: str) -> ResourceRequest:
    item = _table(raw, label)
    allowed = {"cpu_slots", "ram_mib", "gpu"}
    unknown = set(item) - allowed
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")

    cpu_slots = _int(
        item.get("cpu_slots", 0),
        f"{label}.cpu_slots",
        maximum=MAX_CPU_SLOTS,
    )
    ram_mib = _int(
        item.get("ram_mib", 0),
        f"{label}.ram_mib",
        maximum=MAX_RAM_MIB,
    )

    gpu_raw = item.get("gpu")
    gpu = None
    if gpu_raw is not None:
        gpu_item = _table(gpu_raw, f"{label}.gpu")
        gpu_allowed = {"vram_mib", "compute_slots", "device_id", "exclusive"}
        gpu_unknown = set(gpu_item) - gpu_allowed
        if gpu_unknown:
            raise ValueError(
                f"{label}.gpu has unknown fields: {sorted(gpu_unknown)}"
            )
        vram_mib = _int(
            gpu_item.get("vram_mib", 0),
            f"{label}.gpu.vram_mib",
            maximum=MAX_VRAM_MIB,
        )
        compute_slots = _int(
            gpu_item.get("compute_slots", 1),
            f"{label}.gpu.compute_slots",
            maximum=MAX_CPU_SLOTS,
        )
        device_id_raw = gpu_item.get("device_id")
        device_id = (
            None
            if device_id_raw is None
            else _string(device_id_raw, f"{label}.gpu.device_id")
        )
        exclusive = _bool(
            gpu_item.get("exclusive", False),
            f"{label}.gpu.exclusive",
        )
        gpu = GpuResourceRequest(
            vram_mib=vram_mib,
            compute_slots=compute_slots,
            device_id=device_id,
            exclusive=exclusive,
        )

    try:
        return ResourceRequest(cpu_slots=cpu_slots, ram_mib=ram_mib, gpu=gpu)
    except ValueError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc


def _capacity(resources: dict) -> ResourceCapacity:
    allowed = {"enabled", "cpu_slots", "ram_mib", "max_active_leases", "gpus"}
    unknown = set(resources) - allowed
    if unknown:
        raise ValueError(f"resources has unknown fields: {sorted(unknown)}")

    cpu_slots = _int(
        resources.get("cpu_slots"),
        "resources.cpu_slots",
        minimum=1,
        maximum=MAX_CPU_SLOTS,
    )
    ram_mib = _int(
        resources.get("ram_mib"),
        "resources.ram_mib",
        minimum=1,
        maximum=MAX_RAM_MIB,
    )
    max_active_leases = _int(
        resources.get("max_active_leases", 64),
        "resources.max_active_leases",
        minimum=1,
        maximum=MAX_ACTIVE_LEASES,
    )

    gpu_items = _array_of_tables(
        resources.get("gpus"),
        "resources.gpus",
        maximum=MAX_CONFIGURED_GPUS,
    )
    gpus = []
    for index, item in enumerate(gpu_items):
        label = f"resources.gpus[{index}]"
        allowed_gpu = {"device_id", "vram_mib", "reserve_vram_mib", "compute_slots"}
        unknown_gpu = set(item) - allowed_gpu
        if unknown_gpu:
            raise ValueError(f"{label} has unknown fields: {sorted(unknown_gpu)}")
        try:
            gpus.append(
                GpuCapacity(
                    device_id=_string(item.get("device_id"), f"{label}.device_id"),
                    vram_mib=_int(
                        item.get("vram_mib"),
                        f"{label}.vram_mib",
                        minimum=1,
                        maximum=MAX_VRAM_MIB,
                    ),
                    reserve_vram_mib=_int(
                        item.get("reserve_vram_mib", 0),
                        f"{label}.reserve_vram_mib",
                        maximum=MAX_VRAM_MIB,
                    ),
                    compute_slots=_int(
                        item.get("compute_slots", 1),
                        f"{label}.compute_slots",
                        minimum=1,
                        maximum=MAX_CPU_SLOTS,
                    ),
                )
            )
        except ValueError as exc:
            raise ValueError(f"invalid {label}: {exc}") from exc

    try:
        return ResourceCapacity(
            cpu_slots=cpu_slots,
            ram_mib=ram_mib,
            gpus=tuple(gpus),
            max_active_leases=max_active_leases,
        )
    except ValueError as exc:
        raise ValueError(f"invalid resources capacity: {exc}") from exc


def _profiles(models: dict) -> tuple[ModelResourceProfile, ...]:
    items = _array_of_tables(
        models.get("profiles"),
        "models.profiles",
        maximum=MAX_MODEL_PROFILES,
    )
    result = []
    for index, item in enumerate(items):
        label = f"models.profiles[{index}]"
        allowed = {"profile_id", "role", "model_id", "model_hash", "runtime_id", "resources"}
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")
        role_raw = _string(item.get("role"), f"{label}.role")
        try:
            role = ModelRole(role_raw)
        except ValueError as exc:
            raise ValueError(f"{label}.role is unsupported: {role_raw}") from exc
        model_hash_raw = item.get("model_hash")
        model_hash = (
            None
            if model_hash_raw is None
            else _string(model_hash_raw, f"{label}.model_hash")
        )
        try:
            result.append(
                ModelResourceProfile(
                    profile_id=_string(item.get("profile_id"), f"{label}.profile_id"),
                    role=role,
                    model_id=_string(item.get("model_id"), f"{label}.model_id"),
                    runtime_id=_string(item.get("runtime_id"), f"{label}.runtime_id"),
                    resources=_resource_request(item.get("resources"), f"{label}.resources"),
                    model_hash=model_hash,
                )
            )
        except ValueError as exc:
            raise ValueError(f"invalid {label}: {exc}") from exc
    try:
        ModelProfileRegistry(tuple(result))
    except ModelProfileError as exc:
        raise ValueError(f"invalid models.profiles: {exc}") from exc
    return tuple(result)


def _policies(
    models: dict,
    profiles: tuple[ModelResourceProfile, ...],
) -> tuple[ModelSelectionPolicy, ...]:
    items = _array_of_tables(
        models.get("policies"),
        "models.policies",
        maximum=MAX_MODEL_POLICIES,
    )
    registry = ModelProfileRegistry(profiles)
    result = []
    seen_roles = set()
    for index, item in enumerate(items):
        label = f"models.policies[{index}]"
        allowed = {"role", "primary_profile_id", "fallback_profile_ids"}
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")
        role_raw = _string(item.get("role"), f"{label}.role")
        try:
            role = ModelRole(role_raw)
        except ValueError as exc:
            raise ValueError(f"{label}.role is unsupported: {role_raw}") from exc
        if role in seen_roles:
            raise ValueError(f"duplicate model policy role: {role.value}")
        seen_roles.add(role)
        primary = _string(
            item.get("primary_profile_id"),
            f"{label}.primary_profile_id",
        )
        fallback_raw = item.get("fallback_profile_ids", [])
        if not isinstance(fallback_raw, list) or any(
            not isinstance(value, str) or not value.strip() for value in fallback_raw
        ):
            raise ValueError(
                f"{label}.fallback_profile_ids must be an array of non-empty strings"
            )
        if len(fallback_raw) > MAX_MODEL_PROFILES:
            raise ValueError(f"{label}.fallback_profile_ids exceeds count limit")
        fallback = tuple(value.strip() for value in fallback_raw)
        try:
            policy = ModelSelectionPolicy(role, primary, fallback)
            referenced = tuple(
                registry.profile(profile_id)
                for profile_id in policy.ordered_profile_ids
            )
        except (ValueError, ModelProfileError) as exc:
            raise ValueError(f"invalid {label}: {exc}") from exc
        mismatched = [profile.profile_id for profile in referenced if profile.role != role]
        if mismatched:
            raise ValueError(
                f"{label} role {role.value} does not match profiles: {', '.join(mismatched)}"
            )
        result.append(policy)
    return tuple(sorted(result, key=lambda policy: policy.role.value))


def parse_resource_model_config(
    resources_raw: object,
    models_raw: object,
) -> ResourceModelConfig:
    """Parse protected Phase-14 sections without modifying project configuration."""

    resources = _table(resources_raw, "resources")
    models = _table(models_raw, "models")
    allowed_models = {"profiles", "policies"}
    unknown_models = set(models) - allowed_models
    if unknown_models:
        raise ValueError(f"models has unknown fields: {sorted(unknown_models)}")

    enabled = resources.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("resources.enabled must be boolean")

    if not enabled:
        extra_resources = set(resources) - {"enabled", "gpus"}
        if extra_resources:
            raise ValueError(
                "disabled resources may not declare active capacity fields: "
                + ", ".join(sorted(extra_resources))
            )
        if resources.get("gpus") not in (None, []):
            raise ValueError("disabled resources may not configure GPUs")
        if models.get("profiles") not in (None, []) or models.get("policies") not in (None, []):
            raise ValueError("model profiles/policies require resources.enabled = true")
        return ResourceModelConfig.disabled()

    capacity = _capacity(resources)
    profiles = _profiles(models)
    policies = _policies(models, profiles)
    return ResourceModelConfig(True, capacity, profiles, policies)
