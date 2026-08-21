# Phase 52 — Governed Blender Production Output Adoption

Status: **PLANNED — architecture frozen before implementation**

Verified planning base `main`:

```text
2687c901529bb7484ddbdb3af872ed85fef55039
```

Immutable released v0.5 identity remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 51 can now execute exactly one governed Blender `EXPORT_GLB` production request, persist exact request/result/output/Run/Verification lineage, bind one exact `DISPEXEC-*` to one exact durable `BLENDER_GLB_EXPORT`, and recover a stranded successful execution without invoking Blender again. It deliberately stops with the production Task still `RUNNING`, the GLB still inside protected Origin Forge model3d workspace state, and no canonical project asset adopted.

Phase 52 closes exactly the next authority gap:

```text
Phase-51 DISPEXEC RETURNED / claim CONSUMED
    + exact immutable Blender dispatch-output binding
    + exact current Run/request/result/GLB/Verification evidence
    ↓
Blender production-adoption eligibility/currentness
    ↓
explicit human-operated adoption request
    ↓
reserve exact execution/output/destination
    ↓
create-only publication of the exact revalidated GLB bytes
    ↓
new canonical BLENDER_GLB_EXPORT Artifact, status ADOPTED
    + Blender production-adoption-integrity PASS evidence
    + immutable adoption receipt
    ↓
STOP with Task still RUNNING
```

A successful Phase-52 adoption means only that a human explicitly selected one exact terminal Phase-51 Blender production execution and Origin Forge safely published those exact structurally verified GLB bytes once into a new canonical project path. It does **not** mean the geometry semantically satisfies the production request, the asset is artistically or gameplay accepted, the Task is verified or complete, provenance is signed, an existing canonical asset may be replaced, or a release is authorized.

---

## 1. Existing authorities Phase 52 must preserve

### Phase-51 governed Blender dispatch authority

The reviewed Blender owner is exactly:

```text
originforge.execution.blender.export-glb@1
```

Phase 51 already provides:

- protected immutable `MODEL3DREQ-*` semantic input;
- exact `MODEL3D_REQUEST` WorkOrder reference and Blender binding;
- exclusive Phase-35 claim ownership;
- atomic `STARTED` execution ownership and Task `READY → RUNNING` transition;
- post-`STARTED` `BLOP-*` operation and `MODEL3D-*` workspace allocation;
- trusted Blender profile/runtime/version/hash/fingerprint and fixed `BlenderBudget()`;
- exactly one reviewed Blender adapter invocation;
- fixed workspace output `exports/model.glb`;
- one `BLENDER_JOB_REQUEST` Artifact;
- one `BLENDER_EXECUTION_RESULT` Artifact;
- one `BLENDER_GLB_EXPORT` Artifact with status `PRODUCED`;
- one `blender-glb-export-integrity` PASS Artifact Verification;
- one `blender-export-glb` PASS Run Verification;
- independent GLB structural reinspection;
- immutable `blender_dispatch_output_bindings` relation;
- no-replay durable-output recovery;
- normal terminal dispatch state `RETURNED` with claim `CONSUMED` while Task remains `RUNNING`.

The Phase-51 evidence explicitly keeps semantic and product acceptance false. Structural GLB validity is not semantic geometry verification and is not Task acceptance.

### Phase-51 immutable dispatch-output binding

`BlenderDispatchOutputBinding` already stores the exact one-to-one durable relation between:

- dispatch execution and claim;
- frozen Task/WorkOrder/dispatch-binding authority;
- reviewed Blender execution owner;
- exact Blender Run;
- request/result/output Artifacts;
- output and Run Verifications;
- output SHA-256 and byte count.

`read_blender_dispatch_output_binding(...)` revalidates the frozen execution relation. `materialize_bound_blender_result(...)` independently reconstructs the exact durable Blender return and verifies current Run/Task lifecycle, request/result schemas, exact protected output location, current GLB bytes/hash/size, independent GLB inspection, and exact PASS Verification evidence.

Phase 52 must **reuse** this relation. It must not create a second Blender execution→output binding, infer output identity from Task/Run correlation, or introduce a generic production-output registry.

### Phase-19/49 create-only publication law

