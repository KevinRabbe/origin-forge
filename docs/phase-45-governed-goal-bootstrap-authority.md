# Phase 45 — Governed Goal Bootstrap Authority & Single Materialization

Status: **PLANNED — architecture only; no Goal bootstrap implementation yet**

Phase 45 closes the remaining authority gap between one durable canonical Goal and the already-proven Phase-39/40/41/42/43/44 Manager production path.

Verified prerequisite `main`:

```text
092fc4c2ca5b09a969a7bfa2a34e82dcd91e9207
```

The prerequisite audit proves that the downstream production coordinator is not missing scheduling logic. The missing authority is upstream: existing APIs can freeze a Phase-31 PlanningInput, invoke the bounded Planner, independently audit a proposal, materialize canonical work, construct Phase-32/33 authority, and publish a Phase-39 PREPPOL, but no production boundary owns that complete Goal → Manager bootstrap relation.

Phase 45 adds one explicit, durable, fail-closed bootstrap authority. It does not turn the Planner into approval authority and it does not widen Manager execution authority.

Core rule:

```text
explicit exact Goal bootstrap request
        ↓
code-owned bootstrap authority + current Goal revision
        ↓
exact dispatch-safe CAPCAT / CAPPOL / DISPCAT authority
        ↓
code-owned PlanningInput evidence derivation
        ↓
durable PLANNER_STARTED no-replay checkpoint
        ↓
one existing bounded Goal Planner call
        ↓
independent Phase-31 structural audit
        ↓
explicit bootstrap authority materializes exactly one passing proposal
        ↓
exact Phase-39 PREPPOL publication
        ↓
READY FOR EXISTING MANAGER
        ↓
STOP
```

A successful bootstrap creates governed production authority for the exact Goal revision. It does **not** call the Manager, execute a Task, acquire a dispatch claim, reinterpret Task outcomes, adopt/sign an Artifact, mutate Project Intelligence, merge, or release.

---

## 1. Verified missing boundary

The current repository deliberately separates the existing authority surfaces.

### Phase 31

Phase 31 provides:

- exact Goal-bound `PLINPUT-*` evidence;
- one proposal-only `BoundedProductionPlanner` call;
- strict `PLPROP-*` parsing;
- independent `PLAUD-*` recomputation;
- explicit atomic `PLMAT-*` materialization;
- canonical Task dependencies and readiness.

Its contract explicitly states that a successful Planner Run does not audit or materialize itself. A structural audit PASS is not approval or materialization authority. The read-only planning CLI exposes no generate/materialize command.

### Phase 32

Phase 32 provides immutable capability inventory and explicit static routing policy, but inventory alone grants no routing authority. The caller currently chooses an already-persisted `CAPCAT-*` / `CAPPOL-*` pair when freezing a governed PlanningInput.

### Phase 33

Phase 33 provides immutable dispatch contracts and proposal-only WorkOrders. The current reviewed built-in dispatch catalog supports the bounded code adapter:

```text
adapter     originforge.code.bounded-retry
capability  code.change
contract    code.bounded-retry@1
```

Other built-in Phase-32 adapters remain intentionally deferred until exact Phase-33/34 input-evidence resolution exists. Therefore a Goal bootstrap must not advertise all Phase-32 inventory as currently executable Manager authority.

### Phase 39

Phase 39 begins from one explicit immutable `PREPPOL-*` over an already-existing exact `PLMAT / PLINPUT / CAPCAT / CAPPOL / DISPCAT` relation. Its constructor deliberately allows the caller to choose that already-persisted relation while preventing caller selection of Task, adapter, model profile, runtime provider, WorkOrder payload, binder, or process authority.

### Phase 40 and later Manager phases

The Manager consumes already-admissible preparation/dispatch authority. It does not create PlanningInputs, call the Goal Planner, audit/materialize a plan, select/publish capability authority, build dispatch-contract inventory, or create PREPPOL.

Phase-40 acceptance currently constructs the full upstream chain manually before Manager admission becomes actionable:

```text
Goal
→ CAPCAT/CAPPOL
→ PLINPUT
→ PLPROP
→ PLAUD
→ PLMAT
→ DISPCAT
→ PREPPOL
→ Manager
```

That manual fixture chain is the acceptance-level proof of the missing production authority.

### Phase 44

The operator surface exposes only governed Manager status and bounded Manager advancement. Phase 45 does not change those commands or packaging behavior.

---

## 2. Goal

Phase 45 v1 must provide one explicit infrastructure-owned operation that can take one existing canonical Goal revision from “not yet bootstrapped for production” to “one exact current PREPPOL exists for one exact materialized plan” without caller-selected downstream authority.

Conceptual public operation:

```text
bootstrap_goal_once(runtime, goal_id)
```

The exact final module/API name is implementation-owned, but the authority shape is fixed:

```text
caller may choose:   one canonical GOAL-* only
caller may not choose:
    CAPCAT / CAPPOL / DISPCAT IDs
    allowed capability IDs
    adapter IDs
    Planner model/profile/runtime
    PlanningInput evidence hashes
    PLPROP / PLAUD / PLMAT IDs
    PREPPOL owner/model strategy
    Task ID
    WorkOrder payload
    Manager action
```

The operation performs one bounded bootstrap progression and then stops. It never invokes `advance_production_manager_once()` or the Phase-44 bounded Manager driver.

---

## 3. Explicit authority expansion

Phase 31 intentionally left materialization behind separate explicit authority. Phase 45 supplies that missing authority in a narrow form.

The authorization statement is:

> An explicit Phase-45 bootstrap request for one exact current Goal revision authorizes infrastructure to obtain exactly one bounded proposal from the code-owned Goal Planner, independently audit it against the frozen PlanningInput, and materialize that proposal only if the independently recomputed audit is PASS and all bound authority is still current.

This is **not Planner self-approval**.

The Planner remains proposal-only:

```text
model proposes
infrastructure parses
infrastructure independently audits
explicit bootstrap authority decides whether the exact passing proposal may materialize
```

A Planner response can never directly set canonical IDs, statuses, verification results, approval flags, routing policy, dispatch contracts, PREPPOL authority, Manager action, merge, or release state.

Phase 45 v1 does not add a semantic correctness oracle. Materialization means the bounded proposal became canonical work under the explicit bootstrap request; production Task verification remains authoritative for whether that work later succeeds.

---

## 4. New durable bootstrap identity

Reserve one infrastructure-owned identity family:

```text
GOALBOOT-*   durable per-Goal bootstrap receipt
```

No model or caller chooses the identity.

The receipt is the authority and recovery spine for one exact Goal revision. It must bind at least:

```text
bootstrap_id
project_id
goal_id
goal_revision
goal_content_hash
bootstrap_owner_id/bootstrap_owner_fingerprint
bootstrap_contract_version
capability_catalog_id/hash
capability_routing_policy_id/hash
dispatch_contract_catalog_id/hash
planning_input_id/hash
planner_dependency_plan_hash
planner_run_id
plan_proposal_id/hash
plan_audit_id/hash
materialization_id/hash
preparation_policy_id/hash
stage
status
revision
created_at / updated_at
terminal_reason
```

Fields become non-null only after their corresponding durable checkpoint. Once set, authority-bearing identities/hashes are immutable.

A schema migration should enforce bounded stage/status relations and protect concurrent ownership for the same exact Goal revision.

Suggested stages:

```text
CLAIMED
AUTHORITY_PUBLISHED
PLANNING_INPUT_PUBLISHED
PLANNER_STARTED
PLANNER_RETURNED
PLAN_AUDITED
MATERIALIZED
PREPPOL_PUBLISHED
```

Suggested statuses:

```text
ACTIVE
READY
FAILED_PRE_PLANNER
INTERRUPTED
```

`READY` requires `stage == PREPPOL_PUBLISHED` and an exact current PREPPOL relation.

`ACTIVE + PLANNER_STARTED` without a trustworthy later planner checkpoint is recovery-required. It is never automatically expired or stolen.

---

## 5. Bootstrap ownership and code-owned policy

