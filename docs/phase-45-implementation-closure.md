# Phase 45 — Governed Goal Bootstrap Authority — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-45-governed-goal-bootstrap-authority.md`. The planning document remains the frozen authority contract; this companion records the accepted durable GOALBOOT authority spine, governed Goal-Planner boundary, deterministic post-planner finalization, narrow operator/API surface, packaging/cockpit isolation, and exact-head CI evidence.

## Final governed bootstrap boundary

Phase 45 fills the missing explicit bridge from one exact canonical Goal revision to the existing Phase-39 PREPPOL handoff consumed by Manager admission.

One bootstrap authority is represented by an infrastructure-owned durable `GOALBOOT-*` receipt. The receipt binds the exact current Goal revision/hash and progressively checkpoints the exact authority/evidence chain:

```text
GOALBOOT
  -> CAPCAT / CAPPOL / DISPCAT
  -> PLINPUT
  -> PLANNER_STARTED dependency proof
  -> exact Planner Run + PLPROP
  -> independent PLAUD PASS
  -> PLMAT
  -> PREPPOL
  -> READY
```

`READY` means only that the exact Goal revision has a current materialization and exact current PREPPOL that existing Manager admission can discover. Phase 45 does not invoke Manager, dispatch a Task, reinterpret Task outcome, adopt/sign an Artifact, merge code, or release anything.

## 45A — durable GOALBOOT receipt foundation

The first implementation slice added:

- infrastructure-owned `GOALBOOT-*` IDs;
- schema v12 durable `goal_bootstraps` rows;
- one-current-owner protection for the same exact Goal revision;
- typed stage/status/checkpoint invariants;
- exact canonical Goal revision/hash acquisition;
- `BEGIN IMMEDIATE` plus revision-CAS checkpoints;
- immutable historical terminal evidence;
- explicit pre-planner failure and interruption terminalization.

No capability publication, PlanningInput construction, Planner call, plan audit, materialization, PREPPOL, Manager, CLI/API, packaging, or cockpit authority was added in this slice.

## 45B — code-owned authority and PlanningInput freeze

The second slice made the bootstrap authority self-contained and derived rather than caller-selected:

- one code-owned Goal-bootstrap owner descriptor and stable fingerprint;
- exact current Phase-32/33/39 intersection limited to `code.change` -> `originforge.code.bounded-retry` -> `code.bounded-retry@1`;
- immutable CAPCAT/CAPPOL/DISPCAT publication with exact GOALBOOT checkpointing;
- bounded Project Intelligence projection hashing;
- protected CODER_STRONG model/resource-policy projection hashing;
- governed PlanningInput construction/publication and exact checkpointing;
- restart recovery that never chooses orphan authority by ordering;
- fail-closed configuration handling before the Planner boundary.

The caller cannot choose capability catalog IDs, routing policy IDs, dispatch catalog IDs, model/profile/runtime/provider/fallback selection, Task identity, or Manager behavior.

## 45C — governed Planner checkpoint and no-replay recovery

The third slice added the single Goal-Planner model boundary while preserving the durable uncertainty fence:

- durable `PLANNER_STARTED` dependency-plan checkpoint before model execution;
- one exact taskless Run and Run-targeted dispatch authorization committed before any model request;
- code-owned selected-profile/runtime binding through the protected existing model stack;
- exactly one reviewed Planner invocation path;
- exact Run request/response proof and immutable PLPROP publication;
- `PLANNER_RETURNED` as the first GOALBOOT checkpoint that stores Planner Run and proposal identity;
- crash/restart recovery that can resume a pre-dispatch started checkpoint once but never automatically replays an uncertain dispatched Planner call;
- exact adoption of a trustworthy already-persisted Planner result after a post-call/pre-checkpoint crash;
- protected-config drift and concurrent-worker fail-closed behavior.

The v12 receipt invariant remains deliberate: `PLANNER_STARTED` stores only the dependency-plan hash. The exact `planner_run_id` first appears at `PLANNER_RETURNED`.

## 45D — independent audit, materialization, PREPPOL, READY

The fourth slice completes only deterministic post-planner work:

- independent Phase-31 structural `audit_plan(...)` over the exact PLINPUT/PLPROP relation;
- atomic PLAUD publication/checkpoint with only PASS authority continuing;
- exact existing Phase-31 materializer invocation and PLMAT checkpoint;
- crash-idempotent adoption of the one exact already-persisted PLMAT when process death occurs after materialization but before the receipt checkpoint;
- exact Phase-39 PREPPOL construction from the checkpointed `PLMAT + CAPCAT + CAPPOL + DISPCAT` relation;
- serialized immutable PREPPOL publication under GOALBOOT finalization ownership, followed by full normal provenance revalidation and READY checkpointing;
- crash-idempotent adoption of the one exact already-persisted PREPPOL after publish-before-checkpoint death;
- bounded cause-aware retry only for transient active-journal / SQLite busy writer contention;
- authority drift remaining terminal rather than being mistaken for an ordinary CAS race;
- two-worker convergence to one PLAUD, one PLMAT, one PREPPOL, one Flow/Task graph, and one READY receipt.

Phase 45D stops immediately after PREPPOL publication/READY. It creates no dispatch claim/execution and performs no Manager advancement.

