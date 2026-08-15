# Phase 47 — Governed Deterministic Simulation Production Dispatch — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-47-governed-deterministic-simulation-production-dispatch.md`. Phase 47 promotes only the existing deterministic simulation backend into the governed production preparation/claim/execution path while preserving the existing bounded-code path, Phase-45/46 code-only Goal bootstrap, Manager stop/no-fallback semantics, and the Phase-25 rule that simulation evidence does not become production Task truth.

## Final production boundary

An already-governed Task whose exact Phase-32 authority is:

```text
simulation.run
→ originforge.simulation.deterministic
→ simulation.deterministic@1
```

may now proceed through the existing preparation and Manager path to exactly one reviewed deterministic simulation execution owner.

The production execution sequence is:

```text
QUEUED simulation Task
→ governed Phase-39 preparation / WorkOrder planning
→ current PASS-audited Phase-34 binding
→ exact Phase-35 claim
→ atomic Phase-36 DISPEXEC STARTED + Task READY→RUNNING
→ fresh execution-owned SIMSPEC / SIM / SIMWS identities
→ exactly one SimulationService.execute(...)
→ canonical Phase-25 SIMULATOR Run + spec/result/summary evidence
→ durable result revalidation
→ DISPEXEC RETURNED / claim CONSUMED
→ Task remains RUNNING
```

A normal simulation return is therefore dispatch completion evidence, not Task success/failure, semantic-balance truth, tuning authority, Artifact adoption, merge, or release authority.

## 47A — simulation template and dispatch contract

Phase 47A added the ID-free `SimulationSpecTemplate` semantic boundary and the strict deterministic simulation WorkOrder validator/contract.

The accepted contract:

- is self-contained and accepts zero external input refs;
- fixes engine identity/version in code;
- accepts only bounded deterministic simulation semantics already enforced by Phase 25;
- permits no caller/model-selected SIMSPEC/SIM/SIMWS identity, path, executable, runtime, provider, resource, model, process, network, shell, SQL, callback, or arbitrary tool authority;
- adds `simulation.deterministic@1` only for an explicit simulation-capable Phase-32 catalog;
- preserves the full/global Phase-45/46 dispatch authority as the original code-only `code.bounded-retry@1` relation.

## 47B — exact Phase-34 simulation request binding

Phase 47B expanded the built-in binding inventory from one code binder to exactly two reviewed binders: bounded code plus deterministic simulation.

The simulation binder:

- reconstructs only Task identity plus the independently validated `SimulationSpecTemplate` projection;
- accepts no external input refs or arbitrary Artifact/path bytes;
- allocates no concrete simulation execution identities;
- is frozen and audited through the existing Phase-34 evidence/currentness contracts;
- fails closed on request, schema, binder, contract, Task-currentness, or fingerprint drift.

The accepted bounded-code Phase-34 implementation and compatibility surface remain intact.

## 47C — separate simulation preparation authority

Phase 47C added `originforge.preparation.simulation-work-order-planner@1` as a separate code-owned Phase-39 preparation owner while preserving the bounded-code preparation owner identity/fingerprint exactly.

Simulation preparation still uses the accepted one-shot governed WorkOrder Planner and `CODER_STRONG` planning role. A simulation-only DISPCAT resolves the simulation preparation owner; a code-only DISPCAT resolves the existing code owner; a multi-owner catalog fails closed rather than selecting by ordering.

Preparation stops before backend execution. `SimulationService.execute()` is not crossed during planning/PREPPOL construction.

## 47D — zero-model execution owner and atomic start

Phase 47D added the deterministic simulation execution owner with an empty model-role set and owner-specific dependency assembly.

The accepted simulation execution dependencies require no:

- model profile or model runtime;
- resource scheduler lease;
- managed model provider/endpoint;
- sandbox backend;
- Git Workspace manager.

For simulation only, Phase 36 atomically commits the exact `DISPEXEC STARTED` receipt and the exact Task `READY → RUNNING` transition under the existing transaction/revision contract. Rollback tests prove neither side can persist alone. The bounded-code begin path remains unchanged.

Phase 47D deliberately does not invoke the simulation backend and does not allocate SIMSPEC/SIM/SIMWS identities.

## 47E — exact single-shot simulation invocation

Phase 47E extends the single-shot Phase-37 coordinator to exactly two hard-coded reviewed owner branches.

For deterministic simulation it:

- revalidates the exact active claim, binding audit, binder/request relation and owner relation;
- allocates fresh concrete `SIMSPEC-*`, `SIM-*`, and `SIMWS-*` identities only after durable STARTED ownership;
- calls `SimulationService.execute(task_id, concrete_spec)` exactly once;
- requires a typed `SimulationServiceResult`;
- reopens and integrity-checks the canonical Phase-25 spec/result/summary Artifacts;
- requires the exact SUCCEEDED `SIMULATOR` Run and exact PASS `simulation-structure` Run verification;
- validates result/spec/summary hashes and lineage before recording DISPEXEC `RETURNED`;
- preserves ordinary owner-exception `RAISED/CONSUMED` behavior and BaseException `STARTED/ACTIVE` no-replay uncertainty;
- leaves the production Task RUNNING after either normal simulation return or uncertain post-STARTED state.

The bounded-code coordinator still contains exactly one `.drive()` call site. The simulation branch contains exactly one `.execute()` call site. Manager does not reinterpret either owner result into Task semantics.

## 47F — cross-phase adversarial acceptance

Phase 47F is acceptance-only. Its final merged diff adds one test file and no production code.

The accepted real temporary-project scenarios prove:

- a simulation-only Phase-32 authority chain reaches the real Phase-39 → 34 → 35 → 36 → 37 → 38/40/43 path through one bounded Manager invocation;
- normal return creates exactly one SIMULATOR Run and the canonical Phase-25 simulation spec/result/summary evidence, consumes the claim, returns the dispatch, and leaves Task RUNNING with no Task-level verification;
- ordinary simulation exception records RAISED/CONSUMED, leaves Task RUNNING, and does not fall through to a newer Task;
- BaseException after STARTED leaves STARTED/ACTIVE/RUNNING and restart never automatically replays the simulation owner;
- durable simulation evidence followed by dispatch-terminalization failure leaves explicit recovery-required state and restart never replays the already-executed simulation;
- two Managers pinned to the same selected simulation dispatch candidate race the real claim boundary, produce at most one simulation owner invocation, and never dispatch the newer Task;
- Phase-45/46 Goal-bootstrap ownership remains exactly `code.change → originforge.code.bounded-retry → code.bounded-retry@1` with the original code preparation owner;
- the invocation coordinator remains closed to exactly one bounded `.drive()` and one deterministic simulation `.execute()` call site.

No acceptance failure demonstrated a production defect. The final 47F repair history only removed interpreter-sensitive test timing; production code remained unchanged throughout 47F.

## Manager, Goal-bootstrap, and packaging boundaries preserved

A simulation `DISPATCH_RETURNED` is terminal for the current bounded Manager invocation just like the existing bounded-code dispatch result. Manager does not automatically dispatch another Task in the same call and does not treat simulation metrics as Task outcome truth.

Phase-45/46 Goal bootstrap remains deliberately code-only. `goal bootstrap start|recover` may prepare the existing bounded-code authority and stops at GOALBOOT READY; it does not gain `simulation.run` capability and does not automatically invoke Manager.

Production simulation execution therefore requires already-governed simulation Task/materialization/preparation authority and the existing explicit Manager invocation. Phase 47 adds no direct `origin-forge simulation run` mutation command.

Packaging remains exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The cockpit remains read-only.

## Authority exclusions preserved

Phase 47 adds no:

- automatic Goal-bootstrap support for `simulation.run`;
- automatic Goal bootstrap or bootstrap→Manager chaining;
- automatic semantic interpretation of simulation findings;
- automatic Task SUCCEEDED/FAILED/BLOCKED/QUARANTINED transition from simulation metrics;
- automatic tuning, parameter search, replay, or retry after STARTED uncertainty;
- model/caller-selected engine, executable, runtime, provider, path, model, profile, resource, sandbox, Workspace, SIMSPEC/SIM/SIMWS, or dispatch-owner authority;
- arbitrary simulation WorkOrder input refs or arbitrary Artifact/path byte reads;
- generic owner/plugin/tool dispatch or dynamic executable expression language;
- promotion of Pixelorama, Blender, image, vision, audio, runtime, or playtest adapters into production dispatch;
- background loop, queue drain, timer, watcher, poller, daemon, service, or automatic Manager invocation;
- mutating simulation CLI, cockpit route, HTTP endpoint, plugin endpoint, or model-callable mutation surface;
- Artifact adoption/signing, Project Intelligence/Design Bible mutation, Dream promotion, training/model activation, merge, release, deployment, or remote multi-user authority.

## Exact-head accepted evidence

- **Phase-47 planning — PR #96:** exact head `d0c93da80b8e8a8f62c23c9e26a238f85fbb289f`; normal run `31854658992` passed Python 3.12 and Python 3.13; merged as `c777661269295d94b42f960f23620dfd81103712`.
- **47A — simulation template + Phase-33 contract — PR #97:** exact head `33905dd52fcf0d7e107311321f8d2cc584bc4de5`; normal run `31855236685` passed Python 3.12 and Python 3.13; merged as `071c64d3793eaca40b713afce180a91c8801098d`.
- **47B — Phase-34 simulation request binding — PR #98:** exact head `b84d52caf0f52f1ec782427e3d9615a3f8d5fe85`; normal run `31863500202` passed Python 3.12 and Python 3.13; merged as `6987d2f751e637c201c6e9a63c2e228c2b421fd2`.
- **47C — Phase-39 simulation preparation authority — PR #99:** exact head `a750bc59c3ae8470e727586d41fb0e9c886c1b73`; normal run `31890507717` passed Python 3.12 and Python 3.13; merged as `93c67f3e5cff24ce21a576edb9b845b45ba80533`.
- **47D — Phase-36 no-model owner + atomic simulation start — PR #100:** exact head `72f473691c11b664e276ca1d7afe797f532736ba`; normal run `31900288864` passed Python 3.12 and Python 3.13; merged as `5e42f0083cd03dd9ae851d2e5244927ec0a1319e`.
- **47E — Phase-37 exact simulation invocation — PR #101:** exact head `32306b005eff6296eb0c94c1152d8b14e5977f04`; normal run `31900910397` passed Python 3.12 and Python 3.13; merged as `61b9daa3657fd3a09527176e2975c5d55cea71ab`.
- **47F — cross-phase adversarial acceptance — PR #102:** exact accepted head `6389dd236df636b38f260f832afb252b86b72c62`; normal run `31910549681` / #1344 passed Python 3.12 and Python 3.13; the final diff is exactly one acceptance-test file with no production mutation; SHA-guarded merged as `29e00d8d5afa20f9f24c6a20fef35b8cfffa5340`.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact merged Phase-47F main `29e00d8d5afa20f9f24c6a20fef35b8cfffa5340`.

The closure branch may modify documentation only. It must preserve the three packaged scripts, read-only cockpit boundary, code-only Phase-45/46 Goal bootstrap, bounded Manager semantics, and the accepted two-owner production invocation surface.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
