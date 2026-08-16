from __future__ import annotations

from .production_dispatch_binding_core import DispatchBindingError
from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import (
    InputResolutionBundle,
    ResolvedInputCurrentness,
)
from .production_work_order_models import WorkOrderRefType, content_hash
from .production_work_order_pixelorama import (
    PIXELORAMA_ADAPTER_ID,
    PIXELORAMA_CONTRACT_ID,
    PIXELORAMA_EXPORT_PATH,
    PIXELORAMA_OPERATION,
    PIXELORAMA_SOURCE_ARTIFACT_TYPE,
    PIXELORAMA_SOURCE_ROLE,
    PIXELORAMA_STAGED_SOURCE_PATH,
)
from .production_work_orders import ProductionWorkOrder


PIXELORAMA_BINDER_ID = "binder.pixelorama.spritesheet-export@1"
PIXELORAMA_REQUEST_TYPE_ID = "PixeloramaCliExportService.execute@production-v1"
PIXELORAMA_SOURCE_STATUS = "PRODUCED"

_REQUEST_SCHEMA = {
    "request_type": PIXELORAMA_REQUEST_TYPE_ID,
    "fields": {
        "task_id": "TASK ID",
        "source_artifact_id": "ARTIFACT ID",
        "source_artifact_hash": "lowercase SHA-256",
        "source_artifact_type": PIXELORAMA_SOURCE_ARTIFACT_TYPE,
        "source_artifact_status": PIXELORAMA_SOURCE_STATUS,
        "source_path_or_uri": "inert Artifact path_or_uri metadata",
        "operation": PIXELORAMA_OPERATION,
        "staged_source_relative_path": PIXELORAMA_STAGED_SOURCE_PATH,
        "output_relative_path": PIXELORAMA_EXPORT_PATH,
    },
    "injected_later": [
        "Artifact bytes and derived byte count",
        "trusted Pixelorama CLI profile",
        "PXOP operation identity",
        "MEDIA workspace identity",
    ],
    "artifact_byte_read": False,
    "pixelorama_invocation": False,
    "adoption": False,
    "task_outcome": False,
}
_REQUEST_SCHEMA_HASH = content_hash(_REQUEST_SCHEMA)
_BINDER_FINGERPRINT = content_hash(
    {
        "implementation_id": "origin-forge-pixelorama-spritesheet-export-dispatch-binder@1",
        "adapter_id": PIXELORAMA_ADAPTER_ID,
        "dispatch_contract_id": PIXELORAMA_CONTRACT_ID,
        "request_schema": _REQUEST_SCHEMA,
        "mapping": {
            "task_id": "WorkOrder.task_id",
            "source_artifact_id": "resolved Artifact projection.id",
            "source_artifact_hash": "resolved Artifact projection.content_hash",
            "source_artifact_type": "resolved Artifact projection.type == PIXELORAMA_PROJECT",
            "source_artifact_status": "resolved Artifact projection.status == PRODUCED",
            "source_path_or_uri": "resolved Artifact projection.path_or_uri metadata only",
            "operation": "code-owned EXPORT_SPRITESHEET",
            "staged_source_relative_path": "code-owned inputs/source.pxo",
            "output_relative_path": "code-owned exports/spritesheet.png",
        },
    }
)
_DESCRIPTOR = DispatchBinderDescriptor(
    binder_id=PIXELORAMA_BINDER_ID,
    binder_fingerprint=_BINDER_FINGERPRINT,
    adapter_id=PIXELORAMA_ADAPTER_ID,
    dispatch_contract_id=PIXELORAMA_CONTRACT_ID,
    request_type_id=PIXELORAMA_REQUEST_TYPE_ID,
    request_schema_hash=_REQUEST_SCHEMA_HASH,
    accepted_input_roles=(PIXELORAMA_SOURCE_ROLE,),
)


class PixeloramaSpritesheetExportInputBinder:
    """Reconstruct inert Pixelorama export authority without opening source bytes."""

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return _DESCRIPTOR

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
            raise DispatchBindingError(
                "Pixelorama binder WorkOrder does not match the exact input-resolution bundle"
            )
        if (
            work_order.selected_adapter_id != self.descriptor.adapter_id
            or work_order.dispatch_contract_id != self.descriptor.dispatch_contract_id
        ):
            raise DispatchBindingError(
                "Pixelorama binder does not match WorkOrder adapter/contract"
            )
        if work_order.payload != {}:
            raise DispatchBindingError("Pixelorama export WorkOrder payload drifted")
        if len(work_order.input_refs) != 1 or len(bundle.resolved_inputs) != 1:
            raise DispatchBindingError(
                "Pixelorama binder requires exactly one resolved source Artifact"
            )

        source = bundle.resolved_inputs[0]
        ref = source.original_ref
        if work_order.input_refs != (ref,):
            raise DispatchBindingError(
                "Pixelorama resolved source does not equal the frozen WorkOrder ref"
            )
        if (
            ref.ref_type is not WorkOrderRefType.ARTIFACT
            or ref.role != PIXELORAMA_SOURCE_ROLE
            or ref.revision is not None
        ):
            raise DispatchBindingError(
                "Pixelorama source ref does not match the exact Artifact role contract"
            )
        if source.currentness is not ResolvedInputCurrentness.CURRENT:
            raise DispatchBindingError("Pixelorama source Artifact is not current")
        if source.source_object_type != "ARTIFACT":
            raise DispatchBindingError("Pixelorama source did not resolve as an Artifact")
        if source.source_id != ref.ref_id or source.source_content_hash != ref.content_hash:
            raise DispatchBindingError("Pixelorama resolved source identity/hash drifted")

        projection = source.projection
        if not isinstance(projection, dict):
            raise DispatchBindingError("Pixelorama Artifact projection must be an object")
        required_projection_fields = {
            "id",
            "type",
            "path_or_uri",
            "content_hash",
            "status",
        }
        if not required_projection_fields.issubset(projection):
            raise DispatchBindingError("Pixelorama Artifact projection shape drifted")
        if projection["id"] != ref.ref_id or projection["content_hash"] != ref.content_hash:
            raise DispatchBindingError("Pixelorama Artifact projection identity/hash drifted")
        if projection["type"] != PIXELORAMA_SOURCE_ARTIFACT_TYPE:
            raise DispatchBindingError(
                "Pixelorama source Artifact has the wrong canonical Artifact type"
            )
        if projection["status"] != PIXELORAMA_SOURCE_STATUS:
            raise DispatchBindingError(
                "Pixelorama source Artifact is not in the accepted PRODUCED state"
            )
        path_or_uri = projection["path_or_uri"]
        if not isinstance(path_or_uri, str) or not path_or_uri:
            raise DispatchBindingError(
                "Pixelorama source Artifact path_or_uri metadata is invalid"
            )

        return {
            "task_id": work_order.task_id,
            "source_artifact_id": ref.ref_id,
            "source_artifact_hash": ref.content_hash,
            "source_artifact_type": PIXELORAMA_SOURCE_ARTIFACT_TYPE,
            "source_artifact_status": PIXELORAMA_SOURCE_STATUS,
            "source_path_or_uri": path_or_uri,
            "operation": PIXELORAMA_OPERATION,
            "staged_source_relative_path": PIXELORAMA_STAGED_SOURCE_PATH,
            "output_relative_path": PIXELORAMA_EXPORT_PATH,
        }
