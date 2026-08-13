# Phase 40 — Governed Manager Production Advancement & Single Action

Status: **PLANNED — architecture frozen before implementation**

Verified prerequisite `main`:

```text
493a74533e568ed46b96a376aa546a8f344f64a0
```

Phase 40 composes the already-governed Phase-38 dispatch boundary and Phase-39 preparation boundary into one higher Manager decision **without** adding a worker loop, daemon, hidden retry queue, or caller-selected Task authority.

The required operation is deliberately one-shot:

```text
inspect current production state
    ↓
select one exact Task/action deterministically
    ↓
perform at most one existing governed action
    ↓
STOP
```

A later phase may decide whether repeated invocation is justified. Phase 40 does not.

---

## Why Phase 40 is required

Phase 38 can select and dispatch one already-`READY` Task with current Phase-34 authority.

Phase 39 can, for one explicit persisted `PREPPOL-*`, select and prepare one dependency-ready `QUEUED` Task through one WorkOrder-planner call, then expose separate deterministic finalizers for:

```text
PLANNER_STARTED / PLANNER_RETURNED
→ WORK_ORDER_AUDITED

WORK_ORDER_AUDITED
→ BOUND / READY
```

These layers are individually safe, but a global Manager still lacks three things:

1. bounded enumeration of persisted preparation policies and durable preparation receipts;
2. one deterministic cross-state admission/selection rule spanning dispatch-ready, preparation-continuation, and new-preparation work;
3. a way to execute the **already-selected exact candidate** without the underlying Phase-38 or Phase-39 public tick re-admitting and switching to a different Task after a race.

The third point is the critical composition hazard.

Calling `dispatch_manager_tick()` after Phase 40 has selected a dispatch Task would cause Phase 38 to perform a second admission/selection. Likewise, calling `prepare_materialization_tick(preparation_policy_id)` after Phase 40 has selected a preparation Task would cause Phase 39 to perform a second per-policy admission/selection. If the originally selected Task changed between those reads, either public tick could legitimately choose a different candidate. That would violate the existing no-fallback rule at the new Manager boundary.

Phase 40 therefore requires infrastructure-only **pinned candidate execution helpers**. Public Phase-38/39 APIs keep their existing signatures and behavior; their mutation bodies are refactored so a higher trusted coordinator can invoke the exact already-admitted candidate and let the existing transactional rechecks decide success or failure. A stale selected candidate always stops the call. It never becomes permission to select another Task.

---

## Authority boundary

The public mutating API is conceptually:

```text
advance_production_manager_once(runtime)
```

The caller supplies no:

- Task ID;
- preparation policy ID;
- PREP ID;
- Phase-34 binding/audit ID;
- routing policy/catalog;
- adapter/dispatch contract/binder;
- model role/profile/runtime/provider/endpoint;
- WorkOrder payload/evidence refs;
- retry/fallback candidate;
- priority/cost/resource-pressure override.

All action authority is derived from current trusted Origin Forge state.

One call may choose **one exact Task** and **one exact action kind** only.

---

## Global read-side inputs

Phase 40 may read only existing governed state:

- canonical Tasks / dependency readiness through the Phase-30 immutable SQLite boundary;
- current Phase-38 dispatch admission;
- protected persisted `PREPPOL-*` objects;
- durable `PREP-*` receipts;
- Phase-39 immutable preparation status/currentness;
- exact Phase-32/33/34 evidence already referenced by those layers.

It does not create a PREPPOL, infer a missing preparation policy, activate a Task during admission, load a model during admission, acquire a dispatch claim during admission, or repair evidence during admission.

---

## Protected PREPPOL enumeration

Add a bounded non-creating preparation-policy enumeration surface over `.origin-forge/production-preparation-policies/`.

Rules:

- missing policy storage means zero published policies;
- a symlinked/aliased root, malformed filename, duplicate JSON key, noncanonical bytes, object-count overflow, content-hash mismatch, or invalid policy fails closed;
- every enumerated PREPPOL is independently reloaded through the existing protected reader/current provenance checks;
- filesystem order is never scheduling authority;
- enumeration never creates the storage directory.

Semantically identical duplicate PREPPOLs may collapse only when every authority-bearing field except infrastructure-owned `preparation_policy_id` is identical.

