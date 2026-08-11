# Phase 36 — Governed Dispatch Execution Ownership & Runtime Binding

Status: **PLANNED — architecture only; no production executor invocation**

Phase 36 prepares the last execution-side infrastructure required after Phase 35 and before the first production dispatcher may call a trusted execution owner.

It exists because Phase 35 now proves that Origin Forge can activate one exact dependency-ready Task, rebuild Phase-32/33/34 authority on the new `READY` revision, and acquire exactly one durable `ACTIVE` dispatch claim — but the repository still lacks two independent contracts required for safe invocation:

1. a durable one-shot execution receipt/claim-consumption protocol; and
2. a protected, code-owned way to construct the bounded-code executor's runtime/model dependencies without caller-supplied endpoints, loaders, model objects, shell commands, or arbitrary process authority.

Phase 36 may add tightly bounded infrastructure-owned model-runtime process management because that is itself a missing dependency authority. It still stops before `BoundedRetryPolicy.drive()` and before any production Task is executed.

---

## Current verified gap

At Phase-35 merged `main`, the following pieces already exist:

```text
Phase 31   dependency readiness
Phase 32   exact capability route
Phase 33   exact WorkOrder + audit
Phase 34   exact input resolution + typed binding + audit/currentness
Phase 35   exact QUEUED→READY activation + exclusive ACTIVE claim
```

The bounded-code execution owner already exists:

```text
BoundedRetryPolicy(
    runtime,
    models: Sequence[ModelAdapter],
    sandbox_backend,
    workspaces,
).drive(...)
```

`BoundedRetryPolicy` owns the downstream Task/Run/Workspace/retry/audit/sandbox lifecycle. A later dispatcher must not duplicate that truth model.

The missing dependency construction is concrete:

- Phase-14 `create_model_scheduling()` constructs resource/model scheduling state but deliberately does not load a model.
- `ModelScheduler.use()` requires a caller-supplied `ManagedModelLoader`.
- `ModelRuntimeRegistry` stores caller-supplied loader objects; it does not construct trusted production loaders.
- `ScheduledModelAdapter` requires a supplied loader.
- current production llama.cpp adapters are bounded HTTP clients whose endpoint/model/API settings are supplied to their constructors; they do not own the llama.cpp process/model lifecycle.
- the Phase-14 model/resource CLI explicitly performs inspection without loading a model.
- Phase-14 scheduler-factory tests prove lease construction and release, not production runtime loading.
- Phase-21 llama.cpp vision is also a governed HTTP adapter, not a managed llama.cpp process loader.
- the sandbox dependency is already safely constructible from protected configuration through `create_sandbox_backend()`.

Therefore a dispatcher created immediately after Phase 35 would have to receive model/runtime authority from its caller. That is forbidden.

---

## Core Phase-36 boundary

The intended architecture is:

```text
Phase-35 ACTIVE DISPCLAIM
        ↓
exact claim currentness = CURRENT_ACTIVE
        ↓
trusted execution-owner descriptor
        ↓
protected model/runtime dependency plan
        ↓
code-owned runtime-provider registry
        ↓
construct bounded execution dependencies
        ↓
create durable DISPEXEC STARTED ownership receipt
        ↓
STOP

NO BoundedRetryPolicy.drive()
NO production Task execution
```

Phase 36 proves that all execution authority can be reconstructed from protected infrastructure state and exact existing evidence before Phase 37 is allowed to perform the first call.

---

## 36A — One-shot dispatch execution identity and claim-consumption semantics

Add one infrastructure-owned identity family:

```text
DISPEXEC-*   DispatchExecution
```

A `DispatchExecution` is an invocation-ownership receipt, not a second Run or Task truth model.

Frozen authority fields bind at minimum:

```text
execution_id
project_id
claim_id
claim_revision_at_start
task_id
task_revision
task_content_hash
work_order_id/work_order_hash
input_resolution_id/input_resolution_hash
dispatch_binding_id/dispatch_binding_hash
binding_audit_id/binding_audit_hash
selected_adapter_id/selected_adapter_fingerprint
dispatch_contract_id/dispatch_contract_hash
binder_id/binder_fingerprint
execution_owner_id/execution_owner_fingerprint
runtime_dependency_plan_hash
status
revision
created_at
updated_at
terminal_detail_hash/null
```

Initial execution lifecycle:

```text
STARTED → RETURNED
STARTED → RAISED
STARTED → INTERRUPTED
```

These states describe invocation mechanics only:

- `RETURNED`: the trusted execution owner returned normally.
- `RAISED`: the trusted execution owner was actually called and raised/failed at the invocation boundary.
- `INTERRUPTED`: ownership was lost or abandoned before a trustworthy terminal return/raise could be recorded.

They do **not** reinterpret the Task outcome. The existing Task/Run/Workspace state produced by `BoundedRetryPolicy` remains authoritative.

Phase 36 extends the Phase-35 claim lifecycle with one terminal state:

```text
ACTIVE → CONSUMED
```

`CONSUMED` means only that execution authority was used exactly once. It does not mean success.

Critical ordering:

- while `DISPEXEC` is `STARTED`, its originating claim remains `ACTIVE`;
- therefore Phase-35 one-ACTIVE-claim-per-Task continues blocking a second owner during the invocation window;
- one immutable uniqueness relation permits at most one `DISPEXEC-*` for a claim;
- a normal `RETURNED` or `RAISED` terminalization atomically terminalizes the execution record and changes the exact claim `ACTIVE → CONSUMED`;
- explicit interrupted recovery atomically changes `DISPEXEC STARTED → INTERRUPTED` and the exact claim `ACTIVE → INTERRUPTED`.

This avoids the unsafe gap that would exist if a claim were freed before the executor call completed.

No Phase-36 API may mark a claim `RELEASED` after execution authority has been consumed. Phase-35 `RELEASED` retains its original meaning: unused/abandoned before invocation.

---

## 36B — Trusted execution-owner catalog

Introduce an infrastructure-owned, code-defined execution-owner registry. Persistent/model-visible descriptors are inert and content-addressed; they contain no callable, module path, import string, shell, argv, endpoint, credential, executable handle, or dynamically supplied plugin metadata.

The initial reviewed execution owner is exactly:

```text
owner_id: originforge.execution.bounded-retry@1
adapter_id: originforge.code.bounded-retry
dispatch_contract_id: code.bounded-retry@1
binder_id: binder.code.bounded-retry@1
request_type_id: BoundedRetryPolicy.drive@1
```

The descriptor additionally freezes its dependency classes:

```text
runtime: canonical OriginForgeRuntime
sandbox: protected configured SandboxBackend
workspace_manager: canonical GitWorkspaceManager
model_strategy_roles: explicit ordered ModelRole sequence
model_runtime_policy: protected Phase-36 runtime-provider binding
```

The model strategy sequence is explicit because two existing policies must not be conflated:

- `BoundedRetryPolicy` uses a sequence of model adapters for strategy escalation across attempts.
- Phase-14 `ModelSelectionPolicy` chooses an explicitly allowed primary/fallback profile within one semantic `ModelRole` under resource admission.

Phase 36 must never infer the bounded-retry escalation sequence from whichever profiles happen to exist. The execution-owner descriptor owns the allowed role sequence, initially a deliberately narrow code-owned sequence such as:

```text
CODER_FAST → CODER_STRONG
```

or an even narrower single-role sequence if the repository/config cannot prove both roles are present. Missing required policies fail closed; there is no implicit role downgrade or profile fallback beyond explicit Phase-14 policy.

---

## 36C — Protected model-runtime provider configuration

Advance protected project configuration only as much as required to bind a model profile's inert `runtime_id` to a code-owned runtime provider.

The configuration must remain declarative. It may identify exact local runtime/model files and bounded runtime settings, but it may not contain arbitrary command arrays, shell fragments, import paths, Python callables, plugin names, environment maps, or unrestricted network endpoints.

