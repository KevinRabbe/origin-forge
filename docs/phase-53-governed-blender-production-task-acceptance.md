# Phase 53 — Governed Blender Production Task Acceptance

Status: **FROZEN ARCHITECTURE — implementation not yet authorized by this document alone**

Phase 53 closes the next missing post-v0.5 production boundary after Phase 52: explicit human semantic acceptance of one already-dispatched, already-canonically-adopted Blender production result, followed by the existing verification-gated production Task transition law.

Phase 53 does **not** add a geometry oracle, aesthetic model judge, autonomous acceptance loop, Blender replay, new adoption authority, provenance signing, merge, deployment, release, Manager auto-acceptance, Goal-bootstrap widening, or UI implementation.

The core law is:

```text
exact Phase-51 terminal Blender production output
+ exact Phase-52 PUBLISHED canonical adoption
+ current adopted GLB bytes / structure
+ explicit HUMAN_OPERATOR semantic acceptance
→ one immutable Task PASS acceptance relation
→ existing canonical Task RUNNING → SUCCEEDED transition
→ STOP
```

A successful Phase-53 acceptance states that a human operator accepted the exact canonical Blender result against the production Task contract. It is not a claim that arbitrary geometry metrics, a vision model, a specialist, Blender itself, Manager, or the browser verified semantic correctness independently.

## 1. Why Phase 53 is the next production slice

Phase 51 deliberately stops after governed Blender dispatch and exact durable GLB output binding, leaving the production Task `RUNNING`.

Phase 52 deliberately stops after create-only canonical publication of those exact bytes, leaving all higher authorities false:

- `production_task_verified = false`;
- `semantic_geometry_verified = false`;
- provenance unsigned;
- release unauthorized.

The frozen Phase-52 architecture explicitly defers Blender production Task acceptance to a separately planned later phase. Phase 53 supplies only that missing acceptance/terminalization boundary.

The accepted Phase-50 Pixelorama production Task acceptance is the mechanical precedent for receipt publication, recovery, and canonical Task transition, but Phase 53 is a separate Blender authority family. No Pixelorama acceptance row, verifier identity, evidence type, currentness implementation, or operator authority is reused as Blender truth.

## 2. Current repository facts this architecture binds

Phase 53 starts from `main` after Phase 52 closure at:

```text
7825e5648377f6e1bef59b12c6609195f81c7322
```

The current durable schema line is:

```text
v15  Pixelorama production Task acceptance
v16  Blender dispatch-output binding
v17  Blender production adoption
v18  independent governed-conversation Gate-A substrate
v19  governed-conversation Gate-C operation/reference substrate
```

`src/origin_forge/db.py` composes the migrations in that order and derives `SCHEMA_VERSION` from the final migration. Phase 53 therefore reserves **schema v20** for its Blender production Task-acceptance receipt. It must append after the governed-conversation Gate-C v19 migration; it must not renumber, replace, fold into, or otherwise claim the UI/conversation schema line.

The current immutable `BlenderDispatchOutputBinding` already binds one exact:

- `DISPEXEC-*` execution;
- dispatch claim;
- production Task revision/content hash;
- WorkOrder and WorkOrder hash;
- Phase-34 dispatch binding and hash;
- reviewed Blender execution owner `originforge.execution.blender.export-glb@1`;
- Blender Run;
- request/result/output Artifacts;
- output and Run Verifications;
- output SHA-256 and byte count.

Phase-51 materialization/currentness remains responsible for re-deriving and validating the exact protected MODEL3D semantic request relation represented by that governed WorkOrder/binding chain.

Phase 52 already provides exactly one Blender-specific production-adoption receipt per execution/output/destination with lifecycle:

```text
PREPARED → PUBLISHED
```

A PUBLISHED receipt binds the exact source output to one adopted child `BLENDER_GLB_EXPORT` Artifact and one exact `blender-production-adoption-integrity` PASS Verification.

Phase 53 consumes those authorities; it does not recreate them.

