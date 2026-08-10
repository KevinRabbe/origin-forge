from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .blender_models import BlenderJobRequest, BlenderModelError
from .blockbench_glb import GlbError, GlbInspection, inspect_glb
from .blockbench_models import canonical_bytes, canonical_hash, validate_sha256
from .runtime import OriginForgeRuntime


_MAX_RUNTIME_FILES = 20_000
_MAX_RUNTIME_BYTES = 8 * 1024 * 1024 * 1024
_MAX_RUNNER_BYTES = 1024 * 1024
_MAX_RESULT_BYTES = 1024 * 1024


class BlenderAdapterError(RuntimeError):
    pass


class BlenderIntegrityError(BlenderAdapterError):
    pass


class BlenderProcessError(BlenderAdapterError):
    pass


@dataclass(frozen=True)
class BlenderProcessOutcome:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limit_exceeded: bool = False


class BlenderProcessRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> BlenderProcessOutcome: ...


class BoundedBlenderSubprocessRunner:
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
        env: Mapping[str, str],
        timeout_seconds: int,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> BlenderProcessOutcome:
        if not argv or any(not isinstance(value, str) or not value for value in argv):
            raise ValueError("argv must contain non-empty strings")
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
        )
        assert process.stdout is not None and process.stderr is not None
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
            raise BlenderProcessError("failed to drain bounded Blender process output")
        return BlenderProcessOutcome(
            returncode=returncode,
            stdout=bytes(stdout[:max_stdout_bytes]),
            stderr=bytes(stderr[:max_stderr_bytes]),
            timed_out=timed_out,
            output_limit_exceeded=overflow.is_set(),
        )


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _safe_regular_file(path: Path, label: str, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BlenderIntegrityError(f"{label} must be a regular non-symlink file")
    size = path.stat().st_size
    if not 1 <= size <= maximum:
        raise BlenderIntegrityError(f"{label} is outside byte limit")
    data = path.read_bytes()
    if len(data) != size:
        raise BlenderIntegrityError(f"{label} changed while being read")
    return data


def blender_runtime_tree_hash(
    runtime_root: Path,
    *,
    max_files: int = _MAX_RUNTIME_FILES,
    max_total_bytes: int = _MAX_RUNTIME_BYTES,
) -> str:
    """Hash one materialized, symlink-free portable Blender runtime tree."""
    if not isinstance(runtime_root, Path):
        raise TypeError("runtime_root must be a Path")
    if runtime_root.is_symlink() or not runtime_root.is_dir():
        raise BlenderIntegrityError("Blender runtime root must be a regular directory")
    if not isinstance(max_files, int) or not 1 <= max_files <= _MAX_RUNTIME_FILES:
        raise ValueError("max_files is outside allowed range")
    if not isinstance(max_total_bytes, int) or not 1 <= max_total_bytes <= _MAX_RUNTIME_BYTES:
        raise ValueError("max_total_bytes is outside allowed range")
    files: list[dict[str, object]] = []
    total = 0
    for path in sorted(runtime_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise BlenderIntegrityError("Blender runtime tree may not contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise BlenderIntegrityError("Blender runtime tree contains an undeclared entry")
        relative = path.relative_to(runtime_root).as_posix()
        size = path.stat().st_size
        total += size
        if total > max_total_bytes:
            raise BlenderIntegrityError("Blender runtime tree exceeds byte limit")
        data = path.read_bytes()
        if len(data) != size:
            raise BlenderIntegrityError("Blender runtime file changed while being read")
        files.append(
            {
                "path": relative,
                "byte_count": size,
                "content_hash": _sha256_bytes(data),
            }
        )
        if len(files) > max_files:
            raise BlenderIntegrityError("Blender runtime tree exceeds file-count limit")
    if not files:
        raise BlenderIntegrityError("Blender runtime tree is empty")
    return canonical_hash({"schema_version": 1, "files": files})


def blender_runner_v1_bytes() -> bytes:
    runner = Path(__file__).with_name("blender_runner_v1.py")
    return _safe_regular_file(runner, "Blender runner v1", _MAX_RUNNER_BYTES)


def blender_runner_v1_fingerprint() -> str:
    return _sha256_bytes(blender_runner_v1_bytes())


@dataclass(frozen=True)
class BlenderRuntimeProfile:
    runtime_root: Path
    executable: Path
    runtime_hash: str
    expected_blender_version: str
    runner_fingerprint: str
    max_runtime_files: int = _MAX_RUNTIME_FILES
    max_runtime_bytes: int = _MAX_RUNTIME_BYTES

    def __post_init__(self) -> None:
        try:
            validate_sha256(self.runtime_hash, "runtime_hash")
            validate_sha256(self.runner_fingerprint, "runner_fingerprint")
        except ValueError as exc:
            raise BlenderModelError(str(exc)) from exc
        if (
            not isinstance(self.expected_blender_version, str)
            or not self.expected_blender_version
            or self.expected_blender_version != self.expected_blender_version.strip()
            or len(self.expected_blender_version) > 128
            or any(char in self.expected_blender_version for char in ("\x00", "\n", "\r"))
        ):
            raise BlenderModelError("expected_blender_version must be one bounded line")
        if not isinstance(self.runtime_root, Path) or not isinstance(self.executable, Path):
            raise TypeError("runtime_root and executable must be Paths")

    def verify(self) -> Path:
        actual = blender_runtime_tree_hash(
            self.runtime_root,
            max_files=self.max_runtime_files,
            max_total_bytes=self.max_runtime_bytes,
        )
        if actual != self.runtime_hash:
            raise BlenderIntegrityError("Blender runtime tree hash does not match profile")
        if self.executable.is_symlink() or not self.executable.is_file():
            raise BlenderIntegrityError("Blender executable must be a regular non-symlink file")
        try:
            executable = self.executable.resolve(strict=True)
            executable.relative_to(self.runtime_root.resolve(strict=True))
        except (OSError, RuntimeError, ValueError) as exc:
            raise BlenderIntegrityError("Blender executable must be inside runtime tree") from exc
        runner_fingerprint = blender_runner_v1_fingerprint()
        if runner_fingerprint != self.runner_fingerprint:
            raise BlenderIntegrityError("Blender runner fingerprint does not match profile")
        return executable


@dataclass(frozen=True)
class BlenderExecution:
    request: BlenderJobRequest
    workspace_path: Path
    output_path: Path
    inspection: GlbInspection
    blender_version: str
    runtime_hash: str
    runner_fingerprint: str
    stdout: bytes
    stderr: bytes

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.request.operation_id,
            "workspace_id": self.request.workspace_id,
            "request_hash": self.request.content_hash,
            "project_hash": self.request.project.content_hash,
            "output_relative_path": self.request.output_relative_path,
            "output": self.inspection.to_dict(),
            "blender_version": self.blender_version,
            "runtime_hash": self.runtime_hash,
            "runner_fingerprint": self.runner_fingerprint,
            "production_verification_changed": False,
            "canonical_asset_adopted": False,
        }


class BlenderAdapter:
    """Run one frozen Origin Forge Blender runner inside a protected 3D workspace."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: BlenderRuntimeProfile,
        *,
        runner: BlenderProcessRunner | None = None,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, BlenderRuntimeProfile):
            raise TypeError("profile must be a BlenderRuntimeProfile")
        self.runtime = runtime
        self.profile = profile
        self.runner = runner or BoundedBlenderSubprocessRunner()
        self.workspace_root = runtime.state_dir / "model3d-workspaces"

    @staticmethod
    def _require_success(outcome: BlenderProcessOutcome, label: str) -> None:
        if outcome.timed_out:
            raise BlenderProcessError(f"{label} timed out")
        if outcome.output_limit_exceeded:
            raise BlenderProcessError(f"{label} exceeded stdout/stderr budget")
        if outcome.returncode != 0:
            detail = outcome.stderr.decode("utf-8", errors="replace")[:2000]
            raise BlenderProcessError(f"{label} exited with {outcome.returncode}: {detail}")

    def _workspace(self, request: BlenderJobRequest) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.workspace_root.is_symlink():
            raise BlenderIntegrityError("3D workspace root may not be a symlink")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        try:
            self.workspace_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise BlenderIntegrityError("3D workspace root escapes protected state") from exc
        workspace = self.workspace_root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise BlenderIntegrityError("Blender workspace already exists")
        workspace.mkdir()
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir()
        return workspace

    @staticmethod
    def _root(workspace: Path, name: str) -> Path:
        root = workspace / name
        if root.is_symlink():
            raise BlenderIntegrityError(f"Blender {name} root may not be a symlink")
        try:
            workspace_resolved = workspace.resolve(strict=True)
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BlenderIntegrityError(f"Blender {name} root is unavailable") from exc
        if not resolved.is_dir() or resolved.parent != workspace_resolved:
            raise BlenderIntegrityError(f"Blender {name} root escaped containment")
        return resolved

    def _environment(self, workspace: Path) -> dict[str, str]:
        scratch = workspace / "runtime" / "state"
        home = scratch / "home"
        data = scratch / "data"
        config = scratch / "config"
        cache = scratch / "cache"
        temp = scratch / "tmp"
        for path in (home, data, config, cache, temp):
            path.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": os.defpath,
            "HOME": str(home),
            "PWD": str(workspace),
            "TMPDIR": str(temp),
            "XDG_DATA_HOME": str(data),
            "XDG_CONFIG_HOME": str(config),
            "XDG_CACHE_HOME": str(cache),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if os.name == "nt":
            for name in ("SystemRoot", "WINDIR"):
                value = os.environ.get(name)
                if value:
                    env[name] = value
        return env

    def _probe_version(self, executable: Path, workspace: Path) -> None:
        outcome = self.runner.run(
            (str(executable), "--version"),
            cwd=workspace,
            env=self._environment(workspace),
            timeout_seconds=30,
            max_stdout_bytes=64 * 1024,
            max_stderr_bytes=64 * 1024,
        )
        self._require_success(outcome, "Blender version probe")
        try:
            first = outcome.stdout.decode("utf-8", errors="strict").splitlines()[0].strip()
        except (UnicodeDecodeError, IndexError) as exc:
            raise BlenderIntegrityError("Blender version probe did not return UTF-8 output") from exc
        if first != self.profile.expected_blender_version:
            raise BlenderIntegrityError("Blender version does not match governed profile")

    @staticmethod
    def _parse_runner_result(path: Path, request: BlenderJobRequest) -> str:
        raw = _safe_regular_file(path, "Blender runner result", _MAX_RESULT_BYTES)
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BlenderIntegrityError("Blender runner result is not strict UTF-8 JSON") from exc
        expected = {
            "protocol_version",
            "status",
            "operation_id",
            "workspace_id",
            "request_hash",
            "project_hash",
            "output_relative_path",
            "blender_version",
        }
        if not isinstance(value, dict) or set(value) != expected or value["protocol_version"] != 1:
            raise BlenderIntegrityError("Blender runner result fields do not match strict schema")
        if value["status"] != "SUCCEEDED":
            raise BlenderIntegrityError("Blender runner did not report success")
        bindings = {
            "operation_id": request.operation_id,
            "workspace_id": request.workspace_id,
            "request_hash": request.content_hash,
            "project_hash": request.project.content_hash,
            "output_relative_path": request.output_relative_path,
        }
        for key, expected_value in bindings.items():
            if value[key] != expected_value:
                raise BlenderIntegrityError(f"Blender runner result {key} does not match request")
        version = value["blender_version"]
        if not isinstance(version, str) or version != request.expected_blender_version:
            raise BlenderIntegrityError("Blender runner version does not match request")
        return version

    @staticmethod
    def _output_path(workspace: Path, relative_path: str) -> Path:
        relative = Path(relative_path)
        if not relative.parts or relative.parts[0] != "exports":
            raise BlenderIntegrityError("Blender output must remain under exports")
        current = workspace
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise BlenderIntegrityError("Blender output contains a symlink component")
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to((workspace / "exports").resolve(strict=True))
        except (OSError, RuntimeError, ValueError) as exc:
            raise BlenderIntegrityError("Blender output escaped workspace") from exc
        if not resolved.is_file():
            raise BlenderIntegrityError("Blender output must be a regular file")
        return resolved

    def execute(self, request: BlenderJobRequest) -> BlenderExecution:
        if not isinstance(request, BlenderJobRequest):
            raise TypeError("request must be a BlenderJobRequest")
        if request.runtime_hash != self.profile.runtime_hash:
            raise BlenderIntegrityError("request runtime hash does not match profile")
        if request.runner_fingerprint != self.profile.runner_fingerprint:
            raise BlenderIntegrityError("request runner fingerprint does not match profile")
        if request.expected_blender_version != self.profile.expected_blender_version:
            raise BlenderIntegrityError("request Blender version does not match profile")

        executable = self.profile.verify()
        workspace = self._workspace(request)
        self._probe_version(executable, workspace)
        request_path = workspace / "request" / "request.json"
        request_path.write_bytes(canonical_bytes(request.to_dict()))
        runner_path = workspace / "runtime" / "runner_v1.py"
        runner_path.write_bytes(blender_runner_v1_bytes())
        if _sha256_bytes(runner_path.read_bytes()) != request.runner_fingerprint:
            raise BlenderIntegrityError("staged Blender runner fingerprint drifted")
        output_path = workspace / request.output_relative_path
        result_path = workspace / "runtime" / "result.json"

        argv = (
            str(executable),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "97",
            "--python",
            str(runner_path.resolve(strict=True)),
            "--",
            "--workspace",
            str(workspace.resolve(strict=True)),
            "--request",
            str(request_path.resolve(strict=True)),
            "--output",
            str(output_path.resolve(strict=False)),
            "--result",
            str(result_path.resolve(strict=False)),
        )
        outcome = self.runner.run(
            argv,
            cwd=workspace,
            env=self._environment(workspace),
            timeout_seconds=request.budget.timeout_seconds,
            max_stdout_bytes=request.budget.max_stdout_bytes,
            max_stderr_bytes=request.budget.max_stderr_bytes,
        )
        self._require_success(outcome, "Blender governed operation")
        for name in ("request", "inputs", "exports", "runtime"):
            self._root(workspace, name)
        version = self._parse_runner_result(result_path, request)
        actual_exports = {
            path.relative_to(workspace).as_posix()
            for path in (workspace / "exports").rglob("*")
            if path.is_file()
        }
        if actual_exports != {request.output_relative_path}:
            raise BlenderIntegrityError("Blender export set does not match frozen request")
        resolved_output = self._output_path(workspace, request.output_relative_path)
        data = _safe_regular_file(
            resolved_output,
            "Blender GLB output",
            request.budget.max_output_bytes,
        )
        try:
            inspection = inspect_glb(data)
        except GlbError as exc:
            raise BlenderIntegrityError("Blender GLB failed independent validation") from exc
        return BlenderExecution(
            request=request,
            workspace_path=workspace,
            output_path=resolved_output,
            inspection=inspection,
            blender_version=version,
            runtime_hash=request.runtime_hash,
            runner_fingerprint=request.runner_fingerprint,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
        )
