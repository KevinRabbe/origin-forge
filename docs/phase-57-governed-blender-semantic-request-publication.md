# Phase 57 — Governed Blender Semantic Request Publication

Status: **FROZEN ARCHITECTURE — implementation not yet authorized by this document alone**

Phase 57 closes the missing authority boundary between an exact governed production Task with accepted game-design lineage and the pre-existing canonical Blender semantic request consumed by Phase 51.

Phase 57 does **not** redefine `MODEL3DREQ-*`, replace the Phase-20A `BlockbenchProjectSpec`, create a second 3D semantic truth, widen Planner or Manager authority, add browser authority, accept produced Blender artifacts, change Phase-53 acceptance, add release/signing authority, or authorize implementation merely by merging this document.

The core law is:

```text
exact current governed production Task
+ exact Phase-31 planning/materialization lineage
+ exact accepted Phase-56 DESIGNACC-*/DESIGNSPEC-* lineage
+ exact bounded Blender semantic-publication contract
→ immutable semantic-translation input
→ one governed proposal-only semantic translation Run
→ strict parser + independent structural/provenance audit
→ explicit HUMAN_OPERATOR publication approval
→ infrastructure freezes the exact final request identity/hash
→ create-only protected MODEL3DREQ-* publication
→ immutable Task/request publication relation
→ Phase-51 admits only that exact current Task/MODEL3DREQ-* pair
→ existing Phase-51 Blender dispatch
→ existing Phase-52 adoption / Phase-53 result acceptance
→ STOP
```

A successful Phase-57 publication states only that the exact canonical `MODEL3DREQ-*` is the explicitly human-authorized Blender semantic translation for one exact governed production Task and its exact accepted-design provenance. It does not state that Blender execution succeeded, that a produced GLB was accepted, that provenance is signed, or that release is authorized.

## 1. Authoritative base and repository facts

This architecture is frozen against exact repository base:

```text
21ceccb7ae4cbfbd363e7ba849f654c7b093a7d4
```

On that base:

- Phase 31 owns governed production planning and infrastructure-owned `FLOW-*` / `TASK-*` materialization;
- Phase 31 revalidates the exact PlanningInput / proposal / independent audit and current Goal revision/hash before materialization;
- materialized Task identity is infrastructure-owned rather than model-selected;
- Phase 56 owns accepted design-specification evidence through immutable `DESIGNACC-*` / `DESIGNSPEC-*` lineage;
- the accepted-design → PlanningInput bridge architecture preserves exact accepted-design evidence rather than replaying Planner/model semantics;
- Phase 51 already owns the canonical protected `MODEL3DREQ-*` payload, WorkOrder binding, dispatch claim, Blender execution, and dispatch-output binding;
- Phase 53 already owns the later, separate explicit human acceptance boundary for an already-produced and adopted Blender result.

The current schema line on this exact base ends at the implemented Phase-56 production-design-specification substrate. This architecture PR performs **no schema mutation**. Any Phase-57 implementation must append a new migration after the schema current on its rebased implementation base; this document does not reserve a numeric schema version against concurrent work.

## 2. The missing authority boundary

Phase 51 deliberately consumes one already-existing protected semantic request:

```text
MODEL3DREQ-*
```

Its canonical `Model3DProductionRequest` contains the Blender-production semantic payload and remains backed by the Phase-20A `BlockbenchProjectSpec` truth. The protected request registry is create-only and hash-revalidated.

That is correct and remains unchanged.

The missing relation is **not** another request format. The missing relation is durable proof that:

```text
this exact TASK-*
was derived from this exact governed planning / accepted-design lineage
and this exact MODEL3DREQ-*
was the human-authorized canonical semantic translation for that Task
```

Without that relation, a caller can potentially substitute another otherwise-valid, same-project `MODEL3DREQ-*` while still satisfying the Phase-51 request-registry and WorkOrder-shape rules.

Phase 57 closes only that substitution hole.

## 3. Permanent semantic and authority boundaries

### 3.1 `MODEL3DREQ-*` remains canonical and payload-only

Phase 57 must not add Task, planning, design-acceptance, operator, model-Run, audit, or publication fields to the canonical `Model3DProductionRequest` merely to encode provenance.

