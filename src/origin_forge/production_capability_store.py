from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ids import IdKind, new_id, validate_id
from .production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    CapabilityRoutingPolicy,
    ProductionCapability,
    ProductionCapabilityError,
    TrustedProductionAdapter,
)
from .production_capability_routing import (
    CapabilityRouteOutcome,
    CapabilityRouteReason,
    CapabilityRouteReasonCode,
    CapabilityRouteResolution,
    CapabilityRoutingError,
    TaskRouteInput,
    resolve_task_route,
)
from .runtime import OriginForgeRuntime


_SCHEMA_VERSION = 1
_MAX_OBJECT_BYTES = 2 * 1024 * 1024
_MAX_OBJECTS_PER_CATEGORY = 10_000
_CATEGORY_KIND = {
    "catalogs": IdKind.CAPABILITY_CATALOG,
    "policies": IdKind.CAPABILITY_ROUTING_POLICY,
    "routes": IdKind.CAPABILITY_ROUTE_DECISION,
}


class ProductionCapabilityStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionCapabilityStoreError(f"duplicate JSON key: {key}")
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
        raise ProductionCapabilityStoreError(
            "production capability evidence is not canonical JSON"
        ) from exc
    if not data or len(data) > _MAX_OBJECT_BYTES:
        raise ProductionCapabilityStoreError(
            "production capability evidence is outside byte bounds"
        )
    return data


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProductionCapabilityStoreError(f"{label} schema drifted")
    return value


def _capability_from_dict(value: object) -> ProductionCapability:
    raw = _exact_keys(
        value,
        {"capability_id", "name", "summary", "media_domain", "contract_version"},
        "ProductionCapability",
    )
    try:
        return ProductionCapability(
            capability_id=raw["capability_id"],
            name=raw["name"],
            summary=raw["summary"],
            media_domain=CapabilityDomain(raw["media_domain"]),
            contract_version=raw["contract_version"],
        )
    except (ProductionCapabilityError, TypeError, ValueError) as exc:
        raise ProductionCapabilityStoreError(
            "stored ProductionCapability failed validation"
        ) from exc


def _adapter_from_dict(value: object) -> TrustedProductionAdapter:
    raw = _exact_keys(
        value,
        {
            "adapter_id",
            "adapter_family",
            "adapter_version",
            "implementation_fingerprint",
            "capability_ids",
            "execution_effect",
            "replay_class",
        },
        "TrustedProductionAdapter",
    )
    if not isinstance(raw["capability_ids"], list):
        raise ProductionCapabilityStoreError("stored adapter capability_ids are invalid")
    try:
        return TrustedProductionAdapter(
            adapter_id=raw["adapter_id"],
            adapter_family=raw["adapter_family"],
            adapter_version=raw["adapter_version"],
            implementation_fingerprint=raw["implementation_fingerprint"],
            capability_ids=tuple(raw["capability_ids"]),
            execution_effect=AdapterExecutionEffect(raw["execution_effect"]),
            replay_class=AdapterReplayClass(raw["replay_class"]),
        )
    except (ProductionCapabilityError, TypeError, ValueError) as exc:
        raise ProductionCapabilityStoreError(
            "stored TrustedProductionAdapter failed validation"
        ) from exc


def _catalog_from_dict(value: object) -> CapabilityCatalog:
    raw = _exact_keys(
        value,
        {"catalog_id", "schema_version", "capabilities", "adapters"},
        "CapabilityCatalog",
    )
    if not isinstance(raw["capabilities"], list) or not isinstance(raw["adapters"], list):
        raise ProductionCapabilityStoreError("stored catalog arrays are invalid")
    try:
        return CapabilityCatalog(
            catalog_id=raw["catalog_id"],
            capabilities=tuple(_capability_from_dict(item) for item in raw["capabilities"]),
            adapters=tuple(_adapter_from_dict(item) for item in raw["adapters"]),
            schema_version=raw["schema_version"],
        )
    except (ProductionCapabilityError, TypeError, ValueError) as exc:
        raise ProductionCapabilityStoreError("stored CapabilityCatalog failed validation") from exc


