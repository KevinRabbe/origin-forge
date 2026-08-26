# Origin Forge Operator Guide

Status: **POST-v0.5 DEVELOPMENT MAINLINE**

This guide describes the current `main` operator surface. Origin Forge v0.5.0 was released on 2026-08-16 and remains immutably identified by annotated tag `v0.5.0` at release commit `8ac46ee5f14654187469e79b021dbbd83992270b`; current `main` is post-v0.5 development and contains the separately gated Phase-48 Pixelorama production-dispatch integration, Phase-49 governed Pixelorama production-output adoption, Phase-50 governed Pixelorama production Task acceptance, Phase-51 governed Blender 3D production dispatch, Phase-52 governed Blender production-output adoption, Phase-53 governed Blender production Task acceptance, Phase-54 governed Blender production provenance signing, Phase-55 governed Pixelorama production provenance signing, and Phase-56 governed design-specification production substrate. For the exact released v0.5.0 surface, see `docs/v0.5-operator-guide.md`.

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

The bounded coding attempt is also available under the unified operator CLI:

```text
origin-forge attempt TASK-... --auto-context
```

It delegates to the same single-attempt engine as `origin-forge-attempt`.

Current source metadata remains package version `0.5.0` under the Apache License 2.0. The immutable `v0.5.0` tag identifies the released bits; post-release Phase-48/49/50/51/52/53/54/55/56 commits on `main` are not retroactively part of that tagged release merely because the source version string remains `0.5.0`.

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

Phases 47, 48, 49, 50, 51, 52, 53, 54, 55, and 56 do not widen this bootstrap boundary: Phase-45/46 Goal bootstrap remains exactly code-only (`code.change → originforge.code.bounded-retry → code.bounded-retry@1`). It does not bootstrap `simulation.run`, `media.2d.export`, `media.3d.blender`, or the Phase-56 pre-planning design-specification operation.

## Inspect or explicitly advance governed Manager work

The main control-plane CLI exposes one local Manager group over the already bounded production Manager primitives:

```bash
origin-forge --project-root /path/to/project manager status
origin-forge --project-root /path/to/project manager advance
```

The equivalent top-level command is available for the daily workflow:

```text
origin-forge --project-root /path/to/project advance
```

It invokes the same fixed bounded Manager driver exactly once and accepts no
caller-selected budget or fallback authority.

`manager status` performs the non-creating Manager admission/selection projection once and prints its typed JSON result. `manager advance` invokes the fixed bounded Manager driver once and prints its exact typed trace. The bounded driver owns a hard code-defined maximum of six one-shot Manager steps and stops on the first non-continuable result, including the first dispatch result; the CLI provides no budget override.

A typed Manager result with process exit code `0` means the operator command ran and returned Manager mechanics. It is not Task success/failure, verification truth, merge authority, or release authority.

These commands do not initialize or migrate project state, do not repeat/watch/poll until idle, do not drain a queue, do not run in the background, and expose no Task/PREP/claim/action/model/resource selector. Missing, stale, partial, or actively written durable state remains fail closed through the existing Manager boundary.

Phase 47 allows an **already-governed** `simulation.run` Task with the exact deterministic simulation adapter/contract to execute through this same explicit Manager path. Simulation preparation still uses the governed one-shot WorkOrder Planner, but the execution owner itself requires no model/runtime/resource/sandbox/Git-Workspace dependencies. After durable dispatch STARTED ownership, infrastructure allocates fresh `SIMSPEC-*`, `SIM-*`, and `SIMWS-*` identities and invokes the existing deterministic `SimulationService` exactly once.

A normal simulation dispatch creates the canonical Phase-25 `SIMULATOR` Run plus `SIMULATION_SPEC`, `SIMULATION_RESULT`, and `SIMULATION_SUMMARY` evidence, consumes the dispatch claim, and returns `DISPATCH_RETURNED`. The production Task deliberately remains `RUNNING`: simulation findings are structural evidence, not Task PASS/FAIL, semantic-balance truth, tuning authority, adoption/signing authority, merge authority, or release authority. Uncertain post-STARTED states are not automatically replayed.

There is no direct `origin-forge simulation run` mutation command. Production simulation execution is reachable only through already-governed preparation/claim/dispatch authority and the existing explicit Manager invocation.

