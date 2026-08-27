from __future__ import annotations

from dataclasses import dataclass

from .ids import IdKind, validate_id
from .production_dispatch_execution_models import DispatchExecution

AUDIO_EXECUTION_OWNER_ID = "originforge.execution.audio.piper-tts@1"
FFMPEG_AUDIO_EXECUTION_OWNER_ID = "originforge.execution.audio.ffmpeg-process@1"
AUDIO_EXECUTION_OWNER_IDS = frozenset({AUDIO_EXECUTION_OWNER_ID, FFMPEG_AUDIO_EXECUTION_OWNER_ID})


class AudioDispatchOutputBindingModelError(ValueError):
    pass


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise AudioDispatchOutputBindingModelError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise AudioDispatchOutputBindingModelError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class AudioDispatchOutputBinding:
    execution_id: str
    claim_id: str
    task_id: str
    task_revision: int
    task_content_hash: str
    work_order_id: str
    work_order_hash: str
    dispatch_binding_id: str
    dispatch_binding_hash: str
    execution_owner_id: str
    run_id: str
    request_artifact_id: str
    result_artifact_id: str
    output_artifact_id: str
    output_verification_id: str
    output_relative_path: str
    output_content_hash: str
    output_pcm_hash: str
    output_byte_count: int
    output_frame_count: int
    output_sample_rate: int
    output_channels: int
    output_peak_abs_sample: int
    output_clipped_sample_count: int
    output_nonzero_sample_count: int
    backend_result_hash: str
    schema_version: int
    created_at: str

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id"),
            (self.claim_id, IdKind.DISPATCH_CLAIM, "claim_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.work_order_id, IdKind.PRODUCTION_WORK_ORDER, "work_order_id"),
            (self.dispatch_binding_id, IdKind.DISPATCH_BINDING, "dispatch_binding_id"),
            (self.run_id, IdKind.RUN, "run_id"),
            (self.request_artifact_id, IdKind.ARTIFACT, "request_artifact_id"),
            (self.result_artifact_id, IdKind.ARTIFACT, "result_artifact_id"),
            (self.output_artifact_id, IdKind.ARTIFACT, "output_artifact_id"),
            (self.output_verification_id, IdKind.VERIFICATION, "output_verification_id"),
        ):
            _id(value, kind, label)
        if self.execution_owner_id not in AUDIO_EXECUTION_OWNER_IDS:
            raise AudioDispatchOutputBindingModelError("audio binding owner is not trusted")
        if type(self.task_revision) is not int or self.task_revision < 0:
            raise AudioDispatchOutputBindingModelError("task_revision is invalid")
        for digest_value, label in (
            (self.task_content_hash, "task_content_hash"),
            (self.work_order_hash, "work_order_hash"),
            (self.dispatch_binding_hash, "dispatch_binding_hash"),
            (self.output_content_hash, "output_content_hash"),
            (self.output_pcm_hash, "output_pcm_hash"),
            (self.backend_result_hash, "backend_result_hash"),
        ):
            _digest(digest_value, label)
        if not isinstance(self.output_relative_path, str) or not self.output_relative_path.startswith("exports/") or not self.output_relative_path.lower().endswith(".wav"):
            raise AudioDispatchOutputBindingModelError("audio output path is invalid")
        for metric_value, label in (
            (self.output_byte_count, "output_byte_count"),
            (self.output_frame_count, "output_frame_count"),
            (self.output_sample_rate, "output_sample_rate"),
        ):
            if type(metric_value) is not int or metric_value <= 0:
                raise AudioDispatchOutputBindingModelError(f"{label} is invalid")
        if self.output_channels not in {1, 2} or not 0 <= self.output_peak_abs_sample <= 32768:
            raise AudioDispatchOutputBindingModelError("audio output format metrics are invalid")
        if self.output_clipped_sample_count < 0 or self.output_nonzero_sample_count < 0:
            raise AudioDispatchOutputBindingModelError("audio output sample metrics are invalid")
        if self.schema_version != 1 or not isinstance(self.created_at, str) or not self.created_at:
            raise AudioDispatchOutputBindingModelError("audio binding metadata is invalid")

    @classmethod
    def from_execution_result(cls, execution: DispatchExecution, result, *, created_at: str) -> AudioDispatchOutputBinding:
        if execution.execution_owner_id not in AUDIO_EXECUTION_OWNER_IDS:
            raise AudioDispatchOutputBindingModelError("execution is not owned by a trusted audio owner")
        output = result.output
        return cls(
            execution_id=execution.execution_id, claim_id=execution.claim_id,
            task_id=execution.task_id, task_revision=execution.task_revision,
            task_content_hash=execution.task_content_hash, work_order_id=execution.work_order_id,
            work_order_hash=execution.work_order_hash, dispatch_binding_id=execution.dispatch_binding_id,
            dispatch_binding_hash=execution.dispatch_binding_hash, execution_owner_id=execution.execution_owner_id,
            run_id=result.run_id, request_artifact_id=result.request_artifact_id,
            result_artifact_id=result.result_artifact_id, output_artifact_id=output.artifact_id,
            output_verification_id=output.verification_id, output_relative_path=output.relative_path,
            output_content_hash=output.content_hash.removeprefix("sha256:"),
            output_pcm_hash=output.pcm_hash.removeprefix("sha256:"), output_byte_count=output.byte_count,
            output_frame_count=output.frame_count, output_sample_rate=output.sample_rate,
            output_channels=output.channels, output_peak_abs_sample=output.peak_abs_sample,
            output_clipped_sample_count=output.clipped_sample_count,
            output_nonzero_sample_count=output.nonzero_sample_count,
            backend_result_hash=result.backend_result_hash.removeprefix("sha256:"),
            schema_version=1, created_at=created_at,
        )
