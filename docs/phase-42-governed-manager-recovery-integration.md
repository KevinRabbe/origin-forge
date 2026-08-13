# Phase 42 — Governed Manager Recovery Integration

Status: **PLANNED — architecture frozen before implementation**

Verified prerequisite `main`:

```text
f4c9d690095b7d5cdd757f9c623502955cf780b9
```

Phase 42 closes the scheduling gap deliberately left between Phase 40 and Phase 41.

Phase 40 already performs one immutable Manager admission, selects exactly the oldest admitted Task, executes at most one governed action for that Task, and then stops. It deliberately reports current pre-planner `ACTIVE PREP-*` receipts at `CLAIMED`, `ACTIVATED`, or `ROUTED` as recovery-required rather than replaying preparation.

Phase 41 now provides the missing lower-level recovery primitive:

```text
recover_preparation_once(runtime, preparation_id)
```

That primitive independently classifies one exact existing PREP, advances at most one already-governed recovery edge, never selects another PREP or Task, durably fences planner invocation, and never dispatches.

Phase 42 does **not** build a retry loop or a second recovery system. It teaches the existing Phase-40 Manager admission/coordinator to distinguish an exactly current pre-planner PREP that is safe to hand to Phase 41 from evidence that merely requires recovery/operator attention.

The authority shape is:

```text
one immutable Manager admission
    ↓
oldest admitted Task only
    ↓
exact current ACTIVE PREP at CLAIMED / ACTIVATED / ROUTED
    ↓
RECOVER_PREPARATION candidate
    ↓
recover_preparation_once(runtime, exact_preparation_id) exactly once
    ↓
project typed lower result
    ↓
STOP
```

There is no same-call continuation to WorkOrder finalization, Phase-34 finalization, dispatch claim acquisition, or execution after the recovery primitive returns.

---

## Why a distinct Manager action is required

Phase 40 currently uses `ManagerAdvanceActionKind.RECOVERY_REQUIRED` for two semantically different conditions:

1. an exact current pre-planner PREP whose next operation is now reconstructable by Phase 41; and
2. stale, invalid, ambiguous, or otherwise unsupported PREP authority that must remain fail-closed.

Those conditions must not become conflated merely because Phase 41 exists.

Phase 42 therefore adds a new Manager admission action:

```text
RECOVER_PREPARATION
```

Only an exact current `ACTIVE` PREP at one of these stages may be classified as `RECOVER_PREPARATION`:

```text
CLAIMED
ACTIVATED
ROUTED
```

The existing `RECOVERY_REQUIRED` action remains non-mutating and fail-closed. A stale/invalid projection, unsupported lifecycle shape, or other authority uncertainty must continue to produce `RECOVERY_REQUIRED`; the Manager must perform zero recovery action for that candidate.

This distinction is part of the Phase-42 authority boundary, not merely a status rename.

---

## Admission contract

Phase 42 extends the existing immutable Phase-40 admission only enough to identify safe automatic recovery candidates.

For each PREP-backed Task, the admission must continue to load the same bounded inventory and exact Phase-39 status projection used by Phase 40.

The classification order is authoritative:

1. if the PREP projection is stale, invalid, non-current, malformed, or otherwise fails the existing Phase-40 currentness rules, emit `RECOVERY_REQUIRED` exactly as today;
2. otherwise, if the PREP is `ACTIVE` and its exact current stage is `CLAIMED`, `ACTIVATED`, or `ROUTED`, emit `RECOVER_PREPARATION` with the exact PREP ID and stage;
3. otherwise preserve all accepted Phase-40 post-planner/finalization/dispatch classifications unchanged.

`RECOVER_PREPARATION` carries no caller-selectable recovery policy. Its candidate shape contains only the already admitted scheduling identity:

- exact Task ID;
- exact Task creation timestamp/order key;
- exact PREP ID;
- exact current pre-planner PREP stage.

It must not carry or accept caller-provided Task revisions/hashes, PREPPOL authority, route IDs, planner/model settings, retry counts, fallback PREPs, fallback Tasks, or dispatch authority.

Add an exact `recover_preparation_count` admission counter and include it in the same structural validation performed for every other Manager action kind. Existing counters retain their meanings; in particular, `recovery_required_count` counts only non-automatic fail-closed recovery-required candidates after Phase 42.