Pixelorama already proves the repository's canonical create-only media publication laws:

- destination must be portable project-relative text;
- protected project roots are rejected;
- destination symlinks and parent symlink escapes are rejected;
- every pre-existing destination is refused;
- source bytes are bounded and independently hashed;
- a temporary copy is created exclusively and fsynced;
- copied bytes are independently rehashed;
- final publication is create-only and concurrent destination appearance fails closed;
- the adopted Artifact is a child of the exact source Artifact;
- adoption evidence is append-only;
- no overwrite/force/edit-in-place authority exists.

The current `GovernedPixeloramaOutputAdopter` wraps those mechanics in Pixelorama-specific source authority and media-workspace assumptions. Phase 52 may reuse or extract only the authority-neutral **mechanics** if that extraction preserves all existing Pixelorama semantics and cannot become an arbitrary-file publication authority. Phase 52 must not call a Pixelorama-specific authority layer as though it were Blender authorization.

### Provenance and Task outcome authorities

`ProvenanceService` remains the signing authority. Task terminalization remains governed by Task Verification and is deliberately separate from byte-safe adoption.

Phase 52 must not move signing keys, Task PASS/FAIL authority, semantic geometry acceptance, Goal/Flow terminalization, merge, release, or deployment into Blender adoption.

---

## 2. The hard Phase-51 → Phase-52 gap

Phase 51 deliberately leaves a successful GLB here:

```text
.origin-forge/model3d-workspaces/MODEL3D-.../exports/model.glb
```

with an exact durable source Artifact:

```text
type   = BLENDER_GLB_EXPORT
status = PRODUCED
```

and an exact immutable `DISPEXEC-* → output` binding.

That protected workspace output is production evidence, not yet a canonical project asset. Copying it into the project tree based only on a filesystem path, Task ID, Run ID, Artifact ID, or caller-supplied source would bypass the exact dispatch authority Phase 51 established.

Conversely, `materialize_bound_blender_result(...)` is a recovery/materialization primitive. It proves that the bound durable Blender return is still exact, but its existence alone does not grant adoption authority. A stranded `STARTED` execution may have exact durable output evidence for recovery while still being ineligible for canonical adoption.

Therefore Phase 52 adds one narrow production-adoption currentness boundary requiring both:

```text
exact Phase-51 binding/materialized output is current
AND
DISPEXEC status == RETURNED
AND
claim status == CONSUMED
```

before any destination reservation or filesystem publication can occur.

Legacy or manually created Blender-shaped Artifacts without the exact Phase-51 binding are not production-adoption eligible. Phase 52 performs no backfill from loose correlation.

---

## 3. Blender production-adoption eligibility/currentness

Add a read-only Blender-specific eligibility projection for one explicit `execution_id`, conceptually:

```text
inspect_blender_dispatch_output_currentness_readonly(
    runtime,
    execution_id,
)
```

The exact name may follow repository conventions, but the authority law is frozen.

The reader must require at minimum:

- a valid exact `DISPEXEC-*` identity;
- one exact immutable `blender_dispatch_output_bindings` row;
- reviewed owner exactly `originforge.execution.blender.export-glb@1`;
- exact dispatch execution exists and is `RETURNED`;
- exact bound claim exists and is `CONSUMED` at the expected terminal revision;
- claim/execution frozen Task, WorkOrder, dispatch-binding, owner, hashes, and identities remain exact;
- exact Task still exists and remains `RUNNING` at the Phase-51 post-start revision;
- exact bound Blender Run remains `SUCCEEDED` and belongs to that Task;
- exact request/result/output Artifact identities and lineage remain unchanged;
- output is exactly `BLENDER_GLB_EXPORT`, status `PRODUCED`, parented to the exact result Artifact and created by the exact Run;
- output path remains the exact protected Phase-51 `MODEL3D-* / exports/model.glb` location;
- source path contains no symlink or containment escape;
- current output file is a regular file;
- current bytes hash and byte count equal the immutable bound values;
- independent `inspect_glb(...)` succeeds and equals the bound inspection/hash/size contract;
- exact bound output PASS Verification remains `blender-glb-export-integrity` from the reviewed Blender service;
- exact bound Run PASS Verification remains `blender-export-glb` from the reviewed Blender service;
- all contract-relevant Verification evidence remains exact;
- semantic geometry verification remains false;
- production Task verification remains false;
- canonical adoption remains false on the original Phase-51 evidence.

