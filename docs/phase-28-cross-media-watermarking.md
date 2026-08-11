# Phase 28 — Cross-Media Watermarking and Fingerprinting

Status: **DONE — governed exact fingerprints plus fragile derivative watermark evidence**

Phase 28 adds deterministic cross-media fingerprints and one explicitly fragile PNG watermark path without weakening Phase-18 cryptographic provenance.

## Core rule

```text
cryptographic provenance = trust root
fingerprint / watermark  = supplementary evidence
```

Fingerprint equality or watermark detection never proves authorship, never replaces an Artifact hash or Phase-18 signature, and never grants Task/adoption/signing/merge/release authority.

## v1 evidence identities

Phase 28 adds infrastructure-owned:

- `MFPR-*` — media fingerprints;
- `FPCMP-*` — exact fingerprint comparisons;
- `WMPLAN-*` — derivative watermark plans;
- `WMRES-*` — independent watermark detection results;
- `FPLINK-*` — explicit links from fingerprint evidence to Phase-18 provenance manifests.

All durable Phase-28 objects are immutable canonical JSON with no-overwrite publication and canonical/hash revalidation.

## Exact fingerprint algorithms

### Source text

`source-text-exact:1` accepts bounded strict UTF-8 source bytes and normalizes only line endings (`CRLF` / `CR` → `LF`). It rejects NUL/ambiguous control characters and does not trim, fold whitespace, remove comments, parse syntax, or claim refactor invariance.

The raw source hash remains distinct from the line-ending-normalized content hash.

### Raster image

`raster-rgba8-exact:1` reuses the existing independent `image_png.decode_truecolor8_png` boundary. Accepted 8-bit RGB and RGBA PNGs normalize to exact width/height + canonical RGBA8 pixel evidence; RGB receives alpha 255.

The fingerprint therefore survives irrelevant RGB-vs-RGBA container representation when normalized pixels and geometry are identical. It is not perceptual and makes no resize/crop/color-management/edit invariance claim.

### PCM audio

`pcm16-audio-exact:1` reuses the existing `audio_wav.decode_pcm16_wav` boundary. Canonical identity binds channel count, sample rate, frame count and exact interleaved PCM16 sample hash.

Ancillary RIFF chunks may change raw source bytes without changing the canonical PCM fingerprint. The algorithm is not an acoustic/perceptual fingerprint and makes no codec/resampling/edit invariance claim.

### GLB 3D

`glb-v2-validated-exact:1` reuses the existing independent `blockbench_glb.inspect_glb` Phase-20A truth layer.

The current GLB validator exposes the exact validated GLB file hash plus structural counts, not normalized geometry/buffer component hashes. Phase 28 therefore deliberately uses the **exact validated GLB bytes** as canonical identity and records structural summary evidence alongside it.

It explicitly does **not** claim invariance under mesh re-indexing, optimizer rewrites, coordinate transformations, JSON reserialization, or re-export through another DCC. A stronger structural/perceptual 3D fingerprint requires a future validator contract that exposes the required normalized component evidence.

## Comparison semantics

`FingerprintComparison` reports exactly one of:

- `EXACT_MATCH`
- `DIFFERENT`
- `INCOMPARABLE`

Two fingerprints are comparable only when their media class and full algorithm/canonicalizer identity match. There is no probabilistic confidence score in v1.

Before durable publication, comparison ID/hash bindings and the expected comparison classification are recomputed against both referenced fingerprint objects. A forged dataclass cannot persist a false `EXACT_MATCH` or `DIFFERENT` result merely by hashing itself consistently.

## PNG fragile metadata watermark

Phase 28 implements one format-safe derivative mark:

- media: validated truecolor PNG;
- private ancillary chunk: `ofWM`;
- robustness: `FRAGILE_METADATA`;
- mutation class: `METADATA_ONLY`;
- placement: immediately before `IEND`;
- maximum non-secret mark payload: 4096 bytes;
- duplicate private chunks: rejected;
- parent bytes and payload must match the exact frozen `WMPLAN-*` hashes.

