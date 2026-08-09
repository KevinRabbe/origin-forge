from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any


_GLB_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_MAX_GLB_BYTES = 512 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_COLLECTION = 100_000


class GlbError(ValueError):
    pass


def _array(root: dict[str, Any], key: str) -> list[Any]:
    value = root.get(key, [])
    if not isinstance(value, list):
        raise GlbError(f"glTF {key} must be an array")
    if len(value) > _MAX_COLLECTION:
        raise GlbError(f"glTF {key} exceeds item limit")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GlbError(f"{label} must be an object")
    return value


def _index(value: Any, count: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GlbError(f"{label} must be an integer index")
    if value < 0 or value >= count:
        raise GlbError(f"{label} index is out of range")
    return value


def _optional_index(
    obj: dict[str, Any], key: str, count: int, label: str
) -> int | None:
    if key not in obj:
        return None
    return _index(obj[key], count, f"{label}.{key}")


def _validate_uri(uri: Any, label: str) -> None:
    if not isinstance(uri, str) or not uri:
        raise GlbError(f"{label} URI must be a non-empty string")
    if not uri.startswith("data:"):
        raise GlbError(f"{label} external URI is not allowed in Phase-20 GLB evidence")


@dataclass(frozen=True)
class GlbInspection:
    content_hash: str
    byte_count: int
    node_count: int
    mesh_count: int
    material_count: int
    texture_count: int
    animation_count: int
    scene_count: int
    embedded_bin_bytes: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "node_count": self.node_count,
            "mesh_count": self.mesh_count,
            "material_count": self.material_count,
            "texture_count": self.texture_count,
            "animation_count": self.animation_count,
            "scene_count": self.scene_count,
            "embedded_bin_bytes": self.embedded_bin_bytes,
        }


