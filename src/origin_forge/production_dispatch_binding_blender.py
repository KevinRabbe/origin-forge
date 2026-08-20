from __future__ import annotations

from .blender_models import BlenderModelError, validate_blender_v1_project
from .model3d_requests import (
    Model3DRequestError,
    Model3DRequestOperation,
    _request_from_value,
)
from .production_dispatch_binding_core import DispatchBindingError
from .production_dispatch_binding_models import DispatchBinderDescriptor
from .production_dispatch_resolution_models import (
    InputResolutionBundle,
    ResolvedInputCurrentness,
)
from .production_work_order_blender import (
    BLENDER_ADAPTER_ID,
    BLENDER_CONTRACT_ID,
    BLENDER_OPERATION,
    BLENDER_REQUEST_ROLE,
)
from .production_work_order_models import WorkOrderRefType, content_hash
from .production_work_orders import ProductionWorkOrder


BLENDER_BINDER_ID = "binder.blender.export-glb@1"
BLENDER_REQUEST_TYPE_ID = "BlenderJobRequest@production-v1-semantic-binding"

_REQUEST_SCHEMA = {
    "request_type": BLENDER_REQUEST_TYPE_ID,
    "fields": {
        "task_id": "TASK ID",
        "model3d_request_id": "MODEL3DREQ ID",
        "model3d_request_hash": "sha256-prefixed semantic request hash",
        "operation": BLENDER_OPERATION,
        "project": "canonical BlockbenchProjectSpec semantic object",
        "project_hash": "sha256-prefixed canonical project hash",
    },
    "injected_only_after_dispexec_started": [
        "BLOP operation identity",
        "MODEL3D workspace identity",
        "workspace/output paths",
        "trusted Blender runtime profile/executable",
        "runtime hash",
        "runner fingerprint",
        "expected Blender version",
        "process budget",
        "argv/environment",
    ],
    "claim_creation": False,
    "task_transition": False,
    "blender_invocation": False,
}
_REQUEST_SCHEMA_HASH = content_hash(_REQUEST_SCHEMA)
_BINDER_FINGERPRINT = content_hash(
    {
        "implementation_id": "origin-forge-blender-export-glb-dispatch-binder@1",
        "adapter_id": BLENDER_ADAPTER_ID,
        "dispatch_contract_id": BLENDER_CONTRACT_ID,
        "request_schema": _REQUEST_SCHEMA,
        "mapping": {
            "task_id": "WorkOrder.task_id",
            "model3d_request_id": "exact resolved MODEL3D_REQUEST.request_id",
            "model3d_request_hash": "exact resolved MODEL3D_REQUEST.request_hash",
            "operation": "code-owned EXPORT_GLB and exact semantic request operation",
            "project": "exact resolved MODEL3D_REQUEST.project",
            "project_hash": "exact resolved MODEL3D_REQUEST.project_hash",
            "compatibility": "validate_blender_v1_project",
        },
    }
)
_DESCRIPTOR = DispatchBinderDescriptor(
    binder_id=BLENDER_BINDER_ID,
    binder_fingerprint=_BINDER_FINGERPRINT,
    adapter_id=BLENDER_ADAPTER_ID,
    dispatch_contract_id=BLENDER_CONTRACT_ID,
    request_type_id=BLENDER_REQUEST_TYPE_ID,
    request_schema_hash=_REQUEST_SCHEMA_HASH,
    accepted_input_roles=(BLENDER_REQUEST_ROLE,),
)


class BlenderExportGLBInputBinder:
    """Bind exact semantic 3D intent without allocating Blender runtime authority."""

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
                "Blender binder WorkOrder does not match the exact input-resolution bundle"
            )
        if (
            work_order.selected_adapter_id != self.descriptor.adapter_id
            or work_order.dispatch_contract_id != self.descriptor.dispatch_contract_id
        ):
            raise DispatchBindingError(
                "Blender binder does not match WorkOrder adapter/contract"
            )
        if work_order.payload != {}:
            raise DispatchBindingError("Blender export WorkOrder payload drifted")
        if len(work_order.input_refs) != 1 or len(bundle.resolved_inputs) != 1:
            raise DispatchBindingError(
                "Blender binder requires exactly one resolved MODEL3D request"
            )

        source = bundle.resolved_inputs[0]
        ref = source.original_ref
        if work_order.input_refs != (ref,):
            raise DispatchBindingError(
                "Blender resolved request does not equal the frozen WorkOrder ref"
            )
        if (
            ref.ref_type is not WorkOrderRefType.MODEL3D_REQUEST
            or ref.role != BLENDER_REQUEST_ROLE
            or ref.revision is not None
        ):
            raise DispatchBindingError(
                "Blender request ref does not match the exact MODEL3D_REQUEST role contract"
            )
        if source.currentness is not ResolvedInputCurrentness.CURRENT:
            raise DispatchBindingError("Blender MODEL3D request is not current")
        if source.source_object_type != "MODEL3D_REQUEST":
            raise DispatchBindingError(
                "Blender input did not resolve as a MODEL3D_REQUEST"
            )
        if source.source_id != ref.ref_id or source.source_content_hash != ref.content_hash:
            raise DispatchBindingError("Blender resolved request identity/hash drifted")

        projection = source.projection
        try:
            request = _request_from_value(projection)
        except (Model3DRequestError, TypeError, ValueError) as exc:
            raise DispatchBindingError(
                "Blender MODEL3D request projection failed canonical semantic reconstruction"
            ) from exc
        if request.request_id != ref.ref_id:
            raise DispatchBindingError("Blender MODEL3D request identity drifted")
        if request.request_hash != f"sha256:{ref.content_hash}":
            raise DispatchBindingError("Blender MODEL3D request hash drifted")
        if request.operation is not Model3DRequestOperation.EXPORT_GLB:
            raise DispatchBindingError("Blender MODEL3D request operation drifted")
        try:
            validate_blender_v1_project(request.project)
        except BlenderModelError as exc:
            raise DispatchBindingError(
                "Blender MODEL3D request project is incompatible with runner v1"
            ) from exc

        return {
            "task_id": work_order.task_id,
            "model3d_request_id": request.request_id,
            "model3d_request_hash": request.request_hash,
            "operation": BLENDER_OPERATION,
            "project": request.project.to_dict(),
            "project_hash": request.project.content_hash,
        }
