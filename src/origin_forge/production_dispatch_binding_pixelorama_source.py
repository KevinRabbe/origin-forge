from __future__ import annotations

from .production_dispatch_binding_core import DispatchBindingError
from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import (
    InputResolutionBundle,
    ResolvedInputCurrentness,
)
from .production_pixelorama_source_request import (
    PixeloramaSourceInvocationRequest,
    PixeloramaSourceRequestError,
    decode_pixelorama_source_request,
)
from .production_work_order_models import WorkOrderRefType, content_hash
from .production_work_orders import ProductionWorkOrder
from .production_work_order_pixelorama import (
    PIXELORAMA_SOURCE_ADAPTER_ID,
    PIXELORAMA_SOURCE_CONTRACT_ID,
    PIXELORAMA_SOURCE_REQUEST_TYPE_ID,
    PIXELORAMA_SOURCE_ROLE,
)


PIXELORAMA_SOURCE_BINDER_ID = "binder.pixelorama.source-create@1"
_REQUEST_SCHEMA = {
    "request_type": PIXELORAMA_SOURCE_REQUEST_TYPE_ID,
    "fields": {
        "task_id": "TASK ID",
        "accepted_design_projection": "current resolver-owned projection",
        "operation": "CREATE_SPRITE_PROJECT",
        "sprite_spec": "canonical SpriteProjectSpec",
        "export_specs": "canonical ExportSpec list",
        "budget": "canonical BridgeBudget",
    },
    "injected_later": [
        "PlanningInput bridge",
        "trusted Pixelorama profile",
        "PXOP operation identity",
        "MEDIA workspace identity",
    ],
    "pixelorama_invocation": False,
}
_REQUEST_SCHEMA_HASH = content_hash(_REQUEST_SCHEMA)
_BINDER_FINGERPRINT = content_hash(
    {
        "implementation_id": "origin-forge-pixelorama-source-create-dispatch-binder@1",
        "adapter_id": PIXELORAMA_SOURCE_ADAPTER_ID,
        "dispatch_contract_id": PIXELORAMA_SOURCE_CONTRACT_ID,
        "request_schema": _REQUEST_SCHEMA,
        "accepted_design_currentness": "resolver projection must be CURRENT",
    }
)
_DESCRIPTOR = DispatchBinderDescriptor(
    binder_id=PIXELORAMA_SOURCE_BINDER_ID,
    binder_fingerprint=_BINDER_FINGERPRINT,
    adapter_id=PIXELORAMA_SOURCE_ADAPTER_ID,
    dispatch_contract_id=PIXELORAMA_SOURCE_CONTRACT_ID,
    request_type_id=PIXELORAMA_SOURCE_REQUEST_TYPE_ID,
    request_schema_hash=_REQUEST_SCHEMA_HASH,
    accepted_input_roles=(PIXELORAMA_SOURCE_ROLE,),
)


class PixeloramaSourceCreationInputBinder:
    """Reconstruct source/animation input authority without invoking or mutating."""

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return _DESCRIPTOR

    def bind(
        self,
        work_order: ProductionWorkOrder,
        bundle: InputResolutionBundle,
    ) -> PixeloramaSourceInvocationRequest:
        if not isinstance(work_order, ProductionWorkOrder):
            raise TypeError("work_order must be a ProductionWorkOrder")
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        if (
            work_order.work_order_id != bundle.work_order_id
            or work_order.content_hash != bundle.work_order_hash
        ):
            raise DispatchBindingError(
                "Pixelorama source binder WorkOrder does not match the exact resolution bundle"
            )
        if (
            work_order.selected_adapter_id != self.descriptor.adapter_id
            or work_order.dispatch_contract_id != self.descriptor.dispatch_contract_id
        ):
            raise DispatchBindingError(
                "Pixelorama source binder does not match WorkOrder adapter/contract"
            )
        if len(work_order.input_refs) != 1 or len(bundle.resolved_inputs) != 1:
            raise DispatchBindingError(
                "Pixelorama source binder requires exactly one accepted-design input"
            )
        source = bundle.resolved_inputs[0]
        ref = source.original_ref
        if work_order.input_refs != (ref,):
            raise DispatchBindingError(
                "Pixelorama source resolved input does not equal the frozen WorkOrder ref"
            )
        if (
            ref.ref_type is not WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE
            or ref.role != PIXELORAMA_SOURCE_ROLE
            or ref.revision is not None
            or not ref.ref_id.startswith("DESIGNACC-")
        ):
            raise DispatchBindingError(
                "Pixelorama source input is not an immutable accepted design"
            )
        if source.currentness is not ResolvedInputCurrentness.CURRENT:
            raise DispatchBindingError("Pixelorama source accepted design is not current")
        if source.source_object_type != "ACCEPTED_DESIGN":
            raise DispatchBindingError("Pixelorama source input resolved to the wrong object type")
        projection = source.projection
        if not isinstance(projection, dict) or projection.get("acceptance_id") != ref.ref_id:
            raise DispatchBindingError("Pixelorama source accepted-design projection drifted")
        if content_hash(projection) != ref.content_hash:
            raise DispatchBindingError("Pixelorama source accepted-design projection hash drifted")
        try:
            return decode_pixelorama_source_request(
                work_order.task_id, work_order.payload, projection
            )
        except PixeloramaSourceRequestError as exc:
            raise DispatchBindingError(
                "Pixelorama source request projection failed deterministic validation"
            ) from exc