Phase 48 likewise allows an **already-governed** `media.2d.export` Task using the exact `originforge.pixelorama.export / pixelorama.spritesheet-export@1` relation to execute through the same explicit Manager path. Its WorkOrder must contain exactly one project-owned `PIXELORAMA_PROJECT` Artifact ref with role `pixelorama_project`. Phase 34 resolves and revalidates that Artifact as metadata only; the `.pxo` source is opened only after durable DISPEXEC `STARTED` and Task `READY → RUNNING` ownership.

The Pixelorama execution owner uses the infrastructure-owned trusted Pixelorama CLI profile, not caller/model-selected executable or process settings. After STARTED it revalidates the exact local `.pxo` source path, containment, regular-file/no-symlink status, hash, and bounded byte count; allocates fresh `PXOP-*` and `MEDIA-*` identities; and invokes the durable direct CLI spritesheet-export service at most once. A trustworthy return creates one PIXELORAMA Run plus exact request/result/export/Verification evidence, consumes the claim, records DISPEXEC `RETURNED`, and leaves the production Task `RUNNING`.

Pixelorama export evidence is structural only. Manager does not infer aesthetic quality or Task acceptance, does not adopt the exported PNG into a canonical project path, does not sign it, and does not complete/fail the Task. Project creation/import/edit/save, arbitrary extensions/plugins/GDScript, caller-selected source/output paths, and automatic replay after STARTED remain outside the production boundary. There is no direct command that executes a production Pixelorama editor operation; editor execution remains reachable only through governed Manager dispatch.

Phase 51 adds one equally narrow **already-governed** `media.3d.blender` path using `originforge.blender.model3d / blender.export-glb@1`. Preparation may select exactly one pre-existing protected `MODEL3DREQ-*` semantic request through the infrastructure-owned Blender planner allow-list. The WorkOrder contains exactly one `MODEL3D_REQUEST` ref with role `model3d_request` and inert `{}` payload; caller/model runtime paths, profile, Blender version, runner, process settings, budgets, operation IDs, workspace IDs, adoption, and Task authority are not WorkOrder inputs.

The Blender execution owner requires only the infrastructure-owned trusted Blender profile and atomically records DISPEXEC `STARTED + Task READY → RUNNING` before allocating any `BLOP-*` operation or `MODEL3D-*` workspace identity. Only after STARTED does infrastructure construct the strict runtime request with fixed `exports/model.glb`, trusted profile hashes/version, and code-owned budget, then invoke the existing governed Blender adapter exactly once. A trustworthy return persists and independently revalidates request/result/GLB Artifact and Run/Verification lineage, consumes the claim, records DISPEXEC `RETURNED`, and leaves the production Task `RUNNING`.

There is no direct `origin-forge blender run` mutation command and no automatic GLB adoption, Task acceptance, signing, merge, or release. If durable Blender output exists but dispatch terminalization is interrupted, explicit infrastructure recovery may revalidate and consume that exact bound output without replaying Blender; drift fails closed.

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

## Explicitly adopt one terminal Blender production output

Phase 52 adds one explicit human-operated production-adoption command under a module-only Blender admin surface. It does **not** add a fourth installed package script:

```bash
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  adopt-production-new \
  --execution-id DISPEXEC-... \
  --destination assets/models/new_asset.glb
```

The optional `--max-source-bytes` argument retains the bounded source-read safety limit. The command accepts no Task ID, Run ID, request/result/output Artifact ID, source path, Verification ID, binding override, Blender executable/profile/runtime/version/runner, semantic verdict, signing key/certificate, overwrite/force flag, or automatic destination selector.

The selected `DISPEXEC-*` must resolve to the exact immutable Phase-51 Blender dispatch-output binding and a trustworthy terminal relation: exact Blender execution owner and frozen Task/WorkOrder/binding identity, `DISPEXEC RETURNED`, claim `CONSUMED`, the production Task still `RUNNING`, exact successful Blender Run/request/result/output/Verification lineage, and exact current regular non-symlinked GLB bytes/hash/byte count. Missing, stale, ambiguous, tampered, nonterminal, escaped, symlinked, oversized, or byte-drifted evidence fails closed before canonical publication.

The destination must be a new safe project-relative path. Publication is create-only and never overwrites an existing file. One exact bound Blender production execution/output may be canonically adopted at most once. A PREPARED receipt is retryable only while the destination is absent. If the destination exists beside PREPARED state, automatic retry fails closed with recovery required rather than deleting, replacing, or guessing whether the prior publication completed.

## Publish a governed Blender semantic request

