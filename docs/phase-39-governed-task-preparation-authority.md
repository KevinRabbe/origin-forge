# Phase 39 — Governed Task Preparation Authority & Single Tick

Status: **DONE — implementation complete; final exact-head closure gate pending**

Phase 39 closes the deliberate gap between Phase-31 materialized dependency graphs and Phase-38 dispatch admission.

Phase 38 can dispatch only an already-`READY` Task with a complete current audited Phase-34 authority chain. Phase 31 materializes Tasks as `QUEUED`; Phase 35 activation changes the Task revision/content hash; and Phases 32–34 must therefore be rebuilt after activation. Today those steps are individually governed but there is no durable single-shot preparation authority that can perform them without caller-selected routing/model authority or accidental duplicate planner calls after crash.

Verified prerequisite `main`:

```text
07e3e3ad4537b472876818942a43483b94521164
```

---

## Verified existing provenance

A governed Phase-31 PlanningInput created through Phase 32 already contains exact immutable capability authority evidence:

- `PLINPUT.capability_catalog_hash` binds the selected Phase-32 catalog content;
- `PLINPUT.capability_ids` are derived from the selected Phase-32 routing policy;
- `PLINPUT.verified_state_refs` automatically includes the exact selected `CAPCAT-*` ID/hash and exact selected `CAPPOL-*` ID/hash;
- `PLMAT-*` binds every materialized Task ID back to its exact `PLINPUT/PLPROP/PLAUD` chain.

However, `PLINPUT` has no dedicated selected `routing_policy_hash` field. Caller-provided verified-state evidence may legitimately contain additional capability-policy refs. Therefore later infrastructure must not infer a routing policy by "pick the only CAPPOL file" or by filesystem order. Phase 39 introduces an explicit preparation-policy binding that resolves this once and then remains immutable.

The Phase-33 `BoundedProductionWorkOrderPlanner` is already proposal-only and independently constrained, but its real `ScheduledModelAdapter` is supplied by its caller. Phase 36 solved the analogous execution problem with code-owned owner descriptors plus protected model/runtime assembly. Phase 39 must do the same for WorkOrder planning before any Manager is permitted to synthesize dispatch authority.

---

## Core boundary

Phase 39 accepts one explicit immutable preparation policy and performs at most one Task-preparation attempt:

```text
exact PREPPOL
    ↓
bounded eligible QUEUED Task selection from exact PLMAT
    ↓
create durable PREP ACTIVE receipt
    ↓
explicit Phase-35 QUEUED → READY activation
    ↓
exact Phase-32 route using PREPPOL CAPCAT/CAPPOL
    ↓
checkpoint PREP PLANNER_STARTED
    ↓
one code-owned scheduled WorkOrder Planner call
    ↓
trustworthy planner return checkpoint
    ↓
independent WORKAUD + protected Phase-33 publication
    ↓
Phase-34 INRES → DISPBIND → BINDAUD publication
    ↓
PREP READY
    ↓
STOP
```

Phase 39 never acquires a `DISPCLAIM-*`, creates a `DISPEXEC-*`, calls `dispatch_manager_tick()`, calls `dispatch_claim_once()`, or invokes `BoundedRetryPolicy.drive()`.

The intended mutating API is deliberately narrow:

```text
prepare_materialization_tick(runtime, preparation_policy_id)
```

The caller does not supply a Task ID, routing policy, adapter, dispatch contract, WorkOrder payload, binder, model profile, runtime provider, endpoint, sandbox, context paths, or fallback Task.

---

## New infrastructure identities

Phase 39 reserves:

```text
PREPPOL-*   immutable Task-preparation policy binding
PREP-*      durable per-Task preparation receipt
```

No model may choose either identity.

### PREPPOL authority

One immutable preparation policy binds exactly:

```text
PLMAT id/hash
PLINPUT id/hash
CAPCAT id/hash
CAPPOL id/hash
DISPCAT id/hash
preparation-owner id/fingerprint
planner request/contract version
model strategy role sequence
```

