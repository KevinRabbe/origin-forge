# Origin Forge Operator Guide

Status: **POST-v0.5 DEVELOPMENT MAINLINE**

This guide describes the current `main` operator surface. Origin Forge v0.5.0 was released on 2026-08-16 and remains immutably identified by annotated tag `v0.5.0` at release commit `8ac46ee5f14654187469e79b021dbbd83992270b`; current `main` is post-v0.5 development and contains the separately gated Phase-48 Pixelorama production-dispatch integration, Phase-49 governed production-output adoption, and Phase-50 governed production Task acceptance. For the exact released v0.5.0 surface, see `docs/v0.5-operator-guide.md`.

## Install

Origin Forge requires Python 3.12 or newer.

```bash
python -m pip install .
```

The package installs three intentionally distinct commands:

```text
origin-forge          durable control-plane/operator commands
origin-forge-attempt  exactly one bounded coding attempt
origin-forge-cockpit  read-only local inspection
```

Current source metadata remains package version `0.5.0` under the Apache License 2.0. The immutable `v0.5.0` tag identifies the released bits; post-release Phase-48/49/50 commits on `main` are not retroactively part of that tagged release merely because the source version string remains `0.5.0`.

## Initialize a project

From the project repository root:

```bash
origin-forge init
```

Or from another directory:

```bash
origin-forge --project-root /path/to/project init
```

Initialization is the explicit state-creation boundary. It creates the protected `.origin-forge` project state and default configuration.

Other packaged commands are not substitutes for initialization. `origin-forge-attempt` fails closed unless the project already has contained config/database state, the database schema is current, the repository root is bound to a project row, and no active WAL/SHM/rollback-journal state is present. It does not create or migrate partial state before beginning an attempt.

## Configure verification before attempting work

The default configuration deliberately has an unconfigured sandbox and no approved build/test commands. A useful coding attempt therefore requires project-owned configuration for the governed sandbox and at least one required verification command.

Approved commands are structured argv arrays in `.origin-forge/config.toml`; they are not shell command strings.

Model execution remains separate and replaceable. The packaged one-attempt command defaults to a loopback llama.cpp-compatible endpoint and does not grant a model arbitrary shell/filesystem authority.

## Create durable work state

The control-plane CLI exposes explicit Goal / Flow / Task lifecycle operations:

```bash
origin-forge goal --help
origin-forge flow --help
origin-forge task --help
origin-forge run --help
origin-forge verify --help
origin-forge sandbox --help
```

A fresh bounded coding attempt requires the target Task and parent Flow to satisfy the orchestration preconditions. The attempt command does not invent Tasks or silently repair lifecycle state.

## Inspect, bootstrap, or recover one explicit Goal

Phase 46 exposes the accepted Phase-45 Goal-bootstrap operator boundary through the existing `origin-forge` executable without adding a fourth packaged command:

```bash
origin-forge --project-root /path/to/project goal bootstrap status  <GOAL-ID>
origin-forge --project-root /path/to/project goal bootstrap start   <GOAL-ID>
origin-forge --project-root /path/to/project goal bootstrap recover <GOAL-ID>
```

Each operation requires one explicit canonical `GOAL-*` identity. There is no implicit Goal selection, fallback to another Goal, Goal revision/hash override, Task selector, model/profile/runtime selector, capability/policy/catalog selector, Manager selector, or caller-selected retry/step budget.

`goal bootstrap status` performs the bounded non-creating Phase-45 decision projection once and prints its exact typed JSON representation. The possible decisions are:

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

The status command does not initialize or migrate state, create SQLite sidecars, publish authority, repair a receipt, call a model, materialize work, publish PREPPOL, or invoke Manager.

`goal bootstrap start` invokes the accepted fresh-bootstrap API exactly once. Fresh work begins only when the exact current Goal revision is `ELIGIBLE`. A trustworthy current READY bootstrap is revalidated and returned idempotently as `ALREADY_READY`; an existing non-READY same-revision receipt is not silently recovered or replaced.

`goal bootstrap recover` invokes the accepted explicit-recovery API exactly once. It resumes only the one unique exact current recoverable GOALBOOT receipt. It never turns an `ELIGIBLE` Goal into a fresh bootstrap, never acquires replacement authority for a terminal/stale/ambiguous same-revision receipt, and never automatically replays uncertain already-dispatched Planner work.

`start` does not perform a CLI-owned status preflight and does not switch itself into `recover`; `recover` likewise does not switch itself into `start`. Neither command retries, watches, polls, loops, waits until READY, or runs in the background.

Expected blocked bootstrap operations are emitted as bounded JSON with the exact Phase-45 decision and process exit code `4`; other expected bootstrap-operator errors use bounded JSON and exit code `5`. Successful typed status/start/recover mechanics return exit code `0`. Those exit codes describe the operator invocation, not Goal completion, Task success/failure, or verification truth.

The same Phase-45 boundary remains available programmatically through:

```python
from origin_forge.production_goal_bootstrap_operator import (
    bootstrap_goal_once,
    inspect_goal_bootstrap_status_readonly,
    recover_goal_once,
)
```

A successful bootstrap or recovery stops at GOALBOOT `READY` after exact PREPPOL publication/revalidation. It does **not** invoke Manager. Production advancement remains a separate explicit `origin-forge manager advance` authorization.

Phases 47, 48, 49, and 50 do not widen this bootstrap boundary: Phase-45/46 Goal bootstrap remains exactly code-only (`code.change → originforge.code.bounded-retry → code.bounded-retry@1`). It does not bootstrap `simulation.run` or `media.2d.export` Tasks.

## Inspect or explicitly advance governed Manager work

The main control-plane CLI exposes one local Manager group over the already bounded production Manager primitives:

```bash
origin-forge --project-root /path/to/project manager status
origin-forge --project-root /path/to/project manager advance
```

`manager status` performs the non-creating Manager admission/selection projection once and prints its typed JSON result. `manager advance` invokes the fixed bounded Manager driver once and prints its exact typed trace. The bounded driver owns a hard code-defined maximum of six one-shot Manager steps and stops on the first non-continuable result, including the first dispatch result; the CLI provides no budget override.

A typed Manager result with process exit code `0` means the operator command ran and returned Manager mechanics. It is not Task success/failure, verification truth, merge authority, or release authority.

These commands do not initialize or migrate project state, do not repeat/watch/poll until idle, do not drain a queue, do not run in the background, and expose no Task/PREP/claim/action/model/resource selector. Missing, stale, partial, or actively written durable state remains fail closed through the existing Manager boundary.

Phase 47 allows an **already-governed** `simulation.run` Task with the exact deterministic simulation adapter/contract to execute through this same explicit Manager path. Simulation preparation still uses the governed one-shot WorkOrder Planner, but the execution owner itself requires no model/runtime/resource/sandbox/Git-Workspace dependencies. After durable dispatch STARTED ownership, infrastructure allocates fresh `SIMSPEC-*`, `SIM-*`, and `SIMWS-*` identities and invokes the existing deterministic `SimulationService` exactly once.

A normal simulation dispatch creates the canonical Phase-25 `SIMULATOR` Run plus `SIMULATION_SPEC`, `SIMULATION_RESULT`, and `SIMULATION_SUMMARY` evidence, consumes the dispatch claim, and returns `DISPATCH_RETURNED`. The production Task deliberately remains `RUNNING`: simulation findings are structural evidence, not Task PASS/FAIL, semantic-balance truth, tuning authority, adoption/signing authority, merge authority, or release authority. Uncertain post-STARTED states are not automatically replayed.

There is no direct `origin-forge simulation run` mutation command. Production simulation execution is reachable only through already-governed preparation/claim/dispatch authority and the existing explicit Manager invocation.

Phase 48 likewise allows an **already-governed** `media.2d.export` Task using the exact `originforge.pixelorama.export / pixelorama.spritesheet-export@1` relation to execute through the same explicit Manager path. Its WorkOrder must contain exactly one project-owned `PIXELORAMA_PROJECT` Artifact ref with role `pixelorama_project`. Phase 34 resolves and revalidates that Artifact as metadata only; the `.pxo` source is opened only after durable DISPEXEC `STARTED` and Task `READY → RUNNING` ownership.

The Pixelorama execution owner uses the infrastructure-owned trusted Pixelorama CLI profile, not caller/model-selected executable or process settings. After STARTED it revalidates the exact local `.pxo` source path, containment, regular-file/no-symlink status, hash, and bounded byte count; allocates fresh `PXOP-*` and `MEDIA-*` identities; and invokes the durable direct CLI spritesheet-export service at most once. A trustworthy return creates one PIXELORAMA Run plus exact request/result/export/Verification evidence, consumes the claim, records DISPEXEC `RETURNED`, and leaves the production Task `RUNNING`.

Pixelorama export evidence is structural only. Manager does not infer aesthetic quality or Task acceptance, does not adopt the exported PNG into a canonical project path, does not sign it, and does not complete/fail the Task. Project creation/import/edit/save, arbitrary extensions/plugins/GDScript, caller-selected source/output paths, and automatic replay after STARTED remain outside the production boundary. There is no direct command that executes a production Pixelorama editor operation; editor execution remains reachable only through governed Manager dispatch.

## Explicitly adopt one terminal Pixelorama production output

Phase 49 adds one explicit human-operated production-adoption command under the existing module-only Pixelorama admin family. It does **not** add a fourth installed package script:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  adopt-production-new \
  DISPEXEC-... \
  assets/sprites/new_asset.png
```

The optional `--max-source-bytes` flag retains the existing bounded source-read safety limit. The command accepts no Run ID, source Artifact ID, source path/URI, Task selector, verifier override, Pixelorama executable/profile, signing key/certificate, overwrite/force flag, or automatic destination selector.

The selected `DISPEXEC-*` must resolve to the exact immutable Phase-49 dispatch-output binding and a trustworthy terminal Pixelorama relation: `DISPEXEC RETURNED`, claim `CONSUMED`, the frozen production Task still `RUNNING`, exact bound PIXELORAMA Run/request/result/export/Verification lineage, and exact current output bytes. Missing, stale, ambiguous, tampered, nonterminal, escaped, symlinked, or byte-drifted evidence fails closed before canonical publication.

Publication reuses the Phase-19 create-only primitive. The destination must be a new safe project-relative path; an existing destination is never overwritten. One bound production execution/output may be canonically adopted at most once. A crash after a reservation but before publication may be retried only while the destination is still absent. If a destination exists beside a PREPARED receipt, automatic retry fails closed and requires operator recovery rather than deleting or replacing the file.

A successful production adoption creates one child `SPRITESHEET_EXPORT` Artifact with status `ADOPTED` and a production-bound adoption-integrity PASS Verification. It keeps all higher authorities false: the Task remains `RUNNING`, no Task PASS/FAIL Verification is synthesized, semantic/aesthetic quality is not asserted, and provenance is not signed.

Phase 49 adoption never invokes Pixelorama. It consumes only the exact already-durable Phase-48 output. If the bound output is missing or invalid, the command fails closed rather than replaying the editor.

The legacy module command:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  adopt-new ART-... assets/sprites/new_asset.png
```

retains the existing Phase-19 source-verifier gate and behavior. A Phase-48 production export does not gain legacy `adopt-new` authority merely because it is structurally valid; production adoption must go through the exact DISPEXEC-bound path above.

## Explicitly accept one adopted Pixelorama production Task