If one Task is eligible under multiple semantically different current PREPPOLs, Phase 40 must not choose one by filename, creation time, lexical ID, or model judgment. That is `AMBIGUOUS_PREPARATION_AUTHORITY` and fails closed.

---

## PREP lifecycle classification

Phase 40 treats a durable PREP as existing ownership, not as a fresh scheduling candidate.

For one current Task:

### `ACTIVE / CLAIMED`, `ACTIVE / ACTIVATED`, `ACTIVE / ROUTED`

These stages prove the planner boundary has not yet been durably crossed, but a host crash can leave uncertainty about which deterministic sub-step committed outside the receipt checkpoint.

Phase 40 v1 does **not** automatically reconstruct/replay these pre-planner stages. They surface as:

```text
PREPARATION_RECOVERY_REQUIRED
```

and a selected Task stops the Manager call without fallback.

A later dedicated recovery contract may widen this only with independently reconstructable checkpoint evidence.

### `ACTIVE / PLANNER_STARTED`

The Manager may invoke only the existing deterministic planner-evidence recovery / WorkOrder-finalization path.

It must never call the WorkOrder model again.

Outcomes:

- one exact reconstructable successful taskless planner Run may advance toward `WORK_ORDER_AUDITED`;
- zero matching trustworthy results remains recovery-required;
- multiple/conflicting results fail closed;
- no fallback Task is selected.

### `ACTIVE / PLANNER_RETURNED`

Action kind:

```text
FINALIZE_WORK_ORDER
```

Invoke exactly one existing Phase-39 WorkOrder publication/audit finalizer and stop.

### `ACTIVE / WORK_ORDER_AUDITED`

Action kind:

```text
FINALIZE_PHASE34
```

Invoke exactly one existing Phase-39 Phase-34 finalizer and stop.

### `READY / BOUND`

The PREP itself is not a separate Manager action. Current Phase-34 authority is re-admitted independently by Phase 38 and becomes a normal `DISPATCH` candidate.

If a current Phase-39 READY receipt exists but its exact Phase-34 authority is stale/non-current and no Phase-38 candidate exists for that Task, Phase 40 must surface the Task as recovery-required rather than silently treating the project as idle.

### terminal PREP receipts

`FAILED_PRE_PLANNER` and `INTERRUPTED` are historical/terminal evidence. They create no automatic retry, reactivation, or fallback authority.

---

## Unified Manager advancement candidates

Phase 40 derives one typed candidate per currently governed Task at most.

Candidate action kinds:

```text
DISPATCH
FINALIZE_WORK_ORDER
FINALIZE_PHASE34
PREPARE
RECOVERY_REQUIRED
```

### DISPATCH

Source: exact current Phase-38 admission candidate.

### FINALIZE_WORK_ORDER

Source: exact current ACTIVE PREP at `PLANNER_STARTED` or `PLANNER_RETURNED`.

`PLANNER_STARTED` remains evidence-recovery-only and may return unresolved without mutation.

### FINALIZE_PHASE34

Source: exact current ACTIVE PREP at `WORK_ORDER_AUDITED`.

### PREPARE

Source: a dependency-ready `QUEUED` Task from exactly one unambiguous current PREPPOL.

The candidate freezes the exact Phase-39 `PreparationCandidate` plus exact PREPPOL ID/hash. Phase 40 does not later ask Phase 39 to choose again.

### RECOVERY_REQUIRED

Source includes, at minimum:

- current ACTIVE PREP at `CLAIMED`, `ACTIVATED`, or `ROUTED`;
- stale/invalid ACTIVE PREP authority;
- Phase-39 `READY/BOUND` receipt whose exact Phase-34 authority is no longer current and is not Phase-38-admissible;
- conflicting current authority that cannot be collapsed safely.

This is a selectable fail-closed state, not an invitation to skip the Task.

---

## Same-Task conflict rules

One Task must never enter the final admission set with two independent action authorities.

Examples:

- ACTIVE PREP plus Phase-38 dispatch candidate: invalid/ambiguous state;
- two semantically different PREPPOL preparation candidates: ambiguous authority;
- two active PREPs: schema/invariant violation;
- Phase-38 dispatch candidate plus fresh PREPARE candidate: invalid admission relation;
- multiple current dispatch chains with conflicting semantics: retain existing Phase-38 `AMBIGUOUS_AUTHORITY` failure.

