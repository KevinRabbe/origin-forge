from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Sequence

from .model_scheduler import ManagedModelLoader, ModelResourceProfile
from .resource_scheduler import ResourceLease


_RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ModelRuntimeRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelRuntimeBinding:
    runtime_id: str
    loader: ManagedModelLoader

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_id, str) or not _RUNTIME_ID_RE.fullmatch(
            self.runtime_id
        ):
            raise ValueError(f"invalid model runtime_id: {self.runtime_id!r}")


class ModelRuntimeRegistry:
    """Trusted runtime-loader inventory, separate from model selection policy."""

    def __init__(self, bindings: Sequence[ModelRuntimeBinding]):
        values = tuple(bindings)
        if any(not isinstance(binding, ModelRuntimeBinding) for binding in values):
            raise TypeError("runtime registry requires ModelRuntimeBinding values")
        ids = [binding.runtime_id for binding in values]
        if len(ids) != len(set(ids)):
            raise ModelRuntimeRegistryError(
                "model runtime registry contains duplicate runtime IDs"
            )
        self._bindings = values
        self._by_id = {binding.runtime_id: binding.loader for binding in values}

    def loader(self, runtime_id: str) -> ManagedModelLoader:
        try:
            return self._by_id[runtime_id]
        except KeyError as exc:
            raise ModelRuntimeRegistryError(
                f"unknown configured model runtime: {runtime_id}"
            ) from exc

    def runtime_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def dispatch_loader(self) -> "RuntimeDispatchLoader":
        return RuntimeDispatchLoader(self)


class RuntimeDispatchLoader:
    """Route load/unload to the runtime declared by the selected profile.

    The dispatcher tracks active instance identity only for the lifetime of a
    model session. It adds no durable state and grants no runtime not already
    present in the trusted registry.
    """

    def __init__(self, registry: ModelRuntimeRegistry):
        if not isinstance(registry, ModelRuntimeRegistry):
            raise TypeError("registry must be a ModelRuntimeRegistry")
        self.registry = registry
        self._active: dict[int, tuple[object, ManagedModelLoader, str]] = {}
        self._lock = threading.RLock()

    def load(self, profile: ModelResourceProfile, lease: ResourceLease) -> object:
        loader = self.registry.loader(profile.runtime_id)
        instance = loader.load(profile, lease)
        if instance is None:
            raise ModelRuntimeRegistryError(
                f"model runtime {profile.runtime_id} returned no instance"
            )
        identity = id(instance)
        with self._lock:
            existing = self._active.get(identity)
            if existing is not None and existing[0] is instance:
                raise ModelRuntimeRegistryError(
                    f"model runtime {profile.runtime_id} reused an already-active instance"
                )
            self._active[identity] = (instance, loader, profile.runtime_id)
        return instance

    def unload(self, instance: object) -> None:
        identity = id(instance)
        with self._lock:
            active = self._active.get(identity)
            if active is None or active[0] is not instance:
                raise ModelRuntimeRegistryError(
                    "model instance is not owned by this runtime dispatcher"
                )
            _, loader, _ = self._active.pop(identity)
        loader.unload(instance)

    def active_runtime_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(value[2] for value in self._active.values()))