No change is permitted to candidate ordering. Admission remains strictly ordered by `(task_created_at, task_id)`.

---

## Selection remains unchanged

`select_manager_advance_candidate(...)` remains pure and continues to select only the first candidate from a structurally valid immutable admission.

Phase 42 must not:

- prefer `RECOVER_PREPARATION` over an older dispatch/prepare/finalize candidate;
- prefer dispatch over recovery;
- recompute a minimum after admission;
- skip an oldest Task because its recovery loses a race or returns fail-closed;
- fall through to a newer Task;
- add resource, cost, model-availability, priority, retry, or policy scoring.

The oldest admitted Task remains the sole scheduling authority for one Manager call.

---

## One-shot recovery composition

When and only when the selected candidate has `action_kind == RECOVER_PREPARATION`, `advance_production_manager_once(runtime)` may call:

```text
recover_preparation_once(runtime, candidate.preparation_id)
```

exactly once.

Before the call, the coordinator must validate the frozen candidate shape locally:

- `preparation_id` is present and non-empty;
- `preparation_stage` is exactly `CLAIMED`, `ACTIVATED`, or `ROUTED`;
- no dispatch/preparation-policy/preparation-candidate authority is attached.

The Manager does **not** trust the admission snapshot as mutation authority. Phase 41 independently reloads and revalidates the exact PREP and all authority-bearing provenance before any mutation. A race between admission and recovery therefore resolves through the Phase-41 result, never through Manager-side repair or replay.

After the Phase-41 call returns, the Manager must stop. It may not inspect the new PREP state and perform a second action in the same outer call.

In particular, a successful recovery that reaches `PLANNER_RETURNED` must **not** immediately invoke `finalize_preparation_work_order_audit()`. That is a later Manager invocation under a fresh immutable admission.

Likewise, a recovery that reaches `ACTIVATED` or `ROUTED` must not immediately call recovery again in the same Manager invocation.

---

## Result projection

Phase 42 adds a Manager-level success status:

```text
PREPARATION_RECOVERY_ADVANCED
```

This status means only that the single Phase-41 recovery primitive returned a typed result proving that its one governed recovery operation advanced/adopted durable PREP state. It does not mean the Task succeeded, planning succeeded globally, dispatch occurred, or execution completed.

The exact Phase-41 status is retained in `ManagerAdvanceOnceResult.lower_status`.

The following Phase-41 results project to `PREPARATION_RECOVERY_ADVANCED`:

```text
RECOVERED_ACTIVATED
ADOPTED_ACTIVATION_CHECKPOINT
RECOVERED_ROUTED
RESUMED_PLANNER_RETURNED
RECOVERED_PLANNER_RETURNED
```

The latter two are possible if the selected exact PREP is at/races through the planner boundary before the lower primitive completes its independent classification. Their inclusion does not authorize Manager-side planner replay; all planner call/evidence rules remain owned by Phase 41.

Fail-closed projection is:

- `AMBIGUOUS_EVIDENCE` → `AMBIGUOUS_AUTHORITY`;
- `LIMIT_EXCEEDED` → `LIMIT_EXCEEDED`;
- `INVALID_STATE` → `INVALID_STATE`;
- `PLANNER_RECOVERY_REQUIRED`, `ACTIVATION_RECOVERY_REJECTED`, `ROUTE_RECOVERY_REJECTED`, `INVALID_AUTHORITY`, `POST_PLANNER_NOT_REQUIRED`, `READY_NOT_REQUIRED`, and `TERMINAL_NOT_REQUIRED` → `RECOVERY_REQUIRED`.

For every typed lower result, preserve its exact status in `lower_status` and its diagnostic detail in `detail`.

The projection must also validate identity:

- lower `preparation_id` must equal the selected candidate PREP ID;
- if the lower result carries a Task ID, it must equal the selected candidate Task ID;
- an invalid return type or mismatched identity projects to `INVALID_STATE` and performs no alternate action.

The Manager must never interpret a Phase-41 recovery result as Task outcome truth.

---

## Planner-boundary invariants remain Phase-41-owned

Phase 42 adds no planner call site of its own.

