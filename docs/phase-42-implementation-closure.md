# Phase 42 — Governed Manager Recovery Integration — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-42-governed-manager-recovery-integration.md`. The planning document remains the frozen authority contract; this companion records the accepted implementation, the narrow legacy-admission repair exposed by acceptance, and exact-head CI evidence.

## Final Manager recovery boundary

Phase 42 extends the existing Phase-40 one-shot Manager with one additional admitted action:

```text
RECOVER_PREPARATION
```

Only an exact current `ACTIVE` preparation receipt at `CLAIMED`, `ACTIVATED`, or `ROUTED` may enter that automatic-recovery path. Stale, invalid, ambiguous, unsupported, or otherwise non-current preparation authority remains the existing zero-action `RECOVERY_REQUIRED` path.

The final outer authority shape is:

```text
one immutable Manager admission
→ one pure oldest candidate by (created_at, task_id)
→ at most one governed lower action
→ typed Manager projection
→ unconditional STOP
```

For `RECOVER_PREPARATION`, the only lower mutation call is:

```text
recover_preparation_once(runtime, preparation_id)
```

The Manager never loops, never selects a fallback Task or PREP, never performs a second recovery edge in the same invocation, and never continues from recovery into WorkOrder finalization, Phase-34 finalization, dispatch-claim acquisition, or Phase-37 execution.

## Admission and projection implemented

Phase42A split safe exact-current pre-planner recovery from generic fail-closed recovery-required state while preserving Phase-40 ordering and selection semantics.

Phase42B integrated exactly one Phase-41 recovery call for the selected `RECOVER_PREPARATION` candidate and added typed lower-result projection:

- `RECOVERED_ACTIVATED` → `PREPARATION_RECOVERY_ADVANCED`;
- `ADOPTED_ACTIVATION_CHECKPOINT` → `PREPARATION_RECOVERY_ADVANCED`;
- `RECOVERED_ROUTED` → `PREPARATION_RECOVERY_ADVANCED`;
- `RESUMED_PLANNER_RETURNED` → `PREPARATION_RECOVERY_ADVANCED`;
- `RECOVERED_PLANNER_RETURNED` → `PREPARATION_RECOVERY_ADVANCED`;
- ambiguous/limit/invalid/rejected/not-required results preserve their frozen fail-closed Manager mappings;
- invalid lower return types or Task/PREP identity mismatches fail closed as `INVALID_STATE`.

The exact lower Phase-41 status remains visible in `lower_status`; Manager projection never becomes Task-outcome authority.

## Legacy activation-checkpoint repair

Phase42C acceptance exposed one narrow crash window omitted by the initial 42A admission taxonomy: an `ACTIVE/CLAIMED` PREP can legitimately coexist with a Task already advanced to READY when the exact Phase-35 activation mutation committed but the PREP activation checkpoint was lost.

Phase 41 already recognizes that state only when exact immutable evidence classifies it as `ADOPTABLE_ACTIVATION_CHECKPOINT`.

The accepted repair therefore does not treat generic READY state as recoverable. Manager admission upgrades only the exact Phase-41 adoptable classification to `RECOVER_PREPARATION`; generic READY transitions, stale/non-current authority, classifier failures, and other malformed states remain zero-action `RECOVERY_REQUIRED`.

## Planner-fence concurrency semantics

Phase 42 adds no planner call site. `ROUTED` recovery remains fully Phase-41-owned:

```text
ROUTED
→ durable PLANNER_STARTED compare-and-swap
→ at most one existing WorkOrder-planner call
→ exact return checkpoint when trustworthy
```

Two concurrent Manager calls may select the same oldest recovery candidate and each may invoke the one-PREP Phase-41 recovery primitive at most once. Phase-41 currentness/revision/CAS rules remain the sole mutation authority.

The accepted concurrency contract is therefore **at most one planner model call**, not a liveness guarantee that one model call must occur under every simultaneous read race. The strict immutable recovery read guard may fail closed before either caller reaches the planner boundary. In that zero-call race, both Manager calls still stop on the same oldest PREP and may not dispatch or otherwise fall through to a newer Task.

