# Phase 48 — Governed Pixelorama Spritesheet Export Production Dispatch

Status: **PLANNED — architecture frozen before implementation**

Verified planning base `main`:

```text
972b414d0eaaff7284fb277218141f585ea438e6
```

Immutable released v0.5 identity remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 48 is the first bounded **v1.0 production-integration slice** after the v0.5 release. It promotes exactly one already-proven Phase-19 Pixelorama backend through the accepted Phase-33 → Phase-39 preparation and Phase-34 → Phase-37 production-dispatch chain:

```text
media.2d.export
→ originforge.pixelorama.export
→ Pixelorama v1.2 documented headless EXPORT_SPRITESHEET boundary
```

This phase does **not** promote the broader generic Pixelorama bridge. In particular, it does not add automated project creation, import, editing, save, Extension API 9 authority, model-generated editor scripts, or generic media commands. Phase 19 explicitly left those surfaces for later separately governed work; Phase 48 preserves that decision.

The intended production vertical is exactly:

```text
existing Task requiring media.2d.export
    ↓
Phase-32 exact Pixelorama route
    ↓
Phase-33 Pixelorama-export WorkOrder
    + exactly one project-owned PIXELORAMA_PROJECT Artifact ref
    ↓
Phase-34 Artifact metadata resolution + exact Pixelorama export binding
    ↓
Phase-35 exclusive claim
    ↓
Phase-36 STARTED execution ownership
    + Pixelorama-only READY → RUNNING Task transition
    ↓
post-STARTED exact local .pxo source materialization
    + content-hash / size / containment revalidation
    + fresh PXOP-* / MEDIA-* identities
    ↓
exactly one proven PixeloramaCliExportAdapter invocation
    ↓
durable PIXELORAMA Run + request/result/export evidence
    ↓
independent PNG / lineage / source-binding revalidation
    ↓
DISPEXEC RETURNED / claim CONSUMED
    ↓
STOP with Task still RUNNING
```

A successful Pixelorama export dispatch means only that the exact governed editor boundary produced structurally valid durable export evidence from the exact frozen source Artifact. It does **not** mean the asset is aesthetically correct, adopted into the canonical project, cryptographically signed, accepted by a Task, merged, or released.

---

## 1. Why Pixelorama export is the next v1.0 vertical

The canonical v1.0 milestone requires integrated production across code, assets, runtime verification, and provenance. After Phase 47, the production-dispatch chain has two reviewed owner relations:

```text
code.change
→ originforge.code.bounded-retry

simulation.run
→ originforge.simulation.deterministic
```

Phase 32 already contains a trusted Pixelorama adapter:

```text
capability    = media.2d.export
adapter_id    = originforge.pixelorama.export
provider      = originforge.pixelorama
execution     = MEDIA_WORKSPACE_MUTATION
replay_class  = RUNTIME_BOUND
```

But Phase 33/34 still deliberately defer it because a complete exact source/profile request was not frozen for production dispatch.

Pixelorama export is the strongest next candidate because Phase 19 already proved a narrow real upstream boundary:

- Pixelorama release `v1.2`;
- exact runtime version `v1.2-stable`;
- documented headless spritesheet export;
- opaque `.pxo` input rather than reverse-engineered project bytes;
- exact executable fingerprint/version checking;
- isolated `MEDIA-*` workspace;
- no shell;
- fixed argv;
- strict timeout/log/output bounds;
- post-process containment revalidation;
- exact single output set;
- independent RGBA8 PNG validation;
- opt-in real upstream execution evidence.

The real-editor proof does **not** cover project construction/import/save. Phase 48 therefore promotes export only.

---

## 2. Existing Phase-19 boundary to preserve

The accepted direct adapter remains:

```text
PixeloramaCliExportAdapter
PixeloramaCliExportRequest
PixeloramaCliProfile
```

The request remains restricted to:

```text
operation = EXPORT_SPRITESHEET
source_relative_path under inputs/*.pxo
output_relative_path under exports/*.png
source_hash
source_byte_count
bounded timeout/output bytes
fresh PXOP-* operation identity
fresh MEDIA-* workspace identity
```

The trusted profile remains infrastructure-owned and pins:

```text
pixelorama_executable
pixelorama_fingerprint
expected_pixelorama_version
allowed_operations = EXPORT_SPRITESHEET only
timeout_seconds
stdout/stderr limits
executable/runtime byte limits
```

The direct adapter continues to:

- verify the executable and exact Pixelorama version;
- create a protected media workspace;
- copy one exact source `.pxo` into `inputs/`;
- invoke fixed headless spritesheet-export argv without a shell;
- use infrastructure-derived absolute process paths only after containment checks;
- independently revalidate the workspace and exact output set;
- independently validate the exported PNG;
- return typed output hash/size/dimensions;
- expose no project-create/import/save/model/Task/merge/release/install/download authority.

Phase 48 must not weaken or bypass those checks.

---

## 3. Source authority: exactly one canonical Artifact ref

Phase 48 does not invent a generic path/file resolver.

The Phase-33 Pixelorama export WorkOrder accepts exactly one input ref:

```text
ref_type = ARTIFACT
role     = pixelorama_project
```

The referenced Artifact must be a current project-owned canonical Artifact with:

```text
type = PIXELORAMA_PROJECT
content_hash = exact frozen SHA-256 identity
```

The existing Phase-34 `ArtifactInputResolver` remains the metadata authority. It revalidates project ownership and exact `content_hash` and exposes metadata only; it does not read Artifact bytes.

This separation is intentional:

```text
Phase 33 / 34
    freeze identity + hash + metadata
    do not open arbitrary source bytes

Phase 35 / 36
    acquire exact dispatch/execution authority

post-STARTED execution owner
    materialize only the already-bound local PIXELORAMA_PROJECT source
    rehash bytes before process launch
```

No caller/model may supply an arbitrary host path, URI, source byte count, executable, profile, or workspace identity through the WorkOrder.

---

## 4. Phase-33 Pixelorama export contract

Add exactly one reviewed contract:

```text
adapter_id  = originforge.pixelorama.export
contract_id = pixelorama.spritesheet-export@1
```

The contract is deliberately tiny.

### Input refs

Exactly one input ref is required:

```text
WorkOrderRefType.ARTIFACT
role = PIXELORAMA_PROJECT
```

No second source, Verification ref, Project Entity ref, Design Rule ref, URL, path ref, profile ref, or runtime ref is accepted.

### Payload

The initial payload should contain no caller-selected execution authority. Prefer an empty object or an equivalently inert fixed-schema object whose only purpose is contract/version identity.

The following must **not** be payload fields:

- operation kind;
- source path;
- output path;
- source hash or byte count duplicated from the Artifact ref;
- PXOP/MEDIA identity;
- Pixelorama executable/path/fingerprint/version;
- bridge/extension identity;
- timeout/process/log/resource limits;
- argv/environment;
- model/profile/runtime/resource/sandbox/workspace selector;
- adoption/signing/verification/Task status fields.

`EXPORT_SPRITESHEET`, the staged path `inputs/source.pxo`, and the output path `exports/spritesheet.png` are code-owned v1 contract semantics.

### Catalog isolation

For a Pixelorama-only Phase-32 capability catalog, the Phase-33 dispatch catalog contains exactly `pixelorama.spritesheet-export@1`.

Existing code-only and simulation-only catalog behavior must remain semantically unchanged.

The Phase-45/46 Goal-bootstrap full/global authority remains deliberately code-only. Phase 48 must not widen Goal bootstrap simply because the Phase-33 registry learns a Pixelorama contract.

All other deferred adapters remain deferred.

---

## 5. Phase-34 Pixelorama binding and currentness

Add exactly one trusted binder relation:

```text
binder_id       = binder.pixelorama.spritesheet-export@1
adapter_id      = originforge.pixelorama.export
contract_id     = pixelorama.spritesheet-export@1
request_type_id = PixeloramaCliExportService.execute@production-v1
```

The binder requires exactly one resolved input and independently checks:

- ref role is `pixelorama_project`;
- source object type is `ARTIFACT`;
- resolved Artifact ID equals the frozen ref ID;
- resolved Artifact `type` is exactly `PIXELORAMA_PROJECT`;
- resolved Artifact content hash equals the frozen ref hash;
- Artifact status is acceptable for production evidence;
- no extra resolved input exists.

