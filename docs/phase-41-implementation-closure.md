# Phase 41 — Governed Preparation Recovery — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-41-governed-preparation-recovery.md`. The planning document remains the frozen authority contract; this companion records the accepted implementation, repairs, and exact-head CI evidence.

## Final recovery boundary

Phase 41 adds one explicit recovery operation over one existing preparation receipt:

```text
recover_preparation_once(runtime, preparation_id)
```

The caller supplies only a `PREP-*` identity. Immutable classification determines the one permitted recovery edge. A call never selects another Task or PREP, never loops, never retries another candidate, and never gains Manager, dispatch-claim, dispatch-execution, Task-outcome, merge, release, or background scheduling authority.

Accepted recovery states are composed from already-governed lower primitives:

- exact dependency-ready `CLAIMED` → atomic Phase-35 Task activation + PREP `ACTIVATED` checkpoint;
- exact legacy post-activation `CLAIMED` evidence → activation-checkpoint adoption only;
- exact `ACTIVATED` → current Phase-32 route recovery/reuse + PREP `ROUTED` checkpoint;
- exact `ROUTED` → durable `PLANNER_STARTED` compare-and-swap, then at most one existing Phase-33 WorkOrder-planner call;
- exact `PLANNER_STARTED` → successful planner-evidence reconciliation only, with model replay forbidden;
- later post-planner, READY, terminal, stale, or ambiguous states stop without widening authority.

## Normal path and recovery path share one planner-call owner

Phase41D exposed a concurrency-sensitive distinction between two valid read boundaries:

- explicit recovery uses the Phase-30 immutable SQLite guard and therefore requires a quiescent database/journal state;
- the normal Phase-39 authoritative write path may legitimately have WAL/SHM bookkeeping under concurrent callers and must not treat that live journal state as stale authority.

The repair did **not** weaken the immutable read guard. Instead:

- explicit recovery keeps the strict quiescent D1 reconstruction;
- normal Phase39 freezes exact PREPPOL provenance before acquisition and uses a WAL-safe same-call current-state boundary after activation/routing;
- both paths converge on the same D2 executor that owns the durable `PLANNER_STARTED` no-replay fence, the sole `planner.propose()` call site, and the planner-return checkpoint.

This preserves the invariant:

```text
one validated ROUTED authority
→ one PLANNER_STARTED CAS winner
→ at most one model-backed planner call
→ return checkpoint or explicit evidence recovery
```

There is no automatic replay after a durable planner-start marker.

## Accepted slice evidence

- **41D2 — single ROUTED planner resume:** exact head `02443127c9ac8912e088a4c53e5b815c6c5d04f1`; GitHub Actions run `31699829874`; Python 3.12 and 3.13 passed.
- **41D3 — Phase39 shared-authority inheritance and WAL-safe normal boundary:** exact head `6ac28e6d984ddc1d6cfb88a40ab8a1b3b4732337`; run `31722569013`; Python 3.12 and 3.13 passed.
- **41E — one-PREP recovery composition:** exact head `b0782ac806b7d6c157d6006962f8feeebfe65481`; run `31723644015`; Python 3.12 and 3.13 passed.
- **41F — adversarial cross-phase acceptance:** exact test-only head `3d651f2193538b68a11371722961c6b8e5c31692`; run `31724154244`; Python 3.12 and 3.13 passed.

Earlier 41A–41D1 slices established immutable classification, exact Phase-35 activation-event reconstruction/adoption, atomic activation+checkpoint mechanics, bounded Phase-32 route recovery, and the read-only ROUTED planner boundary. Their accepted implementation remains unchanged by the final D3/41E/41F closure.

## Cross-phase acceptance proved

The final acceptance suite proves two real crash windows with durable project state:

1. crash after PREP acquisition: separate explicit recovery calls advance exactly one edge at a time through activation, routing, and one planner call, then stop post-planner with zero dispatch claims/executions;
2. crash after a successful planner call but before PREP return checkpoint: `PLANNER_STARTED` recovery reconstructs the exact existing successful planner evidence while `ScheduledModelAdapter.generate` is forbidden, then records `PLANNER_RETURNED` without replay.

The existing Phase39/40 concurrency suites remain green with the shared planner-call authority, including real concurrent preparation acquisition/model-call behavior.

## Authority exclusions preserved

Phase 41 adds no:

- Manager admission, selection, retry loop, daemon, timer, or background polling;
- second-Task/PREP fallback after a stale/racing recovery action;
- caller-selected Task, PREPPOL, route, adapter, model role/profile/provider, WorkOrder, binder, dispatch claim, or execution input;
- model replay after durable `PLANNER_STARTED`;
- Phase-38 claim acquisition or Phase-37 execution invocation;
- Task success/failure/quarantine reinterpretation;
- Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training, merge, or release authority.

## Closure gate

The documentation/roadmap closure head produced after the accepted `3d651f2193538b68a11371722961c6b8e5c31692` code/test boundary must itself pass the normal Python 3.12/3.13 matrix. Only that immutable green documentation head may be used for ready-for-review transition and SHA-guarded merge.