The existing request remains:

- the canonical Blender semantic payload;
- immutable after publication;
- create-only in the protected Phase-51 request registry;
- addressed by infrastructure-owned `MODEL3DREQ-*` identity;
- protected by the existing canonical payload hash/currentness rules.

All Phase-57 provenance and publication authority lives in separate immutable evidence.

### 3.2 The model is proposal-only

A semantic-translation model may propose a bounded 3D semantic payload from the exact governed input. It cannot:

- mint `MODEL3DREQ-*`;
- choose a canonical request ID;
- approve publication;
- claim audit PASS;
- choose or replace the Task;
- choose or replace accepted-design evidence;
- manufacture planning/materialization lineage;
- create WorkOrders;
- dispatch Blender;
- accept Blender outputs;
- sign provenance;
- authorize release.

No model output becomes production authority merely because it parses or is structurally valid.

### 3.3 Audit is independent but not publication authority

A strict parser and an independent structural/provenance audit are mandatory before publication approval.

Audit establishes only that the proposal is structurally valid, bounded by the exact input and contract, and provenance-consistent. Audit PASS does **not** authorize semantic publication.

### 3.4 Publication approval is explicitly human

The only Phase-57 semantic-publication approval authority is:

```text
HUMAN_OPERATOR
```

Manager, Planner, Reviewer, Visual Critic, another specialist, the browser/UI, Blender, a deterministic parser, an audit service, or the proposing model cannot synthesize that approval.

The human approves the exact audited semantic proposal for the exact Task lineage. The human does not mint the canonical request identity or rewrite request bytes after approval.

### 3.5 Infrastructure mints final canonical identity/hash

Infrastructure alone:

- constructs the final canonical `Model3DProductionRequest` from the exact audited proposal;
- allocates the final `MODEL3DREQ-*` identity;
- serializes canonical bytes;
- computes the canonical request content hash;
- freezes those exact values in durable approval/publication evidence;
- performs create-only protected-registry publication.

No operator- or model-supplied request ID/hash override is accepted.

### 3.6 Phase 53 remains downstream result acceptance

Phase-53 `HUMAN_OPERATOR` authority remains a separate later decision over an already-dispatched, already-produced, already-adopted Blender result.

Phase 53 does not:

- authorize semantic-request publication;
- repair a missing Phase-57 relation;
- select a different request for a Task;
- back-authorize an old Phase-51 WorkOrder;
- convert a historical Phase-57 publication into a current one.

Likewise, Phase 57 does not accept GLB output or terminalize a production Task.

## 4. Required immutable Phase-57 evidence families

Implementation must add distinct immutable evidence rather than overloading Phase-31, Phase-51, Phase-53, or Phase-56 rows.

The following identifiers are architecturally reserved for the Phase-57 relation; implementation may encode them through the repository's canonical typed-ID mechanism without changing their semantic roles:

```text
M3DREQIN-*    immutable semantic-translation input
M3DREQPROP-*  immutable model proposal
M3DREQAUD-*   immutable independent audit
M3DREQAPP-*   immutable HUMAN_OPERATOR publication approval
M3DREQPUB-*   immutable final Task/request publication relation
```

All five families are project-owned, immutable after creation, and content-hash validated on reads.

A model Run may produce a proposal, but infrastructure owns all durable evidence identities.

## 5. Immutable semantic-translation input

Phase 57 must construct one immutable `M3DREQIN-*` only from already-governed repository state.

Caller input must be bounded to the minimum selector needed to identify the production Task. Every provenance field is then derived by infrastructure.

At minimum the input freezes:

- `project_id`;
- exact `task_id`;
- exact Task content identity required by the canonical Task store;
- exact Phase-31 planning materialization identity (`PLMAT-*`);
- exact Phase-31 PlanningInput identity/hash (`PLINPUT-*`);
- exact governed planning lineage needed to prove the Task was materialized by that relation;
- exact accepted design acceptance identity/hash (`DESIGNACC-*`);
- exact accepted design specification identity/hash (`DESIGNSPEC-*`);
- any exact Phase-56 upstream input/hash necessary to revalidate that acceptance;
- exact Goal identity/revision/hash as derived from the planning/design lineage;
- the bounded semantic-publication operation/contract version;
- the exact canonical Phase-51 semantic request schema/operation expected for Blender `EXPORT_GLB` production;
- a canonical input/context hash over the exact material supplied to the proposal model.

