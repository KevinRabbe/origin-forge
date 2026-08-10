# Phase 22 — Audio

Status: **DONE**

Phase 22 adds deterministic/local sound effects, FFmpeg processing, structured music, text-to-speech, and audio validation/provenance without turning an audio runtime, model, or processor into production authority.

## Core rule

```text
audio backend/model/process output = untrusted evidence
Origin Forge deterministic audio validation = structural truth
human/governance = acceptance/promotion authority
```

No audio component may complete a production Task, mark an asset semantically approved, overwrite canonical project assets, install arbitrary plugins/models, sign protected provenance, merge, or release.

## 1. Canonical v0 audio surface

The first independently validated interchange format is deliberately narrow:

```text
RIFF/WAVE
format: integer PCM
sample format: signed 16-bit little-endian
channels: 1 or 2
sample rate: bounded 8 kHz .. 192 kHz
metadata: ignored on ingest and removed by canonicalization
```

Origin Forge owns a standard-library WAV parser/encoder and canonicalizer. It independently validates RIFF/chunk framing, PCM format fields, byte rate/block alignment, sample/frame counts, duration/byte budgets, and exact PCM hashes. Accepted external WAV may contain bounded ancillary chunks, but canonical Origin Forge WAV contains only the required `fmt ` and `data` chunks.

Structural inspection records exact values such as:

- file SHA-256;
- canonical PCM SHA-256;
- byte count;
- channels;
- sample rate;
- frame/sample counts;
- exact peak absolute sample;
- clipped-sample count;
- non-zero sample count.

These metrics are deterministic structural evidence. They are not claims that audio sounds good, is intelligible, is mixed well, or satisfies a creative brief.

## 2. Typed identities

Phase 22 adds:

- `AUDIO-*` — isolated audio workspace;
- `AUDOP-*` — bounded audio operation;
- `AUDPROF-*` — governed processing/generation profile.

All IDs are infrastructure-owned and opaque.

## 3. Audio operation contract

`AudioOperationRequest` freezes:

- operation kind;
- exact backend ID/version;
- exact governed profile ID/hash;
- optional exact model/voice ID/hash;
- exact source audio references when required;
- text or prompt only for operations that require it;
- deterministic seed where applicable;
- target sample rate/channels;
- exact output path;
- maximum duration/byte/runtime budgets.

Initial operation kinds:

```text
SYNTHESIZE_SFX
SYNTHESIZE_SPEECH
GENERATE_MUSIC
PROCESS_AUDIO
```

Requests do not contain shell commands, arbitrary FFmpeg arguments/filter graphs, Python source, network URLs, plugin-install directives, or unrestricted host paths.

`AudioOperationResult` binds the exact operation/workspace/request/backend/profile/model identities and declares only the requested outputs. A successful backend response is not sufficient: output bytes are independently decoded and canonicalized before durable evidence is recorded.

## 4. Deterministic local SFX

The v0 SFX substrate includes an infrastructure-owned procedural renderer for small deterministic effects. It uses structured bounded synthesis specifications rather than prompt-to-code generation.

Implemented primitives include bounded square/triangle oscillators, seeded integer noise, deterministic envelopes, sequencing/mixing, and exact sample-rate/channel/duration/PCM-byte budgets. The renderer emits canonical PCM16 WAV. A model may later propose a structured SFX specification, but deterministic infrastructure validates and renders it.

## 5. Deterministic structured music

The v0 music substrate establishes a replaceable generation contract and a small deterministic structured renderer for test/reference material. Structured events use bounded frequencies/durations/amplitudes and deterministic waveform primitives.

Neural text-to-music is a separate backend implementation, not the canonical music representation. Models such as AudioCraft/MusicGen may be evaluated as external research providers, but license/runtime/model identities must be reviewed and pinned independently before any production role. No model download occurs as an operation side effect.

## 6. FFmpeg processing boundary

FFmpeg is treated as a one-shot external processor behind a fixed Origin Forge adapter. Callers do **not** supply arbitrary command-line tokens or filter strings.

The initial adapter supports bounded PCM16 WAV processing such as resampling, mono/stereo normalization, metadata stripping, and deterministic/bitexact-oriented codec/container flags where supported.

The process boundary requires:

- exact executable identity/hash and expected runtime version;
- `shell=False` / fixed argv construction;
- no stdin command stream;
- isolated `AUDIO-*` workspace;
- exact source-hash preconditions;
- hard timeout/stdout/stderr/output limits;
- no network/download surface;
- no overwrite outside the isolated workspace;
- post-process symlink/root containment checks;
- independent WAV decode/hash/canonicalization.

The real evidence profile pins FFmpeg release 8.1.2, upstream tag `n8.1.2`, and exact source commit `38b88335f99e76ed89ff3c93f877fdefce736c13`. The evidence workflow builds a network-disabled/autodetection-disabled runtime, hashes the built executable, and executes the governed adapter/service path. FFmpeg success or exit code 0 remains process evidence only.

## 7. Text-to-speech boundary

TTS is a replaceable local provider contract. The initial real provider is Piper through its governed v1.6.0 C++ CLI runtime. Origin Forge does not bundle or silently install Piper or voices.

A governed TTS profile freezes:

