from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .ids import IdKind, validate_id
from .production_capability_models import (
    CapabilityCatalog,
    CapabilityRoutingPolicy,
    ProductionCapabilityError,
)
from .service import OriginForgeStore


_MAX_TASK_TEXT_CHARS = 16_384
_MAX_TASK_LIST_ITEMS = 256
_MAX_TASK_BUDGET_KEYS = 128
_MAX_TASK_PAYLOAD_BYTES = 1024 * 1024


class CapabilityRoutingError(RuntimeError):
    pass


class CapabilityRouteOutcome(StrEnum):
    ROUTABLE = "ROUTABLE"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    CAPABILITY_NOT_ALLOWED = "CAPABILITY_NOT_ALLOWED"
    NO_ELIGIBLE_ADAPTER = "NO_ELIGIBLE_ADAPTER"
    INVALID_TASK_CONTRACT = "INVALID_TASK_CONTRACT"


class CapabilityRouteReasonCode(StrEnum):
    NO_REQUIRED_CAPABILITY = "NO_REQUIRED_CAPABILITY"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    CAPABILITY_NOT_ALLOWED = "CAPABILITY_NOT_ALLOWED"
    ADAPTER_MISSING_CAPABILITY = "ADAPTER_MISSING_CAPABILITY"


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CapabilityRoutingError("Task routing payload is not finite canonical JSON") from exc
    if not encoded or len(encoded) > _MAX_TASK_PAYLOAD_BYTES:
        raise CapabilityRoutingError("Task routing payload is outside byte bounds")
    return encoded


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _strict_json(raw: object, label: str) -> object:
    if not isinstance(raw, str):
        raise CapabilityRoutingError(f"Task {label} is not stored JSON text")
    if len(raw.encode("utf-8")) > _MAX_TASK_PAYLOAD_BYTES:
        raise CapabilityRoutingError(f"Task {label} exceeds byte bounds")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CapabilityRoutingError(f"Task {label} contains duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=object_pairs)
    except CapabilityRoutingError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise CapabilityRoutingError(f"Task {label} is invalid JSON") from exc


def _string_list(raw: object, label: str) -> tuple[str, ...]:
    value = _strict_json(raw, label)
    if not isinstance(value, list) or len(value) > _MAX_TASK_LIST_ITEMS:
        raise CapabilityRoutingError(f"Task {label} is outside list bounds")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > _MAX_TASK_TEXT_CHARS:
            raise CapabilityRoutingError(f"Task {label} contains invalid text")
        result.append(item.strip())
    if len(result) != len(set(result)):
        raise CapabilityRoutingError(f"Task {label} contains duplicates")
    return tuple(result)


def _budget(raw: object) -> dict[str, object]:
    value = _strict_json(raw, "budget_json")
    if not isinstance(value, dict) or len(value) > _MAX_TASK_BUDGET_KEYS:
        raise CapabilityRoutingError("Task budget_json is outside object bounds")
    if any(not isinstance(key, str) or not key for key in value):
        raise CapabilityRoutingError("Task budget_json contains invalid keys")
    _canonical_bytes(value)
    return value


def _task_payload(row: sqlite3.Row) -> dict[str, object]:
    if not validate_id(row["id"], IdKind.TASK):
        raise CapabilityRoutingError("Task has invalid canonical ID")
    if not validate_id(row["flow_id"], IdKind.FLOW):
        raise CapabilityRoutingError("Task has invalid canonical Flow ID")
    parent_task_id = row["parent_task_id"]
    if parent_task_id is not None and not validate_id(parent_task_id, IdKind.TASK):
        raise CapabilityRoutingError("Task has invalid parent Task ID")
    objective = row["objective"]
    if (
        not isinstance(objective, str)
        or not objective.strip()
        or len(objective) > _MAX_TASK_TEXT_CHARS
    ):
        raise CapabilityRoutingError("Task objective is invalid")
    priority = row["priority"]
    revision = row["revision"]
    if type(priority) is not int or type(revision) is not int or revision < 0:
        raise CapabilityRoutingError("Task priority/revision is invalid")
    return {
        "id": row["id"],
        "flow_id": row["flow_id"],
        "parent_task_id": parent_task_id,
        "objective": objective.strip(),
        "acceptance_criteria": list(
            _string_list(row["acceptance_criteria_json"], "acceptance_criteria_json")
        ),
        "constraints": list(_string_list(row["constraints_json"], "constraints_json")),
        "required_capabilities": list(
            _string_list(row["required_capabilities_json"], "required_capabilities_json")
        ),
        "budget": _budget(row["budget_json"]),
        "priority": priority,
        "revision": revision,
    }


def task_routing_hash(row: sqlite3.Row) -> str:
    return _hash(_task_payload(row))


@dataclass(frozen=True)
class TaskRouteInput:
    task_id: str
    flow_id: str
    task_revision: int
    task_content_hash: str
    required_capabilities: tuple[str, ...]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "TaskRouteInput":
        payload = _task_payload(row)
        required = tuple(payload["required_capabilities"])
        return cls(
            task_id=row["id"],
            flow_id=row["flow_id"],
            task_revision=int(row["revision"]),
            task_content_hash=_hash(payload),
            required_capabilities=tuple(sorted(required)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "flow_id": self.flow_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "required_capabilities": list(self.required_capabilities),
        }


@dataclass(frozen=True)
class CapabilityRouteReason:
    code: CapabilityRouteReasonCode
    subject_id: str
    capability_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.code, CapabilityRouteReasonCode):
            raise CapabilityRoutingError("route reason code is invalid")
        if not isinstance(self.subject_id, str) or not self.subject_id:
            raise CapabilityRoutingError("route reason subject_id is invalid")
        values = tuple(self.capability_ids)
        if len(values) > _MAX_TASK_LIST_ITEMS or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise CapabilityRoutingError("route reason capability_ids are invalid")
        object.__setattr__(self, "capability_ids", tuple(sorted(values)))

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "subject_id": self.subject_id,
            "capability_ids": list(self.capability_ids),
        }


