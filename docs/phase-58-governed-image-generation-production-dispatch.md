# Phase 58 — Governed Image Generation Production Dispatch

Status: **implemented in a separately reviewable vertical; remote CI remains the merge gate**

Phase 58 promotes ComfyUI generation from a standalone image service to the
governed production path:

```text
WorkOrder → resolution → binding → claim → dependency assembly
→ STARTED execution → ComfyUI → Artifacts/Verifications
→ image output binding → RETURNED → no-replay recovery
```

## Frozen boundary

- `ImageGenerationInvocationRequest` reconstructs only the exact WorkOrder
  projection and request hash.
- `ImageGenerationInputBinder` and the image execution owner freeze the exact
  adapter, contract, request schema, and owner relations.
- `ImageWorkflowStore` supplies the exact immutable workflow and model
  identity. The default ComfyUI profile is local-only.
- Operation and workspace IDs are allocated only after durable
  `DISPATCH_EXECUTION_STARTED`.
- Schema v24 stores one immutable row per generated PNG output, including
  exact execution lineage, Artifact/Verification IDs, paths, dimensions, byte
  counts, content hashes, pixel hashes, and backend result hash.
- A durable output binding is sufficient to complete terminalization after an
  interruption, but recovery never invokes ComfyUI.

## Authority exclusions

Image generation produces structural evidence only. The adapter, model,
workflow, vision service, cockpit, and dispatcher cannot accept a Task, adopt
an Artifact, sign provenance, merge, or release. Missing, stale, conflicting,
or tampered evidence fails closed.

## Verification

The focused vertical test proves WorkOrder assembly, claim acquisition,
READY→RUNNING transition, fake backend invocation, request/result/output
Artifact lineage, PNG Verification evidence, output binding publication,
RETURNED terminalization, and restart materialization with exactly one backend
call. Adjacent image, owner, dispatch, migration, and authority suites remain
required before merge.
