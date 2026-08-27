from __future__ import annotations

from typing import ClassVar

from .production_dispatch_binding_core import DispatchBindingError
from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import (
    InputResolutionBundle,
    ResolvedInputCurrentness,
)
from .production_work_order_models import WorkOrderRefType, content_hash
from .production_work_order_playtest import (
    PLAYTEST_ADAPTER_ID,
    PLAYTEST_CONTRACT_ID,
    PLAYTEST_REQUEST_ROLE,
    PLAYTEST_REQUEST_TYPE_ID,
    CooperativePlaytestDispatchValidator,
)
from .production_work_orders import ProductionWorkOrder

PLAYTEST_BINDER_ID = "binder.playtest.cooperative@1"


class CooperativePlaytestInputBinder:
    _SCHEMA: ClassVar[dict[str, object]] = {
        "request_type": PLAYTEST_REQUEST_TYPE_ID,
        "fields": "task_id, exact PLAYSCEN scenario identity/hash, inert operation",
        "execution_ids": "allocated only after durable DISPATCH_EXECUTION_STARTED",
        "adapter_invocation": False,
    }
    _DESCRIPTOR = DispatchBinderDescriptor(
        binder_id=PLAYTEST_BINDER_ID,
        binder_fingerprint=content_hash(
            {"implementation_id": "origin-forge-playtest-binder@1", "schema": _SCHEMA}
        ),
        adapter_id=PLAYTEST_ADAPTER_ID,
        dispatch_contract_id=PLAYTEST_CONTRACT_ID,
        request_type_id=PLAYTEST_REQUEST_TYPE_ID,
        request_schema_hash=content_hash(_SCHEMA),
        accepted_input_roles=(PLAYTEST_REQUEST_ROLE,),
    )

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._DESCRIPTOR

    def bind(
        self, work_order: ProductionWorkOrder, bundle: InputResolutionBundle
    ) -> object:
        if (
            work_order.work_order_id != bundle.work_order_id
            or work_order.content_hash != bundle.work_order_hash
        ):
            raise DispatchBindingError(
                "playtest WorkOrder does not match exact input-resolution bundle"
            )
        if (
            work_order.selected_adapter_id != PLAYTEST_ADAPTER_ID
            or work_order.dispatch_contract_id != PLAYTEST_CONTRACT_ID
            or len(work_order.input_refs) != 1
            or len(bundle.resolved_inputs) != 1
        ):
            raise DispatchBindingError(
                "playtest binder requires exact adapter and scenario"
            )
        resolved = bundle.resolved_inputs[0]
        ref = resolved.original_ref
        if (
            resolved.currentness is not ResolvedInputCurrentness.CURRENT
            or ref.ref_type is not WorkOrderRefType.PLAYTEST_SCENARIO
            or ref.role != PLAYTEST_REQUEST_ROLE
            or resolved.source_object_type != "PLAYTEST_SCENARIO"
            or resolved.resolution_class != "PROTECTED_PLAYTEST_SCENARIO"
            or resolved.source_id != ref.ref_id
            or resolved.source_content_hash != ref.content_hash
        ):
            raise DispatchBindingError(
                "playtest scenario is not the exact protected input"
            )
        return {
            "task_id": work_order.task_id,
            "scenario_id": ref.ref_id,
            "scenario_hash": ref.content_hash,
            **CooperativePlaytestDispatchValidator().validate(
                work_order.payload, work_order.input_refs
            ),
        }