For a selected `ROUTED` PREP, the only legal path to model invocation is still the Phase-41/Phase-39 shared planner owner:

```text
ROUTED
  → durable PLANNER_STARTED compare-and-swap
  → at most one existing WorkOrder-planner call
  → exact return checkpoint when trustworthy
```

If `PLANNER_STARTED` is already durable or becomes durable concurrently, Phase 42 may not invoke a planner directly or reset/replay the marker.

Evidence-only `PLANNER_STARTED` reconciliation remains inside `recover_preparation_once(...)` and never calls the model.

No Phase-42 module may import or call the WorkOrder planner, scheduled model adapter, model runtime/provider, or planner evidence writer directly.

---

## Concurrency and races

Phase 42 does not introduce a global Manager lock.

Two concurrent Manager invocations may read the same immutable admission and select the same oldest `RECOVER_PREPARATION` candidate. Each outer invocation may call `recover_preparation_once(...)` at most once.

Phase-41 expected-revision/currentness/CAS rules remain the mutation authority. Therefore:

- at most one caller may win a given exact PREP recovery transition;
- a losing caller stops on its lower result and never falls through to another Task;
- concurrent outer calls may serialize onto different later recovery edges if durable state advances between their independent Phase-41 classifications; this is acceptable because each Manager invocation still owns only one lower recovery call;
- the existing durable `PLANNER_STARTED` fence must continue to guarantee at most one planner model call for the PREP;
- no race authorizes same-call WorkOrder finalization or dispatch.

A concurrency test must prove the no-fallback rule explicitly with a newer actionable Task present.

---

## Existing Phase-40 behavior that must not change

Phase 42 is an additive composition boundary. The following accepted Phase-40 behaviors remain unchanged:

- one immutable admission per Manager call;
- one pure oldest-candidate selection per Manager call;
- no loop in `advance_production_manager_once(...)`;
- `NO_ACTIONABLE_WORK`, admission ambiguity, limits, and invalid state remain non-mutating;
- PREP acquisition remains Phase-39-owned;
- WorkOrder finalization remains the existing Phase-39 finalizer;
- Phase-34 binding finalization remains the existing Phase-39 finalizer;
- dispatch claim/invocation remains Phase-38-owned;
- a lost race never falls through to a newer candidate;
- Manager never interprets `PolicyOutcome` or Task outcome;
- terminal retry suppression and active-claim exclusion remain unchanged.

The existing `RECOVERY_REQUIRED` action remains zero-action. Phase 42 must preserve and strengthen the Phase-40 unit test that proves this.

---

## Explicit non-authority

Phase 42 does **not** add authority for:

- repeated Manager advancement;
- retry loops, daemons, timers, polling, watchers, or background work;
- fallback to a second Task or PREP;
- Task reprioritization or starvation policy;
- Task READY→QUEUED demotion, retry, reset, or outcome reinterpretation;
- PREP interruption, replacement, deletion, receipt stealing, or terminal repair;
- direct Phase-35 activation outside Phase-41 recovery ownership;
- direct Phase-32 routing outside Phase-41 recovery ownership;
- planner invocation except through the existing Phase-41 shared planner-call owner;
- planner replay after durable `PLANNER_STARTED`;
- Phase-38 dispatch claim acquisition from the recovery branch;
- Phase-37 execution invocation from the recovery branch;
- WorkOrder audit finalization in the same call after recovery;
- Phase-34 finalization in the same call after recovery;
- Artifact adoption/signing;
- Project Intelligence mutation;
- Dream promotion;
- training, merge, or release authority.

A future phase may add repeated outer scheduling or operator policy only after defining its own durable liveness, fairness, retry, and shutdown semantics. Phase 42 does not pre-authorize such a loop.

---

## Acceptance matrix

Final Phase-42 acceptance must cover at least the following.

### Admission and selection