The reader should reuse `read_blender_dispatch_output_binding(...)` and `materialize_bound_blender_result(...)` rather than duplicate or weaken their exact durable checks. It then adds the terminal `RETURNED`/`CONSUMED` adoption gate that recovery materialization intentionally does not own.

Any missing row/file, malformed evidence, wrong owner, nonterminal execution, non-consumed claim, Task drift, lineage drift, path/symlink escape, hash/size drift, invalid GLB, or Verification drift fails closed before adoption mutation.

Later Blender installation/profile/runtime drift does not invalidate an already terminal successful Phase-51 execution merely because the same invocation could not be launched today. Phase 52 judges frozen accepted execution evidence and current bound bytes; it does not reprobe Blender.

---

## 4. Explicit Blender production adoption coordinator

Add a Blender-specific production-aware coordinator, conceptually:

```text
GovernedBlenderProductionOutputAdopter.adopt_new(
    execution_id,
    destination_relative_path,
)
```

The caller selects only:

- one exact terminal production `DISPEXEC-*`;
- one new destination-relative project path;
- optionally the existing bounded source-byte safety limit if retained as a constructor/operator safety control.

The caller/model does **not** select:

- source Artifact ID;
- source filesystem path or URI;
- Run ID;
- Task ID/revision/status;
- output Verification or verifier;
- `MODEL3D-*` workspace;
- `BLOP-*` operation;
- Blender executable/profile/runtime/version/fingerprint;
- `MODEL3DREQ-*` source independently from the frozen execution;
- overwrite/force/replace behavior;
- signing key/certificate;
- automatic destination selection.

The coordinator derives the exact source only from the immutable Phase-51 binding after terminal adoption-currentness passes.

Before publication it must reopen and independently revalidate the exact bound GLB bytes again. A currentness check that was true before destination reservation is not sufficient if the source can drift before the create-only link publication boundary.

The coordinator stops after one exact publication plus immutable receipt/evidence finalization. It does not invoke Blender, Manager, Task acceptance, provenance, Goal bootstrap, merge, release, deployment, cockpit mutation, or GUI behavior.

---

## 5. Create-only canonical GLB publication

The destination law is the existing strict create-only project-publication law, applied to the already-authorized Blender source.

The destination must:

- be canonical portable project-relative text;
- remain inside the project root after resolution;
- not target `.git`, `.origin-forge`, or another protected root;
- not traverse a symlinked destination or parent;
- not already exist as any file/symlink/directory conflict;
- be supplied explicitly by the human operator;
- be published create-only with no overwrite, replacement, force, rename-over-existing, or edit-in-place path.

The publication mechanics must:

1. revalidate the exact authorized source;
2. stream-copy under a bounded byte limit to an exclusive temporary sibling;
3. hash the copied bytes while copying;
4. fsync the temporary file;
5. require copied byte count/hash to equal the immutable bound values;
6. run a final exact adoption-currentness check immediately before final publication;
7. publish create-only so concurrent destination appearance fails closed;
8. never delete or replace an existing canonical destination to make retry convenient;
9. create exactly one adopted child Artifact and its adoption Verification after publication.

If an authority-neutral mechanical helper is extracted from the existing Pixelorama adopter, it must remain internal/narrow and require an already-authorized typed source projection. It may not accept arbitrary caller-selected files or weaken legacy Pixelorama checks.

---

## 6. Blender-specific immutable production-adoption receipt

Phase 52 adds one narrow Blender-specific persistence relation, conceptually:

```text
blender_production_adoptions
```

Current `main` schema is version 16. Under this frozen plan the first Phase-52 schema delta therefore advances the repository to schema version 17 unless an independently accepted intervening migration changes that base before implementation starts.

The relation is not a generic media-adoption registry. It records one exact canonical publication attempt for one exact reviewed Blender production output.

The v1 receipt is keyed by the existing execution identity and enforces database uniqueness over the authority-critical values. Conceptually:

```text
execution_id         PRIMARY KEY
output_artifact_id   UNIQUE
destination_path     UNIQUE
status               PREPARED | PUBLISHED
adopted_artifact_id  UNIQUE NULL until PUBLISHED
verification_id      UNIQUE NULL until PUBLISHED
created_at
published_at         NULL until PUBLISHED
```

Exact implementation naming may follow established store conventions, but these semantics are frozen.

### PREPARED

Before filesystem publication, reserve one exact:

```text
execution_id + bound output_artifact_id + destination_path
```

inside an immediate database transaction after revalidating the exact Phase-51 binding relation.

For the same execution:

- no row → create one canonical PREPARED reservation;
- exact same row → idempotently return it;
- different output or destination → fail closed;
- another execution reusing the same output or destination → database uniqueness fails closed.

### PUBLISHED

After create-only file publication and Artifact/Verification creation, finalization independently rereads and proves the exact durable relation before moving the receipt to `PUBLISHED`.

It must require:

- exact Phase-51 binding remains unchanged;
- exact PREPARED execution/output/destination reservation;
- adopted Artifact is the exact expected child;
- adopted Artifact type/status/path/hash/Run/parent relation are exact;
- exact Blender production-adoption PASS Verification exists with canonical evidence;
- publication identities are not already used elsewhere.

Finalization is insert/update-only within this narrow lifecycle. There is no API to retarget destination, replace output, revert a PUBLISHED adoption, or mark an adoption accepted/rejected semantically.

---

## 7. Canonical adopted Artifact and evidence

The new canonical Artifact is:

```text
type               = BLENDER_GLB_EXPORT
status             = ADOPTED
parent_artifact_id = exact bound Phase-51 BLENDER_GLB_EXPORT
created_by_run_id  = exact bound Blender Run
a path_or_uri      = exact canonical destination-relative project path
content_hash       = exact bound GLB SHA-256
```

The exact `path_or_uri` representation must follow existing lineage conventions for project-local adopted Artifacts; receipt finalization must compare against that canonical representation rather than mix absolute and project-relative forms.

Record one Blender-specific PASS Verification, conceptually:

```text
verification_type = blender-production-adoption-integrity
verifier          = OriginForge.GovernedBlenderProductionOutputAdopter
status            = PASS
run_id            = exact bound Blender Run
```

The v1 evidence must include at least:

```text
source_artifact_id
source_content_hash
source_byte_count
destination_path
destination_content_hash
existing_asset_overwritten = false
production_dispatch_output_bound = true
dispatch_execution_id
dispatch_claim_id
production_run_id
production_task_verified = false
semantic_geometry_verified = false
provenance_signed = false
```

The exact output hash and byte count come from the immutable binding and must equal the bytes independently revalidated immediately before publication.

`production_dispatch_output_bound = true` means only that the adopted bytes are exactly the bytes bound to one terminal successful Phase-51 Blender execution. It is not semantic geometry acceptance and not Task acceptance.

Phase 52 does not mutate earlier Phase-51 Verification evidence from false to true. Evidence remains append-only; the adopted Artifact receives its own publication evidence.

---

## 8. Operator boundary

Phase 52 remains explicit and human operated.

When the operator slice is implemented, extend Blender administration as a Blender-specific module command rather than a new installed package entrypoint or a Pixelorama command extension, conceptually:

```text
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  adopt-production-new DISPEXEC-... path/to/model.glb
```

If implementation discovers an existing repository-local Blender admin module naming convention before 52C, the exact module filename may follow it, but the command authority above may not widen.

The command accepts only the explicit project root, exact `DISPEXEC-*`, one new destination-relative path, and a bounded byte safety control if retained.

It must not accept source Artifact/path/URI, Run, Task, verifier, Blender executable/profile/runtime, workspace/operation IDs, signing material, overwrite/force flags, semantic acceptance flags, or automatic destination selection.

Installed package scripts remain exactly the existing three:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The cockpit remains read-only. Phase 52 adds no GUI route, mutating HTTP endpoint, daemon, watcher, timer, polling loop, or background adoption queue.

---

## 9. Task acceptance remains outside Phase 52