Phase 45 requires a code-owned bootstrap owner descriptor analogous in governance shape to Phase-39 preparation ownership, but dedicated to Goal planning.

Conceptual v1 descriptor:

```text
owner_id:                originforge.bootstrap.goal-planner@1
planner_contract:        BoundedProductionPlanner.propose@1
planner_request_version: 1
semantic_model_role:     CODER_STRONG
supported_adapter:       originforge.code.bounded-retry
supported_capability:    code.change
supported_dispatch:      code.bounded-retry@1
```

The exact identifiers/fingerprint algorithm are implementation details frozen by source/tests.

The descriptor is inert metadata. It contains no callable/import path, shell, argv, executable path, endpoint, credential, secret, model file, container image, or process authority.

The bootstrap owner fingerprint must commit to the exact reviewed v1 authority contract so source/config drift fails closed.

### Why `CODER_STRONG` in v1

The current model-role registry has no independent `PLANNER` role. The only current production-preparation planner authority uses the protected `CODER_STRONG` semantic role. Phase 45 v1 may reuse that role while keeping profile selection/fallback inside existing Phase-14 protected configuration.

Phase 45 must not allow the caller to pick a profile, model ID, runtime provider, endpoint, or fallback sequence.

A future dedicated Planner role is a separate authority/configuration change and is not required for Phase 45 v1.

---

## 6. Dispatch-safe capability authority

Phase 45 must derive, never accept from the caller, the exact production capability surface exposed to the Goal Planner.

V1 authority is intentionally narrower than the complete built-in Phase-32 inventory.

The bootstrap may build/publish a normal current built-in Phase-32 catalog, but the bootstrap-owned routing policy exposed through the PlanningInput must allow only the capability/adapter relation that is also supported by the current reviewed Phase-33 dispatch catalog and Phase-39 preparation owner.

For current `main`, that means exactly:

```text
allowed capability: code.change
ordered adapter:    originforge.code.bounded-retry
```

The Phase-33 dispatch catalog must resolve exactly the matching `code.bounded-retry@1` contract.

The implementation must independently cross-check all three authority layers:

```text
Phase-32 adapter/capability
        ∩
Phase-33 dispatch contract
        ∩
Phase-39 code-owned preparation owner
```

If the intersection is empty, ambiguous, stale, fingerprint-mismatched, or broader than the frozen v1 bootstrap contract, bootstrap fails before the Goal Planner model call.

This prevents a valid Phase-31 proposal from materializing media/runtime Tasks that the current Manager path cannot prepare or dispatch.

No fuzzy capability matching, hidden adapter composition, “best available” fallback, installed-tool discovery, or filesystem-order selection is allowed.

---

## 7. Infrastructure-owned authority publication

The explicit Goal bootstrap request owns creation/publication of the exact capability/dispatch authority used by that bootstrap attempt.

It must not require an operator to pre-create or pass IDs for:

```text
CAPCAT-*
CAPPOL-*
DISPCAT-*
```

The implementation may reuse exact current immutable evidence only through a bounded content/relationship validation path; it may never select “the first file,” “the newest object,” or “the only object currently on disk” as authority.

A simpler acceptable v1 implementation is to publish fresh infrastructure-owned immutable authority objects for the winning GOALBOOT attempt and bind their exact IDs/hashes into the receipt. Immutable orphan evidence after a pre-checkpoint crash is acceptable if it grants no authority and later recovery remains bounded; hidden inference from orphan ordering is not.

Concurrent bootstrap calls for the same exact Goal revision must produce one durable winning bootstrap owner. A losing caller must not publish a second Planner invocation or fall through to another Goal.

---

## 8. PlanningInput evidence must be derived, not supplied

The existing governed PlanningInput constructor expects exact evidence including:

```text
Project Intelligence hash
model-policy hash
resource-policy hash
CAPCAT/CAPPOL authority
optional verified-state / Design Rule refs
```

Phase-45 production bootstrap may not accept opaque caller-supplied hashes for these fields.

It must derive them from current protected project state using code-owned finite canonical projections.

Required rules:

1. CAPCAT/CAPPOL values come from the exact bootstrap-owned Phase-32 authority relation.
2. model/resource policy hashes come from the exact current protected configuration and must commit to the selection/resource policy actually available to the Goal Planner.
3. Project Intelligence evidence must be a deterministic bounded hash of the current governed Project Intelligence state/projection selected by infrastructure. If no existing public canonical helper exposes the exact required hash, Phase 45 may add/factor a pure bounded hasher without widening Project Intelligence mutation authority.
4. active Design Rule / verified-state evidence, if included, must come from bounded code-owned current-state readers with exact IDs/hashes/revisions. V1 may deliberately use an empty optional set where the existing PlanningInput contract permits it rather than inventing or trusting opaque references.
5. no secret bytes, arbitrary repository file contents, mutable handles, unrestricted Verification blobs, or database handles enter PlanningInput evidence.

The resulting `PLINPUT-*` is published before the Goal Planner boundary and is bound into GOALBOOT.

Any Goal revision/hash change before Planner invocation or materialization invalidates the bootstrap attempt.

---

## 9. Code-owned Goal Planner dependency assembly

Phase 31 correctly requires a governed `ScheduledModelAdapter` for real Planner inference, but the current Planner constructor receives that adapter from its caller. Phase 45 must remove that caller authority for production bootstrap.

Add a protected bootstrap dependency assembler that:

- loads current protected config;
- resolves the code-owned bootstrap owner’s semantic model role;
- validates the exact Phase-14 selection policy and ordered profile/fallback chain;
- validates profile → runtime-provider bindings;
- binds provider fingerprints and relevant config hashes;
- constructs only lazy governed scheduler/runtime-loader objects;
- returns the exact `ScheduledModelAdapter` for the Goal Planner;
- acquires no resource lease and loads no model before the explicit Planner boundary.

Before model execution, persist a deterministic `planner_dependency_plan_hash` committing to at least:

```text
bootstrap owner identity/fingerprint
planner request/contract version
config version
resource/model policy hash
ordered model profile IDs
runtime IDs/provider fingerprints
model runtime config fingerprint
```

The caller never supplies any of these values.

Where existing Phase-39 preparation assembly hashing/config projection is semantically identical, Phase 45 should factor/reuse common pure helpers rather than create conflicting hash definitions. It must not weaken Phase-39 source seals or alter existing WorkOrder-planner authority as a side effect.

---

## 10. Planner no-replay fence

Phase 41 established the accepted crash-safety pattern for a model-backed planning boundary:

```text
reconstruct exact current authority
        ↓
durable compare-and-swap PLANNER_STARTED
        ↓
only the CAS winner may call the model once
        ↓
checkpoint trustworthy return
```

Its implementation is PREP/WorkOrder-specific and is not directly reused as Goal authority. Phase 45 must reuse the **semantic pattern**.

Required ordering:

1. acquire exact GOALBOOT ownership for one current Goal revision;
2. publish/checkpoint exact CAPCAT/CAPPOL/DISPCAT authority;
3. derive/publish/checkpoint exact PlanningInput;
4. assemble and hash the code-owned Goal Planner dependencies;
5. durably advance GOALBOOT to `PLANNER_STARTED` by expected receipt revision;
6. only that CAS winner invokes the existing bounded Goal Planner exactly once;
7. after trustworthy return, durably checkpoint the exact Planner Run and `PLPROP-*` ID/hash;
8. continue only deterministic infrastructure work.

If process death, `BaseException`, timeout uncertainty, connector/runtime loss, or another uncertain failure occurs after durable `PLANNER_STARTED` but before trustworthy `PLANNER_RETURNED`, the receipt remains recovery-required.

A later ordinary bootstrap call must **not** automatically call the Planner again.

No TTL, PID liveness guess, automatic receipt stealing, “probably did not run” inference, or second model attempt is permitted.

### Phase-31 Planner refactor constraint

`BoundedProductionPlanner.propose()` currently owns Run creation internally. Phase 45 may introduce a narrow pinned invocation/refactor so the bootstrap no-replay marker is durably committed before the model boundary while preserving all existing Phase-31 parser, Run, Verification, scheduled-model, and failure-cleanup semantics.