The PREPPOL filesystem publication deliberately reuses the existing protected Phase-39 store semantics: exclusive create, canonical bytes, file flush/fsync, and exact readback/provenance validation. Phase 45 does not silently redefine that store into a stronger temp-file-rename/directory-fsync power-loss contract.

## 45E — narrow operator/API and read-only status boundary

The final implementation slice adds a module/API-first operator boundary rather than changing package entrypoints.

The accepted public functions are:

```text
inspect_goal_bootstrap_status_readonly(runtime, goal_id)
bootstrap_goal_once(runtime, goal_id)
recover_goal_once(runtime, goal_id)
```

`inspect_goal_bootstrap_status_readonly(...)` uses the existing immutable Phase-30-style SQLite read guard and classifies one explicit Goal into the frozen decision vocabulary:

```text
ELIGIBLE
ACTIVE_PRE_PLANNER
PLANNER_RECOVERY_REQUIRED
POST_PLANNER_RESUMABLE
MATERIALIZED_NEEDS_PREPPOL
READY_FOR_MANAGER
STALE_GOAL
FAILED_PRE_PLANNER
INTERRUPTED
AMBIGUOUS_AUTHORITY
INVALID_STATE
```

The inspection path is bounded and non-creating: it does not initialize, migrate, create SQLite sidecars, publish authority, repair state, call a model, or invoke Manager.

`bootstrap_goal_once(...)` starts fresh work only from `ELIGIBLE`. A current READY bootstrap is exactly revalidated and returned idempotently. Any existing non-READY same-revision receipt requires the separate explicit recovery path rather than hidden replay or replacement authority.

`recover_goal_once(...)` resumes only the one unique exact current recoverable receipt. Pre-planner and safe `PLANNER_STARTED` recovery reuse the accepted Phase-45C boundary; deterministic post-planner states continue directly through Phase-45D finalization. Terminal or ambiguous same-revision authority remains fail closed. A later Goal revision is a distinct authority question.

Concurrent fresh calls are protected by the durable GOALBOOT ownership constraint and acceptance proves they cross the Planner boundary at most once.

## Packaging, cockpit, and Manager isolation preserved

Phase 45 adds **no fourth executable**. Packaging remains exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The existing Phase-44 `origin-forge manager status` and `origin-forge manager advance` commands are unchanged. Phase 45 does not add a bootstrap subcommand to the packaged CLI, a cockpit mutation route, a daemon, watcher, timer, poller, queue drain, or background scheduler.

The module/API-first bootstrap boundary is intentional and matches the frozen architecture: a packaged bootstrap command, if ever proposed, is a separate reviewed authority/UX change and must preserve the existing three-command packaging and cockpit guidance unless explicitly re-authorized.

## Accepted exact-head evidence

- **Phase-45 planning — PR #84:** exact head `91a3b84554c5134b3e5ebf3f43cda3cad02d04c5`; accepted normal run `31807612095` / workflow run #1288; Python 3.12 and Python 3.13 passed; merged as `1fb482a0fd108bd74eb8e8c0bb90e44b1cf38822`.
- **45A — GOALBOOT receipt foundation — PR #85:** exact head `c610bc3abb3dd167ad9955d9bb336bcc62a1db1f`; normal run `31817876253` / #1291 passed; merged as `4983a369ab6c292c37cd446ea18f17908f7fa025`.
- **45B — governed authority and PlanningInput freeze — PR #86:** exact head `3667582747b3f9c9986b613f80d9fcd632537911`; normal run `31822885546` / #1293 passed; merged as `4e0ecd6150cd529ee138934681b5cd7ba7295a44`.
- **45C — Planner checkpoint/recovery — PR #87:** accepted exact head `594a494411a37a9f2adcc42320062d4a1d14046f`; normal run `31845014956` / #1299 passed; merged as `d73b6eadb4969430e778d68d9d20729802d99a6b`.
- **45D — audit/materialization/PREPPOL finalization — PR #88:** accepted exact head `2f07330a0e8ac07de3404718f167bc30511a885e`; normal run `31847415346` / #1305 passed; merged as `a3dbd2a47cb855613ec01a591f6c4c60eeafb861`.
- **45E — operator/API boundary — PR #90:** exact head `9500252ad426ea27a3f45cc9c3aa8872eadd342b`; normal run `31849238950` / #1308 passed Python 3.12 and Python 3.13; the branch remained exactly two added files with no packaging/cockpit/Manager/docs mutation and merged SHA-guarded as `f881f47325f960a3a704d67237ce9b55f8f7f9ef`.

## Authority exclusions preserved

Phase 45 adds no:

- implicit Goal selection or fallback to another Goal;
- caller-selected Planner model/profile/runtime/provider/fallback sequence;
- caller-selected capability catalog, routing policy, dispatch catalog, adapter, contract, Task, PREP, claim, or Manager action;
- automatic replay across uncertain Planner execution;
- second plan/materialization/PREPPOL for one accepted exact current authority;
- automatic Manager invocation, dispatch claim, dispatch execution, or queue drain;
- Task outcome reinterpretation, verification truth, Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training/weight mutation, merge, release, deployment, or remote multi-user authority;
- fourth package executable, cockpit mutation command, daemon, service, timer, watcher, poller, or recurring scheduler.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact merged Phase-45E main `f881f47325f960a3a704d67237ce9b55f8f7f9ef`. The final closure head must itself pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that immutable green documentation head may be used for ready-for-review transition and SHA-guarded merge.