Semantically identical evidence may collapse only using the already-frozen semantic-equivalence rules of the underlying phase. Phase 40 must not invent a weaker equivalence relation.

---

## Deterministic ordering

Cross-state scheduling keeps the same narrow v1 ordering already accepted by Phases 38 and 39:

```text
(Task.created_at, Task.id)
```

Action type is **not** an ordering key.

That means Phase 40 does not silently prefer:

- dispatch over preparation;
- preparation over dispatch;
- post-planner work over older queued work;
- priority values;
- resource pressure;
- model availability;
- estimated cost;
- retry history;
- objective text;
- operator/UI list order.

For a single Task, lifecycle/current authority determines its one action kind. Across Tasks, creation time and Task ID determine selection.

If the selected oldest Task is `RECOVERY_REQUIRED`, the Manager reports that state and stops. It does not skip to newer work.

---

## Pinned Phase-38 dispatch execution

Refactor Phase 38 so its existing public API remains:

```text
dispatch_manager_tick(runtime)
```

but the mutation path after selection is available to trusted infrastructure as a typed exact-candidate helper, conceptually:

```text
_dispatch_selected_candidate_once(runtime, candidate)
```

Rules:

- accepts a validated Phase-38 `ManagerDispatchCandidate`, not arbitrary caller strings;
- performs exactly the existing Phase-35 claim transaction with expected Task revision;
- requires the returned claim to bind the exact selected candidate;
- performs at most one Phase-37 invocation;
- any stale/race/claim failure/recovery-required state stops;
- never re-admits or falls through to another Task.

Existing Phase-38 tests must prove the public tick behavior is unchanged after refactor.

---

## Pinned Phase-39 preparation execution

Refactor Phase 39 so its existing public API remains:

```text
prepare_materialization_tick(runtime, preparation_policy_id)
```

but the mutation path after policy admission/selection is available to trusted infrastructure as a typed exact-candidate helper, conceptually:

```text
_prepare_selected_candidate_once(runtime, policy, candidate)
```

Rules:

- `policy` must be the independently reloaded exact persisted PREPPOL;
- `candidate` must be a typed Phase-39 `PreparationCandidate` frozen by Phase-40 admission;
- PREP acquisition transaction revalidates exact queued revision/hash/readiness/ownership;
- after acquisition, behavior remains the existing Phase-39 activation → fresh route → durable `PLANNER_STARTED` → at most one planner-call boundary;
- stale acquisition stops without selecting the policy's next Task;
- no automatic post-planner finalization is added to the PREPARE action.

Existing Phase-39 tests must prove the public tick behavior is unchanged after refactor.

Neither pinned helper becomes a CLI/HTTP/cockpit surface.

---

## Single Manager advancement action

The public one-shot Manager operation performs:

1. immutable global advancement admission;
2. pure deterministic selection of `candidates[0]` only;
3. one action dispatch based on the frozen candidate kind;
4. STOP.

Action behavior:

### DISPATCH

Call the pinned Phase-38 candidate helper once.

### PREPARE

Call the pinned Phase-39 candidate helper once.

Successful PREPARE still stops at `PLANNER_RETURNED`; it does not immediately audit/bind/dispatch in the same Manager action.

### FINALIZE_WORK_ORDER

Call `finalize_preparation_work_order_audit(runtime, preparation_id)` once and stop.

For `PLANNER_STARTED`, this is recovery-from-existing-evidence only; no model call is reachable.

### FINALIZE_PHASE34

Call `finalize_preparation_phase34(runtime, preparation_id)` once and stop.

### RECOVERY_REQUIRED

Perform no mutation and return recovery-required status.

No action failure or race causes a second candidate attempt.

---

## Manager result truth

The Manager result reports mechanics only. It does not create a second Task/Run/Workspace outcome model.

Suggested result states:

```text
NO_ACTIONABLE_WORK
AMBIGUOUS_AUTHORITY
INVALID_STATE
RECOVERY_REQUIRED
PREPARATION_NOT_ACQUIRED
PREPARATION_FAILED_PRE_PLANNER
PREPARATION_PLANNER_RETURNED
PREPARATION_PLANNER_RECOVERY_REQUIRED
WORK_ORDER_AUDITED
PHASE34_READY
DISPATCH_CLAIM_NOT_ACQUIRED
DISPATCH_NOT_STARTED
DISPATCH_RETURNED
DISPATCH_RAISED
DISPATCH_RECOVERY_REQUIRED
```