The input must not infer design intent from Task prose when exact accepted-design evidence exists.

The input must not accept caller-supplied replacements for Task lineage, `DESIGNACC-*`, `DESIGNSPEC-*`, Goal revision/hash, or protected-request schema identity.

### 5.1 Task provenance must be reconstructed, not guessed

Infrastructure must prove that the exact Task was created by the exact Phase-31 materialization it records.

The proof must use the canonical durable Phase-31 materialization/Task relation and its exact PlanningInput lineage. No filename convention, list ordering, newest-row heuristic, Task description parser, UI metadata, or caller assertion may substitute for that relation.

### 5.2 Accepted-design provenance must be exact

The accepted-design evidence frozen into Phase 57 must be the same exact accepted evidence carried by the governed PlanningInput bridge for that planning lineage.

At minimum:

```text
PlanningInput accepted-design reference
== exact DESIGNACC-* identity/hash
== exact DESIGNACC-* resolved DESIGNSPEC-* identity/hash
== Phase-57 input accepted-design identity/hash
```

Any split identity, hash mismatch, wrong project, stale acceptance, or missing bridge evidence fails closed before proposal execution.

## 6. Proposal-only semantic translation

A governed Phase-57 proposal Run receives only the exact immutable translation input and a bounded projection of its accepted design semantics.

The model response is parsed into a proposal representation that can deterministically construct the existing canonical Phase-51 `Model3DProductionRequest` payload.

The proposal may contain only semantic payload fields permitted by the existing canonical request schema. It must not contain authoritative overrides for:

- `MODEL3DREQ-*` ID;
- Task ID;
- project ownership;
- PlanningInput/materialization identity;
- `DESIGNACC-*` / `DESIGNSPEC-*` identity;
- evidence hashes;
- WorkOrder ID;
- dispatch binding/claim/execution IDs;
- filesystem destination or arbitrary external path authority;
- Blender executable/profile/runtime authority;
- audit status;
- operator approval;
- release/signing authority.

Unknown or authority-bearing fields fail parsing rather than being ignored.

The exact proposal bytes, canonical parsed representation, proposal hash, model Run identity, model/provider identity allowed by policy, and exact input hash are durable before audit.

## 7. Independent structural/provenance audit

`M3DREQAUD-*` is an immutable PASS/FAIL judgment over exactly one `M3DREQIN-*` and one `M3DREQPROP-*`.

A PASS must independently establish at least:

- project ownership is exact across all evidence;
- the Task is exactly the Task frozen by the input;
- the Task still reconstructs through the exact recorded Phase-31 materialization/PlanningInput relation;
- accepted-design identities/hashes exactly match the PlanningInput lineage;
- the accepted-design relation is current under the Phase-56 currentness rules used by the bridge;
- proposal input hash matches the immutable translation input;
- proposal bytes/hash are canonical and unchanged;
- proposal fields are within the existing Phase-51 semantic request schema;
- operation remains the supported Blender `EXPORT_GLB` semantic operation;
- the proposal does not encode caller-selected IDs, runtime paths, dispatch authority, acceptance authority, signing, release, or other forbidden authority;
- deterministic construction of the canonical request payload is possible without another model call.

The auditor must not repair malformed output by inventing fields or consulting a model.

Audit evidence is not human semantic approval.

## 8. Human publication approval and final request reservation

The operator approves exactly one audited proposal for exactly one Task lineage.

Before first approval, infrastructure must reload and revalidate:

```text
M3DREQIN
+ M3DREQPROP
+ PASS M3DREQAUD
+ current Task/planning lineage
+ current accepted-design lineage
```

If any relation is stale or conflicting, approval fails closed.

### 8.1 Approval freezes the final canonical target

To make cross-store recovery deterministic, the durable `M3DREQAPP-*` must freeze the final protected-request target **before** the protected-registry write can become the only durable fact.

Canonical order:

