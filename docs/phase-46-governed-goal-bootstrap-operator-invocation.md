# Phase 46 — Governed Goal Bootstrap Operator Invocation

Status: **PLANNED — architecture frozen before implementation**

Verified prerequisite `main`:

```text
575aae1dcb0b1e9f19e39858619ce81eb0130480
```

Phase 46 exposes the already-accepted Phase-45 Goal-bootstrap status/bootstrap/recovery APIs through the existing durable `origin-forge` control-plane CLI.

It does **not** add a fourth executable, new bootstrap authority, automatic Manager invocation, background scheduling, hidden Planner replay, cockpit mutation, or caller-selected model/capability/Task authority.

The only new operator surface is conceptually:

```text
origin-forge goal bootstrap status  <GOAL-ID>
origin-forge goal bootstrap start   <GOAL-ID>
origin-forge goal bootstrap recover <GOAL-ID>
```

`status` performs one bounded non-creating Phase-45 status projection.

`start` is one explicit operator authorization to invoke the existing Phase-45 fresh-bootstrap API exactly once for the supplied Goal identity.

`recover` is one explicit operator authorization to invoke the existing Phase-45 recovery API exactly once for the supplied Goal identity.

All three commands stop at the Phase-45 GOALBOOT boundary. They never invoke Manager.

---

## Why Phase 46 is required

Phase 45 deliberately implemented the bootstrap authority and recovery semantics as a module/API-first boundary:

```text
inspect_goal_bootstrap_status_readonly(runtime, goal_id)
bootstrap_goal_once(runtime, goal_id)
recover_goal_once(runtime, goal_id)
```

The Phase-45 architecture explicitly deferred any packaged operator command to a later separately reviewed surface and required such a command to preserve the existing three-command package guidance and accept no authority selector beyond the Goal identity.

That deferred boundary is now the narrow next step. A local operator should not need ad hoc Python code merely to inspect, start, or explicitly recover the already-governed bootstrap primitive.

Phase 46 therefore adds only CLI invocation over accepted Phase-45 APIs. It does not change GOALBOOT receipt semantics, Planner fencing, audit/materialization, PREPPOL publication, currentness classification, recovery eligibility, or Manager behavior.

---

## Existing package boundary remains authoritative

Packaging remains exactly:

```text
origin-forge          durable control-plane/operator commands
origin-forge-attempt  exactly one bounded coding attempt
origin-forge-cockpit  read-only local inspection
```

Phase 46 extends only the command tree reachable through the existing `origin-forge` executable.

Do not add or rename a console script in `pyproject.toml`.

The read-only cockpit remains a separate non-mutating surface and receives no Goal-bootstrap mutation route.

---

## Public CLI contract

Add one nested bootstrap group under the existing `goal` command:

```text
origin-forge goal bootstrap status  GOAL-ID
origin-forge goal bootstrap start   GOAL-ID
origin-forge goal bootstrap recover GOAL-ID
```

The group inherits only the existing global:

```text
--project-root PATH
```

Each bootstrap subcommand accepts exactly one authority-bearing argument:

```text
GOAL-ID
```

The CLI must not accept a Goal revision/hash override. Phase 45 derives the exact current revision/hash from canonical protected state.

### `goal bootstrap status`

Calls exactly:

```text
inspect_goal_bootstrap_status_readonly(runtime, goal_id)
```

once and prints that exact `GoalBootstrapStatusProjection.to_dict()` JSON representation.

It may not initialize, migrate, checkpoint, repair, acquire GOALBOOT ownership, publish authority, call a model, audit/materialize a plan, publish PREPPOL, or call Manager.

### `goal bootstrap start`

Calls exactly:

```text
bootstrap_goal_once(runtime, goal_id)
```

once and prints the exact `GoalBootstrapOperatorResult.to_dict()` JSON representation.

The CLI must **not** perform a separate status preflight before calling `bootstrap_goal_once(...)`. The accepted Phase-45 API owns fresh-vs-existing currentness classification, idempotent READY revalidation, durable ownership races, Planner fencing, and fail-closed authority decisions.

The CLI must not call lower Phase-45 acquisition/planner/finalization helpers directly.

### `goal bootstrap recover`

Calls exactly:

```text
recover_goal_once(runtime, goal_id)
```

once and prints the exact `GoalBootstrapOperatorResult.to_dict()` JSON representation.

The CLI must **not** perform a separate status preflight before calling `recover_goal_once(...)`. Phase 45 remains the sole authority for determining whether the one unique exact current receipt is safely recoverable.

The CLI must not acquire a replacement GOALBOOT, replay uncertain Planner work, or call lower recovery/finalization helpers directly.

---

## No bootstrap-to-Manager composition