## 3. Permanent authority model

### 3.1 Human semantic acceptance is explicit

The only Phase-53 semantic acceptance authority is:

```text
HUMAN_OPERATOR
```

A model, vision backend, Visual Critic, Reviewer, other specialist, Blender process, deterministic GLB inspector, Manager, Planner, conversation processor, browser, or UI may provide evidence or presentation, but cannot synthesize the Phase-53 acceptance decision.

The operator must explicitly select one canonical `DISPEXEC-*` production execution. Phase 53 derives every other production identity from durable authority.

The acceptance operation must not accept caller-supplied overrides for:

- Task ID;
- WorkOrder ID/hash;
- MODEL3D request ID/hash;
- Phase-34 binding ID/hash;
- claim ID;
- Run ID;
- request/result/output Artifact IDs;
- source path;
- adopted Artifact ID;
- adoption Verification ID;
- destination path;
- output/adopted hash or byte count;
- Blender executable/profile/runtime/version/runner/workspace/operation identity;
- Task PASS status;
- verifier identity;
- semantic score/verdict supplied by a model;
- signing key/certificate;
- overwrite/force/bypass flag;
- merge/deploy/release decision.

### 3.2 Structural validation is necessary but not semantic authority

Independent GLB validation remains mandatory before a first acceptance while the Task is `RUNNING`. It proves that the current canonical destination is still the exact structurally valid GLB adopted from the exact bound Phase-51 output.

It does **not** itself make `semantic_geometry_verified = true`.

That field becomes true only as part of the explicit human acceptance evidence described below.

### 3.3 Existing runtime owns Task terminalization

Phase 53 must not update the `tasks` table directly.

After the exact Task PASS and immutable Phase-53 receipt are durable, the acceptor may request the existing canonical runtime/store transition:

```text
Task RUNNING → SUCCEEDED
```

using the exact expected Task revision captured at acceptance publication.

All existing runtime invariants remain authoritative, including optimistic revision checks, child-Task compatibility, Task Verification requirements, state-event history, and any future stricter invariant already present in the normal transition path.

## 4. Required exact pre-acceptance relation

For a first acceptance, one `DISPEXEC-*` is eligible only if all of the following reconstruct exactly.

### 4.1 Phase-51 dispatch authority

- the execution ID is a canonical `DISPEXEC-*`;
- the immutable Blender dispatch-output binding exists and passes canonical validation;
- `execution_owner_id` is exactly `originforge.execution.blender.export-glb@1`;
- the dispatch execution is exact terminal `RETURNED` currentness;
- the originating claim is exact `CONSUMED` truth;
- execution/claim/Task/WorkOrder/Phase-34 binding identities and hashes match the immutable Phase-51 binding;
- the production Task is still the exact Task bound to that execution;
- the exact successful Blender Run/request/result/output/Verification lineage remains trustworthy;
- the protected MODEL3D semantic request reconstructed through the governed WorkOrder/binding relation remains exact and current for acceptance purposes;
- the bound output Artifact is the exact produced `BLENDER_GLB_EXPORT` with the expected parent, Run, content hash and byte count.

### 4.2 Phase-52 canonical adoption authority

- one Blender production-adoption receipt exists for the execution;
- its status is exactly `PUBLISHED`;
- its source output Artifact is exactly the Phase-51 bound output;
- the adopted Artifact ID and adoption Verification ID are non-null and exact;
- the adopted Artifact is exactly a child `BLENDER_GLB_EXPORT` with status `ADOPTED`;
- its parent is the exact Phase-51 output Artifact;
- its `created_by_run_id` is the exact Blender production Run;
- its canonical destination path is exactly the receipt destination;
- its content hash is exactly the bound output hash;
- the exact `blender-production-adoption-integrity` Verification exists, is PASS, targets that adopted Artifact, uses the reviewed Phase-52 verifier identity, and has exact expected evidence;
- no conflicting adoption relation exists for the same execution, Task, adopted Artifact or adoption Verification.

