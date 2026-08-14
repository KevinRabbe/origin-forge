# Phase 44 — Governed Manager Operator Invocation

Status: **PLANNED — architecture frozen before implementation**

Verified prerequisite `main`:

```text
d87a3c308e405ae8b3a58d85110deab5978026d9
```

Phase 44 exposes the already-accepted Phase-40 read-only Manager status and Phase-43 bounded mutating driver through the existing durable `origin-forge` control-plane CLI.

It does **not** add a fourth service/entrypoint, daemon, scheduler process, watcher, timer, polling mode, queue drain, or caller-selected production authority.

The only new operator surface is conceptually:

```text
origin-forge manager status
origin-forge manager advance
```

`manager status` performs one read-only Manager projection.

`manager advance` is one explicit human/operator authorization to invoke the existing fixed Phase-43 bounded driver **exactly once**.

---

## Why Phase 44 is required

Phases 38–42 deliberately kept Manager mutation as library/infrastructure authority while concurrency, recovery, currentness, and no-fallback semantics were still being proven.

Phase 43 then proved a finite outer composition:

```text
advance_production_manager_bounded(runtime)
```

with a fixed six-step maximum, a closed four-status continuation whitelist, fresh one-shot admission on every permitted continuation, and mandatory stop on dispatch/failure/race/quiescence.

That production primitive is now accepted, but there is no packaged operator command that can invoke it. An operator currently needs Python/library access to drive the governed Manager path.

The existing package boundary already defines:

```text
origin-forge          durable control-plane/operator commands
origin-forge-attempt  exactly one bounded coding attempt
origin-forge-cockpit  read-only local inspection
```

Phase 44 therefore extends the existing `origin-forge` control-plane command rather than creating another executable or transferring mutation authority into the read-only cockpit.

---

## Public CLI contract

Add one `manager` command group to the existing `origin-forge` parser:

```text
origin-forge manager status
origin-forge manager advance
```

The group inherits only the existing global:

```text
--project-root PATH
```

No Manager subcommand accepts any additional authority-bearing selector or budget.

### `manager status`

Calls exactly:

```text
inspect_manager_advance_status_readonly(runtime)
```

once and prints that exact immutable projection as JSON via its existing `to_dict()` surface.

It may not create, repair, migrate, checkpoint, activate, route, prepare, recover, claim, dispatch, load a model, acquire a resource lease, or call the bounded Manager driver.

### `manager advance`

Calls exactly:

```text
advance_production_manager_bounded(runtime)
```

once and prints the exact `BoundedManagerAdvanceResult.to_dict()` JSON trace.

The CLI must not call `advance_production_manager_once()` directly. Phase 43 remains the sole repeated-Manager composition authority.

One CLI invocation may therefore perform no more than the already-frozen six one-shot Manager actions, and only under the Phase-43 continuation whitelist.

---

## Forbidden Manager CLI arguments

The initial Manager CLI accepts no:

- Task ID;
- Flow ID;
- Goal ID;
- PREPPOL ID;
- PREP ID;
- route/WorkOrder/Phase-34 binding/audit ID;
- dispatch claim/execution ID;
- model role/profile/runtime/provider/endpoint;
- resource/device selector;
- priority override;
- action-kind selector;
- retry count;
- fallback selector;
- step count or `--max-steps`;
- `--repeat`;
- `--watch`;
- `--until-idle`;
- `--loop`;
- `--interval` / sleep delay;
- background/detach flag;
- automatic PREPPOL creation or recovery policy.

The absence of these arguments is part of the authority boundary, not merely a v1 UX choice.

---

## Process exit semantics

The CLI process exit code reports whether the **operator command itself** completed and returned its typed projection. It does not reinterpret production mechanics as Task success/failure.

Therefore:

```text
0 = a typed Manager status or bounded Manager result was produced and printed
```

This remains true when the bounded result stops on, for example:

