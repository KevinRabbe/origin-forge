from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .blockbench_glb import GlbError, inspect_glb
from .blockbench_models import BlockbenchBridgeRequest, validate_sha256
from .blockbench_protocol import (
    BlockbenchBridgeResult,
    BlockbenchOutputType,
    BlockbenchResultStatus,
)
from .runtime import OriginForgeRuntime


class BlockbenchBridgeError(RuntimeError):
    pass


class BlockbenchBridgeUnavailable(BlockbenchBridgeError):
    pass


class BlockbenchBridgeIntegrityError(BlockbenchBridgeError):
    pass


def _safe_file(path: Path, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise BlockbenchBridgeIntegrityError(f"{label} may not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BlockbenchBridgeIntegrityError(f"{label} is unavailable") from exc
    if not resolved.is_file():
        raise BlockbenchBridgeIntegrityError(f"{label} must be a regular file")
    return resolved


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
                raise BlockbenchBridgeIntegrityError(
                    f"{label} exceeds byte limit ({total} > {maximum})"
                )
            digest.update(chunk)
    return "sha256:" + digest.hexdigest(), total


@dataclass(frozen=True)
class BlockbenchBridgeProfile:
    bridge_executable: Path
    bridge_fingerprint: str
    expected_blockbench_version: str
    max_executable_bytes: int = 512 * 1024 * 1024
    max_result_bytes: int = 1024 * 1024
    max_runtime_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        validate_sha256(self.bridge_fingerprint, "bridge_fingerprint")
        if (
            not isinstance(self.expected_blockbench_version, str)
            or not self.expected_blockbench_version.strip()
            or self.expected_blockbench_version != self.expected_blockbench_version.strip()
            or len(self.expected_blockbench_version) > 128
            or "\x00" in self.expected_blockbench_version
            or "\n" in self.expected_blockbench_version
            or "\r" in self.expected_blockbench_version
        ):
            raise ValueError(
                "expected_blockbench_version must be one bounded non-empty line"
            )
        for value, field, maximum in (
            (self.max_executable_bytes, "max_executable_bytes", 2 * 1024 * 1024 * 1024),
            (self.max_result_bytes, "max_result_bytes", 16 * 1024 * 1024),
            (self.max_runtime_bytes, "max_runtime_bytes", 2 * 1024 * 1024 * 1024),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= maximum
            ):
                raise ValueError(f"{field} is outside the allowed range")

    def verify_executable(self) -> Path:
        executable = _safe_file(self.bridge_executable, "Blockbench bridge executable")
        fingerprint, _ = _sha256_file(
            executable,
            self.max_executable_bytes,
            "Blockbench bridge executable",
        )
        if fingerprint != self.bridge_fingerprint:
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge executable fingerprint mismatch"
            )
        return executable


@dataclass(frozen=True)
class BlockbenchBridgeExecution:
    request: BlockbenchBridgeRequest
    result: BlockbenchBridgeResult
    workspace_path: Path
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.request.operation_id,
            "workspace_id": self.request.workspace_id,
            "request_hash": self.request.content_hash,
            "result_hash": self.result.content_hash,
            "status": self.result.status.value,
            "blockbench_version": self.result.blockbench_version,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "production_verification_changed": False,
            "canonical_asset_adopted": False,
        }


