from __future__ import annotations

from typing import ClassVar

from .production_dispatch_binding_core import DispatchBindingError
from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import (
    InputResolutionBundle,
    ResolvedInputCurrentness,
)
from .production_work_order_models import WorkOrderRefType, content_hash
from .production_work_order_runtime import (
    RUNTIME_ADAPTER_ID,
    RUNTIME_CONTRACT_ID,
    RUNTIME_REQUEST_ROLE,
    RUNTIME_REQUEST_TYPE_ID,
    RuntimeObservationDispatchValidator,
)
from .production_work_orders import ProductionWorkOrder

RUNTIME_BINDER_ID = "binder.runtime.observe@1"


class RuntimeObservationInputBinder:
    """Freeze one current protected runtime request without allocating execution state."""

    _SCHEMA: ClassVar[dict[str, object]] = {
        "request_type": RUNTIME_REQUEST_TYPE_ID,
        "fields": "task_id, exact OBS request identity/hash, inert operation",
        "execution_ids": "allocated only after durable DISPATCH_EXECUTION_STARTED",
        "adapter_invocation": False,
    }
    _DESCRIPTOR = DispatchBinderDescriptor(
        binder_id=RUNTIME_BINDER_ID,
        binder_fingerprint=content_hash(
            {"implementation_id": "origin-forge-runtime-observation-binder@1", "schema": _SCHEMA}
        ),
        adapter_id=RUNTIME_ADAPTER_ID,
        dispatch_contract_id=RUNTIME_CONTRACT_ID,
        request_type_id=RUNTIME_REQUEST_TYPE_ID,
        request_schema_hash=content_hash(_SCHEMA),
        accepted_input_roles=(RUNTIME_REQUEST_ROLE,),
    )

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._DESCRIPTOR

    def bind(self, work_order: ProductionWorkOrder, bundle: InputResolutionBundle) -> object:
        if not isinstance(work_order, ProductionWorkOrder) or not isinstance(bundle, InputResolutionBundle):
            raise TypeError("work_order and bundle must be canonical production objects")
        if work_order.work_order_id != bundle.work_order_id or work_order.content_hash != bundle.work_order_hash:
            raise DispatchBindingError("runtime WorkOrder does not match exact input-resolution bundle")
        if work_order.selected_adapter_id != RUNTIME_ADAPTER_ID or work_order.dispatch_contract_id != RUNTIME_CONTRACT_ID:
            raise DispatchBindingError("runtime binder does not match WorkOrder adapter/contract")
        if len(work_order.input_refs) != 1 or len(bundle.resolved_inputs) != 1:
            raise DispatchBindingError("runtime binder requires exactly one protected request")
        resolved = bundle.resolved_inputs[0]
        ref = resolved.original_ref
        if resolved.currentness is not ResolvedInputCurrentness.CURRENT:
            raise DispatchBindingError("runtime observation request is not current")
        if (
            ref.ref_type is not WorkOrderRefType.RUNTIME_OBSERVATION_REQUEST
            or ref.role != RUNTIME_REQUEST_ROLE
            or resolved.source_object_type != "RUNTIME_OBSERVATION_REQUEST"
            or resolved.resolution_class != "PROTECTED_RUNTIME_OBSERVATION_REQUEST"
            or resolved.source_id != ref.ref_id
            or resolved.source_content_hash != ref.content_hash
        ):
            raise DispatchBindingError("runtime request is not the exact protected input")
        payload = RuntimeObservationDispatchValidator().validate(work_order.payload, work_order.input_refs)
        return {"task_id": work_order.task_id, "request_id": ref.ref_id, "request_hash": ref.content_hash, **payload}
