# Phase 20 — Blockbench Integration

Status: **IN PROGRESS — deterministic 3D substrate implemented; real-editor automation blocked on a supported non-interactive plugin bootstrap**

Phase 20 adds the first deterministic 3D production boundary to Origin Forge. Blockbench remains the human-visible editor, while Origin Forge owns canonical project intent, isolation, evidence, independent structural validation, provenance, and production authority.

The central rule is:

```text
Blockbench edits/exports 3D content
Origin Forge owns task authority, exact inputs, validation, and provenance
```

Phase 20 does not synthesize Blockbench's internal `.bbmodel` representation and does not use GUI-coordinate automation.

---

## 1. Verified upstream target

The Phase-20 target is Blockbench `v5.1.4`.

Upstream-supported surfaces relevant to Origin Forge include:

- JavaScript plugins registered with `Plugin.register(...)`
- the Blockbench object/API model for cubes, groups/outliner hierarchy, pivots, rotations, textures, animations, codecs, and file writing
- standardized model export formats including glTF/GLB
- desktop startup with an isolated `--userData <path>` directory
- opening supported model files at startup

The v5.1.4 desktop package is an Electron application. It does not expose a documented headless create/edit/export command surface comparable to Pixelorama's Phase-19 CLI export path.

Blockbench's own `.bbmodel` documentation treats the format as an internal project representation that may receive breaking changes and recommends integrations use a custom plugin/format when stable programmatic behavior is required. Origin Forge therefore treats `.bbmodel` as Blockbench-owned and does not serialize it independently.

Primary upstream evidence used for this phase is pinned to Blockbench tag `v5.1.4`, including:

```text
package.json
electron/main.js
js/desktop.js
js/plugin_loader.ts
js/util/state_memory.ts
```

and the official Blockbench plugin, URL-parameter, format, and API documentation.

---

## 2. Implemented deterministic project contract

Origin Forge now owns an editor-independent bounded 3D specification:

```text
BlockbenchProjectSpec
- project_name
- bones[]
- cuboids[]
- textures[]
- animations[]
- content_hash
```

### Bones

```text
BoneSpec
- bone_id
- name
- pivot
- rotation
- parent_bone_id
```

Infrastructure validates:

- bounded identity/name fields
- finite coordinates
- parent references
- no self-parent
- no hierarchy cycles
- deterministic ordering

### Cuboids

```text
CuboidSpec
- element_id
- name
- from_point
- to_point
- origin
- rotation
- parent_bone_id
- inflate
- uv_offset
- mirror_uv
- visible
```

The v0 geometry surface intentionally maps onto the conservative Blockbench cube/cuboid model rather than attempting arbitrary mesh topology before a real editor bridge exists.

### Textures

```text
TextureRef
- texture_id
- inputs/textures/<name>.png
- exact SHA-256
- exact byte count
- exact dimensions
```

Texture references remain exact and workspace-relative. They do not contain URLs or arbitrary host paths.

### Animation

```text
AnimationSpec
- animation_id
- name
- length_seconds
- loop_mode
- keyframes[]
```

```text
KeyframeSpec
- bone_id
- time_seconds
- channel: POSITION | ROTATION | SCALE
- value
- interpolation: LINEAR | STEP
```

Infrastructure validates exact bone references, bounded durations, duplicate bone/time/channel keys, and deterministic keyframe ordering.

---

## 3. Infrastructure identity

Phase 20 adds infrastructure-owned IDs:

```text
MODEL3D-<UUID>   isolated 3D workspace
BBOP-<UUID>      one Blockbench bridge operation
```

Models/plugins cannot choose or redefine these identities.

---

## 4. Strict bridge request

The implemented request protocol is content-addressed and bounded:

```text
BlockbenchBridgeRequest
- protocol_version
- operation_id
- workspace_id
- operation
- project
- project_hash
- output_relative_path
- bridge_fingerprint
- expected_blockbench_version
- budget
- content_hash
```

Recognized v0 operation classes are deliberately small:

```text
CREATE_PROJECT
EXPORT_GLB
SAVE_PROJECT
```

