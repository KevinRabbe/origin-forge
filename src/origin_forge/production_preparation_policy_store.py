from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .ids import IdKind, validate_id
from .production_capability_read import read_capability_catalog, read_capability_policy
from .production_planning_inspection import inspect_plan_materialization, inspect_planning_input
from .production_preparation_models import (
    ProductionPreparationModelError,
    TaskPreparationPolicyBinding,
)
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
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_read import read_dispatch_catalog
from .runtime import OriginForgeRuntime


_SCHEMA_VERSION = 1
_MAX_POLICY_BYTES = 1024 * 1024
_MAX_POLICIES = 10_000


class ProductionPreparationPolicyStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionPreparationPolicyStoreError(
                f"duplicate PREPPOL JSON key: {key}"
            )
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionPreparationPolicyStoreError(
            "PREPPOL evidence is not finite canonical JSON"
        ) from exc
    if not data or len(data) > _MAX_POLICY_BYTES:
        raise ProductionPreparationPolicyStoreError(
            "PREPPOL evidence is outside byte bounds"
        )
    return data


def _policy_from_dict(value: object) -> TaskPreparationPolicyBinding:
    keys = {
        "preparation_policy_id",
        "project_id",
        "materialization_id",
        "materialization_hash",
        "planning_input_id",
        "planning_input_hash",
        "capability_catalog_id",
        "capability_catalog_hash",
        "capability_routing_policy_id",
        "capability_routing_policy_hash",
        "dispatch_contract_catalog_id",
        "dispatch_contract_catalog_hash",
        "preparation_owner_id",
        "preparation_owner_fingerprint",
        "planner_request_version",
        "planner_contract_id",
        "model_strategy_roles",
        "schema_version",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ProductionPreparationPolicyStoreError("stored PREPPOL schema drifted")
    roles = value["model_strategy_roles"]
    if not isinstance(roles, list):
        raise ProductionPreparationPolicyStoreError(
            "stored PREPPOL model strategy roles are invalid"
        )
    try:
        return TaskPreparationPolicyBinding(
            preparation_policy_id=value["preparation_policy_id"],
            project_id=value["project_id"],
            materialization_id=value["materialization_id"],
            materialization_hash=value["materialization_hash"],
            planning_input_id=value["planning_input_id"],
            planning_input_hash=value["planning_input_hash"],
            capability_catalog_id=value["capability_catalog_id"],
            capability_catalog_hash=value["capability_catalog_hash"],
            capability_routing_policy_id=value["capability_routing_policy_id"],
            capability_routing_policy_hash=value["capability_routing_policy_hash"],
            dispatch_contract_catalog_id=value["dispatch_contract_catalog_id"],
            dispatch_contract_catalog_hash=value["dispatch_contract_catalog_hash"],
            preparation_owner_id=value["preparation_owner_id"],
            preparation_owner_fingerprint=value["preparation_owner_fingerprint"],
            planner_request_version=value["planner_request_version"],
            planner_contract_id=value["planner_contract_id"],
            model_strategy_roles=tuple(roles),
            schema_version=value["schema_version"],
        )
    except (ProductionPreparationModelError, TypeError, ValueError) as exc:
        raise ProductionPreparationPolicyStoreError(
            "stored PREPPOL failed contract validation"
        ) from exc


def _root(runtime: OriginForgeRuntime, *, create: bool) -> Path:
    state = runtime.state_dir.resolve(strict=True)
    root = runtime.state_dir / "production-preparation" / "policies"
    parent = root.parent
    for candidate, label in ((parent, "production-preparation"), (root, "policies")):
        if candidate.is_symlink():
            raise ProductionPreparationPolicyStoreError(
                f"{label} path may not be a symlink"
            )
    if create:
        parent.mkdir(exist_ok=True)
        root.mkdir(exist_ok=True)
    if not root.exists():
        raise ProductionPreparationPolicyStoreError(
            "protected PREPPOL store does not exist"
        )
    if not root.is_dir():
        raise ProductionPreparationPolicyStoreError(
            "protected PREPPOL store is not a directory"
        )
    try:
        resolved = root.resolve(strict=True)
        resolved.relative_to(state)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionPreparationPolicyStoreError(
            "protected PREPPOL store escaped project state"
        ) from exc
    return resolved


def _policy_path(
    runtime: OriginForgeRuntime,
    preparation_policy_id: str,
    *,
    require_file: bool,
    create_root: bool,
) -> Path:
    if not validate_id(preparation_policy_id, IdKind.TASK_PREPARATION_POLICY):
        raise ProductionPreparationPolicyStoreError("invalid PREPPOL ID")
    root = _root(runtime, create=create_root)
    path = root / f"{preparation_policy_id}.json"
    if path.is_symlink():
        raise ProductionPreparationPolicyStoreError("PREPPOL file may not be a symlink")
    if require_file and not path.is_file():
        raise ProductionPreparationPolicyStoreError("PREPPOL does not exist")
    if path.exists():
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProductionPreparationPolicyStoreError(
                "PREPPOL file could not be resolved"
            ) from exc
        if resolved != path or resolved.parent != root:
            raise ProductionPreparationPolicyStoreError(
                "PREPPOL file path is aliased"
            )
    return path


def _matching_owner(
    dispatch_catalog,
) -> ProductionPreparationOwnerDescriptor:
    registry = build_builtin_preparation_owner_registry()
    matches: list[ProductionPreparationOwnerDescriptor] = []
    for owner in registry.descriptors:
        try:
            contract = dispatch_catalog.contract_for_adapter(owner.supported_adapter_id)
        except KeyError:
            continue
        if (
            contract.contract_id == owner.supported_dispatch_contract_id
            and contract.content_hash == owner.supported_dispatch_contract_hash
            and contract.adapter_fingerprint == owner.supported_adapter_fingerprint
        ):
            matches.append(owner)
    if len(matches) != 1:
        raise ProductionPreparationPolicyStoreError(
            "exact dispatch catalog does not resolve one code-owned preparation owner"
        )
    return matches[0]


def create_preparation_policy_binding(
    runtime: OriginForgeRuntime,
    *,
    materialization_id: str,
    capability_catalog_id: str,
    capability_routing_policy_id: str,
    dispatch_contract_catalog_id: str,
) -> TaskPreparationPolicyBinding:
    """Construct PREPPOL from explicit evidence IDs and code-owned owner authority.

    The caller may choose the already-persisted planning/capability/dispatch
    evidence relation. It cannot choose owner fingerprints, planner contract,
    semantic model roles, model profiles, runtime providers, endpoints, loaders,
    sandbox settings, or process authority.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    try:
        materialization = inspect_plan_materialization(runtime, materialization_id)
        planning_input = inspect_planning_input(runtime, materialization.planning_input_id)
        catalog = read_capability_catalog(runtime, capability_catalog_id)
        routing_policy = read_capability_policy(runtime, capability_routing_policy_id)
        dispatch_catalog = read_dispatch_catalog(
            runtime,
            dispatch_contract_catalog_id,
            build_builtin_dispatch_validator_registry(),
        )
        owner = _matching_owner(dispatch_catalog)
        result = TaskPreparationPolicyBinding.create(
            project_id=planning_input.project_id,
            materialization_id=materialization.materialization_id,
            materialization_hash=materialization.content_hash,
            planning_input_id=planning_input.planning_input_id,
            planning_input_hash=planning_input.content_hash,
            capability_catalog_id=catalog.catalog_id,
            capability_catalog_hash=catalog.content_hash,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            capability_routing_policy_hash=routing_policy.content_hash,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
            dispatch_contract_catalog_hash=dispatch_catalog.content_hash,
            preparation_owner_id=owner.owner_id,
            preparation_owner_fingerprint=owner.fingerprint,
            planner_request_version=owner.planner_request_version,
            planner_contract_id=owner.planner_contract_id,
            model_strategy_roles=owner.policy_role_names,
        )
        provenance = resolve_preparation_policy_provenance(runtime, result)
        require_current_preparation_owner(
            result,
            provenance.dispatch_contract_catalog,
        )
        return result
    except ProductionPreparationPolicyStoreError:
        raise
    except Exception as exc:
        raise ProductionPreparationPolicyStoreError(
            "PREPPOL could not be constructed from exact current evidence"
        ) from exc


def publish_preparation_policy(
    runtime: OriginForgeRuntime,
    policy: TaskPreparationPolicyBinding,
) -> Path:
    """Publish one immutable PREPPOL after full provenance/owner revalidation."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(policy, TaskPreparationPolicyBinding):
        raise TypeError("policy must be a TaskPreparationPolicyBinding")
    try:
        provenance = resolve_preparation_policy_provenance(runtime, policy)
        require_current_preparation_owner(
            policy,
            provenance.dispatch_contract_catalog,
        )
    except (
        ProductionPreparationProvenanceError,
        ProductionPreparationOwnerError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionPreparationPolicyStoreError(
            "PREPPOL failed full authority validation before publication"
        ) from exc

    root = _root(runtime, create=True)
    if len(tuple(root.glob("PREPPOL-*.json"))) >= _MAX_POLICIES:
        raise ProductionPreparationPolicyStoreError("PREPPOL object-count limit reached")
    path = _policy_path(
        runtime,
        policy.preparation_policy_id,
        require_file=False,
        create_root=True,
    )
    if path.exists() or path.is_symlink():
        raise ProductionPreparationPolicyStoreError("PREPPOL already exists")
    envelope = {
        "schema_version": _SCHEMA_VERSION,
        "object_type": "preparation-policy",
        "object_id": policy.preparation_policy_id,
        "content_hash": policy.content_hash,
        "payload": policy.to_dict(),
    }
    data = _canonical_bytes(envelope)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ProductionPreparationPolicyStoreError("PREPPOL already exists") from exc
    return _policy_path(
        runtime,
        policy.preparation_policy_id,
        require_file=True,
        create_root=False,
    )


def read_preparation_policy(
    runtime: OriginForgeRuntime,
    preparation_policy_id: str,
) -> TaskPreparationPolicyBinding:
    """Read and fully revalidate one PREPPOL without creating store state."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    path = _policy_path(
        runtime,
        preparation_policy_id,
        require_file=True,
        create_root=False,
    )
    try:
        size = path.stat().st_size
        if size <= 0 or size > _MAX_POLICY_BYTES:
            raise ProductionPreparationPolicyStoreError(
                "stored PREPPOL byte size is outside bounds"
            )
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except ProductionPreparationPolicyStoreError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionPreparationPolicyStoreError(
            "stored PREPPOL is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "object_type",
        "object_id",
        "content_hash",
        "payload",
    }:
        raise ProductionPreparationPolicyStoreError("PREPPOL envelope schema drifted")
    if (
        envelope["schema_version"] != _SCHEMA_VERSION
        or envelope["object_type"] != "preparation-policy"
        or envelope["object_id"] != preparation_policy_id
        or not isinstance(envelope["payload"], dict)
        or _canonical_bytes(envelope) != raw
    ):
        raise ProductionPreparationPolicyStoreError("PREPPOL envelope binding drifted")
    policy = _policy_from_dict(envelope["payload"])
    if (
        policy.preparation_policy_id != preparation_policy_id
        or policy.content_hash != envelope["content_hash"]
    ):
        raise ProductionPreparationPolicyStoreError("PREPPOL content hash drifted")
    try:
        provenance = resolve_preparation_policy_provenance(runtime, policy)
        require_current_preparation_owner(
            policy,
            provenance.dispatch_contract_catalog,
        )
    except (
        ProductionPreparationProvenanceError,
        ProductionPreparationOwnerError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionPreparationPolicyStoreError(
            "stored PREPPOL is stale or invalid"
        ) from exc
    return policy
