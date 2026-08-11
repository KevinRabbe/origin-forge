# Phase 35 — Governed Task Activation & Dispatch Claims

Status: **IMPLEMENTED — execution intentionally remains out of scope**

Phase 35 closes the final durable-state prerequisites before any Phase-34 dispatch binding may be executed. It owns exactly two new authority operations:

1. promote one dependency-ready canonical Task from `QUEUED` to `READY`; and
2. acquire one durable exclusive dispatch claim over one exact current Phase-34 binding chain.

Phase 35 still stops before `BoundedRetryPolicy.drive()`, adapter/backend invocation, model/process/tool execution, resource leasing, or production-result interpretation.

---

## Why Phase 35 is required

Phase 31 dependency readiness is intentionally read-only. A canonical `QUEUED` Task with all prerequisites satisfied is reported as dependency `READY` without mutating the Task.

Phase 32 routing, Phase 33 WorkOrders, and Phase 34 bindings all bind the exact Task revision/content. The existing bounded-code executor, however, requires canonical execution state such as `READY`; it cannot start a fresh attempt from `QUEUED`.

Therefore this sequence is invalid:

```text
QUEUED Task rev N
→ CAPROUTE / WORKORD / INRES / DISPBIND built at rev N
→ transition QUEUED → READY rev N+1
→ execute old binding                  # stale authority: forbidden
```

The required sequence is:

```text
QUEUED Task rev N
+ dependency readiness = READY
        ↓
explicit atomic activation
QUEUED → READY rev N+1
        ↓
STOP / rebuild exact authority chain
CAPROUTE → WORKORD/WORKAUD → INRES/DISPBIND/BINDAUD
        ↓
Phase-34 binding currentness = CURRENT_READY
        ↓
explicit atomic dispatch claim
DISPCLAIM-* = ACTIVE
        ↓
STOP — no executor/backend call in Phase 35
```

A second missing prerequisite is dispatch ownership. Existing Run and Workspace invariants prevent many downstream conflicts, but they do not provide an exclusive coordinator-level claim over the exact audited Phase-34 binding. A durable claim is required before a later coordinator is allowed to invoke an execution owner.

---

## 35A — Identity and durable claim model

Phase 35 adds one infrastructure-owned ID family:

```text
DISPCLAIM-*   DispatchClaim
```

No new activation ID is required. Task activation is a canonical Task state transition plus an explicit state event.

Schema migration v8 adds a canonical `dispatch_claims` table. The frozen v1 row contains only infrastructure-owned state/evidence metadata:

```text
claim_id
project_id
task_id
task_revision
task_content_hash
work_order_id
work_order_hash
work_order_audit_id
work_order_audit_hash
input_resolution_id
input_resolution_hash
dispatch_binding_id
dispatch_binding_hash
binding_audit_id
binding_audit_hash
selected_adapter_id
selected_adapter_fingerprint
dispatch_contract_id
dispatch_contract_hash
binder_id
binder_fingerprint
status
revision
created_at
updated_at
terminal_reason
```

Accepted v1 status transitions:

```text
ACTIVE → RELEASED
ACTIVE → INTERRUPTED
```

`RELEASED` and `INTERRUPTED` are terminal claim states. They do not change Task status and do not imply execution success/failure.

Hard database invariant:

```text
at most one ACTIVE dispatch claim per Task
```

A partial unique index on `task_id WHERE status = 'ACTIVE'` enforces this below the service layer so concurrent processes cannot both acquire authority.

The claim contains no PID, hostname lease, timer/TTL, callable/import path, shell/argv, endpoint, credentials, model handle, process handle, Workspace handle, or arbitrary caller metadata.

---

## 35B — Atomic dependency-ready Task activation

The implemented control-plane operation is:

```text
activate_dependency_ready_task(runtime, task_id, expected_revision)
```

The caller may supply only the exact Task ID and expected revision. The caller cannot supply or override dependency-readiness evidence, target status, Task content hash, route, adapter, contract, or binding authority.

Inside one authoritative SQLite write transaction it:

1. resolves project ownership;
2. reads the exact Task row;
3. requires `status == QUEUED`;
4. requires exact `expected_revision`;
5. recomputes dependency readiness using the existing connection-level Phase-31 readiness resolver on the same transaction snapshot;
6. requires derived status exactly `READY`;
7. transitions only `QUEUED → READY`;
8. increments Task revision exactly once;
9. appends an explicit canonical state event recording infrastructure-owned activation evidence.