@dataclass(frozen=True)
class CapabilityRouteResolution:
    route_input: TaskRouteInput
    catalog_id: str
    catalog_hash: str
    routing_policy_id: str
    routing_policy_hash: str
    outcome: CapabilityRouteOutcome
    selected_adapter_id: str | None
    selected_adapter_fingerprint: str | None
    considered_adapter_ids: tuple[str, ...]
    reasons: tuple[CapabilityRouteReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.route_input, TaskRouteInput):
            raise CapabilityRoutingError("route_input is invalid")
        if not isinstance(self.outcome, CapabilityRouteOutcome):
            raise CapabilityRoutingError("route outcome is invalid")
        considered = tuple(self.considered_adapter_ids)
        if len(considered) != len(set(considered)):
            raise CapabilityRoutingError("considered adapters contain duplicates")
        object.__setattr__(self, "considered_adapter_ids", considered)
        reasons = tuple(self.reasons)
        if not all(isinstance(value, CapabilityRouteReason) for value in reasons):
            raise CapabilityRoutingError("route reasons are invalid")
        object.__setattr__(self, "reasons", reasons)
        if self.outcome is CapabilityRouteOutcome.ROUTABLE:
            if not self.selected_adapter_id or not self.selected_adapter_fingerprint:
                raise CapabilityRoutingError("ROUTABLE result requires selected adapter identity")
        elif self.selected_adapter_id is not None or self.selected_adapter_fingerprint is not None:
            raise CapabilityRoutingError("non-ROUTABLE result cannot select an adapter")

    def to_dict(self) -> dict[str, object]:
        return {
            "route_input": self.route_input.to_dict(),
            "catalog_id": self.catalog_id,
            "catalog_hash": self.catalog_hash,
            "routing_policy_id": self.routing_policy_id,
            "routing_policy_hash": self.routing_policy_hash,
            "outcome": self.outcome.value,
            "selected_adapter_id": self.selected_adapter_id,
            "selected_adapter_fingerprint": self.selected_adapter_fingerprint,
            "considered_adapter_ids": list(self.considered_adapter_ids),
            "reasons": [value.to_dict() for value in self.reasons],
        }

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())


def _result(
    route_input: TaskRouteInput,
    catalog: CapabilityCatalog,
    policy: CapabilityRoutingPolicy,
    *,
    outcome: CapabilityRouteOutcome,
    selected_adapter_id: str | None = None,
    selected_adapter_fingerprint: str | None = None,
    considered_adapter_ids: tuple[str, ...] = (),
    reasons: tuple[CapabilityRouteReason, ...] = (),
) -> CapabilityRouteResolution:
    return CapabilityRouteResolution(
        route_input=route_input,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.content_hash,
        routing_policy_id=policy.routing_policy_id,
        routing_policy_hash=policy.content_hash,
        outcome=outcome,
        selected_adapter_id=selected_adapter_id,
        selected_adapter_fingerprint=selected_adapter_fingerprint,
        considered_adapter_ids=considered_adapter_ids,
        reasons=reasons,
    )


