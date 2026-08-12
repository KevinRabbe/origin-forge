from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence

from .model_scheduler import ModelRole
from .production_capability_builtin import (
    build_builtin_capability_catalog,
    builtin_trusted_production_adapters,
)
from .production_preparation_models import TaskPreparationPolicyBinding
from .production_work_order_builtin import build_builtin_dispatch_catalog
from .production_work_order_models import DispatchContractCatalog


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ProductionPreparationOwnerError(RuntimeError):
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
        raise ProductionPreparationOwnerError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ProductionPreparationOwnerError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


@dataclass(frozen=True)
class ProductionPreparationOwnerDescriptor:
    """Inert code-owned authority for one bounded WorkOrder-planner relation."""

    owner_id: str
    owner_version: str
    planner_request_version: str
    planner_contract_id: str
    supported_adapter_id: str
    supported_adapter_fingerprint: str
    supported_dispatch_contract_id: str
    supported_dispatch_contract_hash: str
    model_strategy_roles: tuple[ModelRole, ...]

    def __post_init__(self) -> None:
        _identity(self.owner_id, "owner_id")
        _identity(self.owner_version, "owner_version")
        _identity(self.planner_request_version, "planner_request_version")
        _identity(self.planner_contract_id, "planner_contract_id")
        _identity(self.supported_adapter_id, "supported_adapter_id")
        _digest(self.supported_adapter_fingerprint, "supported_adapter_fingerprint")
        _identity(
            self.supported_dispatch_contract_id,
            "supported_dispatch_contract_id",
        )
        _digest(
            self.supported_dispatch_contract_hash,
            "supported_dispatch_contract_hash",
        )
        roles = tuple(self.model_strategy_roles)
        if not roles or any(not isinstance(role, ModelRole) for role in roles):
            raise ProductionPreparationOwnerError(
                "model_strategy_roles must contain ModelRole values"
            )
        if len(roles) != len(set(roles)):
            raise ProductionPreparationOwnerError(
                "model_strategy_roles may not contain duplicates"
            )
        object.__setattr__(self, "model_strategy_roles", roles)

    @property
    def policy_role_names(self) -> tuple[str, ...]:
        return tuple(role.name for role in self.model_strategy_roles)

    def authority_dict(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "owner_version": self.owner_version,
            "planner_request_version": self.planner_request_version,
            "planner_contract_id": self.planner_contract_id,
            "supported_adapter_id": self.supported_adapter_id,
            "supported_adapter_fingerprint": self.supported_adapter_fingerprint,
            "supported_dispatch_contract_id": self.supported_dispatch_contract_id,
            "supported_dispatch_contract_hash": self.supported_dispatch_contract_hash,
            "model_strategy_roles": list(self.policy_role_names),
        }

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(self.authority_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.authority_dict(),
            "owner_fingerprint": self.fingerprint,
        }


class ProductionPreparationOwnerRegistry:
    def __init__(
        self,
        descriptors: Sequence[ProductionPreparationOwnerDescriptor],
    ) -> None:
        values = tuple(descriptors)
        if not values or any(
            not isinstance(value, ProductionPreparationOwnerDescriptor)
            for value in values
        ):
            raise ProductionPreparationOwnerError(
                "preparation owner registry requires non-empty descriptor values"
            )
        owner_ids = [value.owner_id for value in values]
        if len(owner_ids) != len(set(owner_ids)):
            raise ProductionPreparationOwnerError(
                "preparation owner registry contains duplicate owner IDs"
            )
        relations = [
            (
                value.planner_contract_id,
                value.supported_adapter_id,
                value.supported_dispatch_contract_id,
            )
            for value in values
        ]
        if len(relations) != len(set(relations)):
            raise ProductionPreparationOwnerError(
                "preparation owner registry contains ambiguous planner relations"
            )
        self._descriptors = tuple(sorted(values, key=lambda value: value.owner_id))
        self._fingerprint = _canonical_hash(
            {"owners": [value.to_dict() for value in self._descriptors]}
        )

    @property
    def descriptors(self) -> tuple[ProductionPreparationOwnerDescriptor, ...]:
        return self._descriptors

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def owner(self, owner_id: str) -> ProductionPreparationOwnerDescriptor:
        normalized = _identity(owner_id, "owner_id")
        matches = [value for value in self._descriptors if value.owner_id == normalized]
        if len(matches) != 1:
            raise ProductionPreparationOwnerError(
                "no unique trusted preparation owner matches PREPPOL"
            )
        return matches[0]