Phase 57 adds a separate module-only publication boundary between accepted design
evidence and the existing Blender WorkOrder. First create the Phase-57A
proposal and independent PASS audit, then explicitly approve and publish it:

```bash
python -m origin_forge.model3d_request_publication_admin_cli approve \
  --proposal-id M3DREQPROP-...
python -m origin_forge.model3d_request_publication_admin_cli publish \
  --approval-id M3DREQAPP-...
python -m origin_forge.model3d_request_publication_admin_cli inspect \
  --publication-id M3DREQPUB-...
```

Approval is fixed to `HUMAN_OPERATOR`. Origin Forge allocates the final
`MODEL3DREQ-*` identity and publishes it to the existing protected registry;
operators and models cannot provide or replace its ID, hash, payload, path, or
runtime authority. Blender admission requires the exact current
`M3DREQPUB-*` relation for the Task. Missing, conflicting, stale, or tampered
approval/publication/request evidence fails closed. Recovery can finish a
durable approval or publication without rerunning the semantic model.

A successful adoption creates one adopted child `BLENDER_GLB_EXPORT` Artifact, one exact `blender-production-adoption-integrity` PASS Verification, and finalizes the immutable Blender adoption receipt as PUBLISHED. The Task remains `RUNNING`; no Task PASS/FAIL is synthesized, semantic geometry or aesthetic quality is not asserted, and provenance is not signed.

Phase 52 adoption never invokes Blender. It consumes only the exact already-durable Phase-51 terminal output and fails closed rather than replaying the backend. Phase 52 alone stops at canonical byte adoption; semantic Task acceptance is the separately governed Phase-53 boundary documented below.

A future UI may expose this adoption boundary only as a client of the existing application/service authority. Presentation code must not copy files directly, duplicate or weaken currentness checks, auto-select source authority, auto-adopt, retry ambiguous PREPARED state, replay Blender, overwrite assets, terminalize Tasks, sign provenance, or authorize release. Successful adoption should be presented as canonical byte adoption only—not semantic correctness or Task success.

## Explicitly accept one adopted Blender production Task

Phase 53 adds one separate explicit human-operated acceptance command to the same module-only Blender admin family. It does **not** add a fourth installed package script:

```bash
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  accept-production-task \
  --execution-id DISPEXEC-...
```

The optional `--actor-id` argument provides operator attribution only. Semantic acceptance authority remains fixed to `HUMAN_OPERATOR`; `--actor-id` cannot override the Task, WorkOrder, Phase-34 binding, protected MODEL3D request, Run, Artifact, Verification, destination, hash/size, PASS value/verifier, Blender runtime/profile/workspace/operation, force/bypass, signing, merge, deploy, or release authority.

Before a first acceptance, the selected execution must reconstruct the exact current Phase-51/52 relation: immutable Blender dispatch-output binding, exact Blender owner, `DISPEXEC RETURNED`, claim `CONSUMED`, exact Task/WorkOrder/Phase-34 binding and protected MODEL3D semantic request relation, exact successful Blender Run/request/result/output/Verification lineage, exact PUBLISHED Phase-52 adoption receipt, exact adopted `BLENDER_GLB_EXPORT` Artifact and `blender-production-adoption-integrity` PASS, exact safe regular non-symlinked canonical destination, exact current hash/byte count/structurally valid GLB bytes, and the exact still-`RUNNING` Task revision with child Tasks compatible with success. Missing, stale, ambiguous, relinked, escaped, symlinked, mutated, byte-drifted, structurally invalid, revision-drifted, or conflicting evidence fails closed before a new Task PASS is created.

A successful explicit acceptance atomically records one immutable Blender production Task-acceptance receipt and exactly one Task-targeted `blender-production-task-acceptance` PASS with `acceptance_authority=HUMAN_OPERATOR`. Only after that exact acceptance is durable does Origin Forge request the existing runtime/store Task transition law for `RUNNING → SUCCEEDED`; the acceptance implementation does not update Task state directly or weaken optimistic revision, child-Task, Verification, or state-event invariants.

The successful typed result makes the authority boundary explicit: `production_task_verified=true`, `semantic_geometry_verified=true`, `canonical_asset_adopted=true`, and `acceptance_authority=HUMAN_OPERATOR`, while `provenance_signed=false` and `release_authorized=false`. Those semantic flags mean that the human/governance boundary accepted the exact canonical result against the Task contract. They are not a model-, vision-, specialist-, Blender-, Manager-, conversation-, browser-, or UI-derived geometry oracle.