Failure is no-mutation. Waiting, failed, invalid, active, terminal, stale-revision, cross-project, or malformed Task states cannot be activated.

Phase 35 does not automatically block Tasks whose prerequisites failed and does not scan for ready Tasks. Activation is explicit and one-Task-at-a-time.

After successful activation, all pre-activation Phase-32/33/34 evidence becomes stale because the Task revision/content binding changed. Phase 35 does not rewrite those immutable objects or pretend they remain current.

---

## 35C — Exact dispatch-claim acquisition

The implemented control-plane operation is:

```text
acquire_dispatch_claim(
    runtime,
    dispatch_binding_id,
    binding_audit_id,
    expected_task_revision,
)
```

The caller does not choose the Task, adapter, dispatch contract, binder, WorkOrder, route, or evidence hashes. Those are derived from the exact trusted Phase-34 chain.

Before claim insertion:

1. load and strictly revalidate the exact persisted Phase-34 `INRES → DISPBIND → BINDAUD` chain;
2. require the audit to be an independently valid frozen relation;
3. require current trusted resolver/binder/schema identities;
4. require Phase-34 live binding currentness exactly `CURRENT_READY`;
5. require the bound Task canonical status exactly `READY` in v1.

Then one authoritative SQLite write transaction re-checks mutable production facts that can race:

1. project ownership;
2. Task ID, status `READY`, exact revision, and exact canonical Task content hash bound by the Phase-34 chain;
3. dependency readiness still exactly `READY` using the same transaction connection;
4. no current Task-state drift;
5. no existing ACTIVE dispatch claim for the Task.

Only then is one `ACTIVE` `DISPCLAIM-*` row plus an explicit state event inserted.

The database partial unique index is the final concurrency defense; a losing concurrent claimant fails closed and creates no second authority object.

Phase 35 v1 claims only canonical `READY` Tasks. `BLOCKED`/`FAILED` resume claims remain deferred until the actual execution coordinator defines and proves resume semantics.

---

## 35D — Claim release and explicit interruption recovery

Implemented bounded infrastructure lifecycle operations:

```text
release_dispatch_claim(runtime, claim_id, expected_revision)
interrupt_dispatch_claim(runtime, claim_id, expected_revision, reason)
```

Both require exact current `ACTIVE` identity/revision and are atomic compare-and-transition operations. Lifecycle transitions re-read the canonical claim and verify that every frozen Phase-34 authority field is byte-for-byte unchanged after terminalization; only status, revision, update time, and terminal reason may change.

`release` is for an unused/abandoned claim before execution authority is consumed. `interrupt` is explicit recovery evidence after the owning process/operation is known to have been lost or abandoned.

Crash semantics are deliberately fail-closed:

- an `ACTIVE` claim survives process restart;
- it continues blocking all other claims for that Task;
- there is no automatic TTL expiry;
- there is no PID/hostname liveness guess;
- there is no second-process claim stealing;
- recovery requires an explicit expected-revision interruption operation.

Neither terminal claim state changes Task success/failure/readiness. Actual execution outcome ownership remains a later phase.

---

## 35E — Currentness and read-only inspection

Implemented an independent immutable/read-only inspection facade over the Phase-30 guarded SQLite connection. It does not call `runtime.project_id()` or `runtime.store.session()` and therefore does not enter the normal migrating/writer-capable path.

The accepted read API provides:

- exact immutable `DISPCLAIM-*` reads;
- activation eligibility for one Task;
- exact frozen claim-to-Phase34 relation revalidation;
- ACTIVE claim currentness against exact current Task revision/hash/dependency readiness and trusted Phase-34 binding currentness.

Claim currentness states are:

```text
CURRENT_ACTIVE
STALE_TASK
STALE_BINDING
NOT_READY
RELEASED
INTERRUPTED
INVALID
```

Historical claim validity and current execution eligibility remain separate: a historically valid claim can become stale without being rewritten. The reader proves non-creation/no-sidecar behavior under the existing immutable SQLite contract.

No Phase-35 CLI was added. Mutating activation/claim/release/interruption operations remain control-plane APIs until a separately reviewed operator command surface is justified.

---

## 35F — Cross-phase acceptance proof

The accepted integration proof demonstrates the exact authority ordering:

1. a dependency-ready `QUEUED` Task can have a complete pre-activation Phase-32/33/34 chain;
2. explicit activation increments its revision and makes that pre-activation chain non-current;
3. a claim over the stale pre-activation binding is rejected;
4. a new route/WorkOrder/audit/resolution/binding/audit built on the `READY` revision becomes `CURRENT_READY`;
5. concurrent claims over the fresh exact binding yield exactly one durable ACTIVE owner;
6. the successful claim creates no Run or Workspace and performs no Task transition beyond prior activation;
7. restart preserves the ACTIVE claim and duplicate claim acquisition remains blocked;
8. explicit interruption terminalizes only the claim and allows a later fresh claim;
9. explicit release terminalizes only that replacement claim;
10. source-level authority tests prove the entire Phase-35 production surface stops before any execution owner/backend invocation.

---

## Required adversarial tests

The implemented suite covers:

- root/dependency-satisfied `QUEUED` Task activation succeeds exactly once;
- waiting/failed/invalid prerequisites cannot activate;
- stale expected revision fails before mutation;
- concurrent activation attempts produce one transition/event only;
- pre-activation route/WorkOrder/binding currentness becomes stale after activation;
- fresh Phase-32/33/34 evidence on the `READY` revision is current;
- claim rejects `QUEUED` even when derived dependency readiness is `READY`;
- claim rejects stale Task revision/content;
- claim rejects stale/forged Phase-34 evidence/currentness;
- two concurrent claim attempts create exactly one ACTIVE claim;
- a second store/process instance cannot bypass the one-active-claim invariant;
- release/interruption require exact active claim revision;
- terminal claims cannot be reactivated or rewritten;
- interrupted/released claims do not imply Task verification or completion;
- immutable claim reads create no SQLite WAL/SHM/journal state and do not modify database/config bytes;
- uninitialized reads create no Origin Forge state;
- source-level authority tests prove Phase 35 contains no `BoundedRetryPolicy.drive()`, model generation, subprocess/backend dispatch, resource lease, Workspace execution, Artifact adoption/signing, merge, release, or self-training invocation surface.

---

## CI evidence

Each authority-expanding slice was frozen and independently gated on the normal Ubuntu Python 3.12/3.13 matrix before the next slice:

- **35A — identity/schema/model:** `07a658ae4e927b5febdf0bff4bd363565571a6c2`, run `31520783221` — PASS 3.12/3.13.
- **35B — atomic Task activation:** `decf42316ed74c6bc1d908e75f00f7e2328cddd7`, run `31521204677` — PASS 3.12/3.13.
- **35C — exclusive claim acquisition:** `6fda6cdeeffcea8386e6ac83dc190a9a04d2f8bf`, run `31521692074` — PASS 3.12/3.13.
- **35D — release/interruption lifecycle:** `84986d6c40fac37202bf520413cfd508804da78e`, run `31524027837` — PASS 3.12/3.13.
- **35E — immutable read/currentness:** `b1a8402bfbe90ded77e9e50cb09f50289573bc35`, run `31524950193` — PASS 3.12/3.13.
- **35F — cross-phase acceptance proof:** `58eeb69ea55759c521268f65a7b46d60fd56fcfd`, run `31525230603` — PASS 3.12/3.13.

The final 35G documentation/roadmap closure head is intentionally created only after all implementation proofs and must itself pass the full normal Python 3.12/3.13 matrix before ready-for-review transition and SHA-guarded merge.

---

## Explicit authority exclusions

Phase 35 does **not** add:

- `BoundedRetryPolicy.drive()` invocation;
- any production adapter/backend invocation;
- model loading/generation or resource leasing;
- Workspace creation/mutation;
- sandbox execution;
- Artifact creation/adoption/signing;
- Task success/failure/quarantine authority;
- Flow/Goal transition authority;
- automatic dependency scheduling or background queues;
- recursive planning/replanning;
- generic tool/plugin/shell/argv/import/callable/network authority;
- merge/release/self-training authority.

The only new Task mutation is the exact positive activation transition `QUEUED → READY` after same-transaction dependency-readiness recomputation.

---

## Exit condition

Phase 35 is complete when Origin Forge can explicitly and atomically activate one dependency-ready `QUEUED` Task, force the downstream Phase-32/33/34 authority chain to be rebuilt on the new `READY` revision, and atomically acquire at most one durable exact dispatch claim over that current binding while remaining fail-closed across concurrency/restart and still stopping before execution.

That implementation condition is met through exact green 35F head `58eeb69ea55759c521268f65a7b46d60fd56fcfd`. The final documentation/roadmap closure head must still pass the normal exact-head matrix and the standard review/merge gate.

Only after Phase 35 is merged should a later phase introduce the first governed single-shot production dispatcher that consumes an ACTIVE claim and invokes a trusted code-owned execution owner.