from __future__ import annotations

import binascii
import struct
import unittest
import zlib

from origin_forge.pixelorama_models import PixelPlane
from origin_forge.pixelorama_png import (
    PNG_SIGNATURE,
    PngError,
    decode_rgba8_png,
    encode_rgba8_png,
    inspect_rgba8_png,
)


def chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def filtered_png(filter_type: int, filtered_row: bytes, *, width: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, 1, 8, 6, 0, 0, 0)
    raw = bytes([filter_type]) + filtered_row
    return PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class PixeloramaPngTests(unittest.TestCase):
    def test_deterministic_encode_decode_round_trip(self) -> None:
        pixels = bytes(
            [
                255, 0, 0, 255,
                0, 255, 0, 128,
                0, 0, 255, 0,
                255, 255, 255, 255,
            ]
        )
        plane = PixelPlane(2, 2, pixels)
        first = encode_rgba8_png(plane)
        second = encode_rgba8_png(plane)
        self.assertEqual(first, second)
        decoded = decode_rgba8_png(first)
        self.assertEqual(decoded, plane)
        inspection = inspect_rgba8_png(first)
        self.assertEqual((inspection.width, inspection.height), (2, 2))
        self.assertEqual(inspection.nontransparent_pixels, 3)
        self.assertEqual(inspection.transparent_pixels, 1)
        self.assertEqual(inspection.opaque_pixels, 2)
        self.assertEqual(inspection.alpha_bbox, (0, 0, 1, 1))

    def test_all_standard_row_filters_decode(self) -> None:
        # Two RGBA pixels. The desired second pixel is [15, 25, 35, 45].
        first = bytes([10, 20, 30, 40])
        desired_second = bytes([15, 25, 35, 45])
        expected = first + desired_second

        cases = {
            0: expected,
            1: first + bytes((desired_second[i] - first[i]) & 0xFF for i in range(4)),
            2: expected,  # no previous row, so Up predictor is zero
            3: first + bytes((desired_second[i] - first[i] // 2) & 0xFF for i in range(4)),
            4: first + bytes((desired_second[i] - first[i]) & 0xFF for i in range(4)),
        }
        for filter_type, filtered in cases.items():
            with self.subTest(filter_type=filter_type):
                decoded = decode_rgba8_png(filtered_png(filter_type, filtered, width=2))
                self.assertEqual(decoded.rgba_bytes, expected)

    def test_signature_crc_chunk_order_and_trailing_bytes_fail_closed(self) -> None:
        plane = PixelPlane(1, 1, bytes([1, 2, 3, 4]))
        valid = encode_rgba8_png(plane)
        with self.assertRaisesRegex(PngError, "signature"):
            decode_rgba8_png(b"not-png")

        corrupt = bytearray(valid)
        # Flip one byte in the IHDR payload without updating CRC.
        corrupt[len(PNG_SIGNATURE) + 8] ^= 1
        with self.assertRaisesRegex(PngError, "CRC mismatch"):
            decode_rgba8_png(bytes(corrupt))

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        raw = zlib.compress(b"\x00\x01\x02\x03\x04")
        out_of_order = PNG_SIGNATURE + chunk(b"IDAT", raw) + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")
        with self.assertRaisesRegex(PngError, "IHDR must be the first"):
            decode_rgba8_png(out_of_order)

        with self.assertRaisesRegex(PngError, "trailing bytes"):
            decode_rgba8_png(valid + b"junk")

    def test_unsupported_color_depth_interlace_and_critical_chunk_fail_closed(self) -> None:
        def custom_ihdr(bit_depth: int, color_type: int, interlace: int = 0) -> bytes:
            ihdr = struct.pack(">IIBBBBB", 1, 1, bit_depth, color_type, 0, 0, interlace)
            return PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")) + chunk(b"IEND", b"")

        with self.assertRaisesRegex(PngError, "8-bit RGBA"):
            decode_rgba8_png(custom_ihdr(16, 6))
        with self.assertRaisesRegex(PngError, "8-bit RGBA"):
            decode_rgba8_png(custom_ihdr(8, 2))
        with self.assertRaisesRegex(PngError, "interlace"):
            decode_rgba8_png(custom_ihdr(8, 6, 1))

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        unknown_critical = (
            PNG_SIGNATURE
            + chunk(b"IHDR", ihdr)
            + chunk(b"ABCD", b"")
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(PngError, "unsupported critical"):
            decode_rgba8_png(unknown_critical)

    def test_decompressed_payload_must_match_exact_bounded_geometry(self) -> None:
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        too_much = PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" + b"x" * 100)) + chunk(b"IEND", b"")
        with self.assertRaises(PngError):
            decode_rgba8_png(too_much)

        too_little = PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\x01")) + chunk(b"IEND", b"")
        with self.assertRaisesRegex(PngError, "byte count mismatch"):
            decode_rgba8_png(too_little)

    def test_fully_transparent_and_fully_opaque_are_inspectable(self) -> None:
        transparent = inspect_rgba8_png(
            encode_rgba8_png(PixelPlane(1, 1, bytes([0, 0, 0, 0])))
        )
        self.assertTrue(transparent.fully_transparent)
        self.assertFalse(transparent.fully_opaque)
        self.assertIsNone(transparent.alpha_bbox)

        opaque = inspect_rgba8_png(
            encode_rgba8_png(PixelPlane(1, 1, bytes([0, 0, 0, 255])))
        )
        self.assertFalse(opaque.fully_transparent)
        self.assertTrue(opaque.fully_opaque)
        self.assertEqual(opaque.alpha_bbox, (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