The implementation must not fork a second Goal Planner schema/parser or bypass `BoundedProductionPlanner` validation.

---

## 11. Planner return and independent audit

A trustworthy Planner return must bind the exact:

```text
PLINPUT ID/hash
Planner Run ID
request hash
response hash
PLPROP ID/hash
model ID/hash evidence
```

The Planner remains proposal-only.

After checkpointing the return, Phase 45 independently recomputes the existing Phase-31 plan audit:

```text
audit_plan(planning_input, proposal)
```

and publishes the exact `PLAUD-*` through the existing evidence store.

A forged, stale, mismatched, malformed, oversized, cyclic, unknown-capability, authority-shaped, or non-PASS proposal never materializes.

The GOALBOOT receipt advances to `PLAN_AUDITED` only after the published audit can be reloaded and independently revalidated against the exact input/proposal relation.

There is no model call in the audit stage.

---

## 12. Single explicit materialization

After exact current `PLINPUT / PLPROP / PLAUD PASS` is checkpointed, Phase 45 may call only the existing Phase-31 atomic materializer.

Materialization must:

- revalidate current Goal revision/hash;
- revalidate exact input/proposal/audit identities/hashes;
- reject duplicate proposal materialization;
- create one canonical Flow;
- create bounded canonical Tasks and dependencies;
- publish one exact `PLMAT-*`;
- roll back atomically on failure.

Phase 45 must checkpoint the exact returned `PLMAT` ID/hash before attempting PREPPOL construction.

A bootstrap call never manually creates Tasks in parallel with Phase-31 materialization and never rewrites the resulting Task graph.

One GOALBOOT may bind only one PLMAT.

A later Goal revision is a distinct bootstrap authority question; v1 must not silently “update” an old materialization in place.

---

## 13. PREPPOL publication and Manager handoff

After materialization, Phase 45 constructs the exact Phase-39 preparation policy using the already-existing constructor and the exact GOALBOOT-bound authority IDs:

```text
PLMAT
CAPCAT
CAPPOL
DISPCAT
```

The current Phase-39 constructor independently validates the full relation and derives the code-owned preparation owner/model strategy.

Phase 45 publishes that PREPPOL through the protected Phase-39 store and checkpoints its exact ID/hash.

Only then may GOALBOOT become `READY`.

READY means:

> the exact current Goal revision has one exact materialization whose exact PREPPOL is current and can be discovered by existing Manager admission.

It does **not** mean:

- any Task ran;
- any Task passed verification;
- Manager was invoked;
- an Artifact was adopted/signed;
- the Goal is complete;
- code is merged/released.

Phase 45 stops immediately after PREPPOL publication.

The existing Phase-44 `manager status` / `manager advance` behavior remains unchanged and requires a separate explicit operator invocation.

---

## 14. Idempotence, currentness, and repeated calls

A repeated bootstrap request for the same exact Goal revision must not create a second Planner call after one trustworthy bootstrap already exists.

Read/decision semantics should distinguish at least:

```text
ELIGIBLE
ACTIVE_PRE_PLANNER
PLANNER_RECOVERY_REQUIRED
POST_PLANNER_RESUMABLE
MATERIALIZED_NEEDS_PREPPOL
READY_FOR_MANAGER
STALE_GOAL
FAILED_PRE_PLANNER
INTERRUPTED
AMBIGUOUS_AUTHORITY
INVALID_STATE
```

If a current READY GOALBOOT with current PREPPOL already exists, a repeated bootstrap call returns an idempotent READY/already-bootstrapped result with the exact IDs; it does not generate another plan.

If the Goal revision/hash changed, historical bootstrap evidence remains immutable and is not silently reused as current authority.

The implementation must define bounded behavior for multiple historical bootstrap receipts and fail closed on ambiguous current authority.

No same-call fallback to another Goal is ever permitted.

---

## 15. Recovery boundary

Phase 45 should provide explicit recovery semantics patterned after Phase 41 without automatic model replay.

