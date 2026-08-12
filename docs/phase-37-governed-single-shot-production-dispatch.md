# Phase 37 — Governed Single-Shot Production Dispatch Invocation

Status: **PLANNED — architecture only; no production dispatch invocation yet**

Phase 37 is the first Origin Forge phase permitted to cross the production invocation boundary prepared by Phases 31–36.

Its job is deliberately narrow: take one exact current Phase-35 `ACTIVE` dispatch claim, establish the exact Phase-36 `DISPEXEC STARTED` ownership receipt, reconstruct the already-frozen `BoundedRetryPolicy.drive@1` request from the exact Phase-34 binding, invoke the one reviewed execution owner **exactly once**, and terminalize the execution/claim relation according to whether that Python call returned or raised.

Phase 37 does not add a background dispatcher, automatic claim acquisition, automatic Task activation, a generic adapter switch, caller-supplied execution parameters, dispatcher-level retry, or a second Task/Run/Workspace truth model.

---

## Verified prerequisite state

Phase 36 is merged and verified on `main` at:

```text
d92b2b5b8a832da49ab7b9679de14bdb244661d0
```

The merged execution boundary now provides:

```text
READY Task
  ↓
exact Phase-32 route
  ↓
exact audited Phase-33 WorkOrder
  ↓
exact Phase-34 input resolution / typed binding / audit
  ↓
Phase-35 ACTIVE DISPCLAIM
  ↓
Phase-36 trusted execution owner + protected dependency plan
  ↓
DISPEXEC STARTED + exact lazy dependencies
  ↓
STOP
```

The reviewed execution owner is exactly:

```text
owner_id:             originforge.execution.bounded-retry@1
adapter_id:           originforge.code.bounded-retry
dispatch_contract_id: code.bounded-retry@1
binder_id:            binder.code.bounded-retry@1
request_type_id:      BoundedRetryPolicy.drive@1
```

The Phase-34 binding already persists the complete canonical request projection required by `BoundedRetryPolicy.drive()`:

```text
task_id
selected_paths
auto_context
context_seed_paths
structural_context
semantic_context
```

The Phase-34 binder independently reconstructs that projection from the exact audited WorkOrder and stores it as canonical bounded JSON with a request-content hash. Phase 37 therefore has no reason to accept any of those fields from its caller.

---

## Newly identified prerequisite defect

The Phase-36 ownership repair deliberately leaves the originating dispatch claim `ACTIVE` for the entire `DISPEXEC STARTED` window. That ACTIVE row is the durable exclusion lock preventing another process from acquiring a second claim for the same Task.

However, the pre-existing Phase-35 lifecycle functions currently permit:

```text
release_dispatch_claim(ACTIVE)
interrupt_dispatch_claim(ACTIVE)
```

without checking whether the claim already owns a `DISPEXEC STARTED` receipt.

That was valid before Phase 36 existed, but it is unsafe once Phase 37 introduces a real long-running call: a concurrent legacy release/interruption could remove the ACTIVE exclusion lock while the execution owner is still running.

Therefore the first Phase-37 gate is an ownership-sealing repair. No production `drive()` call may be introduced until that repair is independently green.

---

## Core Phase-37 boundary

The accepted v1 flow is:

```text
exact ACTIVE DISPCLAIM + expected claim revision
        ↓
freeze exact Phase-34 request projection
        ↓
begin_dispatch_execution(...)
        ↓
DISPEXEC STARTED
claim remains ACTIVE and sealed against legacy terminalization
        ↓
invoke exactly one code-owned owner:
BoundedRetryPolicy.drive(**frozen_projection)
        ↓
       ┌───────────────────────┐
       │                       │
   normal return          Python Exception
       │                       │
DISPEXEC RETURNED        DISPEXEC RAISED
claim CONSUMED           claim CONSUMED
       │                       │
       └──────────┬────────────┘
                  ↓
          synchronous caller
```

If the process is interrupted, killed, crashes, or loses durable terminalization after the call boundary, the existing Phase-36 `STARTED + ACTIVE` recovery state remains authoritative. The dispatcher must **not replay the call automatically**.

---

## 37A — Seal ACTIVE claim ownership during STARTED execution

Advance the core SQLite schema to v10 with one narrow cross-table invariant.

Conceptually:

```sql
BEFORE UPDATE OF status ON dispatch_claims
WHEN OLD.status = 'ACTIVE'
 AND NEW.status IN ('RELEASED', 'INTERRUPTED')
 AND EXISTS (
     SELECT 1
     FROM dispatch_executions
     WHERE claim_id = OLD.claim_id
       AND status = 'STARTED'
 )
→ ABORT
```

This trigger protects the ownership lock even if an older trusted lifecycle function is called concurrently.

The existing Phase-36 execution-specific interruption remains valid because its authoritative transaction first changes:

```text
DISPEXEC STARTED → INTERRUPTED
```

and only then changes:

```text
claim ACTIVE → INTERRUPTED
```

within the same transaction. By the time the claim row is updated, no STARTED execution remains.

The Phase-35 application lifecycle should also perform an explicit same-transaction STARTED-execution check before legacy `RELEASED` / `INTERRUPTED` transitions so callers receive a clear domain error rather than relying on the SQLite trigger message.

Required 37A proofs:

- v9→v10 migration preserves every claim/execution row exactly;
- fresh databases reach schema v10;
- ACTIVE claim without execution may still be RELEASED or legacy INTERRUPTED;
- ACTIVE claim with STARTED execution cannot be RELEASED;
- ACTIVE claim with STARTED execution cannot be legacy INTERRUPTED;
- concurrent legacy lifecycle vs execution begin serializes to a safe state;
- execution-specific `interrupt_dispatch_execution()` remains legal and atomically terminalizes both objects;
- returned/raised execution terminalization remains legal;
- no `BoundedRetryPolicy.drive()` call exists in 37A.

This slice is a hard prerequisite for all later Phase-37 invocation work.

---

## 37B — Frozen trusted invocation request

Add one infrastructure-owned typed in-memory request projection for the reviewed owner, reconstructed solely from the exact persisted Phase-34 binding.

Conceptually:

```text
BoundedRetryInvocationRequest(
    task_id,
    selected_paths,
    auto_context,
    context_seed_paths,
    structural_context,
    semantic_context,
    request_content_hash,
)
```

It is not a new durable truth object. It is a strict invocation view over existing immutable Phase-34 evidence.

The decoder must require all of the following exact relations:

- execution owner is `originforge.execution.bounded-retry@1`;
- adapter is `originforge.code.bounded-retry`;
- dispatch contract is `code.bounded-retry@1`;
- binder is `binder.code.bounded-retry@1` with exact current code-owned fingerprint;
- request type is `BoundedRetryPolicy.drive@1`;
- request schema hash equals the trusted Phase-34 binder schema;
- binding ID/hash exactly match the claim and later STARTED execution;
- canonical request JSON decodes to exactly the six expected fields;
- `task_id` equals the exact claim Task;
- manual mode has non-empty selected paths and no seed paths;
- automatic mode has no selected paths;
- seed paths require automatic mode;
- booleans are exact booleans rather than integer-like values;
- path arrays remain within the already-frozen canonical request bounds;
- request-content hash recomputes exactly.

The Phase-37 public API must not accept any direct override for context mode, paths, model role/profile, sandbox, runtime provider, endpoint, loader, Workspace manager, execution owner, adapter, binder, or contract.

No owner call occurs in 37B.

---

## 37C — One synchronous invocation coordinator

Introduce one code-owned internal coordinator with the deliberately narrow API:

```text
dispatch_claim_once(
    runtime,
    claim_id,
    expected_claim_revision,
)
```

No other production execution parameters are accepted.

Required ordering:

1. Read and freeze the exact Phase-34 invocation request bound by the claim.
2. Call `begin_dispatch_execution(runtime, claim_id, expected_claim_revision)`.
3. Require the returned STARTED receipt and dependency plan to match the frozen binding/request identity exactly.
4. Call only:

```python
started.dependencies.bounded_retry_policy.drive(
    task_id=request.task_id,
    selected_paths=request.selected_paths,
    auto_context=request.auto_context,
    context_seed_paths=request.context_seed_paths,
    structural_context=request.structural_context,
    semantic_context=request.semantic_context,
)
```