The request projection freezes only inert authority needed later:

```text
task_id
source_artifact_id
source_artifact_hash
source_path_or_uri metadata
operation = EXPORT_SPRITESHEET (code-owned)
contract/binder identity
```

It does **not** contain actual source bytes, source byte count, executable/profile identity, PXOP/MEDIA IDs, or process arguments.

Existing Phase-34 frozen binding audit/currentness remains authoritative. Any Artifact metadata/hash drift invalidates currentness before claim acquisition.

The Pixelorama row in `production_dispatch_binding_review.py` may move from deferred to supported only when this exact relation exists and is independently tested. Other deferred rows remain unchanged.

---

## 6. Post-STARTED local source materialization

The generic Artifact model permits `path_or_uri`, so Phase 48 needs one **Pixelorama-specific** post-STARTED materializer rather than broadening the generic Phase-34 resolver.

Given the exact bound Artifact projection, the materializer must require:

- Artifact `type == PIXELORAMA_PROJECT`;
- a local repository/project-contained path representation, not an external URI;
- canonical portable relative spelling;
- `.pxo` suffix;
- path not under `.git` or `.origin-forge` protected internal state unless an already-established canonical Artifact rule explicitly requires otherwise;
- no symlink source and no symlink parent component;
- regular file existence;
- resolved path contained within the project root;
- actual SHA-256 exactly equals the frozen Artifact content hash;
- actual byte count is positive and within the direct adapter's existing source-size bound.

The materializer returns the validated source file and the actual byte count. The byte count is derived from the exact hash-bound source bytes after STARTED; it is not caller/model authority.

Source drift after Phase-34 binding but before process launch must fail closed without invoking Pixelorama.

No generic `open arbitrary Artifact path` API is added.

---

## 7. Infrastructure-owned Pixelorama installation/profile

The WorkOrder/binder may not choose the editor installation.

Phase 48 execution dependencies must receive one infrastructure-owned trusted Pixelorama CLI profile through a reviewed assembly boundary. That dependency must be exact and fingerprinted enough that the execution dependency plan changes when relevant installation semantics change.

The execution dependency may contain or derive:

```text
PixeloramaCliProfile
    executable
    executable SHA-256
    expected exact version
    EXPORT_SPRITESHEET-only allowlist
    timeout/log/executable/runtime limits
```

But caller/model WorkOrder data may not provide those values.

Normal CI must continue to use fake deterministic process fixtures; the existing opt-in real Pixelorama supply-chain gate remains separate. Phase 48 does not download/install Pixelorama during normal production dispatch or normal CI.

---

## 8. Phase-39 Pixelorama preparation owner

Add a separate code-owned preparation owner for the Pixelorama export contract, conceptually:

```text
owner_id = originforge.preparation.pixelorama-spritesheet-export-planner@1
supported_adapter_id = originforge.pixelorama.export
supported_contract_id = pixelorama.spritesheet-export@1
planner_contract_id = BoundedProductionWorkOrderPlanner.propose@1
model_strategy_roles = (CODER_STRONG,)
```

The existing WorkOrder Planner remains proposal-only. It may select the already-authorized exact Artifact ref and emit the inert Pixelorama export WorkOrder, but it gains no editor/process/profile/path/adoption authority.

Preserve the existing PREPPOL single-owner law:

- code-only catalog → existing code preparation owner;
- simulation-only catalog → existing simulation preparation owner;
- Pixelorama-only catalog → new Pixelorama preparation owner;
- a catalog resolving multiple preparation owners fails closed rather than selecting by ordering.

Phase-45/46 Goal bootstrap remains code-only and keeps its existing owner fingerprint/currentness.

---

## 9. Phase-36 Pixelorama execution owner and atomic start

Add exactly one execution owner:

```text
owner_id = originforge.execution.pixelorama.spritesheet-export@1
adapter_id = originforge.pixelorama.export
contract_id = pixelorama.spritesheet-export@1
binder_id = binder.pixelorama.spritesheet-export@1
model_strategy_roles = ()
requires_sandbox = false
requires_workspace_manager = false
```