Policy construction must independently load and validate the whole relation:

- `PLMAT` must bind the stated `PLINPUT` exactly;
- the stated `CAPCAT-*` must appear in `PLINPUT.verified_state_refs` with the exact `PLINPUT.capability_catalog_hash`;
- the stated `CAPPOL-*` must appear in `PLINPUT.verified_state_refs`, bind that exact catalog ID/hash, and expose exactly `PLINPUT.capability_ids` as its allowed capability set;
- the stated `DISPCAT-*` must validate against that exact Phase-32 catalog;
- the preparation owner must be code-owned and current;
- unknown/multiple/conflicting relations fail closed.

A preparation policy does not itself activate, route, plan, audit, bind, claim, dispatch, or complete a Task.

---

## Code-owned WorkOrder-planner owner

Add an inert trusted preparation-owner descriptor for the one existing v1 WorkOrder planner, conceptually:

```text
owner_id:              originforge.preparation.work-order-planner@1
planner_contract:      BoundedProductionWorkOrderPlanner.propose@1
supported_adapter:     originforge.code.bounded-retry
supported_contract:    code.bounded-retry@1
model_strategy_roles:  (CODER_STRONG,)
```

The descriptor contains no callable/import path, endpoint, executable, argv, environment, secret, model path, or process authority.

The v1 model strategy is explicitly `CODER_STRONG` only. Phase-14 profile fallback inside that semantic role remains separately governed by protected configuration. Phase 39 does not invent a fast→strong retry/escalation policy.

A protected preparation dependency assembler must construct the exact `ScheduledModelAdapter` from existing config-v6 resource/model/runtime-provider authority, without sandbox or Workspace construction and without calling the model. It must persist/freeze a deterministic dependency-plan hash covering the exact model policy, ordered profile IDs, runtime IDs/provider fingerprints, and relevant protected config hashes before planner execution authority is crossed.

---

## Durable PREP receipt and schema v11

Advance the core schema to v11 with one durable preparation table and database uniqueness protecting one `ACTIVE` preparation per Task.

A receipt binds at minimum:

```text
preparation_id
project_id
preparation_policy_id/hash
materialization_id/hash
planning_input_id/hash
task_id
queued_task_revision/hash
ready_task_revision/hash (after activation)
route_decision_id/hash (after routing)
planner_dependency_plan_hash
planner_run_id (after trustworthy return)
work_order_id/hash
work_order_audit_id/hash
input_resolution_id/hash
dispatch_binding_id/hash
binding_audit_id/hash
stage
status
revision
created_at / updated_at
terminal_reason
```

All authority-bearing IDs/hashes already known at receipt creation remain immutable. Later fields may move only from null to their exact checkpoint value under expected receipt revision.

Suggested bounded stages:

```text
CLAIMED
ACTIVATED
ROUTED
PLANNER_STARTED
PLANNER_RETURNED
WORK_ORDER_AUDITED
BOUND
```

Terminal statuses:

```text
READY
INTERRUPTED
FAILED_PRE_PLANNER
```

`ACTIVE + PLANNER_STARTED` without a trustworthy later checkpoint is a recovery-required state. No clock TTL, PID guessing, automatic expiration, receipt stealing, or automatic model replay is allowed.

---

## Exactly-once-at-the-planner-boundary semantics

Phase 39 cannot make an arbitrary model request mathematically exactly-once across host failure. It can provide the safety property required here:

```text
no automatic duplicate WorkOrder-planner invocation after durable PLANNER_STARTED
```

Required order:

1. create/own exact ACTIVE `PREP-*`;
2. activate the exact selected QUEUED Task once;
3. route the resulting READY revision through PREPPOL's exact CAPCAT/CAPPOL;
4. assemble and freeze the code-owned planner dependency plan;
5. durably advance `PREP.stage → PLANNER_STARTED`;
6. make exactly one WorkOrder-planner model call;
7. after trustworthy return, durably bind the exact planner Run and WorkOrder IDs/hashes;
8. only then continue deterministic infrastructure audit/publication/binding work.

