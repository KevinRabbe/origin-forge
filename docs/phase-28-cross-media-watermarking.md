# Phase 28 — Cross-Media Watermarking and Fingerprinting

Status: **IN PROGRESS — fingerprint-first provenance supplement**

Phase 28 adds deterministic cross-media fingerprints and explicitly classified watermark evidence without weakening Phase-18 cryptographic provenance.

## Core rule

```text
cryptographic provenance = trust root
fingerprint / watermark  = supplementary evidence
```

A fingerprint or embedded mark can help correlate, detect drift, or recover likely origin after ordinary transformations. It never proves authorship by itself, never replaces an exact Artifact hash/signature, and never grants Task/adoption/signing/merge/release authority.

## Why fingerprint-first

“Watermarking” spans very different guarantees:

- exact cryptographic hashes detect any byte change but do not survive transformations;
- canonical-content fingerprints can ignore irrelevant container differences while remaining exact over normalized content;
- perceptual/structural fingerprints may tolerate some transformations but can collide and must be treated as heuristic evidence;
- embedded marks may be fragile, lossy, removable, forgeable, or format/tool dependent.

Origin Forge therefore does not expose one misleading `watermark_verified = true` bit. Every evidence object states the exact fingerprint/mark algorithm, version, canonicalization boundary and confidence/robustness class.

## v1 media classes

Phase 28 v1 targets four media classes already governed elsewhere:

- `SOURCE_TEXT`
- `RASTER_IMAGE`
- `PCM_AUDIO`
- `MODEL3D_GLB`

The implementation reuses existing canonical validators where available rather than building a second parser/truth layer.

## Fingerprint envelope

A `MediaFingerprint` binds:

- infrastructure-owned fingerprint ID;
- media class;
- exact source Artifact/reference ID and SHA-256;
- exact algorithm ID/version;
- exact canonicalizer/validator identity;
- canonical-content SHA-256;
- optional bounded supplementary feature hashes;
- deterministic structural summary needed to interpret the fingerprint;
- explicit comparison semantics;
- `cryptographic_provenance_verified = false`.

Fingerprints are immutable, content-addressed evidence. Recomputing a fingerprint over different source bytes creates new evidence; it does not update the old record.

## Initial fingerprint algorithms

### Source text

v1 source fingerprinting is intentionally exact after a narrow UTF-8 text canonicalization:

- UTF-8 only;
- no NUL/control ambiguity;
- normalized line endings (`CRLF` / `CR` → `LF`);
- no trimming, comment deletion, whitespace folding or semantic parsing.

This gives a container-normalized text hash without pretending to survive refactors.

### Raster image

v1 uses the existing independent raster/PNG validation path to derive exact normalized pixel evidence. The primary fingerprint is an exact hash over dimensions + canonical RGBA8 pixel bytes.

A later perceptual image fingerprint may be added only as a separately labeled heuristic algorithm with measured false-match behavior. It must never replace the exact normalized-pixel hash.

### PCM audio

v1 uses the existing canonical PCM16 RIFF/WAVE boundary. The primary fingerprint is an exact hash over sample rate/channel count/frame count + canonical interleaved PCM16 sample bytes.

A later robust/acoustic fingerprint may be added only as separately classified heuristic evidence and only after measured collision/transformation tests.

### GLB 3D

v1 consumes independently validated GLB v2 evidence. The primary structural fingerprint is derived from a deterministic normalized summary of the accepted GLB structure plus exact hashes of geometry/buffer payload evidence used by that summary.

It does not claim invariance under mesh re-indexing, optimizer rewrites, coordinate transformations, or re-export through another DCC unless a future algorithm explicitly proves/test those invariances.

## Comparison result

`FingerprintComparison` reports one of:

- `EXACT_MATCH`
- `DIFFERENT`
- `INCOMPARABLE`

v1 exact algorithms do not expose probabilistic confidence. A future heuristic algorithm must use a separate result type/score contract rather than overloading exact equality.

## Embedded watermark contract

Phase 28 also defines an explicit derivative-mark boundary even before every media class has an approved embedder.

A `WatermarkPlan` binds:

- exact parent Artifact/source hash;
- mark payload hash, never secret material;
- media class;
- exact embedder ID/version/fingerprint;
- robustness class;
- declared expected content mutation;
- output constraints;
- independent detector/validator ID/version/fingerprint.

Robustness classes are descriptive, not trust levels:

- `FRAGILE_METADATA` — likely removed by re-encoding/export;
- `FRAGILE_CONTENT` — embedded in content but not designed to survive material edits;
- `TRANSFORM_TOLERANT_EXPERIMENTAL` — only after measured transformation evidence.

No v1 embedder may label itself “robust” or “provenance-secure”.

## Derivative-only mutation

Embedding never mutates an accepted canonical Artifact in place.

```text
verified parent artifact
        ↓
new isolated derivative workspace
        ↓
format-specific bounded embedder
        ↓
independent format validation
        ↓
independent mark detection
        ↓
new derivative Artifact evidence
        ↓
optional later create-only adoption/signing through existing governance
```

The parent hash remains immutable. The derivative is a new Artifact/evidence object with explicit parent lineage.

## Detector separation

The embedder may not self-certify success. A watermark result requires an independently invoked detector/validator contract over the produced bytes.

For deterministic fragile marks, detection can establish only that the declared mark is present under the specific algorithm—not who created it and not whether the media is otherwise semantically correct.

## Secret material

Phase 28 v1 does not store secret signing keys or watermark secrets in media evidence. Phase-18 provenance key handling remains separate.

If a future keyed watermark is evaluated, the durable record may contain key/certificate references and non-secret algorithm evidence but never raw private key material.

## Persistence and operator surface

Fingerprint/mark evidence must be immutable, bounded, symlink/root-contained, content-addressed and read-only inspectable. The CLI may compute/inspect only through explicitly governed adapters; it must not become a generic file hashing or arbitrary-path surface.

## Threat and interpretation boundary

Phase 28 explicitly rejects these claims:

- “matching watermark proves authorship”;
- “missing watermark proves foreign origin”;
- “fingerprint match is equivalent to a valid Phase-18 signature”;
- “watermarked derivative is automatically adopted/canonical”;
- “the model may choose an arbitrary embedder/detector executable”;
- “watermark evidence may complete/verify a production Task”.

Attackers may copy, strip or forge non-cryptographic marks. Therefore Phase-18 signatures/manifests and exact causal lineage remain authoritative.

## Initial implementation checkpoints

1. immutable IDs/models for fingerprint specification/result/comparison and watermark plan/result;
2. deterministic source-text fingerprint adapter;
3. exact raster fingerprint adapter reusing independent validated pixel evidence;
4. exact PCM16 fingerprint adapter reusing canonical WAV evidence;
5. exact GLB structural fingerprint adapter reusing independent GLB validation;
6. immutable bounded fingerprint persistence and read-only inspection;
7. at least one derivative-only fragile watermark embedder + independent detector, if a format-safe implementation can be proven without weakening existing validators;
8. adversarial tests for source/hash drift, media-type mismatch, malformed input, symlink/path escape, algorithm/version drift and forged detector evidence;
9. explicit Phase-18 linkage proving fingerprint/watermark evidence remains supplementary;
10. exact-head Python 3.12/3.13 closure CI with unrelated heavyweight evidence gates skipped.

## Explicit v1 exclusions

Not authorized:

- replacing Phase-18 signatures/manifests;
- claiming forensic/robust watermark guarantees without measured evidence;
- in-place canonical Artifact mutation;
- arbitrary external watermark executables;
- arbitrary path/file hashing exposed to a model;
- secret-key persistence in media evidence;
- automatic adoption/signing;
- production Task verification/completion;
- merge/release authority.

## Exit condition

Phase 28 v1 is complete when one immutable repository head proves that Origin Forge can create and compare deterministic media-class-specific fingerprints over existing governed canonical media boundaries, persist/reconstruct the evidence, optionally create at least one independently detected derivative fragile mark if safely supported, and keep all such evidence subordinate to exact Artifact hashes, Phase-18 cryptographic provenance and existing adoption/signing/Task authority.
