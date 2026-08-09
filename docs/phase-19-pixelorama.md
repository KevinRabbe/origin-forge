# Phase 19 — Pixelorama Integration

Status: **DONE — deterministic v0 media substrate and frozen real-editor export proof implemented**

Phase 19 adds the first deterministic 2D production tool integration to Origin Forge. Pixelorama remains the human-visible editor, but Origin Forge owns the automation contract, isolation, validation, evidence, and provenance around every machine-driven operation.

The central rule is:

```text
Pixelorama edits pixels/projects
Origin Forge owns task authority, input contracts, verification, and provenance
```

Phase 19 does **not** add image generation or vision critique. Those remain Phase 21. The v0 goal is deterministic, inspectable 2D production infrastructure with the smallest independently proven real-editor surface.

---

## 1. Upstream integration boundary

Pixelorama is an open-source Godot-based pixel-art editor with an official extension system. Phase 19 integrates through the smallest versioned upstream-supported boundary rather than screen-coordinate GUI macros.

For Pixelorama v1.2, the desktop CLI provides a supported headless export surface. Its exact application runtime version is `v1.2-stable`; the v1.2 project declares Extensions API version `9` and `.pxo` format version `7`. The initial real-editor proof therefore targets opaque `.pxo` input plus the documented CLI export path. Extension API 9 project construction/save remains a separate later boundary and must not be assumed equivalent to the CLI export proof.

Origin Forge does not depend on undocumented internal `.pxo` byte layout or simulated mouse/keyboard automation.

If a later installed Pixelorama build does not expose a stable one-shot command-line editing API, a separately governed trusted bridge must become the explicit automation boundary.

```text
Origin Forge
  ↓ canonical bridge request
trusted Pixelorama bridge / documented CLI boundary
  ↓ Pixelorama editor APIs
isolated working project/assets
  ↓
bridge result + exported files
  ↓
Origin Forge deterministic validators
  ↓
Artifact / Verification / provenance
```

The bridge is a locally installed, versioned capability. Arbitrary downloaded extensions are not trusted or auto-enabled.

---

## 2. Fundamental rules

1. **No GUI macro authority.**
   Phase 19 does not use click coordinates, window focus, keyboard simulation, or screenshots as the mutation interface.

2. **No undocumented `.pxo` rewriting.**
   Origin Forge does not manufacture or patch Pixelorama project files by reverse-engineering private serialization.

3. **Bridge protocol is versioned and strict.**
   Every request/result uses exact fields, schema version, operation ID, input hashes, output paths, and bounded values.

4. **One bounded operation per invocation.**
   No persistent autonomous editor agent or hidden command queue.

5. **Workspace/temp isolation first.**
   Automated editing occurs only in an explicitly supplied isolated working directory. The adapter never writes arbitrary paths.

6. **Models never receive editor filesystem authority.**
   A model may later propose a structured sprite specification. Deterministic infrastructure validates it before any bridge call.

7. **Exports are revalidated by Origin Forge.**
   Pixelorama reporting success is not sufficient evidence. Origin Forge independently checks output file format, dimensions, frame geometry, hashes, and declared metadata.

8. **Existing live assets are immutable without a precondition.**
   Replacement/derivation requires an exact source hash or isolated-copy workflow.

9. **No network authority.**
   The adapter itself has no network/download surface. The separately reviewed opt-in evidence workflow may acquire frozen editor/fixture inputs before the adapter is invoked.

10. **No arbitrary extension execution.**
    Only configured trusted Pixelorama capability identities may be used.

11. **No model-generated GDScript execution.**
    Bridge scripts are shipped/governed infrastructure, not generated at runtime by an LLM.

12. **Provenance is first-class.**
    Source specification, bridge/editor version, input/output hashes, operation result, validators, and resulting Artifacts are captured.

---

## 3. Phase-19 v0 asset model

The initial deterministic data model is deliberately small.

### 3.1 Pixel color

```text
Rgba8
- r: 0..255
- g: 0..255
- b: 0..255
- a: 0..255
```

### 3.2 Raster layer

```text
RasterLayerSpec
- layer_id
- name
- visible
- opacity
- blend_mode
```

V0 supports a conservative known blend-mode surface rather than assuming arbitrary editor semantics.

