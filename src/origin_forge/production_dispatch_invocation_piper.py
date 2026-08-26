from __future__ import annotations

from dataclasses import dataclass

from .audio_models import AudioOperation, AudioOperationRequest
from .audio_profiles import GovernedAudioProfile
from .ids import IdKind, validate_id
from .production_work_order_audio import PiperSpeechDispatchValidator
from .production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)


class PiperInvocationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PiperInvocationRequest:
    """Exact frozen Piper request; runtime IDs are post-STARTED authority."""

    task_id: str
    profile_id: str
    profile_hash: str
    text: str
    max_duration_ms: int
    timeout_seconds: int
    output_relative_path: str
    request_content_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.task_id, IdKind.TASK):
            raise PiperInvocationError("Piper request task_id is invalid")
        if not validate_id(self.profile_id, IdKind.AUDIO_PROFILE):
            raise PiperInvocationError("Piper request profile_id is invalid")
        if not isinstance(self.profile_hash, str) or len(self.profile_hash) != 64 or any(
            char not in "0123456789abcdef" for char in self.profile_hash
        ):
            raise PiperInvocationError("Piper request profile_hash is invalid")
        if not isinstance(self.request_content_hash, str) or len(self.request_content_hash) != 64:
            raise PiperInvocationError("Piper request content hash is invalid")
        projection = self.projection_dict()
        try:
            normalized = PiperSpeechDispatchValidator().validate(
                {
                    key: value for key, value in projection.items()
                    if key not in {"task_id", "profile_id", "profile_hash"}
                },
                (
                    WorkOrderInputRef(
                        WorkOrderRefType.AUDIO_PROFILE,
                        self.profile_id,
                        self.profile_hash,
                        "audio_profile",
                    ),
                ),
            )
        except Exception as exc:
            raise PiperInvocationError("Piper request violates the frozen WorkOrder contract") from exc
        expected = {
            "task_id": self.task_id,
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            **normalized,
        }
        if expected != projection or content_hash(projection) != self.request_content_hash:
            raise PiperInvocationError("Piper request is not canonical")

    def projection_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "operation": AudioOperation.SYNTHESIZE_SPEECH.value,
            "text": self.text,
            "max_duration_ms": self.max_duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "output_relative_path": self.output_relative_path,
        }

    @classmethod
    def from_projection(
        cls, projection: dict[str, object], request_content_hash: str
    ) -> PiperInvocationRequest:
        if not isinstance(projection, dict) or set(projection) != {
            "task_id", "profile_id", "profile_hash", "operation", "text",
            "max_duration_ms", "timeout_seconds", "output_relative_path",
        }:
            raise PiperInvocationError("Piper request projection has unknown or missing fields")
        if projection["operation"] != AudioOperation.SYNTHESIZE_SPEECH.value:
            raise PiperInvocationError("Piper request operation drifted")
        task_id = projection["task_id"]
        profile_id = projection["profile_id"]
        profile_hash = projection["profile_hash"]
        text = projection["text"]
        max_duration_ms = projection["max_duration_ms"]
        timeout_seconds = projection["timeout_seconds"]
        output_relative_path = projection["output_relative_path"]
        if (
            not isinstance(task_id, str)
            or not isinstance(profile_id, str)
            or not isinstance(profile_hash, str)
            or not isinstance(text, str)
            or not isinstance(output_relative_path, str)
        ):
            raise PiperInvocationError("Piper request text or identity fields are invalid")
        if (
            isinstance(max_duration_ms, bool)
            or not isinstance(max_duration_ms, int)
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
        ):
            raise PiperInvocationError("Piper request duration or timeout fields are invalid")
        try:
            request = cls(
                task_id=task_id,
                profile_id=profile_id,
                profile_hash=profile_hash,
                text=text,
                max_duration_ms=max_duration_ms,
                timeout_seconds=timeout_seconds,
                output_relative_path=output_relative_path,
                request_content_hash=request_content_hash,
            )
        except (TypeError, ValueError) as exc:
            raise PiperInvocationError("Piper request projection cannot be reconstructed") from exc
        if request.projection_dict() != projection:
            raise PiperInvocationError("Piper request projection is not canonical")
        return request

    def to_operation_request(self, profile: GovernedAudioProfile) -> AudioOperationRequest:
        if not isinstance(profile, GovernedAudioProfile):
            raise TypeError("profile must be a GovernedAudioProfile")
        if profile.profile_id != self.profile_id or profile.profile_hash != "sha256:" + self.profile_hash:
            raise PiperInvocationError("Piper profile does not match frozen request")
        if profile.operation is not AudioOperation.SYNTHESIZE_SPEECH:
            raise PiperInvocationError("Piper profile operation is not speech synthesis")
        if profile.model_id is None or profile.model_hash is None:
            raise PiperInvocationError("Piper profile has no governed model identity")
        return AudioOperationRequest.create(
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id=profile.backend_id,
            backend_version=profile.backend_version,
            profile_id=profile.profile_id,
            profile_hash=profile.profile_hash,
            model_id=profile.model_id,
            model_hash=profile.model_hash,
            text=self.text,
            target_sample_rate=profile.target_sample_rate,
            target_channels=profile.target_channels,
            max_duration_ms=self.max_duration_ms,
            timeout_seconds=self.timeout_seconds,
            output_relative_path=self.output_relative_path,
        )