Embedding never modifies the parent bytes in place. It returns new derivative bytes. The existing PNG validator independently accepts the resulting derivative, and the raster fingerprint test proves normalized pixel identity is unchanged.

The mark is deliberately classified as fragile. Re-encoding/export may remove it; an attacker may copy, remove, or forge it. Presence therefore establishes only that the expected private payload hash is present under this detector contract.

## Independent detector evidence

The embedder does not certify mark presence. `detect_png_fragile_metadata` is a separate invocation that:

1. validates the complete derivative through the existing PNG validator;
2. locates the private Phase-28 ancillary chunk;
3. rejects ambiguous duplicate chunks and oversized observed payloads;
4. hashes the observed payload;
5. emits `WMRES-*` evidence with `DETECTED`, `NOT_DETECTED`, or `MISMATCH`.

Durable watermark-result publication revalidates the exact plan/detector binding and recomputes whether the status is consistent with the planned payload hash.

Every watermark result explicitly records false for authorship proof, cryptographic provenance verification, parent-lineage verification, canonical adoption and production Task verification.

## Phase-18 provenance linkage

`FPLINK-*` provides an explicit supplementary link to a `ProvenanceManifest` only when:

- fingerprint `source_ref` equals the manifest Artifact ID; and
- fingerprint raw `source_hash` equals the manifest `artifact_content_hash`.

Publication revalidates the exact fingerprint, manifest and Artifact bindings.

Phase 28 does **not** verify the manifest's Ed25519 signature. Link evidence therefore states:

- `phase18_manifest_bound = true`;
- `phase18_signature_verified = false`;
- `cryptographic_provenance_verified = false`.

Signature/certificate/revocation verification remains exclusively in the Phase-18 provenance authority surface.

## Durable evidence store

`.origin-forge/media-fingerprints/` contains bounded immutable categories for:

- fingerprints;
- comparisons;
- watermark plans;
- watermark results;
- provenance links.

The store enforces:

- protected-root containment;
- symlink/alias rejection;
- no overwrite;
- object-count and byte limits;
- strict UTF-8 JSON and duplicate-key rejection;
- exact ID/category binding;
- canonical bytes and content-hash revalidation;
- referenced-evidence revalidation for comparison/result/link publication.

## Read-only operator surface

`python -m origin_forge.media_fingerprint_cli` exposes only:

- `status`;
- list commands for the five immutable evidence categories;
- corresponding `*-show` commands.

It has no fingerprint-computation, arbitrary-path hashing, watermark embedding/detection, key access, adoption, Task mutation, signing, merge or release command.

## Threat and authority boundary

Phase 28 explicitly rejects these interpretations:

- matching fingerprint or watermark proves authorship;
- missing watermark proves foreign origin;
- fingerprint equality equals a valid Phase-18 signature;
- a detected watermark proves parent lineage;
- a marked derivative is automatically canonical/adopted;
- a model may choose arbitrary embedder/detector executables;
- watermark/fingerprint evidence may verify or complete a production Task.

No arbitrary filesystem path hashing, external watermark process, secret-key persistence, automatic adoption/signing, Task completion, merge or release authority is added.

## v1 exit condition

Phase 28 v1 is complete when one immutable repository head proves on Python 3.12 and 3.13 that Origin Forge can:

1. create exact governed fingerprints for source text, validated raster pixels, canonical PCM16 audio and validated GLB bytes;
2. compare only identical algorithm/media classes with deterministic exact semantics;
3. persist/reconstruct bounded immutable fingerprint/comparison evidence;
4. create one derivative-only `FRAGILE_METADATA` PNG mark without changing normalized pixels;
5. independently detect that mark and preserve `DETECTED` / `NOT_DETECTED` / `MISMATCH` evidence without authorship claims;
6. bind a fingerprint to an exact Phase-18 manifest Artifact ID/content hash without taking signature-verification authority;
7. expose only read-only operator inspection; and
8. keep production Task/adoption/signing/merge/release authority unchanged.

Heuristic/perceptual fingerprints, transform-tolerant watermarking, keyed/secret watermark schemes and stronger GLB structural invariance remain future research and require measured evidence before any stronger claim is permitted.
