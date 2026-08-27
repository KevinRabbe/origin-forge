from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..audio_models import (
    AudioOperation,
    AudioOperationRequest,
    AudioOperationResult,
    AudioOutputEvidence,
    AudioResultStatus,
    canonical_bytes,
    content_hash,
)
from ..audio_profiles import AudioProfileKind, GovernedAudioProfile
from ..audio_wav import WavError, inspect_pcm16_wav
from ..runtime import OriginForgeRuntime
from .audio_piper_wav import canonicalize_piper_output_wav

_MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
_MAX_RUNTIME_FILES = 8192
_MAX_RUNTIME_BYTES = 4 * 1024 * 1024 * 1024
_MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_MAX_LICENSE_BYTES = 4 * 1024 * 1024
_MAX_WAV_BYTES = 64 * 1024 * 1024
_MAX_STDIN_BYTES = 64 * 1024


class PiperAudioError(RuntimeError):
    pass


class PiperAudioIntegrityError(PiperAudioError):
    pass


class PiperAudioProcessError(PiperAudioError):
    pass


@dataclass(frozen=True)
class PiperProcessOutcome:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limit_exceeded: bool = False


class PiperProcessRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        stdin_bytes: bytes,
        timeout_seconds: int,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> PiperProcessOutcome: ...