- `NO_ACTIONABLE_WORK`;
- `RECOVERY_REQUIRED`;
- `PREPARATION_FAILED_PRE_PLANNER`;
- `PREPARATION_PLANNER_RECOVERY_REQUIRED`;
- `DISPATCH_RETURNED`;
- `DISPATCH_RAISED`;
- `DISPATCH_RECOVERY_REQUIRED`;
- `STEP_LIMIT_REACHED`.

Those exact stop/result values remain visible in JSON and are not collapsed into shell success/failure policy.

Ordinary parser/runtime/configuration/state errors retain the existing top-level `origin-forge` error taxonomy and exit-code behavior. Phase 44 adds no new Task-outcome-derived exit code.

---

## Project-state creation boundary

Neither Manager subcommand may call:

```text
runtime.initialize(...)
runtime.recover(...)
```

or any migration/repair/checkpoint helper.

`origin-forge init` remains the explicit project-state creation boundary.

`manager status` reuses the accepted non-creating Phase-40 immutable status path.

`manager advance` enters only the existing accepted Phase-43 authoritative writer path. Any currentness, protected-read, schema, policy, preparation, claim, execution, or model/runtime prerequisite failure must remain fail-closed through the existing lower authority.

A missing/uninitialized project must not be silently initialized by either Manager command.

---

## No new scheduling semantics

The CLI is an invocation surface only.

It may not inspect the returned trace and then decide to invoke the Manager again.

In particular:

```text
origin-forge manager advance
```

means exactly:

```text
one call to advance_production_manager_bounded(runtime)
→ print exact result
→ process exits
```

The CLI must not:

- call again after `STEP_LIMIT_REACHED`;
- call again after `DISPATCH_RETURNED` to drain another Task;
- call again after a race or claim/PREP loss;
- retry planner/model/dispatch uncertainty;
- sleep and re-check idle state;
- infer that a returned `PolicyResult` means the project needs another Manager cycle;
- select a newer Task because the oldest Task stopped the bounded driver.

A future recurring Manager service, if ever justified, requires its own explicit durable scheduling/lease/stop architecture. Phase 44 does not pre-authorize it.

---

## Read-only cockpit remains read-only

Phase 44 must not add a POST/PUT/PATCH route, button, form, script, or mutation endpoint to `origin-forge-cockpit`.

The Phase-30 cockpit remains a bounded loopback-only inspection surface.

Likewise Phase 44 does not expose Manager mutation over HTTP, plugin/tool schemas, model-callable tools, MCP, or any remote/multi-user interface.

The mutation authority is local explicit CLI invocation only.

---

## Packaging boundary

Do not add a new console script.

`pyproject.toml` must retain the existing installed entrypoint set:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Phase 44 changes only the command tree reachable under the existing `origin-forge` executable.

This keeps the operator surface aligned with the existing v0.1 contract instead of multiplying service identities.

---

## Output contract

### Status output

`manager status` prints exactly the existing `ManagerAdvanceStatusProjection.to_dict()` representation.

That projection remains mechanical/read-only and includes the accepted Manager admission/selection counts and selected authority IDs without creating any new truth model.

### Advance output

`manager advance` prints exactly the existing `BoundedManagerAdvanceResult.to_dict()` representation, including:

- ordered exact Manager one-shot step results;
- `step_count`;
- `stop_reason`;
- fixed `max_steps`;
- existing bounded-driver authority marker.

The CLI does not remove lower statuses/identities, invent a summary success field, infer Task outcome, or rewrite `DISPATCH_RETURNED` as success.

JSON goes to stdout for typed results. Existing bounded JSON error handling remains on stderr for top-level CLI errors.

---

## Implementation boundary

The expected production change is intentionally small:

```text
src/origin_forge/cli.py
```

It may add imports only for:

```text
inspect_manager_advance_status_readonly
advance_production_manager_bounded
```

plus the already imported CLI/runtime infrastructure.

The CLI file must not import Phase-35/37/38/39/41 lower mutation helpers merely to implement Manager commands.

No production change is required to:

- `production_manager_advance_once.py`;
- `production_manager_advance_bounded.py`;
- Manager admission/selection/status logic;
- preparation/recovery logic;
- dispatch claim/execution logic;
- model/resource scheduling;
- cockpit server/interface code;
- `pyproject.toml` entrypoints.

