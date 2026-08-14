# Phase 44 — Governed Manager Operator Invocation — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-44-governed-manager-operator-invocation.md`. The planning document remains the frozen authority contract; this companion records the accepted main-CLI Manager surface, cross-phase operator acceptance, packaging/cockpit isolation, and exact-head CI evidence.

## Final operator boundary

Phase 44 exposes the already accepted Manager surfaces through the existing main `origin-forge` control-plane CLI only:

```text
origin-forge manager status
origin-forge manager advance
```

The commands reuse the existing global `--project-root` option. No fourth executable, daemon, service, watcher, or scheduler entrypoint was added.

`manager status` calls exactly:

```text
inspect_manager_advance_status_readonly(runtime)
```

once and prints that projection's exact `.to_dict()` JSON.

`manager advance` calls exactly:

```text
advance_production_manager_bounded(runtime)
```

once and prints that bounded driver's exact `.to_dict()` JSON. The CLI performs no status preflight and does not call `advance_production_manager_once` or any lower preparation, recovery, finalization, claim, dispatch, model, resource, or execution helper directly.

## Deliberately absent operator authority

The Manager CLI group exposes no:

- caller-selected `--max-steps` or other budget override;
- `--repeat`, `--watch`, `--until-idle`, `--loop`, `--interval`, or background mode;
- Task, PREP, claim, priority, action, model, resource, policy, adapter, or execution selector;
- automatic initialization, schema migration, recovery, retry, queue drain, or fallback selection;
- HTTP mutation or cockpit mutation route;
- separate Manager executable or background service.

The accepted Phase-43 fixed six-step maximum and continuation whitelist therefore remain the sole bounded-driver policy.

## Process and result semantics

A successfully parsed Manager command that returns a typed Manager result exits with process code `0`, including quiescent, blocked, fail-closed, recovery-required, dispatch-raised, and hard-step-limit Manager results.

This process status means the operator command executed and emitted a typed result. It does **not** reinterpret Manager mechanics as Task success/failure, PolicyOutcome truth, verification truth, merge authority, or release authority.

Uninitialized or otherwise unreadable durable state remains fail closed through the existing lower Manager read/admission boundary. Phase 44 does not silently create `.origin-forge`, initialize a project, migrate a database, checkpoint SQLite, or repair partial state.

## Accepted main-CLI implementation

The accepted implementation changes only the existing main CLI surface:

```text
src/origin_forge/cli.py
```

The new parser group contains only `status` and `advance`. Source-level acceptance proves the main CLI imports Manager functionality only from:

```text
production_manager_advance_status
production_manager_advance_bounded
```

and contains no direct one-shot or lower Manager mutation call.

The first implementation head `06dbc68702c9a941b7b138ab41c7b5465f993853` was not accepted: both interpreters deterministically failed one new test because its synthetic status fixture named nonexistent `ManagerAdvanceSelectionStatus.NONE_AVAILABLE`. Production code was not implicated. The fixture was corrected in one test-only line to the real idle status `NO_ACTIONABLE_WORK`, producing the accepted head below and a completely fresh exact-head matrix.

## Cross-phase operator acceptance proved

The Phase-44B acceptance suite adds no production code and proves:

1. a real initialized temporary project can be advanced through `_main(["--project-root", ..., "manager", "advance"])` while the CLI invokes the accepted Phase-43 bounded driver exactly once;
2. the emitted stdout JSON exactly equals the bounded driver's own `.to_dict()` projection;
3. a normal fresh lifecycle produces the ordered four-step trace `PREPARATION_PLANNER_RETURNED → WORK_ORDER_AUDITED → PHASE34_READY → DISPATCH_RETURNED` and stops on that first dispatch result;
4. exactly one planner model call and one dispatch occur for that path;
5. every trace step remains pinned to the same oldest Task, and the final claim/execution identities match the real downstream dispatch result;
6. a newer Task remains QUEUED at revision zero with no dispatch claim or execution, proving the operator command is not a queue drain;
7. `manager status` and `manager advance` on an uninitialized project emit typed fail-closed JSON with process code `0` while creating no `.origin-forge` state;
8. package scripts remain exactly `origin-forge`, `origin-forge-attempt`, and `origin-forge-cockpit`;
9. the cockpit remains a separate read-only `snapshot` / `serve` surface and rejects Manager commands.

Existing Phase-40/41/42/43 scheduling, recovery, planner-fence, claim, execution-ownership, and bounded continuation semantics remain unchanged.

## Operator guide update

The living current-main operator guide, `docs/operator-guide.md`, documents the explicit Manager commands and their limits:

```text
origin-forge --project-root /path/to/project manager status
origin-forge --project-root /path/to/project manager advance
```

It states that `status` is the non-creating Manager admission/selection projection, `advance` performs one invocation of the fixed Phase-43 bounded driver, a typed Manager result is not Task outcome truth, and neither command provides initialization, repetition, queue draining, background scheduling, or caller-selected authority/budget arguments.

The historical `docs/v0.1-operator-guide.md` deliberately excludes these post-v0.1 commands. The cockpit remains the stricter read-only inspection surface and receives no Manager mutation command.

## Accepted exact-head evidence

- **Phase-44 planning — PR #76:** exact head `a48afae9835051ab82fce74846cbb23bd9555649`; normal run `31766870026`; Python 3.12 and Python 3.13 both passed on attempt 1; merged as `5bee0650f5f023aefd86191d8a588dab81f43bd6`.
- **44A — main CLI Manager group — PR #77:** accepted corrected exact head `8b089a73250343644ff70cc6cfd2eedb446f0fe4`; fresh normal run `31770262537`; Python 3.12 and Python 3.13 both passed on attempt 1; merged as `6d2bd224e7202bbdde221bc4d373ddbfb942a270`.
- **44B — cross-phase operator acceptance — PR #78:** exact head `8166f33a48ac12e817fa521006f98ec5cd3b13ce`; normal run `31770691249`; Python 3.12 and Python 3.13 both passed on attempt 1; merged as `891013efb9f95c36bee8850d5ce5ed0a2c4c72cb`.

## Authority exclusions preserved

Phase 44 adds no:

- fourth executable, daemon, service, timer, watcher, poller, or recurring scheduler;
- caller/model/Task/PREP-selected step budget;
- action-kind priority or change to canonical `(Task.created_at, Task.id)` ordering;
- direct lower preparation, recovery, finalization, claim, dispatch, execution, model, resource, or policy authority from the CLI;
- immediate retry after race loss, stale authority, planner uncertainty, dispatch failure, or recovery-required state;
- processing of another Task after the first dispatch result in one bounded-driver invocation;
- Task outcome reinterpretation from Manager or `PolicyResult` mechanics;
- HTTP/cockpit mutation route;
- Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training/weight mutation, merge, release, deployment, or remote multi-user control authority.

## Closure gate

This documentation/roadmap closure branch starts from merged implementation main `891013efb9f95c36bee8850d5ce5ed0a2c4c72cb`. The final closure head must itself pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that immutable green documentation head may be used for ready-for-review transition and SHA-guarded merge.