- runtime identity/version/tree hash;
- exact voice/model file hash;
- exact voice configuration hash;
- exact license-document hash and license ID;
- target sample rate/channels;
- fixed infrastructure-owned synthesis controls and output budget.

The real evidence profile pins Piper v1.6.0 at exact source commit `f04d52c5528ac7cf2d73757f57990ff490f75005`, exact espeak-ng commit `212928b394a96e8fd2096616bfd54e17845c48f6`, ONNX Runtime 1.22.0 with frozen archive size/SHA-512, and the `en_US-joe-medium` voice from exact piper-voices commit `375a0fe641dea077c2a47b4e9a056d6da521eed3`. The voice ONNX/config/license bytes are independently hashed and the profile records `CC0-1.0` license evidence.

Piper v1.6.0's C++ WAV writer intentionally emits a streaming RIFF/WAVE form with placeholder RIFF/data sizes and mono IEEE-float32 samples. Origin Forge keeps its shared canonical WAV parser strictly PCM16. A Piper-specific adapter-boundary normalizer accepts only the exact governed streaming shape (or already-canonical PCM16 for deterministic fake runners), derives the true payload length from EOF, rejects malformed/non-finite/unbounded samples, deterministically quantizes finite float32 samples to PCM16, then sends only canonical PCM16 WAV into shared Artifact/Verification evidence.

TTS output is therefore independently normalized, parsed, hashed and structurally validated before Artifact evidence is created. Text synthesis never implies semantic intelligibility or pronunciation verification.

## 8. Neural SFX/music provider boundary

Text-to-sound and text-to-music providers use the same authority pattern as TTS:

```text
frozen request/profile
→ one-shot isolated provider execution
→ bounded raw audio
→ Origin Forge canonicalization + structural validation
→ Artifact / Verification evidence
```

Provider-specific Python environments, model weights, licenses, device requirements and caches are external evidence inputs. They are never model-selected or downloaded during a production operation.

Research-only/non-commercial model weights are not promoted to a general production default merely because an evidence run succeeds. Phase 22 closes without requiring a neural SFX/music provider.

## 9. Durable evidence services

`AudioOperationService` records a dedicated audio Run and persists:

- exact request Artifact;
- backend/process result Artifact;
- canonical PCM16 WAV Artifact;
- deterministic structural audio Verification;
- exact runtime/profile/model/source identities.

The service independently requires the backend-reported workspace to be exactly `.origin-forge/audio-workspaces/<workspace_id>` before trusting persisted request/result/output bytes.

A successful audio Run may increment Task attempts, but it may not transition the production Task, create a Task PASS, merge, release, or adopt an output automatically.

## 10. Create-only adoption

`GeneratedAudioAdopter` publishes an audio Artifact only when exactly one matching structural PASS is present and current source bytes still match frozen evidence.

Adoption is create-only:

- no overwrite;
- no protected-root destination;
- no symlink destination/parent escape;
- post-copy rehash and reinspection;
- no semantic approval implied;
- no Task completion implied.

## 11. Read-only operator surface

The initial audio CLI remains inspection-only:

- `status`
- `profile-list`
- `profile-show`
- `artifact-show`
- `operation-runs`

There is intentionally no generate/speak/process/adopt/install/download/promote/merge/release command in the read-only surface.

## 12. Evidence levels

Phase 22 distinguishes:

1. **Codec/substrate proof** — standard-library WAV parsing/canonicalization and deterministic synthesis tests.
2. **Fake-process protocol proof** — adversarial process/backend tests prove isolation, exact binding and authority separation.
3. **Real FFmpeg proof** — a pinned real FFmpeg runtime processes exact frozen audio through a governed profile and the result is independently canonicalized.
4. **Real TTS proof** — a pinned Piper runtime + exact reviewed voice produces bounded speech through the governed service and the result is independently normalized/canonicalized/validated.
5. **Neural SFX/music proof** — optional provider-specific real model evidence after license/runtime review.
6. **Quality evaluation** — separate paired/replayable intelligibility/aesthetic/fit evaluation before default provider/profile promotion.

These levels may not be collapsed into one another.

## 13. Authority exclusions

Phase 22 components may not:

- complete or verify production Tasks/Goals;
- merge or release;
- sign with protected provenance keys;
- overwrite existing canonical assets;
- execute caller/model-supplied shell commands or FFmpeg filter graphs;
- install arbitrary codecs/plugins/packages/models as an operation side effect;
- download unreviewed model/voice weights as an operation side effect;
- treat process success as audio truth;
- treat structural audio metrics as semantic quality;
- treat a TTS/music/SFX model opinion/output as verification authority.

## Exit condition

Phase 22 is complete because:

- canonical PCM16 WAV parsing/canonicalization is exact-head green;
- deterministic local SFX and structured music rendering are independently reproducible;
- bounded audio operation/evidence/adoption authority separation is exact-head green;
- a pinned real FFmpeg processing path executes through the governed boundary and its output is independently validated;
- a pinned real Piper runtime/voice executes through the governed boundary and its streaming float output is independently normalized and validated;
- neural SFX/music providers remain replaceable and are not required for closure absent an explicitly approved production-suitable licensed profile.

Quality promotion remains a separate measured decision.
