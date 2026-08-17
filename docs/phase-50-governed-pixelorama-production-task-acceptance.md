# Phase 50 — Governed Pixelorama Production Task Acceptance

Status: **PLANNED — architecture frozen before implementation**

Verified planning base `main`:

```text
4435caccbc05f1cd64cca2f340e112b4a0f3dd7e
```

Immutable released v0.5 identity remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 49 closes governed Pixelorama production publication but deliberately stops before Task acceptance. After a successful Phase-49 production adoption, Origin Forge can prove that one exact terminal production dispatch produced one exact structurally verified PNG and that a human explicitly published those exact bytes create-only as one canonical project Artifact. The production Task still remains `RUNNING` because structural export correctness and safe publication do not prove that the result satisfies the Task's semantic or aesthetic acceptance criteria.

Phase 50 closes exactly that next authority gap for the already-governed Pixelorama production path:

```text
exact Phase-49 PUBLISHED production-adoption receipt
    + exact immutable Phase-48 dispatch/output binding
    + exact RETURNED execution / CONSUMED claim
    + exact current adopted Artifact bytes
    + exact Phase-49 adoption-integrity PASS evidence
    + exact still-current RUNNING production Task
    ↓
explicit human operator acceptance of that exact production result
    ↓
new immutable Pixelorama production Task-acceptance record
    + one canonical Task-targeted PASS Verification
    ↓
existing OriginForgeRuntime / OriginForgeStore Task transition law
    ↓
Task RUNNING → SUCCEEDED
```

The core rule is:

```text
vision/specialist/model evidence = advisory evidence
structural export/adoption evidence = deterministic integrity evidence
explicit human acceptance = semantic production acceptance authority
existing verification-gated Task transition = canonical SUCCEEDED authority
```

Phase 50 does not create a generic model-driven quality gate, does not allow a vision model or specialist to mark a Task complete, and does not replace the existing Task state machine. It adds one narrow human-governed acceptance path over the exact Phase-49 Pixelorama production relation.

---

## 1. Existing authorities Phase 50 must preserve

### Existing Task success law

`OriginForgeRuntime.transition_task(...)` already owns the public runtime transition boundary. Before a Task can become `SUCCEEDED`, it preserves the existing child-Task completeness law and delegates to `OriginForgeStore.transition_task(...)`.

`OriginForgeStore.transition_task(...)` already refuses `SUCCEEDED` unless at least one Task-targeted PASS Verification exists:

```text
Task target_type = TASK
Task target_id = exact Task
Verification status = PASS
```

Phase 50 must use this existing transition path. It may not update `tasks.status` directly, add a second terminal Task state, or treat a production-adoption receipt as an implicit substitute for a Task PASS.

The existing generic store check is necessary but not by itself sufficient for Phase-50 production acceptance. The Phase-50 coordinator must require its own exact production acceptance record and exact Phase-50 Task PASS before it requests the canonical `RUNNING → SUCCEEDED` transition. An unrelated historical Task PASS must never be treated as Phase-50 production acceptance.

### Phase-49 production adoption authority

Phase 49 already provides one exact database-enforced relation from production execution to output and one exact database-enforced production-adoption receipt.

The relevant durable chain is:

```text
pixelorama_dispatch_output_bindings
    execution_id
    claim_id
    task_id / frozen Task identity
    run_id
    request/result/output Artifact IDs
    output/run Verification IDs
    output hash / byte count

pixelorama_production_adoptions
    execution_id
    output_artifact_id
    destination_path
    status = PUBLISHED
    adopted_artifact_id
    verification_id
```

A finalized Phase-49 production adoption additionally proves that the adopted Artifact is the exact create-only child of the bound Phase-48 output and that its `pixelorama-production-adoption-integrity` Verification exactly matches the immutable binding and destination.

Every Phase-49 production-adoption record remains immutable historical evidence and retains:

```text
production_task_verified = false
semantic_visual_quality_verified = false
provenance_signed = false
```

Phase 50 must never rewrite those fields to `true`. Task acceptance is new append-only evidence.

### Phase-21 vision authority

Vision inspection is advisory by design. Every accepted `VisionReport` remains:

```text
semantic_findings_verified = false
advisory_only = true
```