If process death, `BaseException`, or an uncertain failure occurs after `PLANNER_STARTED` and before a trustworthy `PLANNER_RETURNED` checkpoint, the PREP remains ACTIVE/recovery-required and future preparation ticks do not call the model again.

Ordinary deterministic failures before `PLANNER_STARTED` may become `FAILED_PRE_PLANNER` because no model call can have occurred. Explicit interruption after recovery review is separate infrastructure authority and never implies Task failure.

---

## Candidate admission and selection

One PREPPOL scopes selection to Tasks materialized by its exact `PLMAT-*` only.

A Task is initially eligible only when:

- it belongs to that exact materialization;
- canonical status is `QUEUED`;
- Phase-31 dependency readiness is `READY` for the QUEUED Task;
- there is no ACTIVE PREP receipt for that Task;
- there is no existing current READY Phase-34 chain already making the Task Phase-38 dispatch-admissible;
- its required capabilities remain permitted by the bound CAPPOL.

Selection is deterministic by:

```text
Task.created_at ASC
Task.id ASC
```

One tick selects at most one Task. A race/staleness/preparation failure never falls through to a second Task during the same call.

Phase 39 does not introduce legacy Task priority, resource pressure, estimated cost, retry history, objective text, or model judgment as scheduling authority.

---

## Post-activation routing

Activation must use the existing Phase-35 expected-revision path. The resulting READY Task revision/hash is re-read and bound into PREP before routing.

Routing must call only the existing Phase-32 resolver with PREPPOL's exact `CAPCAT-*` / `CAPPOL-*`. No catalog/policy discovery by directory enumeration is allowed.

A non-ROUTABLE outcome, unsupported adapter, policy/catalog drift, or Task revision drift fails before planner invocation. The v1 preparation owner supports only the already-reviewed bounded-code dispatch contract; media/runtime preparation remains fail-closed until Phase-33/34 contract coverage exists for those adapters.

---

## WorkOrder planning and publication

The model boundary remains the existing Phase-33 strict WorkOrder Planner contract:

- one taskless `WORK_ORDER_PLANNER` Run;
- one exact current route;
- infrastructure-selected dispatch contract;
- inert schema;
- finite infrastructure-owned evidence allow-list;
- strict duplicate-key/authority-field/bounds validation;
- infrastructure WorkOrder construction;
- no model self-audit or dispatch.

For the v1 bounded-code contract, `max_input_refs = 0`; Phase 39 therefore supplies no caller/model evidence-ref discovery surface.

After trustworthy planner return, Phase 39 performs only existing independent infrastructure operations:

```text
WORKORD publication
→ independent WORKAUD
→ WORKAUD publication
→ INRES construction/publication
→ DISPBIND construction/publication
→ independent BINDAUD
→ BINDAUD publication
```

The exact final `BINDAUD PASS` relation must be current for the same READY Task revision before PREP may become READY.

No Task transition beyond the initial `QUEUED → READY` activation occurs in Phase 39.

---

## Recovery and idempotence

Read-side preparation status must distinguish at least:

```text
ELIGIBLE_QUEUED
ACTIVE_PRE_PLANNER
PLANNER_RECOVERY_REQUIRED
POST_PLANNER_RESUMABLE
READY_FOR_PHASE38
INTERRUPTED
FAILED_PRE_PLANNER
STALE_OR_INVALID
```

A future explicit recovery operation may resume deterministic post-planner infrastructure work only when exact stored Run/WorkOrder checkpoint evidence reconstructs. It may never infer that an uncertain planner call did not occur.

If PREP is READY and the exact Phase-34 chain remains current, later preparation ticks exclude the Task; Phase 38 may then admit it independently.

Phase 39 does not automatically call Phase 38 after successful preparation.

---

## Read-only inspection

Expose non-creating bounded inspection for:

```text
preparation policy
materialization preparation eligibility
PREP receipt/stage/currentness
prepared Phase-34 authority IDs
```

