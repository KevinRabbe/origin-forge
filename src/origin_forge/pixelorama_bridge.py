from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping

from .pixelorama_models import (
    BridgeOperation,
    BridgeOutputType,
    BridgeResultStatus,
    PixeloramaBridgeRequest,
    PixeloramaBridgeResult,
)
from .pixelorama_png import PngError, inspect_rgba8_png
from .pixelorama_protocol import PixeloramaProtocolError, parse_bridge_result
from .runtime import OriginForgeRuntime


_MAX_BRIDGE_PACKAGE_BYTES = 16 * 1024 * 1024
_MAX_RESULT_BYTES = 2 * 1024 * 1024
_MAX_PROFILE_ARGS = 32
_MAX_ARG_CHARS = 4096


class PixeloramaBridgeError(RuntimeError):
    pass


class PixeloramaBridgeUnavailable(PixeloramaBridgeError):
    pass


class PixeloramaBridgeIntegrityError(PixeloramaBridgeError):
    pass


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
                raise PixeloramaBridgeIntegrityError(
                    f"{label} exceeds byte limit ({total} > {maximum})"
                )
            digest.update(chunk)
    return "sha256:" + digest.hexdigest(), total


def _safe_existing_file(path: Path, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise PixeloramaBridgeIntegrityError(f"{label} may not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PixeloramaBridgeIntegrityError(f"{label} is unavailable") from exc
    if not resolved.is_file():
        raise PixeloramaBridgeIntegrityError(f"{label} must be a regular file")
    return resolved


@dataclass(frozen=True)
class PixeloramaBridgeProfile:
    bridge_id: str
    bridge_version: str
    bridge_fingerprint: str
    pixelorama_executable: Path
    bridge_package: Path
    allowed_operations: tuple[BridgeOperation, ...]
    launcher_args: tuple[str, ...] = ()
    protocol_version: int = 1
    timeout_seconds: int = 60
    max_stdout_bytes: int = 64 * 1024
    max_stderr_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if (
            not isinstance(self.bridge_id, str)
            or not self.bridge_id
            or len(self.bridge_id) > 128
            or any(character.isspace() or ord(character) < 32 for character in self.bridge_id)
        ):
            raise ValueError("bridge_id must be a bounded non-whitespace identifier")
        if not isinstance(self.bridge_version, str) or not self.bridge_version.strip() or len(self.bridge_version) > 256:
            raise ValueError("bridge_version must be a bounded non-empty string")
        if (
            not isinstance(self.bridge_fingerprint, str)
            or not self.bridge_fingerprint.startswith("sha256:")
            or len(self.bridge_fingerprint) != 71
        ):
            raise ValueError("bridge_fingerprint must be a sha256: digest")
        try:
            int(self.bridge_fingerprint.split(":", 1)[1], 16)
        except ValueError as exc:
            raise ValueError("bridge_fingerprint must be lowercase hexadecimal") from exc
        if self.bridge_fingerprint.lower() != self.bridge_fingerprint:
            raise ValueError("bridge_fingerprint must be lowercase hexadecimal")
        if self.protocol_version != 1:
            raise ValueError("unsupported Pixelorama bridge protocol_version")
        operations = tuple(self.allowed_operations)
        if not operations or any(not isinstance(value, BridgeOperation) for value in operations):
            raise ValueError("allowed_operations must contain BridgeOperation values")
        if len(operations) != len(set(operations)):
            raise ValueError("allowed_operations contains duplicates")
        args = tuple(self.launcher_args)
        if len(args) > _MAX_PROFILE_ARGS:
            raise ValueError("launcher_args exceeds item limit")
        for value in args:
            if (
                not isinstance(value, str)
                or len(value) > _MAX_ARG_CHARS
                or "\x00" in value
            ):
                raise ValueError("launcher_args contains an invalid argument")
        for value, name, maximum in (
            (self.timeout_seconds, "timeout_seconds", 3600),
            (self.max_stdout_bytes, "max_stdout_bytes", 16 * 1024 * 1024),
            (self.max_stderr_bytes, "max_stderr_bytes", 16 * 1024 * 1024),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > maximum
            ):
                raise ValueError(f"{name} must be between 1 and {maximum}")
        object.__setattr__(self, "allowed_operations", tuple(sorted(operations, key=lambda value: value.value)))
        object.__setattr__(self, "launcher_args", args)

    def verify_installation(self) -> tuple[Path, Path]:
        executable = _safe_existing_file(self.pixelorama_executable, "Pixelorama executable")
        package = _safe_existing_file(self.bridge_package, "Pixelorama bridge package")
        fingerprint, _ = _sha256_file(
            package,
            _MAX_BRIDGE_PACKAGE_BYTES,
            "Pixelorama bridge package",
        )
        if fingerprint != self.bridge_fingerprint:
            raise PixeloramaBridgeIntegrityError(
                "Pixelorama bridge package fingerprint mismatch"
            )
        return executable, package


@dataclass(frozen=True)
class PixeloramaOperationResult:
    request: PixeloramaBridgeRequest
    bridge_result: PixeloramaBridgeResult
    workspace_path: Path
    process_exit_code: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool

    @property
    def succeeded(self) -> bool:
        return (
            self.process_exit_code == 0
            and self.bridge_result.status == BridgeResultStatus.SUCCEEDED
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.request.operation_id,
            "workspace_id": self.request.workspace_id,
            "request_hash": self.request.content_hash,
            "bridge_result_hash": self.bridge_result.content_hash,
            "bridge_status": self.bridge_result.status.value,
            "process_exit_code": self.process_exit_code,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "succeeded": self.succeeded,
            "production_verification_changed": False,
            "canonical_asset_adopted": False,
        }


class PixeloramaBridgeAdapter:
    """One-shot deterministic Pixelorama bridge process over an isolated media workspace."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: PixeloramaBridgeProfile,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, PixeloramaBridgeProfile):
            raise TypeError("profile must be a PixeloramaBridgeProfile")
        self.runtime = runtime
        self.profile = profile
        self.media_root = runtime.state_dir / "media-workspaces"

    @staticmethod
    def _drain(stream: BinaryIO, maximum: int, sink: dict[str, object]) -> None:
        retained = bytearray()
        total = 0
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            total += len(chunk)
            if len(retained) <= maximum:
                keep = max(0, maximum + 1 - len(retained))
                retained.extend(chunk[:keep])
        sink["data"] = bytes(retained[:maximum])
        sink["truncated"] = total > maximum
        sink["total"] = total

    def _workspace(self, request: PixeloramaBridgeRequest) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.media_root.is_symlink():
            raise PixeloramaBridgeIntegrityError(
                "media workspace root may not be a symlink"
            )
        self.media_root.mkdir(parents=True, exist_ok=True)
        try:
            self.media_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PixeloramaBridgeIntegrityError(
                "media workspace root escapes protected project state"
            ) from exc
        workspace = self.media_root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise PixeloramaBridgeIntegrityError(
                f"media workspace already exists: {request.workspace_id}"
            )
        workspace.mkdir()
        for name in ("inputs", "project", "exports"):
            (workspace / name).mkdir()
        return workspace

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        data = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def _stage_inputs(
        self,
        request: PixeloramaBridgeRequest,
        workspace: Path,
        staged_inputs: Mapping[str, Path],
    ) -> None:
        expected = {value.relative_path: value for value in request.input_refs}
        if set(staged_inputs) != set(expected):
            raise PixeloramaBridgeIntegrityError(
                "staged input paths must exactly match request input refs"
            )
        for relative_path, source_path in staged_inputs.items():
            if not relative_path.startswith("inputs/"):
                raise PixeloramaBridgeIntegrityError(
                    "bridge input refs must stay under inputs/"
                )
            source = _safe_existing_file(source_path, "Pixelorama staged input")
            ref = expected[relative_path]
            digest, byte_count = _sha256_file(
                source,
                request.budget.max_input_bytes,
                "Pixelorama staged input",
            )
            if digest != ref.content_hash or byte_count != ref.byte_count:
                raise PixeloramaBridgeIntegrityError(
                    f"staged input does not match frozen ref: {relative_path}"
                )
            destination = workspace / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            current = workspace
            for part in Path(relative_path).parts:
                current = current / part
                if current.is_symlink():
                    raise PixeloramaBridgeIntegrityError(
                        "staged input destination contains a symlink"
                    )
            with source.open("rb") as src, destination.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())

    def _expected_outputs(
        self,
        request: PixeloramaBridgeRequest,
    ) -> dict[str, BridgeOutputType]:
        expected = {
            value.relative_path: value.output_type for value in request.export_specs
        }
        if request.operation == BridgeOperation.CREATE_SPRITE_PROJECT:
            assert request.sprite_spec is not None
            expected[f"project/{request.sprite_spec.output_basename}.pxo"] = (
                BridgeOutputType.PIXELORAMA_PROJECT
            )
        return expected

    def _validate_outputs(
        self,
        request: PixeloramaBridgeRequest,
        result: PixeloramaBridgeResult,
        workspace: Path,
    ) -> None:
        expected = self._expected_outputs(request)
        actual = {value.relative_path: value for value in result.outputs}
        if result.status == BridgeResultStatus.SUCCEEDED:
            if set(actual) != set(expected):
                raise PixeloramaBridgeIntegrityError(
                    "successful bridge result output set does not match declared outputs"
                )
        elif actual:
            raise PixeloramaBridgeIntegrityError(
                "failed/blocked bridge result may not publish outputs"
            )
        total = 0
        for relative_path, output in actual.items():
            if output.output_type != expected[relative_path]:
                raise PixeloramaBridgeIntegrityError(
                    f"bridge output type mismatch: {relative_path}"
                )
            path = workspace / relative_path
            if path.is_symlink() or not path.is_file():
                raise PixeloramaBridgeIntegrityError(
                    f"declared bridge output is missing or unsafe: {relative_path}"
                )
            digest, byte_count = _sha256_file(
                path,
                request.budget.max_output_bytes,
                "Pixelorama bridge output",
            )
            total += byte_count
            if total > request.budget.max_output_bytes:
                raise PixeloramaBridgeIntegrityError(
                    "bridge output byte total exceeds request budget"
                )
            if digest != output.content_hash or byte_count != output.byte_count:
                raise PixeloramaBridgeIntegrityError(
                    f"bridge output hash/size mismatch: {relative_path}"
                )
            if output.output_type in {BridgeOutputType.PNG, BridgeOutputType.SPRITESHEET}:
                try:
                    inspection = inspect_rgba8_png(path.read_bytes())
                except (OSError, PngError) as exc:
                    raise PixeloramaBridgeIntegrityError(
                        f"bridge raster output is invalid: {relative_path}"
                    ) from exc
                if output.width != inspection.width or output.height != inspection.height:
                    raise PixeloramaBridgeIntegrityError(
                        f"bridge raster dimensions mismatch: {relative_path}"
                    )

    def _validate_file_set(
        self,
        request: PixeloramaBridgeRequest,
        workspace: Path,
        result: PixeloramaBridgeResult,
    ) -> None:
        allowed = {
            "request.json",
            "result.json",
            *(value.relative_path for value in request.input_refs),
            *(value.relative_path for value in result.outputs),
        }
        actual: set[str] = set()
        for path in workspace.rglob("*"):
            if path.is_dir():
                continue
            if path.is_symlink():
                raise PixeloramaBridgeIntegrityError(
                    "Pixelorama operation produced a symlink"
                )
            actual.add(path.relative_to(workspace).as_posix())
        unexpected = actual - allowed
        if unexpected:
            raise PixeloramaBridgeIntegrityError(
                f"Pixelorama operation produced undeclared files: {sorted(unexpected)}"
            )

    def execute(
        self,
        request: PixeloramaBridgeRequest,
        *,
        staged_inputs: Mapping[str, Path] | None = None,
    ) -> PixeloramaOperationResult:
        if not isinstance(request, PixeloramaBridgeRequest):
            raise TypeError("request must be a PixeloramaBridgeRequest")
        if request.protocol_version != self.profile.protocol_version:
            raise PixeloramaBridgeUnavailable(
                "request protocol version does not match bridge profile"
            )
        if request.operation not in self.profile.allowed_operations:
            raise PixeloramaBridgeUnavailable(
                f"bridge operation is not allowed by profile: {request.operation.value}"
            )
        if request.budget.timeout_seconds > self.profile.timeout_seconds:
            raise PixeloramaBridgeUnavailable(
                "request timeout exceeds trusted bridge profile limit"
            )
        executable, _ = self.profile.verify_installation()
        workspace = self._workspace(request)
        self._stage_inputs(request, workspace, staged_inputs or {})
        request_path = workspace / "request.json"
        result_path = workspace / "result.json"
        self._write_json(request_path, request.to_dict())

        command = [
            str(executable),
            *self.profile.launcher_args,
            "--",
            "--origin-forge-request",
            str(request_path),
            "--origin-forge-result",
            str(result_path),
        ]
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as exc:
            raise PixeloramaBridgeUnavailable(
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
            exit_code = process.wait(timeout=request.budget.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            raise PixeloramaBridgeUnavailable(
                "Pixelorama bridge operation exceeded timeout"
            ) from exc
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            raise PixeloramaBridgeIntegrityError(
                "Pixelorama bridge output streams did not terminate cleanly"
            )
        stdout = stdout_sink.get("data", b"")
        stderr = stderr_sink.get("data", b"")
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            raise PixeloramaBridgeIntegrityError("bridge output capture failed")

        if not result_path.exists() or result_path.is_symlink() or not result_path.is_file():
            raise PixeloramaBridgeIntegrityError(
                "Pixelorama bridge did not produce a safe result.json"
            )
        if result_path.stat().st_size > _MAX_RESULT_BYTES:
            raise PixeloramaBridgeIntegrityError("Pixelorama result.json exceeds byte limit")
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8"))
            bridge_result = parse_bridge_result(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, PixeloramaProtocolError) as exc:
            raise PixeloramaBridgeIntegrityError(
                "Pixelorama bridge result validation failed"
            ) from exc
        if bridge_result.operation_id != request.operation_id:
            raise PixeloramaBridgeIntegrityError("bridge result operation_id mismatch")
        if bridge_result.request_hash != request.content_hash:
            raise PixeloramaBridgeIntegrityError("bridge result request hash mismatch")
        if bridge_result.bridge_version != self.profile.bridge_version:
            raise PixeloramaBridgeIntegrityError("bridge result version mismatch")
        if bridge_result.bridge_fingerprint != self.profile.bridge_fingerprint:
            raise PixeloramaBridgeIntegrityError("bridge result fingerprint mismatch")
        if exit_code != 0 and bridge_result.status == BridgeResultStatus.SUCCEEDED:
            raise PixeloramaBridgeIntegrityError(
                "bridge reported success despite non-zero process exit code"
            )
        self._validate_outputs(request, bridge_result, workspace)
        self._validate_file_set(request, workspace, bridge_result)
        return PixeloramaOperationResult(
            request=request,
            bridge_result=bridge_result,
            workspace_path=workspace,
            process_exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=bool(stdout_sink.get("truncated", False)),
            stderr_truncated=bool(stderr_sink.get("truncated", False)),
        )
