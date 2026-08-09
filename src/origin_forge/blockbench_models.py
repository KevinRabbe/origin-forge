from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from .ids import IdKind, new_id, validate_id
from .path_policy import portable_relative_path


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_TEXT = 1024
_MAX_COORDINATE = 1_000_000.0
_MAX_UV = 65_536.0
_MAX_BONES = 256
_MAX_CUBES = 4096
_MAX_TEXTURES = 64
_MAX_ANIMATIONS = 256
_MAX_KEYFRAMES = 8192
_MAX_TEXTURE_BYTES = 256 * 1024 * 1024


class BlockbenchModelError(ValueError):
    pass


class BlockbenchOperation(StrEnum):
    CREATE_PROJECT = "CREATE_PROJECT"
    EXPORT_GLB = "EXPORT_GLB"
    SAVE_PROJECT = "SAVE_PROJECT"


class AnimationLoopMode(StrEnum):
    ONCE = "ONCE"
    HOLD = "HOLD"
    LOOP = "LOOP"


class TransformChannel(StrEnum):
    POSITION = "POSITION"
    ROTATION = "ROTATION"
    SCALE = "SCALE"


class KeyframeInterpolation(StrEnum):
    LINEAR = "LINEAR"
    STEP = "STEP"


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
        raise BlockbenchModelError("value is not canonical JSON serializable") from exc


def canonical_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise BlockbenchModelError(f"{field} must be a lowercase sha256: digest")
    return value


