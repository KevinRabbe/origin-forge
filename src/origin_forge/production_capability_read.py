from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ids import IdKind, validate_id
from .production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from .production_capability_routing import (
    CapabilityRouteResolution,
    CapabilityRoutingError,
    TaskRouteInput,
    resolve_route_input,
)
from .production_capability_store import (
    _CATEGORY_KIND,
    _MAX_OBJECT_BYTES,
    _MAX_OBJECTS_PER_CATEGORY,
    _canonical_bytes,
    _catalog_from_dict,
    _decision_from_dict,
    _policy_from_dict,
    _strict_object,
    CapabilityRouteDecision,
    ProductionCapabilityStoreError,
)
from .production_read_guard import (
    ProductionReadGuardError,
    existing_config_path,
    production_read_connection,
)
from .runtime import OriginForgeRuntime


class ProductionCapabilityReadError(RuntimeError):
    pass


def _state_exists(runtime: OriginForgeRuntime) -> bool:
    state = runtime.state_dir
    config = state / "config.toml"
    return state.is_dir() and not state.is_symlink() and config.is_file() and not config.is_symlink()


def _existing_root(runtime: OriginForgeRuntime, *, required: bool) -> Path | None:
    try:
        existing_config_path(runtime.project_root)
    except ProductionReadGuardError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    root = runtime.state_dir / "production-capabilities"
    if root.is_symlink():
        raise ProductionCapabilityReadError("production-capabilities root may not be a symlink")
    if not root.exists():
        if required:
            raise ProductionCapabilityReadError("production-capabilities evidence root does not exist")
        return None
    if not root.is_dir():
        raise ProductionCapabilityReadError("production-capabilities root is not a directory")
    try:
        state = runtime.state_dir.resolve(strict=True)
        resolved = root.resolve(strict=True)
        resolved.relative_to(state)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionCapabilityReadError(
            "production-capabilities root escaped protected state"
        ) from exc
    return resolved


def _category_dir(
    runtime: OriginForgeRuntime, category: str, *, required: bool
) -> Path | None:
    if category not in _CATEGORY_KIND:
        raise ProductionCapabilityReadError("unknown production capability category")
    root = _existing_root(runtime, required=required)
    if root is None:
        return None
    directory = root / category
    if directory.is_symlink():
        raise ProductionCapabilityReadError(f"{category} directory may not be a symlink")
    if not directory.exists():
        if required:
            raise ProductionCapabilityReadError(f"{category} evidence directory does not exist")
        return None
    if not directory.is_dir():
        raise ProductionCapabilityReadError(f"{category} evidence path is not a directory")
    try:
        resolved = directory.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionCapabilityReadError(f"{category} directory escaped protected root") from exc
    return resolved


def _object_path(runtime: OriginForgeRuntime, category: str, object_id: str) -> Path:
    kind = _CATEGORY_KIND.get(category)
    if kind is None or not validate_id(object_id, kind):
        raise ProductionCapabilityReadError("invalid production capability object ID")
    directory = _category_dir(runtime, category, required=True)
    assert directory is not None
    path = directory / f"{object_id}.json"
    if path.is_symlink():
        raise ProductionCapabilityReadError("production capability object may not be a symlink")
    if not path.is_file():
        raise ProductionCapabilityReadError("production capability object does not exist")
    try:
        root = (runtime.state_dir / "production-capabilities").resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionCapabilityReadError("production capability object escaped protected root") from exc
    if resolved != path:
        raise ProductionCapabilityReadError("production capability object path is aliased")
    return path


def _load_envelope(runtime: OriginForgeRuntime, category: str, object_id: str) -> dict[str, Any]:
    path = _object_path(runtime, category, object_id)
    try:
        size = path.stat().st_size
        if size <= 0 or size > _MAX_OBJECT_BYTES:
            raise ProductionCapabilityReadError("production capability object byte size is outside bounds")
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except ProductionCapabilityStoreError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionCapabilityReadError(
            "production capability object is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "object_type",
        "object_id",
        "content_hash",
        "payload",
    }:
        raise ProductionCapabilityReadError("production capability envelope schema drifted")
    if (
        envelope["schema_version"] != 1
        or envelope["object_type"] != category
        or envelope["object_id"] != object_id
        or not isinstance(envelope["payload"], dict)
    ):
        raise ProductionCapabilityReadError("production capability envelope binding drifted")
    try:
        if _canonical_bytes(envelope) != raw:
            raise ProductionCapabilityReadError("production capability object bytes are not canonical")
    except ProductionCapabilityStoreError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    return envelope


