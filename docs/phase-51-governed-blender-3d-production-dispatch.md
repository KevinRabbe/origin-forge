# Phase 51 — Governed Blender 3D Production Dispatch

Status: **PLANNED — architecture frozen before implementation**

Verified planning base `main`:

```text
7cdbd5f76b3671c942132d303cfdeef35bddd87b
```

Phase 51 promotes exactly one already-proven Phase-20C Blender backend into the governed Phase-33 → Phase-39 preparation and Phase-34 → Phase-37 production-dispatch chain, but only after supplying the protected semantic input boundary that Phase 34 deliberately left missing.

The target vertical is:

```text
media.3d.blender
→ originforge.blender.model3d
→ fixed EXPORT_GLB semantic request
→ protected MODEL3DREQ-* evidence
→ exact Phase-33 WorkOrder ref
→ exact Phase-34 resolver + Blender binding
→ Phase-35 exclusive claim
→ Phase-36 STARTED execution ownership
→ post-STARTED BLOP-* / MODEL3D-* runtime allocation
→ existing governed Blender adapter + frozen runner
→ independently inspected self-contained GLB evidence
→ DISPEXEC RETURNED / claim CONSUMED
→ STOP with Task still RUNNING
```

A normal return proves only that the exact protected 3D request was executed through the reviewed Blender boundary and produced structurally valid durable GLB evidence. It does **not** adopt the GLB into canonical project state, accept the Task, sign provenance, complete a Flow/Goal, merge, or release.

---

## 1. The Phase-34 blocker is still real

Phase 32 already contains:

```text
capability   = media.3d.blender
adapter_id   = originforge.blender.model3d
family       = originforge.blender
execution    = MEDIA_WORKSPACE_MUTATION
replay_class = RUNTIME_BOUND
```

The missing surface is not a capability descriptor. The current Phase-33/34 built-in review still defers Blender because no complete exact 3D request can be resolved through a protected typed reader.

The current direct `BlenderJobRequest` cannot be used as a WorkOrder semantic request. It intentionally freezes execution-owned state:

- fresh `BLOP-*` operation ID;
- fresh `MODEL3D-*` workspace ID;
- output workspace path;
- frozen runner SHA-256;
- Blender runtime-tree hash;
- expected Blender version line;
- process/output/log budgets.

Its `create()` method allocates `BLOP-*` and `MODEL3D-*` immediately. Moving that object upstream into Phase 33 would therefore allocate execution authority before a durable dispatch execution exists and would let runtime identity contaminate semantic WorkOrder identity.

Phase 51 resolves this by adding a separate semantic request relation. It does not weaken `BlenderJobRequest`; that strict type remains the post-STARTED runtime request consumed by the proven direct adapter.

---

## 2. Protected semantic 3D request

Add one new typed infrastructure identity:

```text
IdKind.MODEL3D_REQUEST = MODEL3DREQ
```

External IDs are therefore:

```text
MODEL3DREQ-<uuid>
```

`MODEL3D-*` remains reserved for execution workspaces. `BLOP-*` remains reserved for Blender operations.

Add one immutable semantic model, conceptually:

```text
Model3DProductionRequest
    request_id: MODEL3DREQ-*
    operation: EXPORT_GLB
    project: BlockbenchProjectSpec
```

The semantic object binds the exact canonical Phase-20A project and its content hash. `EXPORT_GLB` is the only Phase-51 operation.

The semantic object must contain **none** of:

- `BLOP-*` operation identity;
- `MODEL3D-*` workspace identity;
- workspace/source/output filesystem paths;
- Blender executable or runtime root;
- runner fingerprint or runner path;
- runtime hash;
- expected Blender version;
- argv/environment;
- timeout/log/output/process budgets;
- model/provider/resource/sandbox/workspace selection;
- Artifact adoption destination;
- Task/Flow/Goal state or acceptance fields;
- signing, merge, or release authority.

The canonical Phase-20A `BlockbenchProjectSpec` remains the 3D truth. Blender remains a replaceable backend.

### Protected persistence

Persist semantic requests in a dedicated project-local registry:

```text
.origin-forge/model3d-requests/
```

