from __future__ import annotations

from typing import Any, ClassVar

from .production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
from .production_work_order_validators import (
    DispatchPayloadValidator,
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)

RUNTIME_ADAPTER_ID = "originforge.runtime.observe"
RUNTIME_CONTRACT_ID = "runtime.observe@1"
RUNTIME_REQUEST_TYPE_ID = "RUNTIME_OBSERVATION_REQUEST"
RUNTIME_REQUEST_ROLE = "runtime_observation_request"


class RuntimeObservationDispatchValidator:
    """Validate inert runtime-observation intent plus one exact OBS request ref."""

    validator_id = "validator.runtime.observe@1"
    payload_schema_id = "schema.runtime.observe@1"
    _base: ClassVar[DispatchPayloadValidator] = StaticObjectPayloadValidator(
        validator_id=validator_id,
        payload_schema_id=payload_schema_id,
        fields=(
            PayloadFieldRule(
                "operation",
                PayloadFieldKind.STRING,
                allowed_values=("OBSERVE",),
                max_string_chars=16,
            ),
        ),
    )

    @property
    def validator_fingerprint(self) -> str:
        return self._base.validator_fingerprint

    @property
    def payload_schema_hash(self) -> str:
        return self._base.payload_schema_hash

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if len(input_refs) != 1:
            raise DispatchValidatorError(
                "runtime observation requires exactly one protected request ref"
            )
        ref = input_refs[0]
        if (
            ref.ref_type is not WorkOrderRefType.RUNTIME_OBSERVATION_REQUEST
            or not ref.ref_id.startswith("OBS-")
            or ref.role != RUNTIME_REQUEST_ROLE
            or ref.revision is not None
        ):
            raise DispatchValidatorError(
                "runtime observation ref must be one exact OBS request"
            )
        return self._base.validate(payload, input_refs)


def runtime_observation_contract_dict() -> dict[str, object]:
    validator = RuntimeObservationDispatchValidator()
    return {
        "adapter_id": RUNTIME_ADAPTER_ID,
        "contract_id": RUNTIME_CONTRACT_ID,
        "request_type_id": RUNTIME_REQUEST_TYPE_ID,
        "request_role": RUNTIME_REQUEST_ROLE,
        "validator_id": validator.validator_id,
        "validator_fingerprint": validator.validator_fingerprint,
        "payload_schema_id": validator.payload_schema_id,
        "payload_schema_hash": validator.payload_schema_hash,
        "contract_hash": content_hash(validator._base.schema_dict()),
    }
