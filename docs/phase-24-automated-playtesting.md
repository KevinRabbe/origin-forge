# Phase 24 — Automated Playtesting

Status: **IN PROGRESS — governed v1 substrate implemented; final roadmap/closure pending**

Phase 24 adds bounded synthetic-player execution and telemetry without creating a generic OS-input or production-verification path.

## Core rule

```text
frozen semantic action plan
        ↓
preconfigured cooperative harness
        ↓
bounded typed telemetry + logs
        ↓
independent deterministic analysis
        ↓
durable playtest evidence

playtest evidence != production Task authority
```

## Governed v1 surface

Phase 24 v1 provides:

- infrastructure-owned `PLAYSCEN-*` scenario IDs, `PLAY-*` session IDs and `PLAYWS-*` workspaces;
- immutable content-addressed scenarios;
- exact harness ID/version/hash and target ID/version binding;
- semantic controls rather than raw OS keycodes:
  - `SET_AXIS`
  - `PRESS`
  - `RELEASE`
  - `WAIT`
- an exact per-scenario control whitelist;
- bounded action count, timeline, durations, values, logs and session duration;
- typed telemetry for:
  - deaths;
  - encounter start/end and derived duration;
  - damage dealt/taken;
  - resource shortages;
  - soft locks;
  - pathfinding failures;
  - progression markers and derived progression stalls;
- exact scenario-bound telemetry with contiguous event sequencing and bounded timestamps;
- deterministic analysis retaining incomplete/unmatched encounters rather than silently normalizing them;
- a real cooperative harness process boundary using an adapter-owned executable and fixed argv;
- no shell, no caller-supplied environment, no model-supplied script, no caller-selected executable, and no raw keyboard/mouse command surface;
- concurrent bounded stdout/stderr capture with process-group termination on timeout/overflow/cleanup;
- strict telemetry JSON schema with unknown-field rejection and pre-read byte bounds;
- infrastructure-owned synthetic `FAILED`/`TIMEOUT` telemetry when an abnormal process cannot emit final telemetry;
- durable scenario/telemetry/summary/log Artifacts and a `playtest-structure` Run Verification;
- read-only operator inspection through `playtest_cli`;
- explicit evidence fields proving that production Task verification, semantic game-quality authority, canonical adoption, signing, merge and release remain outside this service.

## Semantic action boundary

The model/caller does not receive a generic input injector. A trusted target-specific harness owns the translation from frozen semantic controls to application behavior.

For example:

```text
SET_AXIS move-x 1000
PRESS attack 100 ms
WAIT 500 ms
RELEASE move-x
```

is a bounded domain contract. It is not permission to choose a process, run shell commands, inject arbitrary JavaScript/Python, send raw system keycodes, move a host mouse, or control unrelated windows.

Each scenario carries an exact `allowed_controls` set. An action naming any other control is rejected before execution.

A future native keyboard/mouse/controller backend must be separately governed and proven. It is not implied by the v1 cooperative harness.

## Harness authority

`CooperativePlaytestHarness` is constructed with trusted infrastructure-owned configuration:

- executable path;
- exact executable SHA-256;
- harness ID/version;
- target ID/version;
- fixed argv;
- exact playtest workspace root.

The scenario can bind those values but cannot replace them.

The process runs with:

- `shell=False`;
- stdin disabled;
- a minimal infrastructure-owned environment;
- a new POSIX process group;
- bounded stdout/stderr;
- a hard scenario duration;
- process-group cleanup after timeout, overflow, or direct-child exit.

The harness receives only:

- the exact canonical scenario JSON path;
- scenario/session identity hashes;
- the exact telemetry output path.

## Runtime outcome vs playtest infrastructure outcome

A failed game session is still useful playtest evidence.

```text
playtest infrastructure succeeded + game/harness outcome FAILED
!=
playtest infrastructure failed
```

If the harness exits nonzero before writing telemetry, Origin Forge creates an infrastructure-owned empty `FAILED` telemetry record bound to the exact scenario. On timeout, Origin Forge creates an exact empty `TIMEOUT` telemetry record.

A zero exit is stronger: it must provide valid exact-bound `COMPLETED` telemetry. Zero exit without telemetry fails closed.

If telemetry exists, its declared outcome must agree with the process state. Unknown fields, identity drift, oversized telemetry, malformed events, symlinks, workspace escape, log overflow, or content drift are infrastructure failures rather than game-quality findings.

## Deterministic telemetry analysis