def inspect_glb(data: bytes) -> GlbInspection:
    if not isinstance(data, bytes):
        raise TypeError("GLB data must be bytes")
    if len(data) < 20:
        raise GlbError("GLB is truncated")
    if len(data) > _MAX_GLB_BYTES:
        raise GlbError("GLB exceeds byte limit")

    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    if magic != _GLB_MAGIC:
        raise GlbError("invalid GLB magic")
    if version != 2:
        raise GlbError("only GLB version 2 is supported")
    if declared_length != len(data):
        raise GlbError("GLB declared length does not match file length")

    offset = 12
    chunks: list[tuple[int, bytes]] = []
    while offset < len(data):
        if len(data) - offset < 8:
            raise GlbError("GLB chunk header is truncated")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        if chunk_length % 4 != 0:
            raise GlbError("GLB chunk length must be four-byte aligned")
        end = offset + chunk_length
        if end > len(data):
            raise GlbError("GLB chunk exceeds declared file length")
        chunks.append((chunk_type, data[offset:end]))
        offset = end
        if len(chunks) > 2:
            raise GlbError("Phase-20 GLB evidence allows JSON plus optional BIN only")
    if offset != len(data):
        raise GlbError("GLB contains trailing bytes")
    if not chunks or chunks[0][0] != _JSON_CHUNK:
        raise GlbError("GLB first chunk must be JSON")
    if len(chunks) == 2 and chunks[1][0] != _BIN_CHUNK:
        raise GlbError("GLB second chunk must be BIN when present")

    json_bytes = chunks[0][1]
    if len(json_bytes) > _MAX_JSON_BYTES:
        raise GlbError("GLB JSON chunk exceeds byte limit")
    try:
        text = json_bytes.decode("utf-8", errors="strict").rstrip(" \t\r\n\x00")
        root = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GlbError("GLB JSON chunk is invalid") from exc
    root = _object(root, "glTF root")

    asset = _object(root.get("asset"), "glTF asset")
    if asset.get("version") != "2.0":
        raise GlbError("glTF asset.version must be exactly 2.0")

    scenes = _array(root, "scenes")
    nodes = _array(root, "nodes")
    meshes = _array(root, "meshes")
    accessors = _array(root, "accessors")
    buffer_views = _array(root, "bufferViews")
    buffers = _array(root, "buffers")
    materials = _array(root, "materials")
    textures = _array(root, "textures")
    images = _array(root, "images")
    samplers = _array(root, "samplers")
    skins = _array(root, "skins")
    animations = _array(root, "animations")

    if not scenes:
        raise GlbError("glTF must contain at least one scene")
    if not nodes:
        raise GlbError("glTF must contain at least one node")
    if not meshes:
        raise GlbError("glTF must contain at least one mesh")

    if "scene" in root:
        _index(root["scene"], len(scenes), "glTF scene")

    for scene_index, raw_scene in enumerate(scenes):
        scene = _object(raw_scene, f"scene[{scene_index}]")
        for node_index in scene.get("nodes", []):
            _index(node_index, len(nodes), f"scene[{scene_index}].nodes")

    children_by_node: dict[int, list[int]] = {}
    for node_index, raw_node in enumerate(nodes):
        node = _object(raw_node, f"node[{node_index}]")
        _optional_index(node, "mesh", len(meshes), f"node[{node_index}]")
        _optional_index(node, "skin", len(skins), f"node[{node_index}]")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise GlbError(f"node[{node_index}].children must be an array")
        normalized_children = [
            _index(child, len(nodes), f"node[{node_index}].children")
            for child in children
        ]
        if len(normalized_children) != len(set(normalized_children)):
            raise GlbError("glTF node may not repeat a child")
        if node_index in normalized_children:
            raise GlbError("glTF node may not parent itself")
        children_by_node[node_index] = normalized_children

    def visit(node_index: int, visiting: set[int], visited: set[int]) -> None:
        if node_index in visited:
            return
        if node_index in visiting:
            raise GlbError("glTF node hierarchy contains a cycle")
        visiting.add(node_index)
        for child in children_by_node[node_index]:
            visit(child, visiting, visited)
        visiting.remove(node_index)
        visited.add(node_index)

    visited_nodes: set[int] = set()
    for node_index in range(len(nodes)):
        visit(node_index, set(), visited_nodes)

    for mesh_index, raw_mesh in enumerate(meshes):
        mesh = _object(raw_mesh, f"mesh[{mesh_index}]")
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise GlbError(f"mesh[{mesh_index}] must contain primitives")
        if len(primitives) > _MAX_COLLECTION:
            raise GlbError("mesh primitive count exceeds limit")
        for primitive_index, raw_primitive in enumerate(primitives):
            primitive = _object(
                raw_primitive, f"mesh[{mesh_index}].primitives[{primitive_index}]"
            )
            attributes = _object(
                primitive.get("attributes"),
                f"mesh[{mesh_index}].primitives[{primitive_index}].attributes",
            )
            if "POSITION" not in attributes:
                raise GlbError("mesh primitive must provide POSITION")
            for semantic, accessor_index in attributes.items():
                if not isinstance(semantic, str) or not semantic:
                    raise GlbError("mesh attribute semantic must be a string")
                _index(
                    accessor_index,
                    len(accessors),
                    f"mesh[{mesh_index}].attributes[{semantic}]",
                )
            _optional_index(
                primitive,
                "indices",
                len(accessors),
                f"mesh[{mesh_index}].primitive[{primitive_index}]",
            )
            _optional_index(
                primitive,
                "material",
                len(materials),
                f"mesh[{mesh_index}].primitive[{primitive_index}]",
            )

    for accessor_index, raw_accessor in enumerate(accessors):
        accessor = _object(raw_accessor, f"accessor[{accessor_index}]")
        _optional_index(
            accessor,
            "bufferView",
            len(buffer_views),
            f"accessor[{accessor_index}]",
        )
        count = accessor.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise GlbError(f"accessor[{accessor_index}].count must be non-negative")
        if count > _MAX_COLLECTION * 100:
            raise GlbError("accessor count exceeds limit")

    for view_index, raw_view in enumerate(buffer_views):
        view = _object(raw_view, f"bufferView[{view_index}]")
        _index(view.get("buffer"), len(buffers), f"bufferView[{view_index}].buffer")
        byte_length = view.get("byteLength")
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length < 0
            or byte_length > _MAX_GLB_BYTES
        ):
            raise GlbError(f"bufferView[{view_index}].byteLength is invalid")

    embedded_bin_bytes = len(chunks[1][1]) if len(chunks) == 2 else 0
    for buffer_index, raw_buffer in enumerate(buffers):
        buffer = _object(raw_buffer, f"buffer[{buffer_index}]")
        byte_length = buffer.get("byteLength")
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length < 0
            or byte_length > _MAX_GLB_BYTES
        ):
            raise GlbError(f"buffer[{buffer_index}].byteLength is invalid")
        if "uri" in buffer:
            _validate_uri(buffer["uri"], f"buffer[{buffer_index}]")
        elif buffer_index == 0 and embedded_bin_bytes == 0 and byte_length:
            raise GlbError("GLB declares embedded buffer data without a BIN chunk")
        elif buffer_index > 0:
            raise GlbError("additional GLB buffers require embedded data URIs")
        if buffer_index == 0 and "uri" not in buffer and byte_length > embedded_bin_bytes:
            raise GlbError("embedded buffer byteLength exceeds BIN chunk")

    for image_index, raw_image in enumerate(images):
        image = _object(raw_image, f"image[{image_index}]")
        has_uri = "uri" in image
        has_view = "bufferView" in image
        if has_uri == has_view:
            raise GlbError("glTF image must use exactly one of uri or bufferView")
        if has_uri:
            _validate_uri(image["uri"], f"image[{image_index}]")
        else:
            _index(
                image["bufferView"],
                len(buffer_views),
                f"image[{image_index}].bufferView",
            )
            if not isinstance(image.get("mimeType"), str) or not image["mimeType"].startswith("image/"):
                raise GlbError("bufferView image must declare an image MIME type")

    for texture_index, raw_texture in enumerate(textures):
        texture = _object(raw_texture, f"texture[{texture_index}]")
        _optional_index(texture, "source", len(images), f"texture[{texture_index}]")
        _optional_index(texture, "sampler", len(samplers), f"texture[{texture_index}]")

    for skin_index, raw_skin in enumerate(skins):
        skin = _object(raw_skin, f"skin[{skin_index}]")
        joints = skin.get("joints")
        if not isinstance(joints, list) or not joints:
            raise GlbError(f"skin[{skin_index}] must contain joints")
        for joint in joints:
            _index(joint, len(nodes), f"skin[{skin_index}].joints")
        _optional_index(skin, "skeleton", len(nodes), f"skin[{skin_index}]")
        _optional_index(
            skin,
            "inverseBindMatrices",
            len(accessors),
            f"skin[{skin_index}]",
        )

    for animation_index, raw_animation in enumerate(animations):
        animation = _object(raw_animation, f"animation[{animation_index}]")
        animation_samplers = animation.get("samplers")
        channels = animation.get("channels")
        if not isinstance(animation_samplers, list) or not isinstance(channels, list):
            raise GlbError("glTF animation must contain sampler and channel arrays")
        if not animation_samplers or not channels:
            raise GlbError("glTF animation sampler/channel arrays may not be empty")
        for sampler_index, raw_sampler in enumerate(animation_samplers):
            sampler = _object(raw_sampler, f"animation[{animation_index}].sampler[{sampler_index}]")
            _index(
                sampler.get("input"),
                len(accessors),
                f"animation[{animation_index}].sampler[{sampler_index}].input",
            )
            _index(
                sampler.get("output"),
                len(accessors),
                f"animation[{animation_index}].sampler[{sampler_index}].output",
            )
            if "interpolation" in sampler and sampler["interpolation"] not in {
                "LINEAR",
                "STEP",
                "CUBICSPLINE",
            }:
                raise GlbError("glTF animation interpolation is unsupported")
        for channel_index, raw_channel in enumerate(channels):
            channel = _object(raw_channel, f"animation[{animation_index}].channel[{channel_index}]")
            _index(
                channel.get("sampler"),
                len(animation_samplers),
                f"animation[{animation_index}].channel[{channel_index}].sampler",
            )
            target = _object(
                channel.get("target"),
                f"animation[{animation_index}].channel[{channel_index}].target",
            )
            _index(
                target.get("node"),
                len(nodes),
                f"animation[{animation_index}].channel[{channel_index}].target.node",
            )
            if target.get("path") not in {"translation", "rotation", "scale", "weights"}:
                raise GlbError("glTF animation target path is unsupported")

    return GlbInspection(
        content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
        node_count=len(nodes),
        mesh_count=len(meshes),
        material_count=len(materials),
        texture_count=len(textures),
        animation_count=len(animations),
        scene_count=len(scenes),
        embedded_bin_bytes=embedded_bin_bytes,
    )