This distinction is covered separately from the sequential routed-recovery test, which proves normal one-edge progress, durable `PLANNER_STARTED` before the model boundary, and stop-at-`PLANNER_RETURNED` behavior.

## Accepted exact-head evidence

- **Phase-42 planning:** exact head `9c459321cad11854a5a9fcbff26ced6a58a9f7f4`; normal run `31734536705`; Python 3.12 and 3.13 passed; merged as `57d829047f1ba8878f71d4b99b87d6c4f45bb78d`.
- **42A — Manager recovery admission split:** exact head `6c760df403f9e8c5778919653e81f7868aa3eff3`; normal run `31736235398`; Python 3.12 and 3.13 passed; merged as `821bb480f4e8d76e401f3dd9e0731691743aee9c`.
- **42B — typed recovery projection and one-shot composition:** exact head `64896d725b83bb87182ab5d60acd81a470d49137`; normal run `31740148549`; Python 3.12 and 3.13 passed; merged as `7b55c1cc8b06e6d333acc7c5280d61625258d195`.
- **42C1 — exact legacy activation-checkpoint admission repair:** exact head `1cdb2ebb3d4f4820f1bcd422930133c7e3fd58aa`; normal run `31749195179`; Python 3.12 and 3.13 passed; merged as `5add4120c9425d50b9fcbd904ccb4a8a1f08ecfc`.
- **42C2 — adversarial Manager recovery acceptance:** exact head `7f8d2ff6a5c0d5575a66ff11bae8bdca06db3753`; run `31753948294`; after the first Python-3.13 attempt exposed only pre-existing scheduler-sensitive Phase-39/40 exact-one-call assumptions, failed-job rerun attempt 2 passed and records Python 3.12 and 3.13 successful on the unchanged head; merged as `d933f6c2b35fdd7d0b0bb0a15a19112b0ce00659`.

## Cross-phase acceptance proved

The final Phase-42 acceptance suite proves:

1. the oldest recoverable current PREP blocks every newer actionable Task and advances only one recovery edge per Manager invocation;
2. stale/non-current/generic invalid recovery state performs zero lower recovery action;
3. exact Phase-35 lost activation-checkpoint evidence may be adopted through Manager only through the existing Phase-41 classifier;
4. routed recovery persists the durable `PLANNER_STARTED` fence before any model call and stops before WorkOrder/Phase-34 finalization;
5. concurrent Manager recovery causes at most one planner model call, never falls through to the newer Task, and creates no dispatch claim or execution for that newer Task;
6. any race, identity mismatch, lower failure, or fail-closed result terminates the outer Manager call rather than selecting another candidate;
7. existing Phase-40 preparation/finalization/dispatch action ownership and Phase-41 recovery ownership remain separate and unchanged.

## Authority exclusions preserved

Phase 42 adds no:

- Manager loop, daemon, timer, watcher, polling cycle, hidden retry queue, or repeated outer advancement;
- second-Task or second-PREP fallback;
- caller-selected recovery policy, retry count, priority, Task revision/hash, route, planner/model, WorkOrder, binder, claim, or execution authority;
- direct Phase-35 activation or Phase-32 routing outside Phase-41 recovery ownership;
- planner replay after durable `PLANNER_STARTED`;
- same-call WorkOrder or Phase-34 finalization after recovery;
- same-call Phase-38 claim acquisition or Phase-37 execution invocation from recovery;
- Task success/failure/quarantine reinterpretation;
- Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training, merge, or release authority.

## Closure gate

The documentation/roadmap closure head produced from merged implementation main `d933f6c2b35fdd7d0b0bb0a15a19112b0ce00659` must itself pass the normal Python 3.12/3.13 matrix with unrelated heavyweight evidence workflows disarmed/skipped. Only that immutable green documentation head may be used for ready-for-review transition and SHA-guarded merge.