A successful Phase-52 adoption must end with:

```text
Blender Run = SUCCEEDED
DISPEXEC = RETURNED
claim = CONSUMED
bound source BLENDER_GLB_EXPORT = PRODUCED
canonical child BLENDER_GLB_EXPORT = ADOPTED
Task = RUNNING
production_task_verified = false
semantic_geometry_verified = false
```

Structural GLB validity plus exact byte-safe canonical publication does not prove that the model satisfies semantic geometry requirements, artistic intent, topology constraints not encoded in Phase-51 structure inspection, gameplay requirements, or any other human acceptance criterion.

Phase 52 therefore does not:

- record a Task PASS/FAIL Verification;
- transition Task to `SUCCEEDED` or `FAILED`;
- alter Task acceptance criteria;
- treat adoption success as semantic geometry verification;
- fail the Task automatically if adoption fails;
- terminalize a Flow or Goal.

Blender production Task acceptance requires a separately planned later phase.

---

## 10. Provenance signing remains outside Phase 52

An adopted GLB may later be supplied explicitly to the existing provenance authority. Phase 52 itself must not:

- call `sign_artifact(...)` automatically;
- create, load, or move private signing keys into Blender/adoption dependencies;
- set `provenance_signed = true` merely because adoption succeeded;
- equate cryptographic provenance with Task acceptance;
- authorize merge, release, or deployment.

Focused tests must prove adoption succeeds with no signing key configured and creates no signature/provenance record as a side effect.

---

## 11. Concurrency, crash, retry, and no-replay law

### Repeated adoption / fan-out

One exact Phase-51 execution/output may be canonically adopted at most once through the Phase-52 production path. A second destination for the same execution/output fails closed. A second execution may not claim the same bound output or reserved destination.

This uniqueness is database-backed through the Blender-specific receipt, not inferred by scanning filesystem children.

### Destination race

Two explicit adoption attempts may race for the same absent destination, but at most one create-only publication may succeed. Concurrent destination appearance is an error; no retry path overwrites it.

### Crash before final publication

A crash before the create-only destination appears may leave only a bounded hidden temporary file plus a PREPARED receipt. Retry may clean/recreate only the temporary copy after revalidating:

- exact binding/currentness;
- exact PREPARED receipt;
- destination still absent;
- exact source bytes.

### Crash after destination publication but before Artifact/evidence/receipt finalization

A destination present beside a PREPARED receipt is an ambiguous post-publication state. Automatic retry must fail closed with explicit operator recovery required. It must not delete, overwrite, replace, or silently adopt the existing destination based only on matching path.

A later recovery authority may be designed separately if needed. Phase 52 does not manufacture missing canonical lineage by assumption.

### Crash after Artifact/Verification but before receipt PUBLISHED

If implementation can independently prove the exact reserved destination, exact child Artifact, exact Verification, exact bytes, and uniqueness without ambiguity, finalization may be idempotently completed under the frozen receipt law. If exact identities cannot be derived without scanning/guessing, fail closed as operator recovery required rather than create duplicates.

### No Blender replay

No Phase-52 eligibility read, reservation, adoption, retry, receipt finalization, or recovery path invokes Blender. Missing, invalid, or ambiguous Phase-51 output fails closed instead of re-exporting GLB.

---

## 12. Compatibility and authority isolation

Phase 52 must preserve all existing owners and behavior:

- code production dispatch unchanged;
- deterministic simulation production dispatch unchanged;
- Pixelorama dispatch/adoption/Task-acceptance semantics unchanged;
- Phase-51 Blender dispatch/recovery semantics unchanged;
- Phase-45/46 Goal bootstrap remains code-only;
- protected `MODEL3DREQ-*`, `MODEL3D-*`, and `BLOP-*` boundaries unchanged;
- no generic Artifact source selector for production adoption;
- no generic production-output/adoption registry or plugin surface;
- no caller/model destination-selection automation;
- no model-selected source/runtime/profile/workspace/verifier;
- no fourth installed package entrypoint;
- no mutating cockpit/GUI surface;
- no background worker/daemon/watcher;
- no signing/Task/Goal/release authority;
- immutable v0.5 records/tag unchanged.

