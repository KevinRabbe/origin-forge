from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Iterable

from .ids import IdKind, new_id, validate_id


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,255}$")
_MAX_CAPTURES = 256
_MAX_BASELINES = 128
_MAX_LOG_BYTES = 16 * 1024 * 1024
_MAX_TIMEOUT_SECONDS = 3600


class RuntimeObservationModelError(ValueError):
    pass


class RuntimeCaptureKind(StrEnum):
    SCREENSHOT = "SCREENSHOT"
    VIDEO_FRAME = "VIDEO_FRAME"


class RuntimeObservationStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class RuntimeExitKind(StrEnum):
    EXITED = "EXITED"
    FAILED = "FAILED"
    SIGNALED = "SIGNALED"
    TIMEOUT = "TIMEOUT"


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeObservationModelError(
            "runtime observation value must be finite JSON data"
        ) from exc


def content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise RuntimeObservationModelError(
            f"{label} must be lowercase sha256:<64 hex>"
        )
    return value


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise RuntimeObservationModelError(f"{label} must be a bounded identity token")
    return value


def _relative_path(
    value: str,
    label: str,
    *,
    required_prefix: str | None = None,
    required_suffix: str | None = None,
) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise RuntimeObservationModelError(
            f"{label} must be a non-empty portable forward-slash path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/"):
        raise RuntimeObservationModelError(f"{label} must be workspace-relative")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeObservationModelError(f"{label} contains unsafe path components")
    normalized = path.as_posix()
    if normalized != value:
        raise RuntimeObservationModelError(f"{label} must be canonical")
    if required_prefix is not None and not normalized.startswith(required_prefix):
        raise RuntimeObservationModelError(
            f"{label} must be below {required_prefix.rstrip('/')}"
        )
    if required_suffix is not None and path.suffix.lower() != required_suffix:
        raise RuntimeObservationModelError(
            f"{label} must end in {required_suffix}"
        )
    return normalized


@dataclass(frozen=True)
class VisualBaselineRef:
    baseline_id: str
    content_hash: str
    pixel_hash: str
    width: int
    height: int
    max_changed_pixels: int = 0
    max_channel_delta: int = 0
    max_total_channel_delta: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline_id", _token(self.baseline_id, "baseline_id"))
        validate_sha256(self.content_hash, "baseline content_hash")
        validate_sha256(self.pixel_hash, "baseline pixel_hash")
        if not isinstance(self.width, int) or not 1 <= self.width <= 4096:
            raise RuntimeObservationModelError("baseline width is outside raster bounds")
        if not isinstance(self.height, int) or not 1 <= self.height <= 4096:
            raise RuntimeObservationModelError("baseline height is outside raster bounds")
        if self.width * self.height > 16_777_216:
            raise RuntimeObservationModelError("baseline pixel count exceeds raster bounds")
        if (
            not isinstance(self.max_changed_pixels, int)
            or not 0 <= self.max_changed_pixels <= self.width * self.height
        ):
            raise RuntimeObservationModelError("max_changed_pixels is outside baseline bounds")
        if not isinstance(self.max_channel_delta, int) or not 0 <= self.max_channel_delta <= 255:
            raise RuntimeObservationModelError("max_channel_delta must be from 0 to 255")
        max_total = self.width * self.height * 4 * 255
        if (
            not isinstance(self.max_total_channel_delta, int)
            or not 0 <= self.max_total_channel_delta <= max_total
        ):
            raise RuntimeObservationModelError(
                "max_total_channel_delta is outside baseline bounds"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_id": self.baseline_id,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "width": self.width,
            "height": self.height,
            "max_changed_pixels": self.max_changed_pixels,
            "max_channel_delta": self.max_channel_delta,
            "max_total_channel_delta": self.max_total_channel_delta,
        }


@dataclass(frozen=True)
class RuntimeCaptureSpec:
    capture_id: str
    kind: RuntimeCaptureKind
    relative_path: str
    timestamp_ms: int
    baseline_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_id", _token(self.capture_id, "capture_id"))
        if not isinstance(self.kind, RuntimeCaptureKind):
            raise RuntimeObservationModelError("capture kind must be a RuntimeCaptureKind")
        object.__setattr__(
            self,
            "relative_path",
            _relative_path(
                self.relative_path,
                "capture relative_path",
                required_prefix="captures/",
                required_suffix=".png",
            ),
        )
        if not isinstance(self.timestamp_ms, int) or not 0 <= self.timestamp_ms <= 86_400_000:
            raise RuntimeObservationModelError("capture timestamp_ms is outside allowed range")
        if self.baseline_id is not None:
            object.__setattr__(
                self, "baseline_id", _token(self.baseline_id, "capture baseline_id")
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "capture_id": self.capture_id,
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "timestamp_ms": self.timestamp_ms,
            "baseline_id": self.baseline_id,
        }


@dataclass(frozen=True)
class RuntimeObservationRequest:
    observation_id: str
    workspace_id: str
    backend_id: str
    backend_version: str
    target_id: str
    target_version: str
    executable_hash: str
    timeout_seconds: int
    max_log_bytes: int
    captures: tuple[RuntimeCaptureSpec, ...]
    baselines: tuple[VisualBaselineRef, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.observation_id, IdKind.RUNTIME_OBSERVATION):
            raise RuntimeObservationModelError("observation_id must be an OBS ID")
        if not validate_id(
            self.workspace_id, IdKind.RUNTIME_OBSERVATION_WORKSPACE
        ):
            raise RuntimeObservationModelError("workspace_id must be an OBSWS ID")
        object.__setattr__(self, "backend_id", _token(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _token(self.backend_version, "backend_version")
        )
        object.__setattr__(self, "target_id", _token(self.target_id, "target_id"))
        object.__setattr__(
            self, "target_version", _token(self.target_version, "target_version")
        )
        validate_sha256(self.executable_hash, "executable_hash")
        if not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise RuntimeObservationModelError("timeout_seconds is outside allowed range")
        if not isinstance(self.max_log_bytes, int) or not 1 <= self.max_log_bytes <= _MAX_LOG_BYTES:
            raise RuntimeObservationModelError("max_log_bytes is outside allowed range")

        captures = tuple(self.captures)
        if len(captures) > _MAX_CAPTURES:
            raise RuntimeObservationModelError("capture count exceeds limit")
        if len({value.capture_id for value in captures}) != len(captures):
            raise RuntimeObservationModelError("captures contain duplicate capture_id values")
        if len({value.relative_path for value in captures}) != len(captures):
            raise RuntimeObservationModelError("captures contain duplicate relative paths")
        video_timestamps = [
            value.timestamp_ms
            for value in captures
            if value.kind is RuntimeCaptureKind.VIDEO_FRAME
        ]
        if len(set(video_timestamps)) != len(video_timestamps):
            raise RuntimeObservationModelError(
                "video-frame timestamps must be unique within one observation"
            )
        object.__setattr__(
            self,
            "captures",
            tuple(
                sorted(
                    captures,
                    key=lambda value: (value.timestamp_ms, value.kind.value, value.capture_id),
                )
            ),
        )

        baselines = tuple(self.baselines)
        if len(baselines) > _MAX_BASELINES:
            raise RuntimeObservationModelError("baseline count exceeds limit")
        if len({value.baseline_id for value in baselines}) != len(baselines):
            raise RuntimeObservationModelError("baselines contain duplicate baseline_id values")
        baseline_ids = {value.baseline_id for value in baselines}
        referenced = {
            value.baseline_id for value in captures if value.baseline_id is not None
        }
        if not referenced.issubset(baseline_ids):
            raise RuntimeObservationModelError("capture references unknown visual baseline")
        object.__setattr__(
            self, "baselines", tuple(sorted(baselines, key=lambda value: value.baseline_id))
        )

    @classmethod
    def create(
        cls,
        *,
        backend_id: str,
        backend_version: str,
        target_id: str,
        target_version: str,
        executable_hash: str,
        timeout_seconds: int = 60,
        max_log_bytes: int = 1_048_576,
        captures: Iterable[RuntimeCaptureSpec] = (),
        baselines: Iterable[VisualBaselineRef] = (),
    ) -> "RuntimeObservationRequest":
        return cls(
            observation_id=new_id(IdKind.RUNTIME_OBSERVATION),
            workspace_id=new_id(IdKind.RUNTIME_OBSERVATION_WORKSPACE),
            backend_id=backend_id,
            backend_version=backend_version,
            target_id=target_id,
            target_version=target_version,
            executable_hash=executable_hash,
            timeout_seconds=timeout_seconds,
            max_log_bytes=max_log_bytes,
            captures=tuple(captures),
            baselines=tuple(baselines),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "workspace_id": self.workspace_id,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "target_id": self.target_id,
            "target_version": self.target_version,
            "executable_hash": self.executable_hash,
            "timeout_seconds": self.timeout_seconds,
            "max_log_bytes": self.max_log_bytes,
            "captures": [value.to_dict() for value in self.captures],
            "baselines": [value.to_dict() for value in self.baselines],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class RuntimeLogEvidence:
    relative_path: str
    content_hash: str
    byte_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            _relative_path(self.relative_path, "log path", required_prefix="logs/"),
        )
        validate_sha256(self.content_hash, "log content_hash")
        if not isinstance(self.byte_count, int) or self.byte_count < 0:
            raise RuntimeObservationModelError("log byte_count must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True)
class RuntimeCaptureEvidence:
    capture_id: str
    kind: RuntimeCaptureKind
    relative_path: str
    timestamp_ms: int
    content_hash: str
    pixel_hash: str
    byte_count: int
    width: int
    height: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_id", _token(self.capture_id, "capture_id"))
        if not isinstance(self.kind, RuntimeCaptureKind):
            raise RuntimeObservationModelError("capture evidence kind is invalid")
        object.__setattr__(
            self,
            "relative_path",
            _relative_path(
                self.relative_path,
                "capture evidence path",
                required_prefix="captures/",
                required_suffix=".png",
            ),
        )
        if not isinstance(self.timestamp_ms, int) or self.timestamp_ms < 0:
            raise RuntimeObservationModelError("capture evidence timestamp_ms is invalid")
        validate_sha256(self.content_hash, "capture content_hash")
        validate_sha256(self.pixel_hash, "capture pixel_hash")
        if not isinstance(self.byte_count, int) or self.byte_count <= 0:
            raise RuntimeObservationModelError("capture byte_count must be positive")
        if not isinstance(self.width, int) or not 1 <= self.width <= 4096:
            raise RuntimeObservationModelError("capture width is outside raster bounds")
        if not isinstance(self.height, int) or not 1 <= self.height <= 4096:
            raise RuntimeObservationModelError("capture height is outside raster bounds")

    def to_dict(self) -> dict[str, object]:
        return {
            "capture_id": self.capture_id,
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "timestamp_ms": self.timestamp_ms,
            "content_hash": self.content_hash,
            "pixel_hash": self.pixel_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class RuntimePerformanceEvidence:
    duration_ms: int
    peak_rss_kib: int

    def __post_init__(self) -> None:
        if not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise RuntimeObservationModelError("duration_ms must be non-negative")
        if not isinstance(self.peak_rss_kib, int) or self.peak_rss_kib < 0:
            raise RuntimeObservationModelError("peak_rss_kib must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "duration_ms": self.duration_ms,
            "peak_rss_kib": self.peak_rss_kib,
        }


@dataclass(frozen=True)
class RuntimeObservationResult:
    observation_id: str
    workspace_id: str
    request_hash: str
    status: RuntimeObservationStatus
    backend_id: str
    backend_version: str
    target_id: str
    target_version: str
    executable_hash: str
    exit_kind: RuntimeExitKind
    exit_code: int | None
    stdout: RuntimeLogEvidence
    stderr: RuntimeLogEvidence
    captures: tuple[RuntimeCaptureEvidence, ...]
    performance: RuntimePerformanceEvidence
    detail: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.observation_id, IdKind.RUNTIME_OBSERVATION):
            raise RuntimeObservationModelError("result observation_id must be an OBS ID")
        if not validate_id(
            self.workspace_id, IdKind.RUNTIME_OBSERVATION_WORKSPACE
        ):
            raise RuntimeObservationModelError("result workspace_id must be an OBSWS ID")
        validate_sha256(self.request_hash, "result request_hash")
        if not isinstance(self.status, RuntimeObservationStatus):
            raise RuntimeObservationModelError("status must be a RuntimeObservationStatus")
        object.__setattr__(self, "backend_id", _token(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _token(self.backend_version, "backend_version")
        )
        object.__setattr__(self, "target_id", _token(self.target_id, "target_id"))
        object.__setattr__(
            self, "target_version", _token(self.target_version, "target_version")
        )
        validate_sha256(self.executable_hash, "result executable_hash")
        if not isinstance(self.exit_kind, RuntimeExitKind):
            raise RuntimeObservationModelError("exit_kind must be a RuntimeExitKind")
        if self.exit_kind is RuntimeExitKind.TIMEOUT:
            if self.exit_code is not None:
                raise RuntimeObservationModelError("timeout result may not report exit_code")
        elif not isinstance(self.exit_code, int):
            raise RuntimeObservationModelError("non-timeout result requires integer exit_code")
        captures = tuple(self.captures)
        if len({value.capture_id for value in captures}) != len(captures):
            raise RuntimeObservationModelError("result captures contain duplicate capture IDs")
        object.__setattr__(
            self,
            "captures",
            tuple(
                sorted(
                    captures,
                    key=lambda value: (value.timestamp_ms, value.kind.value, value.capture_id),
                )
            ),
        )
        if self.detail is not None:
            if not isinstance(self.detail, str) or len(self.detail) > 2048 or "\x00" in self.detail:
                raise RuntimeObservationModelError("detail must be bounded text")

    def bind_request(self, request: RuntimeObservationRequest) -> None:
        if not isinstance(request, RuntimeObservationRequest):
            raise TypeError("request must be a RuntimeObservationRequest")
        expected = (
            request.observation_id,
            request.workspace_id,
            request.content_hash,
            request.backend_id,
            request.backend_version,
            request.target_id,
            request.target_version,
            request.executable_hash,
        )
        actual = (
            self.observation_id,
            self.workspace_id,
            self.request_hash,
            self.backend_id,
            self.backend_version,
            self.target_id,
            self.target_version,
            self.executable_hash,
        )
        if actual != expected:
            raise RuntimeObservationModelError("runtime result does not bind exact request identity")
        if self.status is RuntimeObservationStatus.SUCCEEDED:
            specs = {value.capture_id: value for value in request.captures}
            outputs = {value.capture_id: value for value in self.captures}
            unknown = set(outputs) - set(specs)
            if unknown:
                raise RuntimeObservationModelError("runtime result contains undeclared captures")
            missing = set(specs) - set(outputs)
            if self.exit_kind is RuntimeExitKind.EXITED and missing:
                raise RuntimeObservationModelError("runtime result capture set differs from request")
            for capture_id, output in outputs.items():
                spec = specs[capture_id]
                if (
                    output.kind is not spec.kind
                    or output.relative_path != spec.relative_path
                    or output.timestamp_ms != spec.timestamp_ms
                ):
                    raise RuntimeObservationModelError(
                        "runtime result capture metadata differs from request"
                    )
            if self.stdout.relative_path != "logs/stdout.log":
                raise RuntimeObservationModelError("stdout evidence path is not canonical")
            if self.stderr.relative_path != "logs/stderr.log":
                raise RuntimeObservationModelError("stderr evidence path is not canonical")
            if self.stdout.byte_count > request.max_log_bytes or self.stderr.byte_count > request.max_log_bytes:
                raise RuntimeObservationModelError("runtime result exceeds log byte limit")

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "workspace_id": self.workspace_id,
            "request_hash": self.request_hash,
            "status": self.status.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "target_id": self.target_id,
            "target_version": self.target_version,
            "executable_hash": self.executable_hash,
            "exit_kind": self.exit_kind.value,
            "exit_code": self.exit_code,
            "stdout": self.stdout.to_dict(),
            "stderr": self.stderr.to_dict(),
            "captures": [value.to_dict() for value in self.captures],
            "performance": self.performance.to_dict(),
            "detail": self.detail,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