The Pixelorama editor process is owned by its dedicated trusted adapter, not by the coding sandbox or Git Workspace manager.

Owner-specific dependency assembly must therefore avoid:

- model scheduling/runtime/provider allocation;
- resource scheduler lease unless future evidence proves a specific editor resource contract is required;
- managed llama.cpp;
- scheduled model adapter;
- coding sandbox;
- Git Workspace manager;
- bounded coding retry policy.

It must include the exact trusted Pixelorama installation/profile dependency and the already-frozen binding/request relation.

### Atomic STARTED + READY→RUNNING

Like the simulation owner, the Pixelorama durable service must run only after production execution ownership exists and the production Task is RUNNING.

For the Pixelorama owner only, Phase 36 atomically performs:

```text
validate exact ACTIVE claim + exact READY Task revision/hash/readiness
→ persist DISPEXEC STARTED
→ transition exact Task READY → RUNNING
→ append canonical events
→ COMMIT
```

Rollback must guarantee neither side persists alone.

The code owner remains unchanged. The simulation owner remains unchanged.

A crash after committed Pixelorama STARTED must never automatically reset the Task to READY.

---

## 10. Durable direct CLI export service

The existing `PixeloramaCliExportAdapter` intentionally does not create a Run. Phase 48 therefore introduces one narrow durable service wrapper over that **proven direct CLI adapter**, conceptually:

```text
PixeloramaCliExportService.execute(task_id, request, source_path)
```

This service must not use the broader generic `PixeloramaBridgeAdapter` project-editing surface.

The service should:

1. require the exact canonical RUNNING Task;
2. create one Run with a dedicated Pixelorama export role (reuse the established `PIXELORAMA` role if its semantics remain exact; otherwise introduce one narrowly justified typed role without changing unrelated Run behavior);
3. persist or otherwise durably bind the exact `PixeloramaCliExportRequest` as request evidence;
4. call the existing `PixeloramaCliExportAdapter.execute(...)` exactly once;
5. persist exact typed result evidence;
6. persist the exported PNG Artifact with exact hash/byte count/path and source lineage;
7. independently re-open/re-hash/re-inspect the resulting PNG before recording structural PASS evidence;
8. record a Run-level structural Verification proving source/request/result/export lineage;
9. finish only the Pixelorama Run;
10. leave the production Task RUNNING;
11. perform no adoption, signing, merge, or release.

The wrapper must preserve the adapter's exact source hash/size, executable/version, containment, output-set, PNG, timeout, and no-shell checks rather than duplicating weaker validation.

A failed editor/process/integrity operation affects the Pixelorama Run/evidence only; it does not automatically condemn the production Task.

---

## 11. Phase-37 exact three-owner invocation fanout

After Phase 48, the closed code-owned production owner set becomes exactly:

```text
originforge.execution.bounded-retry@1
originforge.execution.simulation.deterministic@1
originforge.execution.pixelorama.spritesheet-export@1
```

`dispatch_claim_once(...)` remains the only public single-shot coordinator.

Do not introduce:

- dynamic imports;
- plugin/callable registries;
- reflection-based backend selection;
- model-selected owner;
- caller-selected owner;
- arbitrary tool execution;
- generic media dispatch.

### Pixelorama branch

After exact binding/currentness validation and committed Phase-36 STARTED/RUNNING ownership:

1. materialize/revalidate the exact bound local `.pxo` source;
2. allocate fresh infrastructure-owned `PXOP-*` and `MEDIA-*` identities;
3. construct the fixed `PixeloramaCliExportRequest` from the bound source hash + derived byte count + code-owned paths/bounds;
4. call the durable direct CLI export service exactly once;
5. require a typed service result;
6. revalidate the durable Run/request/result/export/Verification lineage;
7. terminalize DISPEXEC as RETURNED and the claim as CONSUMED;
8. stop.

There is no second Pixelorama call in the same invocation.

The existing bounded-code `.drive()` and deterministic simulation `.execute()` branches remain unchanged.

Manager continues to inspect only dispatch mechanics and may not reinterpret Pixelorama output as Task acceptance truth.

---

## 12. Pixelorama Task outcome semantics