The registry must be immutable and content-addressed. Publication/read behavior must include:

- strict typed `MODEL3DREQ-*` validation;
- canonical finite UTF-8 JSON;
- exact content hash revalidation;
- bounded object and catalog sizes;
- no symlink/alias root, entry, or parent escape;
- create-only/no-overwrite publication;
- fsync before durable publication;
- exact ID/hash non-creating lookup;
- no directory scanning as an input-resolution strategy;
- fail closed on malformed, unknown-field, duplicate-key, identity/hash, containment, or competing-publication drift.

A trusted programmatic producer may construct and publish an already-valid semantic request. Phase 51 adds no model/Goal/Task metadata parser and no arbitrary JSON/path creation CLI merely to manufacture 3D authority.

---

## 3. Typed Phase-33 WorkOrder reference

Add exactly one new WorkOrder ref type:

```text
WorkOrderRefType.MODEL3D_REQUEST
```

Do **not** reuse `PHASE_SPECIFIC_EVIDENCE`. Phase 34 explicitly forbids that enum as a wildcard escape hatch.

The Phase-33 Blender WorkOrder contract is:

```text
adapter_id  = originforge.blender.model3d
contract_id = blender.export-glb@1
```

It requires exactly one ref:

```text
ref_type = MODEL3D_REQUEST
role     = model3d_request
ref_id   = exact MODEL3DREQ-*
content_hash = exact semantic request hash
revision = None
```

The payload is an inert empty object. The caller/model may not duplicate, override, or select operation, project bytes, runtime identity, paths, executable/profile/version, budgets, runner, or backend arguments through the payload.

A Blender-only Phase-32 catalog may produce exactly this contract. Existing code-, simulation-, and Pixelorama-only catalog behavior must remain semantically unchanged. Mixed reviewed non-code catalogs continue to fail closed rather than select by ordering.

Phase-45/46 Goal bootstrap remains code-only.

---

## 4. Exact protected resolver

Add one code-owned resolver claim:

```text
ref_type = MODEL3D_REQUEST
prefix   = MODEL3DREQ-
role     = model3d_request
source_object_type = MODEL3D_REQUEST
resolution_class   = PROTECTED_MODEL3D_REQUEST
```

The resolver must use only the exact non-creating protected request reader. It must not:

- scan operation/workspace directories;
- inspect `MODEL3D-*` execution workspaces;
- reconstruct a request from Goal/Task metadata;
- guess files/paths;
- fall back to generic Artifact or phase-specific evidence;
- create missing state;
- probe Blender or any executable.

The resolved projection contains the exact immutable semantic request only.

Once this reader and typed ref exist and are independently tested, only the `model3d-request` resolver-review row may move from deferred to supported. Other deferred evidence families remain unchanged.

---

## 5. Pure Blender-v1 WorkOrder validation and binding

The existing Phase-20C runner v1 supports only:

```text
unrigged
untextured
unanimated
visible
axis-aligned
non-inflated cuboids
→ one self-contained GLB
```

Unsupported semantic projects must be rejected **before** claim/start authority. Phase 51 may expose/refactor the existing pure Blender-v1 project compatibility check so the WorkOrder validator/binder can independently reject bones, textures, animations, parented/rotated/inflated/hidden cuboids, UV controls, or non-positive cuboid extents without invoking Blender.

Add exactly one binder relation:

```text
binder_id       = binder.blender.export-glb@1
adapter_id      = originforge.blender.model3d
contract_id     = blender.export-glb@1
request_type_id = BlenderJobRequest@production-v1-semantic-binding
```

The inert dispatch binding freezes only:

```text
task_id
model3d_request_id
model3d_request_hash
operation = EXPORT_GLB
project
project_hash
contract/binder identity
```

It must contain no `BLOP-*`, `MODEL3D-*`, path, profile, executable, runtime, runner, process budget, model/provider, or resource identity.

Binding audit/currentness must independently reconstruct this projection from the exact protected request. Request deletion, malformed data, hash drift, resolver/binder/schema drift, WorkOrder drift, or Blender-v1 incompatibility makes the binding non-current and blocks claim/start.

