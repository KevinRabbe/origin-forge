from __future__ import annotations

import binascii
import json
import struct
import unittest
import zlib

from origin_forge.audio_wav import WavError, encode_pcm16_wav
from origin_forge.blockbench_glb import GlbError
from origin_forge.exact_media_fingerprint import (
    fingerprint_glb,
    fingerprint_pcm16_wav,
    fingerprint_raster_png,
    glb_fingerprint_algorithm,
)
from origin_forge.media_fingerprint_models import (
    FingerprintComparison,
    FingerprintComparisonOutcome,
    FingerprintMediaClass,
)
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import PngError, encode_rgba8_png


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _rgb_png(width: int, height: int, rgb: bytes) -> bytes:
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        start = row * stride
        raw.extend(rgb[start : start + stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _glb_chunk(kind: int, payload: bytes, pad: bytes) -> bytes:
    remainder = len(payload) % 4
    if remainder:
        payload += pad * (4 - remainder)
    return struct.pack("<II", len(payload), kind) + payload


def _make_glb(*, node_name: str = "Root") -> bytes:
    root = {
        "asset": {"version": "2.0", "generator": "phase28-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": node_name, "mesh": 0}],
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
    json_payload = json.dumps(root, separators=(",", ":")).encode("utf-8")
    json_chunk = _glb_chunk(0x4E4F534A, json_payload, b" ")
    bin_chunk = _glb_chunk(0x004E4942, b"\x00" * 12, b"\x00")
    length = 12 + len(json_chunk) + len(bin_chunk)
    return b"glTF" + struct.pack("<II", 2, length) + json_chunk + bin_chunk


class ExactMediaFingerprintTests(unittest.TestCase):
    def test_rgb_and_rgba_png_with_same_pixels_have_same_canonical_fingerprint(self) -> None:
        rgb = bytes((10, 20, 30, 40, 50, 60))
        rgb_png = _rgb_png(2, 1, rgb)
        rgba_png = encode_rgba8_png(
            PixelPlane(2, 1, bytes((10, 20, 30, 255, 40, 50, 60, 255)))
        )
        left = fingerprint_raster_png(source_ref="ART-rgb", source=rgb_png)
        right = fingerprint_raster_png(source_ref="ART-rgba", source=rgba_png)
        self.assertNotEqual(left.source_hash, right.source_hash)
        self.assertEqual(left.canonical_content_hash, right.canonical_content_hash)
        self.assertIs(
            FingerprintComparison.compare(left, right).outcome,
            FingerprintComparisonOutcome.EXACT_MATCH,
        )
        self.assertIs(left.media_class, FingerprintMediaClass.RASTER_IMAGE)
        self.assertFalse(left.structural_summary["perceptual_similarity"])

    def test_raster_geometry_is_part_of_canonical_identity(self) -> None:
        pixels = bytes((1, 2, 3, 255, 4, 5, 6, 255))
        row = fingerprint_raster_png(
            source_ref="ART-row",
            source=encode_rgba8_png(PixelPlane(2, 1, pixels)),
        )
        column = fingerprint_raster_png(
            source_ref="ART-column",
            source=encode_rgba8_png(PixelPlane(1, 2, pixels)),
        )
        self.assertNotEqual(row.canonical_content_hash, column.canonical_content_hash)

    def test_malformed_raster_is_rejected_by_existing_png_validator(self) -> None:
        with self.assertRaises(PngError):
            fingerprint_raster_png(source_ref="ART-bad-png", source=b"not-png")

    def test_wav_ancillary_container_difference_preserves_pcm_fingerprint(self) -> None:
        pcm = struct.pack("<hhhh", 1, -2, 3, -4)
        canonical = encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm)
        fmt_end = 12 + 8 + 16
        payload = b"INFO"
        extra = b"LIST" + struct.pack("<I", len(payload)) + payload
        with_list = canonical[:fmt_end] + extra + canonical[fmt_end:]
        with_list = with_list[:4] + struct.pack("<I", len(with_list) - 8) + with_list[8:]

        left = fingerprint_pcm16_wav(source_ref="ART-canonical-wav", source=canonical)
        right = fingerprint_pcm16_wav(source_ref="ART-list-wav", source=with_list)
        self.assertNotEqual(left.source_hash, right.source_hash)
        self.assertEqual(left.canonical_content_hash, right.canonical_content_hash)
        self.assertIs(
            FingerprintComparison.compare(left, right).outcome,
            FingerprintComparisonOutcome.EXACT_MATCH,
        )
        self.assertIn("LIST", right.structural_summary["ancillary_chunk_ids"])
        self.assertFalse(right.structural_summary["acoustic_similarity"])

    def test_audio_sample_rate_is_part_of_canonical_identity(self) -> None:
        pcm = struct.pack("<hhhh", 1, 2, 3, 4)
        low = fingerprint_pcm16_wav(
            source_ref="ART-low", source=encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm)
        )
        high = fingerprint_pcm16_wav(
            source_ref="ART-high", source=encode_pcm16_wav(channels=1, sample_rate=16_000, pcm_bytes=pcm)
        )
        self.assertNotEqual(low.canonical_content_hash, high.canonical_content_hash)

    def test_malformed_audio_is_rejected_by_existing_wav_validator(self) -> None:
        with self.assertRaises(WavError):
            fingerprint_pcm16_wav(source_ref="ART-bad-wav", source=b"not-a-wave")

    def test_glb_fingerprint_is_exact_validated_bytes_with_structural_summary(self) -> None:
        first = fingerprint_glb(source_ref="ART-glb-a", source=_make_glb(node_name="Root"))
        second = fingerprint_glb(source_ref="ART-glb-b", source=_make_glb(node_name="Renamed"))
        self.assertIs(first.media_class, FingerprintMediaClass.MODEL3D_GLB)
        self.assertEqual(first.canonical_content_hash, first.source_hash)
        self.assertNotEqual(first.canonical_content_hash, second.canonical_content_hash)
        self.assertEqual(first.structural_summary["node_count"], 1)
        self.assertFalse(first.structural_summary["export_invariance"])
        self.assertFalse(first.structural_summary["mesh_reindex_invariance"])
        self.assertEqual(glb_fingerprint_algorithm().algorithm_id, "glb-v2-validated-exact")

    def test_malformed_glb_is_rejected_by_existing_glb_validator(self) -> None:
        with self.assertRaises(GlbError):
            fingerprint_glb(source_ref="ART-bad-glb", source=b"not-a-glb")


if __name__ == "__main__":
    unittest.main()