def _text(value: str, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BlockbenchModelError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise BlockbenchModelError(f"{field} exceeds character limit")
    if "\x00" in value:
        raise BlockbenchModelError(f"{field} may not contain NUL")
    return value


def _token(value: str, field: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise BlockbenchModelError(f"{field} must be a bounded portable token")
    return value


def _number(
    value: float | int,
    field: str,
    *,
    minimum: float = -_MAX_COORDINATE,
    maximum: float = _MAX_COORDINATE,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BlockbenchModelError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise BlockbenchModelError(
            f"{field} must be finite and between {minimum} and {maximum}"
        )
    return result


def workspace_relative_path(value: str, field: str) -> str:
    _text(value, field, maximum=4096)
    try:
        path = portable_relative_path(value)
    except ValueError as exc:
        raise BlockbenchModelError(f"invalid {field}") from exc
    normalized = PurePosixPath(path.as_posix())
    if not normalized.parts:
        raise BlockbenchModelError(f"{field} may not be empty")
    return normalized.as_posix()


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _number(self.x, "Vec3.x"))
        object.__setattr__(self, "y", _number(self.y, "Vec3.y"))
        object.__setattr__(self, "z", _number(self.z, "Vec3.z"))

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]


@dataclass(frozen=True)
class BoneSpec:
    bone_id: str
    name: str
    pivot: Vec3
    rotation: Vec3 = Vec3(0.0, 0.0, 0.0)
    parent_bone_id: str | None = None

    def __post_init__(self) -> None:
        _token(self.bone_id, "bone_id")
        _text(self.name, "bone name", maximum=256)
        if not isinstance(self.pivot, Vec3) or not isinstance(self.rotation, Vec3):
            raise BlockbenchModelError("bone pivot and rotation must be Vec3 values")
        for value, field in zip(
            self.rotation.to_list(),
            ("rotation.x", "rotation.y", "rotation.z"),
            strict=True,
        ):
            _number(value, field, minimum=-360.0, maximum=360.0)
        if self.parent_bone_id is not None:
            _token(self.parent_bone_id, "parent_bone_id")
            if self.parent_bone_id == self.bone_id:
                raise BlockbenchModelError("bone may not parent itself")

    def to_dict(self) -> dict[str, object]:
        return {
            "bone_id": self.bone_id,
            "name": self.name,
            "pivot": self.pivot.to_list(),
            "rotation": self.rotation.to_list(),
            "parent_bone_id": self.parent_bone_id,
        }


@dataclass(frozen=True)
class CuboidSpec:
    element_id: str
    name: str
    from_point: Vec3
    to_point: Vec3
    origin: Vec3
    rotation: Vec3 = Vec3(0.0, 0.0, 0.0)
    parent_bone_id: str | None = None
    inflate: float = 0.0
    uv_offset: tuple[float, float] = (0.0, 0.0)
    mirror_uv: bool = False
    visible: bool = True

    def __post_init__(self) -> None:
        _token(self.element_id, "element_id")
        _text(self.name, "cuboid name", maximum=256)
        for value, field in (
            (self.from_point, "from_point"),
            (self.to_point, "to_point"),
            (self.origin, "origin"),
            (self.rotation, "rotation"),
        ):
            if not isinstance(value, Vec3):
                raise BlockbenchModelError(f"{field} must be a Vec3")
        if all(
            a == b
            for a, b in zip(
                self.from_point.to_list(), self.to_point.to_list(), strict=True
            )
        ):
            raise BlockbenchModelError("cuboid must have non-zero extent")
        for start, end, axis in zip(
            self.from_point.to_list(),
            self.to_point.to_list(),
            ("x", "y", "z"),
            strict=True,
        ):
            if end < start:
                raise BlockbenchModelError(f"cuboid to_point.{axis} must be >= from_point.{axis}")
        for value, field in zip(
            self.rotation.to_list(),
            ("rotation.x", "rotation.y", "rotation.z"),
            strict=True,
        ):
            _number(value, field, minimum=-360.0, maximum=360.0)
        if self.parent_bone_id is not None:
            _token(self.parent_bone_id, "parent_bone_id")
        object.__setattr__(
            self,
            "inflate",
            _number(self.inflate, "inflate", minimum=-1024.0, maximum=1024.0),
        )
        if (
            not isinstance(self.uv_offset, tuple)
            or len(self.uv_offset) != 2
        ):
            raise BlockbenchModelError("uv_offset must be a two-number tuple")
        normalized_uv = tuple(
            _number(value, f"uv_offset[{index}]", minimum=-_MAX_UV, maximum=_MAX_UV)
            for index, value in enumerate(self.uv_offset)
        )
        object.__setattr__(self, "uv_offset", normalized_uv)
        if not isinstance(self.mirror_uv, bool) or not isinstance(self.visible, bool):
            raise BlockbenchModelError("mirror_uv and visible must be booleans")

    def to_dict(self) -> dict[str, object]:
        return {
            "element_id": self.element_id,
            "name": self.name,
            "from": self.from_point.to_list(),
            "to": self.to_point.to_list(),
            "origin": self.origin.to_list(),
            "rotation": self.rotation.to_list(),
            "parent_bone_id": self.parent_bone_id,
            "inflate": self.inflate,
            "uv_offset": list(self.uv_offset),
            "mirror_uv": self.mirror_uv,
            "visible": self.visible,
        }


@dataclass(frozen=True)
class TextureRef:
    texture_id: str
    relative_path: str
    content_hash: str
    byte_count: int
    width: int
    height: int

    def __post_init__(self) -> None:
        _token(self.texture_id, "texture_id")
        relative = workspace_relative_path(self.relative_path, "texture relative_path")
        if not relative.startswith("inputs/textures/") or not relative.lower().endswith(".png"):
            raise BlockbenchModelError(
                "texture relative_path must be a PNG under inputs/textures/"
            )
        object.__setattr__(self, "relative_path", relative)
        validate_sha256(self.content_hash, "texture content_hash")
        if (
            not isinstance(self.byte_count, int)
            or isinstance(self.byte_count, bool)
            or not 1 <= self.byte_count <= _MAX_TEXTURE_BYTES
        ):
            raise BlockbenchModelError("texture byte_count is outside the allowed range")
        for value, field in ((self.width, "width"), (self.height, "height")):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= 16_384
            ):
                raise BlockbenchModelError(f"texture {field} must be between 1 and 16384")

    def to_dict(self) -> dict[str, object]:
        return {
            "texture_id": self.texture_id,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class KeyframeSpec:
    bone_id: str
    time_seconds: float
    channel: TransformChannel
    value: Vec3
    interpolation: KeyframeInterpolation = KeyframeInterpolation.LINEAR

    def __post_init__(self) -> None:
        _token(self.bone_id, "keyframe bone_id")
        object.__setattr__(
            self,
            "time_seconds",
            _number(self.time_seconds, "keyframe time_seconds", minimum=0.0, maximum=3600.0),
        )
        if not isinstance(self.channel, TransformChannel):
            raise BlockbenchModelError("keyframe channel must be a TransformChannel")
        if not isinstance(self.value, Vec3):
            raise BlockbenchModelError("keyframe value must be a Vec3")
        if not isinstance(self.interpolation, KeyframeInterpolation):
            raise BlockbenchModelError(
                "keyframe interpolation must be a KeyframeInterpolation"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "bone_id": self.bone_id,
            "time_seconds": self.time_seconds,
            "channel": self.channel.value,
            "value": self.value.to_list(),
            "interpolation": self.interpolation.value,
        }


@dataclass(frozen=True)
class AnimationSpec:
    animation_id: str
    name: str
    length_seconds: float
    loop_mode: AnimationLoopMode
    keyframes: tuple[KeyframeSpec, ...]

    def __post_init__(self) -> None:
        _token(self.animation_id, "animation_id")
        _text(self.name, "animation name", maximum=256)
        object.__setattr__(
            self,
            "length_seconds",
            _number(
                self.length_seconds,
                "animation length_seconds",
                minimum=0.001,
                maximum=3600.0,
            ),
        )
        if not isinstance(self.loop_mode, AnimationLoopMode):
            raise BlockbenchModelError("animation loop_mode must be an AnimationLoopMode")
        frames = tuple(self.keyframes)
        if len(frames) > _MAX_KEYFRAMES:
            raise BlockbenchModelError("animation exceeds keyframe limit")
        if any(not isinstance(frame, KeyframeSpec) for frame in frames):
            raise BlockbenchModelError("animation keyframes must contain KeyframeSpec values")
        if any(frame.time_seconds > self.length_seconds for frame in frames):
            raise BlockbenchModelError("keyframe time exceeds animation length")
        semantic_keys = [
            (frame.bone_id, frame.time_seconds, frame.channel.value) for frame in frames
        ]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise BlockbenchModelError(
                "animation may not contain duplicate bone/time/channel keyframes"
            )
        object.__setattr__(
            self,
            "keyframes",
            tuple(
                sorted(
                    frames,
                    key=lambda frame: (
                        frame.time_seconds,
                        frame.bone_id,
                        frame.channel.value,
                    ),
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "animation_id": self.animation_id,
            "name": self.name,
            "length_seconds": self.length_seconds,
            "loop_mode": self.loop_mode.value,
            "keyframes": [frame.to_dict() for frame in self.keyframes],
        }


@dataclass(frozen=True)
class BlockbenchProjectSpec:
    project_name: str
    bones: tuple[BoneSpec, ...]
    cuboids: tuple[CuboidSpec, ...]
    textures: tuple[TextureRef, ...] = ()
    animations: tuple[AnimationSpec, ...] = ()

    def __post_init__(self) -> None:
        _text(self.project_name, "project_name", maximum=256)
        bones = tuple(self.bones)
        cuboids = tuple(self.cuboids)
        textures = tuple(self.textures)
        animations = tuple(self.animations)
        for values, expected, maximum, field in (
            (bones, BoneSpec, _MAX_BONES, "bones"),
            (cuboids, CuboidSpec, _MAX_CUBES, "cuboids"),
            (textures, TextureRef, _MAX_TEXTURES, "textures"),
            (animations, AnimationSpec, _MAX_ANIMATIONS, "animations"),
        ):
            if len(values) > maximum:
                raise BlockbenchModelError(f"project exceeds {field} limit")
            if any(not isinstance(value, expected) for value in values):
                raise BlockbenchModelError(f"project {field} contain invalid values")
        if not cuboids:
            raise BlockbenchModelError("project must contain at least one cuboid")

        bone_ids = [bone.bone_id for bone in bones]
        cube_ids = [cube.element_id for cube in cuboids]
        texture_ids = [texture.texture_id for texture in textures]
        animation_ids = [animation.animation_id for animation in animations]
        for identifiers, field in (
            (bone_ids, "bone"),
            (cube_ids, "cuboid"),
            (texture_ids, "texture"),
            (animation_ids, "animation"),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise BlockbenchModelError(f"duplicate {field} IDs are not allowed")

        known_bones = set(bone_ids)
        for bone in bones:
            if bone.parent_bone_id is not None and bone.parent_bone_id not in known_bones:
                raise BlockbenchModelError("bone parent must reference a project bone")
        for cuboid in cuboids:
            if cuboid.parent_bone_id is not None and cuboid.parent_bone_id not in known_bones:
                raise BlockbenchModelError("cuboid parent must reference a project bone")
        for animation in animations:
            if any(frame.bone_id not in known_bones for frame in animation.keyframes):
                raise BlockbenchModelError(
                    "animation keyframes must reference project bones"
                )

        parent_by_bone = {bone.bone_id: bone.parent_bone_id for bone in bones}
        for bone_id in bone_ids:
            seen: set[str] = set()
            current: str | None = bone_id
            while current is not None:
                if current in seen:
                    raise BlockbenchModelError("bone hierarchy contains a cycle")
                seen.add(current)
                current = parent_by_bone[current]

        object.__setattr__(self, "bones", tuple(sorted(bones, key=lambda item: item.bone_id)))
        object.__setattr__(self, "cuboids", tuple(sorted(cuboids, key=lambda item: item.element_id)))
        object.__setattr__(self, "textures", tuple(sorted(textures, key=lambda item: item.texture_id)))
        object.__setattr__(
            self,
            "animations",
            tuple(sorted(animations, key=lambda item: item.animation_id)),
        )

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "project_name": self.project_name,
            "bones": [bone.to_dict() for bone in self.bones],
            "cuboids": [cube.to_dict() for cube in self.cuboids],
            "textures": [texture.to_dict() for texture in self.textures],
            "animations": [animation.to_dict() for animation in self.animations],
        }


@dataclass(frozen=True)
class BlockbenchBridgeBudget:
    timeout_seconds: int = 60
    max_output_bytes: int = 256 * 1024 * 1024
    max_stdout_bytes: int = 64 * 1024
    max_stderr_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for value, field, maximum in (
            (self.timeout_seconds, "timeout_seconds", 3600),
            (self.max_output_bytes, "max_output_bytes", 2 * 1024 * 1024 * 1024),
            (self.max_stdout_bytes, "max_stdout_bytes", 16 * 1024 * 1024),
            (self.max_stderr_bytes, "max_stderr_bytes", 16 * 1024 * 1024),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= maximum
            ):
                raise BlockbenchModelError(f"{field} is outside the allowed range")

    def to_dict(self) -> dict[str, int]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
        }


@dataclass(frozen=True)
class BlockbenchBridgeRequest:
    operation_id: str
    workspace_id: str
    operation: BlockbenchOperation
    project: BlockbenchProjectSpec
    output_relative_path: str
    bridge_fingerprint: str
    expected_blockbench_version: str
    budget: BlockbenchBridgeBudget = BlockbenchBridgeBudget()

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.BLOCKBENCH_OPERATION):
            raise BlockbenchModelError("operation_id must be a BBOP ID")
        if not validate_id(self.workspace_id, IdKind.MODEL3D_WORKSPACE):
            raise BlockbenchModelError("workspace_id must be a MODEL3D ID")
        if not isinstance(self.operation, BlockbenchOperation):
            raise BlockbenchModelError("operation must be a BlockbenchOperation")
        if not isinstance(self.project, BlockbenchProjectSpec):
            raise BlockbenchModelError("project must be a BlockbenchProjectSpec")
        output = workspace_relative_path(
            self.output_relative_path, "output_relative_path"
        )
        expected_suffix = {
            BlockbenchOperation.CREATE_PROJECT: ".bbmodel",
            BlockbenchOperation.SAVE_PROJECT: ".bbmodel",
            BlockbenchOperation.EXPORT_GLB: ".glb",
        }[self.operation]
        if not output.startswith("exports/") or not output.lower().endswith(expected_suffix):
            raise BlockbenchModelError(
                f"output_relative_path must be under exports/ and end with {expected_suffix}"
            )
        object.__setattr__(self, "output_relative_path", output)
        validate_sha256(self.bridge_fingerprint, "bridge_fingerprint")
        _text(
            self.expected_blockbench_version,
            "expected_blockbench_version",
            maximum=128,
        )
        if not isinstance(self.budget, BlockbenchBridgeBudget):
            raise BlockbenchModelError("budget must be a BlockbenchBridgeBudget")

    @classmethod
    def create(
        cls,
        *,
        operation: BlockbenchOperation,
        project: BlockbenchProjectSpec,
        output_relative_path: str,
        bridge_fingerprint: str,
        expected_blockbench_version: str,
        budget: BlockbenchBridgeBudget | None = None,
    ) -> "BlockbenchBridgeRequest":
        return cls(
            operation_id=new_id(IdKind.BLOCKBENCH_OPERATION),
            workspace_id=new_id(IdKind.MODEL3D_WORKSPACE),
            operation=operation,
            project=project,
            output_relative_path=output_relative_path,
            bridge_fingerprint=bridge_fingerprint,
            expected_blockbench_version=expected_blockbench_version,
            budget=budget or BlockbenchBridgeBudget(),
        )

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": 1,
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "operation": self.operation.value,
            "project": self.project.to_dict(),
            "project_hash": self.project.content_hash,
            "output_relative_path": self.output_relative_path,
            "bridge_fingerprint": self.bridge_fingerprint,
            "expected_blockbench_version": self.expected_blockbench_version,
            "budget": self.budget.to_dict(),
        }