A `vision-report-structure` or `vision-inspection-structure` PASS proves only structural binding and replayability. It does not establish semantic correctness and cannot become a Task PASS merely because its report is favorable.

Phase 50 may leave vision evidence available for human inspection, but it does not invoke vision, consume a model verdict as an acceptance decision, or promote a vision Verification into Task authority.

### Phase-16 specialist authority

Specialist reports remain bounded advisory evidence. A Reviewer or other specialist cannot declare production PASS/FAIL authority, alter Task state, or promote its own recommendation.

Phase 50 does not add a specialist voting rule, majority rule, automatic reviewer gate, or model-owned acceptance token. A human may inspect specialist evidence outside the acceptance command, but the command does not accept a specialist report as a substitute for the operator's explicit action.

### Phase-18 provenance authority

Task acceptance is not provenance signing. `ProvenanceService` remains the only signing authority. Phase 50 does not load private keys, sign the adopted Artifact automatically, or treat `SUCCEEDED` as release authorization.

---

## 2. Scope: Pixelorama production acceptance only

Phase 50 is intentionally not a generic production-output acceptance framework.

The v1 acceptance owner is exactly the already-governed Pixelorama production chain created by Phases 48 and 49. Eligibility begins from one explicit `DISPEXEC-*` identity and derives the Task and canonical adopted Artifact from durable infrastructure-owned relations.

Phase 50 does not add acceptance support for:

- code production dispatch;
- deterministic simulation production dispatch;
- legacy Phase-19 manual Pixelorama adoption not bound to a Phase-48 production dispatch;
- isolated Phase-21 image generation output;
- audio, 3D, or other media paths;
- arbitrary Artifact IDs or filesystem paths.

A future phase may generalize production acceptance only after multiple owners have independently proven compatible authority contracts. Phase 50 must not pre-build that registry.

---

## 3. Human acceptance authority

The new semantic authority is one explicit human-operated command over one exact production execution.

Conceptually:

```text
accept-production-task DISPEXEC-...
```

Executing that command means the human operator accepts the exact currently revalidated canonical Phase-49 production result as satisfying the production Task's acceptance criteria.

The model, dispatcher, Pixelorama process, vision model, specialist, Manager driver, or background service may not synthesize this human action.

The human operator does not supply a PASS status, verifier, Task ID, Run ID, Artifact ID, file path, model verdict, or destination. Those identities are derived from the exact durable `DISPEXEC-*` relation.

The initial v1 interface intentionally supports only positive acceptance. If the operator does not accept the result, the command is not run and the Task remains `RUNNING`. Phase 50 does not invent a rejection/repair/re-dispatch policy or automatically fail the Task.

---

## 4. Exact pre-acceptance currentness boundary

Before publishing any Phase-50 Task PASS, the acceptance coordinator must independently revalidate the complete production relation from the explicit execution ID to the current canonical project bytes.

At minimum it requires:

1. the exact `pixelorama_dispatch_output_bindings` row exists and passes canonical typed validation;
2. the exact dispatch execution exists, uses the frozen Pixelorama owner, and is `RETURNED`;
3. the exact claim exists and is `CONSUMED`;
4. execution/claim Task, WorkOrder, Phase-34 binding, owner, hashes, and frozen revisions still match the immutable binding;
5. the exact Pixelorama Run remains `SUCCEEDED` and belongs to the exact Task;
6. the exact request/result/output Artifacts and exact Phase-48 PASS Verifications still match the binding;
7. the exact Phase-48 source output bytes still pass the existing protected-path/hash/size/RGBA8 currentness law where that law remains part of the accepted dispatch evidence;
8. the exact `pixelorama_production_adoptions` receipt exists and is `PUBLISHED`;
9. the receipt names the exact bound output Artifact;
10. the receipt's adopted Artifact and adoption Verification IDs are present and canonical;
11. the adopted Artifact is exactly `SPRITESHEET_EXPORT`, status `ADOPTED`, parented to the bound output, and created by the exact bound Pixelorama Run;
12. the adopted Artifact's location is exactly the receipt's canonical project-relative destination;
13. the exact `pixelorama-production-adoption-integrity` PASS Verification uses `OriginForge.GovernedPixeloramaProductionOutputAdopter`, targets that adopted Artifact, binds the exact execution/claim/Run/output relation, and retains the Phase-49 false authority flags;
14. the current canonical destination is a regular non-symlinked project file at the exact adopted Artifact location;
15. the current destination bytes independently rehash to the exact adopted Artifact/binding content hash and byte count and still pass the accepted RGBA8 PNG structural validation;
16. the production Task exists and is still `RUNNING` at the exact expected post-activation revision for a first acceptance;
17. existing child Tasks, if any, are already compatible with the canonical Task success law before a new acceptance is published;
18. no conflicting Phase-50 acceptance already exists for this Task, execution, adoption receipt, or adopted Artifact.