### 3.3 Frame

```text
FrameSpec
- frame_id
- duration_ms
```

### 3.4 Animation tag

```text
AnimationSpec
- name
- first_frame
- last_frame
- loop_mode
- fps / frame durations
```

### 3.5 Sprite project specification

```text
SpriteProjectSpec
- schema_version
- width
- height
- layers[]
- frames[]
- animations[]
- palette[]
- background/transparency policy
- output basename
- content_hash
```

The specification does not contain arbitrary script text or arbitrary host paths.

---

## 4. Deterministic pixel payloads

Phase 19 includes a model-independent representation for exact raster content.

V0 supports canonical RGBA8 frame/layer payloads owned by Origin Forge:

```text
PixelPlane
- width
- height
- rgba_bytes_hash
- bounded RGBA bytes
```

For persistence/bridge exchange, large pixel payloads are referenced by exact local file/hash rather than duplicated through model prompts.

Origin Forge implements deterministic standard-library PNG handling for the bounded RGBA8 surface, preserving the repository's zero-runtime-dependency policy.

PNG validation is intentionally narrow and includes:

- PNG signature
- IHDR
- 8-bit RGBA truecolor with alpha
- non-interlaced data
- CRC validation
- bounded decompression
- standard row filters
- exact width/height
- strict chunk/trailing-data handling

Unsupported PNG modes fail closed rather than being silently converted.

---

## 5. Bridge request protocol

Each one-shot bridge request is immutable/canonical JSON.

```text
PixeloramaBridgeRequest
- protocol_version
- operation_id
- operation
- workspace_root
- project_input
- input_refs[]
- sprite_spec
- export_specs[]
- bridge_budget
- content_hash
```

The serialized request/provenance contract uses workspace-relative paths, not absolute arbitrary paths.

The broader bridge model recognizes bounded operations such as:

```text
CREATE_SPRITE_PROJECT
IMPORT_LAYER_PNG
SET_FRAME_DURATION
SET_ANIMATION
EXPORT_FRAME_PNG
EXPORT_SPRITESHEET
SAVE_PROJECT
```

The independently proven direct Pixelorama CLI v0 adapter exposes only `EXPORT_SPRITESHEET`. Unknown/disallowed operations fail closed.

No request field can contain:

- shell command
- GDScript source
- network URL to execute/fetch
- plugin install instruction
- unrestricted filesystem path
- Task/Verification status transition

---

## 6. Bridge result protocol

```text
PixeloramaBridgeResult
- protocol_version
- operation_id
- status
- pixelorama_version
- bridge_version
- input_hash
- outputs[]
- diagnostics[]
- elapsed_ms
- content_hash
```

Output refs contain:

```text
BridgeOutput
- output_type
- relative_path
- content_hash
- byte_count
- width / height when raster
```

Initial result statuses:

```text
SUCCEEDED
FAILED
BLOCKED
```

The bridge/editor result cannot mark an Origin Forge Task, Artifact, or Verification as successful.

---

## 7. Trusted bridge/editor identity

The generic bridge configuration pins governed identity and limits. The direct real-editor CLI profile independently pins:

```text
PixeloramaCliProfile
- pixelorama_executable
- pixelorama_fingerprint
- expected_pixelorama_version
- allowed_operations[]
- timeout_seconds
- max_stdout_bytes
- max_stderr_bytes
- max_executable_bytes
- max_runtime_bytes
```

The direct v1.2 CLI export proof pins executable SHA-256 and exact reported runtime version (`v1.2-stable`). The integration test does not derive its expected executable or fixture hash from the same files under test.

The adapter refuses:

- executable fingerprint mismatch
- wrong reported runtime version
- unsupported operation
- missing/non-regular executable
- timeout/resource/log bound violations

The editor/bridge is infrastructure, not a user-content extension marketplace.

---

## 8. Pixelorama process boundary

The process adapter:

- resolves an explicitly configured executable
- never invokes through a shell
- uses a bounded argument list
- uses a bounded isolated working directory
- redirects common user-data/config/cache locations into isolated runtime scratch
- pins `PWD` to the isolated media workspace for deterministic Pixelorama path handling
- enforces hard timeout
- bounds stdout/stderr while draining process pipes
- never infers success solely from process exit code
- rejects unexpected files outside the declared output set
- revalidates workspace roots and path components after editor execution so a replaced parent symlink cannot escape containment
- re-hashes and independently validates the resulting RGBA8 PNG