5. Make that call exactly once.
6. If it returns normally with `PolicyResult`, terminalize the exact execution `STARTED → RETURNED` and the claim `ACTIVE → CONSUMED` using the original frozen revisions.
7. If it raises an ordinary `Exception`, terminalize the exact execution `STARTED → RAISED` and the claim `ACTIVE → CONSUMED`, then surface a bounded infrastructure-owned invocation error chained from the original exception.
8. If durable terminalization itself fails after the owner was called, surface a terminalization/recovery error containing the exact execution ID and **never call the owner again**.
9. `KeyboardInterrupt`, `SystemExit`, process death, host crash, or other `BaseException`/out-of-process interruption must not trigger a speculative automatic replay. If no trustworthy terminal transition was committed, the durable state remains STARTED + ACTIVE for explicit recovery.

A normal `PolicyResult` with any of these outcomes still means the invocation itself RETURNED:

```text
SUCCEEDED
BLOCKED
FAILED
QUARANTINED
```

Phase 37 must not translate those outcomes into a different `DISPEXEC` state. The existing `BoundedRetryPolicy`, Task, Run, Workspace, Artifact and Verification state remains the authoritative production truth.

---

## Invocation detail / error boundary

Phase 37 does not add a second durable result object.

Rationale:

- `PolicyResult` summarizes state already represented by authoritative Task/Run/Workspace/Verification records;
- persisting a second result structure would create drift/reconciliation pressure without adding execution authority;
- `DISPEXEC` is intentionally only invocation-mechanics evidence.

For `RETURNED`, the terminal detail should be a fixed infrastructure-owned bounded statement that the trusted owner returned normally. It must not persist arbitrary model text, file content, WorkOrder payload, traceback, or `PolicyResult.reason`.

For `RAISED`, terminal detail may identify only a bounded exception class/type commitment; arbitrary exception messages and tracebacks are not durable dispatch evidence. Existing downstream Task/Run/Verification evidence remains the place for governed execution diagnostics.

The synchronous return wrapper may carry the live `PolicyResult` to its trusted caller, but that wrapper is not canonical persisted truth.

---

## Exactly-once-at-the-dispatch-boundary semantics

Phase 37 cannot provide distributed exactly-once execution in the mathematical sense across arbitrary host failure. It can provide the stronger safe property needed by Origin Forge:

```text
no automatic duplicate invocation after durable STARTED ownership exists
```

The state machine is intentionally fail-closed:

```text
before STARTED commit
    → no call has occurred; begin may safely fail

STARTED committed, call not yet made
    → process crash is indistinguishable from later interruption;
      explicit recovery required, no automatic replay

call partially/completely ran, terminal state not committed
    → STARTED survives; explicit recovery required, no automatic replay

RETURNED/RAISED committed
    → claim is CONSUMED and cannot be invoked again
```

A future coordinator may decide how to create a fresh claim after explicit interrupted recovery if the current canonical Task state still permits it. Phase 37 does not make that decision automatically.

---

## 37D — Recovery and read-side dispatch status

Reuse Phase-36 immutable execution inspection as the authority source and add only the minimum invocation-facing projection required to distinguish:

```text
READY_TO_INVOKE
STARTED_RECOVERY_REQUIRED
RETURNED
RAISED
INTERRUPTED
STALE_OR_INVALID
```

The read surface must remain non-creating and use the existing immutable SQLite guard.

It must not:

- repair STARTED execution automatically;
- call the owner;
- release/interrupt claims;
- acquire new claims;
- migrate/checkpoint the database;
- create WAL/SHM sidecars;
- infer Task outcome from execution status.

No mutating operator CLI is required in Phase 37. If a dispatch CLI is added later, it is a separate explicit mutation authority surface and must not be introduced implicitly through a read command.

---

## 37E — Cross-phase invocation acceptance

The final acceptance proof must exercise the complete trusted chain:

```text
QUEUED dependency-ready Task
→ READY activation
→ exact fresh Phase-32 route
→ exact audited Phase-33 WorkOrder
→ exact Phase-34 binding/audit
→ ACTIVE Phase-35 claim
→ exact Phase-36 dependency assembly
→ DISPEXEC STARTED
→ one reviewed owner call
→ RETURNED or RAISED
→ claim CONSUMED
```

Required adversarial cases:

- caller cannot supply or override any `drive()` argument except claim ID + expected revision;
- forged binding request type/schema/binder/adapter/contract relation is rejected before invocation;
- request projection hash drift is rejected before invocation;
- legacy release/interrupt after STARTED is blocked by both application and database boundary;
- two concurrent dispatcher calls for one claim result in at most one owner call;
- a second claim cannot be acquired during STARTED ownership;
- owner is not called if `begin_dispatch_execution()` fails;
- owner is called exactly once after successful begin;
- `PolicyOutcome.SUCCEEDED`, `BLOCKED`, `FAILED`, and `QUARANTINED` all terminalize `DISPEXEC` as RETURNED when the Python call returns normally;
- ordinary Python exception from the owner terminalizes RAISED and consumes the claim;
- terminalization failure after the call leaves durable STARTED/ACTIVE recovery state and never retries the call;
- simulated process restart with STARTED receipt never invokes automatically;
- explicit Phase-36 interrupted recovery remains the only v1 way to clear uncertain ownership;
- Task/Run/Workspace state produced by `BoundedRetryPolicy` is not rewritten by the dispatcher;
- dispatcher does not inspect `PolicyResult.outcome` to transition Task state;
- no generic adapter/model/tool invocation registry is introduced;
- no Artifact adoption/signing, merge, release, Dream promotion, training, or Project Intelligence mutation authority is introduced.

Normal CI may use the already-governed fake/test boundaries to prove coordinator call count and terminal state without downloading a heavyweight model. A real model/runtime evidence workflow, if later required, remains separately governed and cannot replace the normal exact-head Python 3.12/3.13 matrix.

---

## 37F — Canonical closure

After 37A–37E independently pass exact-head normal CI:

- finalize this contract with exact slice SHAs/run IDs;
- append Phase 37 DONE to the canonical roadmap without rewriting prior phases;
- freeze one documentation-only closure SHA;
- require normal Ubuntu Python 3.12 + 3.13 PASS on that exact SHA;
- revalidate reviews/threads and mergeability;
- perform SHA-guarded squash merge;
- verify actual `main` exactly against GitHub's returned merge commit.

---

## Explicit authority exclusions

Phase 37 does **not** add:

- automatic Task activation;
- automatic claim acquisition;
- background polling, worker daemon, dispatch queue, cron loop, or scheduler;
- dispatcher-level retry/replay after STARTED;
- generic model/tool/backend invocation;
- caller-selected model/profile/runtime/provider/endpoint/loader;
- caller-selected sandbox or Workspace manager;
- caller-selected execution owner/adapter/contract/binder;
- arbitrary shell/argv/environment/process authority;
- remote managed-model endpoints;
- new GPU runtime placement;
- Task/Flow/Goal transition logic outside the existing bounded execution owner;
- a second Run/Workspace/Task result truth model;
- semantic reinterpretation of `PolicyResult`;
- Artifact adoption/signing;
- Project Intelligence mutation;
- Dream promotion;
- model training/checkpoint activation;
- merge or release authority.

The only new production authority is one reviewed, synchronous, claim-bound call into the already-existing `BoundedRetryPolicy.drive()` owner after durable Phase-36 ownership has been established and sealed.

---

## Proposed implementation slices

```text
37A  schema-v10 STARTED-ownership seal + legacy claim lifecycle guard
37B  exact typed Phase-34 invocation-request decoder
37C  single-shot trusted owner invocation + RETURNED/RAISED terminalization
37D  immutable invocation/recovery status projection
37E  adversarial cross-phase exactly-once-at-dispatch-boundary acceptance
37F  documentation / roadmap closure
```

Every authority-expanding slice freezes one exact SHA and must pass the normal Ubuntu Python 3.12/3.13 matrix before the next slice begins.

---

## Exit condition

Phase 37 is complete when Origin Forge can take one exact current ACTIVE dispatch claim, durably seal its STARTED execution ownership against every legacy claim-release path, derive the exact reviewed `BoundedRetryPolicy.drive@1` request from immutable Phase-34 evidence, establish one Phase-36 STARTED receipt, invoke that trusted owner exactly once, atomically record RETURNED or RAISED plus claim consumption when a trustworthy call outcome is observed, preserve STARTED recovery state when it is not, and never automatically replay an uncertain invocation.

Only after this boundary is independently proven may a later phase add a Manager-side automatic dispatch loop, claim acquisition policy, or multi-Task scheduling.