Deterministic post-planner stages may be safely resumed when exact persisted evidence reconstructs:

```text
PLANNER_RETURNED
→ PLAN_AUDITED
→ MATERIALIZED
→ PREPPOL_PUBLISHED
```

For example, if process death occurs after `PLMAT` publication but before the receipt checkpoint, recovery may adopt the exact materialization only if it can prove a unique immutable object binds the exact checkpointed PLINPUT/PLPROP/PLAUD relation. Ambiguity fails closed.

If process death occurs after PREPPOL publication but before the final receipt checkpoint, recovery may adopt the exact PREPPOL only after full Phase-39 provenance/current-owner validation and unique exact relation proof.

`PLANNER_STARTED` uncertainty remains qualitatively different: no deterministic recovery path may infer that another model call is safe.

An explicit future/manual interruption authority may mark an unrecoverable receipt `INTERRUPTED`; interruption never implies Task/Goal failure and never authorizes replay by itself.

---

## 16. Read-only inspection

Expose bounded non-creating read-only inspection for:

```text
Goal bootstrap eligibility/currentness
GOALBOOT receipt/stage/status
bound CAPCAT/CAPPOL/DISPCAT IDs/hashes
PLINPUT / PLPROP / PLAUD / PLMAT IDs/hashes
Planner recovery state
PREPPOL ID/hash and Manager readiness
```

Inspection must reuse the established immutable/non-migrating production read boundaries where applicable and protected evidence readers for file-backed stores.

Read-only status must not:

- initialize a project;
- migrate/checkpoint SQLite;
- create WAL/SHM/journal sidecars;
- publish capability/dispatch/planning/PREPPOL evidence;
- acquire GOALBOOT ownership;
- call a model;
- audit/materialize a plan;
- call Manager;
- repair state.

No cockpit mutation is part of Phase 45.

---

## 17. Operator surface

Phase 45 architecture does **not** modify the existing Phase-44 Manager CLI or the v0.1 packaging/cockpit guidance.

Implementation may first expose the new bootstrap operation as a narrow module/API boundary with acceptance coverage. Any packaged operator command is a separately reviewed surface and must preserve the v0.1 three-command guidance unless an explicit later phase changes it.

If an operator command is later added, its authority arguments must remain bounded to the Goal identity; it must not surface model/profile/runtime/catalog/policy/adapter/Task/Manager-action selectors.

---

## 18. Concurrency and adversarial acceptance

Final Phase-45 acceptance must prove at least:

- exact prerequisite authority comes from one current canonical Goal revision;
- caller can supply a Goal ID but no capability/routing/dispatch/model/runtime/Task authority;
- bootstrap derives current protected PlanningInput evidence rather than accepting arbitrary PI/model/resource hashes;
- only the current dispatch-safe code capability is exposed to the v1 Goal Planner;
- a proposal requiring an unsupported/deferred capability fails before materialization;
- CAPCAT/CAPPOL/DISPCAT relation is exact, current, code-owned, and not chosen by filesystem order;
- no model is loaded and no resource lease is acquired while merely assembling bootstrap authority;
- concurrent bootstrap calls for the same Goal revision produce at most one GOALBOOT Planner-boundary winner;
- `PLANNER_STARTED` is durable before the single Goal Planner call;
- two concurrent calls produce at most one Goal Planner model call for that exact Goal revision;
- simulated crash/uncertainty after `PLANNER_STARTED` never auto-replays the Planner;
- a trustworthy return binds the exact taskless Planner Run and PLPROP evidence;
- strict Phase-31 parser and independent PLAUD remain authoritative; Planner output cannot self-audit;
- only independently recomputed `PLAUD PASS` may cross the explicit bootstrap materialization authority;
- one GOALBOOT materializes at most one PLMAT;
- Phase-31 materialization atomic rollback semantics remain intact;
- PREPPOL is built only from the exact GOALBOOT-bound PLMAT/CAPCAT/CAPPOL/DISPCAT relation;
- READY GOALBOOT is visible to existing Manager admission without Phase-45 calling Manager;
- repeated bootstrap of an already READY exact Goal revision creates no second Planner call/materialization/PREPPOL;
- stale Goal revision fails closed and historical evidence remains immutable;
- post-planner deterministic crash stages can resume only from unique exact persisted evidence;
- no dispatch claims/executions are created by bootstrap;
- no Task status is advanced beyond Phase-31 materialization’s initial state by Phase 45;
- no Task Verification outcome is invented or reinterpreted;
- no Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training, merge, release, background loop, timer, or hidden autonomous retry authority is introduced.