Any mismatch fails closed before a new Task PASS is created.

No Phase-50 recovery path replays Pixelorama or republishes the canonical file to repair missing/tampered evidence.

---

## 5. Immutable production Task-acceptance relation

The generic `verifications` table intentionally allows multiple Verifications and has no uniqueness law for one production acceptance. Phase 50 therefore adds one narrow database-enforced relation for this Pixelorama authority rather than relying on read-before-insert timing.

Conceptually add:

```text
pixelorama_production_task_acceptances
```

The v1 row is immutable and one-to-one with the accepted production relation:

```text
execution_id                 PRIMARY KEY
                             REFERENCES pixelorama_production_adoptions(execution_id)
task_id                      UNIQUE
adopted_artifact_id          UNIQUE
adoption_verification_id     UNIQUE
task_verification_id         UNIQUE
task_revision_at_acceptance
accepted_content_hash
accepted_byte_count
accepted_destination_path
acceptance_authority         = HUMAN_OPERATOR
schema_version               = 1
accepted_at
```

Exact implementation naming may follow repository conventions, but these semantics are frozen.

Database constraints must prevent:

- one execution from acquiring multiple production Task acceptances;
- one production Task from being accepted through multiple Pixelorama executions in v1;
- one adopted Artifact from authorizing multiple Task acceptances;
- one Phase-49 adoption Verification from being reused for multiple Task acceptances;
- one Task PASS Verification from being attached to multiple acceptance rows.

The relation has no mutable lifecycle state and no update API. Exact duplicate publication is idempotent; any conflicting relation fails closed.

The schema migration is expected to become the next narrow schema version after Phase 49's schema 14. No unrelated table redesign or global Verification uniqueness change belongs in Phase 50.

---

## 6. Canonical Phase-50 Task PASS

The acceptance relation must reference exactly one new Task-targeted PASS Verification using frozen infrastructure-owned identities:

```text
verification_type = pixelorama-production-task-acceptance
verifier          = OriginForge.GovernedPixeloramaProductionTaskAcceptor
status            = PASS
target_type       = TASK
target_id         = exact derived production Task
```

The caller cannot override any of these values.

The v1 evidence must include at least:

```text
production_task_verified = true
semantic_visual_quality_verified = true
acceptance_authority = HUMAN_OPERATOR
production_dispatch_output_bound = true
canonical_asset_adopted = true
existing_asset_overwritten = false
provenance_signed = false
release_authorized = false

dispatch_execution_id
production_claim_id
production_run_id
source_output_artifact_id
production_adoption_verification_id
adopted_artifact_id
adopted_destination_path
accepted_content_hash
accepted_byte_count
task_content_hash
task_revision_at_acceptance
```

Every identity except the fact of the explicit human action is infrastructure-derived from current durable truth.

`semantic_visual_quality_verified = true` in this new Task PASS means the human/governance acceptance boundary has explicitly accepted the exact canonical production result against the Task contract. It does not mean a vision model became deterministic semantic authority.

The Phase-48 and Phase-49 Artifacts/Verifications remain unchanged with their earlier false flags. Evidence is append-only.

---

## 7. Atomic acceptance publication, separate canonical Task transition

Phase 50 must not create an unbound Task PASS and then separately attempt to attach it to an acceptance receipt. That would allow a crash or race to leave a generic PASS without the exact production-acceptance relation that is supposed to justify it.

The acceptance-record publication therefore uses one serialized database transaction that atomically:

1. rechecks all contract-relevant database rows needed to prove the exact Phase-49 relation has not changed since preflight;
2. confirms the Task is still the exact expected `RUNNING` Task/revision;
3. confirms no acceptance row exists, or reads an exactly identical existing row;
4. creates exactly one `VER-*` Task PASS with the frozen Phase-50 type/verifier/evidence;
5. creates exactly one immutable `pixelorama_production_task_acceptances` row referencing that Verification;
6. appends the normal `VERIFICATION_RECORDED` event for the Task;
7. commits both the Task PASS and acceptance row together.

If the exact acceptance already exists, the publisher returns the existing canonical row and does not create a second Verification.

If any uniqueness conflict or durable relation mismatch occurs, it rolls back without publishing a Task PASS.

This is a narrow serialized Verification publisher inside the existing `verifications` authority. It does not change global Verification semantics.

After that atomic acceptance publication, the coordinator revalidates the exact acceptance record and invokes the existing runtime transition path:

```text
OriginForgeRuntime.transition_task(
    task_id,
    TaskStatus.SUCCEEDED,
    expected_revision = exact current RUNNING revision,
    actor_type = HUMAN,
    ...
)
```

The existing runtime/store state machine remains the only owner of the `SUCCEEDED` mutation.

---

## 8. Crash and retry law

The acceptance PASS and immutable acceptance relation are committed before the canonical Task transition. Therefore one expected recoverable crash boundary exists:

```text
acceptance row + exact Task PASS durable
Task still RUNNING
```

A retry with the same explicit `DISPEXEC-*` must:

- read the exact acceptance row;
- require its Task PASS Verification to match every frozen Phase-50 field exactly;
- revalidate the Phase-49 production relation and current adopted bytes again;
- require the Task still be either the exact expected `RUNNING` state or already `SUCCEEDED` through this exact acceptance;
- if still `RUNNING`, call the existing canonical transition without creating a second PASS;
- if already `SUCCEEDED` and the exact Phase-50 acceptance/Verification is present, return the existing accepted result idempotently;
- fail closed for every other Task state or conflicting acceptance relation.

A retry never invokes Pixelorama, rewrites the canonical asset, reruns vision, reruns a specialist, signs provenance, or creates a second acceptance.

---

## 9. Task transition and child-Task law

Phase 50 does not weaken the existing runtime success law.

For a first acceptance:

```text
Task must be RUNNING
exact Phase-50 Task PASS must be durable
all child Tasks must satisfy existing success-terminal requirements
expected revision must still match
```

Only then may `OriginForgeRuntime.transition_task(...SUCCEEDED...)` succeed.

A stale revision, newly incomplete child, concurrent terminal transition, or Task drift causes the transition to fail according to the existing runtime/store contract. Phase 50 does not force the state or write around optimistic concurrency.

The exact acceptance row/PASS may remain as durable evidence if the crash/race happens after its atomic publication. Retry is permitted only after full exact currentness revalidation under Section 8.

Phase 50 does not automatically transition the parent Flow or Goal. Those remain under their existing authorities.

---

## 10. Advisory vision and specialist isolation

Phase 50 preserves advisory model evidence specifically by refusing to promote it into the acceptance authority surface.

The v1 acceptance command accepts no:

- `VISION-*` inspection ID;
- vision report Artifact ID;
- vision Verification ID;
- specialist contract/report ID;
- reviewer recommendation;
- model confidence/score;
- model-generated PASS/FAIL field.

A favorable structurally valid vision report cannot create a Phase-50 acceptance row, cannot create the Phase-50 Task PASS, and cannot call the Task transition.

A HIGH/CRITICAL specialist finding likewise cannot automatically fail or block the Task through Phase 50. Human/governance may inspect advisory evidence before deciding whether to execute the acceptance command, but that human judgment occurs outside the model's authority contract.

This preserves the Phase-16 and Phase-21 laws without inventing a new semantic model gate.

---

## 11. Operator boundary

Extend the existing human-operated Pixelorama admin module rather than adding a new installed script.

Conceptually:

```text
python -m origin_forge.pixelorama_admin_cli \
  accept-production-task DISPEXEC-...
```

The exact subcommand name may follow existing argparse conventions, but it must remain explicit about production Task acceptance and must require the exact `DISPEXEC-*` identity.

