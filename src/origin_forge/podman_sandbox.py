from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from .sandbox import (
    SandboxGuarantees,
    SandboxJob,
    SandboxResult,
    SandboxUnavailable,
)


@dataclass(frozen=True)
class PodmanSandboxSettings:
    image: str
    executable: str = "podman"
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 256
    probe_timeout_seconds: float = 10.0


class _BoundedStream:
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


def run_bounded_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
    cwd: Path | None = None,
) -> SandboxResult:
    if timeout_seconds <= 0 or max_output_bytes <= 0:
        raise ValueError("process limits must be positive")
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    assert process.stdout is not None and process.stderr is not None
    stdout = _BoundedStream(max_output_bytes)
    stderr = _BoundedStream(max_output_bytes)
    stdout_thread = threading.Thread(target=stdout.consume, args=(process.stdout,), daemon=True)
    stderr_thread = threading.Thread(target=stderr.consume, args=(process.stderr,), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    finally:
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        process.stdout.close()
        process.stderr.close()
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    return SandboxResult(
        exit_code=None if timed_out else process.returncode,
        stdout=stdout.text(),
        stderr=stderr.text(),
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout_truncated=stdout.truncated,
        stderr_truncated=stderr.truncated,
    )


class PodmanSandboxBackend:
    backend_id = "podman"
    guarantees = SandboxGuarantees(
        filesystem_isolated=True,
        process_isolated=True,
        host_secrets_isolated=True,
        network_controlled=True,
    )

    def __init__(self, state_dir: str | Path, settings: PodmanSandboxSettings):
        self.state_dir = Path(state_dir).resolve()
        self.settings = settings
        if not settings.image.strip():
            raise ValueError("Podman sandbox image is required")
        if settings.cpus <= 0 or settings.pids_limit <= 0:
            raise ValueError("Podman resource limits must be positive")
        if settings.probe_timeout_seconds <= 0:
            raise ValueError("Podman probe timeout must be positive")
        self._resolved_image_id: str | None = None

    def _probe_image_id(self) -> str | None:
        executable = shutil.which(self.settings.executable)
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
                    self.settings.image,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.probe_timeout_seconds,
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
            "configured_image": self.settings.image,
            "resolved_image_id": self._resolved_image_id,
            "memory": self.settings.memory,
            "cpus": self.settings.cpus,
            "pids_limit": self.settings.pids_limit,
        }

    def available(self) -> bool:
        self._resolved_image_id = self._probe_image_id()
        return self._resolved_image_id is not None

    @staticmethod
    def _copy_workspace(source: Path, destination: Path) -> None:
        def ignore(directory: str, names: list[str]) -> set[str]:
            ignored: set[str] = set()
            if ".git" in names:
                ignored.add(".git")
            if ".origin-forge" in names:
                ignored.add(".origin-forge")
            return ignored

        shutil.copytree(source, destination, symlinks=True, ignore=ignore)

    def _build_command(
        self, job: SandboxJob, workspace_copy: Path, image_id: str, cidfile: Path
    ) -> list[str]:
        executable = shutil.which(self.settings.executable) or self.settings.executable
        command = [
            executable,
            "run",
            "--rm",
            "--pull=never",
            f"--cidfile={cidfile}",
            "--read-only",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            f"--pids-limit={self.settings.pids_limit}",
            f"--memory={self.settings.memory}",
            f"--cpus={self.settings.cpus}",
            "--workdir=/workspace",
            "--tmpfs=/tmp:rw,nosuid,nodev",
            "--tmpfs=/run:rw,nosuid,nodev",
            "--mount",
            f"type=bind,src={workspace_copy},target=/workspace,rw=true",
        ]
        if not job.network_allowed:
            command.append("--network=none")
        for key, value in sorted(job.environment.items()):
            command.extend(["--env", f"{key}={value}"])
        command.extend(["--entrypoint", job.argv[0], image_id, *job.argv[1:]])
        return command

    def _cleanup_container(self, cidfile: Path) -> None:
        executable = shutil.which(self.settings.executable)
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
                timeout=self.settings.probe_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def run(self, job: SandboxJob) -> SandboxResult:
        image_id = self._resolved_image_id or self._probe_image_id()
        if image_id is None:
            raise SandboxUnavailable(
                f"Podman or configured local image is unavailable: {self.settings.image}"
            )
        source = job.workspace_path.resolve()
        if not source.is_dir():
            raise SandboxUnavailable(f"workspace path is unavailable: {source}")

        job_root = self.state_dir / "sandbox-jobs" / str(uuid4())
        workspace_copy = job_root / "workspace"
        cidfile = job_root / "container.cid"
        job_root.mkdir(parents=True, exist_ok=False)
        try:
            self._copy_workspace(source, workspace_copy)
            command = self._build_command(job, workspace_copy, image_id, cidfile)
            return run_bounded_process(
                command,
                timeout_seconds=job.timeout_seconds,
                max_output_bytes=job.max_output_bytes,
            )
        finally:
            self._cleanup_container(cidfile)
            shutil.rmtree(job_root, ignore_errors=True)
