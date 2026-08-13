# Phase 41 — Governed Preparation Recovery & Pre-Planner Resumption

Status: **PLANNED — architecture frozen before implementation**

Verified prerequisite `main`:

```text
e5b39cbd42b2275f449612e7cce6ff1b75f3e54a
```

Phase 41 closes the one remaining recovery gap deliberately surfaced by Phase 40: an existing `ACTIVE PREP-*` may be stranded at `CLAIMED`, `ACTIVATED`, or `ROUTED` after process loss even though the WorkOrder planner boundary has not yet been durably crossed.

Phase 39 already provides bounded recovery of trustworthy planner-return evidence after `PLANNER_STARTED`, plus crash-idempotent deterministic Phase-33/34 finalizers. Phase 40 already composes those post-planner operations into one-shot Manager advancement. Phase 41 therefore does **not** invent another post-planner recovery system, repeated Manager loop, daemon, or generic retry engine.

The missing primitive is narrower:

```text
one explicit existing PREP id
    ↓
independently classify exact durable recovery state
    ↓
resume only reconstructable pre-planner authority
    ↓
if the planner boundary is crossed:
    persist PLANNER_STARTED first
    ↓
perform at most one WorkOrder-planner call
    ↓
checkpoint an exact trustworthy return when available
    ↓
STOP
```

A later phase may decide whether Phase-40 Manager admission may invoke this primitive automatically. Phase 41 itself does not change Manager scheduling or selection.

---

## Why Phase 41 is required

Phase 40 intentionally classifies current `ACTIVE/CLAIMED`, `ACTIVE/ACTIVATED`, and `ACTIVE/ROUTED` receipts as `RECOVERY_REQUIRED` because the original Phase-39 preparation tick performs several durable operations in separate persistence domains:

```text
PREP acquisition (SQLite)
Task QUEUED → READY activation (SQLite)
PREP ACTIVATED checkpoint (SQLite)
Phase-32 route publication (protected immutable file)
PREP ROUTED checkpoint (SQLite)
PLANNER_STARTED checkpoint (SQLite)
model call / Run / verification evidence
PLANNER_RETURNED checkpoint (SQLite)
```

A crash can therefore leave a durable earlier PREP stage while a later deterministic sub-operation already committed.

The repository already has strong recovery infrastructure for the planner and later stages:

- `recover_planner_evidence()` reconstructs a successful Phase-33 planner result only from exact bounded Run/verification evidence and never calls the model;
- `finalize_preparation_work_order_audit()` recovers/reuses immutable WorkOrder/audit evidence without a model call;
- `finalize_preparation_phase34()` recovers/reuses exact current `INRES/DISPBIND/BINDAUD` evidence and never dispatches.

What does not yet exist is a governed primitive that can safely distinguish and resume the pre-planner crash windows without guessing.

---

## Authority boundary

The public mutating API is conceptually:

```text
recover_preparation_once(runtime, preparation_id)
```

The caller supplies exactly one existing `PREP-*` identity and no other execution authority.

The caller may not supply:

- Task ID or Task revision/hash;
- PREPPOL ID/hash;
- materialization or planning-input authority;
- capability catalog/routing policy;
- route ID to adopt;
- adapter/dispatch contract/binder;
- model role/profile/runtime/provider/endpoint;
- WorkOrder payload or evidence refs;
- Run/verification/WorkOrder ID to adopt;
- fallback PREP or fallback Task;
- retry count, priority, cost, resource-pressure, or model-availability override;
- Task/Flow/Goal outcome.

Every authority-bearing value is reloaded from the durable PREP and its exact current PREPPOL/provenance chain.

One call operates on that one PREP only. A race, stale checkpoint, ambiguous evidence, unsupported adapter, invalid policy, model uncertainty, or persistence failure stops the call. It never falls through to another PREP or Task.

---

## Recovery-state classification

Add a non-mutating exact recovery classifier over one PREP. Suggested states:

```text
RESUMABLE_CLAIMED
ADOPTABLE_ACTIVATION_CHECKPOINT
RESUMABLE_ACTIVATED
RESUMABLE_ROUTED
PLANNER_EVIDENCE_ONLY
POST_PLANNER_NOT_REQUIRED
READY_NOT_REQUIRED
TERMINAL_NOT_REQUIRED
STALE_OR_INVALID
AMBIGUOUS_EVIDENCE
```

Classification must reuse the existing Phase-39 currentness rules and Phase-30 immutable SQLite boundary where possible. It may inspect bounded state-event evidence and protected Phase-32 route objects, but it may not create, checkpoint, activate, route, plan, claim, dispatch, or repair anything.

