from __future__ import annotations

import json
import struct
import unittest

from origin_forge.blockbench_glb import GlbError, inspect_glb


def _chunk(kind: int, payload: bytes, pad: bytes) -> bytes:
    remainder = len(payload) % 4
    if remainder:
        payload += pad * (4 - remainder)
    return struct.pack("<II", len(payload), kind) + payload


def make_glb(mutator=None) -> bytes:
    root = {
        "asset": {"version": "2.0", "generator": "origin-forge-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Root", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 1,
                "type": "VEC3",
            }
        ],
        "bufferViews": [{"buffer": 0, "byteLength": 12}],
        "buffers": [{"byteLength": 12}],
    }
    if mutator is not None:
        mutator(root)
    json_payload = json.dumps(root, separators=(",", ":")).encode("utf-8")
    json_chunk = _chunk(0x4E4F534A, json_payload, b" ")
    bin_chunk = _chunk(0x004E4942, b"\x00" * 12, b"\x00")
    length = 12 + len(json_chunk) + len(bin_chunk)
    return b"glTF" + struct.pack("<II", 2, length) + json_chunk + bin_chunk


class BlockbenchGlbTests(unittest.TestCase):
    def test_minimal_self_contained_glb_is_inspected_and_hashed(self) -> None:
        data = make_glb()
        first = inspect_glb(data)
        second = inspect_glb(data)
        self.assertEqual(first, second)
        self.assertEqual(first.node_count, 1)
        self.assertEqual(first.mesh_count, 1)
        self.assertEqual(first.scene_count, 1)
        self.assertEqual(first.embedded_bin_bytes, 12)
        self.assertTrue(first.content_hash.startswith("sha256:"))
        self.assertEqual(first.byte_count, len(data))

    def test_magic_version_length_and_chunk_order_fail_closed(self) -> None:
        data = bytearray(make_glb())
        data[:4] = b"NOPE"
        with self.assertRaisesRegex(GlbError, "magic"):
            inspect_glb(bytes(data))

        data = bytearray(make_glb())
        struct.pack_into("<I", data, 4, 1)
        with self.assertRaisesRegex(GlbError, "version 2"):
            inspect_glb(bytes(data))

        data = bytearray(make_glb())
        struct.pack_into("<I", data, 8, len(data) + 4)
        with self.assertRaisesRegex(GlbError, "declared length"):
            inspect_glb(bytes(data))

        json_chunk = _chunk(0x4E4F534A, b'{"asset":{"version":"2.0"}}', b" ")
        bin_chunk = _chunk(0x004E4942, b"\x00\x00\x00\x00", b"\x00")
        length = 12 + len(bin_chunk) + len(json_chunk)
        wrong_order = b"glTF" + struct.pack("<II", 2, length) + bin_chunk + json_chunk
        with self.assertRaisesRegex(GlbError, "first chunk"):
            inspect_glb(wrong_order)

    def test_external_buffer_and_image_uris_are_rejected(self) -> None:
        with self.assertRaisesRegex(GlbError, "external URI"):
            inspect_glb(
                make_glb(
                    lambda root: root["buffers"][0].update({"uri": "mesh.bin"})
                )
            )

        def image_uri(root):
            root["images"] = [{"uri": "texture.png"}]

        with self.assertRaisesRegex(GlbError, "external URI"):
            inspect_glb(make_glb(image_uri))

    def test_invalid_mesh_reference_and_hierarchy_cycle_fail_closed(self) -> None:
        with self.assertRaisesRegex(GlbError, "out of range"):
            inspect_glb(
                make_glb(lambda root: root["nodes"][0].update({"mesh": 3}))
            )

        def cycle(root):
            root["nodes"] = [
                {"name": "A", "mesh": 0, "children": [1]},
                {"name": "B", "children": [0]},
            ]

        with self.assertRaisesRegex(GlbError, "cycle"):
            inspect_glb(make_glb(cycle))

    def test_animation_sampler_and_target_references_are_checked(self) -> None:
        def valid_animation(root):
            root["animations"] = [
                {
                    "samplers": [{"input": 0, "output": 0, "interpolation": "LINEAR"}],
                    "channels": [
                        {"sampler": 0, "target": {"node": 0, "path": "rotation"}}
                    ],
                }
            ]

        inspection = inspect_glb(make_glb(valid_animation))
        self.assertEqual(inspection.animation_count, 1)

        def invalid_target(root):
            valid_animation(root)
            root["animations"][0]["channels"][0]["target"]["node"] = 5

        with self.assertRaisesRegex(GlbError, "out of range"):
            inspect_glb(make_glb(invalid_target))

        def invalid_sampler(root):
            valid_animation(root)
            root["animations"][0]["channels"][0]["sampler"] = 2

        with self.assertRaisesRegex(GlbError, "out of range"):
            inspect_glb(make_glb(invalid_sampler))


if __name__ == "__main__":
    unittest.main()
