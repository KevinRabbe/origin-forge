from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .path_policy import portable_relative_path


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_DIMENSION = 4096
_MAX_PIXELS = 16_777_216
_MAX_LAYERS = 128
_MAX_FRAMES = 1024
_MAX_ANIMATIONS = 256
_MAX_PALETTE = 256
_MAX_TEXT = 1024
_MAX_RGBA_BYTES = _MAX_PIXELS * 4


class PixeloramaModelError(ValueError):
    pass


class BridgeOperation(StrEnum):
    CREATE_SPRITE_PROJECT = "CREATE_SPRITE_PROJECT"
    IMPORT_LAYER_PNG = "IMPORT_LAYER_PNG"
    SET_FRAME_DURATION = "SET_FRAME_DURATION"
    SET_ANIMATION = "SET_ANIMATION"
    EXPORT_FRAME_PNG = "EXPORT_FRAME_PNG"
    EXPORT_SPRITESHEET = "EXPORT_SPRITESHEET"
    SAVE_PROJECT = "SAVE_PROJECT"


class BridgeResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class BridgeOutputType(StrEnum):
    PIXELORAMA_PROJECT = "PIXELORAMA_PROJECT"
    PNG = "PNG"
    SPRITESHEET = "SPRITESHEET"


class AnimationLoopMode(StrEnum):
    ONCE = "ONCE"
    LOOP = "LOOP"
    PING_PONG = "PING_PONG"


class LayerBlendMode(StrEnum):
    NORMAL = "NORMAL"


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
        raise PixeloramaModelError("value is not canonical JSON serializable") from exc


def canonical_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PixeloramaModelError(f"{field} must be a lowercase sha256: digest")
    return value


def _bounded_text(
    value: str,
    field: str,
    *,
    maximum: int = _MAX_TEXT,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise PixeloramaModelError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise PixeloramaModelError(f"{field} must be non-empty")
    if len(value) > maximum:
        raise PixeloramaModelError(
            f"{field} exceeds character limit ({len(value)} > {maximum})"
        )
    if "\x00" in value:
        raise PixeloramaModelError(f"{field} may not contain NUL")
    return value


def _token(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID_TOKEN_RE.fullmatch(value):
        raise PixeloramaModelError(f"{field} must be a bounded portable token")
    return value


def bridge_relative_path(value: str, field: str) -> str:
    _bounded_text(value, field, maximum=4096)
    try:
        path = portable_relative_path(value)
    except ValueError as exc:
        raise PixeloramaModelError(f"invalid {field}") from exc
    normalized = PurePosixPath(path.as_posix())
    if not normalized.parts:
        raise PixeloramaModelError(f"{field} may not be empty")
    return normalized.as_posix()


@dataclass(frozen=True)
class Rgba8:
    r: int
    g: int
    b: int
    a: int = 255

    def __post_init__(self) -> None:
        for value, name in ((self.r, "r"), (self.g, "g"), (self.b, "b"), (self.a, "a")):
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 255:
                raise PixeloramaModelError(f"RGBA {name} must be an integer from 0 to 255")

    def to_dict(self) -> dict[str, int]:
        return {"r": self.r, "g": self.g, "b": self.b, "a": self.a}


@dataclass(frozen=True)
class PixelPlane:
    width: int
    height: int
    rgba_bytes: bytes

    def __post_init__(self) -> None:
        for value, name in ((self.width, "width"), (self.height, "height")):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > _MAX_DIMENSION
            ):
                raise PixeloramaModelError(
                    f"PixelPlane {name} must be between 1 and {_MAX_DIMENSION}"
                )
        pixels = self.width * self.height
        if pixels > _MAX_PIXELS:
            raise PixeloramaModelError(
                f"PixelPlane exceeds pixel limit ({pixels} > {_MAX_PIXELS})"
            )
        if not isinstance(self.rgba_bytes, bytes):
            raise PixeloramaModelError("PixelPlane rgba_bytes must be bytes")
        expected = pixels * 4
        if len(self.rgba_bytes) != expected:
            raise PixeloramaModelError(
                f"PixelPlane RGBA byte count mismatch ({len(self.rgba_bytes)} != {expected})"
            )
        if len(self.rgba_bytes) > _MAX_RGBA_BYTES:
            raise PixeloramaModelError("PixelPlane exceeds RGBA byte limit")

    @property
    def rgba_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.rgba_bytes).hexdigest()

    def to_dict(self, *, include_bytes: bool = False) -> dict[str, object]:
        value: dict[str, object] = {
            "width": self.width,
            "height": self.height,
            "rgba_hash": self.rgba_hash,
            "byte_count": len(self.rgba_bytes),
        }
        if include_bytes:
            value["rgba_b64"] = base64.b64encode(self.rgba_bytes).decode("ascii")
        return value


