from __future__ import annotations

import unittest

from origin_forge.audio_synth import (
    AudioSynthError,
    MusicSequenceSpec,
    SfxSpec,
    SynthEvent,
    SynthWaveform,
    render_music_sequence,
    render_sfx,
)
from origin_forge.audio_wav import decode_pcm16_wav, inspect_pcm16_wav


class AudioSynthTests(unittest.TestCase):
    def test_square_sfx_is_byte_identical_and_structurally_valid(self) -> None:
        spec = SfxSpec(
            sample_rate=8_000,
            channels=1,
            seed=7,
            events=(
                SynthEvent(
                    waveform=SynthWaveform.SQUARE,
                    frequency_hz=400,
                    duration_ms=20,
                    amplitude_q15=12_000,
                    attack_ms=2,
                    release_ms=2,
                ),
            ),
        )
        first = render_sfx(spec)
        second = render_sfx(spec)
        self.assertEqual(first, second)
        inspection = inspect_pcm16_wav(first)
        self.assertEqual(inspection.sample_rate, 8_000)
        self.assertEqual(inspection.channels, 1)
        self.assertEqual(inspection.frame_count, 160)
        self.assertGreater(inspection.nonzero_sample_count, 0)
        self.assertEqual(inspection.clipped_sample_count, 0)

    def test_noise_seed_changes_pcm_but_same_seed_replays_exactly(self) -> None:
        event = SynthEvent(
            waveform=SynthWaveform.NOISE,
            duration_ms=20,
            amplitude_q15=8_000,
        )
        first = SfxSpec(sample_rate=8_000, channels=1, seed=1, events=(event,))
        same = SfxSpec(sample_rate=8_000, channels=1, seed=1, events=(event,))
        other = SfxSpec(sample_rate=8_000, channels=1, seed=2, events=(event,))
        self.assertEqual(render_sfx(first), render_sfx(same))
        self.assertNotEqual(
            decode_pcm16_wav(render_sfx(first)).pcm_bytes,
            decode_pcm16_wav(render_sfx(other)).pcm_bytes,
        )

    def test_music_loops_repeat_exact_pcm_segment(self) -> None:
        event = SynthEvent(
            waveform=SynthWaveform.TRIANGLE,
            frequency_hz=250,
            duration_ms=10,
            amplitude_q15=10_000,
            gap_ms=5,
        )
        one = MusicSequenceSpec(
            sample_rate=8_000,
            channels=2,
            seed=9,
            events=(event,),
            loops=1,
        )
        two = MusicSequenceSpec(
            sample_rate=8_000,
            channels=2,
            seed=9,
            events=(event,),
            loops=2,
        )
        one_pcm = decode_pcm16_wav(render_music_sequence(one)).pcm_bytes
        two_decoded = decode_pcm16_wav(render_music_sequence(two))
        self.assertEqual(two_decoded.inspection.channels, 2)
        self.assertEqual(two_decoded.inspection.frame_count, 240)
        self.assertEqual(two_decoded.pcm_bytes, one_pcm + one_pcm)

    def test_attack_and_release_make_first_and_last_samples_zero(self) -> None:
        spec = SfxSpec(
            sample_rate=8_000,
            channels=1,
            seed=1,
            events=(
                SynthEvent(
                    waveform=SynthWaveform.SQUARE,
                    frequency_hz=200,
                    duration_ms=10,
                    amplitude_q15=20_000,
                    attack_ms=2,
                    release_ms=2,
                ),
            ),
        )
        pcm = decode_pcm16_wav(render_sfx(spec)).pcm_bytes
        self.assertEqual(pcm[:2], b"\x00\x00")
        self.assertEqual(pcm[-2:], b"\x00\x00")

    def test_spec_hashes_distinguish_kind_seed_and_loop_count(self) -> None:
        event = SynthEvent(
            waveform=SynthWaveform.SQUARE,
            frequency_hz=300,
            duration_ms=10,
            amplitude_q15=1_000,
        )
        sfx = SfxSpec(sample_rate=8_000, channels=1, seed=1, events=(event,))
        music = MusicSequenceSpec(
            sample_rate=8_000,
            channels=1,
            seed=1,
            events=(event,),
            loops=1,
        )
        music_two = MusicSequenceSpec(
            sample_rate=8_000,
            channels=1,
            seed=1,
            events=(event,),
            loops=2,
        )
        self.assertNotEqual(sfx.content_hash, music.content_hash)
        self.assertNotEqual(music.content_hash, music_two.content_hash)

    def test_invalid_events_and_oversized_pcm_fail_before_render(self) -> None:
        with self.assertRaisesRegex(AudioSynthError, "only SynthEvent"):
            SfxSpec(sample_rate=8_000, channels=1, seed=1, events=(object(),))  # type: ignore[arg-type]
        with self.assertRaisesRegex(AudioSynthError, "NOISE requires"):
            SynthEvent(
                waveform=SynthWaveform.NOISE,
                frequency_hz=100,
                duration_ms=10,
                amplitude_q15=1,
            )
        with self.assertRaisesRegex(AudioSynthError, "attack_ms \+ release_ms"):
            SynthEvent(
                waveform=SynthWaveform.SQUARE,
                frequency_hz=100,
                duration_ms=10,
                amplitude_q15=1,
                attack_ms=6,
                release_ms=5,
            )
        event = SynthEvent(
            waveform=SynthWaveform.SQUARE,
            frequency_hz=100,
            duration_ms=30_000,
            amplitude_q15=1,
            gap_ms=30_000,
        )
        with self.assertRaisesRegex(AudioSynthError, "PCM exceeds"):
            MusicSequenceSpec(
                sample_rate=192_000,
                channels=2,
                seed=1,
                events=(event,),
                loops=2,
            )


if __name__ == "__main__":
    unittest.main()