def read_capability_catalog(
    runtime: OriginForgeRuntime, catalog_id: str
) -> CapabilityCatalog:
    envelope = _load_envelope(runtime, "catalogs", catalog_id)
    try:
        catalog = _catalog_from_dict(envelope["payload"])
    except ProductionCapabilityStoreError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    if catalog.catalog_id != catalog_id or catalog.content_hash != envelope["content_hash"]:
        raise ProductionCapabilityReadError("catalog content hash drifted")
    return catalog


def read_capability_policy(
    runtime: OriginForgeRuntime, policy_id: str
) -> CapabilityRoutingPolicy:
    envelope = _load_envelope(runtime, "policies", policy_id)
    try:
        policy = _policy_from_dict(envelope["payload"])
    except ProductionCapabilityStoreError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    if policy.routing_policy_id != policy_id or policy.content_hash != envelope["content_hash"]:
        raise ProductionCapabilityReadError("routing policy content hash drifted")
    catalog = read_capability_catalog(runtime, policy.catalog_id)
    try:
        policy.validate_against(catalog)
    except Exception as exc:
        raise ProductionCapabilityReadError("routing policy relation drifted") from exc
    return policy


def read_capability_route(
    runtime: OriginForgeRuntime, route_decision_id: str
) -> CapabilityRouteDecision:
    envelope = _load_envelope(runtime, "routes", route_decision_id)
    try:
        decision = _decision_from_dict(envelope["payload"])
    except ProductionCapabilityStoreError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    if (
        decision.route_decision_id != route_decision_id
        or decision.content_hash != envelope["content_hash"]
    ):
        raise ProductionCapabilityReadError("route decision content hash drifted")
    catalog = read_capability_catalog(runtime, decision.resolution.catalog_id)
    policy = read_capability_policy(runtime, decision.resolution.routing_policy_id)
    if (
        decision.resolution.catalog_hash != catalog.content_hash
        or decision.resolution.routing_policy_hash != policy.content_hash
    ):
        raise ProductionCapabilityReadError("route decision relation drifted")
    return decision


def inspect_task_route(
    runtime: OriginForgeRuntime,
    task_id: str,
    catalog_id: str,
    policy_id: str,
) -> CapabilityRouteResolution:
    catalog = read_capability_catalog(runtime, catalog_id)
    policy = read_capability_policy(runtime, policy_id)
    try:
        with production_read_connection(runtime) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            flow = conn.execute("SELECT id FROM flows WHERE id = ?", (row["flow_id"],)).fetchone()
            if flow is None:
                raise ProductionCapabilityReadError("Task references a missing canonical Flow")
            route_input = TaskRouteInput.from_row(row)
            return resolve_route_input(route_input, catalog, policy)
    except ProductionReadGuardError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    except CapabilityRoutingError:
        raise


def capability_read_status(runtime: OriginForgeRuntime) -> dict[str, object]:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _state_exists(runtime):
        return {
            "initialized": False,
            "evidence_root_present": False,
            "catalogs": 0,
            "policies": 0,
            "routes": 0,
        }
    try:
        with production_read_connection(runtime):
            pass
    except ProductionReadGuardError as exc:
        raise ProductionCapabilityReadError(str(exc)) from exc
    root = _existing_root(runtime, required=False)
    if root is None:
        return {
            "initialized": True,
            "evidence_root_present": False,
            "catalogs": 0,
            "policies": 0,
            "routes": 0,
        }
    counts: dict[str, int] = {}
    for category in ("catalogs", "policies", "routes"):
        directory = _category_dir(runtime, category, required=False)
        if directory is None:
            counts[category] = 0
            continue
        paths = tuple(directory.glob("*.json"))
        if len(paths) > _MAX_OBJECTS_PER_CATEGORY:
            raise ProductionCapabilityReadError(f"{category} object-count limit exceeded")
        if any(path.is_symlink() or not path.is_file() for path in paths):
            raise ProductionCapabilityReadError(f"{category} contains invalid evidence entries")
        counts[category] = len(paths)
    return {
        "initialized": True,
        "evidence_root_present": True,
        **counts,
    }