Normal CI may use deterministic/fake governed model runtime boundaries for planner-call-count and crash/concurrency semantics. Heavy model downloads are not part of the normal merge gate.

---

## 19. Proposed implementation slices

Freeze each authority-expanding slice at one immutable SHA and gate the normal Ubuntu Python 3.12/3.13 matrix before advancing.

```text
45A  GOALBOOT contracts + durable schema / receipt / invariants
45B  bootstrap owner + exact dispatch-safe CAPCAT/CAPPOL/DISPCAT authority derivation
45C  code-owned PlanningInput evidence derivation + Goal Planner dependency assembly
45D  GOALBOOT admission/acquisition + PLINPUT publication + durable PLANNER_STARTED fence
45E  one pinned Goal Planner invocation + trustworthy PLANNER_RETURNED checkpoint
45F  independent PLAUD publication + explicit single Phase-31 materialization
45G  exact PREPPOL publication + READY/currentness/status + deterministic recovery
45H  adversarial cross-phase concurrency/no-replay/Manager-handoff acceptance
45I  documentation / roadmap closure
```

If implementation evidence reveals that a slice must be subdivided to preserve one authority expansion per green head, subdivide it rather than weakening the gate.

Planning and implementation remain separate pull requests/branches as in earlier governed phases.

---

## 20. Explicit non-goals

Phase 45 does **not** add:

- automatic Manager invocation after bootstrap;
- background Manager/bootstrap loops, daemons, polling, timers, cron, or queues;
- automatic bootstrap of every OPEN/ACTIVE Goal;
- cross-Goal scheduling or fallback to another Goal;
- multiple Planner calls in one bootstrap attempt;
- automatic Planner replay after uncertain `PLANNER_STARTED`;
- model-selected capability catalogs, routing policies, dispatch contracts, adapters, model profiles, runtime providers, endpoints, sandboxes, or secrets;
- all-built-in capability exposure when current dispatch/preparation authority supports only bounded code work;
- model self-audit or self-materialization;
- semantic Task success claims from a structural plan audit;
- direct Task execution, Phase-35 activation, WorkOrder planning, Phase-34 binding, Phase-38 dispatch, dispatch claim, or dispatch execution;
- Task Verification PASS/FAIL authority;
- Artifact adoption or provenance signing;
- Project Intelligence / Design Bible mutation;
- Dream promotion or training authority;
- generic tool execution;
- automatic repository merge or release;
- live self-training/model-weight mutation;
- packaging/cockpit/Phase-44 Manager command changes in the planning slice.

---

## 21. Exit condition

Phase 45 is complete when one immutable repository head proves that Origin Forge can accept one explicit existing Goal identity and, without caller-selected production/model authority, durably and safely:

1. acquire one exact Goal-revision bootstrap authority;
2. derive/publish exact dispatch-safe Phase-32/33 authority;
3. derive/publish one exact PlanningInput from protected state;
4. cross the Goal Planner boundary at most once behind a durable no-replay checkpoint;
5. independently audit the returned bounded proposal;
6. exercise the explicit Phase-45 authority to materialize exactly one passing plan through the existing Phase-31 atomic materializer;
7. publish one exact Phase-39 PREPPOL over that materialization;
8. expose the resulting state as ready for the existing Manager;
9. stop before Manager advancement or production execution.

The final immutable implementation/documentation head must pass the normal Python 3.12 and Python 3.13 matrix with unrelated heavyweight external evidence workflows disarmed/skipped before ready-for-review transition and SHA-guarded merge.

No post-CI repository self-edit is required; the pull request, exact workflow run, and merge metadata remain the closure record.