The canonical Phase-20A Blockbench project remains the semantic 3D truth and Blender remains a replaceable execution backend. Phase 52 adopts exact Blender-produced GLB bytes; it does not elevate Blender runtime state into upstream semantic authority.

---

## 13. Implementation slices

Phase 52 is implemented as independently gated slices.

### 52A — Blender production-output currentness / adoption eligibility

Scope:

- add a narrow read-only projection for one explicit Blender `DISPEXEC-*`;
- reuse the exact Phase-51 immutable dispatch-output binding and durable result materializer;
- require exact `RETURNED` execution + `CONSUMED` claim + current `RUNNING` Task relation;
- independently require exact current bound GLB path/bytes/hash/size/structure and exact Run/Artifact/Verification lineage;
- expose `adoption_eligible` only for the exact terminal relation;
- prove a stranded `STARTED` execution remains recovery-only and is not adoption eligible;
- no schema mutation, destination publication, Task transition, signing, or Blender invocation.

### 52B — Blender receipt + create-only production adoption

Scope:

- add the narrow `blender_production_adoptions` relation; under current schema v16 this is the Phase-52 schema-v17 migration;
- implement PREPARED/PUBLISHED immutable receipt semantics and database uniqueness over execution/output/destination/publication identities;
- add the Blender-specific production adoption coordinator;
- derive source exclusively from the exact Phase-51 binding;
- revalidate source immediately before publication;
- reuse/extract only safe authority-neutral create-only publication mechanics, or implement an equivalently strict Blender-specific narrow publisher if safe extraction would widen authority;
- create exact child `BLENDER_GLB_EXPORT` Artifact, status `ADOPTED`;
- record exact Blender production-adoption-integrity PASS evidence;
- enforce one canonical production adoption at most per bound execution/output;
- preserve PREPARED/post-publication ambiguity as fail-closed recovery-required;
- keep Task `RUNNING`, semantic geometry false, provenance unsigned;
- no Blender replay.

### 52C — Blender operator surface + adversarial acceptance

Scope:

- add the explicit Blender module command `adopt-production-new` under a Blender-specific admin module;
- add no installed package script;
- exercise real temporary-project state from Phase-51 terminal Blender evidence through explicit Phase-52 adoption;
- cover missing/tampered binding, non-RETURNED execution, non-CONSUMED claim, Task drift, wrong owner/Run/Artifact/Verification lineage, source path/symlink/escape, GLB byte/hash/size/structure drift, protected/symlinked/escaped destinations, byte limits, destination races, repeated adoption/fan-out, PREPARED retry rules, post-publication ambiguity, exact receipt finalization, no Blender replay, no signing, no Task transition, and package-entrypoint stability;
- prove Pixelorama legacy production adoption and Task acceptance remain unchanged;
- prove cockpit and GUI surfaces remain untouched/read-only.

### 52D — implementation closure / operator / roadmap

After 52A–52C are independently accepted:

- add Phase-52 implementation-closure evidence;
- update the living operator guide for explicit governed Blender production adoption;
- insert one Phase-52 DONE block in the canonical roadmap under v1.0;
- do not rewrite the frozen Phase-52 architecture document;
- do not modify production source/tests/schema/config/packaging/workflows in the closure slice;
- do not alter immutable v0.5 release records/tag.

---

## 14. Test invariants across every slice

Every implementation slice must preserve:

