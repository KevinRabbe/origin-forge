# Phase 47 — Governed Deterministic Simulation Production Dispatch

Status: **PLANNED — architecture frozen before implementation**

Verified prerequisite `main`:

```text
0f17098084b3976d9af3b0f30490781efe11fa92
```

Phase 47 promotes exactly one already-proven non-code backend, Phase-25 deterministic simulation, through the accepted Phase-33 → Phase-39 preparation and Phase-34 → Phase-37 dispatch chain.

This is intentionally a **downstream production-integration phase**. It does not widen the Phase-45/46 Goal-bootstrap Planner capability surface. Goal bootstrap remains code-only until a later separately reviewed phase proves that broader Goal planning is safe.

The new production vertical is exactly:

```text
existing Task requiring simulation.run
    ↓
Phase-32 exact route
    ↓
Phase-33 simulation WorkOrder
    ↓
Phase-34 simulation request binding
    ↓
Phase-35 exclusive claim
    ↓
Phase-36 STARTED execution ownership
    + simulation-only READY → RUNNING Task transition
    ↓
Phase-37 exactly one trusted SimulationService invocation
    ↓
Phase-25 SIMULATOR Run + SIMULATION_SPEC/RESULT/SUMMARY evidence
    ↓
DISPEXEC RETURNED / claim CONSUMED
    ↓
STOP with Task still RUNNING
```

A successful simulation dispatch means only that the exact governed simulation service returned structurally valid durable evidence. It does **not** mean the simulation findings satisfy the Task acceptance criteria, that balance/gameplay is semantically correct, or that the Task may be marked SUCCEEDED.

---

## 1. Why Phase 47 is the next dependency

The repository already contains a deliberately broad Phase-32 trusted adapter inventory, but Phases 33–37 intentionally integrated only:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
→ binder.code.bounded-retry@1
→ originforge.execution.bounded-retry@1
```

`originforge.simulation.deterministic` is already a Phase-32 trusted adapter for capability `simulation.run`, with execution effect `SIMULATION_ONLY` and replay class `DETERMINISTIC`, but it remains explicitly deferred downstream.

Phase 25 is the safest first second production adapter because its engine is:

- deterministic;
- finite and work-budgeted;
- declarative only;
- free of Python/JavaScript/shell/callback execution;
- free of process/network/model authority;
- free of caller-supplied executable/runtime/provider authority;
- independently structurally validated;
- already integrated with durable SIMULATOR Run/Artifact/Verification evidence.

By contrast, editor, media, runtime-observation, and playtest adapters require process/runtime/source/profile authority and therefore remain deferred.

---

## 2. Existing Phase-25 boundary to preserve

The accepted Phase-25 engine identity remains exactly:

```text
engine_id      = origin-forge-deterministic-sim
engine_version = 1
```

`run_simulation(spec)` remains the deterministic engine implementation.

`SimulationService.execute(task_id, spec)` remains the durable evidence owner and continues to:

- require a canonical RUNNING Task;
- create one `SIMULATOR` Run;
- create a fresh protected `SIMWS-*` workspace;
- persist exact canonical `request/spec.json`, `evidence/result.json`, and `evidence/summary.json`;
- independently bind result to spec;
- persist `SIMULATION_SPEC`, `SIMULATION_RESULT`, and `SIMULATION_SUMMARY` Artifacts;
- record `simulation-structure` Run Verification;
- finish only the SIMULATOR Run;
- leave production Task outcome unchanged.

Phase 47 must not weaken those semantics or create an alternate simulation engine/service truth.

---

## 3. Simulation specification template boundary

The current `SimulationSpec` combines two different concerns:

1. semantic deterministic simulation inputs; and
2. infrastructure-owned execution identities `SIMSPEC-*`, `SIM-*`, and `SIMWS-*`.

A WorkOrder planner must never choose the infrastructure identities. Phase 47 therefore introduces a pure immutable semantic template contract, conceptually:

```text
SimulationSpecTemplate
    engine_id/version        fixed to Phase-25 v1
    seed
    replicates
    max_steps
    stall_steps
    initial_state
    rules
    invariants
