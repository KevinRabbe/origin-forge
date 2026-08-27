from __future__ import annotations

from typing import ClassVar

from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import InputResolutionBundle
from .production_work_order_image import (
    IMAGE_ADAPTER_ID,
    IMAGE_CONTRACT_ID,
    IMAGE_REQUEST_TYPE_ID,
    ImageGenerationDispatchValidator,
)
from .production_work_order_models import canonical_bytes, content_hash
from .production_work_orders import ProductionWorkOrder


class ImageDispatchBindingError(ValueError):
    pass


class ImageGenerationInputBinder:
    """Bind one validated image GENERATE WorkOrder without invoking ComfyUI."""

    _REQUEST_SCHEMA: ClassVar[dict[str, object]] = {
        "request_type": IMAGE_REQUEST_TYPE_ID,
        "fields": "validated ImageGenerationDispatchValidator payload plus exact task_id",
        "input_refs": "none",
        "execution_ids": "allocated only after durable DISPATCH_EXECUTION_STARTED",
        "adapter_invocation": False,
    }
    _SCHEMA_HASH = content_hash(_REQUEST_SCHEMA)
    _FINGERPRINT = content_hash(
        {
            "implementation_id": "origin-forge-image-generation-dispatch-binder@1",
            "adapter_id": IMAGE_ADAPTER_ID,
            "dispatch_contract_id": IMAGE_CONTRACT_ID,
            "request_schema": _REQUEST_SCHEMA,
            "workflow_identity": "payload is revalidated later against ImageWorkflowStore",
        }
    )
    _DESCRIPTOR = DispatchBinderDescriptor(
        binder_id="binder.image.generate@1",
        binder_fingerprint=_FINGERPRINT,
        adapter_id=IMAGE_ADAPTER_ID,
        dispatch_contract_id=IMAGE_CONTRACT_ID,
        request_type_id=IMAGE_REQUEST_TYPE_ID,
        request_schema_hash=_SCHEMA_HASH,
        accepted_input_roles=(),
    )

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._DESCRIPTOR

    def bind(self, work_order: ProductionWorkOrder, bundle: InputResolutionBundle) -> object:
        if not isinstance(work_order, ProductionWorkOrder):
            raise TypeError("work_order must be a ProductionWorkOrder")
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        if (
            work_order.work_order_id != bundle.work_order_id
            or work_order.content_hash != bundle.work_order_hash
        ):
            raise ImageDispatchBindingError("image binder WorkOrder does not match exact input-resolution bundle")
        if (
            work_order.selected_adapter_id != self.descriptor.adapter_id
            or work_order.dispatch_contract_id != self.descriptor.dispatch_contract_id
        ):
            raise ImageDispatchBindingError("image binder does not match WorkOrder adapter/contract")
        if work_order.input_refs or bundle.resolved_inputs:
            raise ImageDispatchBindingError("image GENERATE binder accepts no input refs")
        try:
            payload = ImageGenerationDispatchValidator().validate(work_order.payload, ())
        except (RuntimeError, TypeError, ValueError) as exc:
            raise ImageDispatchBindingError("image WorkOrder payload no longer reconstructs exact generation request") from exc
        # Keep the frozen request projection at the public scalar contract. The
        # validator's ``budget`` object is derived evidence stored in the
        # WorkOrder, not a second request field.
        payload.pop("budget", None)
        projection = {"task_id": work_order.task_id, **payload}
        canonical_bytes(projection)
        return projection
