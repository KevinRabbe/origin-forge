from __future__ import annotations

from .ids import IdKind, validate_id
from .production_capability_read import (
    ProductionCapabilityReadError,
    _category_dir,
    inspect_task_route,
    read_capability_route,
)
from .production_capability_routing import (
    CapabilityRouteResolution,
    CapabilityRoutingError,
)
from .production_capability_store import (
    _MAX_OBJECTS_PER_CATEGORY,
    CapabilityRouteDecision,
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    TaskPreparationReceipt,
)
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_receipts import (
    PreparationReceiptError,
    checkpoint_preparation_routed,
    read_preparation_receipt,
)
from .production_preparation_recovery import (
    PreparationRecoveryState,
    inspect_preparation_recovery_readonly,
)
from .runtime import OriginForgeRuntime


_MAX_ROUTE_OBJECTS = _MAX_OBJECTS_PER_CATEGORY


class PreparationRouteRecoveryError(RuntimeError):
    pass


def _bounded_route_ids_readonly(runtime: OriginForgeRuntime) -> tuple[str, ...]:
    """Enumerate the existing Phase-32 route directory without creating storage."""

    try:
        directory = _category_dir(runtime, "routes", required=False)
    except ProductionCapabilityReadError as exc:
        raise PreparationRouteRecoveryError(str(exc)) from exc
    if directory is None:
        return ()

    route_ids: list[str] = []
    try:
        for entry in directory.iterdir():
            if len(route_ids) >= _MAX_ROUTE_OBJECTS:
                raise PreparationRouteRecoveryError(
                    "Phase-32 route object-count limit exceeded"
                )
            if entry.is_symlink() or not entry.is_file():
                raise PreparationRouteRecoveryError(
                    "Phase-32 route directory contains invalid evidence entry"
                )
            name = entry.name
            if not name.endswith(".json"):
                raise PreparationRouteRecoveryError(
                    "Phase-32 route directory contains non-route evidence entry"
                )
            route_id = name[:-5]
            if not validate_id(route_id, IdKind.CAPABILITY_ROUTE_DECISION):
                raise PreparationRouteRecoveryError(
                    "Phase-32 route directory contains invalid route identity"
                )
            resolved = entry.resolve(strict=True)
            if resolved != entry or resolved.parent != directory:
                raise PreparationRouteRecoveryError(
                    "Phase-32 route evidence path is aliased or escaped"
                )
            route_ids.append(route_id)
    except PreparationRouteRecoveryError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise PreparationRouteRecoveryError(
            "Phase-32 route directory could not be enumerated safely"
        ) from exc
    return tuple(sorted(route_ids))


def _equivalent_routes_readonly(
    runtime: OriginForgeRuntime,
    expected: CapabilityRouteResolution,
) -> tuple[CapabilityRouteDecision, ...]:
    if not isinstance(expected, CapabilityRouteResolution):
        raise TypeError("expected must be a CapabilityRouteResolution")
    equivalent: list[CapabilityRouteDecision] = []
    expected_payload = expected.to_dict()
    for route_id in _bounded_route_ids_readonly(runtime):
        try:
            route = read_capability_route(runtime, route_id)
        except ProductionCapabilityReadError as exc:
            raise PreparationRouteRecoveryError(
                f"Phase-32 route {route_id} is malformed or invalid"
            ) from exc
        if route.resolution.to_dict() == expected_payload:
            equivalent.append(route)
    return tuple(sorted(equivalent, key=lambda route: route.route_decision_id))


def recover_and_checkpoint_preparation_route(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
) -> TaskPreparationReceipt:
    """Recover or publish one exact Phase-32 route for an ACTIVATED PREP.

    Existing protected route evidence is enumerated under a hard object bound and
    every object is validated. Semantically identical current resolutions collapse
    deterministically by route ID. A fresh immutable route is published only when
    no exact equivalent exists. The existing Phase-39 checkpoint primitive remains
    authoritative for ACTIVATED -> ROUTED mutation/currentness.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if type(expected_revision) is not int or expected_revision < 0:
        raise PreparationRouteRecoveryError(
            "expected_revision must be a non-negative integer"
        )

    recovery = inspect_preparation_recovery_readonly(runtime, preparation_id)
    if recovery.state is not PreparationRecoveryState.RESUMABLE_ACTIVATED:
        raise PreparationRouteRecoveryError(
            f"PREP is {recovery.state.value}, not RESUMABLE_ACTIVATED"
        )

    try:
        receipt = read_preparation_receipt(runtime, preparation_id)
    except (PreparationReceiptError, KeyError, TypeError, ValueError) as exc:
        raise PreparationRouteRecoveryError("PREP receipt is unavailable") from exc
    if (
        receipt.status is not PreparationStatus.ACTIVE
        or receipt.stage is not PreparationStage.ACTIVATED
        or receipt.revision != expected_revision
        or receipt.ready_task_revision is None
        or receipt.ready_task_hash is None
    ):
        raise PreparationRouteRecoveryError(
            "PREP changed after immutable recovery classification"
        )

    try:
        policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
    except (ProductionPreparationPolicyStoreError, KeyError, TypeError, ValueError) as exc:
        raise PreparationRouteRecoveryError("PREPPOL authority is unavailable") from exc
    if (
        policy.content_hash != receipt.preparation_policy_hash
        or policy.project_id != receipt.project_id
        or policy.materialization_id != receipt.materialization_id
        or policy.materialization_hash != receipt.materialization_hash
    ):
        raise PreparationRouteRecoveryError(
            "PREP no longer binds exact PREPPOL authority"
        )

    try:
        expected = inspect_task_route(
            runtime,
            receipt.task_id,
            policy.capability_catalog_id,
            policy.capability_routing_policy_id,
        )
    except (
        ProductionCapabilityReadError,
        CapabilityRoutingError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise PreparationRouteRecoveryError(
            "current Phase-32 route resolution cannot be reconstructed"
        ) from exc
    route_input = expected.route_input
    if (
        route_input.task_id != receipt.task_id
        or route_input.task_revision != receipt.ready_task_revision
        or route_input.task_content_hash != receipt.ready_task_hash
        or expected.catalog_id != policy.capability_catalog_id
        or expected.catalog_hash != policy.capability_catalog_hash
        or expected.routing_policy_id != policy.capability_routing_policy_id
        or expected.routing_policy_hash != policy.capability_routing_policy_hash
    ):
        raise PreparationRouteRecoveryError(
            "current Phase-32 resolution does not exactly continue PREP authority"
        )

    equivalent = _equivalent_routes_readonly(runtime, expected)
    if equivalent:
        route = equivalent[0]
    else:
        try:
            route = ProductionCapabilityStore(runtime).resolve_and_publish(
                receipt.task_id,
                policy.capability_catalog_id,
                policy.capability_routing_policy_id,
            )
        except ProductionCapabilityStoreError as exc:
            raise PreparationRouteRecoveryError(
                "fresh Phase-32 route publication failed"
            ) from exc
        if route.resolution.to_dict() != expected.to_dict():
            raise PreparationRouteRecoveryError(
                "Task changed while fresh Phase-32 route was being published"
            )

    try:
        return checkpoint_preparation_routed(
            runtime,
            preparation_id,
            expected_revision,
            route.route_decision_id,
        )
    except (PreparationReceiptError, KeyError, TypeError, ValueError) as exc:
        raise PreparationRouteRecoveryError(
            "Phase-32 route could not be checkpointed into exact PREP authority"
        ) from exc
