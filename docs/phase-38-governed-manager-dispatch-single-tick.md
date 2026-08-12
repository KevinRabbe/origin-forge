# Phase 38 — Governed Manager Dispatch Admission & Single Tick

Status: **DONE — implementation complete; final exact-head closure gate pending**

Phase 38 adds the smallest Manager-side scheduling boundary permitted after Phase 37: inspect already-existing durable dispatch authority, deterministically admit at most one already-READY Task, acquire one Phase-35 claim for its exact current Phase-34 chain, and invoke the existing Phase-37 single-shot dispatcher once.

Verified prerequisite `main`:

```text
6f26e0d7f0a563a1c0e0768caab34799f7192f9b
```

## Frozen boundary

The v1 path is:

```text
existing READY Tasks + existing Phase-34 evidence
        ↓
bounded read-only admission
        ↓
deterministic one-candidate selection
        ↓
one acquire_dispatch_claim(...) attempt
        ↓
one dispatch_claim_once(...) attempt
        ↓
STOP
```

One Manager call performs at most one candidate selection, one claim attempt, and one Phase-37 dispatch attempt. It never falls through to a different Task after a race, stale candidate, claim failure, or recovery-required result.

The proposed mutating API is intentionally narrow:

```text
dispatch_manager_tick(runtime)
```

The caller supplies no Task ID, binding/audit ID, context arguments, owner, adapter, binder, model, runtime provider, sandbox, retry count, priority, or fallback policy.

## No automatic Task activation

Phase 38 admits only canonical `READY` Tasks that already have current audited Phase-34 authority.

`activate_dependency_ready_task()` changes a Task from `QUEUED revision N` to `READY revision N+1` and changes the revision-bound Task hash. Pre-activation Phase-32/33/34 evidence therefore becomes stale by design. Combining activation, route/WorkOrder/binding rebuilding, claim acquisition, and invocation in one Manager path would collapse independent authority gates. That is outside Phase 38.

## No v1 priority scheduling

The legacy Task schema stores an integer `priority`, but the general Task creation path does not provide a dedicated Phase-38 scheduling bound/policy for it. Phase 38 will not silently promote that legacy field into execution authority.

The v1 candidate order is exactly:

```text
Task.created_at ASC
Task.id ASC
```

Priority, model availability, resource pressure, expected cost, retry history, objective text, and model judgment do not affect selection.

## Phase-34 multiplicity and ambiguity

Phase-34 evidence is immutable history. Reconstructing the same valid chain can create fresh `INRES-*`, `DISPBIND-*`, and `BINDAUD-*` IDs.

Multiple CURRENT_READY chains for one Task may collapse into one admission candidate only when their execution-authority semantics are identical, including Task revision/hash, WorkOrder hash, adapter/fingerprint, contract/hash, binder/fingerprint, request type/schema hash, and request-content hash.

Equivalent chains select one representative deterministically by `(binding_audit_id, dispatch_binding_id, input_resolution_id)` lexical order. This is selection among semantically identical authority, not authority preference.

If CURRENT_READY chains for one Task conflict in execution-authority semantics, the Task is `AMBIGUOUS_AUTHORITY` and is not dispatchable. Phase 38 never chooses one arbitrarily.

## 38A — Immutable dispatch admission

Add a bounded, non-creating admission reader over canonical Task state and existing protected Phase-34 evidence.

It must:

- use the existing immutable SQLite read guard for Task/claim state;
- enumerate only existing Phase-34 evidence without creating directories or objects;
- preserve existing object-count, byte, canonical JSON, hash, symlink, alias, ID, and frozen-relation defenses;
- revalidate candidate chains through existing Phase-34 currentness rules;
- admit only canonical READY + dependency-ready Tasks;
- exclude Tasks with an ACTIVE dispatch claim;
- collapse only exact semantically equivalent CURRENT_READY chains;
- classify conflicting current authority as ambiguous;
- bound the full scan and candidate count;
- fail closed on bound overflow instead of silently truncating the scheduling set;
- sort candidates only by `(created_at, task_id)`;
- create no SQLite sidecars and change no project-state bytes.

No claim acquisition or invocation occurs in 38A.

## 38B — Pure deterministic selector

Add a pure selector over one complete admission result.