### 4.3 Current canonical destination bytes

Before a first acceptance while the Task is `RUNNING`, Phase 53 independently validates the canonical adopted destination again:

- safe project-relative destination;
- contained under the project root;
- no symlink at any path component;
- regular file;
- readable under the accepted byte bound;
- exact byte count;
- exact SHA-256;
- exact structural GLB validation using the existing independent GLB inspector;
- no external/escaped asset relation that the existing accepted GLB boundary rejects.

Any current-byte or structural drift fails closed before a new acceptance PASS can be created.

### 4.4 Production Task state

For a first acceptance:

- Task status is exactly `RUNNING`;
- Task revision is the exact expected post-dispatch revision for the current Phase-51 relation;
- Task content identity remains consistent with the frozen dispatch binding;
- child Tasks are compatible with success under the existing runtime transition law;
- there is no conflicting Phase-53 acceptance authority for the Task/execution/adopted Artifact relation.

## 5. Schema v20 — immutable Blender production Task acceptance receipt

Phase 53A must add exactly one new append-only migration after governed-conversation Gate-C v19.

Proposed table:

```text
blender_production_task_acceptances
```

Minimum immutable fields:

- `execution_id` — primary key and FK to exact Blender production adoption execution;
- `task_id` — unique FK to Task;
- `adopted_artifact_id` — unique FK to exact Phase-52 adopted Artifact;
- `adoption_verification_id` — unique FK to exact Phase-52 integrity PASS;
- `task_verification_id` — unique FK to the Phase-53 Task PASS;
- `task_revision_at_acceptance` — exact non-negative revision;
- `accepted_content_hash` — canonical `sha256:<64 lowercase hex>`;
- `accepted_byte_count` — positive byte count;
- `accepted_destination_path` — exact canonical project-relative path;
- `acceptance_authority` — constrained to `HUMAN_OPERATOR`;
- `schema_version` — Phase-53 receipt schema version, initially `1`;
- `accepted_at` — immutable timestamp.

Database-level requirements:

- one acceptance per execution;
- one Phase-53 acceptance per production Task;
- one acceptance per adopted Artifact;
- one acceptance per adoption Verification;
- one acceptance per Task Verification;
- adoption and Task Verification IDs must be distinct;
- rows cannot be updated;
- rows cannot be deleted;
- conflicting unique/relation writes fail closed.

Phase 53 does not modify the Phase-52 adoption receipt or governed-conversation v18/v19 tables.

## 6. Exact Task PASS Verification

Phase 53A/53B must define a Blender-specific Verification identity, not a Pixelorama identity.

Frozen type:

```text
blender-production-task-acceptance
```

Frozen verifier:

```text
OriginForge.GovernedBlenderProductionTaskAcceptor
```

Frozen authority:

```text
HUMAN_OPERATOR
```

The Verification:

- targets the exact production Task;
- has `status = PASS`;
- binds `run_id` to the exact Phase-51 Blender production Run;
- has empty metrics `{}` unless a later architecture explicitly introduces governed acceptance metrics;
- is created atomically with the immutable Phase-53 receipt;
- is infrastructure-owned evidence of the explicit human acceptance, not model-generated proof.

Minimum exact evidence payload:

```text
production_task_verified = true
semantic_geometry_verified = true
acceptance_authority = HUMAN_OPERATOR
production_dispatch_output_bound = true
canonical_asset_adopted = true
existing_asset_overwritten = false
provenance_signed = false
release_authorized = false

dispatch_execution_id
production_claim_id
production_run_id
work_order_id
model3d_request identity/hash as reconstructed from governed authority
source_output_artifact_id
production_adoption_verification_id
adopted_artifact_id
adopted_destination_path
accepted_content_hash
accepted_byte_count
task_content_hash
task_revision_at_acceptance
```

If the current exact repository API cannot expose the MODEL3D request ID/hash without widening or duplicating Phase-51 authority, implementation must stop and add a read-only exact semantic-request projection first. It must not infer the request from Task prose or reconstruct it from caller metadata.