If the acceptance PASS/receipt becomes durable but Task terminalization is interrupted, retrying the same exact `DISPEXEC-*` revalidates current production truth, reuses the same PASS/receipt, and may finish the canonical transition without replaying Blender, rewriting the GLB, or creating duplicate acceptance. If a concurrent worker wins the same exact transition, the losing worker accepts only a fresh read proving that exact accepted Task already reached `SUCCEEDED`.

An exact already-`SUCCEEDED` invocation is idempotent only when the same historical Phase-53 acceptance is the durable basis. After that terminal acceptance, later unrelated workspace drift of the adopted file does not retroactively rewrite accepted Task history. Other conflicting terminal/currentness states fail closed.

Phase 53 acceptance never invokes Blender, rewrites or republishes the canonical GLB, creates a second adoption receipt, runs vision or a specialist, invokes Manager, signs provenance, authorizes release, or transitions the parent Flow or Goal.

A future UI may expose this acceptance boundary only as a client of the same governed acceptor after explicit human confirmation. Presentation code must not write Task/Verification/acceptance state directly, mutate the GLB, duplicate or weaken currentness checks, auto-accept, turn model/vision/specialist evidence into `HUMAN_OPERATOR` acceptance, automatically retry stale/conflicting state, replay Blender, sign provenance, or merge/deploy/release. It should distinguish `NOT_ACCEPTED`, `ACCEPTED_PENDING_TASK_TRANSITION`, `ACCEPTED_TASK_SUCCEEDED`, and `STALE_OR_CONFLICTING` exactly as returned by the governed service.

The cockpit remains a separate read-only inspection surface. Phases 52 and 53 do not add a Manager, Goal-bootstrap, simulation, Pixelorama execution, Blender execution, production-adoption, or production-acceptance mutation command to the cockpit/browser surface.

## Explicitly sign provenance for one terminally accepted Blender production result

Phase 54 adds one separate explicit operator-triggered signing command to the same module-only Blender admin family. It does **not** add a fourth installed package script:

```bash
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  sign-production-provenance \
  --execution-id DISPEXEC-... \
  --certificate-id KEYCERT-... \
  --operational-private-key /external/path/to/operational-key.pem
```

The operator supplies exactly one canonical `DISPEXEC-*`, one existing Phase-18 certificate identity, and one external operational private-key path. The command accepts no Task/Run/Artifact/Verification identity, destination/path/hash/byte-count override, parent manifest, acceptance flag, force/bypass, Company Root private key, release/publish/merge flag, or automatic target selector.

The selected execution must already represent the exact current terminal Blender production chain: the Phase-51 Blender dispatch/output relation, exact Phase-52 PUBLISHED adoption and canonical `ADOPTED` `BLENDER_GLB_EXPORT`, and exact Phase-53 `ACCEPTED_TASK_SUCCEEDED` Task acceptance. Phase 54 derives the adopted Artifact internally and revalidates its current safe contained non-symlink regular-file GLB bytes, exact accepted hash and byte count, and GLB structure before signing. It does not invoke or recover Phase-53 acceptance to make an execution eligible.

Signing delegates to the existing Phase-18 provenance service with fixed empty parent manifests. Phase 18 remains authoritative for `ARTIFACT_SIGNING` certificate purpose, Company Root trust, revocation, key matching, private-key containment/permissions, Ed25519 signing, signature-chain verification, immutable manifest persistence, and trust/currentness inspection.

The operational private key must remain outside the project tree and satisfy Phase-18 key policy. Phase 54 does not generate keys, copy them into project state, issue/revoke certificates, provision a Company Root, accept the Company Root private key, or repair trust configuration on demand. A `RELEASE_SIGNING` certificate cannot be substituted for the required artifact-signing authority.

A successful result proves that the newly persisted provenance manifest is trusted/current and binds the exact adopted Artifact, accepted Task, production Run, Phase-52 adoption PASS, and Phase-53 Task-acceptance PASS. The adopted Artifact remains `ADOPTED`; the Task remains `SUCCEEDED`; no production Verification is created; the GLB bytes are unchanged; and `release_authorized=false` remains explicit.

Repeated **explicit** signing is allowed. Each successful call may create a new immutable Phase-18 `PROVMAN-*` manifest over the same still-current production truth. There is no one-manifest-per-execution receipt and no automatic re-sign after an exception, restart, Manager tick, browser poll/reconnect, conversation event, startup, or background recovery.

