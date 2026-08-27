from __future__ import annotations

from .pixelorama_models import (
    AnimationLoopMode,
    AnimationSpec,
    BridgeBudget,
    BridgeInputRef,
    BridgeOperation,
    BridgeOutput,
    BridgeOutputType,
    BridgeResultStatus,
    ExportSpec,
    FrameSpec,
    LayerBlendMode,
    PixeloramaBridgeRequest,
    PixeloramaBridgeResult,
    PixeloramaModelError,
    RasterLayerSpec,
    Rgba8,
    SpriteProjectSpec,
)


class PixeloramaProtocolError(ValueError):
    pass


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PixeloramaProtocolError(f"invalid {label} fields")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PixeloramaProtocolError(f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PixeloramaProtocolError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PixeloramaProtocolError(f"{field} must be boolean")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise PixeloramaProtocolError(f"{field} must be an array")
    return value


def _rgba(value: object) -> Rgba8:
    raw = _exact(value, {"r", "g", "b", "a"}, "RGBA color")
    try:
        return Rgba8(
            _integer(raw["r"], "r"),
            _integer(raw["g"], "g"),
            _integer(raw["b"], "b"),
            _integer(raw["a"], "a"),
        )
    except PixeloramaModelError as exc:
        raise PixeloramaProtocolError("RGBA color validation failed") from exc


def _layer(value: object) -> RasterLayerSpec:
    raw = _exact(
        value,
        {"layer_id", "name", "visible", "opacity", "blend_mode"},
        "raster layer",
    )
    try:
        return RasterLayerSpec(
            layer_id=_string(raw["layer_id"], "layer_id"),
            name=_string(raw["name"], "layer name"),
            visible=_boolean(raw["visible"], "layer visible"),
            opacity=_integer(raw["opacity"], "layer opacity"),
            blend_mode=LayerBlendMode(_string(raw["blend_mode"], "blend_mode")),
        )
    except PixeloramaProtocolError:
        raise
    except (PixeloramaModelError, ValueError) as exc:
        raise PixeloramaProtocolError("raster layer validation failed") from exc


def _frame(value: object) -> FrameSpec:
    raw = _exact(value, {"frame_id", "duration_ms"}, "frame")
    try:
        return FrameSpec(
            _string(raw["frame_id"], "frame_id"),
            _integer(raw["duration_ms"], "duration_ms"),
        )
    except PixeloramaModelError as exc:
        raise PixeloramaProtocolError("frame validation failed") from exc


def _animation(value: object) -> AnimationSpec:
    raw = _exact(
        value,
        {"name", "first_frame", "last_frame", "loop_mode"},
        "animation",
    )
    try:
        return AnimationSpec(
            name=_string(raw["name"], "animation name"),
            first_frame=_integer(raw["first_frame"], "first_frame"),
            last_frame=_integer(raw["last_frame"], "last_frame"),
            loop_mode=AnimationLoopMode(_string(raw["loop_mode"], "loop_mode")),
        )
    except PixeloramaProtocolError:
        raise
    except (PixeloramaModelError, ValueError) as exc:
        raise PixeloramaProtocolError("animation validation failed") from exc


def parse_sprite_spec(value: object) -> SpriteProjectSpec:
    raw = _exact(
        value,
        {
            "schema_version",
            "width",
            "height",
            "layers",
            "frames",
            "animations",
            "palette",
            "transparency_required",
            "output_basename",
            "content_hash",
        },
        "sprite specification",
    )
    try:
        spec = SpriteProjectSpec(
            schema_version=_integer(raw["schema_version"], "schema_version"),
            width=_integer(raw["width"], "width"),
            height=_integer(raw["height"], "height"),
            layers=tuple(_layer(item) for item in _array(raw["layers"], "layers")),
            frames=tuple(_frame(item) for item in _array(raw["frames"], "frames")),
            animations=tuple(
                _animation(item) for item in _array(raw["animations"], "animations")
            ),
            palette=tuple(_rgba(item) for item in _array(raw["palette"], "palette")),
            transparency_required=_boolean(
                raw["transparency_required"], "transparency_required"
            ),
            output_basename=_string(raw["output_basename"], "output_basename"),
        )
    except PixeloramaModelError as exc:
        raise PixeloramaProtocolError("sprite specification validation failed") from exc
    if raw["content_hash"] != spec.content_hash:
        raise PixeloramaProtocolError("sprite specification content hash mismatch")
    return spec


def _budget(value: object) -> BridgeBudget:
    raw = _exact(
        value,
        {"max_input_bytes", "max_output_bytes", "max_outputs", "timeout_seconds"},
        "bridge budget",
    )
    try:
        return BridgeBudget(
            max_input_bytes=_integer(raw["max_input_bytes"], "max_input_bytes"),
            max_output_bytes=_integer(raw["max_output_bytes"], "max_output_bytes"),
            max_outputs=_integer(raw["max_outputs"], "max_outputs"),
            timeout_seconds=_integer(raw["timeout_seconds"], "timeout_seconds"),
        )
    except PixeloramaModelError as exc:
        raise PixeloramaProtocolError("bridge budget validation failed") from exc


def parse_bridge_budget(value: object) -> BridgeBudget:
    """Parse one canonical bridge budget for a governed production request."""
    return _budget(value)


def _input_ref(value: object) -> BridgeInputRef:
    raw = _exact(
        value,
        {"relative_path", "content_hash", "byte_count"},
        "bridge input ref",
    )
    try:
        return BridgeInputRef(
            _string(raw["relative_path"], "input relative_path"),
            _string(raw["content_hash"], "input content_hash"),
            _integer(raw["byte_count"], "input byte_count"),
        )
    except PixeloramaModelError as exc:
        raise PixeloramaProtocolError("bridge input ref validation failed") from exc


def _export_spec(value: object) -> ExportSpec:
    raw = _exact(value, {"output_type", "relative_path"}, "export spec")
    try:
        return ExportSpec(
            BridgeOutputType(_string(raw["output_type"], "output_type")),
            _string(raw["relative_path"], "export relative_path"),
        )
    except PixeloramaProtocolError:
        raise
    except (PixeloramaModelError, ValueError) as exc:
        raise PixeloramaProtocolError("export spec validation failed") from exc


def parse_export_spec(value: object) -> ExportSpec:
    """Parse one canonical export declaration for a governed production request."""
    return _export_spec(value)


def parse_bridge_request(value: object) -> PixeloramaBridgeRequest:
    raw = _exact(
        value,
        {
            "protocol_version",
            "operation_id",
            "workspace_id",
            "operation",
            "sprite_spec",
            "input_refs",
            "export_specs",
            "budget",
            "content_hash",
        },
        "Pixelorama bridge request",
    )
    sprite_raw = raw["sprite_spec"]
    try:
        request = PixeloramaBridgeRequest(
            protocol_version=_integer(raw["protocol_version"], "protocol_version"),
            operation_id=_string(raw["operation_id"], "operation_id"),
            workspace_id=_string(raw["workspace_id"], "workspace_id"),
            operation=BridgeOperation(_string(raw["operation"], "operation")),
            sprite_spec=None if sprite_raw is None else parse_sprite_spec(sprite_raw),
            input_refs=tuple(
                _input_ref(item) for item in _array(raw["input_refs"], "input_refs")
            ),
            export_specs=tuple(
                _export_spec(item)
                for item in _array(raw["export_specs"], "export_specs")
            ),
            budget=_budget(raw["budget"]),
        )
    except PixeloramaProtocolError:
        raise
    except (PixeloramaModelError, ValueError) as exc:
        raise PixeloramaProtocolError("Pixelorama bridge request validation failed") from exc
    if raw["content_hash"] != request.content_hash:
        raise PixeloramaProtocolError("Pixelorama bridge request content hash mismatch")
    return request


def _output(value: object) -> BridgeOutput:
    raw = _exact(
        value,
        {"output_type", "relative_path", "content_hash", "byte_count", "width", "height"},
        "bridge output",
    )
    width = raw["width"]
    height = raw["height"]
    if width is not None:
        width = _integer(width, "output width")
    if height is not None:
        height = _integer(height, "output height")
    try:
        return BridgeOutput(
            output_type=BridgeOutputType(_string(raw["output_type"], "output_type")),
            relative_path=_string(raw["relative_path"], "output relative_path"),
            content_hash=_string(raw["content_hash"], "output content_hash"),
            byte_count=_integer(raw["byte_count"], "output byte_count"),
            width=width,
            height=height,
        )
    except PixeloramaProtocolError:
        raise
    except (PixeloramaModelError, ValueError) as exc:
        raise PixeloramaProtocolError("bridge output validation failed") from exc


def parse_bridge_result(value: object) -> PixeloramaBridgeResult:
    raw = _exact(
        value,
        {
            "protocol_version",
            "operation_id",
            "request_hash",
            "status",
            "pixelorama_version",
            "bridge_version",
            "bridge_fingerprint",
            "outputs",
            "diagnostics",
            "elapsed_ms",
            "content_hash",
        },
        "Pixelorama bridge result",
    )
    diagnostics = _array(raw["diagnostics"], "diagnostics")
    if any(not isinstance(item, str) for item in diagnostics):
        raise PixeloramaProtocolError("diagnostics must contain only strings")
    try:
        result = PixeloramaBridgeResult(
            protocol_version=_integer(raw["protocol_version"], "protocol_version"),
            operation_id=_string(raw["operation_id"], "operation_id"),
            request_hash=_string(raw["request_hash"], "request_hash"),
            status=BridgeResultStatus(_string(raw["status"], "status")),
            pixelorama_version=_string(raw["pixelorama_version"], "pixelorama_version"),
            bridge_version=_string(raw["bridge_version"], "bridge_version"),
            bridge_fingerprint=_string(raw["bridge_fingerprint"], "bridge_fingerprint"),
            outputs=tuple(_output(item) for item in _array(raw["outputs"], "outputs")),
            diagnostics=tuple(diagnostics),
            elapsed_ms=_integer(raw["elapsed_ms"], "elapsed_ms"),
        )
    except PixeloramaProtocolError:
        raise
    except (PixeloramaModelError, ValueError) as exc:
        raise PixeloramaProtocolError("Pixelorama bridge result validation failed") from exc
    if raw["content_hash"] != result.content_hash:
        raise PixeloramaProtocolError("Pixelorama bridge result content hash mismatch")
    return result