The initial runtime-provider configuration must bind:

```text
runtime_id
provider_kind
provider_contract_version
executable_path
executable_sha256
profile_id → model_path/model_sha256 relation
loopback-only serving policy
bounded startup timeout
bounded request timeout
bounded shutdown timeout
```

The provider kind is a closed code-owned enum/registry. Unknown provider kinds fail closed.

The initial accepted provider is intentionally narrow:

```text
originforge.llamacpp-managed-cpu@1
```

It is local-only and CPU-only in v1. GPU device binding is deferred until a separately proven provider can map Phase-14 GPU leases to exact llama.cpp runtime placement without relying on ambiguous backend-specific behavior.

CPU-only v1 keeps the resource-ownership statement truthful: the provider may start the model runtime only while holding the exact Phase-14 CPU/RAM lease assigned to the selected profile. A profile requesting GPU resources is rejected by this provider rather than silently ignoring the lease.

Backward compatibility requirements:

- prior protected config versions remain readable/migratable according to existing project rules;
- the new runtime-provider section defaults safe-disabled/empty;
- an enabled model profile with no compatible protected runtime binding is inspectable but **not dispatch-constructible**;
- no release-only dependency broadening is introduced.

---

## 36D — Managed local llama.cpp runtime loader

Implement one code-owned `ManagedModelLoader` for the protected `originforge.llamacpp-managed-cpu@1` provider.

It owns the process lifecycle rather than merely connecting to an arbitrary caller endpoint.

Before process start it must prove:

- exact runtime provider kind/version;
- exact configured runtime ID matches the selected `ModelResourceProfile.runtime_id`;
- exact selected profile ID is bound by protected runtime configuration;
- exact executable exists, is a regular non-symlink file, is outside protected Origin Forge state, and matches configured SHA-256;
- exact model file exists, is a regular non-symlink file, is outside protected Origin Forge state, and matches the profile/runtime-binding SHA-256;
- the profile's `model_hash` is exact and matches the bound model file hash;
- the supplied Phase-14 resource lease belongs to that exact profile/request and contains no GPU lease for the CPU-only provider;
- serving is loopback-only.

Process construction rules:

- infrastructure-owned fixed argv builder only;
- no shell;
- no caller/model argv;
- no arbitrary caller/model environment map;
- minimal code-owned environment plus only explicitly required process/runtime fields;
- loopback host only;
- bounded fixed/protected port policy with explicit collision failure rather than fallback to remote/random authority;
- bounded stdout/stderr capture;
- bounded startup health/readiness checks;
- process-group/descendant cleanup on timeout/error/unload where the host platform supports the existing governed process-cleanup contract;
- no daemonization or hidden background persistence after loader unload;
- no automatic binary/model download;
- no internet lookup;
- no secret discovery.

The loaded object returned to `ScheduledModelAdapter` is the existing bounded text `LlamaCppAdapter`, configured exclusively from trusted provider/profile state. The loader verifies the adapter model identity and the exact selected profile relation before returning it.

`unload()` must terminate only the exact process instance owned by that loader session and must fail closed on unknown/reused instances.

Normal CI uses a controlled fake llama-server process contract to prove argv/environment/loopback/readiness/cleanup and identity binding without requiring a heavyweight model. A separately governed real-runtime evidence path may be added if required to prove a pinned production llama.cpp binary/model combination, but it remains distinct from the normal Python matrix.

---

## 36E — Execution dependency assembler

Add one code-owned assembler that reconstructs the complete bounded-code execution dependencies from protected state and the exact ACTIVE claim without invoking them.

Conceptually:

```text
assemble_bounded_retry_execution(
    runtime,
    active_claim,
    trusted_owner_registry,
    protected_config,
    runtime_provider_registry,
)
        ↓
BoundedExecutionAssembly(
    execution_owner_descriptor,
    exact Phase-34 request projection,
    model strategy adapters,
    sandbox backend,
    workspace manager,
    dependency_plan_hash,
)
```