It must reuse the Phase-30 immutable SQLite guard and independent protected-evidence readers. Inspection may not create/migrate/checkpoint SQLite, create WAL/SHM/journal sidecars, repair a receipt, call the planner, activate a Task, create a route/WorkOrder/binding, acquire a dispatch claim, or invoke production work.

No mutating CLI/HTTP/cockpit control is required in Phase 39.

---

## Cross-phase acceptance

The final acceptance proof must cover:

- exact `PLMAT → PLINPUT → CAPCAT/CAPPOL` provenance recovery;
- conflicting or ambiguous CAPPOL evidence rejected unless exact PREPPOL resolves it;
- PREPPOL cannot bind a policy/catalog outside the frozen planning evidence;
- caller cannot supply Task/routing/model/profile/runtime/WorkOrder/binder authority to the preparation tick;
- only dependency-ready QUEUED Tasks from the bound PLMAT are candidates;
- no automatic selection of another Task after a race/failure;
- one concurrent preparation winner per Task;
- activation happens exactly once and forces READY-revision routing;
- pre-activation Phase-32/33/34 evidence is stale and never reused;
- unsupported routed adapters stop before the WorkOrder model call;
- protected model/runtime dependency assembly loads no model and acquires no lease before the explicit planner boundary;
- `PLANNER_STARTED` is committed before the single model call;
- two concurrent ticks produce at most one planner call for one Task;
- simulated crash/uncertainty after PLANNER_STARTED never auto-replays;
- a trustworthy planner return binds the exact taskless Run + WorkOrder evidence;
- independent WORKAUD and BINDAUD PASS are required before PREP READY;
- PREP READY leaves canonical Task status READY;
- successful preparation does not acquire `DISPCLAIM-*` or create `DISPEXEC-*`;
- Phase 38 independently sees the resulting current Phase-34 authority on a later call;
- no Task outcome reinterpretation, Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training, merge, release, or background scheduling authority is introduced.

Normal CI may use governed deterministic/fake model runtime boundaries for planner-call-count and crash semantics; heavyweight model downloads are not part of the normal merge gate.

---

## Proposed implementation slices

```text
39A  PREPPOL/PREP contracts + schema-v11 durable receipt
39B  exact PLMAT/PLINPUT/CAPCAT/CAPPOL provenance resolver + immutable eligibility
39C  code-owned WorkOrder-planner owner + protected scheduled-model dependency assembly
39D  single preparation tick through activation/routing/PLANNER_STARTED/one planner call
39E  post-planner WORKAUD + Phase-34 publication + PREP READY / recovery semantics
39F  immutable preparation status inspection
39G  adversarial cross-phase concurrency/crash/no-dispatch acceptance
39H  documentation / roadmap closure
```

Every authority-expanding slice freezes one exact SHA and must pass the normal Ubuntu Python 3.12/3.13 matrix before the next slice begins.

---

## Explicit authority exclusions

Phase 39 does **not** add:

- automatic Phase-38 dispatch after preparation;
- dispatch-claim acquisition or execution receipts;
- `dispatch_claim_once()` or `BoundedRetryPolicy.drive()` invocation;
- background polling, worker daemon, queue, cron loop, or repeated preparation loop;
- fallback to a second Task within one tick;
- caller-selected Task, routing policy, adapter, contract, binder, model profile, runtime provider, endpoint, loader, sandbox, argv, or environment;
- implicit capability/routing policy discovery by filesystem order;
- model-selected evidence refs beyond exact contract-bound infrastructure allow-lists;
- media/runtime dispatch preparation before their Phase-33/34 contracts are independently supported;
- Task/Flow/Goal success/failure/quarantine semantics;
- a second Task/Run/Workspace result truth model;
- Artifact adoption/signing;
- Project Intelligence mutation;
- Dream promotion;
- training/checkpoint activation;
- merge or release authority.

---

## Exit condition

