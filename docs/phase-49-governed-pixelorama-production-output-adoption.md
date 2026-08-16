# Phase 49 — Governed Pixelorama Production Output Adoption

Status: **PLANNED — architecture frozen before implementation**

Verified planning base `main`:

```text
5cfebc84d9537e1ad30a26f9a4652bc1dbd0e458
```

Immutable released v0.5 identity remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 49 is the first post-Phase-48 acceptance slice. Phase 48 can now execute exactly one governed Pixelorama spritesheet export and persist a structurally verified output, but deliberately stops with the production Task still `RUNNING` and the output unadopted and unsigned.

Phase 49 closes exactly the next authority gap:

```text
Phase-48 DISPEXEC RETURNED / claim CONSUMED
    + exact durable PIXELORAMA Run/request/result/export evidence
    ↓
new immutable execution→output binding
    ↓
explicit human-operated production adoption request
    ↓
revalidate exact RETURNED/CONSUMED dispatch relation
    + exact bound Run/request/result/output/Verification lineage
    + exact current source bytes
    ↓
reuse Phase-19 create-only project publication laws
    ↓
new canonical project Artifact + adoption-integrity PASS evidence
    ↓
STOP with Task still RUNNING
```

A successful Phase-49 adoption means only that a human explicitly selected one exact structurally verified Phase-48 production output and OriginForge safely published those exact bytes as a new project Artifact under the existing create-only media adoption rules. It does **not** mean the visual result is semantically or aesthetically accepted, the production Task is verified or complete, provenance is signed, an existing canonical asset may be replaced, or a release is authorized.

---

## 1. Existing authorities Phase 49 must preserve

### Phase-48 production export authority

`PixeloramaCliExportService` already produces durable evidence for one `RUNNING` Task:

- one `PIXELORAMA` Run;
- one `PIXELORAMA_CLI_EXPORT_REQUEST` Artifact;
- one `PIXELORAMA_CLI_EXPORT_RESULT` Artifact;
- one `SPRITESHEET_EXPORT` Artifact;
- one output `pixelorama-cli-export-integrity` PASS Verification;
- one Run-level `pixelorama-cli-export` PASS Verification;
- independently rehashed and RGBA8-validated PNG bytes.

The service result explicitly keeps:

```text
task_status_changed = false
canonical_asset_adopted = false
provenance_signed = false
```

The output and Run Verification evidence likewise retain:

```text
production_task_verified = false
canonical_asset_adopted = false
```

Phase-37/48 `dispatch_claim_once(...)` revalidates that durable result before it records `DISPEXEC RETURNED` and consumes the claim.

### Phase-19 create-only adoption authority

`GovernedPixeloramaOutputAdopter.adopt_new(...)` already owns the safe byte-publication primitive. It:

- accepts only reviewed Pixelorama source Artifact types;
- requires exact source-integrity Verification evidence;
- rejects external/escaped/protected/symlinked source paths;
- independently rehashes source bytes;
- resolves one portable project destination;
- refuses every existing destination;
- copies through an exclusive temporary file;
- rehashes the copied bytes;
- uses create-only link publication so a concurrent destination appearance fails closed;
- creates one child Artifact with status `ADOPTED`;
- records `pixelorama-adoption-integrity` PASS evidence;
- keeps `production_task_verified = false`.

The existing admin entry point is deliberately human operated:

```text
python -m origin_forge.pixelorama_admin_cli adopt-new ...
```

Phase 49 must reuse these publication laws. It must not introduce a second weaker byte-copy/adoption implementation.

### Phase-18 provenance authority

`ProvenanceService` remains the only signing authority. It independently rehashes Artifact bytes and signs through the configured operational certificate/private key path. Its public status explicitly keeps automatic Task verification and automatic release disabled.

Phase 49 must not move private signing keys into the dispatcher, Pixelorama service, adoption coordinator, or admin CLI.

---

## 2. The hard Phase-48 → Phase-49 gap

The successful in-memory Phase-48 return contains both:

```text
CompletedDispatchInvocation.execution
CompletedDispatchInvocation.pixelorama_result
```