Request/provenance paths remain portable and workspace-relative. For the actual Pixelorama v1.2 process invocation, Origin Forge first resolves and validates the staged source and output parent inside the isolated `MEDIA-*` workspace, then passes infrastructure-derived **absolute contained paths** to Pixelorama. This is required because Pixelorama v1.2's export implementation requires an absolute export directory. It does not give callers arbitrary host-path authority.

The proven direct command shape is therefore conceptually:

```text
Pixelorama --headless --quit -- --spritesheet \
  --output <validated absolute MEDIA-*/exports/...png> \
  <validated absolute MEDIA-*/inputs/...pxo>
```

After editor exit, Origin Forge validates containment again, requires the declared output leaf to exist, rejects symlink/undeclared output behavior, and only then accepts structural media evidence.

---

## 9. Workspace containment

Automated Pixelorama work uses a dedicated operation directory:

```text
.origin-forge/media-workspaces/<MEDIA-ID>/
```

The direct CLI adapter owns:

```text
inputs/
exports/
runtime/
```

Rules:

- no symlink workspace roots
- no symlink path components
- request paths are portable and workspace-relative
- staged input must match exact frozen hash and byte count
- canonical live project files are never passed as writable inputs
- output set is enumerated and rehashed by Origin Forge
- workspace roots and declared paths are revalidated after editor execution
- runtime scratch is byte-bounded and symlink-checked

---

## 10. Validation engine for 2D assets

Deterministic validators cover at least:

### PNG integrity

- PNG signature/chunk CRC
- supported RGBA8 format
- width/height bounds
- decompression bounds
- exact expected dimensions
- no trailing malformed data

### Sprite/frame geometry

- frame count/geometry inputs
- frame width/height
- spritesheet divisibility/derived geometry
- animation index ranges
- animation duration bounds
- duplicate/invalid animation constraints

### Alpha/readability basics

Deterministic checks only:

- fully transparent output detection
- accidental fully opaque background when transparency is disallowed/required by contract
- empty-output/frame detection
- pixel/bounding geometry

Aesthetic quality remains Phase-21 Visual Critic territory.

Tile/seam-specific production remains a later bounded media capability rather than an unproven assumption in the v0 editor gate.

---

## 11. Artifact model

Useful media Artifact classes include:

```text
PIXELORAMA_PROJECT
PIXELORAMA_BRIDGE_REQUEST
PIXELORAMA_BRIDGE_RESULT
RASTER_SOURCE_PNG
RASTER_EXPORT_PNG
SPRITESHEET_EXPORT
PALETTE
```

The implemented media service persists request/result/output Artifacts and structural Verifications while keeping Pixelorama success advisory. Explicit governed adoption is separate from editor execution.

Phase-18 provenance integration proves an explicitly adopted PNG can enter the existing cryptographic provenance path without granting the media layer signing-key authority.

---

## 12. Tool and operator contracts

Phase 19 deliberately does **not** expose a generic model-facing media call surface.

Implemented operator surfaces are narrow:

- read-only `pixelorama status` installation/fingerprint inspection
- explicit create-only `adopt-new` administration for already verified media outputs

There is no ordinary operator/model create/export/run command in v0. The direct adapter is exercised through governed service/test paths.

Future tool descriptors may expose deterministic Pixelorama operations only after their specific editor boundary is separately implemented and measured.

---

## 13. Model boundary

Phase 19 is deterministic editor integration, not generative image intelligence.

A future model may propose a bounded sprite specification or asset request, but infrastructure must validate the contract before any editor call.

The model may not:

- emit executable editor script
- select arbitrary extension packages
- choose arbitrary host paths
- bypass operation allowlists
- declare visual correctness
- overwrite canonical live assets directly
- mark Tasks/Goals verified
- merge/release

Image generation and semantic/aesthetic vision critique remain Phase 21.

---

## 14. Human editing and round-trip behavior

Pixelorama remains a normal human editor.

