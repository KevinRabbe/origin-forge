from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_capability_routing import CapabilityRouteOutcome
from .production_capability_store import ProductionCapabilityStore, ProductionCapabilityStoreError
from .production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from .production_preparation_assembly import (
    ProductionPreparationAssemblyError,
    assemble_preparation_planner_dependencies,
)
from .production_preparation_models import PreparationStage, TaskPreparationReceipt
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
    acquire_preparation_receipt,
    checkpoint_preparation_activated,
    checkpoint_preparation_planner_returned,
    checkpoint_preparation_planner_started,
    checkpoint_preparation_routed,
    fail_preparation_before_planner,
    read_preparation_receipt,
)
from .production_preparation_selection import (
    PreparationSelectionStatus,
    select_preparation_candidate,
)
from .production_task_activation import TaskActivationError, activate_dependency_ready_task
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_planner import (
    BoundedProductionWorkOrderPlanner,
    ProductionWorkOrderPlannerError,
    WorkOrderPlannerResult,
)
from .runtime import OriginForgeRuntime


class PreparationTickStatus(StrEnum):
    NO_ELIGIBLE_TASK = "NO_ELIGIBLE_TASK"
    INVALID_POLICY = "INVALID_POLICY"
    INVALID_ADMISSION = "INVALID_ADMISSION"
    PREPARATION_NOT_ACQUIRED = "PREPARATION_NOT_ACQUIRED"
    FAILED_PRE_PLANNER = "FAILED_PRE_PLANNER"
    PLANNER_RECOVERY_REQUIRED = "PLANNER_RECOVERY_REQUIRED"
    PLANNER_RETURNED = "PLANNER_RETURNED"


@dataclass(frozen=True)
class PreparationTickResult:
    status: PreparationTickStatus
    preparation_policy_id: str
    preparation_id: str | None
    task_id: str | None
    receipt: TaskPreparationReceipt | None
    planner_result: WorkOrderPlannerResult | None
    detail: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "preparation_policy_id": self.preparation_policy_id,
            "preparation_id": self.preparation_id,
            "task_id": self.task_id,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "planner_result": None
            if self.planner_result is None
            else {
                "run_id": self.planner_result.run_id,
                "route_decision_id": self.planner_result.route_decision_id,
                "route_decision_hash": self.planner_result.route_decision_hash,
                "work_order_id": self.planner_result.work_order.work_order_id,
                "work_order_hash": self.planner_result.work_order.content_hash,
                "verification_id": self.planner_result.verification_id,
            },
            "detail": self.detail,
            "authority": "single-preparation-tick-through-planner-return",
        }


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:4096]


def _preplanner_failure(
    runtime: OriginForgeRuntime,
    policy_id: str,
    receipt: TaskPreparationReceipt,
    exc: BaseException,
) -> PreparationTickResult:
    reason = _detail(exc)
    try:
        failed = fail_preparation_before_planner(
            runtime,
            receipt.preparation_id,
            receipt.revision,
            receipt.stage,
            reason,
        )
    except Exception as terminalize_exc:
        # A lost/uncertain checkpoint must never be overwritten by optimistic
        # failure repair. Surface the current durable state if it can be read.
        try:
            current = read_preparation_receipt(runtime, receipt.preparation_id)
        except Exception:
            current = receipt
        return PreparationTickResult(
            status=PreparationTickStatus.PLANNER_RECOVERY_REQUIRED,
            preparation_policy_id=policy_id,
            preparation_id=receipt.preparation_id,
            task_id=receipt.task_id,
            receipt=current,
            planner_result=None,
            detail=f"pre-planner failure could not be terminalized safely: {_detail(terminalize_exc)}",
        )
    return PreparationTickResult(
        status=PreparationTickStatus.FAILED_PRE_PLANNER,
        preparation_policy_id=policy_id,
        preparation_id=failed.preparation_id,
        task_id=failed.task_id,
        receipt=failed,
        planner_result=None,
        detail=reason,
    )


