from __future__ import annotations

from typing import Any

from .audio_models import AudioOperation, validate_sha256
from .production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from .production_work_order_validators import (
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)

PIPER_ADAPTER_ID = "originforge.audio.piper"
PIPER_CONTRACT_ID = "audio.piper-tts@1"
PIPER_VALIDATOR_ID = "validator.audio.piper-tts@1"
PIPER_SCHEMA_ID = "schema.audio.piper-tts@1"
PIPER_REQUEST_TYPE_ID = "AudioOperationRequest.SYNTHESIZE_SPEECH@production-v1"
PIPER_PROFILE_ROLE = "audio_profile"


class PiperSpeechDispatchValidator:
    """Validate an inert Piper request plus one exact protected audio profile."""

    def __init__(self) -> None:
        self._base = StaticObjectPayloadValidator(
            validator_id=PIPER_VALIDATOR_ID,
            payload_schema_id=PIPER_SCHEMA_ID,
            fields=(
                PayloadFieldRule(
                    "operation", PayloadFieldKind.STRING,
                    allowed_values=(AudioOperation.SYNTHESIZE_SPEECH.value,),
                ),
                PayloadFieldRule("text", PayloadFieldKind.STRING, max_string_chars=16_384),
                PayloadFieldRule("max_duration_ms", PayloadFieldKind.INTEGER, min_integer=1, max_integer=600_000),
                PayloadFieldRule("timeout_seconds", PayloadFieldKind.INTEGER, min_integer=1, max_integer=3_600),
                PayloadFieldRule("output_relative_path", PayloadFieldKind.STRING, max_string_chars=4_096),
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
        if len(input_refs) != 1 or not isinstance(input_refs[0], WorkOrderInputRef):
            raise DispatchValidatorError("Piper speech requires exactly one AUDIO_PROFILE input ref")
        ref = input_refs[0]
        if ref.ref_type is not WorkOrderRefType.AUDIO_PROFILE or ref.role != PIPER_PROFILE_ROLE:
            raise DispatchValidatorError("Piper speech ref must be an AUDIO_PROFILE with role audio_profile")
        normalized = self._base.validate(payload, input_refs)
        if normalized["operation"] != AudioOperation.SYNTHESIZE_SPEECH.value:
            raise DispatchValidatorError("Piper operation must be SYNTHESIZE_SPEECH")
        text = normalized["text"].strip()
        if not text or "\x00" in text:
            raise DispatchValidatorError("Piper text must be non-empty and contain no NUL")
        normalized["text"] = text
        output = normalized["output_relative_path"]
        if "\\" in output or output.startswith("/") or not output.startswith("exports/") or not output.lower().endswith(".wav"):
            raise DispatchValidatorError("Piper output must be a workspace-relative WAV under exports/")
        try:
            validate_sha256("sha256:" + ref.content_hash, "audio profile ref hash")
        except ValueError as exc:
            raise DispatchValidatorError("Piper AUDIO_PROFILE ref hash is invalid") from exc
        return normalized
