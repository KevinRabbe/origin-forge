from __future__ import annotations

from typing import Any, ClassVar

from .ids import IdKind, validate_id
from .pixelorama_models import BridgeOperation
from .pixelorama_protocol import (
    PixeloramaProtocolError,
    parse_bridge_budget,
    parse_export_spec,
    parse_sprite_spec,
)
from .production_work_order_models import (
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    WorkOrderRefType,
    canonical_bytes,
    content_hash,
)
from .production_work_order_validators import DispatchValidatorError

PIXELORAMA_ADAPTER_ID = "originforge.pixelorama.export"
PIXELORAMA_CONTRACT_ID = "pixelorama.spritesheet-export@1"
PIXELORAMA_VALIDATOR_ID = "validator.pixelorama.spritesheet-export@1"
PIXELORAMA_SCHEMA_ID = "schema.pixelorama.spritesheet-export@1"
PIXELORAMA_SOURCE_ROLE = "pixelorama_project"
PIXELORAMA_SOURCE_ARTIFACT_TYPE = "PIXELORAMA_PROJECT"
PIXELORAMA_OPERATION = "EXPORT_SPRITESHEET"
PIXELORAMA_STAGED_SOURCE_PATH = "inputs/source.pxo"
PIXELORAMA_EXPORT_PATH = "exports/spritesheet.png"

PIXELORAMA_SOURCE_ADAPTER_ID = "originforge.pixelorama.source"
PIXELORAMA_SOURCE_CONTRACT_ID = "pixelorama.source-create@1"
PIXELORAMA_SOURCE_VALIDATOR_ID = "validator.pixelorama.source-create@1"
PIXELORAMA_SOURCE_SCHEMA_ID = "schema.pixelorama.source-create@1"
PIXELORAMA_SOURCE_INPUT_ROLE = "accepted_design"
PIXELORAMA_SOURCE_REQUEST_TYPE_ID = "PixeloramaSourceService.create@production-v1"


class PixeloramaSpritesheetExportDispatchValidator:
    """Pure Phase-33 contract for one already-governed Pixelorama project export.

    Phase 48A freezes only the inert WorkOrder relation. It does not read Artifact
    metadata/bytes, choose a Pixelorama installation, allocate execution IDs, or
    invoke the editor. Those boundaries remain downstream.
    """

    _IMPLEMENTATION_ID = "origin-forge-pixelorama-spritesheet-export-validator@1"
    _SCHEMA: ClassVar[dict[str, object]] = {
        "schema_id": PIXELORAMA_SCHEMA_ID,
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
                "source_ref_contract": {
                    "count": 1,
                    "ref_type": WorkOrderRefType.ARTIFACT.value,
                    "role": PIXELORAMA_SOURCE_ROLE,
                    "id_kind": IdKind.ARTIFACT.value,
                    "revision": None,
                },
                "code_owned_operation": PIXELORAMA_OPERATION,
                "code_owned_paths": {
                    "staged_source": PIXELORAMA_STAGED_SOURCE_PATH,
                    "export": PIXELORAMA_EXPORT_PATH,
                },
                "excluded_authority": [
                    "artifact-bytes",
                    "pixelorama-profile",
                    "pixelorama-executable",
                    "process-argv",
                    "pxop-id",
                    "media-workspace-id",
                    "adoption",
                    "task-outcome",
                ],
            }
        )

    @property
    def validator_id(self) -> str:
        return PIXELORAMA_VALIDATOR_ID

    @property
    def validator_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def payload_schema_id(self) -> str:
        return PIXELORAMA_SCHEMA_ID

    @property
    def payload_schema_hash(self) -> str:
        return self._schema_hash

    def schema_dict(self) -> dict[str, object]:
        return {
            "schema_id": PIXELORAMA_SCHEMA_ID,
            "type": "OBJECT",
            "fields": [],
            "additional_fields": False,
        }

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DispatchValidatorError("Pixelorama export payload must be an object")
        if payload:
            raise DispatchValidatorError(
                "Pixelorama export payload is fixed and accepts no caller fields"
            )
        if len(input_refs) != 1 or not isinstance(input_refs[0], WorkOrderInputRef):
            raise DispatchValidatorError(
                "Pixelorama export requires exactly one Artifact input ref"
            )
        source = input_refs[0]
        if source.ref_type is not WorkOrderRefType.ARTIFACT:
            raise DispatchValidatorError(
                "Pixelorama export source ref must be an Artifact"
            )
        if source.role != PIXELORAMA_SOURCE_ROLE:
            raise DispatchValidatorError(
                "Pixelorama export source ref has the wrong role"
            )
        if not validate_id(source.ref_id, IdKind.ARTIFACT):
            raise DispatchValidatorError(
                "Pixelorama export source ref has invalid Artifact identity"
            )
        if source.revision is not None:
            raise DispatchValidatorError(
                "Pixelorama export Artifact ref must not carry a revision"
            )
        canonical_bytes(payload)
        return {}


