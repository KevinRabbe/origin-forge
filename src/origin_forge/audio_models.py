from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Iterable

from .ids import IdKind, new_id, validate_id


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_MAX_TEXT = 16_384
_MAX_PROMPT = 8_192
_MAX_INPUTS = 16
_MAX_DURATION_MS = 10 * 60 * 1000
_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 192_000


class AudioModelError(ValueError):
    pass


class AudioOperation(StrEnum):
    SYNTHESIZE_SFX = "SYNTHESIZE_SFX"
    SYNTHESIZE_SPEECH = "SYNTHESIZE_SPEECH"
    GENERATE_MUSIC = "GENERATE_MUSIC"
    PROCESS_AUDIO = "PROCESS_AUDIO"


class AudioResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AudioModelError("audio value must be finite JSON data") from exc


def content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise AudioModelError(f"{label} must be lowercase sha256:<64 hex>")
    return value


def _text(value: str, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise AudioModelError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise AudioModelError(f"{label} must be non-empty")
    if "\x00" in normalized:
        raise AudioModelError(f"{label} contains NUL")
    if len(normalized) > maximum:
        raise AudioModelError(f"{label} exceeds character limit")
    return normalized


def _optional_text(value: str | None, label: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, label, maximum=maximum)


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise AudioModelError(f"{label} must be a bounded identity token")
    return value


def _wav_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AudioModelError(f"{label} must be a non-empty path")
    if "\\" in value or "\x00" in value:
        raise AudioModelError(f"{label} must use portable forward slashes")
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/"):
        raise AudioModelError(f"{label} must be workspace-relative")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise AudioModelError(f"{label} contains unsafe path components")
    normalized = path.as_posix()
    if normalized != value:
        raise AudioModelError(f"{label} must be canonical")
    if path.suffix.lower() != ".wav":
        raise AudioModelError(f"{label} must name a .wav file")
    return normalized


@dataclass(frozen=True)
class AudioSourceRef:
    source_id: str
    relative_path: str
    content_hash: str
    pcm_hash: str
    byte_count: int
    frame_count: int
    sample_rate: int
    channels: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _token(self.source_id, "source_id"))
        object.__setattr__(
            self, "relative_path", _wav_path(self.relative_path, "source relative_path")
        )
        validate_sha256(self.content_hash, "source content_hash")
        validate_sha256(self.pcm_hash, "source pcm_hash")
        if not isinstance(self.byte_count, int) or self.byte_count <= 0:
            raise AudioModelError("source byte_count must be positive")
        if not isinstance(self.frame_count, int) or self.frame_count <= 0:
            raise AudioModelError("source frame_count must be positive")
        if not isinstance(self.sample_rate, int) or not (
            _MIN_SAMPLE_RATE <= self.sample_rate <= _MAX_SAMPLE_RATE
        ):
            raise AudioModelError("source sample_rate is outside allowed range")
        if self.channels not in {1, 2}:
            raise AudioModelError("source channels must be mono or stereo")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "pcm_hash": self.pcm_hash,
            "byte_count": self.byte_count,
            "frame_count": self.frame_count,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }


@dataclass(frozen=True)
class AudioOperationRequest:
    operation_id: str
    workspace_id: str
    operation: AudioOperation
    backend_id: str
    backend_version: str
    profile_id: str
    profile_hash: str
    model_id: str | None
    model_hash: str | None
    inputs: tuple[AudioSourceRef, ...]
    prompt: str | None
    text: str | None
    seed: int | None
    target_sample_rate: int
    target_channels: int
    max_duration_ms: int
    timeout_seconds: int
    output_relative_path: str

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.AUDIO_OPERATION):
            raise AudioModelError("operation_id must be an AUDOP ID")
        if not validate_id(self.workspace_id, IdKind.AUDIO_WORKSPACE):
            raise AudioModelError("workspace_id must be an AUDIO ID")
        if not isinstance(self.operation, AudioOperation):
            raise AudioModelError("operation must be an AudioOperation")
        object.__setattr__(self, "backend_id", _token(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _token(self.backend_version, "backend_version")
        )
        if not validate_id(self.profile_id, IdKind.AUDIO_PROFILE):
            raise AudioModelError("profile_id must be an AUDPROF ID")
        validate_sha256(self.profile_hash, "profile_hash")
        if (self.model_id is None) != (self.model_hash is None):
            raise AudioModelError("model_id and model_hash must be supplied together")
        if self.model_id is not None:
            object.__setattr__(self, "model_id", _token(self.model_id, "model_id"))
            validate_sha256(self.model_hash or "", "model_hash")
        inputs = tuple(self.inputs)
        if len(inputs) > _MAX_INPUTS:
            raise AudioModelError("inputs exceed count limit")
        if len({value.source_id for value in inputs}) != len(inputs):
            raise AudioModelError("inputs contain duplicate source_id values")
        object.__setattr__(self, "inputs", tuple(sorted(inputs, key=lambda value: value.source_id)))
        object.__setattr__(
            self, "prompt", _optional_text(self.prompt, "prompt", maximum=_MAX_PROMPT)
        )
        object.__setattr__(self, "text", _optional_text(self.text, "text", maximum=_MAX_TEXT))
        if self.seed is not None and (
            not isinstance(self.seed, int) or not 0 <= self.seed <= (2**63 - 1)
        ):
            raise AudioModelError("seed must be an unsigned bounded integer")
        if not isinstance(self.target_sample_rate, int) or not (
            _MIN_SAMPLE_RATE <= self.target_sample_rate <= _MAX_SAMPLE_RATE
        ):
            raise AudioModelError("target_sample_rate is outside allowed range")
        if self.target_channels not in {1, 2}:
            raise AudioModelError("target_channels must be mono or stereo")
        if not isinstance(self.max_duration_ms, int) or not (
            1 <= self.max_duration_ms <= _MAX_DURATION_MS
        ):
            raise AudioModelError("max_duration_ms is outside allowed range")
        if not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= 3600:
            raise AudioModelError("timeout_seconds is outside allowed range")
        output = _wav_path(self.output_relative_path, "output_relative_path")
        if not output.startswith("exports/"):
            raise AudioModelError("output_relative_path must be below exports/")
        object.__setattr__(self, "output_relative_path", output)
        self._validate_operation_shape()

    def _validate_operation_shape(self) -> None:
        if self.operation is AudioOperation.PROCESS_AUDIO:
            if len(self.inputs) != 1:
                raise AudioModelError("PROCESS_AUDIO requires exactly one input")
            if self.prompt is not None or self.text is not None or self.seed is not None:
                raise AudioModelError("PROCESS_AUDIO does not accept prompt/text/seed")
        elif self.operation is AudioOperation.SYNTHESIZE_SPEECH:
            if self.inputs or self.prompt is not None or self.seed is not None:
                raise AudioModelError("SYNTHESIZE_SPEECH accepts only text input")
            if self.text is None:
                raise AudioModelError("SYNTHESIZE_SPEECH requires text")
            if self.model_id is None:
                raise AudioModelError("SYNTHESIZE_SPEECH requires exact voice/model identity")
        elif self.operation in {
            AudioOperation.SYNTHESIZE_SFX,
            AudioOperation.GENERATE_MUSIC,
        }:
            if self.inputs or self.text is not None:
                raise AudioModelError(f"{self.operation.value} accepts only prompt + seed")
            if self.prompt is None or self.seed is None:
                raise AudioModelError(f"{self.operation.value} requires prompt + seed")
        else:
            raise AudioModelError("unsupported audio operation")

    @classmethod
    def create(
        cls,
        *,
        operation: AudioOperation,
        backend_id: str,
        backend_version: str,
        profile_id: str,
        profile_hash: str,
        model_id: str | None = None,
        model_hash: str | None = None,
        inputs: Iterable[AudioSourceRef] = (),
        prompt: str | None = None,
        text: str | None = None,
        seed: int | None = None,
        target_sample_rate: int = 48_000,
        target_channels: int = 1,
        max_duration_ms: int = 60_000,
        timeout_seconds: int = 300,
        output_relative_path: str = "exports/output.wav",
    ) -> "AudioOperationRequest":
        return cls(
            operation_id=new_id(IdKind.AUDIO_OPERATION),
            workspace_id=new_id(IdKind.AUDIO_WORKSPACE),
            operation=operation,
            backend_id=backend_id,
            backend_version=backend_version,
            profile_id=profile_id,
            profile_hash=profile_hash,
            model_id=model_id,
            model_hash=model_hash,
            inputs=tuple(inputs),
            prompt=prompt,
            text=text,
            seed=seed,
            target_sample_rate=target_sample_rate,
            target_channels=target_channels,
            max_duration_ms=max_duration_ms,
            timeout_seconds=timeout_seconds,
            output_relative_path=output_relative_path,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "operation": self.operation.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "inputs": [value.to_dict() for value in self.inputs],
            "prompt": self.prompt,
            "text": self.text,
            "seed": self.seed,
            "target_sample_rate": self.target_sample_rate,
            "target_channels": self.target_channels,
            "max_duration_ms": self.max_duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "output_relative_path": self.output_relative_path,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class AudioOutputEvidence:
    relative_path: str
    content_hash: str
    pcm_hash: str
    byte_count: int
    frame_count: int
    sample_rate: int
    channels: int
    peak_abs_sample: int
    clipped_sample_count: int
    nonzero_sample_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", _wav_path(self.relative_path, "output path"))
        validate_sha256(self.content_hash, "output content_hash")
        validate_sha256(self.pcm_hash, "output pcm_hash")
        if not isinstance(self.byte_count, int) or self.byte_count <= 0:
            raise AudioModelError("output byte_count must be positive")
        if not isinstance(self.frame_count, int) or self.frame_count <= 0:
            raise AudioModelError("output frame_count must be positive")
        if not isinstance(self.sample_rate, int) or not (
            _MIN_SAMPLE_RATE <= self.sample_rate <= _MAX_SAMPLE_RATE
        ):
            raise AudioModelError("output sample_rate is outside allowed range")
        if self.channels not in {1, 2}:
            raise AudioModelError("output channels must be mono or stereo")
        if not isinstance(self.peak_abs_sample, int) or not 0 <= self.peak_abs_sample <= 32768:
            raise AudioModelError("peak_abs_sample is outside PCM16 range")
        sample_count = self.frame_count * self.channels
        for value, label in (
            (self.clipped_sample_count, "clipped_sample_count"),
            (self.nonzero_sample_count, "nonzero_sample_count"),
        ):
            if not isinstance(value, int) or not 0 <= value <= sample_count:
                raise AudioModelError(f"{label} is outside sample-count range")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "pcm_hash": self.pcm_hash,
            "byte_count": self.byte_count,
            "frame_count": self.frame_count,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "peak_abs_sample": self.peak_abs_sample,
            "clipped_sample_count": self.clipped_sample_count,
            "nonzero_sample_count": self.nonzero_sample_count,
        }


@dataclass(frozen=True)
class AudioOperationResult:
    operation_id: str
    workspace_id: str
    request_hash: str
    status: AudioResultStatus
    backend_id: str
    backend_version: str
    profile_id: str
    profile_hash: str
    model_id: str | None
    model_hash: str | None
    outputs: tuple[AudioOutputEvidence, ...]
    detail: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.AUDIO_OPERATION):
            raise AudioModelError("result operation_id must be an AUDOP ID")
        if not validate_id(self.workspace_id, IdKind.AUDIO_WORKSPACE):
            raise AudioModelError("result workspace_id must be an AUDIO ID")
        validate_sha256(self.request_hash, "result request_hash")
        if not isinstance(self.status, AudioResultStatus):
            raise AudioModelError("status must be an AudioResultStatus")
        object.__setattr__(self, "backend_id", _token(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _token(self.backend_version, "backend_version")
        )
        if not validate_id(self.profile_id, IdKind.AUDIO_PROFILE):
            raise AudioModelError("result profile_id must be an AUDPROF ID")
        validate_sha256(self.profile_hash, "result profile_hash")
        if (self.model_id is None) != (self.model_hash is None):
            raise AudioModelError("result model_id and model_hash must be supplied together")
        if self.model_id is not None:
            object.__setattr__(self, "model_id", _token(self.model_id, "model_id"))
            validate_sha256(self.model_hash or "", "result model_hash")
        outputs = tuple(self.outputs)
        if self.status is AudioResultStatus.SUCCEEDED and len(outputs) != 1:
            raise AudioModelError("successful audio result requires exactly one output")
        if self.status is not AudioResultStatus.SUCCEEDED and outputs:
            raise AudioModelError("failed/blocked audio result may not claim outputs")
        object.__setattr__(self, "outputs", outputs)
        object.__setattr__(self, "detail", _optional_text(self.detail, "detail", maximum=2048))

    def bind_request(self, request: AudioOperationRequest) -> None:
        if not isinstance(request, AudioOperationRequest):
            raise TypeError("request must be an AudioOperationRequest")
        expected = (
            request.operation_id,
            request.workspace_id,
            request.content_hash,
            request.backend_id,
            request.backend_version,
            request.profile_id,
            request.profile_hash,
            request.model_id,
            request.model_hash,
        )
        actual = (
            self.operation_id,
            self.workspace_id,
            self.request_hash,
            self.backend_id,
            self.backend_version,
            self.profile_id,
            self.profile_hash,
            self.model_id,
            self.model_hash,
        )
        if actual != expected:
            raise AudioModelError("audio result does not bind the frozen request")
        if self.status is AudioResultStatus.SUCCEEDED:
            output = self.outputs[0]
            if output.relative_path != request.output_relative_path:
                raise AudioModelError("audio result output path does not match request")
            if output.sample_rate != request.target_sample_rate:
                raise AudioModelError("audio result sample rate does not match request")
            if output.channels != request.target_channels:
                raise AudioModelError("audio result channels do not match request")
            if output.frame_count * 1000 > output.sample_rate * request.max_duration_ms:
                raise AudioModelError("audio result exceeds frozen duration budget")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "request_hash": self.request_hash,
            "status": self.status.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "outputs": [value.to_dict() for value in self.outputs],
            "detail": self.detail,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