def _policy_from_dict(value: object) -> CapabilityRoutingPolicy:
    raw = _exact_keys(
        value,
        {
            "routing_policy_id",
            "catalog_id",
            "catalog_hash",
            "ordered_adapter_ids",
            "allowed_capability_ids",
        },
        "CapabilityRoutingPolicy",
    )
    if not isinstance(raw["ordered_adapter_ids"], list) or not isinstance(
        raw["allowed_capability_ids"], list
    ):
        raise ProductionCapabilityStoreError("stored routing policy arrays are invalid")
    try:
        return CapabilityRoutingPolicy(
            routing_policy_id=raw["routing_policy_id"],
            catalog_id=raw["catalog_id"],
            catalog_hash=raw["catalog_hash"],
            ordered_adapter_ids=tuple(raw["ordered_adapter_ids"]),
            allowed_capability_ids=tuple(raw["allowed_capability_ids"]),
        )
    except (ProductionCapabilityError, TypeError, ValueError) as exc:
        raise ProductionCapabilityStoreError(
            "stored CapabilityRoutingPolicy failed validation"
        ) from exc


def _route_input_from_dict(value: object) -> TaskRouteInput:
    raw = _exact_keys(
        value,
        {
            "task_id",
            "flow_id",
            "task_revision",
            "task_content_hash",
            "required_capabilities",
        },
        "TaskRouteInput",
    )
    if not isinstance(raw["required_capabilities"], list):
        raise ProductionCapabilityStoreError("stored route input capabilities are invalid")
    if not validate_id(raw["task_id"], IdKind.TASK) or not validate_id(
        raw["flow_id"], IdKind.FLOW
    ):
        raise ProductionCapabilityStoreError("stored route input canonical IDs are invalid")
    if type(raw["task_revision"]) is not int or raw["task_revision"] < 0:
        raise ProductionCapabilityStoreError("stored route input revision is invalid")
    if (
        not isinstance(raw["task_content_hash"], str)
        or len(raw["task_content_hash"]) != 64
        or any(c not in "0123456789abcdef" for c in raw["task_content_hash"])
    ):
        raise ProductionCapabilityStoreError("stored route input hash is invalid")
    capabilities = tuple(raw["required_capabilities"])
    if any(not isinstance(item, str) or not item for item in capabilities):
        raise ProductionCapabilityStoreError("stored route input capability is invalid")
    return TaskRouteInput(
        task_id=raw["task_id"],
        flow_id=raw["flow_id"],
        task_revision=raw["task_revision"],
        task_content_hash=raw["task_content_hash"],
        required_capabilities=tuple(sorted(capabilities)),
    )


def _reason_from_dict(value: object) -> CapabilityRouteReason:
    raw = _exact_keys(
        value,
        {"code", "subject_id", "capability_ids"},
        "CapabilityRouteReason",
    )
    if not isinstance(raw["capability_ids"], list):
        raise ProductionCapabilityStoreError("stored route reason capabilities are invalid")
    try:
        return CapabilityRouteReason(
            code=CapabilityRouteReasonCode(raw["code"]),
            subject_id=raw["subject_id"],
            capability_ids=tuple(raw["capability_ids"]),
        )
    except (CapabilityRoutingError, TypeError, ValueError) as exc:
        raise ProductionCapabilityStoreError("stored route reason failed validation") from exc


def _resolution_from_dict(value: object) -> CapabilityRouteResolution:
    raw = _exact_keys(
        value,
        {
            "route_input",
            "catalog_id",
            "catalog_hash",
            "routing_policy_id",
            "routing_policy_hash",
            "outcome",
            "selected_adapter_id",
            "selected_adapter_fingerprint",
            "considered_adapter_ids",
            "reasons",
        },
        "CapabilityRouteResolution",
    )
    if not isinstance(raw["considered_adapter_ids"], list) or not isinstance(
        raw["reasons"], list
    ):
        raise ProductionCapabilityStoreError("stored route resolution arrays are invalid")
    try:
        return CapabilityRouteResolution(
            route_input=_route_input_from_dict(raw["route_input"]),
            catalog_id=raw["catalog_id"],
            catalog_hash=raw["catalog_hash"],
            routing_policy_id=raw["routing_policy_id"],
            routing_policy_hash=raw["routing_policy_hash"],
            outcome=CapabilityRouteOutcome(raw["outcome"]),
            selected_adapter_id=raw["selected_adapter_id"],
            selected_adapter_fingerprint=raw["selected_adapter_fingerprint"],
            considered_adapter_ids=tuple(raw["considered_adapter_ids"]),
            reasons=tuple(_reason_from_dict(item) for item in raw["reasons"]),
        )
    except (CapabilityRoutingError, TypeError, ValueError) as exc:
        raise ProductionCapabilityStoreError(
            "stored CapabilityRouteResolution failed validation"
        ) from exc