A read-side classification is evidence only. The mutating recovery operation independently revalidates every required relation under its own transaction or protected-object read immediately before mutation.

---

## CLAIMED recovery

`ACTIVE/CLAIMED` has two safe subcases and several unsafe ones.

### Exact QUEUED state

If canonical Task state still exactly matches:

```text
status = QUEUED
revision = PREP.queued_task_revision
routing hash = PREP.queued_task_hash
dependency readiness = READY
```

then no committed Task activation can have occurred. Recovery may perform the Phase-35 activation exactly once.

Future recovery and normal Phase-39 preparation must not repeat the old two-transaction activation/checkpoint window. Refactor the existing Phase-35 activation implementation so trusted preparation infrastructure can execute the canonical dependency-ready `QUEUED → READY` transition and the PREP `CLAIMED → ACTIVATED` checkpoint in one `BEGIN IMMEDIATE` SQLite transaction.

The existing public Phase-35 activation API must preserve its current signature and behavior. The new transaction-aware helper is infrastructure-only and must not become a generic caller surface.

This atomic relation ensures that after Phase41 is installed, a crash can no longer newly produce a durable `CLAIMED` receipt with a committed READY Task from the normal preparation path.

### Legacy lost activation checkpoint

Existing Phase-39/40 deployments can already contain the older crash shape:

```text
PREP = ACTIVE / CLAIMED
Task = READY at queued revision + 1
```

Canonical READY state alone is insufficient evidence because the generic Task transition API can also perform `QUEUED → READY`.

Phase 41 may adopt a lost activation checkpoint only when the state-event log reconstructs exactly one Phase-35 dependency-ready activation event after the PREP acquisition event.

Required evidence includes, at minimum:

- exactly one canonical `TASK_PREPARATION_ACQUIRED` event for the PREP at revision 0;
- exactly one later `TASK_STATUS_CHANGED` event for the same Task and exact `queued_revision + 1`;
- before/after status exactly `QUEUED → READY`;
- event actor shape exactly the Phase-35 infrastructure shape;
- metadata schema exactly the Phase-35 activation schema, including:
  - `reason = DEPENDENCY_READY_ACTIVATION`;
  - dependency count;
  - satisfied dependency count;
  - exact previous Task routing hash;
  - exact new Task routing hash;
- previous hash equals `PREP.queued_task_hash`;
- current READY Task revision/hash equals the event new revision/hash;
- the Task remains in the same current project and exact PREPPOL/materialization authority.

The recovery relation is ordered by durable event row order, not timestamps alone: the activation event must occur after the exact PREP acquisition event.

A generic `transition_task(..., READY, ...)`, a malformed event, multiple candidate activation events, conflicting hashes, later Task revision, or missing exact acquisition event is **not** adoptable. Recovery stops fail-closed.

Phase 41 does not reinterpret adoption as proof of which process invoked activation; it proves only that the exact reviewed Phase-35 activation semantics committed after durable PREP ownership and still match the current canonical Task.

---

## ACTIVATED recovery and lost Phase-32 route checkpoint

For `ACTIVE/ACTIVATED`, the PREP already proves exact READY Task revision/hash authority. A crash may have happened before routing, or after an immutable Phase-32 route was published but before `PREP → ROUTED` checkpointing.

Phase-32 routing is deterministic for an exact current Task + exact CAPCAT + exact CAPPOL, and route publication has no model/backend/process/Task outcome side effect. Recovery may therefore reuse equivalent immutable route evidence rather than manufacture duplicates blindly.

Required algorithm:

1. reload exact PREPPOL and current CAPCAT/CAPPOL provenance;
2. require the PREP READY Task revision/hash to remain canonical and current;
3. independently compute the expected current Phase-32 route resolution;
4. boundedly enumerate protected route objects using the existing object-count/path/canonical-JSON/hash defenses;
5. retain only routes whose exact resolution semantics equal the expected current resolution;
6. if one or more semantically identical routes exist, choose one deterministically by route ID after proving semantic identity;
7. if none exists, publish exactly one fresh route;
8. checkpoint its exact ID/hash into PREP under expected PREP revision;
9. stop or continue only on that same PREP; never select another Task.

Malformed/aliased/over-limit route storage fails closed. Filesystem iteration order is never authority.

The route semantic-equivalence rule ignores only the infrastructure-generated `route_decision_id`; every field of `CapabilityRouteResolution` must match exactly.

---

## ROUTED recovery and planner-boundary safety

`ACTIVE/ROUTED` is the last pre-planner stage.

