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

PLAYTEST_ADAPTER_ID = "originforge.playtest.cooperative"
PLAYTEST_CONTRACT_ID = "playtest.cooperative@1"
PLAYTEST_REQUEST_TYPE_ID = "PLAYTEST_SCENARIO"
PLAYTEST_REQUEST_ROLE = "playtest_scenario"


class CooperativePlaytestDispatchValidator:
    validator_id = "validator.playtest.cooperative@1"
    payload_schema_id = "schema.playtest.cooperative@1"
    _base: ClassVar[DispatchPayloadValidator] = StaticObjectPayloadValidator(
        validator_id=validator_id,
        payload_schema_id=payload_schema_id,
        fields=(
            PayloadFieldRule(
                "operation",
                PayloadFieldKind.STRING,
                allowed_values=("PLAYTEST",),
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
        self, payload: dict[str, Any], input_refs: tuple[WorkOrderInputRef, ...]
    ) -> dict[str, Any]:
        if len(input_refs) != 1:
            raise DispatchValidatorError(
                "cooperative playtest requires exactly one protected scenario ref"
            )
        ref = input_refs[0]
        if (
            ref.ref_type is not WorkOrderRefType.PLAYTEST_SCENARIO
            or not ref.ref_id.startswith("PLAYSCEN-")
            or ref.role != PLAYTEST_REQUEST_ROLE
            or ref.revision is not None
        ):
            raise DispatchValidatorError(
                "playtest ref must be one exact PLAYSCEN scenario"
            )
        return self._base.validate(payload, input_refs)

    def schema_dict(self) -> dict[str, object]:
        return self._base.schema_dict()


def playtest_contract_dict() -> dict[str, object]:
    validator = CooperativePlaytestDispatchValidator()
    return {
        "adapter_id": PLAYTEST_ADAPTER_ID,
        "contract_id": PLAYTEST_CONTRACT_ID,
        "request_type_id": PLAYTEST_REQUEST_TYPE_ID,
        "request_role": PLAYTEST_REQUEST_ROLE,
        "validator_id": validator.validator_id,
        "validator_fingerprint": validator.validator_fingerprint,
        "payload_schema_id": validator.payload_schema_id,
        "payload_schema_hash": validator.payload_schema_hash,
        "contract_hash": content_hash(validator.schema_dict()),
    }