Only the Blender binding-review row may move to supported when this exact relation exists. No other deferred adapter is promoted by Phase 51.

---

## 6. Phase-39 Blender preparation owner

Add one separate preparation owner for the exact Blender contract, conceptually:

```text
owner_id = originforge.preparation.blender-export-glb@1
supported_adapter_id = originforge.blender.model3d
supported_contract_id = blender.export-glb@1
```

The existing WorkOrder Planner remains proposal-only. It may select one already-authorized `MODEL3DREQ-*` ref; it may not create or mutate the semantic project, choose an executable/profile/runtime, allocate operation/workspace IDs, supply paths, or invoke Blender.

Preserve the single-owner law:

- code-only catalog → existing code owner;
- simulation-only catalog → existing simulation owner;
- Pixelorama-only catalog → existing Pixelorama owner;
- Blender-only catalog → Blender owner;
- any ambiguous multi-owner catalog fails closed.

Goal bootstrap remains code-only.

---

## 7. Phase-36 Blender execution owner and atomic STARTED

Add one zero-model execution owner:

```text
owner_id   = originforge.execution.blender.export-glb@1
adapter_id = originforge.blender.model3d
contract_id = blender.export-glb@1
binder_id  = binder.blender.export-glb@1
model_strategy_roles = ()
requires_sandbox = false
requires_workspace_manager = false
```

The Blender process belongs to the dedicated trusted adapter, not the coding model/sandbox stack.

Owner-specific dependency assembly must avoid model scheduling/provider allocation, managed llama.cpp, coding sandbox, Git Workspace manager, and bounded coding retry policy. It may receive only the exact frozen semantic binding plus an infrastructure-owned trusted Blender runtime profile and fixed code-owned execution dependencies.

For this owner only, Phase 36 atomically performs:

```text
validate exact ACTIVE claim
+ exact READY Task revision/hash/readiness
+ exact current Blender binding
→ persist DISPEXEC STARTED
→ transition exact Task READY → RUNNING
→ append canonical events
→ COMMIT
```

Rollback must guarantee that STARTED and READY→RUNNING cannot persist separately. A crash after committed STARTED never resets the Task to READY automatically.

This slice stops before Blender invocation and before `BLOP-*`/`MODEL3D-*` allocation.

---

## 8. Post-STARTED runtime authority

Only after durable `DISPEXEC STARTED` exists may the Blender execution path allocate or derive:

- fresh `BLOP-*` operation ID;
- fresh `MODEL3D-*` workspace ID;
- code-owned output path, fixed initially to `exports/model.glb`;
- infrastructure-owned `BlenderRuntimeProfile`;
- Blender executable contained under the trusted runtime root;
- exact runtime-tree hash;
- exact expected Blender version line;
- exact frozen runner fingerprint;
- bounded `BlenderBudget` from infrastructure policy.

The owner then constructs the existing strict `BlenderJobRequest` from:

```text
exact bound semantic project
+ fixed EXPORT_GLB
+ fresh runtime IDs
+ code-owned output path
+ trusted profile/runtime/runner identity
+ infrastructure budget
```

No caller/model-supplied value may replace any runtime-owned field.

The existing adapter remains responsible for profile verification, executable containment, version probe, isolated workspace/environment construction, fixed no-shell argv, frozen runner staging, process timeout/log/output bounds, exact export-set checking, symlink/root containment, and independent GLB inspection.

Normal CI uses deterministic fake-process fixtures. Any opt-in real Blender supply-chain/runtime gate remains separate and must not download/install Blender during ordinary production dispatch or normal CI.

---

## 9. Durable Blender execution service and evidence

Wrap the proven direct adapter in one narrow durable production service, conceptually:

```text
BlenderExportService.execute(task_id, request)
```

The service must:

1. require the exact canonical RUNNING Task;
2. create one Blender/3D Run using an existing exact Run role if semantically correct, otherwise one narrowly justified typed role;
3. durably bind the exact `BlenderJobRequest` before process interpretation can become ambiguous;
4. invoke `BlenderAdapter.execute(...)` exactly once;
5. persist exact typed result evidence;
6. persist the exported GLB Artifact with exact bytes/hash/size/path and source request/project lineage;
7. independently re-open/re-hash/`inspect_glb()` the durable GLB before structural PASS evidence;
8. record Run-level Verification proving semantic-request → runtime-request → result → GLB lineage;
9. finish only the Blender Run;
10. leave the production Task RUNNING;
11. perform no adoption, signing, merge, release, or human acceptance.

A successful direct adapter return is process evidence until the durable service independently revalidates and persists the exact output lineage.

---

## 10. Phase-37 exact owner fanout

`dispatch_claim_once(...)` remains the only public one-shot production coordinator.

After exact current Blender binding and committed Phase-36 STARTED/RUNNING ownership, the Blender branch:

1. loads the exact protected semantic request/binding relation;
2. obtains the exact infrastructure-owned trusted Blender profile;
3. allocates fresh `BLOP-*` and `MODEL3D-*` identities;
4. constructs the existing strict `BlenderJobRequest` with code-owned path/budget;
5. invokes the durable Blender export service exactly once;
6. revalidates durable Run/request/result/Artifact/Verification lineage;
7. terminalizes DISPEXEC as RETURNED and the claim as CONSUMED;
8. stops with Task RUNNING.

There is no dynamic import, reflection-selected backend, caller/model-selected owner, arbitrary tool execution, generic media command, or second Blender invocation.

Existing code, simulation, and Pixelorama branches remain semantically unchanged.

---

## 11. No-replay and failure law

The existing Phase-37 no-replay law applies to Blender even though its Phase-32 adapter is `RUNTIME_BOUND`.

### Before STARTED

Any request, WorkOrder, resolver, binder, claim, readiness, or currentness failure must launch no Blender process and allocate no `BLOP-*`/`MODEL3D-*` runtime identities.

### After STARTED but before process launch

Profile/runtime/runner/version/preflight failure launches no Blender operation. Task remains RUNNING and no automatic retry occurs.

### Ordinary exception after STARTED

Retain any durable Run/evidence already produced, record DISPEXEC RAISED under existing laws, consume the claim when current dispatch semantics require it, leave Task RUNNING, and do not invoke Blender again automatically.

### Process death / uncertain return

If control is lost after STARTED before trustworthy terminalization, preserve recovery-required ambiguity. Do not automatically replay Blender.

### Durable output before dispatch terminalization

If exact GLB evidence is already durable but RETURNED/CONSUMED finalization fails, recovery inspects durable evidence/currentness; it must not launch Blender again merely to recreate an existing output.

---

## 12. Concurrency and authority exclusions

Two Managers racing the same Blender candidate must race the real Phase-35 claim boundary. Acceptance requires at most one claim winner, one execution owner, one Blender Run, one Blender process invocation, and no fallback to a newer Task after the selected-candidate race result.

Phase 51 does **not** add:

- automatic GLB adoption into canonical project state;
- automatic Task acceptance/completion;
- negative-decision repair/re-dispatch;
- Flow/Goal completion;
- provenance signing/private-key access;
- merge/release authority;
- arbitrary `.blend` loading or persistence;
- model-generated Blender Python;
- arbitrary add-ons/extensions;
- online runtime mode or runtime downloads;
- arbitrary host paths, argv, environment, executable selection, or shell commands;
- textures/materials/UVs/armatures/animations beyond the already-frozen runner-v1 surface;
- Blockbench production promotion;
- a new installed package script or cockpit mutation path.

Output adoption and human Task acceptance are separate future governed 3D phases, analogous in authority separation to the Pixelorama dispatch/adoption/acceptance sequence rather than silently included here.

---

## 13. Implementation slices

Phase 51 is implemented as independently gated slices.

### 51A — protected MODEL3D semantic request substrate

Scope:

- add `IdKind.MODEL3D_REQUEST = MODEL3DREQ`;
- add immutable semantic `Model3DProductionRequest` with only ID, fixed `EXPORT_GLB`, canonical `BlockbenchProjectSpec`, and exact content identity;
- add protected create-only `.origin-forge/model3d-requests/` persistence plus exact ID/hash non-creating reader;
- reject malformed/hash-drifted/aliased/symlinked/oversized/unknown-field evidence;
- no WorkOrder ref, binder, claim, Task transition, Blender invocation, or runtime ID allocation yet.

