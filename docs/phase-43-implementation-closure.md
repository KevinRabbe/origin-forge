# Phase 43 — Governed Bounded Manager Driver — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-43-governed-bounded-manager-driver.md`. The planning document remains the frozen authority contract; this companion records the prerequisite concurrency-acceptance repair, accepted bounded-driver implementation, adversarial cross-phase acceptance, and exact-head CI evidence.

## Final bounded Manager boundary

Phase 43 adds one finite outer composition over the accepted public Phase-40/42 one-shot primitive:

```text
advance_production_manager_once(runtime)
```

The final authority shape is:

```text
fixed code-owned maximum of six steps
→ one fresh public Manager one-shot call
→ exact typed Manager result
→ continue only on the frozen positive-progress whitelist
→ otherwise STOP
```

Every permitted continuation performs a completely fresh Manager admission and oldest-candidate selection. Phase 43 carries no candidate, PREP, claim, or Task lock across steps and imports no lower preparation, recovery, finalization, dispatch, model, execution-owner, policy, timer, or queue mutation helper.

The driver is finite repeated progress, not a daemon, scheduler service, watcher, poller, queue drain, or retry engine.

## Hard bound and continuation whitelist

The accepted production constant is:

```text
MAX_MANAGER_ADVANCE_STEPS = 6
```

The limit is infrastructure-owned and is not exposed as a caller-selected, model-selected, Task-selected, or policy-selected argument.

The exact closed continuation whitelist is:

```text
PREPARATION_RECOVERY_ADVANCED
PREPARATION_PLANNER_RETURNED
WORK_ORDER_AUDITED
PHASE34_READY
```

Every other current or future Manager result is non-continuable until explicitly proven by a later architecture phase.

In particular, `DISPATCH_RETURNED` is a terminal stop for the bounded driver. A successful mechanical dispatch return does not authorize same-invocation processing of another Task and does not become Task-outcome truth.

## Immutable result surface

The accepted production module is:

```text
src/origin_forge/production_manager_advance_bounded.py
```

It exposes:

- fixed `MAX_MANAGER_ADVANCE_STEPS = 6`;
- frozen `MANAGER_ADVANCE_CONTINUATION_STATUSES`;
- typed `BoundedManagerAdvanceStopReason` values `NO_ACTIONABLE_WORK`, `NON_CONTINUABLE_RESULT`, and `STEP_LIMIT_REACHED`;
- frozen `BoundedManagerAdvanceResult` preserving the ordered tuple of exact `ManagerAdvanceOnceResult` values, exact step count, fixed maximum, final result, and stop reason;
- `advance_production_manager_bounded(runtime)` with no caller-selected budget.

Malformed lower return types or malformed lower status types raise immediately and are not retried. The result constructor also rejects impossible traces, including a non-continuable intermediate step, a mismatched no-action stop, or a claimed hard-limit stop before six continuable results.

The source contains one static call site to `advance_production_manager_once`, no `while` loop, no exception-swallowing retry wrapper, and no lower-phase mutation import.

## Stop semantics preserved

The bounded driver stops immediately on every result outside the four-value continuation whitelist, including:

- `NO_ACTIONABLE_WORK`;
- ambiguity, limit, invalid-state, and recovery-required Manager results;
- PREP acquisition loss;
- terminal pre-planner failure;
- planner recovery-required state;
- dispatch-claim loss;
- dispatch pre-start failure;
- `DISPATCH_RETURNED`;
- `DISPATCH_RAISED`;
- dispatch recovery-required state.

A stop never causes fallback to a newer Task in the same bounded-driver invocation.

This is especially important for concurrency: lower fail-closed currentness/CAS behavior remains authoritative. A race loser stops on its first non-continuable one-shot result instead of immediately re-admitting Manager and attempting to convert contention into progress elsewhere.

## Prerequisite fail-closed concurrency acceptance repair

The initial Phase-43 planning head was documentation-only but exposed four older scheduler-sensitive tests that still required an exact concurrent progress winner. That requirement contradicted the already accepted Phase-41/42 semantics, under which strict protected-read/currentness contention may safely produce zero progress while still guaranteeing at-most-once mutation/model ownership.

The dedicated prerequisite repair PR changed only four tests and no production code:

- `tests/test_phase39_preparation_acceptance.py`;
- `tests/test_phase40_manager_advance_acceptance.py`;
- `tests/test_production_preparation_planner_resume.py`;
- `tests/test_production_preparation_activation_recovery.py`.

