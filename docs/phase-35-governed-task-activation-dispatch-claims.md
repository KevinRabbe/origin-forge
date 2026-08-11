# Phase 35 — Governed Task Activation & Dispatch Claims

Status: **PLANNED — architecture freeze before implementation**

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

Add one infrastructure-owned ID family:

```text
DISPCLAIM-*   DispatchClaim
```

No new activation ID is required. Task activation is a canonical Task state transition plus an explicit state event.

Add schema migration v8 with a canonical `dispatch_claims` table. The frozen v1 row contains only infrastructure-owned state/evidence metadata:

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

Implement this with a partial unique index on `task_id WHERE status = 'ACTIVE'` so concurrent processes cannot both acquire authority.

The claim contains no PID, hostname lease, timer/TTL, callable/import path, shell/argv, endpoint, credentials, model handle, process handle, Workspace handle, or arbitrary caller metadata.

---

## 35B — Atomic dependency-ready Task activation

Provide one explicit control-plane operation conceptually:

```text
activate_dependency_ready_task(task_id, expected_revision)
```

The caller may supply only the exact Task ID and expected revision. The caller cannot supply or override dependency-readiness evidence, target status, Task content hash, route, adapter, contract, or binding authority.

Inside one authoritative SQLite write transaction:

1. resolve project ownership;
2. read the exact Task row;
3. require `status == QUEUED`;
4. require exact `expected_revision`;
5. recompute dependency readiness using the existing connection-level Phase-31 readiness resolver on the same transaction snapshot;
6. require derived status exactly `READY`;
7. transition only `QUEUED → READY`;
8. increment Task revision exactly once;
9. append an explicit canonical state event recording infrastructure-owned activation evidence.

Failure is no-mutation. Waiting, failed, invalid, active, terminal, stale-revision, cross-project, or malformed Task states cannot be activated.

Phase 35 does not automatically block Tasks whose prerequisites failed and does not scan for ready Tasks. Activation is explicit and one-Task-at-a-time.

After successful activation, all pre-activation Phase-32/33/34 evidence is expected to become stale because the Task revision/content binding changed. Phase 35 must not rewrite those immutable objects or pretend they remain current.

---

## 35C — Exact dispatch-claim acquisition

Provide one explicit control-plane operation conceptually:

```text
acquire_dispatch_claim(
    dispatch_binding_id,
    binding_audit_id,
    expected_task_revision,
)
```

The caller does not choose the Task, adapter, dispatch contract, binder, WorkOrder, route, or evidence hashes. Those are derived from the exact trusted Phase-34 chain.

Before claim insertion:

1. load and strictly revalidate the exact persisted Phase-34 `INRES → DISPBIND → BINDAUD` chain;
2. require the audit to be an independently valid frozen `PASS` relation;
3. require current trusted resolver/binder/schema identities;
4. require Phase-34 live binding currentness exactly `CURRENT_READY`;
5. require the bound Task canonical status exactly `READY` in v1.

Then enter one authoritative SQLite write transaction and re-check the mutable production facts that can race:

1. project ownership;
2. Task ID, status `READY`, exact revision, and exact canonical Task content hash bound by the Phase-34 chain;
3. dependency readiness still exactly `READY` using the same transaction connection;
4. no current Task-state drift;
5. no existing ACTIVE dispatch claim for the Task.

Only then insert one `ACTIVE` `DISPCLAIM-*` row plus an explicit state event.

The database partial unique index is the final concurrency defense; a losing concurrent claimant fails closed and creates no second authority object.

Phase 35 v1 claims only canonical `READY` Tasks. `BLOCKED`/`FAILED` resume claims are deliberately deferred until the actual execution coordinator defines and proves resume semantics.

---

## 35D — Claim release and explicit interruption recovery

Provide bounded infrastructure lifecycle operations:

```text
release_dispatch_claim(claim_id, expected_revision)
interrupt_dispatch_claim(claim_id, expected_revision, reason)
```

Both require exact current `ACTIVE` identity/revision and are atomic compare-and-transition operations.

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

Add an immutable/read-only inspection facade over Phase-30 guarded SQLite reads. It may expose:

- activation eligibility for one Task;
- dispatch-claim status/detail;
- exact frozen claim-to-Phase34 relation;
- whether an ACTIVE claim still binds the same current Task revision and trusted Phase-34 chain;
- explicit stale/terminal/released/interrupted state.

Recommended claim currentness states:

```text
CURRENT_ACTIVE
STALE_TASK
STALE_BINDING
NOT_READY
RELEASED
INTERRUPTED
INVALID
```

Historical claim validity and current execution eligibility remain separate: a historically valid claim can become stale without being rewritten.

The Phase-35 CLI, if added, is inspection-only. Mutating activation/claim/release/interruption operations remain control-plane APIs until a separately reviewed operator command surface is justified.

---

## 35F — Cross-phase acceptance proof

The integration proof must demonstrate the exact authority ordering:

1. a dependency-ready `QUEUED` Task can be explicitly activated exactly once;
2. activation increments its revision and makes every pre-activation Phase-32/33/34 chain stale;
3. a new route/WorkOrder/audit/resolution/binding/audit built on the `READY` revision becomes current;
4. a claim over the stale pre-activation binding is rejected;
5. a claim over the fresh exact `CURRENT_READY` binding succeeds;
6. a concurrent second claim for the same Task fails at the durable uniqueness boundary;
7. the successful claim performs no Task transition beyond prior activation and invokes no adapter/backend;
8. release/interruption terminalizes only the claim;
9. restart preserves claim history and ACTIVE claims continue to block duplicate dispatch until explicit recovery.

---

## Required adversarial tests

At minimum:

- root/dependency-satisfied `QUEUED` Task activation succeeds exactly once;
- waiting/failed/invalid prerequisites cannot activate;
- stale expected revision fails before mutation;
- concurrent activation attempts produce one transition/event only;
- pre-activation route/WorkOrder/binding currentness becomes stale after activation;
- fresh Phase-32/33/34 evidence on the `READY` revision is current;
- claim rejects `QUEUED` even when derived dependency readiness is `READY`;
- claim rejects stale Task revision/content;
- claim rejects stale/forged WorkOrder, input resolution, binding, audit, resolver fingerprint, binder fingerprint, or request reconstruction;
- two concurrent claim attempts create exactly one ACTIVE claim;
- a second store/process instance cannot bypass the one-active-claim invariant;
- a different binding for the same Task cannot bypass an ACTIVE claim;
- release/interruption require exact active claim revision;
- terminal claims cannot be reactivated or rewritten;
- interrupted/released claims do not imply Task verification or completion;
- source-level authority tests prove Phase 35 contains no `drive()`, generic `execute()`, model `generate()`, subprocess, backend dispatch, resource lease, Artifact adoption/signing, merge, release, or self-training invocation surface.

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

Only after this exit condition is proven should a later phase introduce the first governed single-shot production dispatcher that consumes an ACTIVE claim and invokes a trusted code-owned execution owner.