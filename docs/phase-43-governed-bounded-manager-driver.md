# Phase 43 — Governed Bounded Manager Driver

Status: **PLANNED — architecture frozen before implementation**

Verified prerequisite `main`:

```text
6ec539cfc7d6e4d2f80be1931b1f7ae011d1644b
```

This prerequisite differs from the original architecture-analysis base only by merged test-only fail-closed concurrency acceptance repair PR #72; production authority is unchanged.

Phase 43 adds the first bounded repeated outer Manager operation over the accepted Phase-40/42 one-shot primitive:

```text
advance_production_manager_once(runtime)
```

The new capability is deliberately a finite driver, not a daemon, scheduler service, watcher, timer, retry queue, or open-ended work loop.

The authority shape is:

```text
code-owned finite step budget
    ↓
advance_production_manager_once(runtime)
    ↓
typed one-shot result
    ↓
continue only for an explicit positive-progress whitelist
    ↓
fresh one-shot Manager admission on the next step
    ↓
STOP on every other result or when the hard step bound is reached
```

Every individual step retains all Phase-40/42 semantics: one immutable admission, one pure oldest-candidate selection by `(Task.created_at, Task.id)`, at most one governed lower action, typed projection, and unconditional stop inside that one-shot call.

Phase 43 composes those accepted calls without weakening their mutation/currentness authority.

---

## Why a separate bounded driver is required

Phase 40 intentionally stopped after one Manager action. Phase 42 preserved that rule even when recovery became automatically actionable.

That one-shot boundary is the correct mutation primitive, but an operator currently needs a separate external invocation for every successful lifecycle edge, for example:

```text
RECOVER CLAIMED → ACTIVATED
RECOVER ACTIVATED → ROUTED
RECOVER ROUTED → PLANNER_RETURNED
FINALIZE_WORK_ORDER → WORK_ORDER_AUDITED
FINALIZE_PHASE34 → READY/BOUND
DISPATCH → terminal dispatch result
```

Phase 43 may automate only this repetition of already-governed one-shot Manager calls. It may not invent new scheduling, retry, recovery, dispatch, Task-outcome, or model authority.

---

## Hard boundedness

The v1 driver has a code-owned hard maximum of **six** one-shot Manager steps per outer invocation.

Six is derived from the longest accepted single-Task lifecycle path currently exposed to Manager starting from an exact current `CLAIMED` PREP:

1. `CLAIMED → ACTIVATED` recovery;
2. `ACTIVATED → ROUTED` recovery;
3. `ROUTED → PLANNER_RETURNED` recovery;
4. WorkOrder audit finalization;
5. Phase-34 binding finalization;
6. dispatch attempt.

The initial Phase-43 public API does not accept a caller-selected step count. The bound is infrastructure-owned and cannot be enlarged by a model, plugin, CLI argument, Task payload, preparation policy, or dispatch contract.

Reaching the six-step limit is a normal bounded stop. It does not authorize a seventh step, fallback call, timer, reschedule, or hidden continuation.

---

## Closed continuation whitelist

A Phase-43 driver may perform another fresh one-shot Manager call only when the previous one-shot result has one of these exact statuses:

```text
PREPARATION_RECOVERY_ADVANCED
PREPARATION_PLANNER_RETURNED
WORK_ORDER_AUDITED
PHASE34_READY
```

These are the only Manager statuses that mechanically prove accepted lifecycle authority has reached a later internal production edge from which a fresh Manager admission may safely decide what is now oldest/actionable.

The whitelist is closed. Any future Manager status is non-continuable until a later architecture phase explicitly proves and adds it.

### Why `DISPATCH_RETURNED` is not continuable

`DISPATCH_RETURNED` proves one dispatch owner returned and the associated execution/claim terminalization completed. It does **not** grant Phase 43 permission to process another Task in the same outer driver invocation.

Phase-38 admission excludes only an `ACTIVE` claim, while a terminal dispatch consumes that claim. Claim history is therefore not itself a permanent same-Task replay fence. Canonical Task state and lower bounded-retry policy remain the authority for what becomes dispatchable later.

Phase 43 must consequently stop at the first dispatch result instead of using `DISPATCH_RETURNED` as a queue-drain signal.

This preserves two important boundaries:

- one outer bounded driver invocation never becomes an open-ended processor of successive Tasks;
- the driver never relies on Manager mechanical dispatch status as Task-outcome truth.

---

## Mandatory stop statuses

Every one-shot result outside the four-value continuation whitelist stops the driver immediately.

That includes, without exception:

```text
NO_ACTIONABLE_WORK
AMBIGUOUS_AUTHORITY
LIMIT_EXCEEDED
INVALID_STATE
RECOVERY_REQUIRED
PREPARATION_NOT_ACQUIRED
PREPARATION_FAILED_PRE_PLANNER
PREPARATION_PLANNER_RECOVERY_REQUIRED
DISPATCH_CLAIM_NOT_ACQUIRED
DISPATCH_NOT_STARTED
DISPATCH_RETURNED
DISPATCH_RAISED
DISPATCH_RECOVERY_REQUIRED
```

The stop rule is semantic, not merely defensive.

- `PREPARATION_FAILED_PRE_PLANNER` is a terminalized preparation failure. Current Manager admission deliberately suppresses an implicit fresh PREPARE retry for an exact-current terminal PREP, so Phase 43 must surface the failure rather than skip onward to newer work.
- `DISPATCH_RAISED` is a durable terminal dispatch failure and must likewise be surfaced rather than silently continuing to another Task.
- claim loss, stale authority, read races, recovery-required state, ambiguity, and limits remain fail-closed.
- `NO_ACTIONABLE_WORK` is quiescence, not a reason to poll again.

No stop result may trigger another one-shot call in the same Phase-43 invocation.

---

## Fresh admission on every permitted continuation

Phase 43 does not carry a candidate from one step into another.

After a whitelisted result, the next step calls the existing public one-shot primitive again. That primitive performs a completely fresh immutable Manager admission and pure selection under the current durable state.

Therefore Phase 43 must not:

- retain or replay a prior `ManagerAdvanceCandidate`;
- call `_prepare_selected_candidate_once`, `_dispatch_selected_candidate_once`, `recover_preparation_once`, WorkOrder finalizers, Phase-34 finalizers, or any model/owner boundary directly;
- infer the next lifecycle edge from the previous action kind;
- assume the same Task remains globally oldest after another actor races;
- bypass Phase-40/42 admission, ordering, currentness, or lower-phase CAS checks.

Concurrent actors may change which Task is oldest between successful steps. That is acceptable: each subsequent mutation is still authorized by a fresh one-shot Manager admission. Phase 43 itself adds no Task affinity or lock.

---

## Result surface

The bounded driver returns an immutable trace, not a synthesized Task outcome.

The proposed result contains:

- the ordered tuple of exact `ManagerAdvanceOnceResult` step results;
- `step_count`;
- a typed stop reason;
- the fixed maximum-step value used by this implementation.

The stop-reason enum is limited to:

```text
NO_ACTIONABLE_WORK
NON_CONTINUABLE_RESULT
STEP_LIMIT_REACHED
```

`NO_ACTIONABLE_WORK` is used when the final one-shot result is exactly `NO_ACTIONABLE_WORK`.

`NON_CONTINUABLE_RESULT` is used for every other result outside the continuation whitelist, including successful terminal dispatch.

`STEP_LIMIT_REACHED` means all six executed results were continuable and the code-owned hard limit prevented another call.

The exact one-shot statuses, lower statuses, Task/PREP/claim/execution identities, and details remain in the step trace. Phase 43 does not collapse them into success/failure of the Task or project.

An invocation that cannot produce a typed `ManagerAdvanceOnceResult` must fail closed and must not continue.

---

## No implicit retry semantics

Phase 43 is repeated **progress**, not repeated **attempt**.

A result may authorize continuation only because the completed one-shot call proves a later governed lifecycle edge. The driver must never continue merely because a fresh admission might choose something else.

In particular it may not retry after:

- PREP acquisition loss;
- pre-planner failure;
- planner recovery-required state;
- recovery rejection or uncertainty;
- claim acquisition loss;
- dispatch pre-start failure;
- dispatch raise;
- dispatch recovery-required state;
- ambiguity, invalid state, or limit exhaustion.

The existing bounded retry policy inside the reviewed production execution owner remains the only accepted coding-attempt retry mechanism. Phase 43 creates no second retry budget and does not inspect `PolicyResult.outcome` or `PolicyAction`.

---

## Concurrency semantics

Phase 43 introduces no global Manager lock.

Two bounded drivers may run concurrently. Each individual step remains protected only by the accepted lower-phase currentness, revision, uniqueness, and CAS rules.

Required behavior:

- each driver independently stops on its first non-continuable one-shot result;
- a lost race must never be converted into an immediate retry by that driver;
- fresh admissions after positive progress may observe state advanced by another caller;
- the Phase-41 `PLANNER_STARTED` fence continues to guarantee at most one planner model call for one exact PREP;
- Phase-35/36 dispatch claim/execution ownership remains unchanged;
- no driver may exceed six calls to `advance_production_manager_once`;
- no concurrency outcome may authorize a seventh call, fallback loop, sleep, polling, or background reschedule.

