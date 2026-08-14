# Phase 46 — Governed Goal Bootstrap Operator Invocation — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-46-governed-goal-bootstrap-operator-invocation.md`. Phase 46 exposes the already-accepted Phase-45 Goal-bootstrap status/start/recovery authority through the existing `origin-forge` control-plane CLI without creating new bootstrap semantics, new package entrypoints, automatic Manager chaining, cockpit mutation, or background autonomy.

## Final operator surface

The accepted packaged commands are:

```text
origin-forge --project-root /path/to/project goal bootstrap status  GOAL-ID
origin-forge --project-root /path/to/project goal bootstrap start   GOAL-ID
origin-forge --project-root /path/to/project goal bootstrap recover GOAL-ID
```

Each command accepts one explicit canonical Goal identity. There is no implicit Goal selection or fallback and no Goal-revision/hash, Flow, Task, PREP, capability, adapter, model, runtime, resource, Planner, or Manager selector.

Packaging remains exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

No fourth executable or cockpit mutation route was added.

## 46A — narrow CLI delegation boundary

The existing `origin-forge goal` command tree gained one nested `bootstrap` group with three commands only:

- `status` delegates exactly once to `inspect_goal_bootstrap_status_readonly(runtime, goal_id)`;
- `start` delegates exactly once to `bootstrap_goal_once(runtime, goal_id)`;
- `recover` delegates exactly once to `recover_goal_once(runtime, goal_id)`.

The CLI prints the accepted Phase-45 `.to_dict()` representation unchanged. It does not derive a second readiness model, Goal-completion result, Task outcome, or next action.

`start` performs no separate status preflight and never automatically switches to recovery. `recover` performs no separate status preflight and never automatically switches to fresh bootstrap. Neither command retries, polls, watches, sleeps, loops, or invokes Manager after READY.

The CLI imports only the accepted Phase-45 operator surface and errors. It does not call lower GOALBOOT acquisition/checkpoint, Planner, audit, materialization, PREPPOL, Manager, preparation, claim, or dispatch helpers.

Expected Phase-45 operator failures are bounded at the existing top-level CLI error boundary:

```text
GoalBootstrapOperatorBlocked
  -> GOAL_BOOTSTRAP_BLOCKED + exact decision/message
  -> exit 4

GoalBootstrapOperatorError
  -> GOAL_BOOTSTRAP_ERROR + bounded message
  -> exit 5
```

Ordinary bootstrap operator failures therefore do not escape as raw tracebacks. Typed successful status/start/recover results exit `0`; this means the operator command successfully produced the requested Phase-45 mechanics/evidence, not that a Goal or Task is complete.

## 46B — cross-phase operator acceptance

Acceptance exercises the real temporary-project CLI composition over durable Phase-45 state while substituting only the deterministic Planner/model-runtime seam where an external model process would otherwise be required.

The accepted scenarios prove:

- a fresh CLI `start` reaches GOALBOOT `READY` through the existing Phase-45 audit/materialization/PREPPOL path;
- a second explicit `start` returns `ALREADY_READY` for the same GOALBOOT with no second Planner call or materialization;
- `status` reports `READY_FOR_MANAGER` for that exact receipt;
- an existing active same-revision GOALBOOT blocks fresh `start` with `ACTIVE_PRE_PLANNER` rather than silently recovering or replacing authority;
- explicit `recover` resumes that exact existing receipt and reaches READY;
- `recover` on an `ELIGIBLE` Goal fails closed instead of creating replacement authority;
- a simulated crash after one real deterministic Planner model call but before durable result proof leaves `PLANNER_STARTED` uncertainty;
- explicit CLI recovery of that uncertainty does not replay the model call, terminalizes the exact receipt as `INTERRUPTED`, and a later fresh `start` remains blocked rather than acquiring replacement GOALBOOT authority;
- every accepted CLI bootstrap/recovery path stops before Manager and creates zero dispatch claims and zero dispatch executions.

These tests add no production authority. The only 46B repository mutation is the acceptance test file.

## Bootstrap / Manager authorization remains separated

GOALBOOT `READY` means only that the exact current Goal revision has an accepted plan/materialization and exact current PREPPOL suitable for existing Manager admission.

Phase 46 does not interpret READY as Goal completion and does not call Manager automatically. Production advancement remains a separate explicit authorization:

```text
origin-forge manager advance
```

Thus the operator boundaries remain:

```text
explicit Goal bootstrap start/recover
→ GOALBOOT READY
→ STOP

separate explicit Manager advance
→ bounded Phase-43/44 Manager mechanics
→ STOP according to the accepted Manager driver
```

## Authority exclusions preserved

Phase 46 adds no:

- automatic Goal selection or cross-Goal fallback;
- caller-selected current Goal revision/hash;
- automatic start↔recovery substitution;
- automatic uncertain Planner replay;
- repeated bootstrap/Manager loop, queue drain, watcher, poller, timer, daemon, service, or background scheduler;
- caller-selected capability catalog, routing policy, dispatch catalog, adapter, contract, binder, model, profile, runtime, provider, endpoint, resource, Task, PREP, claim, execution, or Manager action;
- automatic Manager invocation after READY;
- Task outcome or verification reinterpretation;
- Artifact adoption/signing;
- Project Intelligence or Design Bible mutation;
- Dream promotion, training/model activation, merge, release, deployment, or remote multi-user authority;
- fourth executable or cockpit/HTTP/plugin/model-callable mutation surface.

## Exact-head accepted evidence

- **Phase-46 planning — PR #92:** exact planning head `0c87efd851fa1f5dd9dbc9e4120cecf65c24a661`; normal run `31850379532` / #1312 passed Python 3.12 and Python 3.13; merged as `d56f3853b89a31bc0544b13e0c2922bbe82f9872`.
- **46A — Goal-bootstrap CLI boundary — PR #93:** exact head `b830d25dfdca87cb0a99f90d430c343004d75234`; normal run `31850814889` / #1314 passed Python 3.12 and Python 3.13; the branch changed only `src/origin_forge/cli.py` and focused CLI tests; merged as `4d146cc1d12b5c387c990efbfa93f4062cd0478c`.
- **46B — cross-phase CLI acceptance — PR #94:** exact head `5239c08eb2ffea8200c7b127356f1909fbc33b2b`; normal run `31851197879` / #1316 passed Python 3.12 and Python 3.13; the branch added exactly one acceptance-test file and no production mutation; merged SHA-guarded as `a0e8a04cff45e664153247c9f6f643daa4db2267`.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact merged Phase-46B main `a0e8a04cff45e664153247c9f6f643daa4db2267`.

The closure branch may modify documentation only. It must preserve the existing three packaged scripts, the read-only cockpit boundary, the Phase-45 bootstrap authority, and the separate explicit Manager authorization.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