```text
revalidate exact input/proposal/PASS audit/currentness
→ infrastructure allocate final MODEL3DREQ-* ID
→ infrastructure construct exact canonical request bytes
→ infrastructure compute exact canonical request hash
→ atomically persist immutable HUMAN_OPERATOR approval
   including exact final request ID/hash and proposal lineage
→ protected-registry publication
→ immutable M3DREQPUB-* relation
```

The approval therefore binds at minimum:

- approval identity/hash;
- `project_id`;
- exact `task_id`;
- exact input/proposal/audit identities/hashes;
- exact planning materialization/PlanningInput identities/hashes;
- exact `DESIGNACC-*` / `DESIGNSPEC-*` identities/hashes;
- `acceptance_authority = HUMAN_OPERATOR` for this publication decision;
- operator/audit actor metadata permitted by repository policy;
- exact final infrastructure-owned `MODEL3DREQ-*`;
- exact canonical request content hash;
- exact canonical semantic payload hash or canonical bytes reference needed for deterministic reconstruction;
- exact request schema/operation contract identity;
- immutable approval timestamp/schema identity.

The operator is approving the exact semantic proposal; infrastructure is recording the resulting exact canonical request target. The operator cannot supply a different ID/hash or mutate canonical bytes between approval and publication.

### 8.2 One final publication per exact production Task

Phase 57 must fail closed against competing final semantic publications for one exact materialized production Task.

Multiple proposal/audit attempts may exist before approval, but once a canonical publication is finalized for that Task, a second different `MODEL3DREQ-*` must not become another dispatch-current interpretation of the same Task.

If governed semantics genuinely change, upstream accepted-design/planning state must change and normal governance must produce a new applicable planning/Task lineage. Phase 57 must not use mutable replacement rows or “latest publication wins” semantics.

## 9. Protected request publication and crash recovery

The protected Phase-51 request registry remains the only canonical store for `MODEL3DREQ-*` request payloads.

Phase 57 does not add a competing request store.

After immutable approval exists, publication is:

```text
read exact M3DREQAPP-*
→ reconstruct/verify exact approval-frozen MODEL3DREQ-* bytes/hash
→ publish create-only into existing protected Phase-51 registry
→ reread by exact request ID
→ verify exact bytes/hash/schema
→ persist immutable M3DREQPUB-* relation
```

### 9.1 Idempotent protected-registry behavior

For the approval-frozen request ID:

- if the request is absent, create exactly the approved canonical bytes;
- if the exact request already exists and its canonical bytes/hash match approval, reuse it;
- if the ID exists with any different bytes/hash/schema/ownership, fail closed;
- never scan the request directory to guess which request belongs to the approval;
- never allocate a replacement request ID merely because recovery encountered an uncertain prior write.

### 9.2 Recoverable cross-store crash windows

SQLite evidence and a protected filesystem registry cannot be assumed to commit atomically together. Phase 57 therefore makes recovery explicit.

#### Crash before durable approval

No canonical request publication is authorized. Recovery reuses durable input/proposal/audit evidence, revalidates currentness, and requires the normal explicit operator approval path. It does not rerun the model merely to recreate already-durable proposal bytes.

#### Crash after approval, before request creation

Recovery reads exact `M3DREQAPP-*`, reconstructs the exact approval-frozen request ID/bytes/hash, and performs the missing create-only registry write. No model replay and no new operator decision are required for the same exact approval.

#### Crash after request creation, before `M3DREQPUB-*`

Recovery reads exact approval, resolves the exact frozen `MODEL3DREQ-*` directly by ID, requires exact byte/hash equality, then persists the missing immutable publication relation.

The existence of the request file alone does **not** authorize dispatch. Phase-51 admission requires the final immutable Phase-57 publication relation.

#### Crash after final publication

Recovery rereads and revalidates the exact immutable relation and returns it idempotently. Any split identity or drift fails closed.

At no recovery point may Phase 57 rerun the proposal model merely to recover publication state.

## 10. Immutable final publication relation

`M3DREQPUB-*` is the durable authority connecting one exact Task to one exact canonical request.

It freezes at minimum:

- publication identity/hash;
- `project_id`;
- exact `task_id`;
- exact Task content/revision identity necessary for canonical revalidation;
- exact Phase-31 materialization identity;
- exact `PLINPUT-*` identity/hash;
- exact accepted-design `DESIGNACC-*` identity/hash;
- exact accepted `DESIGNSPEC-*` identity/hash;
- exact `M3DREQIN-*` identity/hash;
- exact `M3DREQPROP-*` identity/hash;
- exact PASS `M3DREQAUD-*` identity/hash;
- exact `M3DREQAPP-*` identity/hash;
- exact `MODEL3DREQ-*` identity/hash;
- exact semantic request schema/operation identity;
- infrastructure publisher identity/version as appropriate;
- immutable publication timestamp/schema identity.

The publication row cannot be updated into another Task/request relation and cannot be deleted as a way to erase history.

## 11. Publication currentness is derived, never stored

Phase 57 must not add a mutable `is_current` flag.

A publication is dispatch-current only when fresh reads reconstruct the complete exact relation.

At minimum currentness requires:

1. the publication and every referenced Phase-57 evidence object are present, canonical, immutable, and hash-valid;
2. the exact protected `MODEL3DREQ-*` exists and its canonical content hash exactly matches publication/approval;
3. the exact Task still belongs to the same project and reconstructs through the exact recorded Phase-31 planning materialization/PlanningInput lineage;
4. the exact accepted-design reference carried by that PlanningInput matches the publication's `DESIGNACC-*` identity/hash;
5. that acceptance resolves to the same exact `DESIGNSPEC-*` identity/hash;
6. the accepted-design evidence remains current under the Phase-56 currentness rules on the exact upstream Goal/design-rule/project-intelligence evidence;
7. canonical Task/flow routing has not made the recorded Task historical or otherwise ineligible for new production dispatch;
8. no conflicting final Phase-57 publication exists for the Task;
9. the requested Phase-51 Task/request pair exactly equals this publication relation.

Currentness readers must use canonical stores and exact identities. They must not select `MAX(created_at)`, directory order, newest UUID, UI state, a caller-provided “current” boolean, or semantic similarity.

### 11.1 Historical evidence remains immutable

If Goal, accepted-design, planning, Task routing, or another upstream authority is superseded, the old Phase-57 evidence remains historical and inspectable.

It is not rewritten, relinked, deleted, or silently migrated to a new Task/request pair.

Historical publication is simply inadmissible for **new** Phase-51 dispatch.

Existing downstream historical execution/adoption/acceptance evidence remains governed by its own phase-specific historical rules and is not retroactively rewritten by Phase 57.

## 12. Phase-51 admission integration

Phase 51 gains only the minimum read-only admission/currentness dependency needed to prove the exact Task/request publication relation.

It does not gain Phase-57 publication authority.

### 12.1 WorkOrder admission law

Before a new Blender WorkOrder can become dispatch-admissible:

```text
requested TASK-*
+ requested MODEL3DREQ-*
→ resolve exact Phase-57 publication for TASK-*
→ require publication dispatch-current
→ require publication.task_id == requested task_id
→ require publication.model3d_request_id == requested MODEL3DREQ-*
→ require exact request hash equality
→ then continue existing Phase-51 WorkOrder/binder rules
```

A different otherwise-valid `MODEL3DREQ-*` is rejected even if:

- it is in the same project;
- it is structurally valid;
- its protected-registry hash is valid;
- it has the right `EXPORT_GLB` operation;
- its `BlockbenchProjectSpec` could plausibly satisfy the Task.

Semantic plausibility is not publication authority.

### 12.2 No caller-selected publication fallback

The Phase-51 caller may not bypass Task lookup by presenting an arbitrary publication ID and asking infrastructure to trust it.

Infrastructure must resolve/revalidate the relation from canonical exact Task/request evidence and reject missing, ambiguous, historical, cross-project, or conflicting relations.

### 12.3 Revalidation before execution

A WorkOrder that was valid when created may become stale before claim/start if its Phase-57 upstream publication ceases to be dispatch-current.

The existing Phase-51 currentness/claim/start path must therefore include a fresh exact Phase-57 publication revalidation at the authoritative pre-execution boundary.

If the publication is no longer current, Blender execution does not start.

