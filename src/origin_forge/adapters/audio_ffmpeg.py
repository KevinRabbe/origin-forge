from __future__ import annotations

import hashlib
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from ..audio_models import (
    AudioOperation,
    AudioOperationRequest,
    AudioOperationResult,
    AudioOutputEvidence,
    AudioResultStatus,
    canonical_bytes,
)
from ..audio_profiles import AudioProfileKind, GovernedAudioProfile
from ..audio_wav import WavError, canonicalize_pcm16_wav, inspect_pcm16_wav
from ..runtime import OriginForgeRuntime


_MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024


class FfmpegAudioError(RuntimeError):
    pass


class FfmpegAudioIntegrityError(FfmpegAudioError):
    pass


class FfmpegAudioProcessError(FfmpegAudioError):
    pass


@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limit_exceeded: bool = False


class AudioProcessRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> ProcessOutcome: ...


class BoundedSubprocessRunner:
    """Run one process with bounded pipe capture and no shell/stdin surface."""

    @staticmethod
    def _read_bounded(
        stream,
        *,
        maximum: int,
        buffer: bytearray,
        overflow: threading.Event,
        process: subprocess.Popen[bytes],
    ) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                remaining = maximum + 1 - len(buffer)
                if remaining > 0:
                    buffer.extend(chunk[:remaining])
                if len(buffer) > maximum:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> ProcessOutcome:
        if not argv or any(not isinstance(value, str) or not value for value in argv):
            raise ValueError("argv must contain non-empty strings")
        for value, label in (
            (timeout_seconds, "timeout_seconds"),
            (max_stdout_bytes, "max_stdout_bytes"),
            (max_stderr_bytes, "max_stderr_bytes"),
        ):
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} must be positive")
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()
        threads = (
            threading.Thread(
                target=self._read_bounded,
                kwargs={
                    "stream": process.stdout,
                    "maximum": max_stdout_bytes,
                    "buffer": stdout,
                    "overflow": overflow,
                    "process": process,
                },
                daemon=True,
            ),
            threading.Thread(
                target=self._read_bounded,
                kwargs={
                    "stream": process.stderr,
                    "maximum": max_stderr_bytes,
                    "buffer": stderr,
                    "overflow": overflow,
                    "process": process,
                },
                daemon=True,
            ),
        )
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                process.kill()
            except OSError:
                pass
            returncode = process.wait()
        for thread in threads:
            thread.join(timeout=5)
        if any(thread.is_alive() for thread in threads):
            try:
                process.kill()
            except OSError:
                pass
            raise FfmpegAudioProcessError("failed to drain bounded process output")
        return ProcessOutcome(
            returncode=returncode,
            stdout=bytes(stdout[:max_stdout_bytes]),
            stderr=bytes(stderr[:max_stderr_bytes]),
            timed_out=timed_out,
            output_limit_exceeded=overflow.is_set(),
        )


@dataclass(frozen=True)
class FfmpegAudioExecution:
    request: AudioOperationRequest
    result: AudioOperationResult
    workspace_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.request.operation_id,
            "workspace_id": self.request.workspace_id,
            "request_hash": self.request.content_hash,
            "result_hash": self.result.content_hash,
            "status": self.result.status.value,
            "backend_id": self.result.backend_id,
            "backend_version": self.result.backend_version,
            "profile_id": self.result.profile_id,
            "profile_hash": self.result.profile_hash,
            "production_verification_changed": False,
            "canonical_asset_adopted": False,
        }


