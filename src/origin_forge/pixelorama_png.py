from __future__ import annotations

import binascii
import hashlib
import struct
import zlib
from dataclasses import dataclass

from .pixelorama_models import PixelPlane


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PNG_BYTES = 128 * 1024 * 1024
_MAX_COMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_CHUNKS = 4096


class PngError(ValueError):
    pass


@dataclass(frozen=True)
class PngInspection:
    width: int
    height: int
    pixel_hash: str
    byte_count: int
    nontransparent_pixels: int
    transparent_pixels: int
    opaque_pixels: int
    alpha_bbox: tuple[int, int, int, int] | None

    @property
    def fully_transparent(self) -> bool:
        return self.nontransparent_pixels == 0

    @property
    def fully_opaque(self) -> bool:
        return self.opaque_pixels == self.width * self.height

    def to_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "pixel_hash": self.pixel_hash,
            "byte_count": self.byte_count,
            "nontransparent_pixels": self.nontransparent_pixels,
            "transparent_pixels": self.transparent_pixels,
            "opaque_pixels": self.opaque_pixels,
            "alpha_bbox": None if self.alpha_bbox is None else list(self.alpha_bbox),
            "fully_transparent": self.fully_transparent,
            "fully_opaque": self.fully_opaque,
        }


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(chunk_type)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def encode_rgba8_png(plane: PixelPlane, *, compression_level: int = 9) -> bytes:
    if not isinstance(plane, PixelPlane):
        raise TypeError("plane must be a PixelPlane")
    if (
        not isinstance(compression_level, int)
        or isinstance(compression_level, bool)
        or not 0 <= compression_level <= 9
    ):
        raise ValueError("compression_level must be an integer from 0 to 9")
    stride = plane.width * 4
    raw = bytearray()
    for row in range(plane.height):
        raw.append(0)  # deterministic PNG filter: None
        start = row * stride
        raw.extend(plane.rgba_bytes[start : start + stride])
    compressed = zlib.compress(bytes(raw), level=compression_level)
    ihdr = struct.pack(
        ">IIBBBBB",
        plane.width,
        plane.height,
        8,  # bit depth
        6,  # truecolor + alpha
        0,  # compression
        0,  # filter method
        0,  # no interlace
    )
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter_row(filter_type: int, row: bytes, previous: bytes, bpp: int = 4) -> bytes:
    result = bytearray(len(row))
    if filter_type == 0:
        return row
    if filter_type not in {1, 2, 3, 4}:
        raise PngError(f"unsupported PNG filter type: {filter_type}")
    for index, value in enumerate(row):
        left = result[index - bpp] if index >= bpp else 0
        above = previous[index] if previous else 0
        upper_left = previous[index - bpp] if previous and index >= bpp else 0
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = above
        elif filter_type == 3:
            predictor = (left + above) // 2
        else:
            predictor = _paeth(left, above, upper_left)
        result[index] = (value + predictor) & 0xFF
    return bytes(result)


def _bounded_decompress(compressed: bytes, expected: int) -> bytes:
    if len(compressed) > _MAX_COMPRESSED_BYTES:
        raise PngError(
            f"PNG compressed payload exceeds byte limit ({len(compressed)} > {_MAX_COMPRESSED_BYTES})"
        )
    decompressor = zlib.decompressobj()
    output = bytearray()
    pending = compressed
    while pending:
        remaining = expected + 1 - len(output)
        if remaining <= 0:
            raise PngError("PNG decompressed payload exceeds expected size")
        chunk = decompressor.decompress(pending, remaining)
        output.extend(chunk)
        if len(output) > expected:
            raise PngError("PNG decompressed payload exceeds expected size")
        pending = decompressor.unconsumed_tail
        if not pending:
            break
    remaining = expected + 1 - len(output)
    if remaining <= 0 and not decompressor.eof:
        raise PngError("PNG decompressed payload exceeds expected size")
    if not decompressor.eof:
        tail = decompressor.flush(max(1, remaining))
        output.extend(tail)
    if len(output) != expected:
        raise PngError(
            f"PNG decompressed byte count mismatch ({len(output)} != {expected})"
        )
    if decompressor.unused_data or decompressor.unconsumed_tail:
        raise PngError("PNG compressed stream contains unexpected trailing data")
    return bytes(output)