The command accepts only:

- project root through the existing admin CLI root mechanism;
- exact production `DISPEXEC-*` identity.

It does not accept:

- Task ID;
- Run ID;
- claim ID;
- source or adopted Artifact ID;
- filesystem path or URI;
- destination path;
- Verification ID/type/verifier/status;
- vision/specialist/model report or score;
- Pixelorama executable/profile/path;
- acceptance-criteria replacement text;
- provenance key/certificate;
- release/merge flag;
- overwrite/force flag;
- retry count or automatic redispatch instruction.

Installed package scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The cockpit remains read-only.

---

## 12. No implicit rejection or repair authority

Phase 50 closes positive acceptance only.

If the human does not accept the produced canonical asset:

```text
Task remains RUNNING
no Phase-50 Task PASS exists
no Phase-50 acceptance row exists
```

Phase 50 does not automatically:

- record Task FAIL;
- quarantine the Task;
- delete or replace the adopted Artifact;
- reopen the Phase-49 production adoption;
- replay Pixelorama;
- create a repair Task;
- select a new dispatch owner;
- ask a model to revise the asset.

A governed negative decision/repair/re-dispatch lifecycle, if needed, is a separate future authority boundary.

---

## 13. Acceptance currentness after terminalization

For read-only inspection and exact duplicate retry, Phase 50 should expose a narrow typed projection that can distinguish at least:

```text
NOT_ACCEPTED
ACCEPTED_PENDING_TASK_TRANSITION
ACCEPTED_TASK_SUCCEEDED
STALE_OR_CONFLICTING
```

Exact enum names may follow implementation conventions.

`ACCEPTED_TASK_SUCCEEDED` requires:

- one exact immutable Phase-50 acceptance row;
- one exact Task PASS Verification with the frozen type/verifier/evidence;
- exact Phase-49 binding/adoption lineage still readable as historical evidence;
- Task status `SUCCEEDED` at the expected post-transition revision;
- state-event history containing the canonical Task transition.

Read-only inspection must not perform recovery writes or invoke external tools.

Historical canonical asset changes after Task completion may be surfaced as drift by a later integrity/audit feature, but Phase 50 does not silently rewrite terminal history. During first acceptance or pending-transition retry, current adopted bytes must be exact before transition.

---

## 14. Concurrency and idempotence

### Concurrent identical acceptance

Two human/operator processes may race on the same exact execution. Database serialization and uniqueness must yield one canonical Phase-50 acceptance row and one canonical Task PASS at most.

The loser may read and return the identical canonical acceptance but may not create another PASS.

### Same Task, different executions

Phase 50 v1 does not grant fan-in or replacement acceptance. One Task may have at most one Pixelorama production Task-acceptance row. A second execution attempting to accept the same Task fails closed.

### Same adopted Artifact reused elsewhere

One adopted Artifact or Phase-49 adoption Verification may authorize at most one Phase-50 production Task acceptance.

### Concurrent Task state change

If the Task revision/status changes after acceptance preflight or acceptance publication, the existing optimistic-concurrency transition law decides the outcome. Phase 50 never force-updates the Task.

### Exact duplicate after success

A repeat command for the same exact accepted execution after the Task is already `SUCCEEDED` is idempotent only if the acceptance row, Task PASS, Task identity, and terminal transition all match exactly. Otherwise it fails closed.

---

## 15. Compatibility and authority isolation

Phase 50 must preserve all existing owners and boundaries:

- Phase-48 Pixelorama execution semantics unchanged;
- Phase-49 output binding and create-only production adoption semantics unchanged;
- legacy Phase-19 `adopt-new` unchanged and not made production-acceptance eligible;
- code production owner unchanged;
- simulation production owner unchanged;
- Phase-45/46 Goal bootstrap remains code-only;
- image/vision services remain advisory/non-terminal;
- specialist roles remain advisory/non-terminal;
- `ProvenanceService` remains the only signing authority;
- no automatic release or merge;
- no Task/Flow/Goal background terminalization daemon;
- no generic production-output or acceptance registry/plugin surface;
- no model-selected acceptance authority;
- no fourth installed package entrypoint;
- immutable v0.5 records/tag unchanged.