but `CompletedDispatchInvocation` is intentionally a non-canonical synchronous wrapper.

Durably, the two truth domains are still separate:

```text
dispatch_executions
    knows DISPEXEC / claim / Task / WorkOrder / Phase-34 binding / owner

Pixelorama Run + Artifacts + Verifications
    know Task / Run / request / result / exported PNG
```

The persisted Pixelorama export evidence does **not** carry the exact `DISPEXEC-*` identity, and the dispatch execution does **not** carry the exact Pixelorama Run/output identities.

Task-only or Run-only correlation is insufficient. More than one durable Pixelorama-shaped Run could exist for the same still-`RUNNING` Task, so Phase 49 may not infer that an arbitrary matching output was the exact output returned by a particular production dispatch.

Therefore Phase 49 first adds an immutable durable relation between the exact dispatch execution and the exact already-revalidated Pixelorama output. Production adoption is forbidden without that relation.

Existing Phase-48 outputs created before Phase 49 have no such durable relation and therefore fail closed for the new **production** adoption path. Phase 49 does not synthesize or backfill production authority from loose Task/Run correlation.

---

## 3. Exact durable Pixelorama dispatch-output binding

Add one narrow persistence relation, conceptually:

```text
pixelorama_dispatch_output_bindings
```

This is not a generic production-output registry and not a new Verification type masquerading as a uniqueness boundary. It exists only for the already-reviewed Phase-48 Pixelorama owner.

The v1 row is keyed one-to-one by the existing dispatch execution identity:

```text
execution_id              PRIMARY KEY
claim_id                  UNIQUE
task_id
task_revision_at_start
task_content_hash
work_order_id
work_order_hash
dispatch_binding_id
dispatch_binding_hash
execution_owner_id
run_id                    UNIQUE
request_artifact_id       UNIQUE
result_artifact_id        UNIQUE
output_artifact_id        UNIQUE
output_verification_id    UNIQUE
run_verification_id       UNIQUE
output_content_hash
output_byte_count
schema_version = 1
created_at
```

Exact implementation naming may follow the repository's existing model/store naming conventions, but the semantic relation and one-to-one database constraints above are frozen.

No caller/model supplies any field except by selecting the existing `execution_id` at the later explicit adoption boundary. The binding writer derives all remaining fields from the exact already-frozen dispatch execution/claim and the exact already-revalidated `PixeloramaCliExportServiceResult`.

The relation has no mutable lifecycle status. It is immutable evidence. No update API is added.

### Why a schema migration is required here

The global `verifications` table allocates a fresh `VER-*` ID on every `record_verification(...)` call and has no uniqueness constraint over `(target, verification_type, verifier)` or over a dispatch execution/output relation. An application-level read-before-insert would therefore be raceable and could not prove exactly one durable production output for one execution.

Phase 49 deliberately uses a narrow migration with database-enforced one-to-one identities rather than changing global Verification semantics or relying on timing.

No unrelated schema is widened.

---

## 4. Binding write law and commit ordering

The Phase-48 Pixelorama invocation branch already performs strict durable result revalidation before dispatch terminalization. Phase 49 inserts exactly one binding publication step into that reviewed branch.

The normal ordering becomes:

```text
PixeloramaCliExportService.execute(...)
→ _require_pixelorama_result_durable(...)
→ persist exact immutable execution→output binding
→ mark DISPEXEC RETURNED + claim CONSUMED
→ return CompletedDispatchInvocation
```

The binding writer must independently require that:

- the execution is the exact `STARTED` Pixelorama execution currently owned by the invocation;
- the claim identity/revision and frozen Task/WorkOrder/Phase-34 binding hashes match the execution;
- `execution_owner_id` is exactly `originforge.execution.pixelorama.spritesheet-export@1`;
- the Task remains `RUNNING`;
- the Pixelorama Run is `SUCCEEDED`, role `PIXELORAMA`, and belongs to that exact Task;
- request/result/output Artifact identities and lineage exactly match the Phase-48 service contract;
- the output is exactly `SPRITESHEET_EXPORT`, status `PRODUCED`, under the exact Run;
- output and Run Verification identities, types, verifiers, PASS status, evidence, and `run_id` match the Phase-48 contract;
- the output content hash and byte count equal the independently revalidated Phase-48 result.