## 7. Acceptance publication transaction

The Phase-53 publication primitive accepts a prevalidated exact Blender production snapshot and performs one serialized SQLite transaction.

Canonical order:

```text
BEGIN IMMEDIATE
→ search all uniqueness dimensions for existing acceptance
→ if one exact canonical existing relation exists, revalidate and return it
→ if identities split/conflict, fail closed
→ allocate infrastructure-owned Verification ID
→ insert exact Task PASS Verification
→ append normal VERIFICATION_RECORDED state event
→ insert immutable Blender acceptance receipt
→ reread receipt
→ reread/revalidate exact Task Verification
→ COMMIT
```

No Task status mutation occurs in this transaction.

The transaction must never accept caller-provided PASS evidence or caller-selected IDs for the durable verification/receipt relation.

## 8. Read-only acceptance currentness

Phase 53B must add one Blender-specific non-creating currentness projection with exactly four semantic states analogous to the proven Phase-50 mechanics:

```text
NOT_ACCEPTED
ACCEPTED_PENDING_TASK_TRANSITION
ACCEPTED_TASK_SUCCEEDED
STALE_OR_CONFLICTING
```

### NOT_ACCEPTED

Requires the complete exact live Phase-51/52/current-destination relation and Task `RUNNING`, with no Phase-53 receipt.

`acceptance_eligible = true`.

### ACCEPTED_PENDING_TASK_TRANSITION

Requires:

- exact complete historical/live relation;
- one exact Phase-53 receipt;
- exact Task PASS Verification;
- Task still `RUNNING` at the exact acceptance revision.

This is the deliberate recoverable crash window after durable acceptance publication and before Task terminalization.

`acceptance_eligible = true` only for recovery of the same exact acceptance; it does not authorize a second human decision or duplicate PASS.

### ACCEPTED_TASK_SUCCEEDED

Requires:

- one exact immutable Phase-53 acceptance relation;
- Task exactly `SUCCEEDED` at the canonical revision after acceptance;
- exact canonical `RUNNING → SUCCEEDED` state event;
- the same Phase-53 Task PASS remains the durable acceptance basis.

For this already-terminal historical state, later canonical-file drift must not retroactively rewrite accepted Task history. The read path may report current-file drift separately if desired, but it must not convert an exact historically accepted Task into a different historical acceptance or publish replacement evidence.

### STALE_OR_CONFLICTING

Any missing, malformed, ambiguous, stale, relinked, tampered, inconsistent, wrong-owner, wrong-Task, wrong-Run, wrong-request, wrong-adoption, wrong-Verification, current-byte-drifted first-acceptance state, or conflicting terminal state fails closed here.

No repair, replay, overwrite or replacement acceptance occurs from this reader.

## 9. Governed acceptor and recovery semantics

Phase 53B must expose one application/service authority conceptually equivalent to:

```text
GovernedBlenderProductionTaskAcceptor
```

Public mutation input is only:

```text
execution_id: DISPEXEC-*
actor_id: optional audit actor
```

The acceptor flow is:

```text
inspect exact currentness

if STALE_OR_CONFLICTING:
    fail closed

if ACCEPTED_TASK_SUCCEEDED:
    reread exact historical receipt
    return idempotent canonical result

if NOT_ACCEPTED:
    read exact Phase-51 binding
    read exact Phase-52 PUBLISHED adoption
    atomically publish exact Phase-53 PASS + receipt

if ACCEPTED_PENDING_TASK_TRANSITION:
    reuse exact existing PASS + receipt

reinspect
require ACCEPTED_PENDING_TASK_TRANSITION
request existing runtime Task RUNNING → SUCCEEDED
    with expected_revision = task_revision_at_acceptance

on StaleRevision:
    reinspect once
    if exact ACCEPTED_TASK_SUCCEEDED:
        return canonical result
    otherwise fail closed

reinspect exact SUCCEEDED currentness
return canonical result
```

