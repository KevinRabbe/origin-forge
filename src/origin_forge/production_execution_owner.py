from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from collections.abc import Sequence

from .model_scheduler import ModelRole
from .production_capability_builtin import builtin_trusted_production_adapters
from .production_dispatch_binding import CodeBoundedRetryInputBinder
from .production_dispatch_binding_blender import BlenderExportGLBInputBinder
from .production_dispatch_binding_simulation import DeterministicSimulationInputBinder
from .production_dispatch_binding_pixelorama import PixeloramaSpritesheetExportInputBinder


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")


class ProductionExecutionOwnerError(RuntimeError):
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
        raise ProductionExecutionOwnerError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ProductionExecutionOwnerError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


@dataclass(frozen=True)
class ProductionExecutionOwnerDescriptor:
    owner_id: str
    owner_version: str
    adapter_id: str
    adapter_fingerprint: str
    dispatch_contract_id: str
    binder_id: str
    binder_fingerprint: str
    request_type_id: str
    request_schema_hash: str
    model_strategy_roles: tuple[ModelRole, ...]
    requires_sandbox: bool
    requires_workspace_manager: bool

    def __post_init__(self) -> None:
        _identity(self.owner_id, "owner_id")
        _identity(self.owner_version, "owner_version")
        _identity(self.adapter_id, "adapter_id")
        _digest(self.adapter_fingerprint, "adapter_fingerprint")
        _identity(self.dispatch_contract_id, "dispatch_contract_id")
        _identity(self.binder_id, "binder_id")
        _digest(self.binder_fingerprint, "binder_fingerprint")
        _identity(self.request_type_id, "request_type_id")
        _digest(self.request_schema_hash, "request_schema_hash")
        roles = tuple(self.model_strategy_roles)
        if any(not isinstance(role, ModelRole) for role in roles):
            raise ProductionExecutionOwnerError(
                "model_strategy_roles must contain ModelRole values"
            )
        if len(roles) != len(set(roles)):
            raise ProductionExecutionOwnerError(
                "model_strategy_roles may not contain duplicates"
            )
        object.__setattr__(self, "model_strategy_roles", roles)
        if type(self.requires_sandbox) is not bool:
            raise ProductionExecutionOwnerError("requires_sandbox must be boolean")
        if type(self.requires_workspace_manager) is not bool:
            raise ProductionExecutionOwnerError(
                "requires_workspace_manager must be boolean"
            )

    def authority_dict(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "owner_version": self.owner_version,
            "adapter_id": self.adapter_id,
            "adapter_fingerprint": self.adapter_fingerprint,
            "dispatch_contract_id": self.dispatch_contract_id,
            "binder_id": self.binder_id,
            "binder_fingerprint": self.binder_fingerprint,
            "request_type_id": self.request_type_id,
            "request_schema_hash": self.request_schema_hash,
            "model_strategy_roles": [role.value for role in self.model_strategy_roles],
            "requires_sandbox": self.requires_sandbox,
            "requires_workspace_manager": self.requires_workspace_manager,
        }

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(self.authority_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.authority_dict(),
            "owner_fingerprint": self.fingerprint,
        }


class ProductionExecutionOwnerRegistry:
    def __init__(self, descriptors: Sequence[ProductionExecutionOwnerDescriptor]):
        values = tuple(descriptors)
        if not values or any(
            not isinstance(value, ProductionExecutionOwnerDescriptor)
            for value in values
        ):
            raise ProductionExecutionOwnerError(
                "execution owner registry requires non-empty descriptor values"
            )
        owner_ids = [value.owner_id for value in values]
        if len(owner_ids) != len(set(owner_ids)):
            raise ProductionExecutionOwnerError(
                "execution owner registry contains duplicate owner IDs"
            )
        relations = [
            (
                value.adapter_id,
                value.dispatch_contract_id,
                value.binder_id,
                value.request_type_id,
            )
            for value in values
        ]
        if len(relations) != len(set(relations)):
            raise ProductionExecutionOwnerError(
                "execution owner registry contains ambiguous execution relations"
            )
        self._descriptors = tuple(sorted(values, key=lambda value: value.owner_id))
        self._fingerprint = _canonical_hash(
            {"owners": [value.to_dict() for value in self._descriptors]}
        )

    @property
    def descriptors(self) -> tuple[ProductionExecutionOwnerDescriptor, ...]:
        return self._descriptors

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def owner_for(
        self,
        *,
        adapter_id: str,
        adapter_fingerprint: str,
        dispatch_contract_id: str,
        binder_id: str,
        binder_fingerprint: str,
        request_type_id: str,
        request_schema_hash: str,
    ) -> ProductionExecutionOwnerDescriptor:
        query = (
            _identity(adapter_id, "adapter_id"),
            _digest(adapter_fingerprint, "adapter_fingerprint"),
            _identity(dispatch_contract_id, "dispatch_contract_id"),
            _identity(binder_id, "binder_id"),
            _digest(binder_fingerprint, "binder_fingerprint"),
            _identity(request_type_id, "request_type_id"),
            _digest(request_schema_hash, "request_schema_hash"),
        )
        matches = [
            value
            for value in self._descriptors
            if (
                value.adapter_id,
                value.adapter_fingerprint,
                value.dispatch_contract_id,
                value.binder_id,
                value.binder_fingerprint,
                value.request_type_id,
                value.request_schema_hash,
            )
            == query
        ]
        if not matches:
            raise ProductionExecutionOwnerError(
                "no trusted execution owner matches the exact dispatch relation"
            )
        if len(matches) != 1:
            raise ProductionExecutionOwnerError(
                "trusted execution owner selection is ambiguous"
            )
        return matches[0]