Phase 50 adds one separate explicit human-operated acceptance command to the same module-only Pixelorama admin family. It also does **not** add a fourth installed package script:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  accept-production-task DISPEXEC-...
```

This command accepts only one explicit canonical `DISPEXEC-*` identity. It accepts no Task ID, Run ID, source or adopted Artifact ID, Verification ID, destination/path, PASS status, verifier, vision/specialist report, model score, Pixelorama profile, signing/release material, overwrite/force flag, or bypass option. All production identities are derived from the exact durable dispatch/adoption relation.

Before a first acceptance, the selected execution must still reconstruct the complete current Phase-48/49 chain: exact immutable dispatch-output binding, Pixelorama owner, `DISPEXEC RETURNED`, claim `CONSUMED`, exact successful PIXELORAMA Run/request/result/output/Verification lineage, exact PUBLISHED production-adoption receipt, exact adopted `SPRITESHEET_EXPORT` Artifact and adoption-integrity PASS, exact regular non-symlinked canonical destination, exact current RGBA8 PNG bytes/hash/byte count, and the exact still-`RUNNING` production Task under the existing child-Task/revision laws. Missing, stale, ambiguous, tampered, byte-drifted, relinked, or conflicting evidence fails closed before a new Task PASS is created.

A successful explicit acceptance atomically records one immutable production Task-acceptance receipt and exactly one Task-targeted `pixelorama-production-task-acceptance` PASS with `acceptance_authority=HUMAN_OPERATOR`. Only after that exact acceptance is durable does Origin Forge invoke the existing runtime/store Task transition law to move the Task `RUNNING → SUCCEEDED`. It does not update Task state directly or weaken the existing verification/child/revision gates.

The Phase-50 PASS states that the human/governance boundary accepted the exact canonical production result against the Task contract. Favorable vision or specialist evidence remains advisory and cannot synthesize this acceptance. An unrelated historical Task PASS is also insufficient.

If the acceptance PASS/receipt becomes durable but the Task transition is interrupted, retrying the same exact `DISPEXEC-*` revalidates current production truth, reuses the same PASS/receipt, and may finish the canonical transition without creating a duplicate. An exact already-`SUCCEEDED` invocation is idempotent only when that same Phase-50 acceptance is the durable basis. Every other conflicting Task or acceptance state fails closed.

Phase 50 acceptance never invokes Pixelorama, rewrites or republishes the canonical asset, runs vision or a specialist, signs provenance, authorizes release, or transitions the parent Flow or Goal. The accepted Task history remains append-only; later asset drift does not retroactively rewrite a successfully terminalized acceptance.

The cockpit remains a separate read-only inspection surface. It does not receive a Manager, Goal-bootstrap, simulation, Pixelorama execution, production-adoption, or production-acceptance mutation command.

## Run exactly one bounded coding attempt

Use explicit context:

```bash
origin-forge-attempt \
  --project-root /path/to/project \
  <TASK-ID> \
  --file src/example.py \
  --file tests/test_example.py
```

Or deterministic automatic context selection:

```bash
origin-forge-attempt \
  --project-root /path/to/project \
  <TASK-ID> \
  --auto-context
```

Optional bounded context refinements include `--seed-file`, `--structural-context`, and `--semantic-context` according to the existing orchestration contract.

Before entering the normal authoritative writer path, the packaged attempt command performs a non-creating readiness check over the existing durable state. Missing/partial/stale/actively-written state fails with exit code 2. Once that check passes, the existing orchestration/runtime path owns the actual attempt and its durable writes.

The command performs **one** governed attempt. It does not expose the Phase-7 retry policy as an automatic CLI loop, does not merge a successful workspace, and does not release anything.

Exit semantics remain:

```text
0   attempt SUCCEEDED
12  attempt FAILED
13  attempt BLOCKED
2   operator/configuration/preflight error
```

Ordinary operator/configuration failures are emitted as bounded JSON errors rather than raw tracebacks.

## Inspect with the read-only cockpit

Snapshot JSON:

```bash
origin-forge-cockpit \
  --project-root /path/to/project \
  snapshot
```

Local HTML cockpit:

```bash
origin-forge-cockpit \
  --project-root /path/to/project \
  serve --port 8765
