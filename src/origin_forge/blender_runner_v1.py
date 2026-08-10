from __future__ import annotations

# This file is executed by Blender's embedded Python.  It intentionally has no
# Origin Forge imports: the host adapter fingerprints and stages these exact
# bytes, while this runner accepts only a bounded JSON data contract.

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy


_MAX_CUBOIDS = 4096
_MAX_NAME = 256
_MAX_COORDINATE = 1_000_000.0


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not -_MAX_COORDINATE <= result <= _MAX_COORDINATE:
        raise ValueError(f"{label} is outside the allowed range")
    return result


def _vec3(value: object, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be a three-number array")
    return tuple(
        _number(component, f"{label}[{index}]")
        for index, component in enumerate(value)
    )


def _name(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_NAME
        or "\x00" in value
    ):
        raise ValueError(f"{label} is invalid")
    return value


def _validate_project(project: object, expected_hash: object) -> dict[str, object]:
    if not isinstance(project, dict):
        raise ValueError("project must be an object")
    expected = {
        "schema_version",
        "project_name",
        "bones",
        "cuboids",
        "textures",
        "animations",
    }
    if set(project) != expected or project["schema_version"] != 1:
        raise ValueError("project fields do not match runner v1 schema")
    _name(project["project_name"], "project_name")
    if (
        project["bones"] != []
        or project["textures"] != []
        or project["animations"] != []
    ):
        raise ValueError(
            "runner v1 accepts unrigged untextured unanimated projects only"
        )
    cuboids = project["cuboids"]
    if not isinstance(cuboids, list) or not 1 <= len(cuboids) <= _MAX_CUBOIDS:
        raise ValueError("runner v1 cuboid count is outside the allowed range")
    if not isinstance(expected_hash, str) or _hash(project) != expected_hash:
        raise ValueError("project hash does not match request")
    return project


def _validate_cuboid(
    value: object,
) -> tuple[str, tuple[float, float, float], tuple[float, float, float]]:
    if not isinstance(value, dict):
        raise ValueError("cuboid must be an object")
    expected = {
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
    }
    if set(value) != expected:
        raise ValueError("cuboid fields do not match runner v1 schema")
    element_id = _name(value["element_id"], "element_id")
    _name(value["name"], "cuboid name")
    start = _vec3(value["from"], "cuboid from")
    end = _vec3(value["to"], "cuboid to")
    _vec3(value["origin"], "cuboid origin")
    rotation = _vec3(value["rotation"], "cuboid rotation")
    if any(component != 0.0 for component in rotation):
        raise ValueError("runner v1 accepts axis-aligned cuboids only")
    if value["parent_bone_id"] is not None:
        raise ValueError("runner v1 cuboids may not have parents")
    if value["inflate"] != 0.0:
        raise ValueError("runner v1 does not accept cuboid inflation")
    if value["uv_offset"] != [0.0, 0.0] or value["mirror_uv"] is not False:
        raise ValueError("runner v1 does not accept UV controls")
    if value["visible"] is not True:
        raise ValueError("runner v1 requires visible cuboids")
    if any(finish <= begin for begin, finish in zip(start, end, strict=True)):
        raise ValueError("runner v1 requires positive cuboid extent on every axis")
    return element_id, start, end


def _create_cuboid(
    element_id: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> None:
    x0, y0, z0 = start
    x1, y1, z1 = end
    vertices = (
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    )
    faces = (
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    )
    mesh = bpy.data.meshes.new(f"OF_MESH_{element_id}")
    mesh.from_pydata(vertices, (), faces)
    mesh.validate(verbose=False, clean_customdata=True)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(f"OF_CUBOID_{element_id}", mesh)
    bpy.context.scene.collection.objects.link(obj)


def _load_request(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if not raw or len(raw) > 16 * 1024 * 1024:
        raise ValueError("request byte size is outside the allowed range")
    value = json.loads(raw.decode("utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError("request must be an object")
    expected = {
        "protocol_version",
        "operation_id",
        "workspace_id",
        "operation",
        "project",
        "project_hash",
        "output_relative_path",
        "runner_fingerprint",
        "runtime_hash",
        "expected_blender_version",
        "budget",
    }
    if set(value) != expected or value["protocol_version"] != 1:
        raise ValueError("request fields do not match Blender runner v1 schema")
    if value["operation"] != "EXPORT_GLB":
        raise ValueError("runner v1 supports EXPORT_GLB only")
    _name(value["expected_blender_version"], "expected_blender_version")
    _validate_project(value["project"], value["project_hash"])
    return value


def _parse_args() -> argparse.Namespace:
    try:
        separator = sys.argv.index("--")
    except ValueError as exc:
        raise SystemExit("Blender runner requires -- argument separator") from exc
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(sys.argv[separator + 1 :])


def main() -> None:
    args = _parse_args()
    workspace = Path(args.workspace).resolve(strict=True)
    request_path = Path(args.request).resolve(strict=True)
    output_path = Path(args.output).resolve(strict=False)
    result_path = Path(args.result).resolve(strict=False)
    request_path.relative_to(workspace)
    output_path.parent.resolve(strict=True).relative_to(workspace)
    result_path.parent.resolve(strict=True).relative_to(workspace)

    request = _load_request(request_path)
    expected_output = (
        workspace / str(request["output_relative_path"])
    ).resolve(strict=False)
    if output_path != expected_output:
        raise ValueError("output path does not match frozen request")
    if (
        output_path.exists()
        or output_path.is_symlink()
        or result_path.exists()
        or result_path.is_symlink()
    ):
        raise ValueError("runner output target already exists")

    embedded_version = "Blender " + bpy.app.version_string
    expected_runtime_version = str(request["expected_blender_version"])
    if expected_runtime_version not in {
        embedded_version,
        embedded_version + " LTS",
    }:
        raise ValueError("embedded Blender API version does not match frozen request")

    # Factory startup is also enforced by the host argv. Clearing here makes
    # the runner's output independent of any default camera/light/mesh.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False, confirm=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for datablock in tuple(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)

    project = request["project"]
    assert isinstance(project, dict)
    for cuboid in project["cuboids"]:
        element_id, start, end = _validate_cuboid(cuboid)
        _create_cuboid(element_id, start, end)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        export_animations=False,
        export_cameras=False,
        export_lights=False,
        export_extras=False,
        export_materials="NONE",
        export_texcoords=False,
        export_normals=True,
        export_tangents=False,
        export_attributes=False,
        export_draco_mesh_compression_enable=False,
        export_meshopt_compression_enable=False,
        use_selection=False,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF export did not finish: {sorted(result)}")
    if not output_path.is_file() or output_path.is_symlink():
        raise RuntimeError("Blender did not create the declared GLB")

    runner_result = {
        "protocol_version": 1,
        "status": "SUCCEEDED",
        "operation_id": request["operation_id"],
        "workspace_id": request["workspace_id"],
        "request_hash": "sha256:"
        + hashlib.sha256(_canonical_bytes(request)).hexdigest(),
        "project_hash": request["project_hash"],
        "output_relative_path": request["output_relative_path"],
        "blender_version": expected_runtime_version,
    }
    result_path.write_bytes(_canonical_bytes(runner_result))


if __name__ == "__main__":
    main()