A future real Blockbench bridge may initially expose a smaller allowlist than this model. Merely recognizing an operation in the schema does not authorize editor execution.

Request paths are portable and workspace-relative. The request cannot contain:

- shell commands
- arbitrary JavaScript/GDScript
- arbitrary host filesystem paths
- plugin install/download instructions
- network URLs
- Task/Goal/Verification transitions
- merge/release/signing authority

---

## 5. Strict bridge result

The implemented result protocol is separate from production truth:

```text
BlockbenchBridgeResult
- operation_id
- workspace_id
- request_hash
- status
- blockbench_version
- bridge_fingerprint
- outputs[]
- diagnostics[]
- content_hash
```

Result statuses:

```text
SUCCEEDED
FAILED
BLOCKED
```

Output types currently modeled:

```text
GLB
BLOCKBENCH_PROJECT
PREVIEW_PNG
```

Strict parsing rejects unknown fields, including attempted production-authority fields. A successful result must bind the exact request operation/workspace/hash/fingerprint/version and the exact declared output path.

---

## 6. One-shot governed bridge process

`BlockbenchBridgeAdapter` implements an editor-neutral one-shot process boundary for the eventual trusted Blockbench launcher/plugin bridge.

Each invocation receives a fresh protected workspace:

```text
.origin-forge/model3d-workspaces/<MODEL3D-ID>/
├── request/
├── inputs/
├── exports/
└── runtime/
```

The adapter:

- verifies the configured bridge executable SHA-256 before launch
- requires the request's bridge fingerprint and expected Blockbench version to match the configured profile
- invokes without a shell
- writes one canonical request file
- passes only absolute infrastructure-derived request/result paths
- redirects HOME/PWD/XDG/APPDATA/LOCALAPPDATA into isolated runtime state
- applies hard timeout and bounded stdout/stderr retention
- requires a strict UTF-8 JSON result
- rebinds the result to the exact request
- requires actual export files to equal the declared output set
- independently rehashes every output
- independently reinspects GLB output
- rejects symlink/root containment violations
- bounds runtime scratch
- rejects undeclared top-level workspace entries

The bridge process is not itself trusted to verify production completion.

---

## 7. Independent GLB/glTF structural evidence

Phase 20 implements a standard-library GLB v2 inspector so editor success is never the only evidence.

The inspector validates:

- `glTF` GLB magic
- GLB version exactly 2
- exact declared file length
- four-byte chunk alignment
- JSON first and optional BIN second
- bounded UTF-8 JSON
- glTF `asset.version == "2.0"`
- bounded scenes/nodes/meshes/accessors/bufferViews/buffers/materials/textures/images/skins/animations
- scene→node references
- node→mesh/skin references
- child references, duplicate children, self-parenting, and hierarchy cycles
- mesh primitive POSITION attributes and accessor/material/index references
- accessor and buffer-view references/counts
- embedded BIN bounds
- image/texture/sampler references
- skin joints/skeleton/inverse-bind references
- animation sampler input/output accessors
- animation channel sampler/target node/path references
- supported interpolation identifiers

For the initial evidence surface, external glTF buffer/image URIs are rejected. Evidence must be self-contained in the GLB or use embedded `data:` URIs where explicitly supported.

This layer is independent of Blockbench and remains useful even if the editor bridge changes later.

---

## 8. Why GLB is the first acceptance format

Blockbench can export standardized 3D formats. For Origin Forge's initial independent validation target, GLB/glTF is preferable to OBJ because it can preserve hierarchy/pivots and animation semantics that OBJ cannot represent.

The first real-editor Phase-20 gate should therefore prove at least:

```text
frozen BlockbenchProjectSpec
        ↓
pinned governed local bridge
        ↓ supported Blockbench plugin/API
pinned Blockbench v5.1.4
        ↓
self-contained exports/model.glb
        ↓
exact hash + independent GLB graph validation
        ↓
advisory 3D evidence only
```

A `.bbmodel` output, if later required for human round-trip editing, must be written by Blockbench itself through supported editor APIs rather than Origin Forge serialization.

---

## 9. Authority boundary

