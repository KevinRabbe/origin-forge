from __future__ import annotations

import ctypes
import hashlib
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .image_png import inspect_truecolor8_png
from .runtime_observation_models import (
    RuntimeCaptureEvidence,
    RuntimeExitKind,
    RuntimeLogEvidence,
    RuntimeObservationRequest,
    RuntimeObservationResult,
    RuntimeObservationStatus,
    RuntimePerformanceEvidence,
    canonical_bytes,
)

_MAX_CAPTURE_BYTES = 128 * 1024 * 1024


class _WindowsProcessJob:
    """Kill-on-close Windows Job Object for one observer process tree."""

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        if os.name != "nt":
            raise RuntimeObserverError("Windows process jobs are only available on Windows")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise RuntimeObserverError("failed to create runtime observation process job")
        self._kernel32 = kernel32
        self._handle = handle
        try:
            class _Basic(ctypes.Structure):
                _fields_ = [
                    ("per_process_user_time", ctypes.c_longlong),
                    ("per_job_user_time", ctypes.c_longlong),
                    ("limit_flags", ctypes.c_uint32),
                    ("minimum_working_set", ctypes.c_size_t),
                    ("maximum_working_set", ctypes.c_size_t),
                    ("active_process_limit", ctypes.c_uint32),
                    ("affinity", ctypes.c_size_t),
                    ("priority", ctypes.c_uint32),
                    ("scheduling_class", ctypes.c_uint32),
                ]

            class _IoCounters(ctypes.Structure):
                _fields_ = [("values", ctypes.c_ulonglong * 6)]

            class _Extended(ctypes.Structure):
                _fields_ = [("basic", _Basic), ("io", _IoCounters), ("process_memory_limit", ctypes.c_size_t), ("job_memory_limit", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

            info = _Extended()
            info.basic.limit_flags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                raise RuntimeObserverError("failed to configure runtime observation process job")
            if not kernel32.AssignProcessToJobObject(handle, ctypes.c_void_p(int(process._handle))):
                raise RuntimeObserverError("failed to assign runtime process to process job")
        except Exception:
            kernel32.CloseHandle(handle)
            raise

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


class RuntimeObserverError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeObserverExecution:
    request: RuntimeObservationRequest
    result: RuntimeObservationResult
    workspace_path: Path


def sha256_file(path: Path, *, max_bytes: int = 512 * 1024 * 1024) -> str:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeObserverError("runtime executable must be a regular non-symlink file")
    total = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                raise RuntimeObserverError("runtime executable exceeds fingerprint byte limit")
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise RuntimeObserverError(f"runtime observer path already exists: {path.name}")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _read_peak_rss_kib(pid: int) -> int:
    status = Path(f"/proc/{pid}/status")
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                fields = line.split()
                if len(fields) >= 2:
                    return max(0, int(fields[1]))
    except (OSError, ValueError, UnicodeError):
        return 0
    return 0


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate every process left in the observation's process group.

    The group may still contain descendants after the direct child exits, so
    cleanup must not stop merely because ``process.poll()`` is non-None.
    """

    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"
        argv = [str(taskkill) if taskkill.is_file() else "taskkill.exe", "/PID", str(process.pid), "/T", "/F"]
        try:
            subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 0.5
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _drain_bounded(
    stream: BinaryIO,
    target: bytearray,
    limit: int,
    overflow: threading.Event,
) -> None:
    try:
        while True:
            chunk = stream.read(65_536)
            if not chunk:
                return
            remaining = max(0, limit - len(target))
            if remaining:
                target.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
    finally:
        try:
            stream.close()
        except OSError:
            pass


class LocalProcessRuntimeObserver:
    """Run one preconfigured executable without shell or caller-controlled environment.

    The executable and fixed argv are supplied when this trusted adapter is
    constructed. The observation request can bind their reviewed identity but
    cannot inject shell text, arbitrary executable paths, environment values,
    or follow-up commands.

    Phase-23 v1 capture is cooperative: the target may write only declared PNG
    paths beneath ORIGIN_FORGE_CAPTURE_DIR. A logically timed sequence of
    VIDEO_FRAME PNGs is the canonical video evidence surface in this revision;
    codec/container packaging is deliberately derived evidence, not truth.
    """

    def __init__(
        self,
        *,
        workspace_root: Path,
        executable: Path,
        executable_hash: str,
        backend_id: str,
        backend_version: str,
        target_id: str,
        target_version: str,
        fixed_args: tuple[str, ...] = (),
    ):
        self.workspace_root = Path(workspace_root)
        self.executable = Path(executable)
        self.executable_hash = executable_hash
        self.backend_id = backend_id
        self.backend_version = backend_version
        self.target_id = target_id
        self.target_version = target_version
        args = tuple(fixed_args)
        if len(args) > 32:
            raise RuntimeObserverError("fixed runtime argv exceeds count limit")
        for value in args:
            if not isinstance(value, str) or not value or "\x00" in value or len(value) > 4096:
                raise RuntimeObserverError("fixed runtime argv contains an invalid token")
        self.fixed_args = args
        actual = sha256_file(self.executable)
        if actual != executable_hash:
            raise RuntimeObserverError("configured runtime executable hash does not match bytes")

    def _bind(self, request: RuntimeObservationRequest) -> None:
        expected = (
            self.backend_id,
            self.backend_version,
            self.target_id,
            self.target_version,
            self.executable_hash,
        )
        actual = (
            request.backend_id,
            request.backend_version,
            request.target_id,
            request.target_version,
            request.executable_hash,
        )
        if actual != expected:
            raise RuntimeObserverError("runtime request does not match trusted adapter identity")

    def _workspace(self, request: RuntimeObservationRequest) -> Path:
        root = self.workspace_root
        if root.is_symlink():
            raise RuntimeObserverError("runtime observation workspace root may not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        workspace = root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise RuntimeObserverError("runtime observation workspace already exists")
        workspace.mkdir()
        for name in ("request", "logs", "captures", "runtime"):
            (workspace / name).mkdir()
        (workspace / "runtime" / "home").mkdir()
        (workspace / "runtime" / "tmp").mkdir()
        return workspace

    @staticmethod
    def _capture_manifest(request: RuntimeObservationRequest) -> dict[str, object]:
        return {
            "observation_id": request.observation_id,
            "request_hash": request.content_hash,
            "captures": [
                {
                    "capture_id": value.capture_id,
                    "kind": value.kind.value,
                    "relative_path": value.relative_path,
                    "timestamp_ms": value.timestamp_ms,
                }
                for value in request.captures
            ],
        }

    @staticmethod
    def _capture_evidence(
        workspace: Path,
        request: RuntimeObservationRequest,
        *,
        allow_missing: bool,
    ) -> tuple[RuntimeCaptureEvidence, ...]:
        capture_root = workspace / "captures"
        expected_paths = {value.relative_path for value in request.captures}
        actual_paths: set[str] = set()
        for path in capture_root.rglob("*"):
            if path.is_symlink():
                raise RuntimeObserverError("runtime capture tree contains a symlink")
            if path.is_file():
                size = path.stat().st_size
                if size <= 0 or size > _MAX_CAPTURE_BYTES:
                    raise RuntimeObserverError(
                        "runtime capture exceeds bounded PNG byte limit"
                    )
                try:
                    relative = path.relative_to(workspace).as_posix()
                except ValueError as exc:
                    raise RuntimeObserverError("runtime capture escaped workspace") from exc
                actual_paths.add(relative)
        extra = sorted(actual_paths - expected_paths)
        missing = sorted(expected_paths - actual_paths)
        if extra or (missing and not allow_missing):
            raise RuntimeObserverError(
                f"runtime capture set mismatch; missing={missing!r} extra={extra!r}"
            )

        evidence: list[RuntimeCaptureEvidence] = []
        for spec in request.captures:
            if spec.relative_path not in actual_paths:
                continue
            path = workspace / spec.relative_path
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(capture_root.resolve(strict=True))
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeObserverError("runtime capture path is unsafe") from exc
            if path.is_symlink() or not path.is_file():
                raise RuntimeObserverError("runtime capture is missing or unsafe")
            size = path.stat().st_size
            if size <= 0 or size > _MAX_CAPTURE_BYTES:
                raise RuntimeObserverError("runtime capture exceeds bounded PNG byte limit")
            data = path.read_bytes()
            if len(data) != size:
                raise RuntimeObserverError("runtime capture changed while being read")
            inspection = inspect_truecolor8_png(data)
            evidence.append(
                RuntimeCaptureEvidence(
                    capture_id=spec.capture_id,
                    kind=spec.kind,
                    relative_path=spec.relative_path,
                    timestamp_ms=spec.timestamp_ms,
                    content_hash=_hash_bytes(data),
                    pixel_hash=inspection.pixel_hash,
                    byte_count=inspection.byte_count,
                    width=inspection.width,
                    height=inspection.height,
                )
            )
        return tuple(evidence)

    def execute(self, request: RuntimeObservationRequest) -> RuntimeObserverExecution:
        if not isinstance(request, RuntimeObservationRequest):
            raise TypeError("request must be a RuntimeObservationRequest")
        self._bind(request)
        if sha256_file(self.executable) != self.executable_hash:
            raise RuntimeObserverError("runtime executable bytes drifted since adapter construction")
        workspace = self._workspace(request)
        request_path = workspace / "request" / "request.json"
        manifest_path = workspace / "request" / "capture-manifest.json"
        _write_new(request_path, canonical_bytes(request.to_dict()))
        _write_new(manifest_path, canonical_bytes(self._capture_manifest(request)))

        env = {
            "HOME": str(workspace / "runtime" / "home"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": str(workspace / "runtime" / "tmp"),
            "ORIGIN_FORGE_OBSERVATION_ID": request.observation_id,
            "ORIGIN_FORGE_REQUEST_HASH": request.content_hash,
            "ORIGIN_FORGE_CAPTURE_DIR": str(workspace / "captures"),
            "ORIGIN_FORGE_CAPTURE_MANIFEST": str(manifest_path),
        }
        argv = [str(self.executable), *self.fixed_args]
        started = time.monotonic()
        stdout_file = None
        stderr_file = None
        process_job = None
        if os.name == "nt":
            stdout_file = (workspace / "logs" / "stdout.log").open("xb")
            stderr_file = (workspace / "logs" / "stderr.log").open("xb")
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            process_job = _WindowsProcessJob(process)
        else:
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
            )
            assert process.stdout is not None
            assert process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()
        stdout_thread = None
        stderr_thread = None
        if os.name != "nt":
            stdout_thread = threading.Thread(
                target=_drain_bounded,
                args=(process.stdout, stdout, request.max_log_bytes, overflow),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_drain_bounded,
                args=(process.stderr, stderr, request.max_log_bytes, overflow),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
        deadline = started + request.timeout_seconds
        peak_rss_kib = 0
        timed_out = False
        while process.poll() is None:
            peak_rss_kib = max(peak_rss_kib, _read_peak_rss_kib(process.pid))
            if os.name == "nt" and (
                stdout_file is not None
                and stderr_file is not None
                and (
                    (workspace / "logs" / "stdout.log").stat().st_size > request.max_log_bytes
                    or (workspace / "logs" / "stderr.log").stat().st_size > request.max_log_bytes
                )
            ):
                overflow.set()
            if overflow.is_set():
                _terminate_process_group(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_process_group(process)
                break
            time.sleep(0.01)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            process.wait(timeout=2)
        _terminate_process_group(process)
        if process_job is not None:
            process_job.close()
        if stdout_file is not None and stderr_file is not None:
            stdout_file.close()
            stderr_file.close()
            stdout_bytes = (workspace / "logs" / "stdout.log").read_bytes()
            stderr_bytes = (workspace / "logs" / "stderr.log").read_bytes()
            if len(stdout_bytes) > request.max_log_bytes or len(stderr_bytes) > request.max_log_bytes:
                overflow.set()
            stdout = bytearray(stdout_bytes[: request.max_log_bytes])
            stderr = bytearray(stderr_bytes[: request.max_log_bytes])
        else:
            assert stdout_thread is not None
            assert stderr_thread is not None
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
        duration_ms = max(0, int((time.monotonic() - started) * 1000))

        stdout_bytes = bytes(stdout)
        stderr_bytes = bytes(stderr)
        if stdout_file is None and stderr_file is None:
            _write_new(workspace / "logs" / "stdout.log", stdout_bytes)
            _write_new(workspace / "logs" / "stderr.log", stderr_bytes)
        stdout_evidence = RuntimeLogEvidence(
            relative_path="logs/stdout.log",
            content_hash=_hash_bytes(stdout_bytes),
            byte_count=len(stdout_bytes),
        )
        stderr_evidence = RuntimeLogEvidence(
            relative_path="logs/stderr.log",
            content_hash=_hash_bytes(stderr_bytes),
            byte_count=len(stderr_bytes),
        )
        performance = RuntimePerformanceEvidence(
            duration_ms=duration_ms,
            peak_rss_kib=peak_rss_kib,
        )

        if overflow.is_set():
            result = RuntimeObservationResult(
                observation_id=request.observation_id,
                workspace_id=request.workspace_id,
                request_hash=request.content_hash,
                status=RuntimeObservationStatus.BLOCKED,
                backend_id=request.backend_id,
                backend_version=request.backend_version,
                target_id=request.target_id,
                target_version=request.target_version,
                executable_hash=request.executable_hash,
                exit_kind=RuntimeExitKind.FAILED,
                exit_code=process.returncode if process.returncode is not None else -1,
                stdout=stdout_evidence,
                stderr=stderr_evidence,
                captures=(),
                performance=performance,
                detail="runtime log byte budget exceeded",
            )
            return RuntimeObserverExecution(request, result, workspace)

        if timed_out:
            exit_kind = RuntimeExitKind.TIMEOUT
            exit_code = None
        else:
            returncode = process.returncode
            if returncode is None:
                raise RuntimeObserverError("runtime process has no exit status after wait")
            exit_code = returncode
            if returncode == 0:
                exit_kind = RuntimeExitKind.EXITED
            elif returncode < 0 or (
                os.name == "nt" and returncode in {signal.SIGINT, signal.SIGTERM, signal.SIGBREAK}
            ):
                exit_kind = RuntimeExitKind.SIGNALED
                if os.name == "nt" and returncode > 0:
                    exit_code = -returncode
            else:
                exit_kind = RuntimeExitKind.FAILED

        captures = self._capture_evidence(
            workspace,
            request,
            allow_missing=exit_kind is not RuntimeExitKind.EXITED,
        )
        result = RuntimeObservationResult(
            observation_id=request.observation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=RuntimeObservationStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            target_id=request.target_id,
            target_version=request.target_version,
            executable_hash=request.executable_hash,
            exit_kind=exit_kind,
            exit_code=exit_code,
            stdout=stdout_evidence,
            stderr=stderr_evidence,
            captures=captures,
            performance=performance,
        )
        result.bind_request(request)
        return RuntimeObserverExecution(request, result, workspace)