A successful Phase-46 `start` or `recover` command may return a GOALBOOT result whose durable receipt is READY.

That means only:

```text
exact current Goal revision
→ exact accepted plan/materialization
→ exact current PREPPOL
→ ready for existing Manager admission
```

It does **not** mean:

- the Goal is complete;
- any Task ran;
- any Task passed verification;
- a dispatch claim/execution occurred;
- an Artifact was adopted/signed;
- Manager was invoked;
- code was merged or released.

Phase 46 must not inspect a READY result and automatically call:

```text
advance_production_manager_bounded(runtime)
```

or any lower Manager/dispatch primitive.

Production advancement remains a separate explicit operator authorization:

```text
origin-forge manager advance
```

The separation between bootstrap authorization and Manager authorization is part of the authority boundary.

---

## Forbidden bootstrap CLI arguments

The Phase-46 bootstrap group accepts no:

- Goal revision/hash override;
- Flow ID;
- Task ID;
- Run ID;
- PLINPUT / PLPROP / PLAUD / PLMAT ID;
- CAPCAT / CAPPOL / DISPCAT ID;
- PREPPOL ID;
- PREP ID;
- WorkOrder / binding / audit ID;
- dispatch claim/execution ID;
- capability list or capability override;
- adapter/contract/binder selector;
- model role/profile/model ID/runtime/provider/endpoint selector;
- resource/device selector;
- Planner seed/temperature/token/timeout override;
- retry count or fallback selector;
- bootstrap-history selector;
- Manager action selector;
- `--auto-manager` / `--advance` chaining flag;
- `--repeat`;
- `--watch`;
- `--until-ready`;
- `--until-idle`;
- `--loop`;
- `--interval` / sleep delay;
- background/detach flag;
- automatic recovery/replay policy.

The absence of these arguments is an authority property, not merely a v1 UX preference.

---

## Exact current Goal authority only

The CLI supplies only the explicit Goal ID to Phase 45.

It may not:

- select the first/oldest/newest OPEN Goal;
- infer a Goal from a Task/Flow;
- fall back to another Goal when the requested Goal is blocked/stale/invalid;
- expose a historical receipt selector;
- permit the caller to pin an old Goal revision/hash as current authority;
- replace a same-revision terminal/ambiguous receipt;
- reinterpret a later Goal revision as recovery of an older receipt.

The Phase-45 exact current Goal revision/hash and same-revision authority rules remain unchanged.

---

## Read-only status semantics

`goal bootstrap status` prints the accepted Phase-45 decision vocabulary unchanged:

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

The CLI must not collapse these values into a new READY/NOT_READY truth model.

A typed status projection is an inspection result and returns process exit code `0`, including projections such as `STALE_GOAL`, `INTERRUPTED`, `AMBIGUOUS_AUTHORITY`, or `INVALID_STATE`, because the operator command successfully produced the exact requested status evidence.

Input/runtime failures that prevent the Phase-45 status projection from being produced remain bounded CLI errors.

---

## Start/recovery result and exit semantics

A successful `start` or `recover` call prints exactly the existing `GoalBootstrapOperatorResult.to_dict()` representation and exits `0`.

The CLI does not invent Goal/Task outcome semantics from:

```text
READY
ALREADY_READY
```

Those values mean the bootstrap operator call produced/revalidated Phase-45 READY authority; they are not production completion or verification truth.

Phase 45 intentionally represents a disallowed start/recovery operation as `GoalBootstrapOperatorBlocked(decision, detail)` and other unavailable/invalid bootstrap execution as `GoalBootstrapOperatorError`.

Phase 46 must add bounded top-level CLI handling so these expected operator conditions do not escape as raw tracebacks:

```text
GoalBootstrapOperatorBlocked
  -> JSON error including exact decision + bounded message
  -> reuse existing INVALID_STATE exit category (4)

GoalBootstrapOperatorError
  -> bounded JSON bootstrap-operator error
  -> reuse existing INVARIANT_VIOLATION/state-unavailable exit category (5)
```

Phase 46 adds no Task-outcome-derived exit code and no new shell meaning for Goal completion.

The exact error labels may be implementation constants, but acceptance must freeze them before merge and prove no traceback leakage for ordinary bootstrap operator errors.

---

## Project-state creation boundary

None of the three bootstrap subcommands may call:

```text
runtime.initialize(...)
runtime.recover(...)
```

or any migration/checkpoint/repair helper.

`origin-forge init` remains the explicit project-state creation boundary.

`goal bootstrap status` reuses the accepted Phase-45 immutable/non-creating status path.

`goal bootstrap start` and `recover` enter only the accepted Phase-45 authoritative writer/recovery APIs. Missing/stale/partial/actively-written state remains fail closed through those existing boundaries.