```

Then open the loopback address printed by the command.

The cockpit is intentionally stricter than the authoritative runtime path. It requires already-initialized, current-schema, quiescent durable state and refuses to create/migrate/checkpoint the database. If SQLite WAL/SHM/rollback-journal state is active, finish the authoritative writer and retry inspection; the cockpit will not repair or checkpoint it for you.

The cockpit exposes bounded runtime/causal state, Project Intelligence and Design Bible state, model/resource configuration/admission state, public provenance metadata, and Dream/memory inspection. It does not read arbitrary Artifact bytes, execute models/tools, mutate Tasks, adopt/sign Artifacts, promote Dream memory, merge, or release.

## `origin-forge status` is different

`origin-forge status` is an existing authoritative control-plane status command. It uses the normal runtime/store path and is therefore not the Phase-30 non-mutating inspection surface.

Use `origin-forge-cockpit snapshot` when the requirement is specifically bounded non-creating inspection.

## Recovery and stop conditions

Origin Forge persists work state rather than relying on one process or chat session. Use the existing recovery/status surfaces to inspect interrupted state.

Autonomous continuation is intentionally bounded. Failed attempts, blocked infrastructure, verification failures, exact-repeat loops, retry budgets, recovery-required states, and quarantine remain explicit control-policy concerns rather than reasons to run an endless agent loop.

The Phase-44 Manager command is similarly bounded: one explicit `manager advance` invocation may traverse only the fixed Phase-43 continuation whitelist and stops at the first non-continuable result or hard six-step limit.

The Phase-45/46 Goal-bootstrap boundary is independently explicit and bounded: a fresh bootstrap starts only from `ELIGIBLE`, uncertain Planner execution is not automatically replayed, recovery must be requested separately, and READY stops before Manager invocation.

The Phase-47 deterministic simulation and Phase-48 Pixelorama dispatch boundaries follow the same no-replay law: once owner-specific DISPEXEC `STARTED` is durable, a BaseException/crash or post-evidence terminalization failure requires explicit recovery rather than a second automatic backend/editor call.

Phases 49 and 50 preserve that law across publication and acceptance: binding publication/currentness, terminal dispatch recovery, production adoption, Task acceptance, retry, and recovery never re-invoke Pixelorama. Exact durable output/adoption/acceptance evidence is consumed or rejected; it is not regenerated to make adoption or acceptance convenient.

## Current-development boundary

Current `main` does not grant:

- automatic merge or release authority;
- unrestricted shell/filesystem/process access;
- UI mutation workflows;
- automatic Artifact adoption or signing;
- automatic Dream promotion;
- production checkpoint/model activation;
- direct simulation execution or direct Pixelorama editor-execution commands, or automatic Task terminalization from simulation/export/adoption/advisory evidence;
- generic Pixelorama project creation/import/edit/save, arbitrary editor scripts/plugins, or automatic output adoption/signing;
- model-, vision-, specialist-, Pixelorama-, Manager-, or dispatcher-synthesized semantic production acceptance;
- background Goal bootstrap, Manager scheduling/queue draining, production adoption, or production Task acceptance;
- remote/multi-user cockpit hosting.

The Pixelorama post-dispatch mutation surfaces are exactly the explicit module commands documented above: create-only `adopt-production-new` and human-only `accept-production-task`. Neither executes the editor, selects a different output, overwrites an asset, signs provenance, authorizes release, or grants background/automatic authority; only the acceptance command may request the existing verification-gated Task `RUNNING → SUCCEEDED` transition after exact currentness and human acceptance are durable.

Origin Forge is licensed under the Apache License 2.0; see the repository `LICENSE` file. The immutable v0.5.0 release remains documented separately in `docs/v0.5-release-readiness.md`, `docs/v0.5-acceptance-matrix.md`, and `docs/v0.5-operator-guide.md`. Phases 48, 49, and 50 are explicitly post-v0.5 development.
