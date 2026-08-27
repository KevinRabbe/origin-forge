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

FFMPEG_ADAPTER_ID = "originforge.audio.ffmpeg"
FFMPEG_CONTRACT_ID = "audio.ffmpeg-process@1"
FFMPEG_VALIDATOR_ID = "validator.audio.ffmpeg-process@1"
FFMPEG_SCHEMA_ID = "schema.audio.ffmpeg-process@1"
FFMPEG_REQUEST_TYPE_ID = "AudioOperationRequest.PROCESS_AUDIO@production-v1"
FFMPEG_SOURCE_ROLE = "audio_source"
FFMPEG_PROFILE_ROLE = "audio_profile"
PIPER_ADAPTER_ID = "originforge.audio.piper"
PIPER_CONTRACT_ID = "audio.piper-tts@1"
PIPER_VALIDATOR_ID = "validator.audio.piper-tts@1"
PIPER_SCHEMA_ID = "schema.audio.piper-tts@1"
PIPER_REQUEST_TYPE_ID = "AudioOperationRequest.SYNTHESIZE_SPEECH@production-v1"
PIPER_PROFILE_ROLE = "audio_profile"


class FfmpegAudioDispatchValidator:
    """Validate an inert FFmpeg request with one exact source and profile."""

    def __init__(self) -> None:
        self._base = StaticObjectPayloadValidator(
            validator_id=FFMPEG_VALIDATOR_ID,
            payload_schema_id=FFMPEG_SCHEMA_ID,
            fields=(
                PayloadFieldRule("operation", PayloadFieldKind.STRING, allowed_values=(AudioOperation.PROCESS_AUDIO.value,)),
                PayloadFieldRule("target_sample_rate", PayloadFieldKind.INTEGER, min_integer=8_000, max_integer=192_000),
                PayloadFieldRule("target_channels", PayloadFieldKind.INTEGER, min_integer=1, max_integer=2),
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

    def validate(self, payload: dict[str, Any], input_refs: tuple[WorkOrderInputRef, ...]) -> dict[str, Any]:
        if len(input_refs) != 2:
            raise DispatchValidatorError("FFmpeg processing requires one AUDIO_SOURCE and one AUDIO_PROFILE")
        roles = {(ref.ref_type, ref.role) for ref in input_refs}
        if roles != {
            (WorkOrderRefType.ARTIFACT, FFMPEG_SOURCE_ROLE),
            (WorkOrderRefType.AUDIO_PROFILE, FFMPEG_PROFILE_ROLE),
        }:
            raise DispatchValidatorError("FFmpeg refs must be one audio_source Artifact and one audio_profile")
        normalized = self._base.validate(payload, input_refs)
        if normalized["operation"] != AudioOperation.PROCESS_AUDIO.value:
            raise DispatchValidatorError("FFmpeg operation must be PROCESS_AUDIO")
        output = normalized["output_relative_path"]
        if "\\" in output or output.startswith("/") or not output.startswith("exports/") or not output.lower().endswith(".wav"):
            raise DispatchValidatorError("FFmpeg output must be a workspace-relative WAV under exports/")
        return normalized


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