@dataclass(frozen=True)
class RasterLayerSpec:
    layer_id: str
    name: str
    visible: bool = True
    opacity: int = 255
    blend_mode: LayerBlendMode = LayerBlendMode.NORMAL

    def __post_init__(self) -> None:
        _token(self.layer_id, "layer_id")
        _bounded_text(self.name, "layer name", maximum=256)
        if not isinstance(self.visible, bool):
            raise PixeloramaModelError("layer visible must be boolean")
        if (
            not isinstance(self.opacity, int)
            or isinstance(self.opacity, bool)
            or not 0 <= self.opacity <= 255
        ):
            raise PixeloramaModelError("layer opacity must be an integer from 0 to 255")
        if not isinstance(self.blend_mode, LayerBlendMode):
            raise PixeloramaModelError("layer blend_mode must be a LayerBlendMode")

    def to_dict(self) -> dict[str, object]:
        return {
            "layer_id": self.layer_id,
            "name": self.name,
            "visible": self.visible,
            "opacity": self.opacity,
            "blend_mode": self.blend_mode.value,
        }


@dataclass(frozen=True)
class FrameSpec:
    frame_id: str
    duration_ms: int = 100

    def __post_init__(self) -> None:
        _token(self.frame_id, "frame_id")
        if (
            not isinstance(self.duration_ms, int)
            or isinstance(self.duration_ms, bool)
            or not 1 <= self.duration_ms <= 60_000
        ):
            raise PixeloramaModelError("frame duration_ms must be between 1 and 60000")

    def to_dict(self) -> dict[str, object]:
        return {"frame_id": self.frame_id, "duration_ms": self.duration_ms}