def prepare_materialization_tick(
    runtime: OriginForgeRuntime,
    preparation_policy_id: str,
) -> PreparationTickResult:
    """Perform at most one governed Phase-39 preparation attempt and stop.

    Caller authority is limited to one persisted PREPPOL ID. This function never
    accepts a Task, route/catalog/policy, adapter, dispatch contract, model role,
    profile/provider, WorkOrder payload, binder, sandbox, endpoint, or fallback
    Task. Once one candidate is selected, every race/failure stops this call.

    Successful 39D completion stops at durable PLANNER_RETURNED. It does not
    publish/audit the WorkOrder, construct Phase-34 authority, acquire a dispatch
    claim, or execute production work; those remain later independently gated
    slices.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(preparation_policy_id, str):
        raise TypeError("preparation_policy_id must be a string")

    try:
        policy = read_preparation_policy(runtime, preparation_policy_id)
    except (ProductionPreparationPolicyStoreError, TypeError, ValueError) as exc:
        return PreparationTickResult(
            PreparationTickStatus.INVALID_POLICY,
            preparation_policy_id,
            None,
            None,
            None,
            None,
            _detail(exc),
        )

    admission = inspect_materialization_preparation_eligibility_readonly(
        runtime,
        policy,
    )
    selection = select_preparation_candidate(admission)
    if selection.status is PreparationSelectionStatus.NO_ELIGIBLE_TASK:
        return PreparationTickResult(
            PreparationTickStatus.NO_ELIGIBLE_TASK,
            preparation_policy_id,
            None,
            None,
            None,
            None,
            None,
        )
    if (
        admission.status is not PreparationAdmissionStatus.COMPLETE
        or selection.status is not PreparationSelectionStatus.ONE_SELECTED
        or selection.candidate is None
    ):
        return PreparationTickResult(
            PreparationTickStatus.INVALID_ADMISSION,
            preparation_policy_id,
            None,
            None,
            None,
            None,
            admission.detail or selection.status.value,
        )
    candidate = selection.candidate

    try:
        receipt = acquire_preparation_receipt(runtime, policy, candidate)
    except Exception as exc:
        return PreparationTickResult(
            PreparationTickStatus.PREPARATION_NOT_ACQUIRED,
            preparation_policy_id,
            None,
            candidate.task_id,
            None,
            None,
            _detail(exc),
        )

    try:
        activation = activate_dependency_ready_task(
            runtime,
            candidate.task_id,
            candidate.task_revision,
        )
        receipt = checkpoint_preparation_activated(
            runtime,
            receipt.preparation_id,
            receipt.revision,
            activation,
        )

        capability_store = ProductionCapabilityStore(runtime)
        route = capability_store.resolve_and_publish(
            candidate.task_id,
            policy.capability_catalog_id,
            policy.capability_routing_policy_id,
        )
        receipt = checkpoint_preparation_routed(
            runtime,
            receipt.preparation_id,
            receipt.revision,
            route.route_decision_id,
        )

        dependencies = assemble_preparation_planner_dependencies(runtime, policy)
        owner = dependencies.owner
        resolution = route.resolution
        if (
            resolution.outcome is not CapabilityRouteOutcome.ROUTABLE
            or resolution.selected_adapter_id != owner.supported_adapter_id
            or resolution.selected_adapter_fingerprint
            != owner.supported_adapter_fingerprint
        ):
            raise PreparationReceiptError(
                "current Phase-32 route is unsupported by code-owned preparation owner"
            )
        try:
            provenance = resolve_preparation_policy_provenance(runtime, policy)
            contract = provenance.dispatch_contract_catalog.contract_for_adapter(
                resolution.selected_adapter_id
            )
        except (
            ProductionPreparationProvenanceError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise PreparationReceiptError(
                "current dispatch contract is unavailable for selected route"
            ) from exc
        if (
            contract.contract_id != owner.supported_dispatch_contract_id
            or contract.content_hash != owner.supported_dispatch_contract_hash
            or contract.adapter_fingerprint != owner.supported_adapter_fingerprint
            or contract.max_input_refs != 0
        ):
            raise PreparationReceiptError(
                "current dispatch contract exceeds v1 preparation owner authority"
            )

        receipt = checkpoint_preparation_planner_started(
            runtime,
            receipt.preparation_id,
            receipt.revision,
            dependencies.plan.plan_hash,
        )
    except BaseException as exc:
        # Before PLANNER_STARTED every failure is known to have occurred before
        # the model boundary. BaseException is safe to terminalize only while
        # the durable receipt still proves a pre-planner stage.
        if receipt.stage in (
            PreparationStage.CLAIMED,
            PreparationStage.ACTIVATED,
            PreparationStage.ROUTED,
        ):
            if isinstance(exc, Exception):
                return _preplanner_failure(
                    runtime,
                    preparation_policy_id,
                    receipt,
                    exc,
                )
            try:
                fail_preparation_before_planner(
                    runtime,
                    receipt.preparation_id,
                    receipt.revision,
                    receipt.stage,
                    _detail(exc),
                )
            except Exception:
                pass
        raise

    # Durable PLANNER_STARTED now exists. From this point forward this function
    # intentionally has no automatic failure/retry/replay transition.
    try:
        planner = BoundedProductionWorkOrderPlanner(
            runtime,
            ProductionCapabilityStore(runtime),
            provenance.dispatch_contract_catalog,
            build_builtin_dispatch_validator_registry(),
            dependencies.model,
        )
        planner_result = planner.propose(
            receipt.route_decision_id,
            allowed_input_refs=(),
        )
        returned = checkpoint_preparation_planner_returned(
            runtime,
            receipt.preparation_id,
            receipt.revision,
            planner_result,
        )
    except Exception as exc:
        try:
            current = read_preparation_receipt(runtime, receipt.preparation_id)
        except Exception:
            current = receipt
        return PreparationTickResult(
            PreparationTickStatus.PLANNER_RECOVERY_REQUIRED,
            preparation_policy_id,
            receipt.preparation_id,
            receipt.task_id,
            current,
            None,
            _detail(exc),
        )

    return PreparationTickResult(
        PreparationTickStatus.PLANNER_RETURNED,
        preparation_policy_id,
        returned.preparation_id,
        returned.task_id,
        returned,
        planner_result,
        None,
    )