class FfmpegAudioAdapter:
    """One-shot fixed-argv FFmpeg PCM16 processor behind a governed profile."""

    BACKEND_ID = "ffmpeg"

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: GovernedAudioProfile,
        *,
        executable: Path,
        runner: AudioProcessRunner | None = None,
        max_process_output_bytes: int = _MAX_PROCESS_OUTPUT_BYTES,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, GovernedAudioProfile):
            raise TypeError("profile must be a GovernedAudioProfile")
        if profile.kind is not AudioProfileKind.FFMPEG_PCM16:
            raise ValueError("FFmpeg adapter requires an FFMPEG_PCM16 profile")
        if profile.operation is not AudioOperation.PROCESS_AUDIO:
            raise ValueError("FFmpeg profile must authorize PROCESS_AUDIO")
        if profile.backend_id != self.BACKEND_ID:
            raise ValueError("FFmpeg profile backend_id must be ffmpeg")
        if profile.model_id is not None or profile.model_hash is not None:
            raise ValueError("FFmpeg profile may not bind a model identity")
        if not isinstance(executable, Path):
            raise TypeError("executable must be a Path")
        if not isinstance(max_process_output_bytes, int) or not (
            1 <= max_process_output_bytes <= 16 * 1024 * 1024
        ):
            raise ValueError("max_process_output_bytes is outside allowed range")
        self.runtime = runtime
        self.profile = profile
        self.executable = executable
        self.runner = runner or BoundedSubprocessRunner()
        self.max_process_output_bytes = max_process_output_bytes
        self.workspace_root = runtime.state_dir / "audio-workspaces"

    def _verify_executable(self) -> None:
        if self.executable.is_symlink() or not self.executable.is_file():
            raise FfmpegAudioIntegrityError("FFmpeg executable must be a regular non-symlink file")
        actual = "sha256:" + hashlib.sha256(self.executable.read_bytes()).hexdigest()
        if actual != self.profile.runtime_hash:
            raise FfmpegAudioIntegrityError("FFmpeg executable hash does not match governed profile")
        outcome = self.runner.run(
            (str(self.executable), "-version"),
            cwd=self.runtime.state_dir,
            timeout_seconds=30,
            max_stdout_bytes=64 * 1024,
            max_stderr_bytes=64 * 1024,
        )
        self._require_process_success(outcome, "FFmpeg version probe")
        first_line = outcome.stdout.decode("utf-8", errors="strict").splitlines()
        expected_prefix = f"ffmpeg version {self.profile.backend_version}"
        if not first_line or not first_line[0].startswith(expected_prefix):
            raise FfmpegAudioIntegrityError("FFmpeg version does not match governed profile")

    def _workspace(self, request: AudioOperationRequest) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.workspace_root.is_symlink():
            raise FfmpegAudioIntegrityError("audio workspace root may not be a symlink")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        try:
            self.workspace_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise FfmpegAudioIntegrityError("audio workspace root escapes protected project state") from exc
        workspace = self.workspace_root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise FfmpegAudioIntegrityError(f"audio workspace already exists: {request.workspace_id}")
        workspace.mkdir()
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir()
        return workspace

    @staticmethod
    def _require_process_success(outcome: ProcessOutcome, label: str) -> None:
        if outcome.timed_out:
            raise FfmpegAudioProcessError(f"{label} timed out")
        if outcome.output_limit_exceeded:
            raise FfmpegAudioProcessError(f"{label} exceeded stdout/stderr budget")
        if outcome.returncode != 0:
            detail = outcome.stderr.decode("utf-8", errors="replace")[:1000]
            raise FfmpegAudioProcessError(
                f"{label} exited with {outcome.returncode}: {detail}"
            )

    @staticmethod
    def _source_bytes(
        request: AudioOperationRequest,
        source_bytes_by_id: Mapping[str, bytes],
    ) -> tuple[object, bytes]:
        if request.operation is not AudioOperation.PROCESS_AUDIO:
            raise FfmpegAudioIntegrityError("FFmpeg adapter accepts PROCESS_AUDIO only")
        if len(request.inputs) != 1:
            raise FfmpegAudioIntegrityError("FFmpeg request must contain exactly one source")
        source = request.inputs[0]
        if set(source_bytes_by_id) != {source.source_id}:
            raise FfmpegAudioIntegrityError("source byte set must exactly match frozen request")
        data = source_bytes_by_id[source.source_id]
        if not isinstance(data, bytes):
            raise FfmpegAudioIntegrityError("source audio payload must be bytes")
        actual_content = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual_content != source.content_hash or len(data) != source.byte_count:
            raise FfmpegAudioIntegrityError("source audio bytes do not match frozen evidence")
        try:
            inspection = inspect_pcm16_wav(data)
        except WavError as exc:
            raise FfmpegAudioIntegrityError("source audio is not accepted PCM16 WAV") from exc
        if (
            inspection.pcm_hash != source.pcm_hash
            or inspection.frame_count != source.frame_count
            or inspection.sample_rate != source.sample_rate
            or inspection.channels != source.channels
        ):
            raise FfmpegAudioIntegrityError("source audio structural evidence drifted")
        return source, data

    def _bind_request(self, request: AudioOperationRequest) -> None:
        if request.backend_id != self.profile.backend_id:
            raise FfmpegAudioIntegrityError("request backend_id does not match governed profile")
        if request.backend_version != self.profile.backend_version:
            raise FfmpegAudioIntegrityError("request backend_version does not match governed profile")
        if request.profile_id != self.profile.profile_id or request.profile_hash != self.profile.profile_hash:
            raise FfmpegAudioIntegrityError("request does not bind governed FFmpeg profile")
        if request.model_id is not None or request.model_hash is not None:
            raise FfmpegAudioIntegrityError("FFmpeg request may not bind a model")
        if request.target_sample_rate != self.profile.target_sample_rate:
            raise FfmpegAudioIntegrityError("request sample rate does not match governed profile")
        if request.target_channels != self.profile.target_channels:
            raise FfmpegAudioIntegrityError("request channel count does not match governed profile")

    def _argv(self, source: Path, raw_output: Path, request: AudioOperationRequest) -> tuple[str, ...]:
        return (
            str(self.executable),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "+bitexact",
            "-flags",
            "+bitexact",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-map_metadata",
            "-1",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            str(request.target_channels),
            "-ar",
            str(request.target_sample_rate),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            "-n",
            str(raw_output),
        )

    def execute(
        self,
        request: AudioOperationRequest,
        source_bytes_by_id: Mapping[str, bytes],
    ) -> FfmpegAudioExecution:
        if not isinstance(request, AudioOperationRequest):
            raise TypeError("request must be an AudioOperationRequest")
        self._bind_request(request)
        source_ref, source_data = self._source_bytes(request, source_bytes_by_id)
        self._verify_executable()
        workspace = self._workspace(request)
        request_path = workspace / "request" / "request.json"
        request_path.write_bytes(canonical_bytes(request.to_dict()))
        source_path = workspace / "inputs" / "source.wav"
        source_path.write_bytes(source_data)
        raw_output = workspace / "runtime" / "ffmpeg-output.wav"
        outcome = self.runner.run(
            self._argv(source_path, raw_output, request),
            cwd=workspace,
            timeout_seconds=request.timeout_seconds,
            max_stdout_bytes=self.max_process_output_bytes,
            max_stderr_bytes=self.max_process_output_bytes,
        )
        self._require_process_success(outcome, "FFmpeg audio processing")
        if raw_output.is_symlink() or not raw_output.is_file():
            raise FfmpegAudioIntegrityError("FFmpeg did not produce a regular output file")
        raw = raw_output.read_bytes()
        if len(raw) > 64 * 1024 * 1024:
            raise FfmpegAudioIntegrityError("FFmpeg output exceeds WAV byte limit")
        try:
            canonical = canonicalize_pcm16_wav(raw, max_duration_ms=request.max_duration_ms)
            inspection = inspect_pcm16_wav(canonical, max_duration_ms=request.max_duration_ms)
        except WavError as exc:
            raise FfmpegAudioIntegrityError("FFmpeg output is not accepted PCM16 WAV") from exc
        if inspection.sample_rate != request.target_sample_rate:
            raise FfmpegAudioIntegrityError("FFmpeg output sample rate drifted")
        if inspection.channels != request.target_channels:
            raise FfmpegAudioIntegrityError("FFmpeg output channel count drifted")
        output_path = workspace / request.output_relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() or output_path.is_symlink():
            raise FfmpegAudioIntegrityError("canonical FFmpeg output target already exists")
        output_path.write_bytes(canonical)
        output = AudioOutputEvidence(
            relative_path=request.output_relative_path,
            content_hash=inspection.content_hash,
            pcm_hash=inspection.pcm_hash,
            byte_count=inspection.byte_count,
            frame_count=inspection.frame_count,
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
            peak_abs_sample=inspection.peak_abs_sample,
            clipped_sample_count=inspection.clipped_sample_count,
            nonzero_sample_count=inspection.nonzero_sample_count,
        )
        result = AudioOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=AudioResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            profile_id=request.profile_id,
            profile_hash=request.profile_hash,
            model_id=None,
            model_hash=None,
            outputs=(output,),
        )
        result.bind_request(request)
        return FfmpegAudioExecution(request=request, result=result, workspace_path=workspace)