def builtin_execution_owner_descriptors() -> tuple[ProductionExecutionOwnerDescriptor, ...]:
    adapters = {
        value.adapter_id: value for value in builtin_trusted_production_adapters()
    }
    from .production_execution_owner_image import (
        image_generation_execution_owner_descriptor,
    )
    try:
        adapter = adapters["originforge.code.bounded-retry"]
    except KeyError as exc:
        raise ProductionExecutionOwnerError(
            "built-in capability inventory lacks bounded-retry adapter"
        ) from exc
    binder = CodeBoundedRetryInputBinder().descriptor
    if (
        binder.adapter_id != adapter.adapter_id
        or binder.dispatch_contract_id != "code.bounded-retry@1"
    ):
        raise ProductionExecutionOwnerError(
            "built-in bounded-retry binder relation drifted"
        )
    code_owner = ProductionExecutionOwnerDescriptor(
        owner_id="originforge.execution.bounded-retry@1",
        owner_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        dispatch_contract_id=binder.dispatch_contract_id,
        binder_id=binder.binder_id,
        binder_fingerprint=binder.binder_fingerprint,
        request_type_id=binder.request_type_id,
        request_schema_hash=binder.request_schema_hash,
        model_strategy_roles=(ModelRole.CODER_STRONG,),
        requires_sandbox=True,
        requires_workspace_manager=True,
    )

    try:
        simulation_adapter = adapters["originforge.simulation.deterministic"]
    except KeyError as exc:
        raise ProductionExecutionOwnerError(
            "built-in capability inventory lacks deterministic simulation adapter"
        ) from exc
    simulation_binder = DeterministicSimulationInputBinder().descriptor
    if (
        simulation_binder.adapter_id != simulation_adapter.adapter_id
        or simulation_binder.dispatch_contract_id != "simulation.deterministic@1"
    ):
        raise ProductionExecutionOwnerError(
            "built-in deterministic simulation binder relation drifted"
        )
    simulation_owner = ProductionExecutionOwnerDescriptor(
        owner_id="originforge.execution.simulation.deterministic@1",
        owner_version="1",
        adapter_id=simulation_adapter.adapter_id,
        adapter_fingerprint=simulation_adapter.implementation_fingerprint,
        dispatch_contract_id=simulation_binder.dispatch_contract_id,
        binder_id=simulation_binder.binder_id,
        binder_fingerprint=simulation_binder.binder_fingerprint,
        request_type_id=simulation_binder.request_type_id,
        request_schema_hash=simulation_binder.request_schema_hash,
        model_strategy_roles=(),
        requires_sandbox=False,
        requires_workspace_manager=False,
    )
    try:
        pixelorama_adapter = adapters["originforge.pixelorama.export"]
    except KeyError as exc:
        raise ProductionExecutionOwnerError(
            "built-in capability inventory lacks Pixelorama export adapter"
        ) from exc
    pixelorama_binder = PixeloramaSpritesheetExportInputBinder().descriptor
    if (
        pixelorama_binder.adapter_id != pixelorama_adapter.adapter_id
        or pixelorama_binder.dispatch_contract_id != "pixelorama.spritesheet-export@1"
    ):
        raise ProductionExecutionOwnerError(
            "built-in Pixelorama export binder relation drifted"
        )
    pixelorama_owner = ProductionExecutionOwnerDescriptor(
        owner_id="originforge.execution.pixelorama.spritesheet-export@1",
        owner_version="1",
        adapter_id=pixelorama_adapter.adapter_id,
        adapter_fingerprint=pixelorama_adapter.implementation_fingerprint,
        dispatch_contract_id=pixelorama_binder.dispatch_contract_id,
        binder_id=pixelorama_binder.binder_id,
        binder_fingerprint=pixelorama_binder.binder_fingerprint,
        request_type_id=pixelorama_binder.request_type_id,
        request_schema_hash=pixelorama_binder.request_schema_hash,
        model_strategy_roles=(),
        requires_sandbox=False,
        requires_workspace_manager=False,
    )
    try:
        blender_adapter = adapters["originforge.blender.model3d"]
    except KeyError as exc:
        raise ProductionExecutionOwnerError(
            "built-in capability inventory lacks Blender model3d adapter"
        ) from exc
    blender_binder = BlenderExportGLBInputBinder().descriptor
    if (
        blender_binder.adapter_id != blender_adapter.adapter_id
        or blender_binder.dispatch_contract_id != "blender.export-glb@1"
    ):
        raise ProductionExecutionOwnerError(
            "built-in Blender export-glb binder relation drifted"
        )
    blender_owner = ProductionExecutionOwnerDescriptor(
        owner_id="originforge.execution.blender.export-glb@1",
        owner_version="1",
        adapter_id=blender_adapter.adapter_id,
        adapter_fingerprint=blender_adapter.implementation_fingerprint,
        dispatch_contract_id=blender_binder.dispatch_contract_id,
        binder_id=blender_binder.binder_id,
        binder_fingerprint=blender_binder.binder_fingerprint,
        request_type_id=blender_binder.request_type_id,
        request_schema_hash=blender_binder.request_schema_hash,
        model_strategy_roles=(),
        requires_sandbox=False,
        requires_workspace_manager=False,
    )
    return (
        code_owner,
        simulation_owner,
        pixelorama_owner,
        blender_owner,
        image_generation_execution_owner_descriptor(),
    )


def build_builtin_execution_owner_registry() -> ProductionExecutionOwnerRegistry:
    return ProductionExecutionOwnerRegistry(builtin_execution_owner_descriptors())