class BoundedPiperSubprocessRunner:
    """Run one local Piper process with bounded stdin/stdout/stderr and no shell."""

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

    @staticmethod
    def _clean_environment(cwd: Path) -> dict[str, str]:
        env = {
            "PATH": os.defpath,
            "HOME": str(cwd),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if os.name == "nt":
            for name in ("SystemRoot", "WINDIR"):
                value = os.environ.get(name)
                if value:
                    env[name] = value
        return env

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        stdin_bytes: bytes,
        timeout_seconds: int,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> PiperProcessOutcome:
        if not argv or any(not isinstance(value, str) or not value for value in argv):
            raise ValueError("argv must contain non-empty strings")
        if not isinstance(stdin_bytes, bytes) or len(stdin_bytes) > _MAX_STDIN_BYTES:
            raise ValueError("stdin_bytes must be bounded bytes")
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
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            env=self._clean_environment(cwd),
        )
        assert process.stdin is not None
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
        try:
            try:
                process.stdin.write(stdin_bytes)
                process.stdin.flush()
            except BrokenPipeError:
                pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
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
            raise PiperAudioProcessError("failed to drain bounded Piper process output")
        return PiperProcessOutcome(
            returncode=returncode,
            stdout=bytes(stdout[:max_stdout_bytes]),
            stderr=bytes(stderr[:max_stderr_bytes]),
            timed_out=timed_out,
            output_limit_exceeded=overflow.is_set(),
        )


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _regular_file_bytes(path: Path, *, maximum: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PiperAudioIntegrityError(f"{label} must be a regular non-symlink file")
    size = path.stat().st_size
    if size < 1 or size > maximum:
        raise PiperAudioIntegrityError(f"{label} is outside byte limit")
    data = path.read_bytes()
    if len(data) != size:
        raise PiperAudioIntegrityError(f"{label} changed while being read")
    return data


def piper_runtime_tree_hash(
    runtime_root: Path,
    *,
    max_files: int = _MAX_RUNTIME_FILES,
    max_total_bytes: int = _MAX_RUNTIME_BYTES,
) -> str:
    """Content-address one symlink-free Piper-owned runtime tree."""
    if not isinstance(runtime_root, Path):
        raise TypeError("runtime_root must be a Path")
    if runtime_root.is_symlink() or not runtime_root.is_dir():
        raise PiperAudioIntegrityError("Piper runtime root must be a regular directory")
    if not isinstance(max_files, int) or not 1 <= max_files <= _MAX_RUNTIME_FILES:
        raise ValueError("max_files is outside allowed range")
    if not isinstance(max_total_bytes, int) or not 1 <= max_total_bytes <= _MAX_RUNTIME_BYTES:
        raise ValueError("max_total_bytes is outside allowed range")
    files: list[dict[str, object]] = []
    total = 0
    for path in sorted(runtime_root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            raise PiperAudioIntegrityError("Piper runtime tree may not contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PiperAudioIntegrityError("Piper runtime tree contains an undeclared entry")
        relative = path.relative_to(runtime_root).as_posix()
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise PiperAudioIntegrityError("Piper runtime tree contains an unsafe path")
        size = path.stat().st_size
        if size < 0:
            raise PiperAudioIntegrityError("Piper runtime file size is invalid")
        total += size
        if total > max_total_bytes:
            raise PiperAudioIntegrityError("Piper runtime tree exceeds byte limit")
        data = path.read_bytes()
        if len(data) != size:
            raise PiperAudioIntegrityError("Piper runtime file changed while being read")
        files.append(
            {
                "path": relative,
                "byte_count": size,
                "content_hash": _sha256_bytes(data),
            }
        )
        if len(files) > max_files:
            raise PiperAudioIntegrityError("Piper runtime tree exceeds file-count limit")
    if not files:
        raise PiperAudioIntegrityError("Piper runtime tree is empty")
    return content_hash({"schema_version": 1, "files": files})


@dataclass(frozen=True)
class PiperAudioExecution:
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
            "model_id": self.result.model_id,
            "model_hash": self.result.model_hash,
            "production_verification_changed": False,
            "canonical_asset_adopted": False,
        }


class PiperAudioAdapter:
    """One-shot fixed-policy Piper speech synthesis behind a governed profile."""

    BACKEND_ID = "piper"

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: GovernedAudioProfile,
        *,
        runtime_root: Path,
        executable: Path,
        espeak_data_path: Path,
        model_path: Path,
        model_config_path: Path,
        license_path: Path,
        runner: PiperProcessRunner | None = None,
        max_process_output_bytes: int = _MAX_PROCESS_OUTPUT_BYTES,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, GovernedAudioProfile):
            raise TypeError("profile must be a GovernedAudioProfile")
        if profile.kind is not AudioProfileKind.PIPER_TTS:
            raise ValueError("Piper adapter requires a PIPER_TTS profile")
        if profile.operation is not AudioOperation.SYNTHESIZE_SPEECH:
            raise ValueError("Piper profile must authorize SYNTHESIZE_SPEECH")
        if profile.backend_id != self.BACKEND_ID:
            raise ValueError("Piper profile backend_id must be piper")
        if (
            profile.model_id is None
            or profile.model_hash is None
            or profile.model_config_hash is None
            or profile.license_id is None
            or profile.license_hash is None
        ):
            raise ValueError("Piper profile must bind exact voice/config/license evidence")
        if profile.target_channels != 1:
            raise ValueError("Piper TTS profile must target mono output")
        for value, label in (
            (runtime_root, "runtime_root"),
            (executable, "executable"),
            (espeak_data_path, "espeak_data_path"),
            (model_path, "model_path"),
            (model_config_path, "model_config_path"),
            (license_path, "license_path"),
        ):
            if not isinstance(value, Path):
                raise TypeError(f"{label} must be a Path")
        if not isinstance(max_process_output_bytes, int) or not (
            1 <= max_process_output_bytes <= 16 * 1024 * 1024
        ):
            raise ValueError("max_process_output_bytes is outside allowed range")
        self.runtime = runtime
        self.profile = profile
        self.runtime_root = runtime_root
        self.executable = executable
        self.espeak_data_path = espeak_data_path
        self.model_path = model_path
        self.model_config_path = model_config_path
        self.license_path = license_path
        self.runner = runner or BoundedPiperSubprocessRunner()
        self.max_process_output_bytes = max_process_output_bytes
        self.workspace_root = runtime.state_dir / "audio-workspaces"

    def _require_runtime_member(self, path: Path, label: str, *, directory: bool) -> None:
        if path.is_symlink():
            raise PiperAudioIntegrityError(f"{label} may not be a symlink")
        if directory:
            if not path.is_dir():
                raise PiperAudioIntegrityError(f"{label} must be a directory")
        elif not path.is_file():
            raise PiperAudioIntegrityError(f"{label} must be a regular file")
        try:
            path.resolve(strict=True).relative_to(self.runtime_root.resolve(strict=True))
        except (OSError, RuntimeError, ValueError) as exc:
            raise PiperAudioIntegrityError(f"{label} must be inside the governed runtime tree") from exc

    def _verify_runtime(self) -> None:
        if self.runtime_root.is_symlink() or not self.runtime_root.is_dir():
            raise PiperAudioIntegrityError("Piper runtime root must be a regular directory")
        self._require_runtime_member(self.executable, "Piper executable", directory=False)
        self._require_runtime_member(self.espeak_data_path, "Piper espeak data", directory=True)
        actual = piper_runtime_tree_hash(self.runtime_root)
        if actual != self.profile.runtime_hash:
            raise PiperAudioIntegrityError("Piper runtime tree hash does not match governed profile")
        outcome = self.runner.run(
            (str(self.executable), "--version"),
            cwd=self.runtime.state_dir,
            stdin_bytes=b"",
            timeout_seconds=30,
            max_stdout_bytes=64 * 1024,
            max_stderr_bytes=64 * 1024,
        )
        self._require_process_success(outcome, "Piper version probe")
        try:
            version = outcome.stdout.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise PiperAudioIntegrityError("Piper version probe was not UTF-8") from exc
        if version != self.profile.backend_version:
            raise PiperAudioIntegrityError("Piper version does not match governed profile")

    def _verify_voice_sources(self) -> tuple[bytes, bytes, bytes]:
        model = _regular_file_bytes(
            self.model_path, maximum=_MAX_MODEL_BYTES, label="Piper voice model"
        )
        config = _regular_file_bytes(
            self.model_config_path,
            maximum=_MAX_CONFIG_BYTES,
            label="Piper voice config",
        )
        license_data = _regular_file_bytes(
            self.license_path,
            maximum=_MAX_LICENSE_BYTES,
            label="Piper voice license",
        )
        if _sha256_bytes(model) != self.profile.model_hash:
            raise PiperAudioIntegrityError("Piper voice model hash does not match governed profile")
        if _sha256_bytes(config) != self.profile.model_config_hash:
            raise PiperAudioIntegrityError("Piper voice config hash does not match governed profile")
        if _sha256_bytes(license_data) != self.profile.license_hash:
            raise PiperAudioIntegrityError("Piper voice license hash does not match governed profile")
        try:
            value = json.loads(config.decode("utf-8", errors="strict"))
            sample_rate = value["audio"]["sample_rate"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise PiperAudioIntegrityError("Piper voice config lacks a valid audio sample rate") from exc
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool):
            raise PiperAudioIntegrityError("Piper voice config sample rate must be an integer")
        if sample_rate != self.profile.target_sample_rate:
            raise PiperAudioIntegrityError("Piper voice config sample rate does not match governed profile")
        return model, config, license_data

    def _bind_request(self, request: AudioOperationRequest) -> None:
        if request.operation is not AudioOperation.SYNTHESIZE_SPEECH:
            raise PiperAudioIntegrityError("Piper adapter accepts SYNTHESIZE_SPEECH only")
        if request.backend_id != self.profile.backend_id:
            raise PiperAudioIntegrityError("request backend_id does not match governed Piper profile")
        if request.backend_version != self.profile.backend_version:
            raise PiperAudioIntegrityError("request backend_version does not match governed Piper profile")
        if request.profile_id != self.profile.profile_id or request.profile_hash != self.profile.profile_hash:
            raise PiperAudioIntegrityError("request does not bind governed Piper profile")
        if request.model_id != self.profile.model_id or request.model_hash != self.profile.model_hash:
            raise PiperAudioIntegrityError("request does not bind governed Piper voice")
        if request.inputs or request.prompt is not None or request.seed is not None:
            raise PiperAudioIntegrityError("Piper speech request may contain only text input")
        if request.text is None:
            raise PiperAudioIntegrityError("Piper speech request requires text")
        if request.target_sample_rate != self.profile.target_sample_rate:
            raise PiperAudioIntegrityError("request sample rate does not match governed Piper profile")
        if request.target_channels != self.profile.target_channels:
            raise PiperAudioIntegrityError("request channel count does not match governed Piper profile")

    def _workspace(self, request: AudioOperationRequest) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.workspace_root.is_symlink():
            raise PiperAudioIntegrityError("audio workspace root may not be a symlink")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        try:
            self.workspace_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PiperAudioIntegrityError("audio workspace root escapes protected project state") from exc
        workspace = self.workspace_root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise PiperAudioIntegrityError(f"audio workspace already exists: {request.workspace_id}")
        workspace.mkdir()
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir()
        return workspace

    @staticmethod
    def _require_process_success(outcome: PiperProcessOutcome, label: str) -> None:
        if outcome.timed_out:
            raise PiperAudioProcessError(f"{label} timed out")
        if outcome.output_limit_exceeded:
            raise PiperAudioProcessError(f"{label} exceeded stdout/stderr budget")
        if outcome.returncode != 0:
            detail = outcome.stderr.decode("utf-8", errors="replace")[:1000]
            raise PiperAudioProcessError(
                f"{label} exited with {outcome.returncode}: {detail}"
            )

    @staticmethod
    def _stage(path: Path, data: bytes) -> None:
        if path.exists() or path.is_symlink():
            raise PiperAudioIntegrityError("Piper staged input target already exists")
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def _argv(
        self,
        *,
        staged_model: Path,
        staged_config: Path,
        raw_output: Path,
    ) -> tuple[str, ...]:
        return (
            str(self.executable),
            "--model",
            staged_model.as_posix(),
            "--config",
            staged_config.as_posix(),
            "--output-file",
            raw_output.as_posix(),
            "--speaker",
            "0",
            "--noise_scale",
            "0",
            "--length_scale",
            "1",
            "--noise_w",
            "0",
            "--espeak_data",
            str(self.espeak_data_path),
        )

    def execute(
        self,
        request: AudioOperationRequest,
        source_bytes_by_id: Mapping[str, bytes],
    ) -> PiperAudioExecution:
        if not isinstance(request, AudioOperationRequest):
            raise TypeError("request must be an AudioOperationRequest")
        self._bind_request(request)
        if source_bytes_by_id:
            raise PiperAudioIntegrityError("Piper speech synthesis accepts no source audio bytes")
        model, config, license_data = self._verify_voice_sources()
        self._verify_runtime()
        workspace = self._workspace(request)
        request_path = workspace / "request" / "request.json"
        request_path.write_bytes(canonical_bytes(request.to_dict()))
        staged_model = workspace / "inputs" / "voice.onnx"
        staged_config = workspace / "inputs" / "voice.onnx.json"
        staged_license = workspace / "inputs" / "voice.LICENSE"
        self._stage(staged_model, model)
        self._stage(staged_config, config)
        self._stage(staged_license, license_data)
        if _sha256_bytes(staged_model.read_bytes()) != self.profile.model_hash:
            raise PiperAudioIntegrityError("staged Piper voice model hash drifted")
        if _sha256_bytes(staged_config.read_bytes()) != self.profile.model_config_hash:
            raise PiperAudioIntegrityError("staged Piper voice config hash drifted")
        if _sha256_bytes(staged_license.read_bytes()) != self.profile.license_hash:
            raise PiperAudioIntegrityError("staged Piper voice license hash drifted")
        raw_output = workspace / "runtime" / "piper-output.wav"
        stdin_bytes = request.text.encode("utf-8") + b"\n"
        if len(stdin_bytes) > _MAX_STDIN_BYTES:
            raise PiperAudioIntegrityError("Piper text payload exceeds stdin byte limit")
        outcome = self.runner.run(
            self._argv(
                staged_model=staged_model,
                staged_config=staged_config,
                raw_output=raw_output,
            ),
            cwd=workspace,
            stdin_bytes=stdin_bytes,
            timeout_seconds=request.timeout_seconds,
            max_stdout_bytes=self.max_process_output_bytes,
            max_stderr_bytes=self.max_process_output_bytes,
        )
        self._require_process_success(outcome, "Piper speech synthesis")
        if raw_output.is_symlink() or not raw_output.is_file():
            raise PiperAudioIntegrityError("Piper did not produce a regular output file")
        raw = raw_output.read_bytes()
        if len(raw) > _MAX_WAV_BYTES:
            raise PiperAudioIntegrityError("Piper output exceeds WAV byte limit")
        try:
            canonical = canonicalize_piper_output_wav(
                raw,
                max_duration_ms=request.max_duration_ms,
            )
            inspection = inspect_pcm16_wav(canonical, max_duration_ms=request.max_duration_ms)
        except WavError as exc:
            raise PiperAudioIntegrityError("Piper output is not accepted PCM16 WAV") from exc
        if inspection.sample_rate != request.target_sample_rate:
            raise PiperAudioIntegrityError("Piper output sample rate drifted")
        if inspection.channels != request.target_channels:
            raise PiperAudioIntegrityError("Piper output channel count drifted")
        output_path = workspace / request.output_relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() or output_path.is_symlink():
            raise PiperAudioIntegrityError("canonical Piper output target already exists")
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
            model_id=request.model_id,
            model_hash=request.model_hash,
            outputs=(output,),
        )
        result.bind_request(request)
        return PiperAudioExecution(
            request=request,
            result=result,
            workspace_path=workspace,
        )