Phase 39 is complete when Origin Forge can take one explicit immutable preparation policy over an exact Phase-31 materialization, deterministically choose at most one dependency-ready QUEUED Task, durably own preparation, activate it exactly once, route the new READY revision using the exact planning-bound Phase-32 authority, cross one code-owned WorkOrder-planner model boundary at most once with fail-closed crash semantics, independently construct/audit/persist the Phase-33/34 chain, leave the Task READY with current `BINDAUD PASS` authority for a later Phase-38 Manager tick, and stop without dispatching production work.

---

## Implementation and CI closure evidence

Implementation PR #60 is based on the merged Phase-39 planning head `ae944742bcdf315a2ddf26d5f214b1c4b6c9e102` and was advanced only after exact-head normal CI gates.

Accepted implementation boundaries:

- **39A — contracts/schema:** `9ee9dbe1535eac05315f865c940fad867b3f60f6`; normal run `31642616970` passed Python 3.12 and 3.13.
- **39B — exact provenance/admission:** `2427e9bdfe8080e66a44064f5de785e18f1e28c1`; run `31645722070` passed Python 3.12 and 3.13.
- **39C — code-owned planner owner/dependencies/PREPPOL store:** `2a5d419d86a0b6761cdb653775a0eeb4be07eb71`; run `31646431337` passed Python 3.12 and 3.13.
- **39D — one preparation tick through trustworthy planner return:** `133372ca569f6e536e023b55f949ff779c7ebabb`; run `31647276851` passed Python 3.12 and 3.13.
- **39E1 — planner-evidence reconstruction/recovery:** `1a71c2812e1799982b27df5a32fafe60dadd0303`; run `31647921089` passed Python 3.12 and 3.13.
- **39E2 — exact Phase-33 WorkOrder publication/audit:** `f023ea035692b848456850ff612631936df4875a`; run `31648866727` passed Python 3.12 and 3.13.
- **39E3 + 39F integrated authority/status boundary:** `7a5684d5682e0a7e1cc553a62bea51f84f752d7e`; run `31652642583` passed Python 3.12 and 3.13. This is the authoritative Phase-34 resolver-fingerprint boundary used by Phase 38.
- **39G — adversarial cross-phase acceptance:** `d2bc3be8d380e2387411001f3261b2630be7f79b`; run `31652889606` passed Python 3.12 and 3.13. The delta from the prior accepted implementation head is tests-only.

Superseded/rejected evidence retained for auditability:

- `dea41e8855bb893fa59ebb2003e46035ddcd4ef4` failed both normal interpreters because an E2 test fixture attempted the illegal canonical transition `READY → READY`. The repair changed only the fixture to legal `READY → BLOCKED` drift; E2 production code was unchanged.
- `d40a152ec44e1e607f6b08f83d860e2b88d242f0` / run `31649282874` initially passed both interpreters for E3, but later cross-phase status acceptance proved that E3 had frozen the core-only resolver-registry fingerprint while Phase 38 correctly trusts the full reviewed Phase-34 resolver registry including `AudioProfileInputResolver`.
- `007cf79000588cb286bc8da6e691505ace0ee4fe` / run `31651941634` failed both interpreters on that real Phase39→Phase38 integration mismatch. The accepted repair aligned the E3 producer, E3 test harness, and 39F inspector to the canonical `build_dispatch_input_resolver_registry()` authority, producing accepted head `7a5684d5682e0a7e1cc553a62bea51f84f752d7e` without changing lifecycle, selection, persistence, or model-call semantics.

The accepted Phase-39 implementation proves that one explicit `PREPPOL-*` can deterministically prepare at most one dependency-ready materialized Task, commit planner ownership before one model call, recover fail-closed without automatic replay, publish current audited Phase-33/34 authority, and stop with the canonical Task still `READY`. The final acceptance suite additionally proves one-winner concurrent PREP acquisition, no second-Task fallback after a race, pre-activation Phase-32/33/34 staleness, fresh post-activation authority visible to Phase 38, and zero `DISPCLAIM-*` / `DISPEXEC-*` creation.

The documentation/roadmap closure head created after these proofs must itself pass the final normal Python 3.12/3.13 matrix before ready-for-review transition and SHA-guarded merge.
