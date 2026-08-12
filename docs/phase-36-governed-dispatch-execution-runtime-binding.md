# Phase 36 — Governed Dispatch Execution Ownership & Runtime Binding

Status: **DONE — implementation complete; final documentation-head CI pending**

Phase 36 closes the last execution-side authority gap between an exact Phase-35 `ACTIVE` dispatch claim and the first future production call into the bounded-code executor.

It adds durable one-shot execution ownership, a trusted execution-owner registry, protected managed-runtime configuration, a code-owned local CPU llama.cpp loader, lazy dependency reconstruction, atomic execution/claim lifecycle primitives, and immutable currentness inspection.

Phase 36 deliberately **stops before production invocation**. No Phase-36 production path calls `BoundedRetryPolicy.drive()`, `ModelAdapter.generate()`, a production backend, or a model runtime as part of dispatch ownership establishment.

---

## Accepted authority chain

```text
READY Task
    ↓
exact current Phase-32 route
    ↓
exact audited Phase-33 WorkOrder
    ↓
exact Phase-34 input resolution / binding / audit
    ↓
Phase-35 ACTIVE DISPCLAIM
    ↓
trusted execution-owner descriptor
    ↓
protected Phase-14 model policy + Phase-36 runtime provider bindings
    ↓
lazy bounded-code dependency assembly
    ↓
one durable DISPEXEC STARTED receipt
    ↓
STOP

NO BoundedRetryPolicy.drive()
NO production Task execution
```

The existing `BoundedRetryPolicy` remains the downstream authority for Task/Run/Workspace/retry/audit/sandbox execution semantics. `DISPEXEC-*` is only invocation-ownership evidence and never becomes a second Task or Run truth model.

---

## 36A — One-shot execution identity and schema — DONE

Implemented:

- infrastructure-owned `DISPEXEC-*` identity;
- `DispatchExecution` frozen authority records;
- execution lifecycle `STARTED → RETURNED | RAISED | INTERRUPTED`;
- Phase-35 claim extension `ACTIVE → CONSUMED`;
- schema migration v9 preserving all v8 dispatch-claim columns/rows while widening only the claim terminal-status constraint;
- `dispatch_executions` with exact claim/task/Phase-34/owner/dependency-plan bindings;
- database uniqueness for one execution per claim;
- database defense allowing at most one `STARTED` execution per Task;
- adversarial migration/model/database coverage.

`CONSUMED` means execution authority was used exactly once. It does not mean the Task succeeded.

Accepted 36A head:

```text
8977103dcb18276d9dfab41ff900c0c60be780dc
```

Normal matrix: GitHub Actions run `31528424230`, Python 3.12 PASS and Python 3.13 PASS.

---

## 36B — Trusted execution-owner registry — DONE

Implemented one inert code-owned execution-owner descriptor for the reviewed bounded-code path:

```text
owner_id:             originforge.execution.bounded-retry@1
adapter_id:           originforge.code.bounded-retry
dispatch_contract_id: code.bounded-retry@1
binder_id:            binder.code.bounded-retry@1
request_type_id:      BoundedRetryPolicy.drive@1
```

The descriptor contains no callable, module/import path, shell, argv, endpoint, credential, executable handle, plugin metadata, or dynamically supplied backend authority.

The initial execution strategy is deliberately narrow:

```text
CODER_STRONG
```

Phase 36 does not infer `CODER_FAST → CODER_STRONG` merely because multiple profiles might exist. Phase-14 profile fallback remains separately governed by the explicit `ModelSelectionPolicy` for the declared semantic role.

Accepted 36B head:

```text
4de123faa0b036cff7740be376aab1983f6ba3a8
```

Normal matrix: GitHub Actions run `31528805134`, Python 3.12 PASS and Python 3.13 PASS.

---

## 36C — Protected managed-runtime configuration — DONE

Protected project configuration advances to v6 with a separate safe-disabled runtime-provider section:

```toml
[model_runtimes]
providers = []
```

Existing Phase-14 `[resources]` / `[models]` profile semantics remain unchanged. Prior v1–v5 configurations remain readable; non-empty managed runtime bindings require v6.

The initial closed provider kind is:

```text
originforge.llamacpp-managed-cpu@1
```

A provider binds exact:

- `runtime_id`;
- provider kind and contract version;
- local executable path and lowercase SHA-256;
- fixed protected port;
- bounded startup/request/shutdown timeouts;
- profile ID → local model path / lowercase SHA-256 relation.

Validation rejects unknown fields/provider kinds, remote-style paths, malformed/non-finite values, model/profile/runtime/hash mismatch, and GPU-bearing profiles for the CPU-only provider. The parser performs no filesystem access, process start, network request, dynamic import, loader construction, model generation, or lease operation.

The first 36C candidate `6a0c20a344b3d1a428265c29cc7ba32366b87e70` was **rejected**: normal run `31529766913` failed on both interpreters because two pre-existing tests still hard-coded the old default config version `5` after the intentional v6 default bump. The correction changed only those two stale assertions; no production byte changed after the rejected candidate.