If the receipt remains current, then the durable database proves that `PLANNER_STARTED` has **not** committed. Under the existing Phase-39 ordering contract, no WorkOrder planner model call is permitted before `PLANNER_STARTED` is durable. Therefore a current `ROUTED` receipt is safe to resume through one planner attempt.

Recovery must:

1. revalidate the exact current PREPPOL and Phase-32 route ID/hash;
2. assemble the code-owned planner dependency plan through the existing protected Phase-39 dependency assembler;
3. repeat the exact preparation-owner / adapter / dispatch-contract checks used by the normal Phase-39 path;
4. durably checkpoint `ROUTED → PLANNER_STARTED` with the exact dependency-plan hash;
5. only after that commit, perform at most one existing `BoundedProductionWorkOrderPlanner.propose()` call;
6. checkpoint `PLANNER_RETURNED` only through the existing exact planner-return validator;
7. on any uncertain failure after `PLANNER_STARTED`, reread durable PREP state and return recovery-required without model replay.

Two concurrent recovery calls against the same `ROUTED` PREP must yield at most one successful `PLANNER_STARTED` compare-and-swap winner and therefore at most one model invocation. A loser that observes/stumbles into `PLANNER_STARTED` must not call the model.

---

## PLANNER_STARTED remains evidence-only

Phase 41 does **not** weaken the Phase-39 no-replay invariant.

For `ACTIVE/PLANNER_STARTED`:

```text
model call may have happened
OR
process may have died after the marker but before the call
```

Those possibilities are intentionally indistinguishable after restart.

The only permitted recovery is the existing `recover_planner_evidence()` path:

- exactly one bounded successful taskless planner Run + exact PASS verification that reconstructs the PREP Task/route may advance to `PLANNER_RETURNED`;
- zero matches remains unresolved;
- multiple matches are ambiguous;
- malformed/stale/over-limit evidence fails closed;
- the model is never called.

If no trustworthy planner result reconstructs, Phase 41 leaves the PREP ACTIVE/PLANNER_STARTED. It does not mark the planner as failed, reset the stage, create a replacement PREP, or assume the call never occurred.

---

## Post-planner stages are not expanded

`PLANNER_RETURNED`, `WORK_ORDER_AUDITED`, and `READY/BOUND` already have governed deterministic continuation or validation paths accepted in Phases 39 and 40.

Phase 41 does not duplicate those authorities.

Suggested recovery behavior:

- `PLANNER_RETURNED` → report `POST_PLANNER_NOT_REQUIRED`;
- `WORK_ORDER_AUDITED` → report `POST_PLANNER_NOT_REQUIRED`;
- `READY/BOUND` → report `READY_NOT_REQUIRED` after currentness validation;
- `FAILED_PRE_PLANNER` / `INTERRUPTED` → report `TERMINAL_NOT_REQUIRED`;
- stale or invalid later authority → fail closed without repair.

Phase 40 remains responsible for its already accepted `FINALIZE_WORK_ORDER` / `FINALIZE_PHASE34` actions.

---

## No interruption/requeue authority in Phase 41

Although the PREP model reserves `INTERRUPTED`, Phase 41 does not add a generic interruption, reset, requeue, receipt-stealing, or Task-demotion API.

That authority is intentionally deferred because terminalizing a PREP after Task activation can leave a READY Task without a valid preparation chain, and automatically returning READY → QUEUED is not an accepted Task transition or retry semantic.

Unrecoverable or ambiguous pre-planner evidence remains explicit recovery-required state for later operator/recovery policy design. Safety takes precedence over liveness.

---

## Existing normal preparation path must inherit the repair

Phase 41 is not allowed to create a special recovery-only implementation while leaving the normal Phase-39 path with a known crash window.

After the atomic activation/checkpoint helper is accepted:

- `prepare_materialization_tick()` and its pinned Phase-40 preparation helper must use the same atomic CLAIMED→READY/ACTIVATED transaction;
- existing public Phase-35 and Phase-39 signatures remain unchanged;
- existing Phase-35/39/40 regression suites must prove behavior and authority boundaries are unchanged;
- no new caller-selected Task or PREP authority is added to Phase 40.

Shared pre-planner owner/contract validation should be factored so normal preparation and recovery cannot drift semantically.

---

## Result truth

Phase41 results describe recovery mechanics only. They do not create Task/Run/Workspace success truth.

Suggested result states:

```text
RECOVERED_PLANNER_RETURNED
RESUMED_PLANNER_RETURNED
PLANNER_RECOVERY_REQUIRED
ACTIVATION_RECOVERY_REJECTED
ROUTE_RECOVERY_REJECTED
INVALID_AUTHORITY
INVALID_STATE
AMBIGUOUS_EVIDENCE
LIMIT_EXCEEDED
POST_PLANNER_NOT_REQUIRED
READY_NOT_REQUIRED
TERMINAL_NOT_REQUIRED
```

Exact names may be tightened during implementation, but no status may imply Task success/failure/quarantine, WorkOrder audit PASS unless independently verified, or dispatch/execution completion.

---

## Concurrency and crash semantics

Final acceptance must cover at least:

- crash after PREP acquisition while Task remains exact QUEUED → recovery resumes safely;
- the repaired normal path cannot commit Task READY while leaving PREP CLAIMED under injected transaction failure;
- legacy CLAIMED+READY with one exact post-acquisition Phase-35 activation event is adoptable;
- generic or forged-looking QUEUED→READY transition evidence is rejected;
- legacy CLAIMED+READY with conflicting/multiple activation evidence fails closed;
- ACTIVATED with no existing route publishes one exact route and checkpoints it;
- crash after route publication but before PREP checkpoint reuses exact semantic route evidence rather than requiring a second authority chain;
- multiple semantically identical current routes collapse deterministically;
- malformed/aliased/over-limit route storage fails closed;
- ROUTED recovery commits PLANNER_STARTED before the model call;
- two concurrent ROUTED recoveries yield at most one model call;
- crash/exception after PLANNER_STARTED never automatically replays the model;
- one exact existing successful planner Run can recover PLANNER_RETURNED without a model call;
- zero/multiple planner matches remain unresolved/ambiguous;
- no recovery path acquires a `DISPCLAIM-*`, creates `DISPEXEC-*`, invokes Phase37 dispatch, or transitions Task beyond the original QUEUED→READY activation;
- no fallback PREP or Task is attempted after any race/failure;
- Phase40 behavior remains fail-closed until a later phase explicitly integrates the new recovery primitive.

Normal CI may use deterministic fake model boundaries for call-count and crash injection. Heavyweight model downloads are not required for the normal merge gate.

---

## Proposed implementation slices

```text
41A  immutable recovery classification + exact Phase-35 activation-event reconstruction
41B  transaction-aware Phase-35 activation helper + atomic PREP CLAIMED→ACTIVATED repair
41C  bounded semantic Phase-32 route recovery/reuse + ACTIVATED→ROUTED checkpoint
41D  single PREP recovery coordinator through ROUTED→PLANNER_STARTED→at-most-one planner call
41E  PLANNER_STARTED evidence-only recovery composition + immutable recovery status
41F  adversarial cross-phase crash/concurrency/no-dispatch acceptance
41G  documentation / roadmap closure
```

Every authority-expanding slice must freeze one exact SHA and pass the normal Ubuntu Python 3.12/3.13 matrix before the next slice begins.

If implementation proves one proposed slice contains two independently meaningful authority gates, split it and gate the sub-slices separately rather than preserving the lettering artificially.

---

## Explicit authority exclusions

Phase 41 does **not** add:

- repeated Manager invocation, background worker, daemon, cron, timer, polling loop, queue consumer, or hidden retry scheduler;
- automatic Phase40 integration of pre-planner recovery;
- caller-selected Task, PREPPOL, route, adapter, contract, binder, model profile/runtime/provider, WorkOrder payload, Run, verification, or fallback authority;
- planner replay after durable `PLANNER_STARTED`;
- generic retry of arbitrary model/backend/tool/process calls;
- automatic PREP interruption, deletion, reset, replacement, or receipt stealing;
- automatic READY→QUEUED rollback or Task retry semantics;
- Task/Flow/Goal success/failure/quarantine reinterpretation;
- dispatch-claim acquisition or production execution;
- Artifact adoption/signing;
- Project Intelligence mutation;
- Dream promotion;
- training/checkpoint activation;
- merge or release authority.

---

## Exit condition

Phase 41 is complete when Origin Forge can take one explicit existing PREP receipt stranded before or at the WorkOrder planner boundary, independently prove its exact durable recovery state, safely reconstruct only the deterministic operations that can be proven, eliminate the future activation/checkpoint crash window by atomically binding Phase-35 activation to PREP `ACTIVATED`, recover/reuse exact current Phase-32 route evidence after route/checkpoint crashes, cross the planner boundary at most once from a provably current `ROUTED` state, recover `PLANNER_STARTED` only from already-existing trustworthy planner evidence, and stop without dispatching, retrying another Task, inventing outcome truth, or adding a background loop.