@dataclass(frozen=True)
class AnimationSpec:
    name: str
    first_frame: int
    last_frame: int
    loop_mode: AnimationLoopMode = AnimationLoopMode.LOOP

    def __post_init__(self) -> None:
        _bounded_text(self.name, "animation name", maximum=256)
        for value, field in (
            (self.first_frame, "first_frame"),
            (self.last_frame, "last_frame"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise PixeloramaModelError(f"animation {field} must be a non-negative integer")
        if self.last_frame < self.first_frame:
            raise PixeloramaModelError("animation last_frame must be >= first_frame")
        if not isinstance(self.loop_mode, AnimationLoopMode):
            raise PixeloramaModelError("animation loop_mode must be an AnimationLoopMode")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "loop_mode": self.loop_mode.value,
        }


@dataclass(frozen=True)
class SpriteProjectSpec:
    width: int
    height: int
    layers: tuple[RasterLayerSpec, ...]
    frames: tuple[FrameSpec, ...]
    animations: tuple[AnimationSpec, ...] = ()
    palette: tuple[Rgba8, ...] = ()
    transparency_required: bool = True
    output_basename: str = "sprite"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise PixeloramaModelError("unsupported SpriteProjectSpec schema_version")
        for value, name in ((self.width, "width"), (self.height, "height")):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > _MAX_DIMENSION
            ):
                raise PixeloramaModelError(
                    f"sprite {name} must be between 1 and {_MAX_DIMENSION}"
                )
        if self.width * self.height > _MAX_PIXELS:
            raise PixeloramaModelError("sprite dimensions exceed pixel limit")
        layers = tuple(self.layers)
        frames = tuple(self.frames)
        animations = tuple(self.animations)
        palette = tuple(self.palette)
        if not layers or len(layers) > _MAX_LAYERS:
            raise PixeloramaModelError(f"sprite layers must contain 1..{_MAX_LAYERS} items")
        if not frames or len(frames) > _MAX_FRAMES:
            raise PixeloramaModelError(f"sprite frames must contain 1..{_MAX_FRAMES} items")
        if len(animations) > _MAX_ANIMATIONS:
            raise PixeloramaModelError("sprite animations exceed item limit")
        if len(palette) > _MAX_PALETTE:
            raise PixeloramaModelError("sprite palette exceeds item limit")
        if any(not isinstance(value, RasterLayerSpec) for value in layers):
            raise PixeloramaModelError("sprite layers must contain RasterLayerSpec values")
        if any(not isinstance(value, FrameSpec) for value in frames):
            raise PixeloramaModelError("sprite frames must contain FrameSpec values")
        if any(not isinstance(value, AnimationSpec) for value in animations):
            raise PixeloramaModelError("sprite animations must contain AnimationSpec values")
        if any(not isinstance(value, Rgba8) for value in palette):
            raise PixeloramaModelError("sprite palette must contain Rgba8 values")
        layer_ids = [value.layer_id for value in layers]
        frame_ids = [value.frame_id for value in frames]
        animation_names = [value.name for value in animations]
        if len(layer_ids) != len(set(layer_ids)):
            raise PixeloramaModelError("sprite contains duplicate layer IDs")
        if len(frame_ids) != len(set(frame_ids)):
            raise PixeloramaModelError("sprite contains duplicate frame IDs")
        if len(animation_names) != len(set(animation_names)):
            raise PixeloramaModelError("sprite contains duplicate animation names")
        for animation in animations:
            if animation.last_frame >= len(frames):
                raise PixeloramaModelError("animation frame range exceeds sprite frame count")
        if not isinstance(self.transparency_required, bool):
            raise PixeloramaModelError("transparency_required must be boolean")
        _token(self.output_basename, "output_basename")
        object.__setattr__(self, "layers", layers)
        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "animations", animations)
        object.__setattr__(self, "palette", palette)

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "width": self.width,
            "height": self.height,
            "layers": [value.to_dict() for value in self.layers],
            "frames": [value.to_dict() for value in self.frames],
            "animations": [value.to_dict() for value in self.animations],
            "palette": [value.to_dict() for value in self.palette],
            "transparency_required": self.transparency_required,
            "output_basename": self.output_basename,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}


@dataclass(frozen=True)
class BridgeBudget:
    max_input_bytes: int = 16 * 1024 * 1024
    max_output_bytes: int = 64 * 1024 * 1024
    max_outputs: int = 64
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        for value, name, maximum in (
            (self.max_input_bytes, "max_input_bytes", 512 * 1024 * 1024),
            (self.max_output_bytes, "max_output_bytes", 2 * 1024 * 1024 * 1024),
            (self.max_outputs, "max_outputs", 4096),
            (self.timeout_seconds, "timeout_seconds", 3600),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > maximum
            ):
                raise PixeloramaModelError(f"BridgeBudget {name} must be between 1 and {maximum}")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_outputs": self.max_outputs,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class BridgeInputRef:
    relative_path: str
    content_hash: str
    byte_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            bridge_relative_path(self.relative_path, "input relative_path"),
        )
        validate_sha256(self.content_hash, "input content_hash")
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool) or self.byte_count < 0:
            raise PixeloramaModelError("input byte_count must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True)
class ExportSpec:
    output_type: BridgeOutputType
    relative_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.output_type, BridgeOutputType):
            raise PixeloramaModelError("export output_type must be a BridgeOutputType")
        object.__setattr__(
            self,
            "relative_path",
            bridge_relative_path(self.relative_path, "export relative_path"),
        )
        if not self.relative_path.startswith("exports/"):
            raise PixeloramaModelError("export relative_path must stay under exports/")

    def to_dict(self) -> dict[str, str]:
        return {"output_type": self.output_type.value, "relative_path": self.relative_path}