Neither the future Blockbench plugin nor the current process adapter may:

- verify or complete a Task/Goal
- mutate Task revision/status directly
- merge or release
- sign provenance
- install arbitrary plugins
- download editor extensions
- execute model-generated JavaScript
- access arbitrary host paths
- use unrestricted network access
- overwrite existing canonical assets without a separate governed adoption/precondition path

The model may eventually propose a bounded `BlockbenchProjectSpec`; infrastructure owns validation and all editor execution authority.

---

## 10. Real-editor bootstrap investigation

A supported programmable editor surface exists: Blockbench JavaScript plugins. The unresolved problem is **non-interactive bootstrap of a governed local plugin**.

What upstream v5.1.4 supports:

- plugin files can be loaded from the plugin UI
- local plugin files can be loaded by drag-and-drop
- store plugins can be installed through the Blockbench plugin UI
- web-app `plugins=` URL parameters prompt the user to install named store plugins
- the desktop app supports a custom `--userData` directory

What the v5.1.4 startup path does **not** provide in the documented/supported surface inspected for this phase:

- no `--plugin <local-file.js>` startup switch
- no documented headless create/edit/export CLI
- no non-interactive local-plugin URL/deep-link bootstrap
- no startup rule that auto-discovers arbitrary JavaScript files merely because they exist under the isolated `plugins/` directory

The implementation detail matters: Blockbench's startup plugin loader iterates its `installed_plugins` state. `StateMemory.installed_plugins` is persisted through browser `localStorage`. Therefore placing a governed plugin file in `<userData>/plugins/` alone is insufficient to make a clean Blockbench profile load it.

Origin Forge will **not** solve this by manufacturing Chromium/Electron private Local Storage / LevelDB state. That would couple the integration to an undocumented browser-storage representation rather than the supported Blockbench plugin contract.

Origin Forge will also not use mouse/keyboard/window-focus automation to click through plugin installation.

---

## 11. Current blocker

The real-editor Phase-20 gate is blocked on one upstream automation capability:

> A supported, non-interactive way to start Blockbench with an exact governed local plugin already loaded, or an equivalent supported headless programmatic edit/export entry point.

Any one of the following would unblock the next step:

1. Blockbench adds/supports a startup argument for a local plugin file or plugin directory.
2. Blockbench adds/supports a headless/scripted model creation/export command surface.
3. A separately reviewed Blockbench distribution strategy is approved in which the governed Origin Forge plugin is packaged/preinstalled through an upstream-supported installation mechanism and its full application/plugin identity is pinned before execution.
4. Upstream documents another non-interactive plugin bootstrap API that avoids private Electron/Chromium state and GUI automation.

Until one of those conditions exists, a fake bridge proves Origin Forge's isolation/protocol/validation contract but does **not** prove Blockbench itself can be driven reliably and supportably.

---

## 12. Implemented tests

Current Phase-20 tests cover:

- canonical project ordering/content addressing
- bounded cuboid/bone/animation semantics
- duplicate IDs/keyframes
- missing references and hierarchy cycles
- portable output paths
- strict result binding
- attempted authority/extra result fields
- GLB container/version/length/chunk ordering
- external URI rejection
- invalid mesh/node/animation references
- GLB hierarchy cycles
- bridge fingerprint mismatch before launch
- no-shell one-shot fake bridge execution
- exact export-set matching
- independent output hash/size verification
- independent GLB reinspection
- timeout handling
- adapter authority-surface regression

At head `771988777778aa00cf20ab3547b5338fd91ca07e`, GitHub Actions run `31328271620` completed successfully on Python 3.12 and Python 3.13. Python 3.13 executed 719 tests with the one ordinary Pixelorama external-evidence skip.

---

## 13. Exit condition not yet met

Phase 20 must remain open/draft until a real pinned Blockbench execution demonstrates that the governed bridge can construct/export a frozen exact project through supported Blockbench APIs and that Origin Forge independently validates the resulting GLB.

The deterministic substrate is implemented and green. The missing item is not an Origin Forge protocol or validator; it is the supported real-editor bootstrap described above.