---

## 16. Implementation slices

Phase 50 is implemented as independently gated slices.

### 50A — immutable Pixelorama production Task-acceptance authority

Scope:

- add the narrow schema migration for `pixelorama_production_task_acceptances` or equivalently named exact table;
- add typed immutable model/read projection;
- add frozen Phase-50 Verification type/verifier constants;
- add one serialized store publisher that atomically creates exactly one Task PASS plus exactly one acceptance row;
- require exact insert-or-identical idempotence and database uniqueness across execution, Task, adopted Artifact, adoption Verification, and Task Verification;
- reject malformed IDs/hashes/sizes/revisions/schema and conflicting duplicates;
- no Task transition, operator command, vision integration, Pixelorama invocation, signing, or release yet.

### 50B — exact Phase-49 currentness + canonical Task terminalization

Scope:

- add the production Task-acceptance eligibility/currentness reader over exact Phase-48 binding + Phase-49 PUBLISHED adoption receipt + current adopted bytes + RUNNING Task;
- add `GovernedPixeloramaProductionTaskAcceptor` or equivalently narrow coordinator;
- derive all identities from explicit `DISPEXEC-*` only;
- publish/reuse the exact 50A acceptance row + Task PASS;
- invoke the existing `OriginForgeRuntime.transition_task(...SUCCEEDED...)` with the exact expected revision;
- preserve child-Task completeness and optimistic concurrency;
- implement crash retry from durable acceptance PASS + still-RUNNING Task without duplicate PASS;
- exact already-SUCCEEDED duplicate is idempotent;
- no Pixelorama replay, file mutation, signing, release, Flow/Goal transition, vision invocation, or specialist invocation.

### 50C — explicit operator acceptance boundary

Scope:

- add one explicit `accept-production-task`-style subcommand under `python -m origin_forge.pixelorama_admin_cli`;
- accept exact `DISPEXEC-*` only in addition to the existing project-root mechanism;
- do not accept Task/Run/Artifact/path/verifier/model/signing/force inputs;
- no new installed package script;
- render exact accepted Task/execution/adopted Artifact/Verification identities for operator inspection;
- repeated exact accepted command follows the 50B idempotence law.

### 50D — cross-phase adversarial acceptance

Scope:

- exercise real temporary-project state from Phase-48 production dispatch evidence through Phase-49 production adoption and Phase-50 human acceptance;
- prove exact accepted path records one Task PASS and transitions one Task to `SUCCEEDED` through the existing runtime/store law;
- cover missing/tampered dispatch binding, non-RETURNED execution, non-CONSUMED claim, stale Task revision/status, wrong Run/output lineage, missing/non-PUBLISHED adoption receipt, wrong adopted Artifact, wrong adoption Verification, destination byte drift, path/symlink drift, malformed acceptance rows, duplicate/conflicting acceptance, concurrent acceptance, stale transition revision, child-Task incompleteness, and crash after acceptance publication before Task transition;
- prove an unrelated pre-existing Task PASS is not sufficient for the Phase-50 coordinator;
- prove favorable vision structural PASS evidence cannot create/bypass production acceptance;
- prove specialist evidence cannot create/bypass production acceptance;
- prove no Pixelorama replay, no asset mutation, no signing, no release, no Flow/Goal transition, and no background action;
- prove legacy Phase-19 adoption, code owner, simulation owner, and Goal-bootstrap behavior remain unchanged;
- prove installed scripts remain exactly the existing three.

### 50E — implementation closure / operator / roadmap

After 50A–50D are independently accepted:

- add Phase-50 implementation-closure evidence;
- update the living operator guide for explicit production Task acceptance;
- insert one Phase-50 DONE block in the canonical roadmap under v1.0 after Phase 49;
- do not rewrite immutable v0.5 release records/tag.

---

## 17. Test invariants across every slice

Every implementation slice must preserve:

1. **Explicit human authority.** Only the explicit human-operated Phase-50 path can create the Phase-50 production acceptance record.
2. **Exact execution anchor.** Acceptance begins from one exact `DISPEXEC-*`, never loose Task/Run/Artifact/path correlation.
3. **Phase-49 publication required.** Acceptance requires one exact `PUBLISHED` production-adoption receipt.
4. **Exact current canonical bytes.** The adopted project file is independently re-read/rehashed/revalidated before first acceptance and pending-transition retry.
5. **Append-only authority.** Phase-48/49 false authority flags are never rewritten; Phase 50 adds new evidence.
6. **One canonical Task PASS.** Exact acceptance creates at most one frozen Phase-50 Task PASS.
7. **Database one-to-one authority.** Execution, Task, adopted Artifact, adoption Verification, and Task PASS cannot be ambiguously reused.
8. **Unbound PASS impossible through Phase 50.** The new Task PASS and acceptance row are committed atomically.
9. **Existing success transition retained.** Task `SUCCEEDED` is written only through the existing runtime/store transition law.
10. **Unrelated PASS insufficient.** The Phase-50 coordinator requires its exact acceptance record/PASS, not merely any Task PASS that satisfies the generic low-level store prerequisite.
11. **Child-Task law retained.** Existing child completion requirements remain authoritative.
12. **Crash retry is no-replay.** A durable acceptance beside RUNNING Task can resume only after exact revalidation and without creating a second PASS or replaying Pixelorama.
13. **Vision remains advisory.** Vision structural PASS or favorable model text never becomes Task acceptance authority.
14. **Specialists remain advisory.** Specialist reports never become Task acceptance authority.
15. **No rejection side channel.** Refusing to accept leaves Task RUNNING; Phase 50 does not synthesize FAIL/repair policy.
16. **No signing/release coupling.** Task acceptance does not sign provenance, merge, or release.
17. **No asset mutation.** Phase 50 does not overwrite, edit, replace, or republish canonical project files.
18. **Legacy compatibility.** Phase-19 adoption, code/simulation owners, image/vision, specialist, Goal bootstrap, and existing Task state behavior do not drift.
19. **Package stability.** Installed scripts remain exactly the existing three.
20. **v0.5 immutability.** `v0.5.0` remains fixed on release commit `8ac46ee5f14654187469e79b021dbbd83992270b`.

---

## 18. CI / merge discipline

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

No real Pixelorama download/execution, model invocation, vision invocation, specialist invocation, signing operation, or release action is added to normal CI. Cross-phase acceptance uses deterministic temporary-project fixtures and existing frozen production contracts.

---

## 19. Stop / split conditions

Phase 50 must stop and split into a new separately planned phase if implementation requires any of the following:

- model/vision/specialist-owned semantic acceptance;
- a generic production acceptance registry/plugin system;
- Task acceptance for code, simulation, image generation, audio, 3D, or other owners;
- automatic rejection, repair, redispatch, or Task FAIL policy;
- automatic acceptance from Manager/dispatcher execution;
- acceptance without exact Phase-48 binding and Phase-49 PUBLISHED adoption relation;
- caller-selected Task, Run, Artifact, path, verifier, or PASS status;
- overwriting/editing/replacing the canonical adopted asset;
- Pixelorama replay/re-execution;
- provenance signing/private-key access;
- automatic merge/release;
- automatic parent Flow/Goal terminalization;
- broad changes to global Verification uniqueness semantics;
- weakening the existing Task state machine or child-Task completion law;
- a fourth installed package entrypoint;
- network/download/update authority;
- moving/replacing the immutable `v0.5.0` tag.

A narrow schema migration and serialized publisher needed to atomically bind exactly one Phase-50 Task PASS to exactly one Pixelorama production acceptance are inside Phase 50 and are not themselves split conditions.

If the exact Phase-49 production relation cannot be safely converted into one explicit human-governed Task PASS under these constraints, Phase 50 fails closed and leaves the Task `RUNNING`.

---

## 20. Planning exit condition

This planning document is the only Phase-50 planning repository delta.

Before 50A begins:

1. the exact planning head must pass the normal Python 3.12/3.13 matrix;
2. the PR diff must contain only this architecture document;
3. review submissions and unresolved threads must be clean;
4. `main` must still equal the expected Phase-49-complete base `4435caccbc05f1cd64cca2f340e112b4a0f3dd7e`;
5. the exact planning head must be SHA-guarded merged.

Only that accepted planning merge may become the base for Phase 50A.
