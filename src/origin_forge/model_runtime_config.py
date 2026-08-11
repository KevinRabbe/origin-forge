from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum

from .resource_model_config import ResourceModelConfig


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_PATH_CHARS = 4096
_MAX_PROVIDERS = 128
_MAX_BINDINGS_PER_PROVIDER = 128
_MIN_PORT = 1
_MAX_PORT = 65535
_MAX_TIMEOUT_SECONDS = 3600.0


class ModelRuntimeProviderKind(StrEnum):
    LLAMACPP_MANAGED_CPU_V1 = "originforge.llamacpp-managed-cpu@1"


class ModelRuntimeConfigError(ValueError):
    pass


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ModelRuntimeConfigError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ModelRuntimeConfigError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _local_path(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > _MAX_PATH_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or "://" in value
    ):
        raise ModelRuntimeConfigError(f"{label} must be a bounded local path")
    return value


def _positive_timeout(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ModelRuntimeConfigError(f"{label} must be a positive number")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelRuntimeConfigError(f"{label} must be a positive number") from exc
    if (
        not math.isfinite(normalized)
        or normalized <= 0
        or normalized > _MAX_TIMEOUT_SECONDS
    ):
        raise ModelRuntimeConfigError(
            f"{label} must be > 0 and <= {_MAX_TIMEOUT_SECONDS}"
        )
    return normalized


def _port(value: object, label: str) -> int:
    if type(value) is not int or not _MIN_PORT <= value <= _MAX_PORT:
        raise ModelRuntimeConfigError(
            f"{label} must be an integer from {_MIN_PORT} to {_MAX_PORT}"
        )
    return value


def _table(value: object, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelRuntimeConfigError(f"{label} must be a TOML table")
    return value


def _tables(
    value: object,
    label: str,
    *,
    maximum: int,
) -> tuple[dict, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ModelRuntimeConfigError(f"{label} must be an array of tables")
    if len(value) > maximum:
        raise ModelRuntimeConfigError(
            f"{label} exceeds count limit ({len(value)} > {maximum})"
        )
    return tuple(value)


@dataclass(frozen=True)
class ManagedModelProfileBinding:
    profile_id: str
    model_path: str
    model_sha256: str

    def __post_init__(self) -> None:
        _identity(self.profile_id, "profile_id")
        _local_path(self.model_path, "model_path")
        _digest(self.model_sha256, "model_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "model_path": self.model_path,
            "model_sha256": self.model_sha256,
        }


@dataclass(frozen=True)
class ManagedModelRuntimeProviderConfig:
    runtime_id: str
    provider_kind: ModelRuntimeProviderKind
    provider_contract_version: str
    executable_path: str
    executable_sha256: str
    port: int
    startup_timeout_seconds: float
    request_timeout_seconds: float
    shutdown_timeout_seconds: float
    profile_bindings: tuple[ManagedModelProfileBinding, ...]

    def __post_init__(self) -> None:
        _identity(self.runtime_id, "runtime_id")
        if not isinstance(self.provider_kind, ModelRuntimeProviderKind):
            raise ModelRuntimeConfigError(
                "provider_kind must be a ModelRuntimeProviderKind"
            )
        if self.provider_contract_version != "1":
            raise ModelRuntimeConfigError(
                "provider_contract_version must be exactly '1'"
            )
        _local_path(self.executable_path, "executable_path")
        _digest(self.executable_sha256, "executable_sha256")
        _port(self.port, "port")
        _positive_timeout(self.startup_timeout_seconds, "startup_timeout_seconds")
        _positive_timeout(self.request_timeout_seconds, "request_timeout_seconds")
        _positive_timeout(self.shutdown_timeout_seconds, "shutdown_timeout_seconds")
        bindings = tuple(self.profile_bindings)
        if not bindings or any(
            not isinstance(value, ManagedModelProfileBinding) for value in bindings
        ):
            raise ModelRuntimeConfigError(
                "profile_bindings must contain at least one binding"
            )
        if len(bindings) > _MAX_BINDINGS_PER_PROVIDER:
            raise ModelRuntimeConfigError("profile_bindings exceeds count limit")
        profile_ids = [value.profile_id for value in bindings]
        if len(profile_ids) != len(set(profile_ids)):
            raise ModelRuntimeConfigError(
                "profile_bindings contains duplicate profile IDs"
            )
        object.__setattr__(
            self,
            "profile_bindings",
            tuple(sorted(bindings, key=lambda value: value.profile_id)),
        )

    def binding(self, profile_id: str) -> ManagedModelProfileBinding:
        for binding in self.profile_bindings:
            if binding.profile_id == profile_id:
                return binding
        raise KeyError(profile_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "provider_kind": self.provider_kind.value,
            "provider_contract_version": self.provider_contract_version,
            "executable_path": self.executable_path,
            "executable_sha256": self.executable_sha256,
            "loopback_host": "127.0.0.1",
            "port": self.port,
            "startup_timeout_seconds": self.startup_timeout_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "shutdown_timeout_seconds": self.shutdown_timeout_seconds,
            "profile_bindings": [value.to_dict() for value in self.profile_bindings],
        }

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(self.to_dict())


@dataclass(frozen=True)
class ModelRuntimeConfig:
    providers: tuple[ManagedModelRuntimeProviderConfig, ...]

    def __post_init__(self) -> None:
        values = tuple(self.providers)
        if len(values) > _MAX_PROVIDERS or any(
            not isinstance(value, ManagedModelRuntimeProviderConfig)
            for value in values
        ):
            raise ModelRuntimeConfigError("providers are invalid or exceed count limit")
        runtime_ids = [value.runtime_id for value in values]
        if len(runtime_ids) != len(set(runtime_ids)):
            raise ModelRuntimeConfigError("duplicate model runtime provider runtime_id")
        profile_ids = [
            binding.profile_id
            for provider in values
            for binding in provider.profile_bindings
        ]
        if len(profile_ids) != len(set(profile_ids)):
            raise ModelRuntimeConfigError(
                "a model profile may be bound by only one runtime provider"
            )
        object.__setattr__(
            self,
            "providers",
            tuple(sorted(values, key=lambda value: value.runtime_id)),
        )

    @classmethod
    def empty(cls) -> "ModelRuntimeConfig":
        return cls(())

    def provider(self, runtime_id: str) -> ManagedModelRuntimeProviderConfig:
        for provider in self.providers:
            if provider.runtime_id == runtime_id:
                return provider
        raise KeyError(runtime_id)

    def provider_for_profile(
        self,
        profile_id: str,
    ) -> ManagedModelRuntimeProviderConfig:
        for provider in self.providers:
            if any(
                binding.profile_id == profile_id
                for binding in provider.profile_bindings
            ):
                return provider
        raise KeyError(profile_id)

    def to_dict(self) -> dict[str, object]:
        return {"providers": [value.to_dict() for value in self.providers]}

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(self.to_dict())


def parse_model_runtime_config(
    raw: object,
    resource_models: ResourceModelConfig,
) -> ModelRuntimeConfig:
    """Parse declarative protected runtime bindings without touching the filesystem."""

    if not isinstance(resource_models, ResourceModelConfig):
        raise TypeError("resource_models must be a ResourceModelConfig")
    table = _table(raw, "model_runtimes")
    unknown = set(table) - {"providers"}
    if unknown:
        raise ModelRuntimeConfigError(
            f"model_runtimes has unknown fields: {sorted(unknown)}"
        )
    items = _tables(
        table.get("providers"),
        "model_runtimes.providers",
        maximum=_MAX_PROVIDERS,
    )
    if not items:
        return ModelRuntimeConfig.empty()

    registry = resource_models.registry()
    result: list[ManagedModelRuntimeProviderConfig] = []
    for index, item in enumerate(items):
        label = f"model_runtimes.providers[{index}]"
        allowed = {
            "runtime_id",
            "provider_kind",
            "provider_contract_version",
            "executable_path",
            "executable_sha256",
            "port",
            "startup_timeout_seconds",
            "request_timeout_seconds",
            "shutdown_timeout_seconds",
            "profile_bindings",
        }
        unknown_fields = set(item) - allowed
        if unknown_fields:
            raise ModelRuntimeConfigError(
                f"{label} has unknown fields: {sorted(unknown_fields)}"
            )
        runtime_id = _identity(item.get("runtime_id"), f"{label}.runtime_id")
        kind_raw = item.get("provider_kind")
        try:
            provider_kind = ModelRuntimeProviderKind(kind_raw)
        except (TypeError, ValueError) as exc:
            raise ModelRuntimeConfigError(
                f"{label}.provider_kind is unsupported: {kind_raw!r}"
            ) from exc
        bindings_raw = _tables(
            item.get("profile_bindings"),
            f"{label}.profile_bindings",
            maximum=_MAX_BINDINGS_PER_PROVIDER,
        )
        bindings: list[ManagedModelProfileBinding] = []
        for binding_index, binding_item in enumerate(bindings_raw):
            binding_label = f"{label}.profile_bindings[{binding_index}]"
            binding_unknown = set(binding_item) - {
                "profile_id",
                "model_path",
                "model_sha256",
            }
            if binding_unknown:
                raise ModelRuntimeConfigError(
                    f"{binding_label} has unknown fields: {sorted(binding_unknown)}"
                )
            binding = ManagedModelProfileBinding(
                profile_id=_identity(
                    binding_item.get("profile_id"),
                    f"{binding_label}.profile_id",
                ),
                model_path=_local_path(
                    binding_item.get("model_path"),
                    f"{binding_label}.model_path",
                ),
                model_sha256=_digest(
                    binding_item.get("model_sha256"),
                    f"{binding_label}.model_sha256",
                ),
            )
            try:
                profile = registry.profile(binding.profile_id)
            except Exception as exc:
                raise ModelRuntimeConfigError(
                    f"{binding_label}.profile_id references unknown model profile"
                ) from exc
            if profile.runtime_id != runtime_id:
                raise ModelRuntimeConfigError(
                    f"{binding_label} runtime_id does not match model profile"
                )
            if profile.model_hash != binding.model_sha256:
                raise ModelRuntimeConfigError(
                    f"{binding_label} model_sha256 does not match model profile model_hash"
                )
            if provider_kind is ModelRuntimeProviderKind.LLAMACPP_MANAGED_CPU_V1:
                if profile.resources.gpu is not None:
                    raise ModelRuntimeConfigError(
                        f"{binding_label} CPU provider cannot bind a GPU model profile"
                    )
            bindings.append(binding)

        result.append(
            ManagedModelRuntimeProviderConfig(
                runtime_id=runtime_id,
                provider_kind=provider_kind,
                provider_contract_version=_identity(
                    item.get("provider_contract_version"),
                    f"{label}.provider_contract_version",
                ),
                executable_path=_local_path(
                    item.get("executable_path"),
                    f"{label}.executable_path",
                ),
                executable_sha256=_digest(
                    item.get("executable_sha256"),
                    f"{label}.executable_sha256",
                ),
                port=_port(item.get("port"), f"{label}.port"),
                startup_timeout_seconds=_positive_timeout(
                    item.get("startup_timeout_seconds"),
                    f"{label}.startup_timeout_seconds",
                ),
                request_timeout_seconds=_positive_timeout(
                    item.get("request_timeout_seconds"),
                    f"{label}.request_timeout_seconds",
                ),
                shutdown_timeout_seconds=_positive_timeout(
                    item.get("shutdown_timeout_seconds"),
                    f"{label}.shutdown_timeout_seconds",
                ),
                profile_bindings=tuple(bindings),
            )
        )

    return ModelRuntimeConfig(tuple(result))
