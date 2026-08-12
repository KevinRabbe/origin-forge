from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .adapters.llamacpp import LlamaCppAdapter
from .model_runtime_config import (
    ManagedModelRuntimeProviderConfig,
    ModelRuntimeProviderKind,
)
from .model_scheduler import ModelResourceProfile
from .resource_scheduler import ResourceLease


_MAX_LOG_BYTES = 64 * 1024
_MAX_HEALTH_BYTES = 4096
_HEALTH_POLL_SECONDS = 0.05
_HASH_RE = __import__("re").compile(r"^[0-9a-f]{64}$")


class ManagedLlamaCppLoaderError(RuntimeError):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class _OwnedRuntime:
    adapter: LlamaCppAdapter
    process: subprocess.Popen[bytes]
    stdout: bytearray
    stderr: bytearray
    overflow: threading.Event
    drain_threads: tuple[threading.Thread, threading.Thread]


def _drain_bounded(
    stream: BinaryIO,
    target: bytearray,
    limit: int,
    overflow: threading.Event,
) -> None:
    try:
        while True:
            chunk = stream.read(64 * 1024)
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


def _file_digest(path: Path) -> tuple[str, tuple[int, int, int, int]]:
    try:
        before = path.stat()
    except OSError as exc:
        raise ManagedLlamaCppLoaderError(f"cannot stat governed file: {path}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise ManagedLlamaCppLoaderError(f"governed path is not a regular file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        after = path.stat()
    except OSError as exc:
        raise ManagedLlamaCppLoaderError(f"cannot read governed file: {path}") from exc
    before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_id != after_id:
        raise ManagedLlamaCppLoaderError(f"governed file changed while hashing: {path}")
    return digest.hexdigest(), after_id


def _assert_same_file(path: Path, expected: tuple[int, int, int, int]) -> None:
    try:
        current = path.stat()
    except OSError as exc:
        raise ManagedLlamaCppLoaderError(f"governed file disappeared before launch: {path}") from exc
    identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if identity != expected or not stat.S_ISREG(current.st_mode):
        raise ManagedLlamaCppLoaderError(f"governed file changed before launch: {path}")


def _has_symlink_component(path: Path) -> bool:
    current = path
    while True:
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _port_is_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


class ManagedLlamaCppCpuLoader:
    """Code-owned local llama.cpp process lifecycle for one protected provider.

    The loader accepts no caller-controlled executable, model path, endpoint,
    argv, environment, or process runner. All runtime authority comes from one
    validated protected provider descriptor and the selected Phase-14 profile.
    """

    def __init__(
        self,
        project_root: str | Path,
        provider: ManagedModelRuntimeProviderConfig,
    ) -> None:
        if not isinstance(provider, ManagedModelRuntimeProviderConfig):
            raise TypeError("provider must be a ManagedModelRuntimeProviderConfig")
        if provider.provider_kind is not ModelRuntimeProviderKind.LLAMACPP_MANAGED_CPU_V1:
            raise ManagedLlamaCppLoaderError("managed llama.cpp loader requires the CPU v1 provider")
        if provider.provider_contract_version != "1":
            raise ManagedLlamaCppLoaderError("managed llama.cpp provider contract version is unsupported")
        root = Path(project_root)
        if root.is_symlink() or not root.is_dir():
            raise ManagedLlamaCppLoaderError("project root must be an existing non-symlink directory")
        self.project_root = root.resolve(strict=True)
        self.protected_root = self.project_root / ".origin-forge"
        self.provider = provider
        self._active: dict[int, _OwnedRuntime] = {}
        self._lock = threading.RLock()

    def _path(self, configured: str, *, label: str) -> Path:
        value = Path(configured)
        candidate = value if value.is_absolute() else self.project_root / value
        candidate = Path(os.path.abspath(candidate))
        if _has_symlink_component(candidate):
            raise ManagedLlamaCppLoaderError(f"{label} path contains a symlink")
        if not candidate.is_file():
            raise ManagedLlamaCppLoaderError(f"{label} must be an existing regular file")
        if _contained(candidate, self.protected_root):
            raise ManagedLlamaCppLoaderError(f"{label} may not be inside protected Origin Forge state")
        return candidate

    def _bind_profile(
        self,
        profile: ModelResourceProfile,
        lease: ResourceLease,
    ) -> tuple[Path, Path, str, tuple[int, int, int, int], tuple[int, int, int, int]]:
        if not isinstance(profile, ModelResourceProfile):
            raise TypeError("profile must be a ModelResourceProfile")
        if not isinstance(lease, ResourceLease):
            raise TypeError("lease must be a ResourceLease")
        if profile.runtime_id != self.provider.runtime_id:
            raise ManagedLlamaCppLoaderError("selected profile runtime_id does not match protected provider")
        if profile.resources.gpu is not None or lease.gpu is not None:
            raise ManagedLlamaCppLoaderError("managed llama.cpp CPU provider rejects GPU profile or lease")
        if profile.resources.cpu_slots <= 0:
            raise ManagedLlamaCppLoaderError("managed llama.cpp CPU profile must reserve CPU slots")
        if (
            lease.cpu_slots != profile.resources.cpu_slots
            or lease.ram_mib != profile.resources.ram_mib
        ):
            raise ManagedLlamaCppLoaderError("resource lease does not exactly match selected profile request")
        if (
            not isinstance(profile.model_hash, str)
            or _HASH_RE.fullmatch(profile.model_hash) is None
        ):
            raise ManagedLlamaCppLoaderError("selected profile requires an exact SHA-256 model hash")
        try:
            binding = self.provider.binding(profile.profile_id)
        except KeyError as exc:
            raise ManagedLlamaCppLoaderError("selected profile has no protected runtime binding") from exc
        if binding.model_sha256 != profile.model_hash:
            raise ManagedLlamaCppLoaderError("protected model binding does not match selected profile hash")

        executable = self._path(self.provider.executable_path, label="runtime executable")
        model = self._path(binding.model_path, label="model")
        if os.name == "posix" and not os.access(executable, os.X_OK):
            raise ManagedLlamaCppLoaderError("runtime executable is not executable")

        executable_hash, executable_identity = _file_digest(executable)
        if executable_hash != self.provider.executable_sha256:
            raise ManagedLlamaCppLoaderError("runtime executable SHA-256 does not match protected configuration")
        model_hash, model_identity = _file_digest(model)
        if model_hash != binding.model_sha256 or model_hash != profile.model_hash:
            raise ManagedLlamaCppLoaderError("model SHA-256 does not match protected profile binding")
        return executable, model, model_hash, executable_identity, model_identity

    def _argv(
        self,
        executable: Path,
        model: Path,
        lease: ResourceLease,
    ) -> list[str]:
        return [
            str(executable),
            "--model",
            str(model),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.provider.port),
            "--threads",
            str(lease.cpu_slots),
            "--threads-batch",
            str(lease.cpu_slots),
            "--device",
            "none",
            "--n-gpu-layers",
            "0",
            "--offline",
            "--no-webui",
            "--no-slots",
            "--no-mmproj",
        ]

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

    def _start_process(self, argv: list[str]) -> _OwnedRuntime:
        kwargs: dict[str, object] = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(self.project_root),
                env=self._environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                **kwargs,
            )
        except OSError as exc:
            raise ManagedLlamaCppLoaderError("failed to start governed llama.cpp runtime") from exc
        assert process.stdout is not None
        assert process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()
        threads = (
            threading.Thread(
                target=_drain_bounded,
                args=(process.stdout, stdout, _MAX_LOG_BYTES, overflow),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_bounded,
                args=(process.stderr, stderr, _MAX_LOG_BYTES, overflow),
                daemon=True,
            ),
        )
        for thread in threads:
            thread.start()
        placeholder = LlamaCppAdapter()
        return _OwnedRuntime(placeholder, process, stdout, stderr, overflow, threads)

    def _health_ready(self, owned: _OwnedRuntime) -> None:
        deadline = time.monotonic() + self.provider.startup_timeout_seconds
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.provider.port}/health",
            method="GET",
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        last_error = "runtime did not become ready"
        while time.monotonic() < deadline:
            if owned.overflow.is_set():
                raise ManagedLlamaCppLoaderError("llama.cpp startup log output exceeded bounded capture")
            returncode = owned.process.poll()
            if returncode is not None:
                detail = bytes(owned.stderr).decode("utf-8", errors="replace")[:1000]
                raise ManagedLlamaCppLoaderError(
                    f"llama.cpp exited before readiness (code {returncode}): {detail}"
                )
            timeout = max(0.05, min(0.25, deadline - time.monotonic()))
            try:
                with opener.open(request, timeout=timeout) as response:
                    if response.status != 200:
                        last_error = f"unexpected health status {response.status}"
                    else:
                        raw = response.read(_MAX_HEALTH_BYTES + 1)
                        if len(raw) > _MAX_HEALTH_BYTES:
                            raise ManagedLlamaCppLoaderError("llama.cpp health response exceeds byte limit")
                        try:
                            payload = json.loads(raw)
                        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                            raise ManagedLlamaCppLoaderError("llama.cpp health response is invalid JSON") from exc
                        if isinstance(payload, dict) and payload.get("status") == "ok":
                            if owned.process.poll() is not None:
                                raise ManagedLlamaCppLoaderError("llama.cpp exited at readiness boundary")
                            return
                        last_error = "llama.cpp health response did not report status ok"
            except urllib.error.HTTPError as exc:
                if exc.code != 503:
                    raise ManagedLlamaCppLoaderError(
                        f"llama.cpp health check returned HTTP {exc.code}"
                    ) from exc
                last_error = "llama.cpp is still loading"
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                last_error = "llama.cpp health endpoint is not reachable yet"
            time.sleep(_HEALTH_POLL_SECONDS)
        raise ManagedLlamaCppLoaderError(
            f"llama.cpp startup timeout after {self.provider.startup_timeout_seconds:g}s: {last_error}"
        )

    def _stop_process(self, owned: _OwnedRuntime) -> None:
        process = owned.process
        timeout = self.provider.shutdown_timeout_seconds
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + timeout
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except OSError:
                        pass
        try:
            process.wait(timeout=max(0.1, timeout))
        except subprocess.TimeoutExpired as exc:
            raise ManagedLlamaCppLoaderError("governed llama.cpp runtime did not terminate") from exc
        for thread in owned.drain_threads:
            thread.join(timeout=max(0.1, timeout))
        if any(thread.is_alive() for thread in owned.drain_threads):
            raise ManagedLlamaCppLoaderError("failed to drain governed llama.cpp runtime logs")

    def load(self, profile: ModelResourceProfile, lease: ResourceLease) -> object:
        with self._lock:
            if self._active:
                raise ManagedLlamaCppLoaderError("managed llama.cpp provider already owns an active runtime")
            (
                executable,
                model,
                model_hash,
                executable_identity,
                model_identity,
            ) = self._bind_profile(profile, lease)
            if _port_is_in_use(self.provider.port):
                raise ManagedLlamaCppLoaderError("protected llama.cpp port is already in use")
            _assert_same_file(executable, executable_identity)
            _assert_same_file(model, model_identity)
            owned = self._start_process(self._argv(executable, model, lease))
            try:
                self._health_ready(owned)
                adapter = LlamaCppAdapter(
                    base_url=f"http://127.0.0.1:{self.provider.port}",
                    model=profile.model_id,
                    timeout_seconds=self.provider.request_timeout_seconds,
                    allow_remote=False,
                    model_hash=model_hash,
                )
                if adapter.model_id != profile.model_id:
                    raise ManagedLlamaCppLoaderError("loaded adapter model identity drifted")
                owned.adapter = adapter
                self._active[id(adapter)] = owned
                return adapter
            except BaseException:
                self._stop_process(owned)
                raise

    def unload(self, instance: object) -> None:
        with self._lock:
            active = self._active.get(id(instance))
            if active is None or active.adapter is not instance:
                raise ManagedLlamaCppLoaderError("model instance is not owned by this managed loader")
            self._active.pop(id(instance))
            self._stop_process(active)

    def active_instance_count(self) -> int:
        with self._lock:
            return len(self._active)
