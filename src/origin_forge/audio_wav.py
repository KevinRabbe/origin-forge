from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass


_MAX_WAV_BYTES = 64 * 1024 * 1024
_MAX_DURATION_MS = 10 * 60 * 1000
_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 192_000
_ALLOWED_CHANNELS = frozenset({1, 2})


class WavError(ValueError):
    pass


@dataclass(frozen=True)
class Pcm16WavInspection:
    content_hash: str
    pcm_hash: str
    byte_count: int
    channels: int
    sample_rate: int
    frame_count: int
    sample_count: int
    duration_ns: int
    peak_abs_sample: int
    clipped_sample_count: int
    nonzero_sample_count: int
    ancillary_chunk_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "content_hash": self.content_hash,
            "pcm_hash": self.pcm_hash,
            "byte_count": self.byte_count,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "frame_count": self.frame_count,
            "sample_count": self.sample_count,
            "duration_ns": self.duration_ns,
            "peak_abs_sample": self.peak_abs_sample,
            "clipped_sample_count": self.clipped_sample_count,
            "nonzero_sample_count": self.nonzero_sample_count,
            "ancillary_chunk_ids": list(self.ancillary_chunk_ids),
        }


@dataclass(frozen=True)
class DecodedPcm16Wav:
    inspection: Pcm16WavInspection
    pcm_bytes: bytes


def _fourcc(value: bytes) -> str:
    if len(value) != 4 or any(byte < 0x20 or byte > 0x7E for byte in value):
        raise WavError("WAV chunk ID must be printable ASCII FourCC")
    return value.decode("ascii")


def decode_pcm16_wav(
    data: bytes,
    *,
    max_bytes: int = _MAX_WAV_BYTES,
    max_duration_ms: int = _MAX_DURATION_MS,
) -> DecodedPcm16Wav:
    if not isinstance(data, bytes):
        raise TypeError("WAV data must be bytes")
    if max_bytes <= 0 or max_duration_ms <= 0:
        raise ValueError("WAV limits must be positive")
    if len(data) < 44:
        raise WavError("WAV file is too small")
    if len(data) > max_bytes:
        raise WavError("WAV file exceeds byte limit")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavError("expected RIFF/WAVE container")
    riff_size = struct.unpack_from("<I", data, 4)[0]
    if riff_size + 8 != len(data):
        raise WavError("RIFF size does not match file length")

    fmt: bytes | None = None
    pcm: bytes | None = None
    ancillary: list[str] = []
    offset = 12
    while offset < len(data):
        if len(data) - offset < 8:
            raise WavError("truncated WAV chunk header")
        chunk_id = data[offset : offset + 4]
        chunk_name = _fourcc(chunk_id)
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        payload_start = offset + 8
        payload_end = payload_start + chunk_size
        if payload_end > len(data):
            raise WavError(f"WAV chunk {chunk_name!r} exceeds file length")
        payload = data[payload_start:payload_end]
        if chunk_id == b"fmt ":
            if fmt is not None:
                raise WavError("duplicate WAV fmt chunk")
            fmt = payload
        elif chunk_id == b"data":
            if pcm is not None:
                raise WavError("duplicate WAV data chunk")
            pcm = payload
        else:
            ancillary.append(chunk_name)
        offset = payload_end
        if chunk_size & 1:
            if offset >= len(data):
                raise WavError("missing RIFF padding byte")
            offset += 1
    if offset != len(data):
        raise WavError("WAV chunk framing did not consume exact file")
    if fmt is None or pcm is None:
        raise WavError("WAV requires exactly one fmt and data chunk")
    if len(fmt) != 16:
        raise WavError("v0 WAV requires canonical 16-byte PCM fmt chunk")

    (
        audio_format,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    ) = struct.unpack("<HHIIHH", fmt)
    if audio_format != 1:
        raise WavError("v0 WAV supports integer PCM only")
    if channels not in _ALLOWED_CHANNELS:
        raise WavError("v0 WAV supports mono or stereo only")
    if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
        raise WavError("WAV sample rate is outside allowed range")
    if bits_per_sample != 16:
        raise WavError("v0 WAV supports signed 16-bit PCM only")
    expected_align = channels * 2
    if block_align != expected_align:
        raise WavError("WAV block alignment is inconsistent")
    if byte_rate != sample_rate * expected_align:
        raise WavError("WAV byte rate is inconsistent")
    if not pcm:
        raise WavError("WAV data chunk must be non-empty")
    if len(pcm) % block_align:
        raise WavError("WAV data chunk is not frame aligned")

    frame_count = len(pcm) // block_align
    if frame_count * 1000 > sample_rate * max_duration_ms:
        raise WavError("WAV duration exceeds limit")
    sample_count = len(pcm) // 2
    peak = 0
    clipped = 0
    nonzero = 0
    for (sample,) in struct.iter_unpack("<h", pcm):
        magnitude = -sample if sample < 0 else sample
        if magnitude > peak:
            peak = magnitude
        if sample in {-32768, 32767}:
            clipped += 1
        if sample:
            nonzero += 1

    inspection = Pcm16WavInspection(
        content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
        pcm_hash="sha256:" + hashlib.sha256(pcm).hexdigest(),
        byte_count=len(data),
        channels=channels,
        sample_rate=sample_rate,
        frame_count=frame_count,
        sample_count=sample_count,
        duration_ns=(frame_count * 1_000_000_000) // sample_rate,
        peak_abs_sample=peak,
        clipped_sample_count=clipped,
        nonzero_sample_count=nonzero,
        ancillary_chunk_ids=tuple(ancillary),
    )
    return DecodedPcm16Wav(inspection=inspection, pcm_bytes=pcm)