def builtin_preparation_owner_descriptors() -> tuple[ProductionPreparationOwnerDescriptor, ...]:
    adapters = {
        value.adapter_id: value for value in builtin_trusted_production_adapters()
    }
    adapter_id = "originforge.code.bounded-retry"
    try:
        adapter = adapters[adapter_id]
    except KeyError as exc:
        raise ProductionPreparationOwnerError(
            "built-in capability inventory lacks bounded-retry adapter"
        ) from exc

    # Build the reviewed contract through the same code-owned Phase-33 builder.
    # Catalog IDs are intentionally irrelevant here; the contract itself has a
    # stable content identity over adapter/validator/schema authority.
    catalog = build_builtin_dispatch_catalog(build_builtin_capability_catalog())
    try:
        contract = catalog.contract_for_adapter(adapter_id)
    except KeyError as exc:
        raise ProductionPreparationOwnerError(
            "built-in dispatch inventory lacks bounded-retry contract"
        ) from exc
    if contract.adapter_fingerprint != adapter.implementation_fingerprint:
        raise ProductionPreparationOwnerError(
            "built-in preparation adapter/dispatch-contract relation drifted"
        )

    return (
        ProductionPreparationOwnerDescriptor(
            owner_id="originforge.preparation.work-order-planner@1",
            owner_version="1",
            planner_request_version="1",
            planner_contract_id="BoundedProductionWorkOrderPlanner.propose@1",
            supported_adapter_id=adapter.adapter_id,
            supported_adapter_fingerprint=adapter.implementation_fingerprint,
            supported_dispatch_contract_id=contract.contract_id,
            supported_dispatch_contract_hash=contract.content_hash,
            model_strategy_roles=(ModelRole.CODER_STRONG,),
        ),
    )


def build_builtin_preparation_owner_registry() -> ProductionPreparationOwnerRegistry:
    return ProductionPreparationOwnerRegistry(builtin_preparation_owner_descriptors())


def require_current_preparation_owner(
    policy: TaskPreparationPolicyBinding,
    dispatch_catalog: DispatchContractCatalog,
    *,
    registry: ProductionPreparationOwnerRegistry | None = None,
) -> ProductionPreparationOwnerDescriptor:
    """Require PREPPOL owner fields to match current code-owned planner authority."""

    if not isinstance(policy, TaskPreparationPolicyBinding):
        raise TypeError("policy must be a TaskPreparationPolicyBinding")
    if not isinstance(dispatch_catalog, DispatchContractCatalog):
        raise TypeError("dispatch_catalog must be a DispatchContractCatalog")
    owner_registry = registry or build_builtin_preparation_owner_registry()
    if not isinstance(owner_registry, ProductionPreparationOwnerRegistry):
        raise TypeError("registry must be a ProductionPreparationOwnerRegistry")
    owner = owner_registry.owner(policy.preparation_owner_id)
    if (
        policy.preparation_owner_fingerprint != owner.fingerprint
        or policy.planner_request_version != owner.planner_request_version
        or policy.planner_contract_id != owner.planner_contract_id
        or tuple(policy.model_strategy_roles) != owner.policy_role_names
    ):
        raise ProductionPreparationOwnerError(
            "PREPPOL preparation-owner/planner authority is not current"
        )
    try:
        contract = dispatch_catalog.contract_for_adapter(owner.supported_adapter_id)
    except KeyError as exc:
        raise ProductionPreparationOwnerError(
            "PREPPOL dispatch catalog does not support the code-owned preparation owner"
        ) from exc
    if (
        contract.contract_id != owner.supported_dispatch_contract_id
        or contract.content_hash != owner.supported_dispatch_contract_hash
        or contract.adapter_fingerprint != owner.supported_adapter_fingerprint
    ):
        raise ProductionPreparationOwnerError(
            "PREPPOL dispatch catalog drifted from code-owned preparation owner"
        )
    return owner