The caller may nominate only the exact claim ID (or exact already-read claim object where an internal API requires it). It may not supply:

- model objects;
- runtime loaders;
- model/profile IDs;
- endpoints;
- API keys;
- executable/model paths;
- sandbox backend objects;
- Workspace manager implementations;
- model-role escalation order;
- adapter/contract/binder IDs;
- arbitrary environment/process settings.

The assembler derives all of those from code-owned registries, protected configuration, and the exact Phase-34/35 authority chain.

Assembly currentness requires:

- exact claim status `ACTIVE` and Phase-35 currentness `CURRENT_ACTIVE`;
- exact execution-owner descriptor match for adapter/contract/binder/request schema;
- every required Phase-14 model role has an explicit configured policy;
- every profile reachable from those explicit policies has a compatible trusted runtime provider or is rejected before dispatch construction;
- sandbox backend is constructible from protected config;
- no active/previous `DISPEXEC` already consumes the claim;
- deterministic dependency-plan hashing over all non-secret authority identities/fingerprints.

Assembly may construct objects but must not:

- call `BoundedRetryPolicy.drive()`;
- call `ModelAdapter.generate()`;
- acquire a model resource lease;
- start a llama.cpp process;
- create a Run or Workspace;
- transition Task/Flow/Goal state;
- publish Artifacts/Verifications;
- consume or terminalize the dispatch claim.

The managed loader remains lazy under `ScheduledModelAdapter`; actual model process loading is exercised only through the loader's own isolated tests/evidence until the later dispatcher phase.

---

## 36F — Execution ownership transaction primitives

Provide internal coordinator primitives that atomically establish and recover invocation ownership without performing the call themselves.

Start primitive:

```text
begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
```

It must:

1. revalidate exact Phase-35 claim ownership/currentness;
2. revalidate exact trusted execution-owner relation and dependency-plan fingerprint;
3. enter one authoritative SQLite transaction;
4. recheck claim `ACTIVE`, revision, Task identity/revision/hash/status, and absence of a prior execution for the claim;
5. insert one `DISPEXEC STARTED` row plus event;
6. leave the claim `ACTIVE` while the execution receipt is `STARTED`;
7. return the exact frozen receipt.

It performs no executor/model/backend call.

Terminal primitives require exact `execution_id + expected_execution_revision + expected_claim_revision` and update execution + claim atomically:

```text
finish_dispatch_execution_returned(...)
finish_dispatch_execution_raised(...)
interrupt_dispatch_execution(...)
```

Only a future trusted coordinator may call `RETURNED`/`RAISED` after the corresponding actual invocation boundary has occurred. Phase-36 public/operator surfaces must not expose a generic way to forge those terminal states.

Tests may exercise the internal transaction functions with explicit test-owned simulated invocation evidence, but no model or backend is called.

---

## 36G — Read-only inspection and pre-dispatch acceptance

Add an immutable/non-creating read surface using the existing Phase-30 SQLite guard for:

- runtime-provider configuration status/fingerprint;
- execution-owner registry status/fingerprint;
- exact dependency assembly eligibility without constructing/starting a model process;
- `DISPEXEC-*` show/currentness;
- ACTIVE claim + STARTED execution recovery detection;
- claim/execution historical relation validation.

No mutating CLI is required in Phase 36. If an operator CLI is added, it is inspection-only.

The cross-phase acceptance proof must establish:

```text
READY Task
→ exact Phase-32/33/34 chain
→ ACTIVE Phase-35 claim
→ trusted execution-owner selection
→ protected runtime dependency plan
→ exact lazy dependency assembly
→ one DISPEXEC STARTED receipt
→ STOP
```

It must also prove:

- a second execution cannot start for the same claim;
- a second claim cannot be acquired for the Task while `DISPEXEC` is STARTED because the originating claim remains ACTIVE;
- restart preserves STARTED execution + ACTIVE claim and fails closed;
- explicit interrupted recovery terminalizes both consistently;
- returned/raised terminalization consumes the claim exactly once in simulated transaction tests;
- no Phase-36 production path invokes `BoundedRetryPolicy.drive()`, `ModelAdapter.generate()`, or a production backend;
- no Task/Run/Workspace truth is duplicated in `DISPEXEC`.

