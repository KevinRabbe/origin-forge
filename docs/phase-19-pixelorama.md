# Phase 19 — Pixelorama Integration

Status: **implementation starting after Phase 18**

Phase 19 adds the first deterministic 2D production tool integration to Origin Forge. Pixelorama remains the human-visible editor, but Origin Forge owns the automation contract, isolation, validation, evidence, and provenance around every machine-driven operation.

The central rule is:

```text
Pixelorama edits pixels/projects
Origin Forge owns task authority, input contracts, verification, and provenance
```

Phase 19 does **not** add image generation or vision critique. Those remain Phase 21. The first goal is deterministic, inspectable 2D production.

---

## 1. Upstream integration boundary

Pixelorama is an open-source Godot-based pixel-art editor with an official extension system. Phase 19 should integrate through the smallest versioned upstream-supported boundary rather than screen-coordinate GUI macros.

For Pixelorama v1.2, the desktop CLI provides a supported headless export surface. Its exact application runtime version is `v1.2-stable`; the v1.2 project declares Extensions API version `9` and `.pxo` format version `7`. The initial real-editor proof therefore targets opaque `.pxo` input plus the documented CLI export path. Extension API 9 project construction/save remains a separate later boundary and must not be assumed equivalent to the CLI export proof.

Origin Forge must not depend on undocumented internal `.pxo` byte layout or simulated mouse/keyboard automation.

If an installed Pixelorama build does not expose a stable one-shot command-line editing API, the trusted bridge becomes the explicit automation boundary.

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

9. **No network.**
   Pixelorama automation is local and should not require network access.

10. **No arbitrary extension execution.**
    Only the configured trusted Origin Forge Pixelorama bridge ID/version/fingerprint may be used.

11. **No model-generated GDScript execution.**
    Bridge scripts are shipped/governed infrastructure, not generated at runtime by an LLM.

12. **Provenance is first-class.**
    Source specification, bridge version, Pixelorama version, input/output hashes, operation result, validators, and resulting Artifacts are captured.

---

## 3. Phase-19 v0 asset model

The initial deterministic data model should be deliberately small.

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

V0 should support only a conservative known blend-mode subset, initially `NORMAL` unless Pixelorama bridge support is independently proven for more.

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

Phase 19 needs a model-independent way to represent exact raster content.

V0 should support canonical RGBA8 frame/layer payloads owned by Origin Forge:

```text
PixelPlane
- width
- height
- rgba_bytes_hash
- bounded RGBA bytes
```

For persistence/bridge exchange, large pixel payloads should be referenced by exact local file/hash rather than duplicated through model prompts.

Origin Forge may implement a minimal deterministic PNG encoder/decoder/validator in Python standard library for bounded RGBA8 assets, preserving the repository's zero-runtime-dependency policy.

PNG support should be intentionally narrow:

- PNG signature
- IHDR
- 8-bit RGBA truecolor with alpha
- non-interlaced
- deterministic filter strategy for Origin Forge-generated files
- CRC validation
- bounded decompression
- exact width/height

Unsupported PNG modes fail closed rather than being silently converted.

---

## 5. Bridge request protocol

Each one-shot request is immutable/canonical JSON.

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

The actual serialized request should use workspace-relative paths, not absolute arbitrary paths.

Initial operations:

```text
CREATE_SPRITE_PROJECT
IMPORT_LAYER_PNG
SET_FRAME_DURATION
SET_ANIMATION
EXPORT_FRAME_PNG
EXPORT_SPRITESHEET
SAVE_PROJECT
```

V0 may implement a smaller subset first, but unknown operation strings always fail closed.

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

The bridge result cannot mark an Origin Forge Task, Artifact, or Verification as successful.

---

## 7. Trusted bridge identity

The adapter configuration should pin:

```text
PixeloramaBridgeProfile
- bridge_id
- protocol_version
- bridge_version
- bridge_fingerprint
- pixelorama_executable
- allowed_operations[]
- timeout_seconds
- max_input_bytes
- max_output_bytes
```

The fingerprint covers the governed bridge package/source that Origin Forge expects.

The adapter refuses:

- unknown bridge version
- fingerprint mismatch
- unsupported protocol version
- bridge outside configured install location where containment policy requires otherwise
- missing executable

The bridge is infrastructure code, not a user-content extension marketplace.

For the direct v1.2 CLI export proof, executable SHA-256 and exact reported runtime version (`v1.2-stable`) are independent external pins. The integration test must not derive its expected executable or fixture hash from the same files under test.

---

## 8. Pixelorama process boundary

The process adapter must:

- resolve an explicitly configured executable
- never invoke through a shell
- use a bounded argument list
- use a bounded isolated working directory
- set explicit bridge request/result paths
- enforce hard timeout
- bound stdout/stderr
- never infer success solely from process exit code
- require a valid bridge result matching the request operation ID/hash
- reject unexpected files outside declared output set
- revalidate workspace roots and path components after editor execution so a replaced parent symlink cannot escape containment