The writer must not weaken `_require_pixelorama_result_durable(...)`; either it consumes a typed projection produced by an equally strict internal reader or repeats the minimum exact equality checks needed to make the stored binding self-contained.

### Idempotence

For one `execution_id`:

- no existing row → insert exactly one canonical binding;
- existing row exactly equal to the canonical expected relation → return/read that row without mutation;
- existing row with any differing field → fail closed as durable ambiguity/tamper;
- a second execution may not claim the same claim, Run, request, result, output, or Verification identities because database uniqueness rejects it.

No fresh Pixelorama invocation occurs to repair a binding race or mismatch.

### Crash after binding but before RETURNED

A durable binding beside a still-`STARTED` execution does **not** authorize adoption.

This ordering intentionally allows recovery to see that exact output evidence already exists without replaying Pixelorama. Production-adoption eligibility requires both:

```text
binding exists and is exact
DISPEXEC status == RETURNED
claim status == CONSUMED
```

So a stranded pre-terminal binding is evidence for recovery, not adoption authority.

---

## 5. Binding read/currentness boundary

Add a narrow read API for one explicit `execution_id`. It returns a typed immutable projection only after exact row decoding and ID/hash/size/schema validation.

A separate production-adoption eligibility reader must join/revalidate the binding against current durable truth. It requires at minimum:

- exact binding row exists;
- exact dispatch execution exists and is `RETURNED`;
- exact execution claim exists and is `CONSUMED`;
- execution/claim frozen Task, WorkOrder, dispatch binding, owner, and hashes equal the immutable binding row;
- exact Task still exists and remains `RUNNING` for Phase 49;
- exact bound Run is still `SUCCEEDED` and belongs to the Task;
- exact request/result/output Artifact rows remain unchanged in all contract-relevant fields;
- exact output and Run PASS Verifications still match the Phase-48 verifier identities/evidence;
- exact output file still exists at the expected protected media-workspace path;
- current output bytes hash and byte count equal the bound values;
- PNG structural validation still passes.

Later runtime dependency/profile drift does not invalidate an already terminal `RETURNED` execution merely because current infrastructure configuration changed. Phase 49 judges the frozen accepted dispatch evidence, not whether the same editor invocation could be launched today.

Any durable evidence mismatch, missing row/file, symlink/path escape, hash/size drift, non-RETURNED execution, or non-CONSUMED claim fails closed before destination publication.

---

## 6. Explicit production adoption coordinator

Add a dedicated production-aware coordinator rather than weakening the legacy source verifier accepted by `GovernedPixeloramaOutputAdopter.adopt_new(...)`.

Conceptually:

```text
GovernedPixeloramaProductionOutputAdopter.adopt_new(
    execution_id,
    destination_relative_path,
)
```

The caller selects an exact production execution and a destination. It does **not** directly nominate an arbitrary source Artifact for production authority.

The coordinator:

1. reads the exact production-adoption eligibility relation for `execution_id`;
2. obtains the one bound `output_artifact_id` from durable evidence;
3. revalidates the exact source bytes immediately before copy;
4. delegates destination normalization, protected-root/symlink checks, bounded copy, concurrent-create refusal, byte rehash, create-only publication, and child Artifact creation to shared Phase-19 adoption primitives;
5. records production-specific adoption-integrity evidence that binds the new Artifact back to the exact dispatch output relation;
6. returns a typed adoption result;
7. stops without Task transition or provenance signing.

The legacy human command:

```text
adopt-new
```

keeps its existing Phase-19 verifier requirement and behavior. Phase 49 must not make an arbitrary Phase-48 `pixelorama-cli-export-integrity` Artifact directly eligible through that legacy path.

If code extraction is needed so both adopters share the safe publication mechanics, the extraction must preserve all existing Phase-19 behavior and tests byte-for-byte semantically. No generic arbitrary-file publisher is introduced.