A normal Pixelorama export return leaves the production Task:

```text
RUNNING
```

Structural evidence can prove:

- exact bound source project was used;
- trusted Pixelorama executable/version was used;
- process stayed within the reviewed one-shot contract;
- one declared spritesheet was produced;
- output bytes/hash/dimensions are valid and bound to the operation.

It does not prove:

- visual/aesthetic quality;
- design correctness;
- animation/gameplay suitability;
- Task acceptance criteria;
- canonical asset adoption;
- cryptographic signing;
- dependent Task readiness.

Those require separate governed verification/adoption/adjudication paths.

`DISPEXEC RETURNED` is dispatch completion evidence only.

---

## 13. Adoption and provenance remain separate

Phase 19 already provides explicit create-only adoption for verified media outputs and later Phase-18 provenance signing for adopted Artifacts.

Phase 48 must not collapse these boundaries.

Pixelorama production dispatch may produce an export Artifact under protected execution evidence, but it may not:

- overwrite a canonical project asset;
- call `PixeloramaOutputAdopter` automatically;
- choose a canonical destination path;
- sign the output;
- access private signing keys;
- mark the output accepted/current for product use;
- complete the Task.

A later explicit human/governed operation may adopt or sign exact verified output under the existing rules.

---

## 14. Exception, crash, and no-replay semantics

The Phase-37 no-replay law applies even though the Phase-32 Pixelorama adapter is classified `RUNTIME_BOUND`.

### Pre-STARTED failure

Failure before durable STARTED ownership must not launch Pixelorama and must not leave partial RUNNING/receipt state.

### Source/profile/preflight failure after STARTED but before process launch

If exact source materialization, executable fingerprint, exact version, or other trusted preflight fails after STARTED:

- no Pixelorama operation is executed;
- dispatcher records the appropriate fail-closed execution/claim mechanics under existing laws;
- Task remains RUNNING once STARTED was committed;
- no automatic retry occurs.

### Ordinary `Exception` after STARTED

If the Pixelorama owner/service raises an ordinary Exception:

- retain any durable Pixelorama Run failure evidence produced by the service;
- record DISPEXEC RAISED;
- consume the claim;
- keep Task RUNNING;
- do not invoke Pixelorama again automatically.

### `BaseException` / process death / uncertain return

If control is lost after STARTED and before trustworthy dispatch terminalization:

- leave DISPEXEC STARTED and claim ACTIVE when existing Phase-37 semantics require it;
- Task remains RUNNING;
- restart surfaces explicit recovery-required state;
- Manager never automatically replays the editor process.

### Durable output before dispatch terminalization failure

If exact Pixelorama evidence is durable but DISPEXEC RETURNED/claim consumption fails:

- recovery must inspect durable evidence/currentness;
- it must not launch Pixelorama a second time merely to recreate already-durable output;
- ambiguity/tamper remains fail closed.

---

## 15. Concurrency and no-fallback law

Two Managers pinned to the same oldest Pixelorama candidate must race the real Phase-35 claim boundary.

Required acceptance law:

- exactly one claim winner at most;
- exactly one losing selected-candidate result in the two-worker acceptance race;
- at most one Pixelorama service/adapter invocation;
- at most one Pixelorama Run;
- at most one DISPEXEC receipt for the winning claim;
- no automatic fallback to a newer Task after either race result;
- the newer Task remains untouched with no claim, execution, media Run, or source materialization.

Do not write a timing-sensitive test that requires the claim winner always to reach process execution under every interpreter schedule. The non-vacuous proof is the exact claim winner/loser plus bounded downstream authority and zero newer-Task fallback, matching the corrected Phase-47F concurrency contract.

---

## 16. Goal-bootstrap and package/operator isolation

Phase 48 is downstream production integration only.

It must not change Phase-45/46 Goal bootstrap authority:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

It must not make `media.2d.export` visible to fresh Goal bootstrap or change:

```text
goal bootstrap status|start|recover
```

Phase 48 also adds no new installed package script and no direct mutating Pixelorama command.

The package remains exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Production Pixelorama export is reachable only through already-governed Task/preparation/claim authority and the existing explicit Manager path.