If the official editor/bridge requires a GUI display, the process contract may still be deterministic; hidden UI interaction must not become part of the API.

A future headless route may be added only if it is supported reliably by Pixelorama/Godot and passes integration tests. Pixelorama v1.2's documented desktop CLI already provides a headless export route; that narrower export route is the first real-editor proof target.

---

## 9. Workspace containment

Automated Pixelorama work uses a dedicated operation directory such as:

```text
.origin-forge/media-workspaces/<MEDIA-ID>/
```

or an equivalent isolated external temporary workspace managed by Origin Forge.

Within the operation directory:

```text
request.json
inputs/
project/
exports/
result.json
```

Rules:

- no symlink components
- all paths portable and workspace-relative
- bridge may read declared inputs only
- bridge may write declared project/export locations only
- canonical live project files are not passed as writable inputs
- output set is enumerated and rehashed by Origin Forge

---

## 10. Validation engine for 2D assets

Deterministic validators should cover at least:

### PNG integrity

- PNG signature/chunk CRC
- supported RGBA8 format
- width/height bounds
- decompression bounds
- exact expected dimensions
- no trailing malformed data

### Sprite/frame geometry

- frame count
- frame width/height
- spritesheet divisibility
- animation index ranges
- animation duration bounds
- no duplicate animation names

### Alpha/readability basics

Deterministic checks only:

- fully transparent output detection
- accidental fully opaque background when transparency required
- empty frame detection
- pixel count / bounding box

Aesthetic quality remains Phase-21 Visual Critic territory.

### Tile/seam validation later in Phase 19

For tileable assets:

- declared tile dimensions
- sheet divisibility
- edge equality checks where exact seamless tiling is required
- transparent padding rules

---

## 11. Artifact model

Useful Artifact types:

```text
PIXELORAMA_PROJECT
PIXELORAMA_BRIDGE_REQUEST
PIXELORAMA_BRIDGE_RESULT
RASTER_SOURCE_PNG
RASTER_EXPORT_PNG
SPRITESHEET_EXPORT
PALETTE
```

Each resulting Artifact records:

- parent/source Artifact when applicable
- creating Run
- Pixelorama tool version
- bridge version/fingerprint
- source spec hash
- output hash
- validator Verification IDs

Phase-18 signed provenance can then sign accepted exported 2D Artifacts without any media-specific change to the trust hierarchy.

---

## 12. Tool contracts

Phase 19 should eventually register deterministic media tools such as:

```text
pixelorama.create_project
pixelorama.import_layer
pixelorama.set_animation
pixelorama.export_frame
pixelorama.export_spritesheet
pixelorama.save_project
pixelorama.inspect
```

However, Tool Registry exposure comes only after the adapter is independently proven.

Initial implementation should call the adapter directly from tests/operator code, not grant a generic model-facing call surface immediately.

Tool descriptors should declare:

- local Pixelorama side effect
- reversible through isolated workspace
- resource requirements
- timeout
- verifier
- allowed path scope

---

## 13. Model boundary

Phase 19 is deterministic editor integration, not generative image intelligence.

Allowed future model role:

```text
human/model proposes bounded SpriteProjectSpec or high-level asset request
        ↓
infrastructure validates contract
        ↓
deterministic Pixelorama tools create/edit/export
        ↓
independent validators
```

The model may not:

- emit executable editor script
- select arbitrary extension packages
- choose arbitrary host paths
- bypass bridge operation allowlist
- declare visual correctness
- overwrite canonical live assets directly

---

## 14. Human editing and round-trip behavior

Pixelorama remains useful as a normal human editor.

Human-created `.pxo` projects may be imported as source Artifacts, but Origin Forge should treat the project file as opaque unless the trusted bridge opens it and reports structured metadata.

For automated modification:

```text
source project Artifact + exact hash
→ copy into isolated media workspace
→ bridge opens/modifies copy
→ save new project Artifact
→ export + validate
→ human review / later acceptance
```

The original project Artifact is never overwritten in place by the automation layer.

For Pixelorama v1.2, `OpenSave.save_pxo_file(...)` is a Pixelorama-owned save implementation. A future trusted Extension API 9 bridge may invoke that Pixelorama-owned path after constructing a project through supported editor APIs. Origin Forge still must not synthesize `.pxo` bytes itself, and this broader creation/save path remains deferred until the direct real-editor CLI export gate is proven.

---

## 15. Failure semantics

Distinguish:

```text
BLOCKED
- Pixelorama unavailable
- trusted bridge unavailable/mismatch
- unsupported editor version
- display/backend requirement unavailable
- resource contention

FAILED
- malformed request/result
- editor/bridge operation error
- output missing/corrupt
- validation failure
- source hash mismatch
- undeclared output
```

Infrastructure unavailability is not evidence that the sprite specification is semantically wrong.
