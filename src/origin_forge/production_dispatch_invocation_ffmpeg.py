from __future__ import annotations

from dataclasses import dataclass

from .audio_models import AudioOperation, AudioOperationRequest, AudioSourceRef
from .audio_profiles import AudioProfileKind, GovernedAudioProfile
from .ids import IdKind, validate_id
from .production_work_order_audio import FfmpegAudioDispatchValidator
from .production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)


class FfmpegInvocationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FfmpegInvocationRequest:
    """Exact frozen FFmpeg request; runtime IDs are post-STARTED authority."""

    task_id: str
    profile_id: str
    profile_hash: str
    source_artifact_id: str
    source_content_hash: str
    source_relative_path: str
    source_pcm_hash: str
    source_byte_count: int
    source_frame_count: int
    source_sample_rate: int
    source_channels: int
    target_sample_rate: int
    target_channels: int
    max_duration_ms: int
    timeout_seconds: int
    output_relative_path: str
    request_content_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.task_id, IdKind.TASK):
            raise FfmpegInvocationError("FFmpeg request task_id is invalid")
        if not validate_id(self.profile_id, IdKind.AUDIO_PROFILE):
            raise FfmpegInvocationError("FFmpeg request profile_id is invalid")
        if not validate_id(self.source_artifact_id, IdKind.ARTIFACT):
            raise FfmpegInvocationError("FFmpeg source Artifact ID is invalid")
        for value, label in (
            (self.profile_hash, "profile_hash"),
            (self.source_content_hash, "source_content_hash"),
            (self.source_pcm_hash, "source_pcm_hash"),
            (self.request_content_hash, "request_content_hash"),
        ):
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise FfmpegInvocationError(f"FFmpeg request {label} is invalid")
        projection = self.projection_dict()
        source_ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT, self.source_artifact_id, self.source_content_hash, "audio_source", None
        )
        profile_ref = WorkOrderInputRef(
            WorkOrderRefType.AUDIO_PROFILE, self.profile_id, self.profile_hash, "audio_profile", None
        )
        try:
            normalized = FfmpegAudioDispatchValidator().validate(
                {
                    key: value for key, value in projection.items()
                    if key not in {
                        "task_id", "profile_id", "profile_hash", "source_artifact_id",
                        "source_content_hash", "source_relative_path", "source_pcm_hash",
                        "source_byte_count", "source_frame_count", "source_sample_rate", "source_channels",
                    }
                },
                (source_ref, profile_ref),
            )
        except Exception as exc:
            raise FfmpegInvocationError("FFmpeg request violates the frozen WorkOrder contract") from exc
        if {**projection, **normalized} != projection or content_hash(projection) != self.request_content_hash:
            raise FfmpegInvocationError("FFmpeg request is not canonical")

    def projection_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "source_artifact_id": self.source_artifact_id,
            "source_content_hash": self.source_content_hash,
            "source_relative_path": self.source_relative_path,
            "source_pcm_hash": self.source_pcm_hash,
            "source_byte_count": self.source_byte_count,
            "source_frame_count": self.source_frame_count,
            "source_sample_rate": self.source_sample_rate,
            "source_channels": self.source_channels,
            "operation": AudioOperation.PROCESS_AUDIO.value,
            "target_sample_rate": self.target_sample_rate,
            "target_channels": self.target_channels,
            "max_duration_ms": self.max_duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "output_relative_path": self.output_relative_path,
        }

    @classmethod
    def from_projection(cls, projection: dict[str, object], request_content_hash: str) -> FfmpegInvocationRequest:
        fields = {
            "task_id", "profile_id", "profile_hash", "source_artifact_id", "source_content_hash",
            "source_relative_path", "source_pcm_hash", "source_byte_count", "source_frame_count",
            "source_sample_rate", "source_channels", "operation", "target_sample_rate",
            "target_channels", "max_duration_ms", "timeout_seconds", "output_relative_path",
        }
        if not isinstance(projection, dict) or set(projection) != fields:
            raise FfmpegInvocationError("FFmpeg request projection has unknown or missing fields")
        if projection["operation"] != AudioOperation.PROCESS_AUDIO.value:
            raise FfmpegInvocationError("FFmpeg request operation drifted")
        try:
            request = cls(
                task_id=projection["task_id"], profile_id=projection["profile_id"], profile_hash=projection["profile_hash"],
                source_artifact_id=projection["source_artifact_id"], source_content_hash=projection["source_content_hash"],
                source_relative_path=projection["source_relative_path"], source_pcm_hash=projection["source_pcm_hash"],
                source_byte_count=projection["source_byte_count"], source_frame_count=projection["source_frame_count"],
                source_sample_rate=projection["source_sample_rate"], source_channels=projection["source_channels"],
                target_sample_rate=projection["target_sample_rate"], target_channels=projection["target_channels"],
                max_duration_ms=projection["max_duration_ms"], timeout_seconds=projection["timeout_seconds"],
                output_relative_path=projection["output_relative_path"], request_content_hash=request_content_hash,
            )
        except (TypeError, ValueError) as exc:
            raise FfmpegInvocationError("FFmpeg request projection cannot be reconstructed") from exc
        if request.projection_dict() != projection:
            raise FfmpegInvocationError("FFmpeg request projection is not canonical")
        return request

    def to_operation_request(self, profile: GovernedAudioProfile) -> AudioOperationRequest:
        if not isinstance(profile, GovernedAudioProfile):
            raise TypeError("profile must be a GovernedAudioProfile")
        if profile.profile_id != self.profile_id or profile.profile_hash != "sha256:" + self.profile_hash:
            raise FfmpegInvocationError("FFmpeg profile does not match frozen request")
        if profile.kind is not AudioProfileKind.FFMPEG_PCM16 or profile.operation is not AudioOperation.PROCESS_AUDIO:
            raise FfmpegInvocationError("FFmpeg profile does not authorize PROCESS_AUDIO")
        if profile.target_sample_rate != self.target_sample_rate or profile.target_channels != self.target_channels:
            raise FfmpegInvocationError("FFmpeg target format does not match governed profile")
        source = AudioSourceRef(
            source_id=self.source_artifact_id,
            relative_path=self.source_relative_path,
            content_hash="sha256:" + self.source_content_hash,
            pcm_hash="sha256:" + self.source_pcm_hash,
            byte_count=self.source_byte_count,
            frame_count=self.source_frame_count,
            sample_rate=self.source_sample_rate,
            channels=self.source_channels,
        )
        return AudioOperationRequest.create(
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id=profile.backend_id,
            backend_version=profile.backend_version,
            profile_id=profile.profile_id,
            profile_hash=profile.profile_hash,
            inputs=(source,),
            target_sample_rate=self.target_sample_rate,
            target_channels=self.target_channels,
            max_duration_ms=self.max_duration_ms,
            timeout_seconds=self.timeout_seconds,
            output_relative_path=self.output_relative_path,
        )