The cockpit remains read-only.

---

## 17. Explicitly deferred Pixelorama surfaces

Phase 48 does **not** authorize:

- `CREATE_SPRITE_PROJECT` production dispatch;
- `IMPORT_LAYER_PNG` production dispatch;
- frame-duration or animation editing;
- `SAVE_PROJECT` production dispatch;
- Extension API 9 project construction/save;
- generic `PixeloramaBridgeAdapter` project-editing promotion;
- model-generated GDScript;
- arbitrary extension/plugin loading;
- arbitrary source/output paths;
- live canonical asset overwrite;
- visual/aesthetic critique;
- image generation/editing;
- automatic adoption/signing;
- automatic Task verification/completion;
- automatic replay/retry after STARTED;
- remote editor service/download/update authority.

Those remain later separately reviewed v1.0 slices if concrete evidence justifies them.

---

## 18. Implementation slices

Phase 48 is implemented as small independently gated slices.

### 48A — exact Pixelorama export WorkOrder contract

Scope:

- add `pixelorama.spritesheet-export@1`;
- require exactly one `ARTIFACT` / `pixelorama_project` input ref;
- keep payload inert/fixed and execution/profile/path identity out of the WorkOrder;
- make Pixelorama-only Phase-32 catalogs produce exactly the new contract;
- preserve existing code-only/simulation-only and Goal-bootstrap authority;
- focused validator/catalog tests only.

Must stop before Phase-34 binding or backend execution.

### 48B — exact Phase-34 Pixelorama binding/currentness

Scope:

- reuse existing `ArtifactInputResolver` metadata-only currentness;
- add exact Pixelorama binder relation;
- require Artifact type/hash/role identity;
- freeze source Artifact metadata + code-owned export semantics;
- no byte reads, executable/profile access, process invocation, or identity allocation;
- move only the Pixelorama binding-review row to supported when exact tests pass.

### 48C — Pixelorama preparation owner

Scope:

- add separate Pixelorama Phase-39 preparation owner;
- reuse existing one-shot WorkOrder Planner;
- preserve code and simulation preparation-owner fingerprints/behavior;
- preserve single-owner/mixed-catalog fail-closed rule;
- Goal bootstrap remains code-only.

### 48D — Pixelorama execution owner + atomic start

Scope:

- add zero-model Pixelorama execution owner;
- add owner-specific dependency assembly with infrastructure-owned trusted Pixelorama CLI profile;
- no model/runtime/resource/sandbox/Git Workspace stack;
- atomically commit STARTED + READY→RUNNING for Pixelorama only;
- rollback/atomicity/restart tests;
- **do not invoke Pixelorama yet**.

### 48E — source materialization + one-shot durable CLI export

Scope:

- add narrow post-STARTED local `PIXELORAMA_PROJECT` materializer;
- reject URI/escape/protected/symlink/non-`.pxo` source;
- rehash exact source and derive bounded byte count;
- allocate fresh PXOP/MEDIA IDs only after STARTED;
- add durable direct CLI export service over `PixeloramaCliExportAdapter`;
- exactly one adapter invocation;
- persist/revalidate request/result/export/Run/Verification lineage;
- RETURNED/CONSUMED on trustworthy normal return;
- Task remains RUNNING;
- no adoption/signing.

### 48F — cross-phase adversarial acceptance

Use real temporary-project state and the actual Manager/preparation/claim/execution path. Cover at minimum:

- happy-path governed Pixelorama export;
- exact source Artifact metadata/currentness;
- source byte/hash drift after binding;
- URI/path escape/protected path/symlink/non-`.pxo` rejection;
- executable fingerprint/version mismatch;
- invalid/extra output rejection;
- ordinary owner exception → RAISED/CONSUMED without Task outcome;
- BaseException after STARTED → STARTED/ACTIVE/RUNNING and no replay;
- durable export followed by terminalization failure → recovery without second editor invocation;
- concurrent same-candidate Managers → exact claim race, at most one Pixelorama invocation, never newer-Task fallback;
- no automatic adoption/signing/Task Verification;
- code owner unchanged;
- simulation owner unchanged;
- Goal bootstrap still code-only;
- closed invocation coordinator has exactly the reviewed code/simulation/Pixelorama call sites and no dynamic owner dispatch.