---

## No new Planner or recovery semantics

The CLI is an invocation surface only.

It may not inspect a blocked/result status and decide to call another Phase-45 API in the same command.

In particular:

```text
start
→ one bootstrap_goal_once(...)
→ print exact result OR bounded exact error
→ exit
```

and:

```text
recover
→ one recover_goal_once(...)
→ print exact result OR bounded exact error
→ exit
```

The CLI must not:

- convert `start` into automatic `recover` when existing state is found;
- convert `recover` into a fresh `start` when no receipt exists;
- retry a race or blocked decision by re-entering the API;
- replay uncertain `PLANNER_STARTED` work;
- call status then mutate based on the CLI's own interpretation;
- invoke Manager after READY;
- sleep, poll, watch, or repeat until READY.

Phase-45 API semantics remain authoritative and independently testable.

---

## Read-only cockpit remains read-only

Phase 46 must not add a POST/PUT/PATCH route, button, form, script, mutation endpoint, or bootstrap action to `origin-forge-cockpit`.

Likewise it does not expose bootstrap mutation through HTTP, plugin/tool schemas, model-callable tools, MCP, remote RPC, or multi-user interfaces.

The mutation authority is local explicit `origin-forge` invocation only.

---

## Packaging boundary

Do not add a new console script.

`pyproject.toml` must retain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The intended production mutation is limited to the existing main CLI command tree plus focused tests and later operator documentation.

If implementation appears to require a new executable, daemon, service, packaging entrypoint, or cockpit route, Phase 46 architecture must be revisited before code is merged.

---

## Output contract

### Status output

Print exactly:

```text
GoalBootstrapStatusProjection.to_dict()
```

No CLI-owned recomputation, summary truth field, or filtering of Phase-45 decision/receipt evidence.

### Start/recover output

Print exactly:

```text
GoalBootstrapOperatorResult.to_dict()
```

No CLI-owned Goal completion field, Manager-readiness reinterpretation, Task status, or synthetic next action.

JSON typed results go to stdout. Ordinary bounded CLI errors go to stderr through the top-level CLI error boundary.

---

## Implementation boundary

The expected production change is intentionally small:

```text
src/origin_forge/cli.py
```

The CLI may add imports only for the accepted Phase-45 operator surface and errors:

```text
inspect_goal_bootstrap_status_readonly
bootstrap_goal_once
recover_goal_once
GoalBootstrapOperatorBlocked
GoalBootstrapOperatorError
```

plus already-existing CLI/runtime infrastructure.

The Phase-46 CLI implementation must not newly import Phase-45 lower authority helpers such as:

- `acquire_current_goal_bootstrap`;
- `advance_goal_bootstrap_planner`;
- `finalize_goal_bootstrap`;
- GOALBOOT checkpoint/store mutation helpers;
- Phase-31 audit/materializer helpers;
- Phase-39 PREPPOL publication helpers.

Existing Phase-44 Manager imports in `cli.py` remain unchanged and are not part of Phase-46 bootstrap ownership.

No production change is expected to:

- `production_goal_bootstrap_operator.py`;
- `production_goal_bootstrap_authority.py`;
- `production_goal_bootstrap_planner.py`;
- `production_goal_bootstrap_finalize.py`;
- GOALBOOT schema/store/models;
- production Manager/dispatch/preparation modules;
- cockpit code;
- `pyproject.toml` entrypoints.

If the public Phase-45 API proves insufficient for the CLI without changing those authority-bearing modules, implementation must stop and revisit the architecture rather than widen Phase 46 opportunistically.

---

## Acceptance contract

Phase 46 is accepted only when tests prove all of the following:

1. the existing `origin-forge goal` group gains exactly one nested `bootstrap` group with `status`, `start`, and `recover`;
2. each bootstrap command requires exactly one explicit Goal ID and exposes no authority-bearing selector beyond global `--project-root`;
3. `status` calls `inspect_goal_bootstrap_status_readonly(runtime, goal_id)` exactly once, prints its exact `.to_dict()` JSON, and never calls bootstrap/recovery/Manager mutation;
4. `start` calls `bootstrap_goal_once(runtime, goal_id)` exactly once, performs no separate status preflight, and never calls `recover_goal_once(...)` or Manager automatically;
5. `recover` calls `recover_goal_once(runtime, goal_id)` exactly once, performs no separate status preflight, and never calls `bootstrap_goal_once(...)` or Manager automatically;
6. typed status/start/recover results print unchanged and exit `0` without Goal/Task outcome reinterpretation;
7. ordinary `GoalBootstrapOperatorBlocked` conditions produce bounded JSON on stderr with the exact Phase-45 decision and no traceback, using the existing invalid-state exit category;
8. ordinary `GoalBootstrapOperatorError` conditions produce bounded JSON on stderr and no traceback, using the existing invariant/state-unavailable exit category;
9. fresh `start` against existing recoverable non-READY state does not silently recover; explicit `recover` remains required;
10. `recover` against ELIGIBLE/terminal/stale/ambiguous authority does not silently start replacement work;
11. a current READY exact Goal is returned idempotently through `start` without a second Planner call/materialization/PREPPOL;
12. a successful real temporary-project CLI bootstrap path reaches READY with zero dispatch claims/executions and zero Manager calls;
13. a real explicit CLI recovery path resumes one safe recoverable receipt and reaches READY without acquiring replacement authority;
14. a PLANNER uncertainty/recovery-required case proves the CLI does not replay the Planner or convert recovery into fresh bootstrap;
15. source-level inspection proves Phase-46 CLI code imports/calls only the accepted Phase-45 operator surface, not lower GOALBOOT/planning/materialization/PREPPOL mutation helpers;
16. `pyproject.toml` still installs exactly the existing three command entrypoints;
17. cockpit production code remains unchanged and contains no bootstrap mutation route;
18. existing Phase-45 operator tests remain unchanged and green.

All exact-head acceptance must pass the normal Python 3.12 and Python 3.13 matrix with `ResourceWarning` treated as error. Heavy external model downloads are not part of the normal merge gate; deterministic/fake governed model runtime boundaries may be used for bootstrap call-count/recovery acceptance exactly as in Phase 45.

---

## Explicit non-authority

Phase 46 adds no authority for:

- automatic Goal selection or cross-Goal fallback;
- caller-selected Goal revision/hash;
- automatic bootstrap of all OPEN/ACTIVE Goals;
- automatic recovery after a blocked fresh start;
- automatic fresh bootstrap after a blocked recovery;
- automatic Planner replay after uncertainty;
- multiple Planner calls in one operator invocation;
- model/profile/runtime/provider/endpoint/resource selection;
- capability/routing/dispatch/adapter/contract/binder selection;
- Task/Flow/PREP/claim/execution selection;
- automatic Manager invocation or bootstrap→Manager chaining;
- repeated Manager/bootstrap loops, daemons, timers, polling, watchers, sleeps, cron, queues, or background execution;
- Task outcome/verification reinterpretation;
- Artifact adoption/signing;
- Project Intelligence or Design Bible mutation;
- Dream promotion;
- training/checkpoint/model activation;
- generic tool execution;
- cockpit/HTTP/plugin/model-callable mutation;
- merge, release, deployment, push, or GitHub authority.

---

## Implementation slices

### 46A — Main CLI Goal-bootstrap group

Add `goal bootstrap status|start|recover` to `origin-forge`, wire only the accepted Phase-45 status/bootstrap/recovery APIs, preserve exact JSON/result semantics, add bounded Phase-45 operator error handling, and add focused parser/delegation/source-boundary tests.

No lower bootstrap, Planner, materialization, PREPPOL, Manager, packaging, or cockpit authority change is allowed.

### 46B — Cross-phase operator acceptance

Exercise real temporary-project CLI paths proving fresh bootstrap to READY, explicit safe recovery to READY, current READY idempotence, blocked start-vs-recovery separation, no uncertain Planner replay, no replacement GOALBOOT authority, zero Manager calls, zero dispatch claims/executions, and unchanged package/cockpit boundaries.

No production authority expansion beyond the 46A CLI surface is allowed in this slice.

### 46C — Documentation / roadmap closure

Record exact accepted CI evidence, update the living operator guide to document the packaged Goal-bootstrap commands and their explicit start/recover/Manager separation, mark Phase 46 DONE in the canonical roadmap, run the normal Python 3.12/3.13 matrix on the immutable closure head, and merge only that exact accepted SHA.

---

## Exit condition

Phase 46 is complete when a local human/operator can explicitly run:

```text
origin-forge goal bootstrap status  GOAL-ID
origin-forge goal bootstrap start   GOAL-ID
origin-forge goal bootstrap recover GOAL-ID
```

and receive the exact accepted Phase-45 typed JSON evidence while preserving every Phase-45 currentness/no-replay/recovery rule, using only the explicit Goal identity and existing protected configuration, with no new executable, status-driven CLI decision logic, hidden fallback/retry, automatic Manager call, cockpit mutation, background scheduling, or Goal/Task completion semantics.

The final immutable implementation/documentation head must pass the normal Python 3.12 and Python 3.13 matrix with unrelated heavyweight external evidence workflows disarmed/skipped before ready-for-review transition and SHA-guarded merge.