1. **Exact dispatch binding.** Production adoption never trusts Task-only, Run-only, Artifact-only, or path-only correlation.
2. **Terminal dispatch required.** Adoption requires exact `DISPEXEC RETURNED` and claim `CONSUMED`.
3. **No recovery/adoption conflation.** A valid bound output beside `STARTED` is recovery evidence only.
4. **No legacy inference.** Blender-shaped outputs without an exact Phase-51 binding are not production-adoption eligible.
5. **Exact current bytes.** Source is reopened, rehashed, size-checked, and independently `inspect_glb(...)` validated before publication.
6. **Exact lineage.** Request/result/output/Run/Verification identities and evidence remain the reviewed Phase-51 contract.
7. **Create-only publication.** Existing destinations, protected roots, symlink escapes, overwrite, force, replacement, and edit-in-place all fail closed.
8. **Explicit operator action.** Adoption is never a dispatcher/Manager/GUI side effect.
9. **At most one canonical adoption.** One bound execution/output cannot fan out to multiple canonical destinations in v1.
10. **Database-backed receipt authority.** Reservation/publication uniqueness is not inferred from filesystem scans.
11. **Crash ambiguity fails closed.** PREPARED + existing destination never triggers automatic deletion/overwrite/republication.
12. **No Blender replay.** Phase 52 never invokes Blender to repair missing/invalid evidence.
13. **No Task outcome authority.** Task remains `RUNNING`; no Task PASS/FAIL is synthesized.
14. **No semantic geometry claim.** Structural GLB integrity and byte-safe adoption do not imply semantic acceptance.
15. **No signing authority.** No automatic signature or private-key access occurs.
16. **Media isolation.** Pixelorama adoption/acceptance behavior is unchanged.
17. **Execution-owner isolation.** Code/simulation/Goal-bootstrap behavior is unchanged.
18. **Package stability.** Installed scripts remain exactly the existing three.
19. **Cockpit/GUI isolation.** No mutating cockpit, HTTP, or GUI surface is introduced.
20. **v0.5 immutability.** `v0.5.0` remains fixed on release commit `8ac46ee5f14654187469e79b021dbbd83992270b`.

---

## 15. CI / merge discipline

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
- verify review state and unresolved review threads;
- verify `main` has not moved unexpectedly;
- transition draft → ready only after those gates;
- merge only with an explicit expected-head SHA guard and required authorization.

A green run from a superseded head does not authorize a later mutation.

No real Blender installation/download/execution is added to normal CI for Phase 52. Phase 52 consumes the already durable Phase-51 contract and deterministic temporary-project fixtures. Tests that exercise structural GLB currentness use bounded deterministic GLB fixtures, not external runtime installation authority.

---

## 16. Stop / split conditions

Phase 52 must stop and split into a new separately planned phase if implementation requires any of the following:

- Task PASS/FAIL Verification or Task terminalization;
- human semantic/aesthetic/geometry acceptance;
- automatic provenance signing or private-key access inside adoption;
- automatic adoption from Manager/dispatcher/cockpit/GUI execution;
- adoption without exact Phase-51 durable execution→output binding;
- inference/backfill of production authority from loose Task/Run/Artifact/path correlation;
- overwriting/editing/replacing an existing canonical asset;
- caller/model-selected source Artifact/path/URI, Run, verifier, workspace, Blender profile/runtime, or execution dependency;
- model/Goal/Task metadata deciding a destination path automatically;
- a generic production-output/adoption registry or plugin system;
- a fourth installed package entrypoint;
- mutating HTTP/cockpit/GUI routes, daemon, watcher, poller, timer, or background queue;
- Blender replay/re-execution during adoption/retry/recovery;
- broad changes to global Verification uniqueness semantics;
- weakening Pixelorama, code, simulation, Goal-bootstrap, or Phase-51 Blender dispatch authority;
- Flow/Goal terminalization, merge, release, deployment, or release-signing authority;
- moving/replacing the immutable `v0.5.0` tag.

A narrow Blender-specific schema migration for the one-shot adoption receipt is **inside** Phase 52. Any broader schema redesign is a split condition.

If exact Blender production output adoption cannot be implemented under these constraints, Phase 52 fails closed rather than treating structural output existence or filesystem copying as product acceptance.

---

## 17. Planning exit condition

This planning document is the only Phase-52 planning repository delta.

Before 52A begins:

1. the exact planning head must pass the normal Python 3.12/3.13 matrix;
2. the PR diff must contain only `docs/phase-52-governed-blender-production-output-adoption.md`;
3. no production source, test, schema, config, packaging, workflow, cockpit, or GUI file may change in planning;
4. exact current `main` ancestry must remain auditable;
5. immutable v0.5 identity must remain unchanged;
6. the planning PR must remain draft until the exact candidate is green and reviewed under the normal gate;
7. merging the planning PR requires explicit authorization and an expected-head SHA guard.

Only after that planning gate is accepted may Phase 52A begin from the exact merged planning commit.