Phase-43 acceptance must include a race where one driver loses a lower transition while newer work exists, proving the losing driver stops rather than immediately invoking Manager again.

---

## Production implementation boundary

The implementation should be isolated in a new small module, expected to be:

```text
src/origin_forge/production_manager_advance_bounded.py
```

It may import only the public one-shot Manager result/status/operation plus standard-library dataclass/enum support required for the result surface.

The new module must not import lower preparation, recovery, dispatch, model, execution-owner, database-store, or orchestration-policy mutation helpers.

The core loop should remain structurally equivalent to:

```text
results = []
repeat at most six times:
    result = advance_production_manager_once(runtime)
    append exact typed result
    if result.status is not in CONTINUATION_WHITELIST:
        STOP
STOP because fixed step limit reached
```

No exception-swallowing retry loop is permitted around `advance_production_manager_once`.

---

## Acceptance contract

Phase 43 is accepted only when adversarial tests prove all of the following:

1. a normal fresh PREPARE path may progress across fresh Manager admissions through planner return, WorkOrder audit, Phase-34 READY, and exactly one dispatch attempt, then stops on the dispatch result;
2. a `CLAIMED` recovery path can use at most six one-shot calls to reach the same dispatch boundary under sequential uncontended state;
3. each continuation performs a fresh call to the public `advance_production_manager_once` primitive rather than a pinned lower helper;
4. only the four frozen continuation statuses permit another step;
5. `PREPARATION_FAILED_PRE_PLANNER` stops immediately even when a newer Task is actionable;
6. `DISPATCH_RAISED` stops immediately even when a newer Task is actionable;
7. `DISPATCH_RETURNED` also stops immediately and does not drain a newer Task;
8. ambiguity, limits, invalid state, recovery-required state, claim loss, planner uncertainty, and no-actionable-work all stop without another Manager call;
9. a six-result all-continuable synthetic trace stops with `STEP_LIMIT_REACHED` and never performs a seventh one-shot call;
10. concurrent drivers preserve lower-phase at-most-once planner/dispatch ownership and a losing driver never converts a race result into an immediate retry;
11. the result trace preserves exact one-shot identities/statuses/details and does not derive Task success/failure from `PolicyResult`;
12. existing Phase-40/42 one-shot tests remain unchanged and green.

All exact-head acceptance must pass the normal Python 3.12 and Python 3.13 matrix with `ResourceWarning` treated as error.

---

## Explicit non-authority

Phase 43 does **not** add authority for:

- daemon/background Manager execution;
- timers, sleep/retry delays, polling, watchers, condition loops, or work queues;
- caller-selected or model-selected step budgets;
- processing another Task after a dispatch result in the same driver invocation;
- retrying a failed/stale/racing Manager action;
- selecting a fallback Task because the oldest action failed;
- changing `(Task.created_at, Task.id)` ordering;
- action-kind priority, Task priority, resource/cost/model scoring, or starvation policy;
- PREPPOL creation or replacement;
- direct recovery, activation, routing, planner, WorkOrder, Phase-34, claim, execution, or orchestration-policy calls outside `advance_production_manager_once`;
- planner replay after durable `PLANNER_STARTED`;
- Task status/outcome reinterpretation;
- Artifact adoption/signing;
- Project Intelligence mutation;
- Dream promotion;
- training/weight mutation;
- merge, release, or deployment authority.

---

## Implementation slices

### 43A — Bounded driver mechanics

Add the new module, fixed six-step bound, closed continuation whitelist, typed stop reason/result trace, strict type validation, and focused unit tests with the one-shot primitive mocked.

### 43B — Cross-phase acceptance

Exercise real Phase-40/42 one-shot behavior through sequential recovery/preparation/finalization/dispatch paths plus stop-on-failure, stop-on-dispatch, no-newer-work-drain, and concurrency race cases.

No production authority expansion beyond 43A is allowed in this slice.

### 43C — Documentation closure

Record accepted exact-head CI evidence, preserve the frozen architecture, mark Phase 43 DONE in the canonical roadmap, run the normal Python 3.12/3.13 matrix on the immutable closure head, and merge only that exact accepted SHA.

---

## Exit condition

Phase 43 is complete when Origin Forge can perform a finite sequence of already-governed Manager progress steps through fresh one-shot admissions, bounded by six calls, continuing only across the four exact internal lifecycle-success statuses and stopping on dispatch, failure, uncertainty, race loss, quiescence, or the hard limit—without adding a retry engine, queue processor, daemon, new scheduling policy, or Task-outcome authority.