def resolve_route_input(
    route_input: TaskRouteInput,
    catalog: CapabilityCatalog,
    policy: CapabilityRoutingPolicy,
) -> CapabilityRouteResolution:
    """Pure static authority resolution over an already-frozen canonical Task input."""

    if not isinstance(route_input, TaskRouteInput):
        raise TypeError("route_input must be a TaskRouteInput")
    if not isinstance(catalog, CapabilityCatalog):
        raise TypeError("catalog must be a CapabilityCatalog")
    if not isinstance(policy, CapabilityRoutingPolicy):
        raise TypeError("policy must be a CapabilityRoutingPolicy")
    try:
        policy.validate_against(catalog)
    except ProductionCapabilityError as exc:
        raise CapabilityRoutingError("routing policy is not valid for the supplied catalog") from exc

    required = set(route_input.required_capabilities)
    if not required:
        return _result(
            route_input,
            catalog,
            policy,
            outcome=CapabilityRouteOutcome.INVALID_TASK_CONTRACT,
            reasons=(
                CapabilityRouteReason(
                    CapabilityRouteReasonCode.NO_REQUIRED_CAPABILITY,
                    route_input.task_id,
                    (),
                ),
            ),
        )

    unknown = tuple(sorted(required - set(catalog.capability_ids)))
    if unknown:
        return _result(
            route_input,
            catalog,
            policy,
            outcome=CapabilityRouteOutcome.UNKNOWN_CAPABILITY,
            reasons=tuple(
                CapabilityRouteReason(
                    CapabilityRouteReasonCode.UNKNOWN_CAPABILITY,
                    capability_id,
                    (capability_id,),
                )
                for capability_id in unknown
            ),
        )

    disallowed = tuple(sorted(required - set(policy.allowed_capability_ids)))
    if disallowed:
        return _result(
            route_input,
            catalog,
            policy,
            outcome=CapabilityRouteOutcome.CAPABILITY_NOT_ALLOWED,
            reasons=tuple(
                CapabilityRouteReason(
                    CapabilityRouteReasonCode.CAPABILITY_NOT_ALLOWED,
                    capability_id,
                    (capability_id,),
                )
                for capability_id in disallowed
            ),
        )

    considered: list[str] = []
    reasons: list[CapabilityRouteReason] = []
    for adapter_id in policy.ordered_adapter_ids:
        adapter = catalog.adapter(adapter_id)
        considered.append(adapter_id)
        missing = tuple(sorted(required - set(adapter.capability_ids)))
        if missing:
            reasons.append(
                CapabilityRouteReason(
                    CapabilityRouteReasonCode.ADAPTER_MISSING_CAPABILITY,
                    adapter_id,
                    missing,
                )
            )
            continue
        return _result(
            route_input,
            catalog,
            policy,
            outcome=CapabilityRouteOutcome.ROUTABLE,
            selected_adapter_id=adapter.adapter_id,
            selected_adapter_fingerprint=adapter.implementation_fingerprint,
            considered_adapter_ids=tuple(considered),
            reasons=tuple(reasons),
        )

    return _result(
        route_input,
        catalog,
        policy,
        outcome=CapabilityRouteOutcome.NO_ELIGIBLE_ADAPTER,
        considered_adapter_ids=tuple(considered),
        reasons=tuple(reasons),
    )


def resolve_task_route(
    store: OriginForgeStore,
    task_id: str,
    catalog: CapabilityCatalog,
    policy: CapabilityRoutingPolicy,
) -> CapabilityRouteResolution:
    """Resolve one static authorized adapter route without executing or mutating Task state."""

    if not isinstance(store, OriginForgeStore):
        raise TypeError("store must be an OriginForgeStore")
    with store.session() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        flow = conn.execute("SELECT id FROM flows WHERE id = ?", (row["flow_id"],)).fetchone()
        if flow is None:
            raise CapabilityRoutingError("Task references a missing canonical Flow")
        route_input = TaskRouteInput.from_row(row)
    return resolve_route_input(route_input, catalog, policy)
