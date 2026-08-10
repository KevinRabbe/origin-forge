# Phase 20C — Governed Blender Backend

Status: **IN PROGRESS**

Phase 20C adds Blender as a replaceable backend behind the already-merged Phase-20A editor-independent 3D contracts and independent GLB validation layer.

## Core rule

```text
canonical bounded 3D spec
→ governed Blender job
→ frozen infrastructure-owned runner
→ pinned isolated Blender runtime
→ declared GLB output
→ independent Origin Forge GLB validation
```

Blender is an execution backend, not 3D truth and not production authority.

## Initial upstream target

The initial runtime target is Blender **5.2.0 LTS**. The official `blender/blender` mirror contains exact tag `v5.2.0` at commit `fbe6228777e7d9afefcd61a413844e790ae75db7`; the release header identifies version 5.2.0, release cycle `release`, suffix `LTS`.

The tagged source also contains the official bundled glTF 2.0 exporter for Blender 5.2.0. No external glTF add-on is installed by Origin Forge.

Before final real-runtime evidence, the acquisition workflow must independently pin the reviewed Blender distribution/source identity and materialized runtime hash. A newer authoritative 5.2.x release may replace this initial target only through an explicit reviewed profile change.

## v1 operation surface

The first trusted runner intentionally supports only:

```text
unrigged
untextured
unanimated
visible
axis-aligned
non-inflated cuboids
→ one self-contained GLB
```

This is narrower than the canonical Phase-20A project contract. Unsupported bones, parented cuboids, rotations, textures, UV controls, animations, hidden cuboids, and inflation fail closed rather than being silently ignored.

The narrow first slice is deliberate: it proves a real deterministic Blender execution boundary before adding semantic mapping for hierarchy, armatures, materials, animation, rendering, or more advanced geometry.

## Identity and replay

A `BlenderJobRequest` freezes:

- infrastructure-owned `BLOP-*` operation ID;
- infrastructure-owned `MODEL3D-*` workspace ID;
- exact canonical 3D project and project hash;
- exact declared `exports/*.glb` path;
- exact Blender runtime-tree hash;
- exact expected Blender version line;
- exact frozen runner SHA-256;
- timeout/log/output budgets.

The runner itself is repository-owned fixed source. The model/caller cannot supply Python source, expressions, add-ons, modules, host paths, shell commands, or arbitrary Blender CLI tokens.

## Process boundary

The host adapter invokes only infrastructure-owned argv equivalent to:

```text
blender
  --background
  --factory-startup
  --disable-autoexec
  --offline-mode
  --python-exit-code 97
  --python <fingerprinted staged runner_v1.py>
  --
  --workspace <isolated MODEL3D workspace>
  --request <canonical request.json>
  --output <declared contained GLB>
  --result <contained result.json>
```

`--disable-autoexec` protects against automatic script execution from Blender data; explicit `--python` execution is reserved for the exact Origin Forge runner whose bytes are bound by the request/profile fingerprint.

The process receives an isolated HOME/XDG/cache/temp environment and no Origin Forge `PYTHONPATH`/system Python opt-in. Network access is disabled at Blender's own runtime policy level through `--offline-mode`. No external `.blend` file is loaded in v1.

## Independent acceptance

Blender exit code 0 and the trusted runner result remain process evidence only. After Blender exits, Origin Forge independently requires:

- workspace roots remain contained and non-symlinked;
- runner result is strict UTF-8 JSON with exact request/project/version binding;
- exports contain exactly the one frozen path;
- the declared output and path components are non-symlink regular files;
- output bytes remain within the request budget;
- `inspect_glb()` accepts the output as self-contained GLB v2/glTF 2.0 evidence.

The adapter itself creates no durable Task verification, Task completion, adoption, merge, signing, or release authority.

## Frozen runner constraints

`blender_runner_v1.py` is a standalone Blender Python program with a deliberately tiny import surface. Normal CI parses its source without importing `bpy` and verifies there is no dynamic `exec`/`eval`/`compile`/`__import__`, subprocess/network library, dynamic module loader, caller code, or add-on loading surface.

Runner v1 clears the factory scene, constructs deterministic cuboid mesh vertices/faces from frozen numeric data, and calls Blender's bundled official glTF exporter with explicit GLB/no-animation/no-camera/no-light/no-material/no-compression settings.

## Deferred expansions

After the real v1 Blender gate is green, later runner-schema revisions may add separately tested:

- parent hierarchy and bone/armature mapping;
- animations/keyframes;
- reviewed textures/materials/UVs;
- deterministic preview PNG rendering;
- `.blend` persistence only if a governed use case requires it;
- additional canonical geometry primitives.

Each expansion must retain structured data input and frozen infrastructure runner code. Model-generated arbitrary Blender Python is not part of the production authority model.

## Authority exclusions

Phase 20C may not:

- accept caller/model-supplied Python or shell code;
- enable arbitrary add-ons/extensions;
- enable online mode or perform runtime downloads;
- load arbitrary host paths;
- treat Blender process success as verification truth;
- complete/verify Tasks or Goals;
- adopt/overwrite canonical project assets automatically;
- sign protected provenance;
- merge or release.

## Exit condition

Phase 20C is complete when:

- the bounded request/runner/adapter boundary is exact-head green on normal CI;
- one reviewed Blender 5.2.x runtime identity is frozen with exact immutable evidence;
- a real pinned Blender process constructs the frozen v1 cuboid scene and exports one self-contained GLB through the trusted runner;
- Origin Forge independently validates the output hash/container/graph structure on the same exact PR head;
- the real execution produces evidence only and does not gain production Task/adoption/merge/release authority.