---

## Required adversarial tests

At minimum:

- malformed/forged execution-owner descriptor rejected;
- owner mismatch against adapter/contract/binder/request schema rejected;
- missing model-role strategy policy rejected;
- implicit role/profile fallback rejected;
- unknown runtime provider rejected;
- caller-supplied loader/model/backend/endpoint/argv/environment authority impossible by API shape;
- runtime executable/model symlink, missing file, hash drift, wrong profile/runtime relation rejected before process start;
- CPU provider rejects GPU-bearing profile/lease;
- remote/non-loopback runtime serving rejected;
- fake runtime proves fixed argv/minimal environment/readiness/timeout/cleanup;
- loader rejects unknown/reused unload instance;
- dependency assembly creates no lease/process/Run/Workspace/Task mutation;
- stale/terminal Phase-35 claim cannot assemble or start execution;
- exact claim may create only one execution receipt;
- STARTED execution leaves claim ACTIVE;
- concurrent start attempts yield exactly one STARTED receipt;
- STARTED execution survives restart and blocks duplicate ownership;
- interrupted recovery requires expected revisions and atomically terminalizes execution + claim;
- simulated RETURNED/RAISED terminalization changes claim exactly `ACTIVE → CONSUMED` and preserves all frozen authority;
- terminal execution/claim states cannot be rewritten;
- immutable inspection creates no SQLite sidecars or protected-state mutations;
- source-level authority guards reject direct calls to `BoundedRetryPolicy.drive()`, model generation, production adapter execution, arbitrary subprocess construction, Artifact adoption/signing, merge, release, or self-training.

---

## Explicit authority exclusions

Phase 36 does **not** add:

- production `BoundedRetryPolicy.drive()` invocation;
- production Task execution;
- automatic Task retry/resume beyond existing bounded-policy semantics;
- background dispatch workers/queues;
- model-selected runtime/provider/profile/endpoint authority;
- remote model endpoints in the initial managed provider;
- GPU runtime placement in the initial managed provider;
- caller/model shell, argv, environment, import, callable, executable, model path, or credential authority;
- generic process execution;
- Task success/failure/quarantine interpretation from `DISPEXEC` status;
- a replacement Run/Workspace truth model;
- Artifact adoption/signing;
- Project Intelligence mutation;
- merge/release/self-training authority.

The first actual production executor call is explicitly deferred to the next phase after Phase 36 is merged and independently proven.

---

## Proposed implementation slices

```text
36A  DISPEXEC + CONSUMED contracts/schema
36B  trusted execution-owner registry + explicit model-role strategy
36C  protected runtime-provider config and validation
36D  managed local CPU llama.cpp loader + isolated fake-process proof
36E  lazy bounded-code dependency assembler
36F  execution ownership/start/terminal/recovery transaction primitives
36G  immutable read/currentness + cross-phase acceptance + canonical closure
```

Every authority-expanding slice must freeze one exact SHA and pass the normal Ubuntu Python 3.12/3.13 matrix before the next slice begins. Managed-runtime real evidence, if introduced, is separately governed and cannot replace the normal exact-head matrix.

---

## Exit condition

Phase 36 is complete when Origin Forge can take one exact current Phase-35 ACTIVE claim, deterministically select the only trusted bounded-code execution owner, reconstruct every non-secret execution dependency from protected configuration/code-owned registries, prove the selected profiles have trusted managed runtime bindings, construct the lazy model/sandbox/workspace dependency graph without caller authority, atomically establish one durable one-shot `DISPEXEC STARTED` receipt, recover/terminalize that ownership safely across restart, and still stop before `BoundedRetryPolicy.drive()`.

Only then may Phase 37 introduce the first governed single-shot production dispatcher.