Expected governed signing failures are emitted as bounded JSON without exposing the private-key path. Missing/pending/stale Phase-53 acceptance is an independent acceptance problem, adopted-byte drift is not repaired by signing, and trust/key failures remain separate Phase-18 administrative concerns. The signing command does not replay Blender, rewrite the GLB, call `accept_artifact()`, publish/recover Task acceptance, transition Task/Flow/Goal state, sign with the Company Root key, merge, deploy, publish, or release.

The cockpit/browser/conversation surfaces do not gain signing authority from Phase 54. Any future UI signing path requires a separately reviewed authority boundary; private-key material must not enter model/conversation/browser project state merely to make signing convenient.

## Explicitly sign provenance for one terminally accepted Pixelorama production result

Phase 55 adds one separate explicit operator-triggered signing command to the same module-only Pixelorama admin family. It does **not** add a fourth installed package script:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  sign-production-provenance \
  --execution-id DISPEXEC-... \
  --certificate-id KEYCERT-... \
  --operational-private-key /external/path/to/operational-key.pem
```

The operator supplies exactly one canonical `DISPEXEC-*`, one existing Phase-18 certificate identity, and one external operational private-key path. The command accepts no Task/Run/Artifact/Verification identity, source/destination/path/hash/byte-count override, parent manifest, acceptance flag, media selector, force/bypass, Company Root private key, release/publish/deploy flag, model/tool/specialist selector, or automatic signing target.

The selected execution must already represent the exact current terminal Pixelorama production chain: the reviewed Phase-48/49 dispatch/output relation, exact Phase-49 PUBLISHED adoption and canonical `ADOPTED` `SPRITESHEET_EXPORT`, and exact Phase-50 `ACCEPTED_TASK_SUCCEEDED` human Task acceptance. Phase 55 derives the adopted Artifact internally and immediately revalidates the canonical project-contained non-symlink regular-file RGBA8 PNG, exact accepted hash, and byte count before signing. It never invokes or recovers Phase-50 acceptance to make an execution eligible.

Signing delegates to the existing Phase-18 provenance service with fixed `parent_manifest_ids=()`. Phase 18 remains authoritative for `ARTIFACT_SIGNING` certificate purpose, Company Root trust, revocation, private-key containment/permissions, key matching, Ed25519 signing, immutable manifest persistence, signature-chain verification, and trust/currentness inspection.

The operational private key must remain outside the project tree. Phase 55 does not generate or copy keys, issue or revoke certificates, provision a Company Root, accept the Company Root private key, repair trust state, or permit `RELEASE_SIGNING` authority to substitute for artifact signing.

A successful result proves the new immutable manifest is trusted/current and binds the exact adopted Artifact, accepted Task, production Run, Phase-49 adoption PASS, and Phase-50 acceptance PASS. The adopted Artifact remains `ADOPTED`; the Task remains `SUCCEEDED`; production Verification state and PNG bytes are unchanged; and `release_authorized=false` remains explicit.

Repeated **explicit** signing is allowed and may create multiple immutable `PROVMAN-*` manifests over the same current production truth. There is no one-manifest-per-execution receipt and no automatic signing or retry after restart, Manager activity, browser polling, conversation events, startup, or recovery.

Governed failures are bounded JSON without exposing the private-key path. Missing/pending/stale Phase-50 acceptance, adopted PNG drift, and Phase-18 trust/key rejection remain independent problems. Signing does not replay Pixelorama, rewrite or re-encode the PNG, call `accept_artifact()`, publish or recover Task acceptance, transition Task/Flow/Goal state, provision trust, merge, deploy, publish, or release.

The cockpit/browser/conversation surfaces do not gain signing authority from Phase 55. Any future UI signing path requires a separately reviewed authority boundary; browser/model/conversation project state must not receive a host private-key path.

## Explicitly accept one governed design specification

Phase 56 adds one separate module-only HUMAN_OPERATOR acceptance command for the pre-planning design-specification boundary. It does **not** add a fourth installed package script:

```bash
python -m origin_forge.design_specification_admin_cli \
  --project-root /path/to/project \
  accept-design-specification \
  --design-specification-id DESIGNSPEC-...
