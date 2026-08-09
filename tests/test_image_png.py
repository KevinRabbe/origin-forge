from __future__ import annotations

import binascii
import hashlib
import struct
import unittest
import zlib

from origin_forge.image_png import decode_truecolor8_png, inspect_truecolor8_png
from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import PngError, encode_rgba8_png, inspect_rgba8_png


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
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
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b"")


class ImagePngTests(unittest.TestCase):
    def test_rgb8_is_normalized_to_opaque_rgba_for_pixel_hashing(self) -> None:
        rgb = bytes((10, 20, 30, 40, 50, 60))
        data = _rgb_png(2, 1, rgb)
        decoded = decode_truecolor8_png(data)
        self.assertEqual(decoded.source_color_type, 2)
        self.assertEqual(
            decoded.plane.rgba_bytes,
            bytes((10, 20, 30, 255, 40, 50, 60, 255)),
        )
        inspection = inspect_truecolor8_png(data)
        self.assertEqual(inspection.width, 2)
        self.assertEqual(inspection.height, 1)
        self.assertTrue(inspection.fully_opaque)
        self.assertEqual(inspection.transparent_pixels, 0)
        expected_hash = "sha256:" + hashlib.sha256(decoded.plane.rgba_bytes).hexdigest()
        self.assertEqual(inspection.pixel_hash, expected_hash)

    def test_rgba8_preserves_phase19_pixel_semantics(self) -> None:
        plane = PixelPlane(1, 2, bytes((1, 2, 3, 0, 4, 5, 6, 255)))
        data = encode_rgba8_png(plane)
        phase21 = inspect_truecolor8_png(data)
        phase19 = inspect_rgba8_png(data)
        self.assertEqual(phase21.pixel_hash, phase19.pixel_hash)
        self.assertEqual(phase21.transparent_pixels, phase19.transparent_pixels)
        self.assertEqual(phase21.opaque_pixels, phase19.opaque_pixels)

    def test_palette_grayscale_interlace_and_trailing_bytes_remain_rejected(self) -> None:
        rgb = _rgb_png(1, 1, bytes((1, 2, 3)))
        # Patch IHDR color type to grayscale and repair CRC.
        grayscale_ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
        grayscale = PNG_SIGNATURE + _chunk(b"IHDR", grayscale_ihdr) + rgb[33:]
        with self.assertRaises(PngError):
            decode_truecolor8_png(grayscale)

        interlaced_ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 1)
        interlaced = PNG_SIGNATURE + _chunk(b"IHDR", interlaced_ihdr) + rgb[33:]
        with self.assertRaises(PngError):
            decode_truecolor8_png(interlaced)
        with self.assertRaises(PngError):
            decode_truecolor8_png(rgb + b"trailing")


if __name__ == "__main__":
    unittest.main()