class PixeloramaSourceCreationDispatchValidator:
    """Validate a complete source/animation request without invoking Pixelorama."""

    _IMPLEMENTATION_ID = "origin-forge-pixelorama-source-create-validator@1"
    _SCHEMA: ClassVar[dict[str, object]] = {
        "schema_id": PIXELORAMA_SOURCE_SCHEMA_ID,
        "type": "OBJECT",
        "fields": ["operation", "sprite_spec", "export_specs", "budget"],
        "additional_fields": False,
    }

    def __init__(self) -> None:
        self._schema_hash = content_hash(self._SCHEMA)
        self._fingerprint = content_hash(
            {
                "implementation_id": self._IMPLEMENTATION_ID,
                "payload_schema_hash": self._schema_hash,
                "input_ref_contract": {
                    "count": 1,
                    "ref_type": WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE.value,
                    "role": PIXELORAMA_SOURCE_INPUT_ROLE,
                    "id_prefix": "DESIGNACC-",
                    "revision": None,
                },
                "excluded_authority": [
                    "pixelorama-profile",
                    "pixelorama-executable",
                    "process-argv",
                    "pxop-id",
                    "media-workspace-id",
                    "task-outcome",
                    "adoption",
                ],
            }
        )

    @property
    def validator_id(self) -> str:
        return PIXELORAMA_SOURCE_VALIDATOR_ID

    @property
    def validator_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def payload_schema_id(self) -> str:
        return PIXELORAMA_SOURCE_SCHEMA_ID

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
        if not isinstance(payload, dict) or set(payload) != {
            "operation", "sprite_spec", "export_specs", "budget"
        }:
            raise DispatchValidatorError(
                "Pixelorama source payload fields are not exact"
            )
        if payload["operation"] != BridgeOperation.CREATE_SPRITE_PROJECT.value:
            raise DispatchValidatorError(
                "Pixelorama source operation must be CREATE_SPRITE_PROJECT"
            )
        if len(input_refs) != 1:
            raise DispatchValidatorError(
                "Pixelorama source requires exactly one accepted-design ref"
            )
        ref = input_refs[0]
        if (
            ref.ref_type is not WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE
            or ref.role != PIXELORAMA_SOURCE_INPUT_ROLE
            or not ref.ref_id.startswith("DESIGNACC-")
            or ref.revision is not None
        ):
            raise DispatchValidatorError(
                "Pixelorama source ref must be an immutable accepted design"
            )
        if not isinstance(payload["export_specs"], list):
            raise DispatchValidatorError("Pixelorama source export_specs must be an array")
        try:
            parse_sprite_spec(payload["sprite_spec"])
            tuple(parse_export_spec(value) for value in payload["export_specs"])
            parse_bridge_budget(payload["budget"])
            canonical_bytes(payload)
        except (PixeloramaProtocolError, ProductionWorkOrderModelError) as exc:
            raise DispatchValidatorError(
                "Pixelorama source payload failed deterministic validation"
            ) from exc
        return dict(payload)