def decode_rgba8_png(data: bytes, *, max_png_bytes: int = _MAX_PNG_BYTES) -> PixelPlane:
    if not isinstance(data, bytes):
        raise TypeError("PNG data must be bytes")
    if (
        not isinstance(max_png_bytes, int)
        or isinstance(max_png_bytes, bool)
        or max_png_bytes <= 0
    ):
        raise ValueError("max_png_bytes must be a positive integer")
    if len(data) > max_png_bytes:
        raise PngError(f"PNG exceeds byte limit ({len(data)} > {max_png_bytes})")
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("invalid PNG signature")

    offset = len(PNG_SIGNATURE)
    chunk_count = 0
    ihdr_seen = False
    idat_seen = False
    idat_closed = False
    iend_seen = False
    width = height = None
    compressed = bytearray()

    while offset < len(data):
        chunk_count += 1
        if chunk_count > _MAX_CHUNKS:
            raise PngError("PNG chunk count exceeds limit")
        if len(data) - offset < 12:
            raise PngError("truncated PNG chunk header")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        if length > max_png_bytes or len(data) - offset < length + 4:
            raise PngError("truncated or oversized PNG chunk")
        chunk_data = data[offset : offset + length]
        expected_crc = struct.unpack(">I", data[offset + length : offset + length + 4])[0]
        actual_crc = binascii.crc32(chunk_type)
        actual_crc = binascii.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise PngError(f"PNG chunk CRC mismatch: {chunk_type!r}")
        offset += length + 4

        if not ihdr_seen and chunk_type != b"IHDR":
            raise PngError("PNG IHDR must be the first chunk")
        if chunk_type == b"IHDR":
            if ihdr_seen or length != 13:
                raise PngError("invalid or duplicate PNG IHDR")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if width <= 0 or height <= 0:
                raise PngError("PNG dimensions must be positive")
            if width > 4096 or height > 4096 or width * height > 16_777_216:
                raise PngError("PNG dimensions exceed Origin Forge raster bounds")
            if bit_depth != 8 or color_type != 6:
                raise PngError("only 8-bit RGBA PNG color type 6 is supported")
            if compression != 0 or filter_method != 0 or interlace != 0:
                raise PngError("unsupported PNG compression/filter/interlace method")
            ihdr_seen = True
            continue
        if chunk_type == b"IDAT":
            if not ihdr_seen or iend_seen:
                raise PngError("PNG IDAT is out of order")
            if idat_closed:
                raise PngError("PNG IDAT chunks must be consecutive")
            idat_seen = True
            compressed.extend(chunk_data)
            if len(compressed) > _MAX_COMPRESSED_BYTES:
                raise PngError("PNG compressed payload exceeds byte limit")
            continue
        if idat_seen:
            idat_closed = True
        if chunk_type == b"IEND":
            if length != 0 or not idat_seen or iend_seen:
                raise PngError("invalid PNG IEND")
            iend_seen = True
            if offset != len(data):
                raise PngError("PNG contains trailing bytes after IEND")
            break
        if chunk_type and 65 <= chunk_type[0] <= 90:
            raise PngError(f"unsupported critical PNG chunk: {chunk_type!r}")

    if not ihdr_seen or not idat_seen or not iend_seen or width is None or height is None:
        raise PngError("PNG is missing required chunks")
    stride = width * 4
    expected_raw = height * (stride + 1)
    raw = _bounded_decompress(bytes(compressed), expected_raw)
    pixels = bytearray()
    previous = b""
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        filtered = raw[position : position + stride]
        position += stride
        row = _unfilter_row(filter_type, filtered, previous, 4)
        pixels.extend(row)
        previous = row
    return PixelPlane(width, height, bytes(pixels))


def inspect_rgba8_png(data: bytes) -> PngInspection:
    plane = decode_rgba8_png(data)
    nontransparent = 0
    transparent = 0
    opaque = 0
    min_x = min_y = None
    max_x = max_y = None
    for index in range(0, len(plane.rgba_bytes), 4):
        pixel = index // 4
        x = pixel % plane.width
        y = pixel // plane.width
        alpha = plane.rgba_bytes[index + 3]
        if alpha == 0:
            transparent += 1
            continue
        nontransparent += 1
        if alpha == 255:
            opaque += 1
        min_x = x if min_x is None else min(min_x, x)
        max_x = x if max_x is None else max(max_x, x)
        min_y = y if min_y is None else min(min_y, y)
        max_y = y if max_y is None else max(max_y, y)
    bbox = (
        None
        if min_x is None
        else (int(min_x), int(min_y), int(max_x), int(max_y))
    )
    return PngInspection(
        width=plane.width,
        height=plane.height,
        pixel_hash=plane.rgba_hash,
        byte_count=len(data),
        nontransparent_pixels=nontransparent,
        transparent_pixels=transparent,
        opaque_pixels=opaque,
        alpha_bbox=bbox,
    )
