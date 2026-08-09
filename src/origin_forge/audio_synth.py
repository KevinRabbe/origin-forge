from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from enum import StrEnum

from .audio_wav import encode_pcm16_wav


_MAX_EVENTS = 128
_MAX_EVENT_MS = 30_000
_MAX_TOTAL_MS = 5 * 60 * 1000
_MAX_LOOPS = 32
_MAX_PCM_BYTES = 64 * 1024 * 1024 - 44


class AudioSynthError(ValueError):
    pass


class SynthWaveform(StrEnum):
    SQUARE = "SQUARE"
    TRIANGLE = "TRIANGLE"
    NOISE = "NOISE"


def _canonical_hash(value: object) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SynthEvent:
    waveform: SynthWaveform
    duration_ms: int
    amplitude_q15: int
    frequency_hz: int = 0
    attack_ms: int = 0
    release_ms: int = 0
    gap_ms: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.waveform, SynthWaveform):
            raise AudioSynthError("waveform must be a SynthWaveform")
        if not isinstance(self.duration_ms, int) or not 1 <= self.duration_ms <= _MAX_EVENT_MS:
            raise AudioSynthError("duration_ms is outside allowed range")
        if not isinstance(self.amplitude_q15, int) or not 0 <= self.amplitude_q15 <= 32767:
            raise AudioSynthError("amplitude_q15 is outside allowed range")
        if self.waveform is SynthWaveform.NOISE:
            if self.frequency_hz != 0:
                raise AudioSynthError("NOISE requires frequency_hz=0")
        elif not isinstance(self.frequency_hz, int) or not 20 <= self.frequency_hz <= 20_000:
            raise AudioSynthError("oscillator frequency_hz is outside allowed range")
        for value, label in (
            (self.attack_ms, "attack_ms"),
            (self.release_ms, "release_ms"),
            (self.gap_ms, "gap_ms"),
        ):
            if not isinstance(value, int) or not 0 <= value <= _MAX_EVENT_MS:
                raise AudioSynthError(f"{label} is outside allowed range")
        if self.attack_ms + self.release_ms > self.duration_ms:
            raise AudioSynthError("attack_ms + release_ms exceeds event duration")

    def to_dict(self) -> dict[str, object]:
        return {
            "waveform": self.waveform.value,
            "duration_ms": self.duration_ms,
            "amplitude_q15": self.amplitude_q15,
            "frequency_hz": self.frequency_hz,
            "attack_ms": self.attack_ms,
            "release_ms": self.release_ms,
            "gap_ms": self.gap_ms,
        }


@dataclass(frozen=True)
class SfxSpec:
    sample_rate: int
    channels: int
    seed: int
    events: tuple[SynthEvent, ...]

    def __post_init__(self) -> None:
        _validate_common(self.sample_rate, self.channels, self.seed, self.events, loops=1)
        if not self.events:
            raise AudioSynthError("SfxSpec requires at least one event")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "SFX",
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "seed": self.seed,
            "events": [event.to_dict() for event in self.events],
        }

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self.to_dict())


@dataclass(frozen=True)
class MusicSequenceSpec:
    sample_rate: int
    channels: int
    seed: int
    events: tuple[SynthEvent, ...]
    loops: int = 1

    def __post_init__(self) -> None:
        _validate_common(self.sample_rate, self.channels, self.seed, self.events, loops=self.loops)
        if not self.events:
            raise AudioSynthError("MusicSequenceSpec requires at least one event")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "MUSIC_SEQUENCE",
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "seed": self.seed,
            "events": [event.to_dict() for event in self.events],
            "loops": self.loops,
        }

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self.to_dict())


def _validate_common(
    sample_rate: int,
    channels: int,
    seed: int,
    events: tuple[SynthEvent, ...],
    *,
    loops: int,
) -> None:
    if not isinstance(sample_rate, int) or not 8_000 <= sample_rate <= 192_000:
        raise AudioSynthError("sample_rate is outside allowed range")
    if channels not in {1, 2}:
        raise AudioSynthError("channels must be mono or stereo")
    if not isinstance(seed, int) or not 0 <= seed <= (2**63 - 1):
        raise AudioSynthError("seed is outside allowed range")
    if not isinstance(events, tuple) or len(events) > _MAX_EVENTS:
        raise AudioSynthError("events must be a bounded tuple")
    if any(not isinstance(event, SynthEvent) for event in events):
        raise AudioSynthError("events must contain only SynthEvent values")
    if not isinstance(loops, int) or not 1 <= loops <= _MAX_LOOPS:
        raise AudioSynthError("loops is outside allowed range")
    total_ms = sum(event.duration_ms + event.gap_ms for event in events) * loops
    if total_ms > _MAX_TOTAL_MS:
        raise AudioSynthError("rendered duration exceeds synthesis limit")
    total_frames = (
        sum(
            (sample_rate * event.duration_ms) // 1000
            + (sample_rate * event.gap_ms) // 1000
            for event in events
        )
        * loops
    )
    if total_frames * channels * 2 > _MAX_PCM_BYTES:
        raise AudioSynthError("rendered PCM exceeds synthesis byte limit")