- exact current `ACTIVE/CLAIMED` PREP → `RECOVER_PREPARATION`;
- exact current `ACTIVE/ACTIVATED` PREP → `RECOVER_PREPARATION`;
- exact current `ACTIVE/ROUTED` PREP → `RECOVER_PREPARATION`;
- stale/invalid/non-current PREP at any stage → existing `RECOVERY_REQUIRED`, never `RECOVER_PREPARATION`;
- `PLANNER_STARTED` / `PLANNER_RETURNED` / `WORK_ORDER_AUDITED` current continuations remain on their existing Phase-40 paths;
- `recover_preparation_count` and `recovery_required_count` exactly match candidate contents;
- immutable candidate ordering remains `(created_at, task_id)`;
- oldest `RECOVER_PREPARATION` candidate wins over every newer actionable candidate regardless of newer action kind.

### Manager composition

- selected `RECOVER_PREPARATION` calls `recover_preparation_once(runtime, exact_preparation_id)` exactly once;
- selected ordinary `RECOVERY_REQUIRED` calls it zero times;
- invalid selected recovery candidate shape fails closed before the lower call;
- invalid lower return type fails closed;
- mismatched lower PREP ID fails closed;
- mismatched non-null lower Task ID fails closed;
- every successful Phase-41 advancement maps to `PREPARATION_RECOVERY_ADVANCED` with exact `lower_status`;
- ambiguous/limit/invalid/rejected/not-required lower statuses map exactly as frozen above;
- Manager performs no second recovery call after any lower result;
- Manager performs no WorkOrder finalization, Phase-34 finalization, dispatch claim, or dispatch invocation after recovery in the same call.

### Cross-phase crash/concurrency safety

- acquisition-crash `CLAIMED` state selected by Manager advances through one Phase-41 recovery call and stops;
- lost legacy activation checkpoint may be adopted through Manager only when Phase-41 evidence rules accept it;
- `ACTIVATED` route recovery through Manager reuses/publishes only Phase-41-governed route evidence and stops;
- `ROUTED` recovery through Manager persists `PLANNER_STARTED` before any model call;
- two concurrent Managers cannot cause duplicate planner calls;
- a recovery race never causes fallback to a newer Task;
- with a newer dispatchable Task present, failure/race of the oldest recovery candidate performs zero dispatch on the newer Task;
- recovery through Manager creates no `DISPCLAIM-*` or `DISPEXEC-*` in the same invocation;
- a lower result reaching `PLANNER_RETURNED` remains unfinalized until a later fresh Manager invocation;
- existing Phase-40 preparation/finalization/dispatch acceptance remains green unchanged except for intentional action/count/result extensions.

Normal CI may use deterministic fake planner boundaries and injected races. Heavyweight model/backend evidence is not required for the normal merge gate.

---

## Source-shape guard

The Phase-40 source-shape test must be extended rather than weakened.

`advance_production_manager_once(...)` must still contain exactly:

```text
1 immutable admission call
1 selection call
≤1 dispatch helper call site
≤1 preparation helper call site
≤1 WorkOrder finalizer call site
≤1 Phase-34 finalizer call site
≤1 recover_preparation_once call site
0 loops
```

The public signature remains exactly:

```text
advance_production_manager_once(runtime)
```

No public caller-supplied Task/PREP/retry/priority argument is added.

---

## Proposed implementation slices

```text
42A  admission split: RECOVER_PREPARATION vs fail-closed RECOVERY_REQUIRED
42B  typed Manager recovery projection + exactly-one Phase-41 call and STOP
42C  adversarial cross-phase concurrency/race/no-fallback/no-dispatch acceptance
42D  implementation closure + canonical roadmap closure
```

Each authority-expanding slice must freeze one exact commit SHA and pass the normal Ubuntu Python 3.12/3.13 matrix before the next slice begins.

If implementation shows that one slice contains two independently meaningful authority gates, split and gate those sub-slices separately rather than preserving the lettering artificially.

---

## Exit condition

Phase 42 is complete only when the repository proves that one normal Manager invocation can automatically advance one exactly current oldest pre-planner PREP through the already accepted Phase-41 primitive while preserving every Phase-40 scheduling invariant:

```text
one admission
one oldest selection
one exact PREP recovery call
no fallback
no loop
no same-call continuation
no dispatch authority expansion
```

The canonical roadmap may be marked Phase 42 DONE only after the final implementation/acceptance head and the roadmap-closure head both pass the normal Python 3.12/3.13 matrix with unrelated heavyweight evidence workflows disarmed/skipped.