from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime
from .runtime_observation_models import (
    RuntimeCaptureKind,
    RuntimeCaptureSpec,
    RuntimeObservationModelError,
    RuntimeObservationRequest,
    VisualBaselineRef,
    canonical_bytes,
    validate_sha256,
)


class RuntimeObservationRequestStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredRuntimeObservationRequest:
    request: RuntimeObservationRequest
    path: Path
    byte_count: int


class RuntimeObservationRequestStore:
    """Immutable protected reader for exact runtime-observation requests."""

    _SCHEMA_VERSION = 1
    _MAX_BYTES = 256 * 1024
    _MAX_REQUESTS = 256

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "runtime-observation-requests"

    def _root(self, *, create: bool) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.root.is_symlink():
            raise RuntimeObservationRequestStoreError("request store may not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists():
            return self.root
        try:
            resolved = self.root.resolve(strict=True)
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeObservationRequestStoreError(
                "request store escapes protected project state"
            ) from exc
        if not resolved.is_dir():
            raise RuntimeObservationRequestStoreError("request store root must be a directory")
        return resolved

    @staticmethod
    def _path(root: Path, request_id: str, request_hash: str) -> Path:
        if not validate_id(request_id, IdKind.RUNTIME_OBSERVATION):
            raise RuntimeObservationRequestStoreError("request_id must be an OBS ID")
        validate_sha256(request_hash, "request_hash")
        return root / f"{request_id}--{request_hash.removeprefix('sha256:')}.json"

    @classmethod
    def _parse(cls, value: object) -> RuntimeObservationRequest:
        if not isinstance(value, dict):
            raise RuntimeObservationRequestStoreError("stored runtime request must be an object")
        expected = {
            "schema_version", "observation_id", "workspace_id", "backend_id",
            "backend_version", "target_id", "target_version", "executable_hash",
            "timeout_seconds", "max_log_bytes", "captures", "baselines", "request_hash",
        }
        if set(value) != expected or value.get("schema_version") != cls._SCHEMA_VERSION:
            raise RuntimeObservationRequestStoreError("stored runtime request has unknown or missing fields")
        try:
            captures = tuple(
                RuntimeCaptureSpec(
                    capture_id=item["capture_id"],
                    kind=RuntimeCaptureKind(item["kind"]),
                    relative_path=item["relative_path"],
                    timestamp_ms=item["timestamp_ms"],
                    baseline_id=item.get("baseline_id"),
                )
                for item in value["captures"]
            )
            baselines = tuple(
                VisualBaselineRef(
                    baseline_id=item["baseline_id"],
                    content_hash=item["content_hash"],
                    pixel_hash=item["pixel_hash"],
                    width=item["width"],
                    height=item["height"],
                    max_changed_pixels=item.get("max_changed_pixels", 0),
                    max_channel_delta=item.get("max_channel_delta", 0),
                    max_total_channel_delta=item.get("max_total_channel_delta", 0),
                )
                for item in value["baselines"]
            )
            request = RuntimeObservationRequest(
                observation_id=value["observation_id"],
                workspace_id=value["workspace_id"],
                backend_id=value["backend_id"],
                backend_version=value["backend_version"],
                target_id=value["target_id"],
                target_version=value["target_version"],
                executable_hash=value["executable_hash"],
                timeout_seconds=value["timeout_seconds"],
                max_log_bytes=value["max_log_bytes"],
                captures=captures,
                baselines=baselines,
            )
        except (KeyError, TypeError, ValueError, RuntimeObservationModelError) as exc:
            raise RuntimeObservationRequestStoreError("stored runtime request is invalid") from exc
        if value["request_hash"] != request.content_hash:
            raise RuntimeObservationRequestStoreError("stored runtime request hash mismatch")
        return request

    def put(self, request: RuntimeObservationRequest) -> StoredRuntimeObservationRequest:
        if not isinstance(request, RuntimeObservationRequest):
            raise TypeError("request must be a RuntimeObservationRequest")
        root = self._root(create=True)
        data_value = {"schema_version": self._SCHEMA_VERSION, **request.to_dict(), "request_hash": request.content_hash}
        data = canonical_bytes(data_value)
        if len(data) > self._MAX_BYTES:
            raise RuntimeObservationRequestStoreError("runtime request exceeds byte limit")
        target = self._path(root, request.observation_id, request.content_hash)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                raise RuntimeObservationRequestStoreError("runtime request identity is already bound to different bytes")
            return StoredRuntimeObservationRequest(request, target, len(data))
        if len(tuple(root.glob("*.json"))) >= self._MAX_REQUESTS:
            raise RuntimeObservationRequestStoreError("runtime request store is full")
        temp = root / f".{target.name}.{os.getpid()}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        except (OSError, FileExistsError) as exc:
            raise RuntimeObservationRequestStoreError("failed to persist runtime request") from exc
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return StoredRuntimeObservationRequest(request, target, len(data))

    def get(self, request_id: str, request_hash: str) -> RuntimeObservationRequest:
        root = self._root(create=False)
        target = self._path(root, request_id, request_hash)
        if target.is_symlink() or not target.is_file():
            raise KeyError((request_id, request_hash))
        try:
            if target.stat().st_size > self._MAX_BYTES:
                raise RuntimeObservationRequestStoreError("stored runtime request exceeds byte limit")
            value = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeObservationRequestStoreError("stored runtime request is not valid UTF-8 JSON") from exc
        request = self._parse(value)
        if request.observation_id != request_id or request.content_hash != request_hash:
            raise RuntimeObservationRequestStoreError("runtime request identity does not match protected path")
        return request

    def list(self) -> tuple[StoredRuntimeObservationRequest, ...]:
        root = self._root(create=False)
        if not root.exists():
            return ()
        result: list[StoredRuntimeObservationRequest] = []
        for path in sorted(root.glob("*.json"), key=lambda value: value.name):
            if path.is_symlink() or not path.is_file():
                raise RuntimeObservationRequestStoreError("runtime request store contains unsafe entry")
            value = json.loads(path.read_text(encoding="utf-8"))
            request = self._parse(value)
            expected = self._path(root, request.observation_id, request.content_hash)
            if expected != path:
                raise RuntimeObservationRequestStoreError("runtime request filename/identity mismatch")
            result.append(StoredRuntimeObservationRequest(request, path, path.stat().st_size))
            if len(result) > self._MAX_REQUESTS:
                raise RuntimeObservationRequestStoreError("runtime request store is full")
        return tuple(result)
