from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .lsp_client import (
    LspRequestSession,
    LspWorkspaceMapper,
    initialize_lsp_session,
)
from .lsp_code_intelligence import LspCodeIntelligenceProvider
from .lsp_session import LspJsonRpcSession
from .repository import RepositoryReader


class PodmanLspError(RuntimeError):
    pass


class PodmanLspUnavailable(PodmanLspError):
    pass


@dataclass(frozen=True)
class PodmanLspServerSpec:
    """Trusted operator-owned language-server process configuration."""

    server_id: str
    image: str
    argv: tuple[str, ...]
    podman_executable: str = "podman"
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 256
    network_allowed: bool = False
    probe_timeout_seconds: float = 10.0
    initialize_timeout_seconds: float = 15.0
    request_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    max_protocol_message_bytes: int = 4 * 1024 * 1024
    max_pending_notifications: int = 256
    max_stderr_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if not self.server_id.strip():
            raise ValueError("LSP server_id is required")
        if not self.image.strip():
            raise ValueError("LSP container image is required")
        if not self.argv or any(not item for item in self.argv):
            raise ValueError("LSP server argv must contain a non-empty executable")
        if self.cpus <= 0 or self.pids_limit <= 0:
            raise ValueError("LSP resource limits must be positive")
        for value, name in (
            (self.probe_timeout_seconds, "probe timeout"),
            (self.initialize_timeout_seconds, "initialize timeout"),
            (self.request_timeout_seconds, "request timeout"),
            (self.shutdown_timeout_seconds, "shutdown timeout"),
        ):
            if value <= 0:
                raise ValueError(f"LSP {name} must be positive")
        if self.max_protocol_message_bytes <= 0:
            raise ValueError("LSP protocol message limit must be positive")
        if self.max_pending_notifications <= 0:
            raise ValueError("LSP notification limit must be positive")
        if self.max_stderr_bytes <= 0:
            raise ValueError("LSP stderr limit must be positive")


class _BoundedStderr:
    def __init__(self, limit: int):
        self.limit = limit
        self.data = bytearray()
        self.truncated = False

    def consume(self, stream) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = self.limit - len(self.data)
            if remaining > 0:
                self.data.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                self.truncated = True

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")


def _close_process_pipes(process: subprocess.Popen) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except (OSError, ValueError):
            pass