### 51B — typed WorkOrder, resolver, Blender contract and binding

Scope:

- add `WorkOrderRefType.MODEL3D_REQUEST`;
- add exact `MODEL3DREQ-*` / `model3d_request` resolver claim;
- add `blender.export-glb@1` with exactly one semantic request ref and inert payload;
- expose/reuse pure Blender-v1 project compatibility validation before claim authority;
- add `binder.blender.export-glb@1` and exact binding audit/currentness;
- move only the model3d-request resolver-review and Blender binding-review rows to supported;
- preserve all other adapters and Goal bootstrap behavior;
- stop before preparation/claim/execution.

### 51C — Blender preparation owner

Scope:

- add separate Blender Phase-39 preparation owner;
- planner may select exactly one pre-existing current `MODEL3DREQ-*` ref;
- preserve existing owner fingerprints/behavior and mixed-owner fail-closed rules;
- no Blender profile/runtime/process or runtime identity allocation.

### 51D — Blender execution owner + atomic start

Scope:

- add zero-model Blender execution owner;
- add owner-specific infrastructure dependency assembly with trusted Blender profile;
- no coding model/resource/sandbox/Git Workspace stack;
- atomically commit STARTED + READY→RUNNING for Blender only;
- rollback/restart/currentness tests;
- **do not invoke Blender or allocate BLOP/MODEL3D IDs yet**.

### 51E — post-STARTED one-shot Blender export

Scope:

- allocate fresh `BLOP-*` and `MODEL3D-*` only after STARTED;
- construct existing strict `BlenderJobRequest` from exact semantic project plus infrastructure profile/path/budget;
- add durable one-shot Blender export service over the existing adapter;
- exactly one adapter invocation;
- persist/revalidate runtime request/result/GLB Artifact/Run/Verification lineage;
- RETURNED/CONSUMED only on trustworthy normal return;
- Task remains RUNNING;
- no adoption/signing/acceptance.

### 51F — cross-phase adversarial acceptance

Use real temporary-project state and the actual preparation/claim/execution path. Cover at minimum:

- happy-path governed Blender export;
- malformed/deleted/wrong-ID/wrong-hash semantic request;
- `PHASE_SPECIFIC_EVIDENCE` substitution attempt;
- wrong ref role/type or extra input refs;
- unsupported Blender-v1 project semantics before STARTED;
- runtime identity/path/profile/budget injection attempts through WorkOrder/request;
- stale WorkOrder/binding/request currentness;
- no `BLOP-*`/`MODEL3D-*` allocation before STARTED;
- runtime hash/runner fingerprint/version/executable containment failure;
- symlink/workspace/output escape and undeclared export-set rejection;
- GLB byte/hash/inspection/lineage drift;
- ordinary exception and uncertain-return no-replay behavior;
- durable-output-before-dispatch-finalization recovery without Blender replay;
- two-manager claim race with at most one Blender invocation and no newer-Task fallback;
- existing code/simulation/Pixelorama and Goal-bootstrap authority unchanged;
- no Task terminalization, adoption, signing, merge, or release.

Every authority-expanding slice must pass the canonical Ubuntu Python 3.12/3.13 matrix at its exact accepted head before the next slice advances.

---

## Exit condition

Phase 51 is complete when Origin Forge can take one exact immutable protected `MODEL3DREQ-*` semantic request, bind it through the canonical production chain without runtime authority leakage, acquire exact dispatch ownership, allocate Blender runtime identity only after durable STARTED, invoke the existing governed Blender adapter exactly once, independently persist/revalidate structural GLB lineage, return/consume the dispatch, and stop with the Task still RUNNING.

The phase is incomplete if Blender can be reached through Goal/Task metadata reconstruction, generic phase-evidence fallback, caller/model-selected runtime state, pre-STARTED operation/workspace allocation, unbounded backend execution, or automatic adoption/acceptance/signing/release.