@dataclass(frozen=True)
class CapabilityRouteDecision:
    route_decision_id: str
    resolution: CapabilityRouteResolution

    def __post_init__(self) -> None:
        if not validate_id(self.route_decision_id, IdKind.CAPABILITY_ROUTE_DECISION):
            raise ProductionCapabilityStoreError("route_decision_id must be a CAPROUTE ID")
        if not isinstance(self.resolution, CapabilityRouteResolution):
            raise ProductionCapabilityStoreError("route decision resolution is invalid")

    @classmethod
    def create(cls, resolution: CapabilityRouteResolution) -> "CapabilityRouteDecision":
        return cls(new_id(IdKind.CAPABILITY_ROUTE_DECISION), resolution)

    def to_dict(self) -> dict[str, object]:
        return {
            "route_decision_id": self.route_decision_id,
            "resolution": self.resolution.to_dict(),
        }

    @property
    def content_hash(self) -> str:
        import hashlib

        return hashlib.sha256(_canonical_bytes(self.to_dict())).hexdigest()


def _decision_from_dict(value: object) -> CapabilityRouteDecision:
    raw = _exact_keys(value, {"route_decision_id", "resolution"}, "CapabilityRouteDecision")
    return CapabilityRouteDecision(
        route_decision_id=raw["route_decision_id"],
        resolution=_resolution_from_dict(raw["resolution"]),
    )


