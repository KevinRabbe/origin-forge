from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .ids import IdKind, new_id, validate_id
from .path_policy import portable_relative_path
from .pixelorama_models import BridgeOperation, canonical_hash, validate_sha256
from .pixelorama_png import PngError, inspect_rgba8_png
from .runtime import OriginForgeRuntime


class PixeloramaCliError(RuntimeError):
    pass


class PixeloramaCliUnavailable(PixeloramaCliError):
    pass


class PixeloramaCliIntegrityError(PixeloramaCliError):
    pass


def _bounded_relative_path(value: str, *, prefix: str, suffix: str, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(f"{field} must be a bounded relative path")
    try:
        path = portable_relative_path(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    normalized = path.as_posix()
    if not normalized.startswith(prefix) or not normalized.endswith(suffix):
        raise ValueError(f"{field} must be under {prefix} and end with {suffix}")
    return normalized


def _sha256_file(path: Path, maximum: int, label: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise PixeloramaCliIntegrityError(
                    f"{label} exceeds byte limit ({total} > {maximum})"
                )
            digest.update(chunk)
    return "sha256:" + digest.hexdigest(), total


def _safe_existing_file(path: Path, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise PixeloramaCliIntegrityError(f"{label} may not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PixeloramaCliIntegrityError(f"{label} is unavailable") from exc
    if not resolved.is_file():
        raise PixeloramaCliIntegrityError(f"{label} must be a regular file")
    return resolved


@dataclass(frozen=True)
class PixeloramaCliExportRequest:
    operation_id: str
    workspace_id: str
    operation: BridgeOperation
    source_relative_path: str
    source_hash: str
    source_byte_count: int
    output_relative_path: str
    timeout_seconds: int = 60
    max_output_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.PIXELORAMA_OPERATION):
            raise ValueError("operation_id must be a PXOP ID")
        if not validate_id(self.workspace_id, IdKind.MEDIA_WORKSPACE):
            raise ValueError("workspace_id must be a MEDIA ID")
        if self.operation != BridgeOperation.EXPORT_SPRITESHEET:
            raise ValueError("v0 official CLI adapter supports EXPORT_SPRITESHEET only")
        source = _bounded_relative_path(
            self.source_relative_path,
            prefix="inputs/",
            suffix=".pxo",
            field="source_relative_path",
        )
        output = _bounded_relative_path(
            self.output_relative_path,
            prefix="exports/",
            suffix=".png",
            field="output_relative_path",
        )
        validate_sha256(self.source_hash, "source_hash")
        for value, name, maximum in (
            (self.source_byte_count, "source_byte_count", 2 * 1024 * 1024 * 1024),
            (self.timeout_seconds, "timeout_seconds", 3600),
            (self.max_output_bytes, "max_output_bytes", 2 * 1024 * 1024 * 1024),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > maximum
            ):
                raise ValueError(f"{name} must be between 1 and {maximum}")
        object.__setattr__(self, "source_relative_path", source)
        object.__setattr__(self, "output_relative_path", output)

    @classmethod
    def create(
        cls,
        *,
        source_hash: str,
        source_byte_count: int,
        source_relative_path: str = "inputs/source.pxo",
        output_relative_path: str = "exports/spritesheet.png",
        timeout_seconds: int = 60,
        max_output_bytes: int = 128 * 1024 * 1024,
    ) -> "PixeloramaCliExportRequest":
        return cls(
            operation_id=new_id(IdKind.PIXELORAMA_OPERATION),
            workspace_id=new_id(IdKind.MEDIA_WORKSPACE),
            operation=BridgeOperation.EXPORT_SPRITESHEET,
            source_relative_path=source_relative_path,
            source_hash=source_hash,
            source_byte_count=source_byte_count,
            output_relative_path=output_relative_path,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def _content_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "operation": self.operation.value,
            "source_relative_path": self.source_relative_path,
            "source_hash": self.source_hash,
            "source_byte_count": self.source_byte_count,
            "output_relative_path": self.output_relative_path,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
        }

    def to_dict(self) -> dict[str, object]:
        value = self._content_dict()
        value["content_hash"] = self.content_hash
        return value


@dataclass(frozen=True)
class PixeloramaCliProfile:
    pixelorama_executable: Path
    pixelorama_fingerprint: str
    expected_pixelorama_version: str
    allowed_operations: tuple[BridgeOperation, ...] = (
        BridgeOperation.EXPORT_SPRITESHEET,
    )
    timeout_seconds: int = 60
    max_stdout_bytes: int = 64 * 1024
    max_stderr_bytes: int = 64 * 1024
    max_executable_bytes: int = 2 * 1024 * 1024 * 1024
    max_runtime_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        validate_sha256(self.pixelorama_fingerprint, "pixelorama_fingerprint")
        if (
            not isinstance(self.expected_pixelorama_version, str)
            or not self.expected_pixelorama_version.strip()
            or self.expected_pixelorama_version != self.expected_pixelorama_version.strip()
            or "\n" in self.expected_pixelorama_version
            or "\r" in self.expected_pixelorama_version
            or len(self.expected_pixelorama_version) > 256
            or "\x00" in self.expected_pixelorama_version
        ):
            raise ValueError("expected_pixelorama_version must be one bounded non-empty line")
        operations = tuple(self.allowed_operations)
        if (
            not operations
            or any(value != BridgeOperation.EXPORT_SPRITESHEET for value in operations)
            or len(operations) != len(set(operations))
        ):
            raise ValueError("official CLI profile may allow EXPORT_SPRITESHEET only in v0")
        for value, name, maximum in (
            (self.timeout_seconds, "timeout_seconds", 3600),
            (self.max_stdout_bytes, "max_stdout_bytes", 16 * 1024 * 1024),
            (self.max_stderr_bytes, "max_stderr_bytes", 16 * 1024 * 1024),
            (self.max_executable_bytes, "max_executable_bytes", 8 * 1024 * 1024 * 1024),
            (self.max_runtime_bytes, "max_runtime_bytes", 2 * 1024 * 1024 * 1024),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > maximum
            ):
                raise ValueError(f"{name} must be between 1 and {maximum}")
        object.__setattr__(self, "allowed_operations", operations)

    def verify_executable(self) -> Path:
        executable = _safe_existing_file(
            self.pixelorama_executable,
            "Pixelorama executable",
        )
        fingerprint, _ = _sha256_file(
            executable,
            self.max_executable_bytes,
            "Pixelorama executable",
        )
        if fingerprint != self.pixelorama_fingerprint:
            raise PixeloramaCliIntegrityError(
                "Pixelorama executable fingerprint mismatch"
            )
        return executable


@dataclass(frozen=True)
class PixeloramaCliExportResult:
    request: PixeloramaCliExportRequest
    workspace_path: Path
    pixelorama_version: str
    process_exit_code: int
    output_hash: str
    output_byte_count: int
    width: int
    height: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.request.operation_id,
            "workspace_id": self.request.workspace_id,
            "request_hash": self.request.content_hash,
            "operation": self.request.operation.value,
            "pixelorama_version": self.pixelorama_version,
            "process_exit_code": self.process_exit_code,
            "output_relative_path": self.request.output_relative_path,
            "output_hash": self.output_hash,
            "output_byte_count": self.output_byte_count,
            "width": self.width,
            "height": self.height,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "succeeded": self.process_exit_code == 0,
            "production_verification_changed": False,
            "canonical_asset_adopted": False,
        }


class PixeloramaCliExportAdapter:
    """Use Pixelorama's documented desktop CLI to export one opaque .pxo copy."""

    def __init__(self, runtime: OriginForgeRuntime, profile: PixeloramaCliProfile):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, PixeloramaCliProfile):
            raise TypeError("profile must be a PixeloramaCliProfile")
        self.runtime = runtime
        self.profile = profile
        self.media_root = runtime.state_dir / "media-workspaces"

    @staticmethod
    def _drain(stream: BinaryIO, maximum: int, sink: dict[str, object]) -> None:
        retained = bytearray()
        total = 0
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                if len(retained) <= maximum:
                    keep = max(0, maximum + 1 - len(retained))
                    retained.extend(chunk[:keep])
        finally:
            sink["data"] = bytes(retained[:maximum])
            sink["truncated"] = total > maximum
            sink["total"] = total
            stream.close()

    def _workspace(self, request: PixeloramaCliExportRequest) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.media_root.is_symlink():
            raise PixeloramaCliIntegrityError("media workspace root may not be a symlink")
        self.media_root.mkdir(parents=True, exist_ok=True)
        try:
            self.media_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PixeloramaCliIntegrityError(
                "media workspace root escapes protected project state"
            ) from exc
        workspace = self.media_root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise PixeloramaCliIntegrityError(
                f"media workspace already exists: {request.workspace_id}"
            )
        workspace.mkdir()
        for name in ("inputs", "exports", "runtime"):
            (workspace / name).mkdir()
        return workspace

    @staticmethod
    def _validate_workspace_root(workspace: Path, name: str) -> Path:
        root = workspace / name
        if root.is_symlink():
            raise PixeloramaCliIntegrityError(
                f"Pixelorama CLI {name} workspace root may not be a symlink"
            )
        try:
            workspace_resolved = workspace.resolve(strict=True)
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PixeloramaCliIntegrityError(
                f"Pixelorama CLI {name} workspace root is unavailable"
            ) from exc
        if not resolved.is_dir() or resolved.parent != workspace_resolved:
            raise PixeloramaCliIntegrityError(
                f"Pixelorama CLI {name} workspace root escaped containment"
            )
        return resolved

    @classmethod
    def _validate_relative_components(
        cls,
        workspace: Path,
        relative_path: str,
        label: str,
    ) -> Path:
        workspace_resolved = workspace.resolve(strict=True)
        current = workspace
        for part in Path(relative_path).parts:
            current = current / part
            if current.is_symlink():
                raise PixeloramaCliIntegrityError(
                    f"{label} contains a symlink component"
                )
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(workspace_resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PixeloramaCliIntegrityError(
                f"{label} escaped the media workspace"
            ) from exc
        return resolved

    @classmethod
    def _validate_relative_parent_components(
        cls,
        workspace: Path,
        relative_path: str,
        label: str,
    ) -> Path:
        workspace_resolved = workspace.resolve(strict=True)
        relative = Path(relative_path)
        current = workspace
        for part in relative.parent.parts:
            current = current / part
            if current.is_symlink():
                raise PixeloramaCliIntegrityError(
                    f"{label} contains a symlink parent component"
                )
        try:
            resolved_parent = current.resolve(strict=True)
            resolved_parent.relative_to(workspace_resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PixeloramaCliIntegrityError(
                f"{label} parent escaped the media workspace"
            ) from exc
        candidate = workspace / relative
        if candidate.is_symlink():
            raise PixeloramaCliIntegrityError(f"{label} may not be a symlink")
        return candidate

    def _validate_workspace_containment(
        self,
        workspace: Path,
        request: PixeloramaCliExportRequest,
    ) -> None:
        for name in ("inputs", "exports", "runtime"):
            self._validate_workspace_root(workspace, name)
        self._validate_relative_components(
            workspace,
            request.source_relative_path,
            "Pixelorama CLI staged source",
        )
        self._validate_relative_parent_components(
            workspace,
            request.output_relative_path,
            "Pixelorama CLI declared output",
        )

    def _stage_source(
        self,
        request: PixeloramaCliExportRequest,
        source_path: Path,
        workspace: Path,
    ) -> Path:
        source = _safe_existing_file(source_path, "Pixelorama source project")
        digest, byte_count = _sha256_file(
            source,
            request.source_byte_count,
            "Pixelorama source project",
        )
        if digest != request.source_hash or byte_count != request.source_byte_count:
            raise PixeloramaCliIntegrityError(
                "Pixelorama source project does not match frozen hash/size"
            )
        destination = workspace / request.source_relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        return destination

    def _isolated_environment(self, workspace: Path) -> dict[str, str]:
        env = dict(os.environ)
        runtime = workspace / "runtime"
        home = runtime / "home"
        data = runtime / "data"
        config = runtime / "config"
        cache = runtime / "cache"
        for path in (home, data, config, cache):
            path.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "HOME": str(home),
                "PWD": str(workspace),
                "XDG_DATA_HOME": str(data),
                "XDG_CONFIG_HOME": str(config),
                "XDG_CACHE_HOME": str(cache),
                "APPDATA": str(data),
                "LOCALAPPDATA": str(data),
            }
        )
        return env

    def _run(
        self,
        command: list[str],
        *,
        workspace: Path,
        timeout_seconds: int,
    ) -> tuple[int, bytes, bytes, bool, bool]:
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=self._isolated_environment(workspace),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as exc:
            raise PixeloramaCliUnavailable(
                "failed to launch configured Pixelorama executable"
            ) from exc
        assert process.stdout is not None and process.stderr is not None
        stdout_sink: dict[str, object] = {}
        stderr_sink: dict[str, object] = {}
        stdout_thread = threading.Thread(
            target=self._drain,
            args=(process.stdout, self.profile.max_stdout_bytes, stdout_sink),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._drain,
            args=(process.stderr, self.profile.max_stderr_bytes, stderr_sink),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            raise PixeloramaCliUnavailable(
                "Pixelorama CLI operation exceeded timeout"
            ) from exc
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            raise PixeloramaCliIntegrityError(
                "Pixelorama CLI output streams did not terminate cleanly"
            )
        stdout = stdout_sink.get("data", b"")
        stderr = stderr_sink.get("data", b"")
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            raise PixeloramaCliIntegrityError("Pixelorama CLI output capture failed")
        return (
            exit_code,
            stdout,
            stderr,
            bool(stdout_sink.get("truncated", False)),
            bool(stderr_sink.get("truncated", False)),
        )

    def probe_version(self) -> str:
        executable = self.profile.verify_executable()
        probe_root = self.runtime.state_dir / "pixelorama-cli-probe"
        if probe_root.is_symlink():
            raise PixeloramaCliIntegrityError(
                "Pixelorama CLI probe workspace may not be a symlink"
            )
        if probe_root.exists():
            shutil.rmtree(probe_root)
        probe_root.mkdir(parents=True)
        try:
            exit_code, stdout, _stderr, stdout_truncated, _stderr_truncated = self._run(
                [
                    str(executable),
                    "--headless",
                    "--quit",
                    "--",
                    "--pixelorama-version",
                ],
                workspace=probe_root,
                timeout_seconds=min(self.profile.timeout_seconds, 30),
            )
            if exit_code != 0:
                raise PixeloramaCliUnavailable(
                    f"Pixelorama version probe exited with code {exit_code}"
                )
            if stdout_truncated:
                raise PixeloramaCliIntegrityError(
                    "Pixelorama version probe stdout exceeded configured limit"
                )
            try:
                text = stdout.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise PixeloramaCliIntegrityError(
                    "Pixelorama version probe output is not UTF-8"
                ) from exc
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if self.profile.expected_pixelorama_version not in lines:
                raise PixeloramaCliIntegrityError(
                    "Pixelorama CLI version does not match trusted profile exactly"
                )
            return self.profile.expected_pixelorama_version
        finally:
            shutil.rmtree(probe_root, ignore_errors=True)

    def _validate_runtime_scratch(self, workspace: Path) -> None:
        runtime_root = self._validate_workspace_root(workspace, "runtime")
        total = 0
        for path in runtime_root.rglob("*"):
            if path.is_symlink():
                raise PixeloramaCliIntegrityError(
                    "Pixelorama CLI runtime scratch contains a symlink"
                )
            if path.is_file():
                total += path.stat().st_size
                if total > self.profile.max_runtime_bytes:
                    raise PixeloramaCliIntegrityError(
                        "Pixelorama CLI runtime scratch exceeds byte limit"
                    )

    def execute(
        self,
        request: PixeloramaCliExportRequest,
        *,
        source_path: Path,
    ) -> PixeloramaCliExportResult:
        if not isinstance(request, PixeloramaCliExportRequest):
            raise TypeError("request must be a PixeloramaCliExportRequest")
        if request.operation not in self.profile.allowed_operations:
            raise PixeloramaCliUnavailable(
                f"Pixelorama CLI operation is not allowed: {request.operation.value}"
            )
        if request.timeout_seconds > self.profile.timeout_seconds:
            raise PixeloramaCliUnavailable(
                "request timeout exceeds trusted Pixelorama CLI profile limit"
            )
        executable = self.profile.verify_executable()
        version = self.probe_version()
        workspace = self._workspace(request)
        self._stage_source(request, source_path, workspace)
        output_path = workspace / request.output_relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        command = [
            str(executable),
            "--headless",
            "--quit",
            "--",
            "--spritesheet",
            "--output",
            request.output_relative_path,
            request.source_relative_path,
        ]
        exit_code, stdout, stderr, stdout_truncated, stderr_truncated = self._run(
            command,
            workspace=workspace,
            timeout_seconds=request.timeout_seconds,
        )
        if exit_code != 0:
            raise PixeloramaCliUnavailable(
                f"Pixelorama CLI export exited with code {exit_code}"
            )
        self._validate_workspace_containment(workspace, request)
        output_path = self._validate_relative_parent_components(
            workspace,
            request.output_relative_path,
            "Pixelorama CLI declared output",
        )
        if not output_path.is_file():
            raise PixeloramaCliIntegrityError(
                "Pixelorama CLI did not produce the declared spritesheet"
            )
        output_path = self._validate_relative_components(
            workspace,
            request.output_relative_path,
            "Pixelorama CLI declared output",
        )
        output_hash, output_byte_count = _sha256_file(
            output_path,
            request.max_output_bytes,
            "Pixelorama CLI spritesheet",
        )
        try:
            inspection = inspect_rgba8_png(output_path.read_bytes())
        except (OSError, PngError) as exc:
            raise PixeloramaCliIntegrityError(
                "Pixelorama CLI spritesheet is not a supported RGBA8 PNG"
            ) from exc
        self._validate_runtime_scratch(workspace)

        allowed_roots = {"inputs", "exports", "runtime"}
        for path in workspace.iterdir():
            if path.name not in allowed_roots:
                raise PixeloramaCliIntegrityError(
                    f"Pixelorama CLI produced undeclared workspace entry: {path.name}"
                )
        for path in (workspace / "inputs").rglob("*"):
            if path.is_symlink():
                raise PixeloramaCliIntegrityError("Pixelorama CLI input tree contains a symlink")
        export_files = sorted(
            (
                path
                for path in (workspace / "exports").rglob("*")
                if path.is_file()
            ),
            key=lambda path: path.as_posix(),
        )
        if export_files != [output_path]:
            raise PixeloramaCliIntegrityError(
                "Pixelorama CLI produced undeclared export files"
            )
        return PixeloramaCliExportResult(
            request=request,
            workspace_path=workspace,
            pixelorama_version=version,
            process_exit_code=exit_code,
            output_hash=output_hash,
            output_byte_count=output_byte_count,
            width=inspection.width,
            height=inspection.height,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )