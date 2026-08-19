from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from .blockbench_models import (
    AnimationLoopMode,
    AnimationSpec,
    BlockbenchModelError,
    BlockbenchProjectSpec,
    BoneSpec,
    CuboidSpec,
    KeyframeInterpolation,
    KeyframeSpec,
    TextureRef,
    TransformChannel,
    Vec3,
    canonical_bytes,
    canonical_hash,
    validate_sha256,
)
from .ids import IdKind, new_id, validate_id
from .runtime import OriginForgeRuntime


_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_REQUESTS = 256


class Model3DRequestError(RuntimeError):
    pass


class Model3DRequestOperation(StrEnum):
    EXPORT_GLB = "EXPORT_GLB"


def _exact_object(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise Model3DRequestError(f"{label} has unknown or missing fields")
    return value


def _exact_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise Model3DRequestError(f"{label} must be a list")
    return value


def _vec3(value: object, label: str) -> Vec3:
    values = _exact_list(value, label)
    if len(values) != 3:
        raise Model3DRequestError(f"{label} must contain exactly three numbers")
    try:
        return Vec3(values[0], values[1], values[2])
    except (TypeError, ValueError, BlockbenchModelError) as exc:
        raise Model3DRequestError(f"{label} is invalid") from exc


def _bone(value: object) -> BoneSpec:
    item = _exact_object(
        value,
        {"bone_id", "name", "pivot", "rotation", "parent_bone_id"},
        "bone",
    )
    try:
        return BoneSpec(
            bone_id=item["bone_id"],
            name=item["name"],
            pivot=_vec3(item["pivot"], "bone pivot"),
            rotation=_vec3(item["rotation"], "bone rotation"),
            parent_bone_id=item["parent_bone_id"],
        )
    except (TypeError, ValueError, BlockbenchModelError) as exc:
        raise Model3DRequestError("bone is invalid") from exc


def _cuboid(value: object) -> CuboidSpec:
    item = _exact_object(
        value,
        {
            "element_id",
            "name",
            "from",
            "to",
            "origin",
            "rotation",
            "parent_bone_id",
            "inflate",
            "uv_offset",
            "mirror_uv",
            "visible",
        },
        "cuboid",
    )
    uv = _exact_list(item["uv_offset"], "cuboid uv_offset")
    if len(uv) != 2:
        raise Model3DRequestError("cuboid uv_offset must contain exactly two numbers")
    try:
        return CuboidSpec(
            element_id=item["element_id"],
            name=item["name"],
            from_point=_vec3(item["from"], "cuboid from"),
            to_point=_vec3(item["to"], "cuboid to"),
            origin=_vec3(item["origin"], "cuboid origin"),
            rotation=_vec3(item["rotation"], "cuboid rotation"),
            parent_bone_id=item["parent_bone_id"],
            inflate=item["inflate"],
            uv_offset=(uv[0], uv[1]),
            mirror_uv=item["mirror_uv"],
            visible=item["visible"],
        )
    except (TypeError, ValueError, BlockbenchModelError) as exc:
        raise Model3DRequestError("cuboid is invalid") from exc


def _texture(value: object) -> TextureRef:
    item = _exact_object(
        value,
        {
            "texture_id",
            "relative_path",
            "content_hash",
            "byte_count",
            "width",
            "height",
        },
        "texture",
    )
    try:
        return TextureRef(
            texture_id=item["texture_id"],
            relative_path=item["relative_path"],
            content_hash=item["content_hash"],
            byte_count=item["byte_count"],
            width=item["width"],
            height=item["height"],
        )
    except (TypeError, ValueError, BlockbenchModelError) as exc:
        raise Model3DRequestError("texture is invalid") from exc


def _keyframe(value: object) -> KeyframeSpec:
    item = _exact_object(
        value,
        {"bone_id", "time_seconds", "channel", "value", "interpolation"},
        "keyframe",
    )
    try:
        return KeyframeSpec(
            bone_id=item["bone_id"],
            time_seconds=item["time_seconds"],
            channel=TransformChannel(item["channel"]),
            value=_vec3(item["value"], "keyframe value"),
            interpolation=KeyframeInterpolation(item["interpolation"]),
        )
    except (TypeError, ValueError, BlockbenchModelError) as exc:
        raise Model3DRequestError("keyframe is invalid") from exc


def _animation(value: object) -> AnimationSpec:
    item = _exact_object(
        value,
        {"animation_id", "name", "length_seconds", "loop_mode", "keyframes"},
        "animation",
    )
    try:
        return AnimationSpec(
            animation_id=item["animation_id"],
            name=item["name"],
            length_seconds=item["length_seconds"],
            loop_mode=AnimationLoopMode(item["loop_mode"]),
            keyframes=tuple(_keyframe(frame) for frame in _exact_list(item["keyframes"], "keyframes")),
        )
    except (TypeError, ValueError, BlockbenchModelError) as exc:
        raise Model3DRequestError("animation is invalid") from exc


def _project(value: object) -> BlockbenchProjectSpec:
    item = _exact_object(
        value,
        {"schema_version", "project_name", "bones", "cuboids", "textures", "animations"},
        "project",
    )
    if item["schema_version"] != 1:
        raise Model3DRequestError("project has unsupported schema_version")
    try:
        return BlockbenchProjectSpec(
            project_name=item["project_name"],
            bones=tuple(_bone(value) for value in _exact_list(item["bones"], "bones")),
            cuboids=tuple(_cuboid(value) for value in _exact_list(item["cuboids"], "cuboids")),
            textures=tuple(_texture(value) for value in _exact_list(item["textures"], "textures")),
            animations=tuple(
                _animation(value) for value in _exact_list(item["animations"], "animations")
            ),
        )
    except (TypeError, ValueError, BlockbenchModelError) as exc:
        raise Model3DRequestError("project is invalid") from exc


@dataclass(frozen=True)
class Model3DProductionRequest:
    request_id: str
    operation: Model3DRequestOperation
    project: BlockbenchProjectSpec

    def __post_init__(self) -> None:
        if not validate_id(self.request_id, IdKind.MODEL3D_REQUEST):
            raise Model3DRequestError("request_id must be a MODEL3DREQ ID")
        if not isinstance(self.operation, Model3DRequestOperation):
            raise Model3DRequestError("operation must be a Model3DRequestOperation")
        if self.operation is not Model3DRequestOperation.EXPORT_GLB:
            raise Model3DRequestError("only EXPORT_GLB is supported")
        if not isinstance(self.project, BlockbenchProjectSpec):
            raise Model3DRequestError("project must be a canonical BlockbenchProjectSpec")

    @classmethod
    def create(cls, *, project: BlockbenchProjectSpec) -> "Model3DProductionRequest":
        return cls(
            request_id=new_id(IdKind.MODEL3D_REQUEST),
            operation=Model3DRequestOperation.EXPORT_GLB,
            project=project,
        )

    def semantic_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "project": self.project.to_dict(),
            "project_hash": self.project.content_hash,
        }

    @property
    def request_hash(self) -> str:
        return canonical_hash(self.semantic_dict())

    @property
    def content_hash(self) -> str:
        return self.request_hash

    def to_dict(self) -> dict[str, object]:
        value = self.semantic_dict()
        value["request_hash"] = self.request_hash
        return value


@dataclass(frozen=True)
class StoredModel3DRequest:
    request_id: str
    request_hash: str
    path: Path
    byte_count: int


def _reject_duplicate_keys(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Model3DRequestError("stored MODEL3D request contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise Model3DRequestError(f"stored MODEL3D request contains non-finite JSON value {value}")


def _request_from_value(value: object) -> Model3DProductionRequest:
    item = _exact_object(
        value,
        {"schema_version", "request_id", "operation", "project", "project_hash", "request_hash"},
        "stored MODEL3D request",
    )
    if item["schema_version"] != 1:
        raise Model3DRequestError("stored MODEL3D request has unsupported schema_version")
    project = _project(item["project"])
    if item["project_hash"] != project.content_hash:
        raise Model3DRequestError("stored MODEL3D request project hash mismatch")
    try:
        request = Model3DProductionRequest(
            request_id=item["request_id"],
            operation=Model3DRequestOperation(item["operation"]),
            project=project,
        )
    except (TypeError, ValueError, Model3DRequestError) as exc:
        raise Model3DRequestError("stored MODEL3D request identity is invalid") from exc
    if item["request_hash"] != request.request_hash:
        raise Model3DRequestError("stored MODEL3D request hash mismatch")
    return request


class _Model3DRequestRegistry:
    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_request_bytes: int = _MAX_REQUEST_BYTES,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if (
            not isinstance(max_request_bytes, int)
            or isinstance(max_request_bytes, bool)
            or not 1 <= max_request_bytes <= _MAX_REQUEST_BYTES
        ):
            raise ValueError("max_request_bytes is outside allowed range")
        self.runtime = runtime
        self.root = runtime.state_dir / "model3d-requests"
        self.max_request_bytes = max_request_bytes

    def _root(self, *, create: bool) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.root.is_symlink():
            raise Model3DRequestError("MODEL3D request root may not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists():
            return self.root
        try:
            resolved = self.root.resolve(strict=True)
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise Model3DRequestError("MODEL3D request root escapes protected state") from exc
        if not resolved.is_dir():
            raise Model3DRequestError("MODEL3D request root must be a directory")
        return resolved

    @staticmethod
    def _name(request_id: str, request_hash: str) -> str:
        if not validate_id(request_id, IdKind.MODEL3D_REQUEST):
            raise Model3DRequestError("request_id must be a MODEL3DREQ ID")
        try:
            validate_sha256(request_hash, "request_hash")
        except BlockbenchModelError as exc:
            raise Model3DRequestError(str(exc)) from exc
        return f"{request_id}--{request_hash.removeprefix('sha256:')}.json"

    def _read_path(self, path: Path) -> Model3DProductionRequest:
        if path.is_symlink():
            raise Model3DRequestError("MODEL3D request entry may not be a symlink")
        if not path.is_file():
            raise KeyError(path.name)
        size = path.stat().st_size
        if not 1 <= size <= self.max_request_bytes:
            raise Model3DRequestError("stored MODEL3D request exceeds byte limit")
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            value = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except Model3DRequestError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Model3DRequestError("stored MODEL3D request is not valid UTF-8 JSON") from exc
        try:
            if canonical_bytes(value) != raw:
                raise Model3DRequestError("stored MODEL3D request is not canonical JSON")
        except BlockbenchModelError as exc:
            raise Model3DRequestError("stored MODEL3D request is not canonical JSON") from exc
        return _request_from_value(value)


class Model3DRequestReader(_Model3DRequestRegistry):
    """Exact, non-creating protected reader for semantic 3D request evidence."""

    def get(self, request_id: str, request_hash: str) -> Model3DProductionRequest:
        path = self._root(create=False) / self._name(request_id, request_hash)
        request = self._read_path(path)
        if request.request_id != request_id or request.request_hash != request_hash:
            raise Model3DRequestError("stored MODEL3D request identity mismatch")
        return request


class Model3DRequestStore(_Model3DRequestRegistry):
    """Create-only protected registry for semantic 3D production requests."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_request_bytes: int = _MAX_REQUEST_BYTES,
        max_requests: int = _MAX_REQUESTS,
    ):
        super().__init__(runtime, max_request_bytes=max_request_bytes)
        if (
            not isinstance(max_requests, int)
            or isinstance(max_requests, bool)
            or not 1 <= max_requests <= _MAX_REQUESTS
        ):
            raise ValueError("max_requests is outside allowed range")
        self.max_requests = max_requests

    def _catalog(self) -> tuple[Path, ...]:
        root = self._root(create=False)
        if not root.exists():
            return ()
        result: list[Path] = []
        for path in root.iterdir():
            if path.is_symlink():
                raise Model3DRequestError("MODEL3D request registry contains a symlink")
            if not path.is_file() or path.suffix != ".json":
                raise Model3DRequestError("MODEL3D request registry contains an undeclared entry")
            size = path.stat().st_size
            if not 1 <= size <= self.max_request_bytes:
                raise Model3DRequestError("stored MODEL3D request exceeds byte limit")
            result.append(path)
            if len(result) > self.max_requests:
                raise Model3DRequestError("MODEL3D request registry exceeds item limit")
        return tuple(sorted(result, key=lambda item: item.name))

    def put(self, request: Model3DProductionRequest) -> StoredModel3DRequest:
        if not isinstance(request, Model3DProductionRequest):
            raise TypeError("request must be a Model3DProductionRequest")
        root = self._root(create=True)
        catalog = self._catalog()
        try:
            data = canonical_bytes(request.to_dict())
        except BlockbenchModelError as exc:
            raise Model3DRequestError("MODEL3D request is not canonical JSON") from exc
        if len(data) > self.max_request_bytes:
            raise Model3DRequestError("MODEL3D request exceeds byte limit")
        target = root / self._name(request.request_id, request.request_hash)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                raise Model3DRequestError("MODEL3D request content-addressed target is unsafe or drifted")
            return StoredModel3DRequest(
                request.request_id,
                request.request_hash,
                target,
                len(data),
            )
        if len(catalog) >= self.max_requests:
            raise Model3DRequestError("MODEL3D request registry is full")
        temp = root / f".{target.name}.{os.getpid()}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, target)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                    raise Model3DRequestError("competing MODEL3D request publication drifted")
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        return StoredModel3DRequest(
            request.request_id,
            request.request_hash,
            target,
            len(data),
        )
