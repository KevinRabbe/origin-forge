from __future__ import annotations

import math
import struct

from ..audio_wav import WavError, canonicalize_pcm16_wav, encode_pcm16_wav


_PIPER_STREAM_UNSPECIFIED_DATA_BYTES = 0x7FFFF000
_PIPER_STREAM_RIFF_SIZE = _PIPER_STREAM_UNSPECIFIED_DATA_BYTES + 36
_PIPER_STREAM_HEADER_BYTES = 44
_MAX_WAV_BYTES = 64 * 1024 * 1024
_MAX_DURATION_MS = 10 * 60 * 1000
_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 192_000


def _quantize_float32_sample(sample: float) -> int:
    """Deterministically map one finite normalized float sample to signed PCM16."""
    if not math.isfinite(sample):
        raise WavError("Piper streaming WAV contains a non-finite float sample")
    if sample <= -1.0:
        return -32768
    if sample >= 1.0:
        return 32767
    if sample < 0.0:
        return int(sample * 32768.0 - 0.5)
    return int(sample * 32767.0 + 0.5)


def canonicalize_piper_output_wav(
    data: bytes,
    *,
    max_bytes: int = _MAX_WAV_BYTES,
    max_duration_ms: int = _MAX_DURATION_MS,
) -> bytes:
    """Normalize one governed Piper output into Origin Forge canonical PCM16 WAV.

    Piper v1.6.0's C++ CLI writes a streaming RIFF/WAVE header with placeholder
    RIFF/data sizes and mono IEEE-float32 samples.  This function accepts only
    that exact streaming shape (plus already-canonical PCM16 for compatibility
    with deterministic fake runners), derives the true payload length from EOF,
    validates it, and converts the samples deterministically to PCM16.
    """
    if not isinstance(data, bytes):
        raise TypeError("Piper WAV data must be bytes")
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if not isinstance(max_duration_ms, int) or max_duration_ms <= 0:
        raise ValueError("max_duration_ms must be positive")
    if len(data) > max_bytes:
        raise WavError("Piper WAV exceeds byte limit")

    try:
        return canonicalize_pcm16_wav(
            data,
            max_bytes=max_bytes,
            max_duration_ms=max_duration_ms,
        )
    except WavError:
        pass

    if len(data) < _PIPER_STREAM_HEADER_BYTES + 4:
        raise WavError("Piper streaming WAV is too small")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavError("expected Piper RIFF/WAVE container")
    if struct.unpack_from("<I", data, 4)[0] != _PIPER_STREAM_RIFF_SIZE:
        raise WavError("Piper streaming WAV has unexpected RIFF placeholder size")
    if data[12:16] != b"fmt " or struct.unpack_from("<I", data, 16)[0] != 16:
        raise WavError("Piper streaming WAV requires one canonical fmt chunk")

    (
        audio_format,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    ) = struct.unpack_from("<HHIIHH", data, 20)
    if audio_format != 3:
        raise WavError("Piper streaming WAV must use IEEE float format")
    if channels != 1:
        raise WavError("Piper streaming WAV must be mono")
    if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
        raise WavError("Piper streaming WAV sample rate is outside allowed range")
    if bits_per_sample != 32 or block_align != 4:
        raise WavError("Piper streaming WAV must use aligned float32 samples")
    if byte_rate != sample_rate * 4:
        raise WavError("Piper streaming WAV byte rate is inconsistent")
    if data[36:40] != b"data":
        raise WavError("Piper streaming WAV requires data immediately after fmt")
    if struct.unpack_from("<I", data, 40)[0] != _PIPER_STREAM_UNSPECIFIED_DATA_BYTES:
        raise WavError("Piper streaming WAV has unexpected data placeholder size")

    payload = data[_PIPER_STREAM_HEADER_BYTES:]
    if not payload:
        raise WavError("Piper streaming WAV data must be non-empty")
    if len(payload) % 4:
        raise WavError("Piper streaming WAV float payload is not frame aligned")
    frame_count = len(payload) // 4
    if frame_count * 1000 > sample_rate * max_duration_ms:
        raise WavError("Piper streaming WAV duration exceeds limit")

    pcm = bytearray(frame_count * 2)
    for index, (sample,) in enumerate(struct.iter_unpack("<f", payload)):
        struct.pack_into("<h", pcm, index * 2, _quantize_float32_sample(sample))
    return encode_pcm16_wav(
        channels=1,
        sample_rate=sample_rate,
        pcm_bytes=bytes(pcm),
    )