Human-created `.pxo` projects may be used as source Artifacts, but Origin Forge treats the project file as opaque unless a trusted Pixelorama boundary opens it and reports structured metadata.

For automated modification in a future broader bridge:

```text
source project Artifact + exact hash
→ copy into isolated media workspace
→ trusted Pixelorama API edits copy
→ save new project Artifact through Pixelorama-owned serialization
→ export + validate
→ human review / later acceptance
```

The original project Artifact is never overwritten in place by the automation layer.

For Pixelorama v1.2, `OpenSave.save_pxo_file(...)` is a Pixelorama-owned save implementation. A future trusted Extension API 9 bridge may invoke that Pixelorama-owned path after constructing a project through supported editor APIs. Origin Forge still must not synthesize `.pxo` bytes itself. That broader create/import/save bridge remains deferred beyond the v0 direct export proof.

---

## 15. Failure semantics

Distinguish:

```text
BLOCKED
- Pixelorama unavailable
- trusted bridge/editor unavailable or identity mismatch
- unsupported editor version
- resource/platform requirement unavailable

FAILED
- malformed request/result
- editor/bridge operation error
- output missing/corrupt
- validation failure
- source hash mismatch
- undeclared output
- workspace/symlink containment violation
```

Infrastructure unavailability is not evidence that the sprite specification is semantically wrong.

---

## 16. Implemented Phase-19 closure

The repository now includes:

- bounded canonical media/project/frame/layer/animation/palette/pixel models
- deterministic standard-library RGBA8 PNG encoding, decoding, inspection, CRC/filter/decompression bounds
- strict bridge request/result protocols and pinned bridge profiles
- one-shot no-shell bounded bridge process isolation and fake-process adversarial coverage
- protected `MEDIA-*` workspaces and `PXOP-*` operation identities
- independent deterministic raster/spritesheet validators
- media Run service that persists Artifacts/Verifications without completing production Tasks
- explicit Task-authority regressions proving Pixelorama cannot change Task completion/revision/verification authority
- separation of editor execution from canonical project adoption
- create-only governed output adoption with non-overwrite/protected-root/source-drift rules
- read-only Pixelorama status inspection
- Phase-18 provenance integration for adopted raster output
- direct `PixeloramaCliExportAdapter` over Pixelorama v1.2's documented headless spritesheet export
- exact executable SHA/version pinning, frozen `.pxo` input hash/size, timeout/log/output/runtime limits
- infrastructure-derived absolute process paths after workspace-relative request validation
- post-process root/component/symlink containment revalidation
- opt-in supply-chain evidence workflow with independently anchored release archive identity
- a frozen real upstream `.pxo` fixture and a successful real Pixelorama v1.2 execution gate

Frozen real-editor evidence profile:

```text
Pixelorama release: v1.2
runtime version: v1.2-stable
Windows x64 release archive SHA-256:
  1ddc65930ddd435612519e293d1927849d4d4c18928a856b5bd4f058fe2f4a72
Pixelorama.exe SHA-256:
  07ee2defdbf14f335b8f102f224926cc1ef1456bd09f3af708e948ccadc3d904
upstream issue #1368 fixture SHA-256:
  c9d3eb48002d0a68ce718717588b3b43d785171f57dbb85a04e194481cb65fb2
fixture byte count: 1906
```

The compatibility probe succeeded in GitHub Actions run `31327381822`; after those identities were frozen as reviewed expected values, the authoritative rerun `31327454509` also succeeded at Origin Forge head `eb38cfaca5b11029b281b58145abad227393763c`.

The real-editor gate remains opt-in and supply-chain explicit. Normal CI does not download Pixelorama. See `docs/pixelorama-real-gate.md` for the exact evidence/acquisition contract.

### Exit condition met

Origin Forge can deterministically isolate and inspect 2D media operations, execute a pinned real Pixelorama v1.2 headless spritesheet export over an exact frozen real `.pxo` project, independently revalidate containment/output/hash/raster integrity, persist media evidence without transferring Task authority, and explicitly adopt verified new outputs without overwrite or signing authority.

Broader Pixelorama project creation/import/save, generic model-facing media tools, image generation, and visual/aesthetic critique remain future separately governed capabilities rather than prerequisites for Phase-19 v0 completion.
