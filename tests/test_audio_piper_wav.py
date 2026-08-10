from __future__ import annotations

import math
import struct
import unittest

from origin_forge.adapters.audio_piper_wav import canonicalize_piper_output_wav
from origin_forge.audio_wav import WavError, decode_pcm16_wav, encode_pcm16_wav


_UNSPECIFIED = 0x7FFFF000


def _piper_stream_wav(
    samples: tuple[float, ...],
    *,
    sample_rate: int = 22_050,
    riff_size: int = _UNSPECIFIED + 36,
    data_size: int = _UNSPECIFIED,
    audio_format: int = 3,
    channels: int = 1,
    bits_per_sample: int = 32,
    block_align: int = 4,
    byte_rate: int | None = None,
) -> bytes:
    if byte_rate is None:
        byte_rate = sample_rate * block_align
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", riff_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),
            struct.pack(
                "<HHIIHH",
                audio_format,
                channels,
                sample_rate,
                byte_rate,
                block_align,
                bits_per_sample,
            ),
            b"data",
            struct.pack("<I", data_size),
            b"".join(struct.pack("<f", value) for value in samples),
        )
    )


class PiperStreamingWavTests(unittest.TestCase):
    def test_official_streaming_float_shape_canonicalizes_deterministically(self) -> None:
        raw = _piper_stream_wav((0.0, 0.25, -0.25, 1.0, -1.0, 2.0, -2.0))
        canonical = canonicalize_piper_output_wav(raw, max_duration_ms=1_000)
        decoded = decode_pcm16_wav(canonical, max_duration_ms=1_000)
        self.assertEqual(decoded.inspection.sample_rate, 22_050)
        self.assertEqual(decoded.inspection.channels, 1)
        self.assertEqual(decoded.inspection.frame_count, 7)
        self.assertEqual(
            tuple(value[0] for value in struct.iter_unpack("<h", decoded.pcm_bytes)),
            (0, 8192, -8192, 32767, -32768, 32767, -32768),
        )
        self.assertEqual(
            canonicalize_piper_output_wav(raw, max_duration_ms=1_000),
            canonical,
        )

    def test_already_canonical_pcm16_remains_supported(self) -> None:
        pcm = struct.pack("<hhh", 0, 123, -123)
        canonical = encode_pcm16_wav(channels=1, sample_rate=22_050, pcm_bytes=pcm)
        self.assertEqual(canonicalize_piper_output_wav(canonical), canonical)

    def test_streaming_placeholder_and_format_are_exact(self) -> None:
        cases = (
            (_piper_stream_wav((0.0,), riff_size=44), "RIFF placeholder"),
            (_piper_stream_wav((0.0,), data_size=4), "data placeholder"),
            (_piper_stream_wav((0.0,), audio_format=1), "IEEE float"),
            (_piper_stream_wav((0.0,), channels=2, block_align=8), "mono"),
            (_piper_stream_wav((0.0,), bits_per_sample=16), "float32"),
            (_piper_stream_wav((0.0,), block_align=8), "float32"),
            (_piper_stream_wav((0.0,), byte_rate=1), "byte rate"),
        )
        for raw, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(WavError, pattern):
                    canonicalize_piper_output_wav(raw)

    def test_nonfinite_float_samples_fail_closed(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(WavError, "non-finite"):
                    canonicalize_piper_output_wav(_piper_stream_wav((value,)))

    def test_payload_alignment_duration_and_size_are_bounded(self) -> None:
        raw = _piper_stream_wav((0.0,)) + b"x"
        with self.assertRaisesRegex(WavError, "frame aligned"):
            canonicalize_piper_output_wav(raw)

        nine_frames = _piper_stream_wav((0.0,) * 9, sample_rate=8_000)
        with self.assertRaisesRegex(WavError, "duration"):
            canonicalize_piper_output_wav(nine_frames, max_duration_ms=1)

        with self.assertRaisesRegex(WavError, "byte limit"):
            canonicalize_piper_output_wav(_piper_stream_wav((0.0,)), max_bytes=44)


if __name__ == "__main__":
    unittest.main()
