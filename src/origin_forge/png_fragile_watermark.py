from __future__ import annotations

import binascii
import hashlib
import struct

from .image_png import decode_truecolor8_png
from .media_fingerprint_models import (
    FingerprintMediaClass,
    MediaFingerprintModelError,
    WatermarkMutationClass,
    WatermarkPlan,
    WatermarkRobustnessClass,
)
from .media_watermark_models import WatermarkResult
from .runtime_observation_models import content_hash


_PRIVATE_CHUNK = b"ofWM"
_MAX_PAYLOAD_BYTES = 4096
_VERSION = "1"
_EMBEDDER_ID = "png-private-ancillary-fragile"
_DETECTOR_ID = "png-private-ancillary-detector"
_EMBEDDER_FINGERPRINT = content_hash(
    {
        "component": _EMBEDDER_ID,
        "version": _VERSION,
        "container": "PNG",
        "chunk_type": _PRIVATE_CHUNK.decode("ascii"),
        "placement": "immediately-before-IEND",
        "mutation": "metadata-only",
        "duplicate_private_chunk": "reject",
        "max_payload_bytes": _MAX_PAYLOAD_BYTES,
    }
)
_DETECTOR_FINGERPRINT = content_hash(
    {
        "component": _DETECTOR_ID,
        "version": _VERSION,
        "validator": "origin_forge.image_png.decode_truecolor8_png",
        "chunk_type": _PRIVATE_CHUNK.decode("ascii"),
        "duplicate_private_chunk": "reject",
        "result": "exact-payload-sha256-only",
        "authorship_claim": False,
    }
)


class PngWatermarkError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def create_png_fragile_metadata_plan(
    *,
    parent_ref: str,
    parent: bytes,
    mark_payload: bytes,
) -> WatermarkPlan:
    decode_truecolor8_png(parent)
    return WatermarkPlan.create(
        media_class=FingerprintMediaClass.RASTER_IMAGE,
        parent_ref=parent_ref,
        parent_hash=_sha256(parent),
        mark_payload=mark_payload,
        embedder_id=_EMBEDDER_ID,
        embedder_version=_VERSION,
        embedder_fingerprint=_EMBEDDER_FINGERPRINT,
        detector_id=_DETECTOR_ID,
        detector_version=_VERSION,
        detector_fingerprint=_DETECTOR_FINGERPRINT,
        robustness_class=WatermarkRobustnessClass.FRAGILE_METADATA,
        mutation_class=WatermarkMutationClass.METADATA_ONLY,
    )


def _validate_plan(plan: WatermarkPlan) -> None:
    if not isinstance(plan, WatermarkPlan):
        raise TypeError("plan must be a WatermarkPlan")
    expected = (
        plan.media_class is FingerprintMediaClass.RASTER_IMAGE
        and plan.embedder_id == _EMBEDDER_ID
        and plan.embedder_version == _VERSION
        and plan.embedder_fingerprint == _EMBEDDER_FINGERPRINT
        and plan.detector_id == _DETECTOR_ID
        and plan.detector_version == _VERSION
        and plan.detector_fingerprint == _DETECTOR_FINGERPRINT
        and plan.robustness_class is WatermarkRobustnessClass.FRAGILE_METADATA
        and plan.mutation_class is WatermarkMutationClass.METADATA_ONLY
    )
    if not expected:
        raise MediaFingerprintModelError(
            "watermark plan is not the exact governed PNG fragile-metadata contract"
        )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _validated_chunk_spans(data: bytes) -> tuple[tuple[int, int, bytes, bytes], ...]:
    # The full PNG structure/CRC/ordering has already been validated by
    # decode_truecolor8_png. This helper only locates the private ancillary
    # chunk and IEND; it is not a second media-validity parser.
    offset = 8
    spans: list[tuple[int, int, bytes, bytes]] = []
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        end = payload_end + 4
        spans.append((offset, end, kind, data[payload_start:payload_end]))
        offset = end
    return tuple(spans)


def embed_png_fragile_metadata(
    *,
    plan: WatermarkPlan,
    parent: bytes,
    mark_payload: bytes,
) -> bytes:
    _validate_plan(plan)
    if not isinstance(parent, bytes):
        raise TypeError("parent must be bytes")
    if not isinstance(mark_payload, bytes):
        raise TypeError("mark_payload must be bytes")
    if not mark_payload or len(mark_payload) > _MAX_PAYLOAD_BYTES:
        raise PngWatermarkError("mark payload byte size is outside bounds")
    if _sha256(parent) != plan.parent_hash:
        raise PngWatermarkError("parent bytes do not match exact watermark plan hash")
    if _sha256(mark_payload) != plan.payload_hash:
        raise PngWatermarkError("mark payload does not match exact watermark plan hash")

    decode_truecolor8_png(parent)
    spans = _validated_chunk_spans(parent)
    if any(kind == _PRIVATE_CHUNK for _, _, kind, _ in spans):
        raise PngWatermarkError("parent already contains Phase-28 private watermark chunk")
    iend = [start for start, _, kind, _ in spans if kind == b"IEND"]
    if len(iend) != 1:  # guarded by the validator, retained as fail-closed invariant
        raise PngWatermarkError("validated PNG does not contain exactly one IEND")
    start = iend[0]
    derivative = parent[:start] + _chunk(_PRIVATE_CHUNK, mark_payload) + parent[start:]
    # Format validity is checked, but presence/authenticity is deliberately left
    # to the separately invoked detector below.
    decode_truecolor8_png(derivative)
    return derivative


def detect_png_fragile_metadata(
    *,
    plan: WatermarkPlan,
    derivative: bytes,
) -> WatermarkResult:
    _validate_plan(plan)
    if not isinstance(derivative, bytes):
        raise TypeError("derivative must be bytes")
    decode_truecolor8_png(derivative)
    marks = [
        payload
        for _, _, kind, payload in _validated_chunk_spans(derivative)
        if kind == _PRIVATE_CHUNK
    ]
    if len(marks) > 1:
        raise PngWatermarkError("derivative contains ambiguous duplicate watermark chunks")
    if marks and len(marks[0]) > _MAX_PAYLOAD_BYTES:
        raise PngWatermarkError("observed watermark payload exceeds detector byte limit")
    observed = _sha256(marks[0]) if marks else None
    result = WatermarkResult.create(
        plan=plan,
        derivative_hash=_sha256(derivative),
        observed_payload_hash=observed,
        format_validated=True,
    )
    result.bind_plan(plan)
    return result
