from __future__ import annotations

from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import InputResolutionBundle
from .production_work_order_models import canonical_bytes, content_hash
from .production_work_order_simulation import (
    DeterministicSimulationDispatchValidator,
    SIMULATION_ADAPTER_ID,
    SIMULATION_CONTRACT_ID,
)
from .production_work_order_validators import DispatchValidatorError
from .production_work_orders import ProductionWorkOrder


class SimulationDispatchBindingError(ValueError):
    pass


class DeterministicSimulationInputBinder:
    """Reconstruct one inert `SimulationService.execute` request without invoking it."""

    _REQUEST_TYPE_ID = "SimulationService.execute@production-v1"
    _REQUEST_SCHEMA = {
        "request_type": _REQUEST_TYPE_ID,
        "fields": {
            "task_id": "TASK ID",
            "engine_id": "fixed code-owned engine identity",
            "engine_version": "fixed code-owned engine version",
            "seed": "bounded non-negative integer",
            "replicates": "bounded positive integer",
            "max_steps": "bounded positive integer",
            "stall_steps": "bounded positive integer",
            "initial_state": "canonical bounded state object",
            "rules": "canonical bounded declarative rule list",
            "invariants": "canonical bounded invariant list",
        },
        "excluded_execution_ids": ["spec_id", "session_id", "workspace_id"],
        "input_refs": "none",
        "adapter_invocation": False,
    }
    _SCHEMA_HASH = content_hash(_REQUEST_SCHEMA)
    _FINGERPRINT = content_hash(
        {
            "implementation_id": "origin-forge-deterministic-simulation-dispatch-binder@1",
            "adapter_id": SIMULATION_ADAPTER_ID,
            "dispatch_contract_id": SIMULATION_CONTRACT_ID,
            "request_schema": _REQUEST_SCHEMA,
            "mapping": {
                "task_id": "WorkOrder.task_id",
                "engine_id": "SimulationSpecTemplate.engine_id",
                "engine_version": "SimulationSpecTemplate.engine_version",
                "seed": "validated WorkOrder payload",
                "replicates": "validated WorkOrder payload",
                "max_steps": "validated WorkOrder payload",
                "stall_steps": "validated WorkOrder payload",
                "initial_state": "validated canonical nested JSON",
                "rules": "validated canonical nested JSON",
                "invariants": "validated canonical nested JSON",
            },
            "concrete_execution_ids": "allocated only after durable DISPEXEC STARTED",
        }
    )
    _DESCRIPTOR = DispatchBinderDescriptor(
        binder_id="binder.simulation.deterministic@1",
        binder_fingerprint=_FINGERPRINT,
        adapter_id=SIMULATION_ADAPTER_ID,
        dispatch_contract_id=SIMULATION_CONTRACT_ID,
        request_type_id=_REQUEST_TYPE_ID,
        request_schema_hash=_SCHEMA_HASH,
        accepted_input_roles=(),
    )

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._DESCRIPTOR

    def bind(
        self,
        work_order: ProductionWorkOrder,
        bundle: InputResolutionBundle,
    ) -> object:
        if not isinstance(work_order, ProductionWorkOrder):
            raise TypeError("work_order must be a ProductionWorkOrder")
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        if (
            work_order.work_order_id != bundle.work_order_id
            or work_order.content_hash != bundle.work_order_hash
        ):
            raise SimulationDispatchBindingError(
                "simulation binder WorkOrder does not match exact input-resolution bundle"
            )
        if (
            work_order.selected_adapter_id != self.descriptor.adapter_id
            or work_order.dispatch_contract_id != self.descriptor.dispatch_contract_id
        ):
            raise SimulationDispatchBindingError(
                "simulation binder does not match WorkOrder adapter/contract"
            )
        if work_order.input_refs or bundle.resolved_inputs:
            raise SimulationDispatchBindingError(
                "deterministic simulation binder accepts no external input refs"
            )

        try:
            template = DeterministicSimulationDispatchValidator().template(
                work_order.payload,
                (),
            )
        except (DispatchValidatorError, TypeError, ValueError) as exc:
            raise SimulationDispatchBindingError(
                "simulation WorkOrder payload no longer reconstructs exact semantic template"
            ) from exc

        projection = {
            "task_id": work_order.task_id,
            **template.to_dict(),
        }
        canonical_bytes(projection)
        return projection
