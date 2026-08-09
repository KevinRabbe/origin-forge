from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass

from .pixelorama_models import PixelPlane
from .pixelorama_png import (
    PNG_SIGNATURE,
    PngError,
    PngInspection,
    _bounded_decompress,
    _unfilter_row,
)

_MAX_PNG_BYTES = 128 * 1024 * 1024
_MAX_COMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_CHUNKS = 4096


@dataclass(frozen=True)
class TruecolorPng:
    plane: PixelPlane
    source_color_type: int


def decode_truecolor8_png(
    data: bytes,
    *,
    max_png_bytes: int = _MAX_PNG_BYTES,
) -> TruecolorPng:
    """Decode bounded PNG truecolor type 2 or 6 into canonical RGBA bytes.

    Phase 19 deliberately remains RGBA-only. Phase 21 needs to accept the
    standard RGB PNGs emitted by image-generation tools while preserving a
    deterministic pixel hash. RGB is normalized to alpha=255; no palette,
    grayscale, interlace, color conversion, or ancillary color-management
    interpretation is performed.
    """

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
    width = height = color_type = None
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
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            if width <= 0 or height <= 0:
                raise PngError("PNG dimensions must be positive")
            if width > 4096 or height > 4096 or width * height > 16_777_216:
                raise PngError("PNG dimensions exceed Origin Forge raster bounds")
            if bit_depth != 8 or color_type not in {2, 6}:
                raise PngError("only 8-bit RGB/RGBA PNG color types 2 and 6 are supported")
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

    if (
        not ihdr_seen
        or not idat_seen
        or not iend_seen
        or width is None
        or height is None
        or color_type is None
    ):
        raise PngError("PNG is missing required chunks")

    source_bpp = 3 if color_type == 2 else 4
    stride = width * source_bpp
    expected_raw = height * (stride + 1)
    raw = _bounded_decompress(bytes(compressed), expected_raw)
    normalized = bytearray()
    previous = b""
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        filtered = raw[position : position + stride]
        position += stride
        row = _unfilter_row(filter_type, filtered, previous, source_bpp)
        if source_bpp == 4:
            normalized.extend(row)
        else:
            for index in range(0, len(row), 3):
                normalized.extend(row[index : index + 3])
                normalized.append(255)
        previous = row
    return TruecolorPng(
        plane=PixelPlane(width, height, bytes(normalized)),
        source_color_type=color_type,
    )


def inspect_truecolor8_png(data: bytes) -> PngInspection:
    decoded = decode_truecolor8_png(data)
    plane = decoded.plane
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