def _xorshift64(state: int) -> int:
    state &= (2**64 - 1)
    state ^= (state << 13) & (2**64 - 1)
    state ^= state >> 7
    state ^= (state << 17) & (2**64 - 1)
    return state & (2**64 - 1)


def _envelope_q15(event: SynthEvent, frame: int, frames: int, sample_rate: int) -> int:
    envelope = 32767
    attack_frames = (sample_rate * event.attack_ms) // 1000
    release_frames = (sample_rate * event.release_ms) // 1000
    if attack_frames and frame < attack_frames:
        envelope = min(envelope, (frame * 32767) // attack_frames)
    if release_frames and frame >= frames - release_frames:
        remaining = max(0, frames - frame - 1)
        envelope = min(envelope, (remaining * 32767) // release_frames)
    return envelope


def _oscillator_q15(
    waveform: SynthWaveform,
    *,
    frame: int,
    sample_rate: int,
    frequency_hz: int,
    noise_state: int,
) -> tuple[int, int]:
    if waveform is SynthWaveform.SQUARE:
        phase = (frame * frequency_hz) % sample_rate
        return (32767 if phase * 2 < sample_rate else -32767), noise_state
    if waveform is SynthWaveform.TRIANGLE:
        phase_q16 = ((frame * frequency_hz) << 16) // sample_rate
        phase_q16 &= 0xFFFF
        if phase_q16 < 32768:
            value = -32767 + (phase_q16 * 65534) // 32768
        else:
            value = 32767 - ((phase_q16 - 32768) * 65534) // 32768
        return value, noise_state
    noise_state = _xorshift64(noise_state or 0x9E3779B97F4A7C15)
    raw = ((noise_state >> 48) & 0xFFFF) - 32768
    if raw == -32768:
        raw = -32767
    return raw, noise_state


def _render_events(
    *,
    sample_rate: int,
    channels: int,
    seed: int,
    events: tuple[SynthEvent, ...],
    loops: int,
) -> bytes:
    pcm = bytearray()
    noise_state = (seed ^ 0xA5A5A5A55A5A5A5A) & (2**64 - 1)
    event_index = 0
    for _ in range(loops):
        for event in events:
            frames = max(1, (sample_rate * event.duration_ms) // 1000)
            noise_state ^= (event_index + 1) * 0x9E3779B97F4A7C15
            noise_state &= (2**64 - 1)
            for frame in range(frames):
                raw, noise_state = _oscillator_q15(
                    event.waveform,
                    frame=frame,
                    sample_rate=sample_rate,
                    frequency_hz=event.frequency_hz,
                    noise_state=noise_state,
                )
                envelope = _envelope_q15(event, frame, frames, sample_rate)
                value = (raw * event.amplitude_q15) // 32767
                value = (value * envelope) // 32767
                value = max(-32767, min(32767, value))
                packed = struct.pack("<h", value)
                pcm.extend(packed * channels)
            gap_frames = (sample_rate * event.gap_ms) // 1000
            if gap_frames:
                pcm.extend(b"\x00\x00" * channels * gap_frames)
            event_index += 1
    return bytes(pcm)


def render_sfx(spec: SfxSpec) -> bytes:
    if not isinstance(spec, SfxSpec):
        raise TypeError("spec must be an SfxSpec")
    pcm = _render_events(
        sample_rate=spec.sample_rate,
        channels=spec.channels,
        seed=spec.seed,
        events=spec.events,
        loops=1,
    )
    return encode_pcm16_wav(
        channels=spec.channels,
        sample_rate=spec.sample_rate,
        pcm_bytes=pcm,
    )


def render_music_sequence(spec: MusicSequenceSpec) -> bytes:
    if not isinstance(spec, MusicSequenceSpec):
        raise TypeError("spec must be a MusicSequenceSpec")
    pcm = _render_events(
        sample_rate=spec.sample_rate,
        channels=spec.channels,
        seed=spec.seed,
        events=spec.events,
        loops=spec.loops,
    )
    return encode_pcm16_wav(
        channels=spec.channels,
        sample_rate=spec.sample_rate,
        pcm_bytes=pcm,
    )
