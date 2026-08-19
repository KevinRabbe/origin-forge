# Phase 51B — Blender WorkOrder Binding Closure

Phase 51B promotes exactly one previously deferred 3D dispatch relation. It does not execute Blender and it does not add claim, Task-transition, adoption, acceptance, signing, or release authority.

## Closed authority gap

Phase 51A supplied immutable protected `MODEL3DREQ-*` semantic requests. Phase 51B makes that evidence independently addressable by the generic production WorkOrder and input-resolution stack:

- `WorkOrderRefType.MODEL3D_REQUEST` is a dedicated typed ref; `PHASE_SPECIFIC_EVIDENCE` is not reused.
- `Model3DRequestInputResolver` claims only `MODEL3D_REQUEST / MODEL3DREQ-* / model3d_request` and calls the exact non-creating `Model3DRequestReader.get(...)` relation.
- the resolver projection is exactly `Model3DProductionRequest.to_dict()` and carries no workspace/runtime evidence.
- the `model3d-request` resolver-review row alone moves to `SUPPORTED`.

## Frozen Blender-v1 WorkOrder contract

The only new reviewed dispatch contract is:

```text
adapter_id  = originforge.blender.model3d
contract_id = blender.export-glb@1
operation   = EXPORT_GLB
payload     = {}
input       = exactly one MODEL3D_REQUEST ref
role        = model3d_request
revision    = None
```

Caller payload cannot supply operation, project duplication, `BLOP-*`, `MODEL3D-*`, paths, runtime/profile/executable identity, runner/version hashes, budgets, argv/environment, model/provider selection, claim state, or Task state.

A Blender-only Phase-32 catalog may produce this one contract. Existing code, deterministic simulation, and Pixelorama single-adapter catalog behavior remains intact. A mixed reviewed non-code catalog still fails closed instead of selecting by tuple/order position. Phase-45/46 code bootstrap remains code-first and unchanged.

## Pure semantic compatibility

The Phase-20C Blender runner compatibility predicate is exposed as `validate_blender_v1_project(...)` and the original private name remains an alias for compatibility. No second 3D semantic parser or alternative compatibility law is introduced.

The exact accepted v1 semantic subset remains unrigged, untextured, unanimated, visible, axis-aligned, non-inflated cuboids with no UV controls/parents and positive extent on every axis.

## Inert dispatch binding

The new binder relation is:

```text
binder_id       = binder.blender.export-glb@1
adapter_id      = originforge.blender.model3d
contract_id     = blender.export-glb@1
request_type_id = BlenderJobRequest@production-v1-semantic-binding
```

Its deterministic request projection contains only:

```text
task_id
model3d_request_id
model3d_request_hash
operation = EXPORT_GLB
project
project_hash
```

The binder reconstructs the canonical semantic request from the resolved projection, rechecks exact request identity/hash/operation and Blender-v1 project compatibility, and fails closed on drift or incompatible semantics.

It intentionally contains no runtime IDs, filesystem/output paths, Blender profile/executable/runtime identity, runner fingerprint/version, process budget, argv/environment, claim identity, Task transition, backend invocation, adoption, acceptance, signing, or release authority.

## Adversarial evidence

`tests/test_phase51b_blender_work_order_binding.py` covers:

- exact protected ID/hash resolution and non-creating missing reads;
- canonical-store tamper rejection;
- exact typed/ref-role/cardinality and empty-payload validation;
- deterministic runtime-free binding projection;
- rejection of Blender-v1-incompatible semantic projects;
- resolver/review/binder/validator registry promotion limited to Blender;
- exact Blender-only dispatch-catalog construction;
- mixed reviewed non-code catalog ambiguity remaining fail-closed.

## Phase stop

Phase 51B stops before Phase 51C preparation/claim authority. In particular, this slice does not create a dispatch claim, transition a Task, allocate `BLOP-*` or `MODEL3D-*`, choose paths/runtime/profile/executable/budget, or invoke Blender.