`analyze_playtest()` derives only mechanical metrics supported by the event stream:

- death count;
- completed encounter count;
- incomplete encounter IDs;
- unmatched encounter-end IDs;
- total/max encounter duration;
- damage dealt/taken totals;
- resource-shortage count;
- soft-lock count;
- pathfinding-failure count;
- progression event count;
- maximum progression gap;
- progression-stall flag against the frozen scenario threshold.

It does not decide whether the game is fun, balanced, shippable, or semantically correct. Those are separate policy/design judgments.

A duplicate active start for the same encounter fails closed because the event stream is structurally ambiguous. Incomplete encounters and unmatched ends are preserved as evidence because they may themselves indicate runtime problems.

## Durable evidence

`PlaytestService` requires an already-`RUNNING` production Task and creates a separate `PLAYTESTER` Run.

It independently revalidates the exact returned workspace, scenario bytes, telemetry binding and log hashes/sizes, then persists:

- `PLAYTEST_SCENARIO`
- `PLAYTEST_TELEMETRY`
- `PLAYTEST_SUMMARY`
- `PLAYTEST_STDOUT_LOG`
- `PLAYTEST_STDERR_LOG`
- one `playtest-structure` Run Verification

The service can finish its `PLAYTESTER` Run as `SUCCEEDED` while telemetry outcome is `FAILED` or `TIMEOUT`. That means the synthetic-player observation completed and produced governed evidence; it does not mean the game passed.

The production Task remains `RUNNING`, receives no Task Verification from this service, and is not automatically failed or completed.

## Read-only operator inspection

```text
python -m origin_forge.playtest_cli status
python -m origin_forge.playtest_cli sessions
python -m origin_forge.playtest_cli run-show <RUN-ID>
python -m origin_forge.playtest_cli artifact-show <ART-ID>
```

The CLI has no play/run execution command, raw input control, scenario mutation, Task mutation, adoption, signing, merge or release surface.

## Relationship to Phase 23

Phase 23 answers: **what happened while an application ran?**

Phase 24 answers: **what bounded synthetic player actions were attempted, and what typed gameplay telemetry resulted?**

The first Phase-24 harness does not require a Phase-23 visual capture session to be nested inside every playtest. The two evidence layers can be composed later by policy when screenshots/video/log/runtime metrics are useful alongside gameplay telemetry. Keeping them separate preserves replaceable backends and clearer authority boundaries.

## Explicit exclusions in v1

Not implemented or authorized:

- generic host keyboard/mouse/controller injection;
- arbitrary executable or shell selection;
- caller/model-supplied Python/JavaScript or automation scripts;
- GUI-coordinate automation;
- network or host-filesystem sandbox claims for a trusted native harness;
- automatic model-driven exploration loops;
- semantic vision/game-quality grading;
- automatic balancing or tuning mutations;
- automatic retry/repair after telemetry findings;
- production Task verification/completion;
- asset/config adoption;
- provenance signing;
- merge/release authority;
- Phase-25 simulation.

## Phase-24 v1 exit condition

Phase 24 v1 is complete when one immutable repository head proves on the supported Python matrix that Origin Forge can:

1. freeze a bounded semantic action scenario with exact harness/target identity and an explicit control whitelist;
2. run a real preconfigured cooperative harness with fixed executable/argv and no shell/caller environment authority;
3. bound logs/session duration and clean the process group;
4. require exact valid telemetry on normal completion while preserving nonzero/timeout outcomes as scenario-bound synthetic evidence when final target telemetry is absent;
5. independently bind and validate typed telemetry covering deaths, encounters, damage, shortages, soft locks, pathfinding failures and progression;
6. derive deterministic encounter/progression/gameplay metrics without semantic game-quality authority;
7. persist exact scenario/telemetry/summary/log lineage through a separate `PLAYTESTER` Run;
8. expose that evidence through a read-only operator surface; and
9. prove none of those paths verifies/completes the production Task, adopts assets/config, signs provenance, merges or releases.

The regression suite includes real local subprocess coverage for successful telemetry, nonzero exit without telemetry, timeout without telemetry, success-without-telemetry rejection, schema-extension rejection and log overflow, plus a real harness → durable service → lineage round trip.

Remaining closure work is canonical roadmap synchronization and one final exact-head Python 3.12/3.13 matrix after the documentation is frozen.

Phase 25 remains separate. Automated playtesting observes executed gameplay; simulation evaluates cheaper abstract system models before or without full runtime execution.