The repaired tests still require at most one PREP owner/checkpoint/planner call, no fall-through, exact safe durable states, and no dispatch side effects. Existing sequential tests remain the liveness proof.

No production authority was changed by that prerequisite repair.

## Accepted exact-head evidence

- **Prerequisite fail-closed concurrency acceptance repair — PR #72:** exact head `9ce497784180f9c6b59cfa349827350540cec0be`; normal run `31764367630`; Python 3.12 and Python 3.13 both passed on the first exact-head run; merged as `6ec539cfc7d6e4d2f80be1931b1f7ae011d1644b`.
- **Phase-43 planning — PR #71:** exact rebuilt planning head `c8ae085cb4da661ec777dbf921f9dd81e8b28ee9`; normal run `31764772997`; Python 3.12 and Python 3.13 both passed on the first fresh exact-head run; merged as `21d35c6ec4bd819dfc6b25b5a7987abe8767f342`.
- **43A — bounded driver mechanics — PR #73:** exact head `509799ea4ce35a6a800e2635a8da3fdb4278fb5e`; normal run `31765239984`; Python 3.12 and Python 3.13 both passed on the first exact-head run; merged as `80f0e0be20f7611db7f03101652d8abac06f9c8b`.
- **43B — adversarial bounded-driver acceptance — PR #74:** exact head `bd26828b88a2d055ffd2739a9a42614631c15c21`; normal run `31765713379`; Python 3.12 and Python 3.13 both passed on the first exact-head run; merged as `ec3411940f01aad936a298fd0e3109af0579bc3d`.

## Cross-phase acceptance proved

The final Phase-43 acceptance suite proves:

1. a normal fresh PREPARE path reaches `PREPARATION_PLANNER_RETURNED → WORK_ORDER_AUDITED → PHASE34_READY → DISPATCH_RETURNED` in four fresh public Manager calls and then stops;
2. that returned dispatch can carry a canonical downstream `PolicyOutcome.BLOCKED` while Manager remains purely mechanical `DISPATCH_RETURNED`, proving no Task-outcome reinterpretation;
3. a second newer Task remains QUEUED with zero dispatch claim/execution after the first Task's terminal dispatch result, proving the driver is not a queue drain;
4. an exact current `CLAIMED` PREP uses the full six-step path `RECOVERED_ACTIVATED → RECOVERED_ROUTED → RESUMED_PLANNER_RETURNED → WORK_ORDER_AUDITED → PHASE34_READY → DISPATCH_RETURNED` with exactly six public one-shot calls and no seventh call;
5. the routed recovery path observes durable `PLANNER_STARTED` before the sole planner model call;
6. terminal pre-planner failure stops after one bounded-driver step, leaves the exact failed PREP, and never falls through to a newer Task;
7. `DISPATCH_RAISED` stops after one bounded-driver step and never acquires a claim for a newer dispatchable Task;
8. concurrent bounded drivers preserve the lower at-most-one planner boundary, each return after their first race/failure result, never convert the race into an immediate second Manager call, and never touch the newer Task;
9. focused mechanics tests prove every non-whitelisted current Manager status stops after one call, malformed lower result types fail closed without retry, and six synthetic continuable results cannot cause a seventh call;
10. existing Phase-40/41/42 one-shot scheduling, recovery, planner-fence, claim, and execution ownership remain unchanged.

## Authority exclusions preserved

Phase 43 adds no:

- daemon, background Manager service, timer, watcher, polling loop, work queue, or open-ended drain;
- caller/model/Task/PREPPOL-selected step budget;
- retry after PREP acquisition loss, stale authority, race loss, planner uncertainty, dispatch failure, or recovery-required state;
- fallback Task or PREP when the oldest action fails;
- cross-step pinned candidate or Task affinity lock;
- action-kind priority or change to global `(Task.created_at, Task.id)` ordering;
- direct lower recovery, activation, routing, planner, WorkOrder, Phase-34, claim, execution, or orchestration-policy mutation call;
- planner replay after durable `PLANNER_STARTED`;
- processing another Task after a dispatch result in the same driver invocation;
- Task success/failure/quarantine reinterpretation from Manager or `PolicyResult` mechanics;
- Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training/weight mutation, merge, release, or deployment authority.

## Closure gate

This documentation/roadmap closure branch starts from merged implementation main `ec3411940f01aad936a298fd0e3109af0579bc3d`. The final closure head must itself pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that immutable green documentation head may be used for ready-for-review transition and SHA-guarded merge.