@dataclass(frozen=True)
class PixeloramaBridgeRequest:
    operation_id: str
    workspace_id: str
    operation: BridgeOperation
    sprite_spec: SpriteProjectSpec | None = None
    input_refs: tuple[BridgeInputRef, ...] = ()
    export_specs: tuple[ExportSpec, ...] = ()
    budget: BridgeBudget = BridgeBudget()
    protocol_version: int = 1

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.PIXELORAMA_OPERATION):
            raise PixeloramaModelError("operation_id must be a PXOP ID")
        if not validate_id(self.workspace_id, IdKind.MEDIA_WORKSPACE):
            raise PixeloramaModelError("workspace_id must be a MEDIA ID")
        if not isinstance(self.operation, BridgeOperation):
            raise PixeloramaModelError("operation must be a BridgeOperation")
        if self.protocol_version != 1:
            raise PixeloramaModelError("unsupported Pixelorama bridge protocol_version")
        if self.sprite_spec is not None and not isinstance(self.sprite_spec, SpriteProjectSpec):
            raise PixeloramaModelError("sprite_spec must be a SpriteProjectSpec or null")
        inputs = tuple(self.input_refs)
        exports = tuple(self.export_specs)
        if any(not isinstance(value, BridgeInputRef) for value in inputs):
            raise PixeloramaModelError("input_refs must contain BridgeInputRef values")
        if any(not isinstance(value, ExportSpec) for value in exports):
            raise PixeloramaModelError("export_specs must contain ExportSpec values")
        input_paths = [value.relative_path for value in inputs]
        export_paths = [value.relative_path for value in exports]
        if len(input_paths) != len(set(input_paths)):
            raise PixeloramaModelError("request contains duplicate input paths")
        if len(export_paths) != len(set(export_paths)):
            raise PixeloramaModelError("request contains duplicate export paths")
        if set(input_paths).intersection(export_paths):
            raise PixeloramaModelError("request input and export paths may not overlap")
        if len(exports) > self.budget.max_outputs:
            raise PixeloramaModelError("request export count exceeds bridge budget")
        if sum(value.byte_count for value in inputs) > self.budget.max_input_bytes:
            raise PixeloramaModelError("request input byte total exceeds bridge budget")
        if self.operation == BridgeOperation.CREATE_SPRITE_PROJECT and self.sprite_spec is None:
            raise PixeloramaModelError("CREATE_SPRITE_PROJECT requires sprite_spec")
        object.__setattr__(self, "input_refs", tuple(sorted(inputs, key=lambda value: value.relative_path)))
        object.__setattr__(self, "export_specs", tuple(sorted(exports, key=lambda value: value.relative_path)))

    @classmethod
    def create(
        cls,
        *,
        operation: BridgeOperation,
        sprite_spec: SpriteProjectSpec | None = None,
        input_refs: Iterable[BridgeInputRef] = (),
        export_specs: Iterable[ExportSpec] = (),
        budget: BridgeBudget | None = None,
    ) -> "PixeloramaBridgeRequest":
        return cls(
            operation_id=new_id(IdKind.PIXELORAMA_OPERATION),
            workspace_id=new_id(IdKind.MEDIA_WORKSPACE),
            operation=operation,
            sprite_spec=sprite_spec,
            input_refs=tuple(input_refs),
            export_specs=tuple(export_specs),
            budget=budget or BridgeBudget(),
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "operation": self.operation.value,
            "sprite_spec": None if self.sprite_spec is None else self.sprite_spec.to_dict(),
            "input_refs": [value.to_dict() for value in self.input_refs],
            "export_specs": [value.to_dict() for value in self.export_specs],
            "budget": self.budget.to_dict(),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}