def inspect_pcm16_wav(
    data: bytes,
    *,
    max_bytes: int = _MAX_WAV_BYTES,
    max_duration_ms: int = _MAX_DURATION_MS,
) -> Pcm16WavInspection:
    return decode_pcm16_wav(
        data,
        max_bytes=max_bytes,
        max_duration_ms=max_duration_ms,
    ).inspection


def encode_pcm16_wav(*, channels: int, sample_rate: int, pcm_bytes: bytes) -> bytes:
    if channels not in _ALLOWED_CHANNELS:
        raise WavError("v0 WAV supports mono or stereo only")
    if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
        raise WavError("WAV sample rate is outside allowed range")
    if not isinstance(pcm_bytes, bytes):
        raise TypeError("PCM payload must be bytes")
    block_align = channels * 2
    if not pcm_bytes:
        raise WavError("PCM payload must be non-empty")
    if len(pcm_bytes) % block_align:
        raise WavError("PCM payload is not frame aligned")
    if len(pcm_bytes) > _MAX_WAV_BYTES - 44:
        raise WavError("PCM payload exceeds WAV byte limit")
    frame_count = len(pcm_bytes) // block_align
    if frame_count * 1000 > sample_rate * _MAX_DURATION_MS:
        raise WavError("PCM duration exceeds WAV limit")

    byte_rate = sample_rate * block_align
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, 16)
    riff_size = 4 + (8 + len(fmt)) + (8 + len(pcm_bytes))
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", riff_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", len(fmt)),
            fmt,
            b"data",
            struct.pack("<I", len(pcm_bytes)),
            pcm_bytes,
        )
    )


def canonicalize_pcm16_wav(
    data: bytes,
    *,
    max_bytes: int = _MAX_WAV_BYTES,
    max_duration_ms: int = _MAX_DURATION_MS,
) -> bytes:
    decoded = decode_pcm16_wav(
        data,
        max_bytes=max_bytes,
        max_duration_ms=max_duration_ms,
    )
    return encode_pcm16_wav(
        channels=decoded.inspection.channels,
        sample_rate=decoded.inspection.sample_rate,
        pcm_bytes=decoded.pcm_bytes,
    )