The acceptor must not call Blender, republish the adopted GLB, mutate the adopted file, create another adoption receipt, run a vision model, run a specialist, sign provenance, invoke Manager, or authorize release.

## 10. Operator surface

Phase 53C should extend the existing module-only Blender admin family rather than add a fourth installed package entrypoint.

Frozen command shape:

```bash
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  accept-production-task \
  --execution-id DISPEXEC-...
```

The command accepts exactly one explicit execution identity plus normal project-root/operator plumbing.

It exposes no Task ID, Artifact ID, path, Run ID, request ID, Verification ID, PASS value, score, model/specialist report, Blender profile/runtime, force/bypass flag, signing material, merge/deploy/release option, retry count, watch/poll/loop mode, or background behavior.

A successful process result means the governed acceptance operation completed and returns its exact typed result. It must not be interpreted as release authorization.

## 11. Future UI integration requirements — instructions only

Phase 53 does **not** implement UI behavior.

A future UI may expose Phase-53 acceptance only as a client of the same governed application/service boundary.

A future UI may:

- display one exact `DISPEXEC-*` and read-only Phase-53 currentness;
- display the exact Task, adopted Artifact, canonical destination, hash/size, MODEL3D request reference, and acceptance status derived by the service;
- clearly distinguish `NOT_ACCEPTED`, `ACCEPTED_PENDING_TASK_TRANSITION`, `ACCEPTED_TASK_SUCCEEDED`, and `STALE_OR_CONFLICTING`;
- require an explicit human confirmation action before first semantic acceptance;
- call the same governed acceptor with the execution identity;
- display the exact returned Task Verification/receipt/Task status;
- surface recovery-required or stale/conflicting states without automatic repair.

A future UI must **not**:

- write Task status directly;
- insert Verification or acceptance rows directly;
- infer or replace Task/Run/Artifact/MODEL3D request/Verification identities;
- copy, replace, rewrite, move, or delete the adopted GLB;
- duplicate or weaken currentness/lineage/hash/size/GLB checks in presentation code;
- auto-accept after adoption or dispatch;
- treat a vision/model/specialist score as HUMAN_OPERATOR acceptance;
- automatically retry a conflicting/stale state;
- replay Blender;
- sign provenance;
- merge, deploy, or release;
- present Task acceptance as provenance trust or release readiness.

The browser/presentation layer owns neither filesystem nor Task/Verification authority. If a future HTTP transport is added, it must delegate to a typed application boundary and preserve the same idempotency and authorization laws.

These are implementation constraints for future UI work only. Phase 53 itself must not change cockpit, conversation, server, browser, HTML/CSS/JS, HTTP routes, CSP, or GUI source.

## 12. Slice plan

### Phase 53A — immutable acceptance substrate

Implement only:

- schema-v20 Blender production Task-acceptance migration;
- migration registration after governed-conversation v19;
- Blender-specific immutable receipt model/read/publish primitive;
- exact Task PASS Verification type/verifier/evidence;
- focused migration/immutability/uniqueness/atomic-publication tests.

53A stops before live currentness, Task transition, CLI, UI, signing or release.

### Phase 53B — currentness, acceptor and recovery

Implement only:

- exact read-only Phase-51/52/MODEL3D/adopted-GLB acceptance currentness;
- child-success compatibility check consistent with normal Task transition;
- first human acceptance publication;
- pending-transition recovery using the same receipt/PASS;
- existing runtime/store `RUNNING → SUCCEEDED` transition;
- idempotent exact already-SUCCEEDED read;
- adversarial currentness/revision/concurrency/recovery tests.

53B adds no CLI or UI implementation.

### Phase 53C — explicit operator and cross-phase acceptance

Implement only:

- module-only Blender admin `accept-production-task --execution-id ...`;
- bounded error/result projection;
- source-level proof that the CLI delegates only to the Phase-53 acceptor;
- cross-phase adversarial acceptance covering the real Phase-51 → Phase-52 → Phase-53 relation;
- no Blender replay, no duplicate acceptance, no file mutation, no Pixelorama authority widening, and no new package entrypoint.