class BlockbenchBridgeAdapter:
    """Execute one fingerprinted bridge process inside an isolated 3D workspace."""

    def __init__(self, runtime: OriginForgeRuntime, profile: BlockbenchBridgeProfile):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, BlockbenchBridgeProfile):
            raise TypeError("profile must be a BlockbenchBridgeProfile")
        self.runtime = runtime
        self.profile = profile
        self.workspace_root = runtime.state_dir / "model3d-workspaces"

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

    def _workspace(self, request: BlockbenchBridgeRequest) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.workspace_root.is_symlink():
            raise BlockbenchBridgeIntegrityError(
                "3D workspace root may not be a symlink"
            )
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        try:
            self.workspace_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise BlockbenchBridgeIntegrityError(
                "3D workspace root escapes protected project state"
            ) from exc
        workspace = self.workspace_root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise BlockbenchBridgeIntegrityError(
                f"3D workspace already exists: {request.workspace_id}"
            )
        workspace.mkdir()
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir()
        return workspace

    @staticmethod
    def _validate_root(workspace: Path, name: str) -> Path:
        root = workspace / name
        if root.is_symlink():
            raise BlockbenchBridgeIntegrityError(
                f"Blockbench {name} workspace root may not be a symlink"
            )
        try:
            workspace_resolved = workspace.resolve(strict=True)
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BlockbenchBridgeIntegrityError(
                f"Blockbench {name} workspace root is unavailable"
            ) from exc
        if not resolved.is_dir() or resolved.parent != workspace_resolved:
            raise BlockbenchBridgeIntegrityError(
                f"Blockbench {name} workspace root escaped containment"
            )
        return resolved

    @classmethod
    def _contained_output(cls, workspace: Path, relative_path: str) -> Path:
        exports = cls._validate_root(workspace, "exports")
        relative = Path(relative_path)
        if not relative.parts or relative.parts[0] != "exports":
            raise BlockbenchBridgeIntegrityError("declared output is outside exports/")
        current = workspace
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise BlockbenchBridgeIntegrityError(
                    "declared output contains a symlink component"
                )
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(exports)
        except (OSError, RuntimeError, ValueError) as exc:
            raise BlockbenchBridgeIntegrityError(
                "declared output escaped the 3D workspace"
            ) from exc
        if not resolved.is_file():
            raise BlockbenchBridgeIntegrityError(
                "declared Blockbench output must be a regular file"
            )
        return resolved

    def _environment(self, workspace: Path) -> dict[str, str]:
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
                "ORIGIN_FORGE_BLOCKBENCH_WORKSPACE": str(workspace),
            }
        )
        return env

    def _run(
        self,
        command: list[str],
        *,
        workspace: Path,
        timeout_seconds: int,
        stdout_limit: int,
        stderr_limit: int,
    ) -> tuple[int, bytes, bytes, bool, bool]:
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=self._environment(workspace),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as exc:
            raise BlockbenchBridgeUnavailable(
                "failed to launch configured Blockbench bridge executable"
            ) from exc
        assert process.stdout is not None and process.stderr is not None
        out_sink: dict[str, object] = {}
        err_sink: dict[str, object] = {}
        out_thread = threading.Thread(
            target=self._drain,
            args=(process.stdout, stdout_limit, out_sink),
            daemon=True,
        )
        err_thread = threading.Thread(
            target=self._drain,
            args=(process.stderr, stderr_limit, err_sink),
            daemon=True,
        )
        out_thread.start()
        err_thread.start()
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            out_thread.join(timeout=2)
            err_thread.join(timeout=2)
            raise BlockbenchBridgeUnavailable(
                "Blockbench bridge operation exceeded timeout"
            ) from exc
        out_thread.join(timeout=2)
        err_thread.join(timeout=2)
        if out_thread.is_alive() or err_thread.is_alive():
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge output streams did not terminate cleanly"
            )
        stdout = out_sink.get("data", b"")
        stderr = err_sink.get("data", b"")
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            raise BlockbenchBridgeIntegrityError("Blockbench bridge log capture failed")
        return (
            exit_code,
            stdout,
            stderr,
            bool(out_sink.get("truncated", False)),
            bool(err_sink.get("truncated", False)),
        )

    def _validate_runtime(self, workspace: Path) -> None:
        runtime = self._validate_root(workspace, "runtime")
        total = 0
        for path in runtime.rglob("*"):
            if path.is_symlink():
                raise BlockbenchBridgeIntegrityError(
                    "Blockbench runtime scratch contains a symlink"
                )
            if path.is_file():
                total += path.stat().st_size
                if total > self.profile.max_runtime_bytes:
                    raise BlockbenchBridgeIntegrityError(
                        "Blockbench runtime scratch exceeds byte limit"
                    )

    def execute(self, request: BlockbenchBridgeRequest) -> BlockbenchBridgeExecution:
        if not isinstance(request, BlockbenchBridgeRequest):
            raise TypeError("request must be a BlockbenchBridgeRequest")
        if request.bridge_fingerprint != self.profile.bridge_fingerprint:
            raise BlockbenchBridgeIntegrityError(
                "request bridge fingerprint does not match configured profile"
            )
        if request.expected_blockbench_version != self.profile.expected_blockbench_version:
            raise BlockbenchBridgeIntegrityError(
                "request Blockbench version does not match configured profile"
            )
        executable = self.profile.verify_executable()
        workspace = self._workspace(request)
        request_path = workspace / "request" / "request.json"
        result_path = workspace / "runtime" / "result.json"
        request_payload = request.to_dict()
        request_payload["content_hash"] = request.content_hash
        serialized = json.dumps(
            request_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        with request_path.open("xb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        command = [
            str(executable),
            "--request",
            str(request_path.resolve(strict=True)),
            "--result",
            str(result_path),
        ]
        exit_code, stdout, stderr, stdout_truncated, stderr_truncated = self._run(
            command,
            workspace=workspace,
            timeout_seconds=request.budget.timeout_seconds,
            stdout_limit=request.budget.max_stdout_bytes,
            stderr_limit=request.budget.max_stderr_bytes,
        )
        if exit_code != 0:
            raise BlockbenchBridgeUnavailable(
                f"Blockbench bridge exited with code {exit_code}"
            )
        for name in ("request", "inputs", "exports", "runtime"):
            self._validate_root(workspace, name)
        if result_path.is_symlink() or not result_path.is_file():
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge did not produce a regular result file"
            )
        if result_path.stat().st_size > self.profile.max_result_bytes:
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge result exceeds byte limit"
            )
        try:
            raw_result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge result is not valid UTF-8 JSON"
            ) from exc
        try:
            result = BlockbenchBridgeResult.from_dict(raw_result)
            result.bind_to_request(request)
        except (TypeError, ValueError) as exc:
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge result failed strict binding"
            ) from exc

        declared_paths = {output.relative_path for output in result.outputs}
        actual_export_paths = {
            path.relative_to(workspace).as_posix()
            for path in (workspace / "exports").rglob("*")
            if path.is_file()
        }
        if declared_paths != actual_export_paths:
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge declared outputs do not match export files"
            )
        for output in result.outputs:
            path = self._contained_output(workspace, output.relative_path)
            digest, byte_count = _sha256_file(
                path,
                request.budget.max_output_bytes,
                "Blockbench output",
            )
            if digest != output.content_hash or byte_count != output.byte_count:
                raise BlockbenchBridgeIntegrityError(
                    "Blockbench output does not match declared hash/size"
                )
            if output.output_type == BlockbenchOutputType.GLB:
                try:
                    inspect_glb(path.read_bytes())
                except (OSError, GlbError) as exc:
                    raise BlockbenchBridgeIntegrityError(
                        "Blockbench GLB output failed independent validation"
                    ) from exc
        if result.status == BlockbenchResultStatus.SUCCEEDED:
            if request.output_relative_path not in declared_paths:
                raise BlockbenchBridgeIntegrityError(
                    "successful bridge result omitted declared request output"
                )
        self._validate_runtime(workspace)
        allowed_top_level = {"request", "inputs", "exports", "runtime"}
        unexpected = {
            path.name for path in workspace.iterdir() if path.name not in allowed_top_level
        }
        if unexpected:
            raise BlockbenchBridgeIntegrityError(
                "Blockbench bridge produced undeclared workspace entries"
            )
        return BlockbenchBridgeExecution(
            request=request,
            result=result,
            workspace_path=workspace,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
