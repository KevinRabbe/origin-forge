from __future__ import annotations

import struct
import unittest

from origin_forge.audio_wav import (
    WavError,
    canonicalize_pcm16_wav,
    decode_pcm16_wav,
    encode_pcm16_wav,
    inspect_pcm16_wav,
)


class AudioWavTests(unittest.TestCase):
    def test_round_trip_mono_pcm16_is_exact_and_deterministic(self) -> None:
        samples = (-32768, -10, 0, 10, 32767)
        pcm = b"".join(struct.pack("<h", value) for value in samples)
        data = encode_pcm16_wav(channels=1, sample_rate=16_000, pcm_bytes=pcm)
        decoded = decode_pcm16_wav(data)

        self.assertEqual(decoded.pcm_bytes, pcm)
        self.assertEqual(decoded.inspection.channels, 1)
        self.assertEqual(decoded.inspection.sample_rate, 16_000)
        self.assertEqual(decoded.inspection.frame_count, len(samples))
        self.assertEqual(decoded.inspection.sample_count, len(samples))
        self.assertEqual(decoded.inspection.peak_abs_sample, 32768)
        self.assertEqual(decoded.inspection.clipped_sample_count, 2)
        self.assertEqual(decoded.inspection.nonzero_sample_count, 4)
        self.assertEqual(decoded.inspection.ancillary_chunk_ids, ())
        self.assertEqual(canonicalize_pcm16_wav(data), data)

    def test_stereo_frame_alignment_is_enforced(self) -> None:
        with self.assertRaisesRegex(WavError, "frame aligned"):
            encode_pcm16_wav(
                channels=2,
                sample_rate=48_000,
                pcm_bytes=struct.pack("<h", 1),
            )

    def test_ancillary_chunks_are_structurally_accepted_but_removed_by_canonicalization(self) -> None:
        pcm = struct.pack("<hhhh", 1, 2, 3, 4)
        canonical = encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm)
        fmt_end = 12 + 8 + 16
        list_payload = b"INFO"
        extra = b"LIST" + struct.pack("<I", len(list_payload)) + list_payload
        with_list = (
            canonical[:fmt_end]
            + extra
            + canonical[fmt_end:]
        )
        with_list = with_list[:4] + struct.pack("<I", len(with_list) - 8) + with_list[8:]

        inspection = inspect_pcm16_wav(with_list)
        self.assertEqual(inspection.ancillary_chunk_ids, ("LIST",))
        self.assertEqual(canonicalize_pcm16_wav(with_list), canonical)
        self.assertNotEqual(inspection.content_hash, inspect_pcm16_wav(canonical).content_hash)
        self.assertEqual(inspection.pcm_hash, inspect_pcm16_wav(canonical).pcm_hash)

    def test_duplicate_data_chunk_fails_closed(self) -> None:
        pcm = struct.pack("<h", 1)
        data = encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm)
        duplicate = data + b"data" + struct.pack("<I", len(pcm)) + pcm
        duplicate = duplicate[:4] + struct.pack("<I", len(duplicate) - 8) + duplicate[8:]
        with self.assertRaisesRegex(WavError, "duplicate WAV data"):
            inspect_pcm16_wav(duplicate)

    def test_inconsistent_riff_size_fails_closed(self) -> None:
        pcm = struct.pack("<h", 1)
        data = bytearray(encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm))
        data[4:8] = struct.pack("<I", 1)
        with self.assertRaisesRegex(WavError, "RIFF size"):
            inspect_pcm16_wav(bytes(data))

    def test_non_pcm_and_non_16_bit_formats_fail_closed(self) -> None:
        pcm = struct.pack("<h", 1)
        data = bytearray(encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm))
        fmt_offset = 20
        data[fmt_offset : fmt_offset + 2] = struct.pack("<H", 3)
        with self.assertRaisesRegex(WavError, "integer PCM"):
            inspect_pcm16_wav(bytes(data))

        data = bytearray(encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm))
        data[fmt_offset + 14 : fmt_offset + 16] = struct.pack("<H", 24)
        with self.assertRaisesRegex(WavError, "16-bit PCM"):
            inspect_pcm16_wav(bytes(data))

    def test_duration_limit_is_enforced_without_float_arithmetic(self) -> None:
        pcm = struct.pack("<" + "h" * 9, *([1] * 9))
        data = encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=pcm)
        with self.assertRaisesRegex(WavError, "duration exceeds"):
            inspect_pcm16_wav(data, max_duration_ms=1)


if __name__ == "__main__":
    unittest.main()