Scheduling states are bounded to:

```text
NO_ELIGIBLE_TASK
ONE_SELECTED
AMBIGUOUS_AUTHORITY
LIMIT_EXCEEDED
INVALID_STATE
```

Ambiguous, incomplete, or invalid admission selects nothing. A complete non-empty candidate set selects exactly its first `(created_at, task_id)` candidate. The selector performs no I/O or mutation.

## 38C — One Manager tick

`dispatch_manager_tick(runtime)` must:

1. construct one complete admission result;
2. select at most one candidate;
3. for that candidate only, call `acquire_dispatch_claim(runtime, binding_id, audit_id, task_revision)`;
4. stop immediately if claim acquisition loses a race or currentness changed;
5. require the returned claim to bind the selected candidate exactly;
6. call `dispatch_claim_once(runtime, claim.claim_id, 0)` at most once;
7. preserve Phase-37 RETURNED/RAISED/recovery semantics without inspecting `PolicyResult.outcome`;
8. stop.

There is no rescan or second candidate within one tick.

If claim acquisition succeeds but Phase-37 fails before STARTED, the ACTIVE claim remains governed by existing Phase-35 lifecycle rules. Phase 38 does not silently release it and try another Task.

## Result boundary

A synchronous Manager result may describe Manager mechanics only, for example:

```text
NO_ELIGIBLE_TASK
CLAIM_NOT_ACQUIRED
DISPATCH_RETURNED
DISPATCH_RAISED
RECOVERY_REQUIRED
```

It may carry exact selected Task/binding/claim/execution IDs and bounded infrastructure-owned detail codes. It must not claim Task success/failure/quarantine, verification success, model quality, mergeability, or release readiness, and must not persist arbitrary model/exception/output text.

No new durable Manager result table is required.

## 38D — Read-only Manager status

Expose bounded read-only admission status: complete candidate count, deterministic selected candidate, exclusion/ambiguity counts, bound-overflow state, and zero mutation authority.

The read surface must not activate Tasks; create/repair Phase-32/33/34 authority; acquire/release/interrupt claims; begin/recover execution; invoke Phase 37; load models; acquire resources; create Workspaces/Runs; migrate/checkpoint SQLite; or create WAL/SHM/journal files.

No mutating CLI, HTTP, or cockpit control is added in Phase 38.

## 38E — Cross-phase acceptance

Acceptance must prove:

- QUEUED dependency-ready Tasks are not auto-activated/admitted;
- READY Tasks without current Phase-34 authority are not admitted;
- stale/corrupt/oversized/aliased/symlinked evidence fails closed;
- equivalent duplicate current chains collapse deterministically;
- conflicting current chains fail closed as ambiguous;
- Task priority does not affect v1 selection;
- created-at ties break by Task ID;
- filesystem enumeration order cannot change selection;
- scan/candidate bound overflow prevents selection;
- ACTIVE claim excludes the Task;
- concurrent Manager ticks create at most one claim/owner call for one selected Task;
- a claim-race loser does not fall through to another Task;
- authority becoming stale between admission and claim produces no second Task attempt;
- claim failure occurs before Phase-37 owner invocation;
- successful claim acquisition calls Phase 37 exactly once;
- recovery-required state is surfaced and never replayed;
- Manager does not reinterpret `PolicyResult.outcome` or transition Task outcome;
- no automatic activation, route/WorkOrder/binding synthesis, background loop, generic execution, adoption/signing, Project Intelligence mutation, Dream promotion, training, merge, or release authority is introduced.

Normal CI may mock the exact Phase-37 boundary for Manager-selection/concurrency proofs; no heavyweight model/runtime evidence is required for the standard merge gate.

## 38F — Closure

After 38A–38E independently pass exact-head normal CI:

- finalize this contract with accepted/rejected SHAs and run IDs;
- append Phase 38 DONE to `docs/roadmap.md` without rewriting prior phases;
- freeze one docs-only closure SHA;
- require normal Ubuntu Python 3.12 + 3.13 PASS on that exact SHA;
- revalidate exact head, mergeability, reviews, and threads;
- mark the implementation PR ready;
- repeat those checks;
- SHA-guarded squash merge;
- verify actual `main` equals GitHub's returned merge commit.

## Explicit exclusions