```

The operator supplies exactly one canonical `DESIGNSPEC-*`. The command accepts no Goal ID, DESIGNIN ID or hash, audit ID/hash/status, DESIGNACC identity, acceptance authority/timestamp, specification replacement text, capability/policy override, model selector, Planner/Task switch, force/bypass flag, signing material, merge/deploy/release flag, retry loop, watcher, or background mode.

Before first acceptance, infrastructure loads and independently validates the exact durable DESIGNSPEC and its DESIGNIN, requires exactly one durable independently recomputed `DESIGNAUD` with status `PASS`, derives the project/Goal and all source hashes, and revalidates current Goal revision/hash, active Design Rules, deterministic Project Intelligence, bounded verified semantic state, and governed capability catalog/routing-policy relation. Missing, stale, ambiguous, tampered, capability-unavailable, or conflicting evidence fails closed before DESIGNACC publication.

Acceptance is serialized and immutable. Infrastructure allocates `DESIGNACC-*`, fixes `acceptance_authority=HUMAN_OPERATOR`, and derives the timestamp. Exact retry returns the same canonical acceptance. If another candidate already owns acceptance for the same exact DESIGNIN relation, the competing candidate cannot replace it.

A successful result reports the canonical DESIGNACC relation and whether that accepted design is currently usable. It does **not** create a Phase-31 PlanningInput automatically, execute the Planner, materialize Tasks, mutate Project Intelligence/Design Rules, invoke Manager, create media, sign provenance, or authorize release.

The accepted-design-to-Phase-31 bridge is a separate infrastructure application boundary. It takes only the exact current `DESIGNACC-*`, revalidates the full immutable acceptance/source relation, and may create or recover the corresponding PlanningInput. The bridge never executes the Planner. There is intentionally no Phase-56 module command that combines semantic acceptance with planning or Task materialization.

Goal, Design Rule, Project Intelligence, verified semantic-state, or required capability drift does not rewrite historical acceptance. The old DESIGNACC remains immutable but becomes stale for new planning use; a new DESIGNIN, proposal, audit, and explicit HUMAN_OPERATOR acceptance are required. Read-only inspection/recovery never reruns the design model or recreates missing capability authority merely to make an acceptance current.

The cockpit/browser/conversation surfaces do not gain Phase-56 semantic acceptance or planning authority. Any future UI must delegate to the same reviewed application boundary after explicit human confirmation; it must not insert DESIGNACC directly, synthesize HUMAN_OPERATOR authority from model/reviewer output, replace source hashes/text, auto-accept, auto-plan, or materialize Tasks client-side.

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

The Phase-47 deterministic simulation, Phase-48 Pixelorama, and Phase-51 Blender dispatch boundaries follow the same no-replay law: once owner-specific DISPEXEC `STARTED` is durable, a BaseException/crash or post-evidence terminalization failure requires explicit recovery rather than a second automatic backend/editor call. For Blender, an exact durable dispatch-output binding can complete terminalization only after the same output/lineage evidence is independently revalidated; recovery never re-invokes Blender.

Phases 49 and 50 preserve that law across Pixelorama publication and acceptance: binding publication/currentness, terminal dispatch recovery, production adoption, Task acceptance, retry, and recovery never re-invoke Pixelorama. Exact durable output/adoption/acceptance evidence is consumed or rejected; it is not regenerated to make adoption or acceptance convenient.

Phases 52 and 53 preserve the same no-replay law across Blender canonical publication and Task acceptance. Adoption consumes only the exact current terminal Phase-51 binding/output; PREPARED ambiguity never triggers automatic overwrite, cleanup, or Blender replay. Acceptance consumes only the exact PUBLISHED Phase-52 adoption and current preacceptance GLB truth, reuses durable PASS/receipt state after interruption, and never re-invokes Blender or rewrites the canonical asset.

Phase 54 remains downstream of that accepted production history. Signing requires exact terminal Phase-53 currentness and current adopted bytes, never invokes or recovers Task acceptance, and never replays Blender or repairs the GLB. Re-signing happens only through another explicit operator invocation; no restart/recovery path automatically creates another provenance manifest.

Phase 55 remains downstream of the accepted Pixelorama production history. Signing requires exact terminal Phase-50 currentness and current adopted RGBA8 PNG bytes, never invokes or recovers Task acceptance, and never replays Pixelorama or repairs/re-encodes the PNG. Re-signing happens only through another explicit operator invocation; no restart/recovery path automatically creates another provenance manifest.

Phase 56 follows the same durable-evidence-first rule upstream of Phase 31. Once a DESIGNIN/DESIGNSPEC/DESIGNAUD or DESIGNACC exists, inspection and recovery consume those exact bytes; they do not rerun the design model to reconstruct evidence. A durable HUMAN_OPERATOR acceptance retry reuses the same exact DESIGNACC, while stale semantic/capability state or a competing candidate fails closed instead of regenerating, silently replacing, or auto-planning from the design.

## Current-development boundary

Current `main` does not grant:

- automatic merge or release authority;
- unrestricted shell/filesystem/process access;
- UI mutation workflows;
- automatic Artifact adoption or signing;
- automatic Dream promotion;
- production checkpoint/model activation;
- direct simulation execution, direct Pixelorama editor-execution commands, direct Blender production-execution commands, or automatic Task terminalization from simulation/export/adoption/advisory evidence;
- generic Pixelorama project creation/import/edit/save, arbitrary editor scripts/plugins, or automatic output adoption/signing;
- caller/model/browser-selected Pixelorama provenance target, Task/Run/Artifact/Verification/path/hash/parent-manifest authority, automatic signing, trust provisioning, private-key generation/storage, or signing-derived release authority;
- caller/model-selected Blender runtime/path/profile/version/runner/budget/workspace/output authority, automatic GLB adoption, or automatic/synthetic Blender Task acceptance;
- caller/model/browser-selected Blender provenance target, Task/Run/Artifact/Verification/path/hash/parent-manifest authority, automatic signing, trust provisioning, private-key generation/storage, or signing-derived release authority;
- model-, vision-, specialist-, Pixelorama-, Blender-, Manager-, dispatcher-, conversation-, browser-, or UI-synthesized semantic production acceptance;
- caller/model/browser-selected DESIGNIN/Goal/audit/hash/acceptance-authority substitution, automatic design acceptance, automatic PlanningInput creation during acceptance, automatic Planner execution, or Phase-56 Task materialization;
- Phase-56 mutation of Phase-17 Project Intelligence/Design Rules or use of DESIGNACC as reverse semantic authority;
- background Goal bootstrap, Manager scheduling/queue draining, production adoption, production Task acceptance, Blender execution/replay, Pixelorama execution/replay, design-specification generation/acceptance replay, or provenance signing;
- remote/multi-user cockpit hosting.

The Pixelorama post-dispatch mutation surfaces are exactly the explicit module commands documented above: Phase-49 create-only `adopt-production-new`, Phase-50 human-only `accept-production-task`, and Phase-55 explicit `sign-production-provenance`. None executes or replays the editor, selects or rewrites a different source, overwrites the canonical asset, authorizes release, or grants background/automatic authority. Only Phase 50 may request the existing verification-gated Task `RUNNING → SUCCEEDED` transition after exact currentness and HUMAN_OPERATOR acceptance are durable; Phase 55 requires that terminal acceptance first and may only create a Phase-18 immutable provenance manifest over the exact still-current adopted Artifact.

The Blender post-dispatch mutation surfaces are exactly the explicit module-only Phase-52 create-only `adopt-production-new`, Phase-53 human-only `accept-production-task`, and Phase-54 explicit `sign-production-provenance` commands documented above. None invokes or replays Blender, selects or rewrites a different source, overwrites the canonical asset, authorizes release, or grants background/automatic authority. Only Phase 53 may request the existing verification-gated Task `RUNNING → SUCCEEDED` transition after exact currentness and HUMAN_OPERATOR acceptance are durable; Phase 54 requires that terminal acceptance first and may only create a Phase-18 immutable provenance manifest over the exact still-current adopted Artifact.

The Phase-56 design-specification mutation surface is exactly the explicit module-only `accept-design-specification --design-specification-id DESIGNSPEC-*` command documented above. It may only publish or recover the exact HUMAN_OPERATOR DESIGNACC relation after current PASS-audited evidence validation. It does not generate a proposal, create PlanningInput automatically, execute Phase-31 planning, materialize Tasks, mutate semantic truth, sign provenance, or authorize release.

Origin Forge is licensed under the Apache License 2.0; see the repository `LICENSE` file. The immutable v0.5.0 release remains documented separately in `docs/v0.5-release-readiness.md`, `docs/v0.5-acceptance-matrix.md`, and `docs/v0.5-operator-guide.md`. Phases 48, 49, 50, 51, 52, 53, 54, 55, and 56 are explicitly post-v0.5 development.