This check supplements rather than replaces existing Phase-51 Task revision/hash, protected request, WorkOrder, binding, claim, capability, contract, runner, and workspace currentness.

### 12.4 Existing Phase-51 durable shapes remain stable unless implementation proves otherwise

The preferred integration is a read-only admission/currentness check around the existing WorkOrder/request relation. Phase 57 should not widen the canonical `Model3DProductionRequest` payload or duplicate Task/design provenance into that payload.

If implementation discovers that exact crash-safe revalidation requires one additional immutable reference in a downstream binding, that must be justified as a separate bounded implementation decision and must not weaken any authority boundary frozen here.

## 13. Operator surface

Phase 57 may expose a bounded module/operator surface for the explicit human publication decision, but it must not expose an arbitrary semantic-authority construction CLI.

A compliant operator surface may conceptually support:

```text
inspect exact Task semantic-publication candidate
approve exact audited candidate
recover/finalize exact approved publication
inspect exact publication/currentness
```

It must derive authoritative identities from durable evidence and must not accept arbitrary overrides for:

- project ownership;
- Task/planning lineage;
- accepted-design lineage;
- proposal/audit PASS evidence;
- final request ID/hash;
- protected-registry path;
- WorkOrder/claim/execution authority;
- Blender runtime path;
- Phase-53 acceptance;
- signing/release authority.

No browser or Manager path acquires Phase-57 `HUMAN_OPERATOR` authority merely because an operator CLI exists.

## 14. Read-only inspection requirements

Implementation must provide exact read-only projections sufficient to answer, without creating evidence:

- what accepted-design/planning lineage an exact Task carries;
- whether a Phase-57 translation input/proposal/audit exists;
- whether an exact proposal has independent PASS audit;
- whether an explicit operator approval exists;
- which exact `MODEL3DREQ-*` identity/hash that approval froze;
- whether the protected request exists and is byte/hash exact;
- whether final `M3DREQPUB-*` exists;
- whether that publication is dispatch-current;
- why a publication is historical/stale/conflicting;
- whether a proposed Phase-51 Task/request pair exactly matches the current publication.

Inspection must not repair, publish, rerun a model, create approval, or mutate currentness.

## 15. Required fail-closed adversarial coverage

Phase-57 implementation is not complete until tests prove at least the following.

### Provenance and substitution

- valid `MODEL3DREQ-*` from another Task is rejected;
- valid same-project competing `MODEL3DREQ-*` is rejected;
- valid publication from another project is rejected;
- Task ID substitution is rejected;
- planning materialization / PlanningInput substitution is rejected;
- `DESIGNACC-*` substitution is rejected;
- `DESIGNSPEC-*` substitution is rejected;
- cross-project design evidence is rejected;
- proposal input-hash drift is rejected;
- proposal byte/hash drift is rejected;
- audit evidence drift or wrong proposal/input binding is rejected.

### Authority

- proposal model cannot approve publication;
- audit PASS alone cannot publish;
- Manager cannot synthesize approval;
- browser/UI/conversation authority cannot synthesize approval;
- Phase-53 result acceptance cannot back-authorize publication;
- caller-supplied final request ID/hash is rejected;
- caller-supplied protected request path is rejected;
- arbitrary runtime/executable/path authority is rejected.

### Currentness

- stale accepted-design lineage blocks proposal/publication as appropriate;
- stale/replaced planning lineage blocks new publication/dispatch;
- historical Task routing blocks new dispatch;
- protected-request byte/hash drift blocks currentness;
- missing final publication relation blocks Phase-51 admission even if the request file exists;
- old historical publication cannot authorize a new WorkOrder;
- WorkOrder valid at creation but stale before execution fails closed at revalidation.

### Uniqueness and ambiguity

- a second conflicting final publication for one exact Task is rejected;
- split identities across approval/request/publication are rejected;
- duplicate exact retry returns/reuses canonical evidence idempotently rather than creating parallel authority;
- no newest-row or directory-scan fallback resolves ambiguity.

### Recovery

