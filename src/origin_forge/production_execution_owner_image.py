from __future__ import annotations

from .production_capability_builtin import builtin_trusted_production_adapters
from .production_dispatch_binding_image import ImageGenerationInputBinder
from .production_execution_owner import ProductionExecutionOwnerDescriptor, ProductionExecutionOwnerError


IMAGE_EXECUTION_OWNER_ID = "originforge.execution.image.generate@1"


def image_generation_execution_owner_descriptor() -> ProductionExecutionOwnerDescriptor:
    """Return the reviewed image owner relation without registering execution yet."""
    adapter = next(
        (value for value in builtin_trusted_production_adapters() if value.adapter_id == "originforge.image.generate"),
        None,
    )
    if adapter is None:
        raise ProductionExecutionOwnerError("built-in capability inventory lacks image generation adapter")
    binder = ImageGenerationInputBinder().descriptor
    if binder.adapter_id != adapter.adapter_id or binder.dispatch_contract_id != "image.generate@1":
        raise ProductionExecutionOwnerError("built-in image generation binder relation drifted")
    return ProductionExecutionOwnerDescriptor(
        owner_id=IMAGE_EXECUTION_OWNER_ID,
        owner_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        dispatch_contract_id=binder.dispatch_contract_id,
        binder_id=binder.binder_id,
        binder_fingerprint=binder.binder_fingerprint,
        request_type_id=binder.request_type_id,
        request_schema_hash=binder.request_schema_hash,
        model_strategy_roles=(),
        requires_sandbox=False,
        requires_workspace_manager=False,
    )