class PodmanLspHandle:
    """One initialized language-server container and normalized provider."""

    def __init__(
        self,
        *,
        backend: "PodmanLspBackend",
        process: subprocess.Popen,
        session: LspRequestSession,
        provider: LspCodeIntelligenceProvider,
        job_root: Path,
        workspace_copy: Path,
        cidfile: Path,
        stderr_capture: _BoundedStderr,
        stderr_thread: threading.Thread,
    ):
        self.backend = backend
        self.process = process
        self.session = session
        self.provider = provider
        self.job_root = job_root
        self.workspace_copy = workspace_copy
        self.cidfile = cidfile
        self.stderr_capture = stderr_capture
        self.stderr_thread = stderr_thread
        self._closed = False

    @property
    def stderr(self) -> str:
        return self.stderr_capture.text()

    @property
    def stderr_truncated(self) -> bool:
        return self.stderr_capture.truncated

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        spec = self.backend.spec
        try:
            try:
                self.session.request(
                    "shutdown",
                    None,
                    timeout_seconds=spec.shutdown_timeout_seconds,
                )
            except Exception:
                pass
            try:
                self.session.notify("exit", None)
            except Exception:
                pass
            close_session = getattr(self.session, "close", None)
            if callable(close_session):
                try:
                    close_session()
                except Exception:
                    pass
            try:
                if self.process.stdin is not None:
                    self.process.stdin.close()
            except (OSError, ValueError):
                pass

            try:
                self.process.wait(timeout=spec.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    self.process.terminate()
                except OSError:
                    pass
                try:
                    self.process.wait(timeout=spec.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    try:
                        self.process.kill()
                    except OSError:
                        pass
                    try:
                        self.process.wait(timeout=spec.shutdown_timeout_seconds)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            self.backend._cleanup_container(self.cidfile)
            self.stderr_thread.join(timeout=1.0)
            _close_process_pipes(self.process)
            shutil.rmtree(self.job_root, ignore_errors=True)

    def __enter__(self) -> "PodmanLspHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


SessionFactory = Callable[..., LspRequestSession]


class PodmanLspBackend:
    """Run one trusted language server in a constrained Podman container.

    The source tree presented to the server is a disposable copy mounted
    read-only at `/workspace`. The configured image must already exist locally;
    Origin Forge resolves it to an immutable local image ID and uses
    `--pull=never`. The model never chooses the image, executable, or argv.
    """

    def __init__(
        self,
        state_dir: str | Path,
        spec: PodmanLspServerSpec,
        *,
        session_factory: SessionFactory = LspJsonRpcSession,
    ):
        self.state_dir = Path(state_dir).resolve()
        self.spec = spec
        self.session_factory = session_factory
        self._resolved_image_id: str | None = None

    def _podman(self) -> str | None:
        return shutil.which(self.spec.podman_executable)

    def _probe_image_id(self) -> str | None:
        executable = self._podman()
        if executable is None:
            return None
        try:
            result = subprocess.run(
                [
                    executable,
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    self.spec.image,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.spec.probe_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        image_id = result.stdout.strip()
        if result.returncode != 0 or not image_id:
            return None
        return image_id

    @property
    def provenance(self) -> dict[str, object]:
        return {
            "backend": "podman-lsp",
            "server_id": self.spec.server_id,
            "configured_image": self.spec.image,
            "resolved_image_id": self._resolved_image_id,
            "argv": list(self.spec.argv),
            "network_allowed": self.spec.network_allowed,
            "memory": self.spec.memory,
            "cpus": self.spec.cpus,
            "pids_limit": self.spec.pids_limit,
        }

    def available(self) -> bool:
        self._resolved_image_id = self._probe_image_id()
        return self._resolved_image_id is not None

    @staticmethod
    def _copy_workspace(source: Path, destination: Path) -> None:
        protected = {".git", ".origin-forge"}

        def ignore(directory: str, names: list[str]) -> set[str]:
            root = Path(directory)
            ignored: set[str] = set()
            for name in names:
                if name.casefold() in protected:
                    ignored.add(name)
                    continue
                try:
                    if (root / name).is_symlink():
                        ignored.add(name)
                except OSError:
                    ignored.add(name)
            return ignored

        shutil.copytree(source, destination, symlinks=False, ignore=ignore)

    def _build_command(
        self,
        workspace_copy: Path,
        image_id: str,
        cidfile: Path,
    ) -> list[str]:
        executable = self._podman() or self.spec.podman_executable
        command = [
            executable,
            "run",
            "--rm",
            "--pull=never",
            "-i",
            f"--cidfile={cidfile}",
            "--read-only",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            f"--pids-limit={self.spec.pids_limit}",
            f"--memory={self.spec.memory}",
            f"--cpus={self.spec.cpus}",
            "--workdir=/workspace",
            "--tmpfs=/tmp:rw,nosuid,nodev",
            "--tmpfs=/run:rw,nosuid,nodev",
            "--env",
            "HOME=/tmp",
            "--env",
            "XDG_CACHE_HOME=/tmp/cache",
            "--mount",
            f"type=bind,src={workspace_copy},target=/workspace,ro=true",
        ]
        if not self.spec.network_allowed:
            command.append("--network=none")
        command.extend(
            [
                "--entrypoint",
                self.spec.argv[0],
                image_id,
                *self.spec.argv[1:],
            ]
        )
        return command

    def _cleanup_container(self, cidfile: Path) -> None:
        executable = self._podman()
        if executable is None:
            return
        try:
            subprocess.run(
                [
                    executable,
                    "rm",
                    "--force",
                    "--time",
                    "0",
                    "--ignore",
                    f"--cidfile={cidfile}",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.spec.probe_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def start(self, workspace_path: str | Path) -> PodmanLspHandle:
        image_id = self._resolved_image_id or self._probe_image_id()
        if image_id is None:
            raise PodmanLspUnavailable(
                f"Podman or configured local LSP image is unavailable: {self.spec.image}"
            )
        self._resolved_image_id = image_id

        source = Path(workspace_path).resolve()
        if not source.is_dir():
            raise PodmanLspUnavailable(f"Workspace path is unavailable: {source}")

        job_root = self.state_dir / "lsp-jobs" / str(uuid4())
        workspace_copy = job_root / "workspace"
        cidfile = job_root / "container.cid"
        job_root.mkdir(parents=True, exist_ok=False)
        process: subprocess.Popen | None = None
        session: LspRequestSession | None = None
        stderr_capture = _BoundedStderr(self.spec.max_stderr_bytes)
        stderr_thread: threading.Thread | None = None
        try:
            self._copy_workspace(source, workspace_copy)
            command = self._build_command(workspace_copy, image_id, cidfile)
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    bufsize=0,
                )
            except OSError as exc:
                raise PodmanLspUnavailable(
                    f"cannot start Podman LSP container: {exc}"
                ) from exc
            if process.stdin is None or process.stdout is None or process.stderr is None:
                raise PodmanLspError("Podman LSP process did not expose stdio pipes")

            stderr_thread = threading.Thread(
                target=stderr_capture.consume,
                args=(process.stderr,),
                name=f"origin-forge-lsp-stderr-{self.spec.server_id}",
                daemon=True,
            )
            stderr_thread.start()

            session = self.session_factory(
                process.stdout,
                process.stdin,
                max_message_bytes=self.spec.max_protocol_message_bytes,
                max_pending_notifications=self.spec.max_pending_notifications,
            )
            mapper = LspWorkspaceMapper(
                workspace_copy,
                server_root_uri="file:///workspace",
            )
            capabilities = initialize_lsp_session(
                session,
                mapper,
                timeout_seconds=self.spec.initialize_timeout_seconds,
            )
            provider = LspCodeIntelligenceProvider(
                RepositoryReader(workspace_copy),
                session,
                capabilities,
                mapper=mapper,
                provider_id=f"lsp:{self.spec.server_id}",
                request_timeout_seconds=self.spec.request_timeout_seconds,
            )
            return PodmanLspHandle(
                backend=self,
                process=process,
                session=session,
                provider=provider,
                job_root=job_root,
                workspace_copy=workspace_copy,
                cidfile=cidfile,
                stderr_capture=stderr_capture,
                stderr_thread=stderr_thread,
            )
        except Exception:
            if session is not None:
                close_session = getattr(session, "close", None)
                if callable(close_session):
                    try:
                        close_session()
                    except Exception:
                        pass
            if process is not None:
                try:
                    if process.stdin is not None:
                        process.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    process.terminate()
                except OSError:
                    pass
                try:
                    process.wait(timeout=self.spec.shutdown_timeout_seconds)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=self.spec.shutdown_timeout_seconds)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            if stderr_thread is not None:
                stderr_thread.join(timeout=1.0)
            if process is not None:
                _close_process_pipes(process)
            self._cleanup_container(cidfile)
            shutil.rmtree(job_root, ignore_errors=True)
            raise