@dataclass(frozen=True)
class BridgeOutput:
    output_type: BridgeOutputType
    relative_path: str
    content_hash: str
    byte_count: int
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_type, BridgeOutputType):
            raise PixeloramaModelError("output_type must be a BridgeOutputType")
        object.__setattr__(
            self,
            "relative_path",
            bridge_relative_path(self.relative_path, "output relative_path"),
        )
        if not self.relative_path.startswith(("exports/", "project/")):
            raise PixeloramaModelError("bridge output must stay under exports/ or project/")
        validate_sha256(self.content_hash, "output content_hash")
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool) or self.byte_count < 0:
            raise PixeloramaModelError("output byte_count must be a non-negative integer")
        for value, field in ((self.width, "width"), (self.height, "height")):
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > _MAX_DIMENSION
            ):
                raise PixeloramaModelError(f"output {field} is invalid")
        if (self.width is None) != (self.height is None):
            raise PixeloramaModelError("output width and height must both be set or both be null")

    def to_dict(self) -> dict[str, object]:
        return {
            "output_type": self.output_type.value,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class PixeloramaBridgeResult:
    operation_id: str
    request_hash: str
    status: BridgeResultStatus
    pixelorama_version: str
    bridge_version: str
    bridge_fingerprint: str
    outputs: tuple[BridgeOutput, ...] = ()
    diagnostics: tuple[str, ...] = ()
    elapsed_ms: int = 0
    protocol_version: int = 1

    def __post_init__(self) -> None:
        if self.protocol_version != 1:
            raise PixeloramaModelError("unsupported Pixelorama result protocol_version")
        if not validate_id(self.operation_id, IdKind.PIXELORAMA_OPERATION):
            raise PixeloramaModelError("result operation_id must be a PXOP ID")
        validate_sha256(self.request_hash, "result request_hash")
        if not isinstance(self.status, BridgeResultStatus):
            raise PixeloramaModelError("result status must be a BridgeResultStatus")
        _bounded_text(self.pixelorama_version, "pixelorama_version", maximum=256)
        _bounded_text(self.bridge_version, "bridge_version", maximum=256)
        validate_sha256(self.bridge_fingerprint, "bridge_fingerprint")
        outputs = tuple(self.outputs)
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(value, BridgeOutput) for value in outputs):
            raise PixeloramaModelError("result outputs must contain BridgeOutput values")
        paths = [value.relative_path for value in outputs]
        if len(paths) != len(set(paths)):
            raise PixeloramaModelError("result contains duplicate output paths")
        if len(diagnostics) > 256:
            raise PixeloramaModelError("result diagnostics exceed item limit")
        for value in diagnostics:
            _bounded_text(value, "result diagnostic", maximum=4096, allow_empty=True)
        if not isinstance(self.elapsed_ms, int) or isinstance(self.elapsed_ms, bool) or self.elapsed_ms < 0:
            raise PixeloramaModelError("result elapsed_ms must be a non-negative integer")
        object.__setattr__(self, "outputs", tuple(sorted(outputs, key=lambda value: value.relative_path)))
        object.__setattr__(self, "diagnostics", diagnostics)

    def _content_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "operation_id": self.operation_id,
            "request_hash": self.request_hash,
            "status": self.status.value,
            "pixelorama_version": self.pixelorama_version,
            "bridge_version": self.bridge_version,
            "bridge_fingerprint": self.bridge_fingerprint,
            "outputs": [value.to_dict() for value in self.outputs],
            "diagnostics": list(self.diagnostics),
            "elapsed_ms": self.elapsed_ms,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}