Accepted 36C head:

```text
4e4a5fcad8194537ab5df66e71d7c5687aaa9155
```

Normal matrix: GitHub Actions run `31595604003`, Python 3.12 job `94110293998` PASS and Python 3.13 job `94110294042` PASS.

---

## 36D — Managed local CPU llama.cpp loader — DONE

Implemented `ManagedLlamaCppCpuLoader` as the code-owned `ManagedModelLoader` for `originforge.llamacpp-managed-cpu@1`.

Before process start it proves:

- exact provider kind/version and profile/runtime relation;
- exact protected profile binding;
- exact lowercase model SHA-256 matching both profile and bound model file;
- executable and model are existing regular non-symlink files outside protected `.origin-forge` state;
- executable/model bytes match protected SHA-256 values;
- CPU/RAM lease exactly matches the selected profile request;
- no GPU request or lease is present;
- configured fixed loopback port is available.

The process surface is infrastructure-owned:

- no shell;
- no caller/model argv;
- no caller environment map;
- loopback `127.0.0.1` only;
- fixed configured port with collision failure and no random/remote fallback;
- explicit CPU-only llama.cpp arguments;
- minimal locale environment;
- bounded stdout/stderr capture;
- bounded `/health` readiness polling;
- cleanup on startup failure, timeout, and unload;
- POSIX process-group descendant cleanup where the host contract supports it;
- no download, internet lookup, secret discovery, daemonization, or hidden persistence.

The loaded object is the existing bounded `LlamaCppAdapter` configured only from trusted provider/profile state. `unload()` accepts only the exact active adapter instance owned by that loader and rejects unknown/reused instances.

Normal CI uses a controlled fake llama-server executable, so no heavyweight model is required for the standard gate.

Accepted 36D head:

```text
16131a847f768d2c2eafbd2ab7196babce3da28a
```

Normal matrix: GitHub Actions run `31597526290`; Python 3.12 job `94116594991` PASS and Python 3.13 job `94116594821` PASS.

---

## 36E — Lazy execution dependency assembly — DONE

Implemented one code-owned assembler that accepts only:

```text
OriginForgeRuntime + exact DISPCLAIM ID
```

It derives everything else from current persisted authority, code-owned registries, and protected configuration:

- exact current Phase-35 claim;
- exact Phase-34 binding/request identity;
- trusted execution owner;
- protected config v6;
- explicit Phase-14 model-role policy;
- all profiles reachable through that explicit policy;
- trusted runtime-provider bindings for every reachable profile;
- model scheduler and lazy scheduled adapters;
- runtime-loader registry/dispatcher;
- protected sandbox backend;
- canonical `GitWorkspaceManager`;
- constructed but uninvoked `BoundedRetryPolicy`;
- deterministic dependency-plan hash over the complete non-secret authority surface.

The dependency-plan identity includes Phase-14 scheduling semantics, not merely selected profile names. Changing resource/model policy state changes the plan hash.

Assembly creates no model/resource lease, llama.cpp process, Run, Workspace, Task transition, Artifact, Verification, claim terminalization, or executor call.

Accepted 36E head:

```text
4b636adea33a4132171520d15f1ff15e65c544ef
```

Normal matrix: GitHub Actions run `31599083299`; Python 3.12 job `94121763572` PASS and Python 3.13 job `94121763386` PASS.

---

## 36F — Execution ownership transactions — DONE

Implemented internal execution lifecycle primitives around exact expected revisions.

`begin_dispatch_execution(runtime, claim_id, expected_revision)`:

1. assembles the trusted dependency graph without invoking it;
2. enters `BEGIN IMMEDIATE`;
3. rechecks exact claim project/status/revision/frozen authority;
4. rechecks exact Task revision/content/status/dependency readiness;
5. rejects prior execution for the claim or competing `STARTED` execution for the Task;
6. inserts one `DISPEXEC STARTED` record + state event;
7. proves the originating claim is byte-for-byte/lifecycle unchanged and remains `ACTIVE`;
8. returns the frozen receipt plus lazy dependencies.

Terminalization requires exact execution and claim revisions and updates both in one transaction:

```text
STARTED → RETURNED     + claim ACTIVE → CONSUMED
STARTED → RAISED       + claim ACTIVE → CONSUMED
STARTED → INTERRUPTED  + claim ACTIVE → INTERRUPTED
```

Every frozen execution/claim authority field is preserved. Terminal detail is represented by bounded content-hash evidence rather than becoming Task-outcome truth.

Accepted initial 36F transaction head:

```text
b987a5481820a4e7cae6096f5515d9dacbca29af
```

Normal matrix: GitHub Actions run `31599943350`; Python 3.12 job `94124605158` PASS and Python 3.13 job `94124605054` PASS.

The later cross-phase invariant review superseded some already-green ownership/currentness semantics; the final accepted integrated semantics are recorded below.

---

## 36G — Immutable execution inspection/currentness — DONE

Implemented non-creating inspection through the existing immutable SQLite boundary for:

- exact `DISPEXEC-*` records;
- claim/execution frozen relation validation;
- `CURRENT_STARTED` ownership;
- returned/raised/interrupted historical terminal state;
- restart recovery detection;
- consumed/interrupted claim history;
- current-vs-stale execution authority without creating migrations, WAL/SHM sidecars, leases, processes, Runs, or Workspaces.

Accepted initial 36G reader head:

```text
e3b24a5346aa3d275c5ce2d842f4e02d2082426e
```

Normal matrix: GitHub Actions run `31600511052`; Python 3.12 job `94126511618` PASS and Python 3.13 job `94126511645` PASS.

---

## Cross-phase acceptance and semantic repair

The first full Phase-36 cross-phase acceptance head was:

```text
8e537868568ed055ac344d631255ac3acecd4c1d
```

Normal matrix run `31600818873` passed on Python 3.12 job `94127475782` and Python 3.13 job `94127475867`.

A subsequent invariant review identified that STARTED execution ownership and claim *eligibility for starting a new execution* must not be conflated. The architecture requires the original claim to remain `ACTIVE` for the entire STARTED invocation window so the durable Phase-35 uniqueness constraint continues to exclude a second dispatch owner.

The repair sequence therefore tightened the implementation and tests so that:

- begin creates `DISPEXEC STARTED` while leaving the exact claim `ACTIVE` and at its original revision;
- a STARTED execution can be `CURRENT_STARTED` while its claim is no longer eligible to start another execution because a receipt already exists;
- a second claim for the Task remains blocked by the original ACTIVE claim;
- terminalization alone releases the STARTED ownership window by atomically consuming/interruption-terminalizing the claim;
- reader/currentness and cross-phase tests use this same distinction.

Final integrated code/test head:

```text
59d40bbd37b8228faa58d4711b2a4c699ecdfd1c
```

Final integrated normal matrix: GitHub Actions run `31601843122`:

- Python 3.12 job `94131030717`: PASS
- Python 3.13 job `94131030600`: PASS

Heavy editor/media evidence workflows were skipped/disarmed and are not part of the Phase-36 standard gate.

---

## Final acceptance proof

The integrated acceptance test establishes:

```text
QUEUED dependency-ready Task
→ explicit READY activation
→ exact Phase-32 route
→ exact Phase-33 WorkOrder + audit
→ exact Phase-34 input resolution + binding + audit
→ exact Phase-35 ACTIVE claim
→ trusted execution-owner selection
→ protected config/runtime dependency plan
→ lazy dependency assembly
→ one DISPEXEC STARTED receipt
→ immutable CURRENT_STARTED inspection
→ explicit interrupted recovery
→ STOP
```

During `begin_dispatch_execution()` the acceptance test installs fail-fast guards against:

- `ManagedLlamaCppCpuLoader.load()`;
- `ResourceScheduler.acquire()`;
- `GitWorkspaceManager.create()`;
- `OriginForgeRuntime.start_run()`;
- `BoundedRetryPolicy.drive()`;
- `subprocess.Popen()`.

The test passes only if none is called. It also proves Task state, Run count, Workspace count, resource leases, runtime instances, and missing configured runtime/model files remain unchanged.

Source-level acceptance separately requires the Phase-36 owner/config/loader/assembly/execution/read modules to contain no `.drive(` call; the execution coordinator contains no `.generate(` call.

---

## Authority exclusions retained

Phase 36 does **not** add:

- production `BoundedRetryPolicy.drive()` invocation;
- production Task execution/completion/failure/quarantine authority;
- model-selected runtime/provider/profile/endpoint authority;
- background dispatch workers or queues;
- implicit model-role downgrade/escalation;
- remote managed-model endpoints;
- managed GPU runtime placement;
- caller/model shell, argv, environment, import, callable, executable/model path, credential, or generic process authority;
- automatic runtime/model download;
- a replacement Run/Workspace truth model;
- Artifact adoption/signing;
- Project Intelligence mutation;
- merge, release, or self-training authority.

`RETURNED` and `RAISED` remain invocation-mechanics states only. They may be written by a future trusted coordinator only after the corresponding real invocation boundary has occurred.

---

## Exit condition — MET

Origin Forge can now take one exact current Phase-35 ACTIVE claim, deterministically select the reviewed bounded-code execution owner, reconstruct every non-secret execution dependency from protected configuration and code-owned registries, bind all reachable model profiles to trusted managed runtimes, construct the lazy model/sandbox/workspace/executor graph without caller authority, atomically establish one durable one-shot `DISPEXEC STARTED` ownership receipt, preserve the ACTIVE claim throughout the ownership window, inspect/recover/terminalize that ownership safely, and still stop before `BoundedRetryPolicy.drive()`.

The implementation head `59d40bbd37b8228faa58d4711b2a4c699ecdfd1c` is green on the normal Python 3.12/3.13 matrix. This documentation commit changes the exact PR head, so it is **not** the final merge gate by itself; the final immutable documentation/roadmap closure SHA must pass the normal matrix before ready-for-review and SHA-guarded merge.

Only after Phase 36 is merged may Phase 37 introduce the first governed single-shot production dispatcher.