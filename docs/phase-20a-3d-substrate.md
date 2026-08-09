# Phase 20A — Editor-Independent 3D Substrate

Status: **DONE**

Phase 20A closes the editor-independent part of Origin Forge's first 3D production boundary. The real Blockbench editor bootstrap is deliberately separated into a deferred backend-specific follow-up rather than blocking later roadmap phases.

## Architectural decision

Origin Forge owns the 3D contract and independent evidence surface. Blockbench is one possible execution backend, not the definition of Origin Forge 3D production.

```text
bounded 3D project intent
        ↓
governed 3D adapter
        ↓
Blockbench / future editor / custom backend
        ↓
self-contained GLB
        ↓
Origin Forge independent structural validation
```

The completed substrate includes:

- infrastructure-owned `MODEL3D-*` workspace IDs and `BBOP-*` operation IDs;
- bounded immutable project contracts for bones/hierarchy, cuboids, pivots/rotations, UV offsets, exact texture refs, animations, and keyframes;
- deterministic ordering/content addressing with duplicate, missing-reference, numeric-bound, and hierarchy-cycle rejection;
- strict content-addressed bridge request/result protocols with exact request/version/fingerprint/output binding and no production-authority fields;
- protected one-shot no-shell bridge execution with pinned executable identity, isolated runtime state, hard timeout/log/output bounds, strict result JSON, exact export-set matching, output rehashing, symlink/root containment, and undeclared-entry rejection;
- independent standard-library GLB v2 / glTF 2.0 structural inspection, including graph references, embedded resource bounds, skins, hierarchy cycles, and animation sampler/target references;
- rejection of external glTF asset URIs in the initial evidence surface;
- adversarial fake-process integration coverage proving the Origin Forge isolation/protocol/validation boundary without claiming real editor execution.

## Authority boundary

Neither the adapter nor any later editor plugin may verify Tasks/Goals, mutate Task completion authority, merge/release, sign provenance, install arbitrary plugins, execute model-generated JavaScript, use arbitrary host paths, or overwrite existing canonical assets without a separate governed adoption/precondition path.

## Deferred Phase 20B — Real Blockbench Automation

Blockbench v5.1.4 exposes a supported JavaScript plugin/API surface, but the investigated desktop startup path does not expose a supported non-interactive bootstrap for an exact governed local side-loaded plugin and does not expose a documented headless create/edit/export CLI.

Phase 20B is therefore **DEFERRED**, not a dependency of Phase 21.

It may resume through any separately reviewed route that preserves the authority model, including:

1. an upstream-supported local-plugin startup argument or headless programmatic editor entry point;
2. a pinned distribution with the governed Origin Forge plugin preinstalled through a supported mechanism;
3. a narrowly maintained Blockbench patch/fork that exposes a deterministic bootstrap, if the maintenance cost is justified;
4. another 3D backend implementing the same Origin Forge contracts and GLB evidence requirements.

Origin Forge will not use Chromium/Electron private Local Storage/LevelDB fabrication or GUI-coordinate automation merely to claim Blockbench support.

## Validation checkpoint

Before this closure decision, the exact Phase-20 branch head completed the repository suite successfully on Python 3.12 and Python 3.13 with 719 tests and one pre-existing external Pixelorama skip per leg. No Phase-20 Blockbench substrate test was skipped.

The detailed Blockbench investigation remains in `docs/phase-20-blockbench.md` as the backend-specific technical record.

## Exit condition met

Origin Forge has an editor-independent, bounded, content-addressed 3D project and execution contract plus independent GLB validation. A real Blockbench process is now a replaceable backend integration concern rather than a roadmap-wide blocker.