### 48G — implementation closure / operator / roadmap

After 48A–48F are independently accepted:

- add Phase-48 implementation-closure evidence;
- update living operator guide only for the new already-governed Pixelorama Manager path;
- insert one Phase-48 DONE block in canonical roadmap;
- do not rewrite immutable v0.5 release records/tag to claim Phase 48 was in v0.5.

---

## 19. Test invariants across every slice

Every implementation slice must preserve:

1. **No dynamic production dispatch.** Owner relations remain a closed code-owned set.
2. **No pre-STARTED process call.** Pixelorama process authority occurs only after durable execution ownership.
3. **One exact source.** One canonical project-owned `PIXELORAMA_PROJECT` Artifact ref; no arbitrary path/ref fan-in.
4. **Metadata before bytes.** Phase 34 resolves/revalidates metadata only; source bytes are opened only by the post-STARTED owner materializer.
5. **Exact source bytes.** Process launch requires rehash equality with the frozen Artifact hash and a bounded derived byte count.
6. **Trusted installation outside WorkOrder.** Executable/version/profile/process limits are infrastructure-owned.
7. **At most one editor invocation.** No replay loop in Manager/coordinator/service.
8. **No Task outcome authority.** Export success/failure does not automatically complete/fail the production Task.
9. **No adoption/signing.** Output remains evidence until an explicit separate authority path acts.
10. **No newer-Task fallback after selection.** Claim races and failures stop on the selected candidate.
11. **Code/simulation compatibility.** Existing owner descriptors, call sites, currentness, and acceptance semantics do not drift.
12. **Goal bootstrap isolation.** Existing code-only bootstrap authority/fingerprint semantics remain intact.
13. **v0.5 immutability.** `v0.5.0` remains fixed on release commit `8ac46ee5f14654187469e79b021dbbd83992270b`; Phase 48 is post-v0.5 development.

---

## 20. CI / merge discipline

Planning and every implementation slice use the existing normal matrix as the authoritative repository gate:

```text
python -W error::ResourceWarning -m unittest discover -s tests -v
```

on both Python 3.12 and Python 3.13.

For each PR:

- branch from the exact accepted preceding merge;
- keep one bounded slice only;
- freeze one exact candidate head;
- require Python 3.12 and Python 3.13 green on that exact head;
- audit every changed file and reject unrelated drift;
- verify clean review submissions and unresolved review threads;
- verify `main` has not moved unexpectedly;
- transition draft → ready only after those gates;
- merge with an expected-head SHA guard.

A green run from a superseded head does not authorize a later mutation.

Real Pixelorama supply-chain execution remains opt-in evidence and is not introduced as a normal CI download. Normal CI proves the production integration through bounded deterministic fake-process fixtures plus existing Phase-19 real-editor evidence.

---

## 21. Stop / split conditions

Phase 48 must stop and split into a new separately planned phase if implementation requires any of the following:

- project creation/edit/save rather than opaque-source export;
- a fourth package entrypoint;
- a generic Artifact byte/path resolver available to arbitrary owners;
- caller/model-selected Pixelorama executable/profile/runtime/path;
- arbitrary extension/plugin/GDScript execution;
- network/download/update authority;
- a new background Manager/editor daemon;
- automatic Task terminalization from export evidence;
- automatic adoption/signing;
- a schema migration not required by the frozen exact export semantics;
- weakening code/simulation/Goal-bootstrap authority to make Pixelorama convenient;
- moving/replacing the immutable `v0.5.0` tag.

If the exact direct CLI export cannot be durably integrated under these constraints, Phase 48 fails closed rather than broadening the editor boundary.

---

## 22. Planning exit condition

This planning document is the only Phase-48 planning repository delta.

Before 48A begins:

1. the exact planning head must pass the normal Python 3.12/3.13 matrix;
2. the PR diff must contain only this architecture document;
3. review submissions and unresolved threads must be clean;
4. `main` must still be the expected post-v0.5 base;
5. the exact planning head must be SHA-guarded merged.

Only that accepted planning merge may become the base for Phase 48A.