Exact names may be tightened during implementation, but Manager states must remain mechanical projections of existing Phase-38/39 results. They may not reinterpret `PolicyResult.outcome`, Task verification, or production success/failure.

---

## Read-only Manager advancement status

Expose one immutable status projection that reports:

- global admission status/detail;
- total governed candidate count;
- selected Task ID/created-at/action kind;
- selected PREPPOL ID where relevant;
- selected PREP ID/stage where relevant;
- selected Phase-34 authority IDs where relevant;
- counts of dispatch, preparation-continuation, fresh-preparation, recovery-required, ambiguous, stale, and excluded work;
- no creation/repair/migration/checkpoint/model/claim/dispatch side effects.

The status path reuses the Phase-30 immutable SQLite guard plus protected evidence readers.

---

## Concurrency and race semantics

Final acceptance must prove:

- two Manager advancement calls selecting the same PREPARE Task yield exactly one PREP owner and at most one WorkOrder-planner call;
- a selected PREPARE candidate that goes stale before PREP acquisition does not cause preparation of the second Task in the same PREPPOL;
- a selected DISPATCH candidate that goes stale before claim does not cause dispatch of another Task;
- two Manager advancement calls selecting the same DISPATCH Task yield exactly one Phase-35 claim/Phase-37 invocation winner;
- deterministic FINALIZE_WORK_ORDER retries reuse/recover existing planner/WorkOrder evidence and never replay the model;
- deterministic FINALIZE_PHASE34 retries reuse existing immutable Phase-34 artifacts and never dispatch;
- selected `RECOVERY_REQUIRED` work performs zero mutation and blocks same-call fallback;
- cross-class ordering is exactly `(created_at, task_id)` and ignores legacy priority;
- duplicate semantically identical PREPPOLs collapse without changing selected authority;
- conflicting PREPPOL authority for one Task fails closed;
- invalid policy-store entries cannot be hidden by enumeration order or scan truncation;
- Phase-38 and Phase-39 public APIs retain their independently accepted behavior after pinned-helper refactoring.

---

## Proposed implementation slices

```text
40A  protected bounded PREPPOL enumeration + global PREP lifecycle read model
40B  immutable cross-state Manager advancement admission + ambiguity/currentness rules
40C  pure selector + pinned Phase-38/39 candidate-execution refactors with regression tests
40D  one Manager advancement action coordinator
40E  immutable Manager advancement status
40F  adversarial cross-phase concurrency/race/recovery acceptance
40G  documentation / roadmap closure
```

Every authority-expanding slice freezes one exact SHA and must pass the normal Ubuntu Python 3.12/3.13 matrix before the next slice begins.

---

## Explicit exclusions

Phase 40 does **not** add:

- background polling;
- recurring worker/Manager daemon;
- timer/cron scheduling;
- multi-action loops;
- fallback to another Task after the selected candidate changes/fails;
- automatic PREPPOL creation;
- automatic recovery/replay of pre-planner `CLAIMED/ACTIVATED/ROUTED` receipts;
- WorkOrder-planner replay after durable `PLANNER_STARTED`;
- action-type priority or legacy Task priority;
- resource/cost/model-pressure scheduling;
- caller-selected Task/PREPPOL/PREP/binding/model/runtime authority;
- generic adapter/backend/model/tool execution beyond the already-reviewed Phase-38/39 paths;
- new Task outcome semantics;
- Artifact adoption/signing;
- Project Intelligence mutation;
- Dream promotion;
- training/checkpoint activation;
- merge/release authority.

---

## Exit condition

Phase 40 is complete when one no-argument Manager advancement call can inspect current governed production state, deterministically select exactly one oldest governed Task by `(created_at, task_id)`, derive exactly one safe action from existing PREP/Phase-38/Phase-39 authority, execute only that pinned candidate through the already-governed lower-phase transaction boundary, and stop without switching Tasks, replaying uncertain model work, creating hidden scheduling policy, or entering a repeated loop.
