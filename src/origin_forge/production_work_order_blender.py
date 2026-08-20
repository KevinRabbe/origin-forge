from __future__ import annotations

from typing import Any

from .blender_models import BlenderModelError, validate_blender_v1_project
from .ids import IdKind, validate_id
from .model3d_requests import Model3DRequestOperation
from .production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
    content_hash,
)
from .production_work_order_validators import DispatchValidatorError


BLENDER_ADAPTER_ID = "originforge.blender.model3d"
BLENDER_CONTRACT_ID = "blender.export-glb@1"
BLENDER_VALIDATOR_ID = "validator.blender.export-glb@1"
BLENDER_SCHEMA_ID = "schema.blender.export-glb@1"
BLENDER_REQUEST_ROLE = "model3d_request"
BLENDER_OPERATION = Model3DRequestOperation.EXPORT_GLB.value


class BlenderExportGLBDispatchValidator:
    """Pure WorkOrder validator for one protected semantic MODEL3D request.

    Phase 51B freezes only the semantic dispatch relation. It does not allocate
    Blender operation/workspace IDs, choose runtime/profile/process authority,
    derive paths, or invoke Blender.
    """

    _IMPLEMENTATION_ID = "origin-forge-blender-export-glb-work-order-validator@1"
    _SCHEMA = {
        "schema_id": BLENDER_SCHEMA_ID,
        "type": "OBJECT",
        "fields": [],
        "additional_fields": False,
    }

    def __init__(self) -> None:
        self._schema_hash = content_hash(self._SCHEMA)
        self._fingerprint = content_hash(
            {
                "implementation_id": self._IMPLEMENTATION_ID,
                "payload_schema_hash": self._schema_hash,
                "request_ref_contract": {
                    "count": 1,
                    "ref_type": WorkOrderRefType.MODEL3D_REQUEST.value,
                    "role": BLENDER_REQUEST_ROLE,
                    "id_kind": IdKind.MODEL3D_REQUEST.value,
                    "revision": None,
                },
                "code_owned_operation": BLENDER_OPERATION,
                "project_compatibility": "validate_blender_v1_project",
                "excluded_authority": [
                    "blop-id",
                    "model3d-workspace-id",
                    "workspace-path",
                    "output-path",
                    "runtime-profile",
                    "blender-executable",
                    "runtime-hash",
                    "runner-fingerprint",
                    "expected-blender-version",
                    "process-budget",
                    "argv-env",
                    "model-provider",
                    "claim",
                    "task-transition",
                    "backend-invocation",
                ],
            }
        )

    @property
    def validator_id(self) -> str:
        return BLENDER_VALIDATOR_ID

    @property
    def validator_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def payload_schema_id(self) -> str:
        return BLENDER_SCHEMA_ID

    @property
    def payload_schema_hash(self) -> str:
        return self._schema_hash

    def schema_dict(self) -> dict[str, object]:
        return dict(self._SCHEMA)

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DispatchValidatorError("Blender export payload must be an object")
        if payload:
            raise DispatchValidatorError(
                "Blender export payload is fixed and accepts no caller fields"
            )
        if len(input_refs) != 1 or not isinstance(input_refs[0], WorkOrderInputRef):
            raise DispatchValidatorError(
                "Blender export requires exactly one MODEL3D_REQUEST input ref"
            )
        request_ref = input_refs[0]
        if request_ref.ref_type is not WorkOrderRefType.MODEL3D_REQUEST:
            raise DispatchValidatorError(
                "Blender export ref must be a MODEL3D_REQUEST"
            )
        if request_ref.role != BLENDER_REQUEST_ROLE:
            raise DispatchValidatorError("Blender export request ref has the wrong role")
        if not validate_id(request_ref.ref_id, IdKind.MODEL3D_REQUEST):
            raise DispatchValidatorError(
                "Blender export request ref has invalid MODEL3DREQ identity"
            )
        if request_ref.revision is not None:
            raise DispatchValidatorError(
                "Blender export MODEL3D_REQUEST ref must not carry a revision"
            )
        canonical_bytes(payload)
        return {}


def validate_blender_semantic_project(project: object) -> None:
    """Expose the existing Phase-20C compatibility predicate at the WorkOrder boundary."""

    try:
        validate_blender_v1_project(project)  # type: ignore[arg-type]
    except (BlenderModelError, TypeError, ValueError) as exc:
        raise DispatchValidatorError(
            "MODEL3D request project is incompatible with Blender runner v1"
        ) from exc