No UI implementation belongs in 53C.

### Phase 53D — implementation closure

Documentation-only closure after 53A–53C are individually accepted:

- implementation closure with exact heads/runs/merge evidence;
- current operator guide update;
- canonical roadmap Phase-53 DONE insertion;
- future UI integration constraints may be restated as instructions only;
- no runtime/tests/schema/config/packaging/workflow/UI source mutation.

The exact 53D documentation head must itself pass the canonical Python 3.12/3.13 matrix before expected-head guarded merge.

## 13. Required adversarial acceptance

Before Phase 53 is considered implemented, tests must prove fail-closed behavior for at least:

- missing/malformed `DISPEXEC-*`;
- wrong execution owner;
- execution not exact RETURNED;
- claim not exact CONSUMED;
- stale/mutated execution authority;
- wrong or drifted Task identity/revision/content hash;
- wrong WorkOrder or Phase-34 binding identity/hash;
- missing/stale/wrong protected MODEL3D semantic request relation;
- failed/noncanonical Blender Run;
- missing/wrong request/result/output Artifacts;
- source output Artifact lineage/hash/size drift;
- missing/wrong output or Run Verification;
- missing/non-PUBLISHED/conflicting Phase-52 adoption receipt;
- wrong adopted Artifact parent/Run/type/status/path/hash;
- missing/non-PASS/wrong Phase-52 integrity Verification;
- adopted destination path escape or symlink before first acceptance;
- adopted destination missing/non-file/unreadable before first acceptance;
- adopted destination hash/size drift before first acceptance;
- adopted destination structural GLB failure before first acceptance;
- Task not RUNNING for first acceptance;
- child Task incompatible with success;
- existing conflicting acceptance by execution/Task/adopted Artifact/Verification;
- forged Task PASS evidence;
- wrong acceptance verifier/type/authority/evidence/run/timestamp;
- receipt mutation/delete attempts;
- crash after PASS+receipt but before Task transition;
- concurrent acceptance publication;
- concurrent Task transition race;
- exact same acceptance retry after pending transition;
- exact same acceptance retry after SUCCEEDED;
- conflicting post-SUCCEEDED acceptance attempt;
- proof that acceptance never invokes Blender;
- proof that acceptance never republishes/rewrites the adopted GLB;
- proof that model/vision/specialist evidence cannot create the HUMAN_OPERATOR PASS;
- proof that Pixelorama acceptance authority remains independent;
- proof that governed-conversation v18/v19 state remains untouched;
- proof that no cockpit/browser/GUI mutation authority is introduced;
- proof that no provenance signing, merge, deployment, release, Flow transition or Goal transition occurs.

## 14. Explicit non-authority

Phase 53 grants no authority for:

- automatic semantic geometry acceptance;
- automated aesthetic acceptance;
- automatic acceptance from vision/specialist/model scores;
- model-authored acceptance decisions treated as human;
- Blender replay or repair;
- asset overwrite/republication;
- Task failure/quarantine decisions from geometry findings;
- Flow/Goal terminalization;
- Manager/background acceptance;
- Goal-bootstrap Blender acceptance;
- provenance signing or key access;
- merge/deployment/release;
- UI/browser mutation implementation;
- remote/multi-user authorization design;
- generic media Task acceptance;
- Pixelorama acceptance widening;
- release modification of immutable v0.5 records.

## 15. Planning acceptance gate

This architecture PR itself must remain documentation-only.

Allowed planning-PR diff:

```text
docs/phase-53-governed-blender-production-task-acceptance.md
```

The planning PR must pass the normal Python 3.12/3.13 matrix on the exact final head integrated with then-current `main`. If `main` advances before merge, the architecture tree must be revalidated against the new base; content-identical refresh is acceptable when the concurrent delta is proven disjoint.

Only after the exact architecture head is green and SHA-guarded merged may 53A schema/runtime implementation begin.