- crash after durable proposal does not rerun the model merely to recover proposal bytes;
- crash after PASS audit reuses exact proposal/audit evidence;
- crash after operator approval but before request creation publishes the exact approval-frozen request;
- crash after request creation but before final publication verifies the exact request and completes the relation;
- conflicting request bytes under the approval-frozen ID fail closed;
- completed publication retry returns exact durable evidence without model replay or second operator decision.

## 16. Implementation slices

Implementation remains blocked until this architecture document itself passes the normal exact-head review/CI gate and is merged.

Once authorized, the intended bounded slices are:

### Phase 57A — immutable input / proposal / audit substrate

- typed Phase-57 IDs/models;
- append-only evidence migration on the then-current schema line;
- exact Task → Phase-31 → accepted-design lineage resolver;
- immutable semantic-translation input;
- bounded proposal-only model Run integration;
- strict parser;
- independent structural/provenance audit;
- read-only inspection/currentness foundations;
- focused adversarial tests.

### Phase 57B — explicit approval / protected publication / recovery

- explicit `HUMAN_OPERATOR` approval primitive;
- infrastructure-owned final `MODEL3DREQ-*` reservation;
- exact canonical request construction/hash;
- create-only protected-registry publication through existing Phase-51 authority;
- immutable final `M3DREQPUB-*` relation;
- deterministic crash recovery/idempotence;
- module/operator surface with no authority widening;
- focused adversarial tests.

### Phase 57C — Phase-51 Task/request admission and execution revalidation

- read-only Phase-57 publication resolver at Blender WorkOrder admission;
- exact Task/request/hash match requirement;
- fresh publication-currentness revalidation at the authoritative pre-execution boundary;
- competing-request and historical-publication rejection;
- no changes to Blender execution semantics beyond admission/currentness;
- focused Phase-51 integration/adversarial tests.

### Phase 57D — closure

- exact-head Python 3.12/3.13 canonical CI;
- implementation closure document;
- operator/currentness documentation if needed;
- roadmap/docs synchronization only if separately authorized and bounded;
- no unrelated prototype, release, UI, packaging, or runtime widening.

Each slice must be independently reviewable. A later slice must not be smuggled into an earlier one to make tests easier.

## 17. Explicit non-goals

Phase 57 does not implement or authorize:

- a new canonical 3D semantic schema replacing Phase 20A;
- Task prose → ungoverned JSON conversion;
- direct model publication into `.origin-forge/model3d-requests/`;
- arbitrary JSON/path request creation CLI;
- user-selected `MODEL3DREQ-*` identity;
- a second protected request registry;
- “latest request wins” behavior;
- mutable publication/current flags;
- automatic retranslation after upstream drift;
- model replay as a recovery primitive;
- Blender execution changes beyond exact admission/currentness integration;
- Phase-52 adoption changes;
- Phase-53 production result acceptance changes;
- Manager auto-approval;
- browser/UI semantic-publication authority;
- provenance signing;
- merge/deploy/release authority;
- production recovery beyond this exact semantic-publication relation;
- unrelated v0.6/v0.9 prototype work.

## 18. Completion law

Phase 57 is complete only when the repository can prove the following without trusting caller substitution or model authority:

```text
For one exact governed production TASK-*:

1. infrastructure reconstructs its exact Phase-31 materialization / PlanningInput lineage;
2. that lineage resolves the exact current accepted DESIGNACC-*/DESIGNSPEC-* evidence;
3. one bounded model Run may propose Blender semantic payload only;
4. strict parsing and independent provenance audit bind the exact proposal to that exact input;
5. a HUMAN_OPERATOR explicitly approves publication of that exact audited semantic proposal;
6. infrastructure alone freezes and publishes the exact canonical MODEL3DREQ-* identity/hash;
7. immutable M3DREQPUB-* binds the exact Task, upstream provenance, approval, and request;
8. recovery can finish publication from durable evidence without model replay;
9. currentness is freshly derived and stale upstream evidence makes the publication historical for new dispatch;
10. Phase 51 admits and starts Blender work only for the exact current Task/MODEL3DREQ-* pair;
11. a different otherwise-valid MODEL3DREQ-* cannot be substituted;
12. Phase 53 remains the separate downstream human result-acceptance authority.
```

That is the entire Phase-57 authority expansion. Everything beyond it remains false until a later governed phase explicitly establishes it.
