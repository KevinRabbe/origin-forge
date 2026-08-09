# Phase 22 — Audio

Status: **IN PROGRESS**

Phase 22 adds deterministic/local sound effects, FFmpeg processing, music generation, text-to-speech, and audio validation/provenance without turning an audio runtime, model, or processor into production authority.

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

`AudioOperationResult` must bind the exact operation/workspace/request/backend/profile/model identities and declare only the requested outputs. A successful backend response is not sufficient: output bytes are independently decoded and canonicalized before durable evidence is recorded.

## 4. Deterministic local SFX

The v0 SFX substrate includes an infrastructure-owned procedural renderer for small deterministic effects. It uses structured bounded synthesis specifications rather than prompt-to-code generation.

Initial primitives may include:

- square/triangle oscillators;
- seeded integer noise;
- bounded amplitude/envelope parameters;
- deterministic sequencing/mixing;
- exact sample-rate/channel/duration budgets.

The renderer uses integer arithmetic where practical and emits canonical PCM16 WAV. A model may later propose a structured SFX specification, but deterministic infrastructure validates and renders it.

## 5. Deterministic structured music

The v0 music substrate establishes a replaceable generation contract and a small deterministic structured renderer for test/reference material. Structured events use bounded frequencies/durations/amplitudes and deterministic waveform primitives.

Neural text-to-music is a separate backend implementation, not the canonical music representation. Models such as AudioCraft/MusicGen may be evaluated as external research providers, but license/runtime/model identities must be reviewed and pinned independently before any production role. No model download occurs as an operation side effect.

## 6. FFmpeg processing boundary

FFmpeg is treated as a one-shot external processor behind a fixed Origin Forge adapter.

The initial adapter exposes only infrastructure-defined processing profiles. Callers do **not** supply arbitrary command-line tokens or filter strings.

A v0 canonical-processing profile may perform only bounded operations such as:

- exact input WAV -> PCM16 WAV;
- resample to an allowed sample rate;
- mono/stereo channel normalization;
- metadata stripping;
- deterministic/bitexact-oriented codec/container flags where supported.

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

FFmpeg success or exit code 0 is process evidence only.

## 7. Text-to-speech boundary

TTS is a replaceable local provider contract. The initial real-provider candidate is Piper through its current supported CLI/API surface, but Origin Forge does not bundle or silently install it.

A governed TTS profile freezes:

- runtime identity/version/hash;
- exact voice/model file hash;
- exact voice configuration hash;
- speaker/language identity where applicable;
- synthesis parameters and output budget;
- target canonical sample rate/channels.

Voice/model licensing is reviewed per profile. The active Piper runtime is GPLv3, so it remains an external governed capability rather than a core library dependency.

TTS output is independently parsed/canonicalized before Artifact evidence is created. Text synthesis never implies semantic intelligibility or pronunciation verification.

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

Research-only/non-commercial model weights are not promoted to a general production default merely because an evidence run succeeds.

## 9. Durable evidence services

`AudioOperationService` records a dedicated audio Run and persists:

- exact request Artifact;
- backend/process result Artifact;
- raw external output evidence where policy permits;
- canonical PCM16 WAV Artifact;
- deterministic structural audio Verification;
- exact runtime/profile/model/source identities.

The service must independently require the backend-reported workspace to be exactly `.origin-forge/audio-workspaces/<workspace_id>` before trusting persisted request/result/output bytes.

A successful audio Run may increment Task attempts, but it may not transition the production Task, create a Task PASS, merge, release, or adopt an output automatically.

## 10. Create-only adoption

A later `GeneratedAudioAdopter` may publish an audio Artifact only when exact structural PASS evidence is present and current source bytes still match the frozen evidence.

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
3. **Real FFmpeg proof** — one pinned real FFmpeg runtime processes exact frozen audio through a governed profile and the result is independently canonicalized.
4. **Real TTS proof** — one pinned real TTS runtime + exact reviewed voice produces bounded speech that passes structural validation.
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

Phase 22 is complete when:

- canonical PCM16 WAV parsing/canonicalization is exact-head green;
- deterministic local SFX and structured music rendering are independently reproducible;
- bounded audio operation/evidence/adoption authority separation is exact-head green;
- at least one pinned real FFmpeg processing path executes through the governed boundary and its output is independently validated;
- at least one pinned real TTS runtime/voice executes through the governed boundary and its output is independently validated;
- neural SFX/music providers remain replaceable and are not required for Phase 22 closure unless a production-suitable licensed profile is explicitly approved.

Quality promotion remains a separate measured decision.
