from __future__ import annotations

from typing import Any

from .production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from .production_work_order_validators import (
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)

BUILD_ADAPTER_ID = "originforge.build.integration"
BUILD_CONTRACT_ID = "build.integration@1"
BUILD_REQUEST_TYPE_ID = "BuildIntegrationService.execute@production-v1"
BUILD_VALIDATOR_ID = "validator.build.integration@1"
BUILD_SCHEMA_ID = "schema.build.integration@1"


class BuildIntegrationDispatchValidator:
    """Validate the inert build selector; commands remain config-owned."""

    def __init__(self) -> None:
        self._base = StaticObjectPayloadValidator(
            validator_id=BUILD_VALIDATOR_ID,
            payload_schema_id=BUILD_SCHEMA_ID,
            fields=(
                PayloadFieldRule(
                    "operation",
                    PayloadFieldKind.STRING,
                    allowed_values=("BUILD",),
                    max_string_chars=16,
                ),
            ),
        )

    @property
    def validator_id(self) -> str:
        return self._base.validator_id

    @property
    def validator_fingerprint(self) -> str:
        return self._base.validator_fingerprint

    @property
    def payload_schema_id(self) -> str:
        return self._base.payload_schema_id

    @property
    def payload_schema_hash(self) -> str:
        return self._base.payload_schema_hash

    def schema_dict(self) -> dict[str, object]:
        return self._base.schema_dict()

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if (
            len(input_refs) != 1
            or input_refs[0].ref_type is not WorkOrderRefType.WORKSPACE
            or input_refs[0].role != "build_workspace"
        ):
            raise DispatchValidatorError(
                "build integration WorkOrder requires one audited Workspace ref"
            )
        return self._base.validate(payload, input_refs)