---

## 7. Production adoption evidence

The newly adopted canonical Artifact remains:

```text
type = SPRITESHEET_EXPORT
status = ADOPTED
parent_artifact_id = exact bound Phase-48 output Artifact
created_by_run_id = exact bound Pixelorama Run
```

Its PASS adoption Verification remains structurally analogous to the Phase-19 `pixelorama-adoption-integrity` evidence but must additionally bind the exact production dispatch relation.

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
production_task_verified = false
semantic_visual_quality_verified = false
provenance_signed = false
```

It may also include exact claim/Run identifiers where useful for independent inspection, but those values must be derived from the immutable binding rather than caller input.

`production_dispatch_output_bound = true` means only that the adopted bytes are exactly the bytes bound to one terminal successful production dispatch. It is **not** a synonym for Task acceptance.

Phase 49 must not change any earlier Phase-48 Verification record from false to true. Evidence remains append-only; the new adopted Artifact gets its own acceptance/publication evidence.

---

## 8. Operator boundary

Phase 49 remains explicit and human operated.

Extend the existing module command family rather than adding an installed package script, conceptually:

```text
python -m origin_forge.pixelorama_admin_cli adopt-production-new \
  DISPEXEC-... path/to/new_asset.png
```

The exact command name may be `adopt-production-new` unless implementation discovers a repository-local argparse naming conflict; no alternative may weaken the explicit execution-ID selection law.

The command accepts only:

- project root;
- exact `DISPEXEC-*` identity;
- one new destination-relative path;
- the existing bounded source-byte limit if retained as an operator safety bound.

It does not accept:

- Run ID;
- source Artifact ID;
- source filesystem path or URI;
- verifier override;
- Pixelorama executable/profile/path;
- Task ID/status/revision;
- signing key/certificate;
- overwrite/force flag;
- automatic destination selection.

Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The cockpit remains read-only.

---

## 9. Task outcome remains outside Phase 49

Phase 49 does not record a Task PASS Verification and does not transition the Task.

After successful production adoption:

```text
Pixelorama Run = SUCCEEDED
DISPEXEC = RETURNED
claim = CONSUMED
canonical adopted Artifact exists
Task = RUNNING
production_task_verified = false
```

This separation is required by the existing runtime law: Task `SUCCEEDED` requires a passing Task Verification. Structural export integrity plus byte-safe canonical publication does not prove that the output satisfies semantic/aesthetic acceptance criteria.

Task verification/terminalization therefore remains a later separately planned authority.

Adoption failure likewise does not automatically fail the Task.

---

## 10. Provenance signing remains outside Phase 49

An adopted production Artifact may later be supplied explicitly to the existing `ProvenanceService`, exactly as Phase 19 already proves for adopted Pixelorama media.

Phase 49 itself must not:

- call `sign_artifact(...)` automatically;
- create/load private signing keys;
- add private-key material to Pixelorama or dispatch dependencies;
- set `provenance_signed = true` merely because adoption succeeded;
- equate a signature with Task acceptance.

Focused tests must prove that production adoption succeeds with no signing key configured and that no signature/provenance record is created as a side effect.

---

## 11. Concurrency, crash, and no-replay law

### Binding race

Concurrent attempts to bind one exact execution/output relation must produce one durable canonical row at most. Exact duplicate observation is idempotent; any conflicting relation fails closed.

### Destination race

Two explicit production-adoption commands targeting the same absent destination may race, but at most one canonical file/Artifact publication may succeed. The existing create-only link publication law remains authoritative.

### Same execution, different destinations

Phase 49 does not grant silent fan-out authority. One production execution/output may be canonically adopted at most once through the production path unless a later phase explicitly designs multi-destination publication. The binding/adoption store/read path must therefore reject a second production adoption for an already adopted execution/output rather than creating duplicate canonical children.

If this requires one narrow production-adoption receipt/uniqueness record in addition to the execution→output binding, implement it within the same Phase-49 persistence boundary; do not infer uniqueness by scanning filesystem children. The exact implementation must be database-enforced and independently tested before 49C is accepted.

### Crash during copy

A crash before create-only publication may leave only a bounded hidden temporary file. Normal retry may clean/recreate only that temporary copy after revalidating the exact source/binding. It may not overwrite a destination that appeared in the meantime.

### Crash after file publication but before Artifact/evidence publication

This is an ambiguous partial canonical publication and must fail closed for automatic retry. Phase 49 must either make the file/metadata publication sequence recoverably identifiable or surface an explicit operator recovery-required condition; it must never overwrite/delete an existing destination merely to make the retry convenient.

### No Pixelorama replay

No Phase-49 read, binding, adoption, retry, or recovery path invokes Pixelorama. If exact Phase-48 output is missing or ambiguous, fail closed rather than recreating it.

---

## 12. Compatibility and authority isolation

Phase 49 must preserve all existing owners and boundaries:

- code production dispatch unchanged;
- simulation production dispatch unchanged;
- Pixelorama export execution semantics unchanged except for the new post-revalidation durable binding write;
- Phase-45/46 Goal bootstrap remains code-only;
- Phase-19 legacy `adopt-new` remains explicit/create-only and retains its existing source verifier identity;
- no generic Artifact byte resolver is exposed to arbitrary production owners;
- no generic production-output registry/plugin surface is added;
- no model acquires destination/adoption/Task/signing authority;
- no fourth installed package entrypoint;
- no background adoption daemon;
- immutable v0.5 records/tag unchanged.

---

## 13. Implementation slices

Phase 49 is implemented as independently gated slices.

### 49A — immutable Pixelorama dispatch-output binding

Scope:

- add the narrow schema migration for `pixelorama_dispatch_output_bindings` or equivalently named exact table;
- add typed model/store/read projection;
- enforce one execution ↔ one claim/Run/request/result/output/output-Verification/Run-Verification relation with database uniqueness;
- exact insert-or-identical idempotence;
- reject malformed IDs/hashes/sizes/schema and conflicting duplicates;
- no invocation integration or adoption yet.

### 49B — Phase-48 invocation/recovery integration

Scope:

- after existing exact Pixelorama durable-result revalidation, persist the canonical binding before RETURNED/CONSUMED terminalization;
- preserve at-most-one Pixelorama invocation;
- add read/eligibility currentness requiring exact binding + `RETURNED` + `CONSUMED` + unchanged durable Run/Artifact/Verification/bytes;
- ensure stranded binding beside `STARTED` is recovery evidence only and cannot authorize adoption;
- integrate existing durable-output recovery without editor replay where required;
- code and simulation branches remain unchanged.

### 49C — explicit create-only production adoption

Scope:

- add `GovernedPixeloramaProductionOutputAdopter` or equivalently narrow coordinator;
- select source only through explicit `DISPEXEC-*` binding;
- share/refactor the existing Phase-19 safe publication primitive without weakening legacy `adopt-new`;
- enforce one production adoption at most for one bound execution/output with database-backed uniqueness if necessary;
- create exact child `ADOPTED` Artifact + production-bound adoption-integrity PASS evidence;
- keep Task `RUNNING`, `production_task_verified=false`, semantic-quality false, provenance unsigned;
- no signing and no Pixelorama execution.

### 49D — operator + cross-phase adversarial acceptance

Scope:

- add explicit `adopt-production-new` under `python -m origin_forge.pixelorama_admin_cli`;
- no new installed script;
- exercise real temporary-project state from Phase-48 dispatch evidence through explicit Phase-49 adoption;
- cover binding tamper/missing/duplicate, non-RETURNED execution, non-CONSUMED claim, wrong Run/output/Verification lineage, output byte drift, path/symlink/protected-root rejection, concurrent destination race, repeated adoption, crash boundaries, no replay, no signing, and no Task transition;
- prove legacy Phase-19 adoption behavior unchanged;
- prove code/simulation/Goal-bootstrap behavior unchanged.

### 49E — implementation closure / operator / roadmap

After 49A–49D are independently accepted:

- add Phase-49 implementation-closure evidence;
- update the living operator guide for explicit production Pixelorama adoption;
- insert one Phase-49 DONE block in the canonical roadmap under v1.0;
- do not rewrite immutable v0.5 release records/tag.

---

## 14. Test invariants across every slice

Every implementation slice must preserve:

1. **Exact dispatch binding.** Production adoption never trusts Task-only, Run-only, path-only, or Artifact-only correlation.
2. **Database one-to-one authority.** One execution cannot ambiguously bind multiple Pixelorama production outputs, and one output relation cannot be reused by a second execution.
3. **Terminal dispatch required.** Adoption requires exact `DISPEXEC RETURNED` and claim `CONSUMED`.
4. **No legacy backfill inference.** Pre-Phase-49 outputs without an exact durable binding are not production-adoption eligible.
5. **Exact bytes.** Bound output is re-opened/rehashed/revalidated before publication; drift fails closed.
6. **Create-only canonical publication.** No overwrite/force/edit path is introduced.
7. **Explicit operator action.** Production adoption is not a Manager/dispatcher side effect.
8. **At most one canonical production adoption per bound output.** Duplicate/fan-out publication fails closed in v1.
9. **No editor replay.** Phase 49 never invokes Pixelorama.
10. **No Task outcome authority.** Task remains `RUNNING`; no Task PASS/FAIL is synthesized.
11. **No semantic-quality claim.** Structural export/adoption evidence does not assert aesthetic acceptance.
12. **No signing authority.** No automatic signature or private-key access occurs.
13. **Legacy compatibility.** Existing Phase-19 `adopt-new`, code owner, simulation owner, and Goal bootstrap semantics do not drift.
14. **Package stability.** Installed scripts remain exactly the existing three.
15. **v0.5 immutability.** `v0.5.0` remains fixed on release commit `8ac46ee5f14654187469e79b021dbbd83992270b`.

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
- verify clean review submissions and unresolved review threads;
- verify `main` has not moved unexpectedly;
- transition draft → ready only after those gates;
- merge with an expected-head SHA guard.

A green run from a superseded head does not authorize a later mutation.

No real Pixelorama download/execution is added to normal CI. Phase 49 consumes the already durable contract and uses deterministic temporary-project fixtures for adoption/binding acceptance.

---

## 16. Stop / split conditions

Phase 49 must stop and split into a new separately planned phase if implementation requires any of the following:

- Task PASS Verification or Task terminalization;
- semantic/aesthetic image acceptance;
- provenance signing or private-key access inside adoption;
- automatic adoption from Manager/dispatcher execution;
- adoption without exact durable execution→output binding;
- inference/backfill of legacy production authority from loose Task/Run correlation;
- overwriting/editing/replacing an existing canonical asset;
- caller/model-selected source Artifact/path/URI for production adoption;
- caller/model-selected Run, verifier, Pixelorama profile, or execution dependency;
- a generic production-output registry/plugin system;
- a fourth installed package entrypoint;
- network/download/update authority;
- Pixelorama replay/re-execution;
- broad changes to global Verification uniqueness semantics;
- weakening code/simulation/Goal-bootstrap authority;
- moving/replacing the immutable `v0.5.0` tag.

A narrow schema migration needed to encode the exact one-to-one Pixelorama dispatch-output relation is **inside** Phase 49 and is not itself a split condition. Any broader schema redesign is.

If exact production output adoption cannot be implemented under these constraints, Phase 49 fails closed rather than treating structural output existence as product acceptance.

---

## 17. Planning exit condition

This planning document is the only Phase-49 planning repository delta.

Before 49A begins:

1. the exact planning head must pass the normal Python 3.12/3.13 matrix;
2. the PR diff must contain only this architecture document;
3. review submissions and unresolved threads must be clean;
4. `main` must still equal the expected Phase-48-complete base `5cfebc84d9537e1ad30a26f9a4652bc1dbd0e458`;
5. the exact planning head must be SHA-guarded merged.

Only that accepted planning merge may become the base for Phase 49A.