```

The template contains no:

- `SIMSPEC-*` ID;
- `SIM-*` session ID;
- `SIMWS-*` workspace ID;
- Task/Run/Artifact/Verification ID;
- filesystem path;
- executable/argv/environment;
- model/runtime/provider/resource authority.

The template must enforce the same Phase-25 semantic bounds and work-unit calculation as `SimulationSpec`.

`SimulationSpec.create(...)` must remain source-compatible and produce the same accepted concrete object semantics. Implementation may internally factor shared validation through the new template, but existing Phase-25 concrete spec/result hashes and behavior must not silently change.

After Phase-36 durable execution ownership exists, infrastructure materializes a fresh concrete `SimulationSpec` from the validated template. Only that post-ownership step allocates fresh `SIMSPEC-*`, `SIM-*`, and `SIMWS-*` IDs.

---

## 4. Phase-33 simulation dispatch contract

Add exactly one reviewed dispatch contract for:

```text
adapter_id  = originforge.simulation.deterministic
contract_id = simulation.deterministic@1
```

The contract accepts **no input refs** in v1.

This is deliberate. Phase-39 automated preparation currently invokes the WorkOrder planner with `allowed_input_refs=()`. Rather than add arbitrary evidence/path selection, the initial simulation contract is self-contained inert declarative data.

The WorkOrder payload may contain only the bounded semantic template. Because the existing inert validator-schema language intentionally supports only scalar/string-list fields, nested simulation structures must be encoded through bounded canonical JSON string fields and independently parsed by a dedicated custom validator. A suggested exact surface is:

```text
seed                 integer
replicates           integer
max_steps            integer
stall_steps          integer
initial_state_json   canonical JSON object string
rules_json           canonical JSON array string
invariants_json      canonical JSON array string
```

The engine ID/version are **not** caller/model payload fields. They are code-owned Phase-25 authority.

The validator must:

- reject duplicate JSON keys;
- reject floats/non-finite data;
- reject extra fields;
- require canonical JSON encoding for nested strings;
- reconstruct typed `SimulationRule` / `SimulationInvariant` values;
- reconstruct and validate one exact `SimulationSpecTemplate`;
- enforce all Phase-25 variable/rule/invariant/replicate/step/state/quantity/work-unit bounds;
- accept no `WorkOrderInputRef` values;
- expose no code, expression, callback, shell, process, endpoint, model, runtime, resource, or filesystem field.

The model may propose inert simulation semantics. Infrastructure remains the validator and execution authority.

### Built-in dispatch catalog behavior

`build_builtin_dispatch_catalog(...)` must become capability-catalog-sensitive rather than assuming bounded code is always present.

For a code-only Phase-32 catalog, the resulting dispatch catalog must remain semantically identical to the current accepted bounded-code contract.

For a simulation-only Phase-32 catalog, the resulting dispatch catalog contains exactly `simulation.deterministic@1`.

If both reviewed adapters exist in the supplied Phase-32 catalog, the dispatch catalog may contain both exact contracts. That does not itself authorize one preparation owner; PREPPOL owner resolution remains separately governed.

All other Phase-32 adapters remain deferred.

---

## 5. Phase-34 simulation binder

Add exactly one trusted binder relation:

```text
binder_id       = binder.simulation.deterministic@1
adapter_id      = originforge.simulation.deterministic
contract_id     = simulation.deterministic@1
request_type_id = SimulationService.execute@production-v1
```

The binder accepts no resolved input refs.

It independently reconstructs the exact validated semantic template from the audited WorkOrder payload and emits a request projection conceptually containing:

```text
task_id
engine_id/version
seed
replicates
max_steps
stall_steps
initial_state
rules
invariants
```

The projection contains no concrete Phase-25 execution IDs. Fresh `SIMSPEC/SIM/SIMWS` IDs are allocated only after `DISPEXEC STARTED` ownership is durable.

The binder registry becomes exactly two reviewed relations:

```text
code bounded-retry
simulation deterministic
```

No generic dynamic binder/plugin/import mechanism is added.

Existing Phase-34 frozen audit/currentness recomputation remains authoritative for both relations.

---

## 6. Phase-39 simulation preparation owner

The existing bounded-code preparation-owner descriptor must remain byte-for-byte authority-stable, including its current owner fingerprint.

Add a separate code-owned preparation owner for simulation, conceptually:

```text
owner_id = originforge.preparation.simulation-work-order-planner@1
planner_contract_id = BoundedProductionWorkOrderPlanner.propose@1
supported_adapter_id = originforge.simulation.deterministic
supported_dispatch_contract_id = simulation.deterministic@1
model_strategy_roles = (CODER_STRONG,)
```

The WorkOrder planner remains the already-accepted one-shot Phase-33 model boundary. The new owner grants that planner only the selected simulation dispatch contract/schema; it does not grant production execution authority.

The existing PREPPOL `_matching_owner(...)` single-owner invariant remains important:

- a code-only dispatch catalog resolves the existing code owner;
- a simulation-only dispatch catalog resolves the simulation owner;
- a catalog that simultaneously resolves multiple preparation owners fails closed rather than choosing by ordering.

This preserves current Phase-45/46 code PREPPOL fingerprints/currentness.

Phase 47 must add no automatic PREPPOL synthesis and no new caller-selected model/profile/runtime authority.

---

## 7. Goal-bootstrap isolation

Phase 45/46 remain deliberately code-only.

Phase 47 must not change the code-owned Goal bootstrap intersection:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

It must not make `simulation.run` visible to the Phase-45 Goal Planner, alter Goal bootstrap CAPCAT/CAPPOL/DISPCAT publication, or change `goal bootstrap status|start|recover` semantics.

A later phase may consider broader Goal planning only after this downstream simulation vertical is independently accepted.

Therefore Phase 47 can be exercised through an explicit existing/materialized simulation Task and exact simulation-specific Phase-32/39 authority without changing Goal bootstrap.

---

## 8. Phase-36 no-model execution owner

Add exactly one execution-owner descriptor:

```text
owner_id = originforge.execution.simulation.deterministic@1
adapter_id = originforge.simulation.deterministic
contract_id = simulation.deterministic@1
binder_id = binder.simulation.deterministic@1
model_strategy_roles = ()
requires_sandbox = false
requires_workspace_manager = false
```

The existing bounded-code execution-owner descriptor and fingerprint must remain unchanged.

The current descriptor validation assumes every execution owner has at least one model role. Phase 47 may relax only that assumption: an empty model-role tuple is valid for a reviewed owner whose relation requires no model. Duplicate/invalid role checks remain.

This does not make model scheduling optional for the bounded-code owner.

### Owner-specific dependency assembly

`assemble_production_execution_dependencies(...)` currently always builds model scheduling, managed llama.cpp runtime bindings, sandbox, Git workspaces, and `BoundedRetryPolicy` because there is only one owner.

Refactor the dependency object to preserve one common immutable dependency plan while allowing owner-specific runtime payloads.

For bounded code:

- existing scheduling/runtime/sandbox/workspace/policy assembly remains exact;
- no model/runtime/sandbox authority is weakened;
- existing `.drive()` arguments and behavior remain unchanged.

For deterministic simulation:

- no `create_model_scheduling(...)` call;
- no model profile/provider/runtime lookup;
- no resource lease;
- no `ManagedLlamaCppCpuLoader`;
- no `ScheduledModelAdapter`;
- no sandbox creation;
- no Git workspace manager;
- no `BoundedRetryPolicy`;
- the dependency plan records code-owned no-model/no-sandbox sentinels plus the exact owner/binding/request identities.

The plan remains content-addressed and is stored only through the existing `runtime_dependency_plan_hash` in `DISPEXEC`.

No schema expansion is required solely to store a simulation dependency plan unless implementation evidence proves otherwise.

---

## 9. Atomic simulation execution start

A simulation dispatch has one additional mechanical state requirement: Phase-25 `SimulationService` requires the Task to be RUNNING.

For the simulation owner only, `begin_dispatch_execution(...)` must atomically perform:

```text
validate exact ACTIVE claim + exact READY Task revision/hash/readiness
→ create exact DISPEXEC STARTED receipt
→ transition that exact Task READY → RUNNING
→ append canonical state events
→ COMMIT
```

This transition is execution-start mechanics, not Task outcome authority.

The claim and execution receipts intentionally retain the exact pre-transition READY Task revision/hash that authorized dispatch. The Task then advances to its normal RUNNING revision for Phase-25 service execution.

For bounded code, `begin_dispatch_execution(...)` must retain its existing behavior and must not start changing the Task itself.

If the atomic simulation begin fails, neither STARTED ownership nor the RUNNING Task transition may survive partially.

Once simulation STARTED commits, crash/recovery must never reset the Task to READY automatically.

---

## 10. Phase-37 exact two-owner dispatch fanout

`dispatch_claim_once(...)` remains the only public single-shot dispatch coordinator.

It must first freeze and validate the exact current Phase-34 request relation, then begin Phase-36 execution ownership, then dispatch through a **closed code-owned two-owner branch**.

The only accepted production owners become:

```text
originforge.execution.bounded-retry@1
originforge.execution.simulation.deterministic@1
```

Do not introduce:

- dynamic import;
- plugin registry;
- generic callable registry;
- arbitrary tool dispatch;
- model-selected owner;
- caller-selected owner;
- reflection-based backend invocation.

### Bounded-code branch

The existing reviewed call remains exactly one:

```text
BoundedRetryPolicy.drive(...)
```

Its `PolicyResult` semantics remain unchanged.

### Simulation branch

After the simulation-specific atomic STARTED + RUNNING transition:

1. reconstruct the exact bound `SimulationSpecTemplate`;
2. allocate fresh infrastructure-owned `SIMSPEC-*`, `SIM-*`, and `SIMWS-*` identities through the accepted Phase-25 concrete-spec factory;
3. call exactly once:

```text
SimulationService(runtime).execute(task_id, concrete_spec)
```

4. require a typed `SimulationServiceResult`;
5. revalidate the returned SIMULATOR Run/Task relation and exact durable Phase-25 result/summary evidence before treating the owner call as normally returned;
6. terminalize the existing DISPEXEC as RETURNED and claim as CONSUMED;
7. stop.

No second simulation call is allowed in the same dispatcher invocation.

---

## 11. Completed-dispatch result typing

The current `CompletedDispatchInvocation` assumes every owner returns `PolicyResult`.

Generalize only enough to represent the two reviewed typed returns while keeping Manager mechanics owner-neutral.

Conceptually the wrapper contains:

```text
execution: DispatchExecution
policy_result: PolicyResult | None
simulation_result: SimulationServiceResult | None
```

Exactly one owner result must be present and it must match the execution owner relation.

Existing bounded-code callers/tests retaining `.policy_result` remain source-compatible.

Phase-38/40/43/44 Manager logic must continue to inspect only dispatch mechanics (`DISPATCH_RETURNED`, execution/claim/task identities) and must not reinterpret either owner result as Task outcome truth.

---

## 12. Simulation Task outcome semantics

A normal simulation service return does **not** transition the production Task to SUCCEEDED, FAILED, BLOCKED, or QUARANTINED.

The Task remains:

```text
RUNNING
```

This is intentional.

Phase-25 `simulation-structure PASS` proves the deterministic service produced structurally bound evidence. It does not prove that simulation findings satisfy arbitrary Task acceptance criteria or semantic game/design quality.

Consequences:

- Manager cannot redispatch the Task because it is no longer READY;
- dependent Tasks remain blocked until canonical Task completion occurs separately;
- a human or future independently governed semantic/adjudication phase may inspect evidence, record appropriate Task Verification, and transition the Task;
- Phase 47 itself invents no Task-level PASS/FAIL truth.

No automatic Task completion is permitted merely because `DISPEXEC RETURNED` or the SIMULATOR Run succeeded.

---

## 13. Exception, crash, and recovery semantics

The existing Phase-37 no-replay principle remains stricter than the Phase-32 adapter replay class.

Even though the deterministic engine is replayable mathematically, Phase 47 does **not** automatically replay after a durable `DISPEXEC STARTED` owner boundary.

### Ordinary Python exception

If the simulation owner raises an ordinary `Exception` after STARTED:

- `SimulationService` retains its existing best-effort failed SIMULATOR Run evidence;
- dispatcher records `DISPEXEC RAISED`;
- claim becomes CONSUMED;
- Task remains RUNNING;
- no second simulation execution occurs automatically.

### BaseException/process death

If execution becomes uncertain after STARTED:

- DISPEXEC remains STARTED;
- claim remains ACTIVE;
- Task remains RUNNING;
- existing explicit dispatch recovery is required;
- recovery does not reset Task to READY;
- recovery does not rerun the simulation.

### Post-service / pre-terminalization crash

If Phase-25 durable evidence exists but DISPEXEC is still STARTED, that evidence remains inspectable but does not authorize an automatic replay or silent RETURNED inference in Phase 47.

A later dedicated reconciliation phase may be proposed if exact evidence proves a safe need. Phase 47 keeps the simpler fail-closed boundary.

---

## 14. Phase-38 through Phase-46 behavior

Phase 47 must preserve existing higher-level mechanics:

- Phase 38 selects at most one already-admissible Task and attempts at most one claim/dispatch;
- Phase 39 prepares at most one Task and crosses the WorkOrder planner boundary at most once;
- Phase 40 advances at most one selected global action;
- Phase 41/42 preparation recovery semantics remain unchanged;
- Phase 43 fixed six-step bounded Manager continuation remains unchanged;
- Phase 44 `manager status` / `manager advance` CLI remains unchanged;
- Phase 45 Goal bootstrap remains code-only and stops at READY;
- Phase 46 Goal-bootstrap CLI remains unchanged.

A simulation `DISPATCH_RETURNED` is still a terminal result for the bounded Manager invocation exactly like the current code dispatch result. The Manager does not continue to another Task.

---

## 15. Read-only inspection

Existing Phase-25 read-only simulation inspection remains valid and should show the SIMULATOR Run/Artifacts created by production dispatch because they use the same canonical Phase-25 evidence layer.

Existing dispatch/Manager inspection should continue to expose the exact claim/execution mechanics.

Phase 47 may add bounded owner/request-type fields to existing read projections only when required to distinguish the two trusted owners. It must not add a mutating simulation CLI, cockpit mutation route, HTTP endpoint, or background monitor.

---

## 16. Packaging and operator boundary

No new console script is added.

Packaging remains exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Phase 47 adds no direct `origin-forge simulation run` mutation command.

Production simulation execution occurs only through the already-governed Task preparation/claim/dispatch path and explicit Manager invocation.

The cockpit remains read-only.

---

## 17. Concurrency and adversarial acceptance

Final Phase-47 acceptance must prove at least:

### Contract / WorkOrder

- a simulation-only Phase-32 catalog routes `simulation.run` only to `originforge.simulation.deterministic`;
- code-only dispatch catalog output remains semantically unchanged;
- simulation dispatch contract accepts zero input refs;
- model cannot choose engine ID/version, SIMSPEC/SIM/SIMWS IDs, paths, executable/runtime/model/resource authority;
- custom simulation validator rejects duplicate keys, noncanonical nested JSON, floats, unknown fields, unknown variables, invalid rules/invariants, overflow bounds, excessive work, and forged engine fields;
- the WorkOrder planner remains one model call and infrastructure independently validates the proposal.

### Phase-34 binding

- exact simulation binder reconstructs only the validated template and Task ID;
- no resolver/path/artifact byte authority is introduced;
- forged request projection, binder fingerprint, schema hash, contract relation, or Task currentness fails audit/currentness.

### Phase-39 preparation

- existing bounded-code preparation owner ID/fingerprint remains unchanged;
- simulation-only DISPCAT resolves exactly one simulation preparation owner;
- a multi-owner dispatch catalog fails PREPPOL owner matching rather than choosing by ordering;
- simulation WorkOrder planning still has durable PLANNER_STARTED no-replay behavior;
- no simulation backend executes during preparation.

### Phase-36 ownership

- simulation owner requires zero model roles, no resource/model scheduler, no managed model runtime, no sandbox, and no Git workspace manager;
- code owner still requires its existing CODER_STRONG/model/runtime/sandbox/workspace dependencies;
- simulation STARTED and Task READY→RUNNING are atomic;
- concurrent workers produce at most one STARTED execution and one RUNNING transition;
- code begin behavior remains unchanged.

### Phase-37 invocation

- exact owner selection is closed to the two code-owned owner IDs;
- one simulation claim produces exactly one `SimulationService.execute(...)` call;
- concrete SIMSPEC/SIM/SIMWS IDs are fresh infrastructure-owned values allocated only after STARTED;
- the service creates exactly one SIMULATOR Run and exact Phase-25 spec/result/summary evidence;
- returned evidence revalidates before DISPEXEC RETURNED;
- normal return consumes the claim while leaving Task RUNNING;
- no Task-level Verification PASS/FAIL or terminal status is created by Phase 47;
- ordinary owner exception produces RAISED/CONSUMED and leaves Task RUNNING;
- BaseException/crash after STARTED leaves STARTED/ACTIVE/RUNNING and never auto-replays;
- crash after durable simulation evidence but before dispatch terminalization never auto-replays;
- concurrent Manager calls result in at most one simulation owner invocation;
- no newer Task is dispatched after the selected simulation result/race/failure in the same Manager call.

### Cross-phase isolation

- bounded-code dispatch remains green and preserves existing PolicyResult behavior;
- Phase-45/46 Goal bootstrap still exposes only code.change/bounded-retry authority;
- no Pixelorama/Blender/image/vision/audio/runtime/playtest adapter becomes dispatchable;
- no background loop, timer, poller, daemon, queue drain, automatic Goal bootstrap, or automatic Manager invocation appears;
- no Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training, merge, release, or deployment authority is added.

---

## 18. Proposed implementation slices

Freeze each authority-expanding slice at one immutable SHA and pass the normal Ubuntu Python 3.12/3.13 matrix before advancing.

### 47A — Simulation template + Phase-33 contract

- factor exact semantic `SimulationSpecTemplate` validation without changing concrete Phase-25 spec behavior;
- add the simulation WorkOrder validator/contract;
- make built-in dispatch-catalog construction capability-sensitive;
- preserve code-only contract identity exactly;
- update built-in dispatch review to mark only deterministic simulation newly supported.

### 47B — Phase-34 simulation request binding

- add the exact simulation binder/request projection;
- expand the built-in binder registry to exactly code + simulation;
- prove frozen audit/currentness and zero external input-ref authority.

### 47C — Phase-39 simulation preparation authority

- add separate simulation preparation-owner descriptor;
- preserve code owner descriptor/fingerprint exactly;
- prove simulation-only PREPPOL resolution and multi-owner ambiguity fail-closed;
- exercise one simulation WorkOrder-planner proposal with no backend execution.

### 47D — Phase-36 no-model owner + atomic simulation start

- add simulation execution-owner descriptor with empty model roles;
- refactor dependency assembly into owner-specific payloads while preserving bounded-code assembly;
- prove simulation requires no model/resource/runtime/sandbox/workspace dependencies;
- atomically commit DISPEXEC STARTED + READY→RUNNING only for simulation.

### 47E — Phase-37 exact simulation invocation

- add strict simulation invocation decoder;
- extend the single-shot coordinator to exactly two reviewed owner branches;
- allocate fresh concrete Phase-25 IDs after STARTED;
- call `SimulationService.execute(...)` once;
- validate typed durable result;
- generalize completed-invocation typing without changing Manager outcome semantics.

### 47F — Cross-phase adversarial acceptance

- full Phase-32→39→34→35→36→37→38/40/43 path for one simulation Task;
- concurrency, crash, exception, no-replay, no-fallback tests;
- Task remains RUNNING after simulation return;
- bounded-code regression coverage;
- Phase-45/46 code-only Goal-bootstrap isolation proof.

### 47G — Documentation / roadmap closure

- record exact accepted SHAs/runs;
- update living operator/development guidance only as needed;
- mark Phase 47 DONE in the canonical roadmap;
- final immutable Python 3.12/3.13 normal matrix;
- ready transition and SHA-guarded merge only on that exact green head.

If implementation evidence shows any slice contains more than one independently risky authority expansion, subdivide it instead of weakening the gate.

---

## 19. Explicit non-goals

Phase 47 does **not** add:

- Phase-45/46 Goal Planner support for `simulation.run`;
- automatic Goal bootstrap for simulation;
- automatic Manager invocation after Goal bootstrap;
- automatic semantic evaluation of simulation findings;
- automatic Task SUCCEEDED/FAILED/BLOCKED/QUARANTINED from simulation metrics;
- automatic tuning or parameter search;
- automatic simulation replay after STARTED uncertainty;
- model-selected engine/runtime/provider/executable/path/resource authority;
- arbitrary WorkOrder input refs for simulation;
- arbitrary Artifact/path byte reading;
- generic nested executable expression language;
- Python/JavaScript/shell/SQL/callback/tool/process/network execution in the simulation spec;
- a generic adapter/owner plugin registry;
- dynamic imports/reflection/callable dispatch;
- Pixelorama, Blender, image, vision, audio, runtime-observation, or playtest production promotion;
- new console scripts;
- mutating cockpit/HTTP/plugin/model-callable surfaces;
- Artifact adoption/signing;
- Project Intelligence / Design Bible mutation;
- Dream promotion;
- training/model-weight mutation;
- automatic merge/release/deployment.

---

## 20. Exit condition

Phase 47 is complete when one immutable repository head proves that an exact existing simulation Task can, without widening Goal-bootstrap authority and without caller/model runtime authority:

1. route to the existing trusted deterministic simulation adapter;
2. receive one independently validated self-contained bounded simulation WorkOrder;
3. bind one exact inert semantic simulation request;
4. be prepared under a simulation-specific code-owned PREPPOL owner;
5. acquire one exact Phase-35 claim;
6. atomically establish Phase-36 STARTED ownership and move the exact Task READY→RUNNING;
7. allocate fresh infrastructure-owned Phase-25 simulation identities;
8. invoke the existing `SimulationService` exactly once;
9. persist/revalidate canonical Phase-25 simulation evidence;
10. terminalize dispatch RETURNED/CONSUMED while leaving Task RUNNING for separate outcome adjudication;
11. stop without dispatching another Task or replaying uncertain work.

The final immutable implementation/documentation head must pass the normal Python 3.12 and Python 3.13 matrix with unrelated heavyweight external evidence workflows skipped/disarmed before ready-for-review transition and SHA-guarded merge.