If implementation appears to require any such authority change, Phase 44 architecture must be revisited before code is merged.

---

## Acceptance contract

Phase 44 is accepted only when tests prove all of the following:

1. `origin-forge manager status` exists under the main CLI and has no authority-bearing arguments beyond global `--project-root`;
2. status calls `inspect_manager_advance_status_readonly(runtime)` exactly once, prints its exact `to_dict()` JSON, and never calls the bounded mutating driver;
3. `origin-forge manager advance` calls `advance_production_manager_bounded(runtime)` exactly once and never calls `advance_production_manager_once()` directly;
4. one typed bounded result is printed exactly and the command then exits without a second Manager invocation;
5. valid bounded results stop with process exit code 0 regardless of mechanical final status/stop reason, proving the CLI does not invent Task-outcome exit policy;
6. the command exposes no `--max-steps`, repeat/watch/until-idle/loop/interval/background, Task/PREP/claim, priority, model, resource, or action selector;
7. missing/uninitialized project state is not created by `manager status` or `manager advance`;
8. source-level inspection proves CLI Manager code imports/calls only the accepted status and bounded-driver surfaces, not lower preparation/recovery/dispatch mutation helpers;
9. `pyproject.toml` still installs exactly the existing three command entrypoints and no Manager daemon/script is added;
10. `origin-forge-cockpit` remains byte-for-byte unchanged in production code and exposes no Manager mutation route;
11. a real bounded Manager scenario invoked through `_main(["--project-root", ..., "manager", "advance"])` preserves the Phase-43 stop-at-first-dispatch/no-newer-Task-drain behavior;
12. existing Phase-43 bounded-driver tests remain unchanged and green.

All exact-head acceptance must pass the normal Python 3.12 and Python 3.13 matrix with `ResourceWarning` treated as error.

---

## Explicit non-authority

Phase 44 adds no authority for:

- daemon/background/recurring Manager execution;
- timers, polling, watchers, sleep/retry delays, cron, or work queues;
- automatic repeated CLI invocation;
- caller-selected Manager step budgets;
- processing another Task after a dispatch result in one command;
- retrying failed/stale/racing Manager actions;
- fallback to a newer Task;
- Task/PREPPOL/PREP/route/WorkOrder/binding/claim/execution/model/resource selection;
- action-kind/legacy priority/resource/cost/model scheduling changes;
- automatic PREPPOL creation/replacement;
- Task status/outcome reinterpretation;
- cockpit/HTTP/plugin/model-callable mutation surfaces;
- Artifact adoption/signing;
- Project Intelligence mutation;
- Dream promotion;
- training/checkpoint/model-profile activation;
- merge, release, deployment, push, or GitHub authority.

---

## Implementation slices

### 44A — Main CLI Manager group

Add `manager status` and `manager advance` to `origin-forge`, wire only the accepted Phase-40 status and Phase-43 bounded-driver surfaces, preserve exact JSON and exit semantics, and add focused CLI/source-boundary tests.

### 44B — Cross-phase operator acceptance

Exercise one real temporary-project Manager path through the main CLI, proving exact bounded trace output, stop-at-first-dispatch, no newer-Task drain, no implicit initialization, no repeat behavior, and unchanged cockpit/package entrypoints.

No production authority expansion beyond 44A is allowed in this slice.

### 44C — Documentation closure

Record exact accepted CI evidence, update the operator-facing documentation to include the new explicit local Manager commands and their bounded/non-recurring semantics, mark Phase 44 DONE in the canonical roadmap, run the normal Python 3.12/3.13 matrix on the immutable closure head, and merge only that exact accepted SHA.

---

## Exit condition

Phase 44 is complete when a local human/operator can explicitly run `origin-forge manager status` for one read-only Manager projection or `origin-forge manager advance` for exactly one already-governed fixed-six-step Phase-43 bounded invocation, receive the exact typed JSON evidence, and return to the shell—without any new Task selector, retry loop, daemon, queue drain, HTTP/cockpit mutation, model-callable authority, or Task-outcome semantics.
