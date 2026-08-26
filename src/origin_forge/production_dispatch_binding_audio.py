from __future__ import annotations

from typing import ClassVar

from .production_dispatch_binding_core import DispatchBindingError
from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import (
    InputResolutionBundle,
    ResolvedInputCurrentness,
)
from .production_work_order_audio import (
    PIPER_ADAPTER_ID,
    PIPER_CONTRACT_ID,
    PIPER_PROFILE_ROLE,
    PIPER_REQUEST_TYPE_ID,
    PiperSpeechDispatchValidator,
)
from .production_work_order_models import WorkOrderRefType, content_hash
from .production_work_orders import ProductionWorkOrder

PIPER_BINDER_ID = "binder.audio.piper-tts@1"


class PiperAudioInputBinder:
    """Freeze exact Piper semantic inputs without allocating execution authority."""

    _SCHEMA: ClassVar[dict[str, object]] = {
        "request_type": PIPER_REQUEST_TYPE_ID,
        "fields": "task_id, profile identity, speech text, duration/timeout limits, output path",
        "execution_ids": "allocated only after durable DISPATCH_EXECUTION_STARTED",
        "adapter_invocation": False,
    }
    _DESCRIPTOR = DispatchBinderDescriptor(
        binder_id=PIPER_BINDER_ID,
        binder_fingerprint=content_hash({"implementation_id": "origin-forge-piper-dispatch-binder@1", "schema": _SCHEMA}),
        adapter_id=PIPER_ADAPTER_ID,
        dispatch_contract_id=PIPER_CONTRACT_ID,
        request_type_id=PIPER_REQUEST_TYPE_ID,
        request_schema_hash=content_hash(_SCHEMA),
        accepted_input_roles=(PIPER_PROFILE_ROLE,),
    )

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._DESCRIPTOR

    def bind(self, work_order: ProductionWorkOrder, bundle: InputResolutionBundle) -> object:
        if not isinstance(work_order, ProductionWorkOrder) or not isinstance(bundle, InputResolutionBundle):
            raise TypeError("work_order and bundle must be canonical production objects")
        if work_order.work_order_id != bundle.work_order_id or work_order.content_hash != bundle.work_order_hash:
            raise DispatchBindingError("Piper WorkOrder does not match exact input-resolution bundle")
        if work_order.selected_adapter_id != PIPER_ADAPTER_ID or work_order.dispatch_contract_id != PIPER_CONTRACT_ID:
            raise DispatchBindingError("Piper binder does not match WorkOrder adapter/contract")
        if len(work_order.input_refs) != 1 or len(bundle.resolved_inputs) != 1:
            raise DispatchBindingError("Piper binder requires exactly one resolved AUDIO_PROFILE")
        source = bundle.resolved_inputs[0]
        ref = source.original_ref
        if source.currentness is not ResolvedInputCurrentness.CURRENT:
            raise DispatchBindingError("Piper AUDIO_PROFILE is not current")
        if source.source_object_type != "AUDIO_PROFILE" or ref.ref_type is not WorkOrderRefType.AUDIO_PROFILE or ref.role != PIPER_PROFILE_ROLE:
            raise DispatchBindingError("Piper input is not the exact AUDIO_PROFILE role")
        if source.source_id != ref.ref_id or source.source_content_hash != ref.content_hash:
            raise DispatchBindingError("Piper AUDIO_PROFILE identity/hash drifted")
        try:
            payload = PiperSpeechDispatchValidator().validate(work_order.payload, work_order.input_refs)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise DispatchBindingError("Piper WorkOrder payload failed exact validation") from exc
        return {
            "task_id": work_order.task_id,
            "profile_id": ref.ref_id,
            "profile_hash": ref.content_hash,
            **payload,
        }
