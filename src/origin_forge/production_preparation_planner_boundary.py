from __future__ import annotations

from dataclasses import dataclass

from .production_capability_routing import (
    CapabilityRouteOutcome,
    CapabilityRoutingError,
    TaskRouteInput,
)
from .production_capability_store import (
    CapabilityRouteDecision,
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_preparation_assembly import (
    PreparationPlannerDependencies,
    ProductionPreparationAssemblyError,
    assemble_preparation_planner_dependencies,
)
from .production_preparation_input_authority import (
    PreparationInputAuthorityError,
    planner_allowed_input_refs,
)
from .production_preparation_models import (
    PreparationStage,
    TaskPreparationPolicyBinding,
    TaskPreparationReceipt,
)
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_provenance import (
    ProductionPreparationProvenanceError,
    resolve_preparation_policy_provenance,
)
from .production_preparation_receipts import (
    PreparationReceiptError,
    _require_active_checkpoint,
    read_preparation_receipt,
)
from .production_read_guard import ProductionReadGuardError
from .production_work_order_models import DispatchContractCatalog, WorkOrderInputRef
from .runtime import OriginForgeRuntime
from .service import StaleRevision
from .state import TaskStatus


class PreparationPlannerBoundaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoutedPreparationPlannerBoundary:
    receipt: TaskPreparationReceipt
    policy: TaskPreparationPolicyBinding
    route: CapabilityRouteDecision
    dependencies: PreparationPlannerDependencies
    dispatch_catalog: DispatchContractCatalog
    allowed_input_refs: tuple[WorkOrderInputRef, ...] = ()


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


def resolve_routed_preparation_planner_boundary(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
) -> RoutedPreparationPlannerBoundary:
    """Reconstruct exact ROUTED planner authority without mutation or model use.

    This is the shared Phase-39/41 pre-planner boundary. It may assemble lazy
    model/runtime dependencies from protected configuration, but it never marks
    PLANNER_STARTED, starts a Run, loads a model, acquires a resource lease,
    publishes WorkOrder evidence, or calls the WorkOrder planner.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if type(expected_revision) is not int or expected_revision < 0:
        raise PreparationPlannerBoundaryError(
            "expected_revision must be a non-negative integer"
        )

    try:
        receipt = read_preparation_receipt(runtime, preparation_id)
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.ROUTED,
            expected_revision=expected_revision,
        )
        policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
        _require_policy_receipt_relation(policy, receipt)

        task = runtime.get_task(receipt.task_id)
        task_status = TaskStatus(task["status"])
        task_input = TaskRouteInput.from_row(task)
        if (
            task_status is not TaskStatus.READY
            or receipt.ready_task_revision is None
            or receipt.ready_task_hash is None
            or task_input.task_revision != receipt.ready_task_revision
            or task_input.task_content_hash != receipt.ready_task_hash
        ):
            raise PreparationPlannerBoundaryError(
                "ROUTED PREP no longer binds exact canonical READY Task authority"
            )

        if receipt.route_decision_id is None or receipt.route_decision_hash is None:
            raise PreparationPlannerBoundaryError(
                "ROUTED PREP lacks exact Phase-32 route checkpoint"
            )
        route = ProductionCapabilityStore(runtime).require_current_route(
            receipt.route_decision_id
        )
        resolution = route.resolution
        if (
            route.content_hash != receipt.route_decision_hash
            or resolution.outcome is not CapabilityRouteOutcome.ROUTABLE
            or resolution.catalog_id != policy.capability_catalog_id
            or resolution.catalog_hash != policy.capability_catalog_hash
            or resolution.routing_policy_id != policy.capability_routing_policy_id
            or resolution.routing_policy_hash != policy.capability_routing_policy_hash
            or resolution.route_input.task_id != receipt.task_id
            or resolution.route_input.task_revision != receipt.ready_task_revision
            or resolution.route_input.task_content_hash != receipt.ready_task_hash
            or resolution.route_input.to_dict() != task_input.to_dict()
        ):
            raise PreparationPlannerBoundaryError(
                "ROUTED PREP Phase-32 authority is stale or outside exact PREPPOL relation"
            )

        dependencies = assemble_preparation_planner_dependencies(runtime, policy)
        owner = dependencies.owner
        if (
            resolution.selected_adapter_id != owner.supported_adapter_id
            or resolution.selected_adapter_fingerprint
            != owner.supported_adapter_fingerprint
        ):
            raise PreparationPlannerBoundaryError(
                "current Phase-32 route is unsupported by code-owned preparation owner"
            )

        provenance = resolve_preparation_policy_provenance(runtime, policy)
        dispatch_catalog = provenance.dispatch_contract_catalog
        contract = dispatch_catalog.contract_for_adapter(
            resolution.selected_adapter_id
        )
        if (
            dispatch_catalog.dispatch_catalog_id
            != policy.dispatch_contract_catalog_id
            or dispatch_catalog.content_hash != policy.dispatch_contract_catalog_hash
            or contract.contract_id != owner.supported_dispatch_contract_id
            or contract.content_hash != owner.supported_dispatch_contract_hash
            or contract.adapter_fingerprint != owner.supported_adapter_fingerprint
        ):
            raise PreparationPlannerBoundaryError(
                "current dispatch contract exceeds exact v1 preparation-owner authority"
            )
        allowed_input_refs = planner_allowed_input_refs(
            provenance.planning_input,
            owner.owner_id,
            contract,
        )
    except PreparationPlannerBoundaryError:
        raise
    except (
        PreparationReceiptError,
        ProductionPreparationPolicyStoreError,
        ProductionCapabilityStoreError,
        ProductionPreparationAssemblyError,
        ProductionPreparationProvenanceError,
        PreparationInputAuthorityError,
        ProductionReadGuardError,
        CapabilityRoutingError,
        StaleRevision,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise PreparationPlannerBoundaryError(
            "ROUTED planner authority could not be reconstructed exactly"
        ) from exc

    return RoutedPreparationPlannerBoundary(
        receipt=receipt,
        policy=policy,
        route=route,
        dependencies=dependencies,
        dispatch_catalog=dispatch_catalog,
        allowed_input_refs=allowed_input_refs,
    )