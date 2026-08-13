from __future__ import annotations

from .production_capability_routing import CapabilityRouteOutcome, CapabilityRoutingError
from .production_capability_store import (
    CapabilityRouteDecision,
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_planning_inspection import (
    ProductionPlanningInspectionError,
    _load_materialization_connection,
)
from .production_preparation_assembly import (
    ProductionPreparationAssemblyError,
    _assemble_preparation_planner_dependencies_from_provenance,
)
from .production_preparation_models import (
    PreparationStage,
    TaskPreparationPolicyBinding,
    TaskPreparationReceipt,
)
from .production_preparation_planner_boundary import (
    PreparationPlannerBoundaryError,
    RoutedPreparationPlannerBoundary,
)
from .production_preparation_provenance import PreparationPolicyProvenance
from .production_preparation_receipts import (
    PreparationReceiptError,
    _require_active_checkpoint,
)
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_read import ProductionWorkOrderReadError, read_dispatch_catalog
from .runtime import OriginForgeRuntime
from .service import StaleRevision


def _require_policy_receipt_relation(
    policy: TaskPreparationPolicyBinding,
    receipt: TaskPreparationReceipt,
) -> None:
    if (
        policy.content_hash != receipt.preparation_policy_hash
        or policy.project_id != receipt.project_id
        or policy.materialization_id != receipt.materialization_id
        or policy.materialization_hash != receipt.materialization_hash
        or policy.planning_input_id != receipt.planning_input_id
        or policy.planning_input_hash != receipt.planning_input_hash
    ):
        raise PreparationPlannerBoundaryError(
            "ROUTED PREP no longer binds exact durable PREPPOL authority"
        )


def resolve_same_call_routed_preparation_planner_boundary(
    runtime: OriginForgeRuntime,
    receipt: TaskPreparationReceipt,
    policy: TaskPreparationPolicyBinding,
    route: CapabilityRouteDecision,
    provenance: PreparationPolicyProvenance,
) -> RoutedPreparationPlannerBoundary:
    """Validate the normal same-call ROUTED boundary without immutable DB reads.

    The normal Phase39 path has already acquired exclusive PREP ownership,
    atomically activated the Task, published a current Phase32 route, and durably
    checkpointed that route. This resolver rechecks relational planning evidence
    through a normal SQLite snapshot so legitimate WAL bookkeeping from concurrent
    authoritative callers cannot masquerade as stale authority. It never mutates
    state and never calls the planner/model.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(receipt, TaskPreparationReceipt):
        raise TypeError("receipt must be a TaskPreparationReceipt")
    if not isinstance(policy, TaskPreparationPolicyBinding):
        raise TypeError("policy must be a TaskPreparationPolicyBinding")
    if not isinstance(route, CapabilityRouteDecision):
        raise TypeError("route must be a CapabilityRouteDecision")
    if not isinstance(provenance, PreparationPolicyProvenance):
        raise TypeError("provenance must be a PreparationPolicyProvenance")

    try:
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.ROUTED,
            expected_revision=receipt.revision,
        )
        _require_policy_receipt_relation(policy, receipt)
        if provenance.policy != policy:
            raise PreparationPlannerBoundaryError(
                "pre-acquisition PREPPOL provenance does not match exact current policy"
            )

        with runtime.store.session() as conn:
            conn.execute("BEGIN")
            project = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?",
                (str(runtime.project_root),),
            ).fetchone()
            if project is None or project["id"] != policy.project_id:
                raise PreparationPlannerBoundaryError(
                    "PREPPOL project is not current authoritative project"
                )
            materialization = _load_materialization_connection(
                conn,
                project["id"],
                policy.materialization_id,
            )
            if (
                materialization != provenance.materialization
                or materialization.content_hash != policy.materialization_hash
                or materialization.planning_input_id != policy.planning_input_id
                or materialization.planning_input_hash != policy.planning_input_hash
            ):
                raise PreparationPlannerBoundaryError(
                    "planning materialization changed after PREP acquisition"
                )

        current_route = ProductionCapabilityStore(runtime).require_current_route(
            route.route_decision_id
        )
        if (
            current_route != route
            or route.route_decision_id != receipt.route_decision_id
            or route.content_hash != receipt.route_decision_hash
        ):
            raise PreparationPlannerBoundaryError(
                "same-call Phase32 route changed after ROUTED checkpoint"
            )

        dispatch_catalog = read_dispatch_catalog(
            runtime,
            policy.dispatch_contract_catalog_id,
            build_builtin_dispatch_validator_registry(),
        )
        if (
            dispatch_catalog != provenance.dispatch_contract_catalog
            or dispatch_catalog.content_hash != policy.dispatch_contract_catalog_hash
        ):
            raise PreparationPlannerBoundaryError(
                "dispatch catalog changed after PREPPOL validation"
            )

        dependencies = _assemble_preparation_planner_dependencies_from_provenance(
            runtime,
            policy,
            provenance,
        )
        resolution = route.resolution
        owner = dependencies.owner
        if (
            resolution.outcome is not CapabilityRouteOutcome.ROUTABLE
            or resolution.catalog_id != policy.capability_catalog_id
            or resolution.catalog_hash != policy.capability_catalog_hash
            or resolution.routing_policy_id != policy.capability_routing_policy_id
            or resolution.routing_policy_hash != policy.capability_routing_policy_hash
            or resolution.route_input.task_id != receipt.task_id
            or resolution.route_input.task_revision != receipt.ready_task_revision
            or resolution.route_input.task_content_hash != receipt.ready_task_hash
            or resolution.selected_adapter_id != owner.supported_adapter_id
            or resolution.selected_adapter_fingerprint
            != owner.supported_adapter_fingerprint
        ):
            raise PreparationPlannerBoundaryError(
                "same-call Phase32 authority is outside exact preparation-owner relation"
            )
        contract = dispatch_catalog.contract_for_adapter(
            resolution.selected_adapter_id
        )
        if (
            contract.contract_id != owner.supported_dispatch_contract_id
            or contract.content_hash != owner.supported_dispatch_contract_hash
            or contract.adapter_fingerprint != owner.supported_adapter_fingerprint
            or contract.max_input_refs != 0
        ):
            raise PreparationPlannerBoundaryError(
                "current dispatch contract exceeds exact v1 preparation-owner authority"
            )
    except PreparationPlannerBoundaryError:
        raise
    except (
        PreparationReceiptError,
        ProductionPlanningInspectionError,
        ProductionCapabilityStoreError,
        ProductionPreparationAssemblyError,
        ProductionWorkOrderReadError,
        CapabilityRoutingError,
        StaleRevision,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise PreparationPlannerBoundaryError(
            "same-call ROUTED planner authority could not be reconstructed exactly"
        ) from exc

    return RoutedPreparationPlannerBoundary(
        receipt=receipt,
        policy=policy,
        route=route,
        dependencies=dependencies,
        dispatch_catalog=dispatch_catalog,
    )