class ProductionCapabilityStore:
    """Protected immutable persistence for Phase-32 capability routing evidence."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "production-capabilities"

    def _ensure_root(self) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        if self.root.is_symlink():
            raise ProductionCapabilityStoreError(
                "production-capabilities root may not be a symlink"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            root = self.root.resolve(strict=True)
            root.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionCapabilityStoreError(
                "production-capabilities root escaped protected project state"
            ) from exc
        return root

    def _category_dir(self, category: str, *, create: bool) -> Path:
        if category not in _CATEGORY_KIND:
            raise ProductionCapabilityStoreError("unknown production capability category")
        root = self._ensure_root()
        directory = root / category
        if directory.is_symlink():
            raise ProductionCapabilityStoreError(f"{category} directory may not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.exists():
            return directory
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionCapabilityStoreError(f"{category} directory escaped protected root") from exc
        return directory

    def _exact_path(self, category: str, object_id: str, *, require_file: bool) -> Path:
        kind = _CATEGORY_KIND.get(category)
        if kind is None or not validate_id(object_id, kind):
            raise ProductionCapabilityStoreError("invalid production capability object ID")
        directory = self._category_dir(category, create=False)
        path = directory / f"{object_id}.json"
        if path.is_symlink():
            raise ProductionCapabilityStoreError("production capability object may not be a symlink")
        if require_file and not path.is_file():
            raise ProductionCapabilityStoreError("production capability object does not exist")
        if not path.exists():
            return path
        try:
            root = self.root.resolve(strict=True)
            expected = root / category / f"{object_id}.json"
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProductionCapabilityStoreError("production capability object escaped protected root") from exc
        if resolved != expected:
            raise ProductionCapabilityStoreError("production capability object path is aliased")
        return path

    @staticmethod
    def _identity(category: str, value: object) -> tuple[str, str, dict[str, object]]:
        if category == "catalogs" and isinstance(value, CapabilityCatalog):
            return value.catalog_id, value.content_hash, value.to_dict()
        if category == "policies" and isinstance(value, CapabilityRoutingPolicy):
            return value.routing_policy_id, value.content_hash, value.to_dict()
        if category == "routes" and isinstance(value, CapabilityRouteDecision):
            return value.route_decision_id, value.content_hash, value.to_dict()
        raise TypeError(f"object type does not belong in production-capabilities/{category}")

    def _publish(self, category: str, value: object) -> Path:
        directory = self._category_dir(category, create=True)
        object_id, content_hash, payload = self._identity(category, value)
        if not validate_id(object_id, _CATEGORY_KIND[category]):
            raise ProductionCapabilityStoreError("object ID has wrong category prefix")
        if len(tuple(directory.glob("*.json"))) >= _MAX_OBJECTS_PER_CATEGORY:
            raise ProductionCapabilityStoreError(f"{category} object-count limit reached")
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "object_type": category,
            "object_id": object_id,
            "content_hash": content_hash,
            "payload": payload,
        }
        data = _canonical_bytes(envelope)
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            raise ProductionCapabilityStoreError("production capability object already exists")
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ProductionCapabilityStoreError(
                "production capability object already exists"
            ) from exc
        return self._exact_path(category, object_id, require_file=True)

    def _load_envelope(self, category: str, object_id: str) -> dict[str, Any]:
        path = self._exact_path(category, object_id, require_file=True)
        size = path.stat().st_size
        if size <= 0 or size > _MAX_OBJECT_BYTES:
            raise ProductionCapabilityStoreError("production capability object byte size is outside bounds")
        try:
            raw = path.read_bytes()
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except ProductionCapabilityStoreError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionCapabilityStoreError(
                "production capability object is not strict UTF-8 JSON"
            ) from exc
        envelope = _exact_keys(
            envelope,
            {"schema_version", "object_type", "object_id", "content_hash", "payload"},
            "production capability envelope",
        )
        if (
            envelope["schema_version"] != _SCHEMA_VERSION
            or envelope["object_type"] != category
            or envelope["object_id"] != object_id
            or not isinstance(envelope["payload"], dict)
        ):
            raise ProductionCapabilityStoreError("production capability envelope binding drifted")
        if _canonical_bytes(envelope) != raw:
            raise ProductionCapabilityStoreError("production capability object bytes are not canonical")
        return envelope

    def publish_catalog(self, catalog: CapabilityCatalog) -> Path:
        return self._publish("catalogs", catalog)

    def load_catalog(self, catalog_id: str) -> CapabilityCatalog:
        envelope = self._load_envelope("catalogs", catalog_id)
        catalog = _catalog_from_dict(envelope["payload"])
        if catalog.catalog_id != catalog_id or catalog.content_hash != envelope["content_hash"]:
            raise ProductionCapabilityStoreError("catalog content hash drifted")
        return catalog

    def publish_policy(
        self, policy: CapabilityRoutingPolicy, catalog: CapabilityCatalog
    ) -> Path:
        persisted = self.load_catalog(catalog.catalog_id)
        if persisted.content_hash != catalog.content_hash:
            raise ProductionCapabilityStoreError("catalog argument differs from persisted catalog")
        try:
            policy.validate_against(persisted)
        except ProductionCapabilityError as exc:
            raise ProductionCapabilityStoreError("routing policy failed catalog validation") from exc
        return self._publish("policies", policy)

    def load_policy(self, policy_id: str) -> CapabilityRoutingPolicy:
        envelope = self._load_envelope("policies", policy_id)
        policy = _policy_from_dict(envelope["payload"])
        if policy.routing_policy_id != policy_id or policy.content_hash != envelope["content_hash"]:
            raise ProductionCapabilityStoreError("routing policy content hash drifted")
        catalog = self.load_catalog(policy.catalog_id)
        try:
            policy.validate_against(catalog)
        except ProductionCapabilityError as exc:
            raise ProductionCapabilityStoreError("routing policy relation drifted") from exc
        return policy

    def resolve_and_publish(
        self,
        task_id: str,
        catalog_id: str,
        policy_id: str,
    ) -> CapabilityRouteDecision:
        catalog = self.load_catalog(catalog_id)
        policy = self.load_policy(policy_id)
        if policy.catalog_id != catalog.catalog_id or policy.catalog_hash != catalog.content_hash:
            raise ProductionCapabilityStoreError("route catalog/policy relation drifted")
        resolution = resolve_task_route(self.runtime.store, task_id, catalog, policy)
        decision = CapabilityRouteDecision.create(resolution)
        self._publish("routes", decision)
        return decision

    def load_route(self, route_decision_id: str) -> CapabilityRouteDecision:
        envelope = self._load_envelope("routes", route_decision_id)
        decision = _decision_from_dict(envelope["payload"])
        if (
            decision.route_decision_id != route_decision_id
            or decision.content_hash != envelope["content_hash"]
        ):
            raise ProductionCapabilityStoreError("route decision content hash drifted")
        catalog = self.load_catalog(decision.resolution.catalog_id)
        policy = self.load_policy(decision.resolution.routing_policy_id)
        if (
            decision.resolution.catalog_hash != catalog.content_hash
            or decision.resolution.routing_policy_hash != policy.content_hash
            or policy.catalog_id != catalog.catalog_id
        ):
            raise ProductionCapabilityStoreError("route decision catalog/policy relation drifted")
        return decision

    def require_current_route(self, route_decision_id: str) -> CapabilityRouteDecision:
        decision = self.load_route(route_decision_id)
        catalog = self.load_catalog(decision.resolution.catalog_id)
        policy = self.load_policy(decision.resolution.routing_policy_id)
        current = resolve_task_route(
            self.runtime.store,
            decision.resolution.route_input.task_id,
            catalog,
            policy,
        )
        if current.to_dict() != decision.resolution.to_dict():
            raise ProductionCapabilityStoreError("route decision is stale for current Task state")
        return decision