Phase 38 does not add automatic Task activation, automatic Phase-32/33/34 construction, more than one claim attempt per tick, fallback after a selected-candidate failure, dispatcher retry/replay, daemon/background polling, priority/resource/cost/model scheduling, generic adapter/model/tool/backend execution, caller-selected execution authority, arbitrary process authority, Task/Flow/Goal outcome transitions outside existing execution behavior, a second production truth model, Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training activation, merge/release authority, or mutating operator controls.

## Proposed slices

```text
38A  bounded immutable READY/Phase-34 admission enumeration
38B  pure deterministic selector + equivalence/ambiguity rules
38C  exact claim acquisition + one Phase-37 dispatch tick
38D  immutable Manager/admission status projection
38E  concurrency / no-fallback cross-phase acceptance
38F  documentation / roadmap closure
```

Every authority-expanding slice freezes one exact SHA and must pass the normal Ubuntu Python 3.12/3.13 matrix before the next slice begins.

## Exit condition

Phase 38 is complete when Origin Forge can inspect a complete bounded set of already-READY Tasks with pre-existing current audited Phase-34 authority, fail closed on incomplete/ambiguous admission, deterministically select exactly one candidate without priority/runtime heuristics, attempt exactly one Phase-35 claim, invoke the exact Phase-37 dispatcher at most once, stop on every race/staleness/recovery boundary without trying another Task, and expose Manager mechanics without creating a background scheduler or second production truth model.

---

## Implementation and CI closure evidence

Phase 38 was implemented cumulatively on PR #58 from the exact planning merge `0b1d3726cff048a4a4ec1b581d8d5aa968c3b92d`.

Accepted slice gates:

- **38A — immutable admission:** head `9b2a86a8c20c63db969cce90641b555488042457`; normal run `31625194743`; Python 3.12 PASS, Python 3.13 PASS.
- **38B — pure deterministic selector:** final head `d7acac42f1d10573a0485b7d728a95cd1742fa76`; normal run `31625741982`; Python 3.12 PASS, Python 3.13 PASS. Earlier selector heads cancelled only because later tightening commits superseded them.
- **38C — one Manager tick:** final head `61fca4185b980f529a128820f9ac09c0d4a52398`; normal run `31626571404`; Python 3.12 PASS, Python 3.13 PASS. The final semantics fail closed to `RECOVERY_REQUIRED` for uncertain post-dispatch state and never fall through to another Task.
- **38D — read-only Manager status:** final head `f3799d4f33c570851763fa844c5c221ba6106c22`; normal run `31626974464`; Python 3.12 PASS, Python 3.13 PASS. Later commits over the first 38D head were test-only proof tightening; production status code was unchanged.
- **38E — cross-phase concurrency/no-fallback acceptance:** final head `5888524b1977126c62541681bb610aa086e11136`; normal run `31628078866`; Python 3.12 PASS, Python 3.13 PASS.

Rejected 38E evidence:

- head `7f82d56ddf9f04f947936a0f91414565e129b34a`, run `31627443373`: Python 3.13 PASS; Python 3.12 FAIL in the exact concurrent-Manager acceptance case. The real concurrent `acquire_dispatch_claim()` race behaved correctly; the mocked Phase-37 boundary performed an extra immutable `read_dispatch_claim()` while the losing authoritative writer still held journal state, and the Phase-30 read guard correctly failed closed. The accepted repair changed only `tests/test_phase38_manager_dispatch_acceptance.py`, passing the already-returned winning `DispatchClaim` object into the mock instead of introducing that unrelated extra read. No production code or immutable-read guard was weakened.

Final implemented authority remains exactly the frozen boundary:

```text
bounded immutable admission
→ pure one-candidate selection
→ one Phase-35 claim attempt
→ one Phase-37 dispatch attempt
→ STOP
```

There is still no automatic Task activation, Phase-32/33/34 authority synthesis, fallback to a second Task, dispatcher retry/replay, daemon/background polling, priority/resource/cost/model scheduling, mutating Manager CLI/HTTP/cockpit surface, generic backend authority, or second production truth model.

The documentation/roadmap closure commit created after these code/test proofs is intentionally a new SHA and must independently pass the normal Python 3.12/3.13 matrix before PR #58 may leave draft state or merge.