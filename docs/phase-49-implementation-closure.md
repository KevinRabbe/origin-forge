# Phase 49 — Governed Pixelorama Production Output Adoption — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-49-governed-pixelorama-production-output-adoption.md`. Phase 49 is post-v0.5 development. It adds the durable authority needed to bind one exact successful Phase-48 Pixelorama dispatch to one exact exported output and then allows a human operator to publish those exact bytes once, create-only, into a new canonical project path.

Phase 49 does **not** turn structural export/adoption evidence into Task acceptance, semantic or aesthetic quality, provenance signing, overwrite authority, release authority, or automatic Manager behavior.

## Final production-adoption boundary

The accepted production sequence is:

```text
Phase-48 Pixelorama DISPEXEC STARTED
→ exactly one durable Pixelorama CLI export invocation
→ exact PIXELORAMA Run/request/result/export/Verification evidence
→ immutable DISPEXEC → output binding persisted
→ DISPEXEC RETURNED / claim CONSUMED
→ explicit human adopt-production-new request
→ revalidate exact binding + RETURNED/CONSUMED/current RUNNING Task relation
→ reopen/revalidate exact bound output bytes
→ reserve one execution/output for one destination
→ Phase-19 create-only publication primitive
→ one child SPRITESHEET_EXPORT Artifact, status ADOPTED
→ one production-bound adoption-integrity PASS Verification
→ Task remains RUNNING
→ provenance remains unsigned
```

A successful Phase-49 production adoption means only that Origin Forge safely published the exact structurally verified bytes produced by one exact terminal Pixelorama production dispatch. It does not prove that the output satisfies semantic/aesthetic requirements and it does not complete or fail the production Task.

## 49A — immutable Pixelorama dispatch-output binding

Phase 49A added schema version 13 and the narrow `pixelorama_dispatch_output_bindings` relation.

The accepted relation is immutable and one-to-one across the exact production identities:

- DISPEXEC identity;
- claim identity;
- frozen Task/WorkOrder/dispatch-binding authority;
- exact Pixelorama execution owner;
- PIXELORAMA Run;
- request/result/output Artifacts;
- output and Run Verifications;
- exact output SHA-256 and byte count.

Database uniqueness prevents a second execution from reusing the same claim, Run, request, result, output, or Verification identities. Publication is insert-or-identical idempotent; any differing duplicate or frozen execution drift fails closed. No invocation, adoption, signing, Task transition, or operator command was introduced in 49A.

## 49B — invocation integration, durable recovery, and adoption eligibility

Phase 49B integrated the immutable binding into the reviewed Pixelorama dispatch path after strict durable Phase-48 result revalidation and before `RETURNED` terminalization:

```text
PixeloramaCliExportService.execute(...)
→ durable result revalidation
→ publish/reuse exact immutable binding
→ DISPEXEC RETURNED / claim CONSUMED
```

This ordering intentionally permits one crash state: an exact binding may coexist with `DISPEXEC STARTED` if terminalization fails after the editor result is already durable. That binding is recovery evidence only; it does not authorize adoption.

The accepted recovery path is keyed by the exact DISPEXEC identity, requires the exact immutable binding and exact durable Run/Artifact/Verification evidence, and completes `STARTED → RETURNED` without invoking Pixelorama again. Missing/ambiguous/tampered evidence fails closed rather than recreating output.

The read-only currentness/eligibility projection requires at minimum:

- exact Pixelorama owner;
- exact immutable binding;
- `DISPEXEC RETURNED`;
- exact claim `CONSUMED` relation;
- Task still `RUNNING` under the frozen execution relation;
- exact bound PIXELORAMA Run and Artifact lineage;
- exact PASS output/Run Verifications;
- current output path containment, bytes, hash, byte count, and PNG structure.

`adoption_eligible=true` is not Task truth. `production_task_verified` remains false.

Code and deterministic-simulation invocation semantics remain delegated to their existing owners unchanged.

## 49C — explicit create-only production adoption

Phase 49C added schema version 14 and the narrow `pixelorama_production_adoptions` receipt table together with `GovernedPixeloramaProductionOutputAdopter`.

The production coordinator accepts only:

- one exact `DISPEXEC-*` identity;
- one new project-relative destination;
- the existing bounded source-byte limit.

It derives the source Artifact/Run/claim relation only from the immutable binding. It does not accept an arbitrary source Artifact, source path/URI, Run ID, Task selector, verifier override, Pixelorama executable/profile, signing material, overwrite flag, or automatic destination selector.

The coordinator reuses the existing Phase-19 create-only publication mechanics rather than introducing a second weaker file copier. It preserves:

- protected-root and symlink rejection;
- bounded source reads;
- independent source/copy hashing;
- create-only final link publication;
- refusal of every pre-existing destination;
- child Artifact creation and independent adoption Verification evidence.

The new production-specific PASS evidence binds the adopted Artifact back to the exact dispatch execution/output relation and keeps:

```text
existing_asset_overwritten = false
production_dispatch_output_bound = true
production_task_verified = false
semantic_visual_quality_verified = false
provenance_signed = false
```

One bound execution/output may be canonically adopted at most once. A PREPARED receipt may be retried only while the reserved destination is still absent. A destination present beside a PREPARED receipt is an ambiguous post-publication state and fails closed as explicit operator-recovery-required; automatic retry never deletes or overwrites it.

The legacy Phase-19 `adopt-new` path keeps its existing verifier gate and does not gain direct production authority merely because a Phase-48 output exists.

## 49D — operator surface and adversarial acceptance

Phase 49D extended only the existing module-operated Pixelorama admin command family:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  adopt-production-new DISPEXEC-... path/to/new_asset.png
```

No fourth installed package script was added. The command is explicit and human operated; it invokes the production adopter once and does not watch, poll, replay Pixelorama, sign provenance, transition the Task, or invoke Manager.

Cross-phase acceptance exercises the real temporary-project chain from Phase-48 dispatch evidence through explicit production adoption and covers fail-closed behavior for:

- missing/tampered binding/evidence;
- nonterminal or otherwise ineligible dispatch state;
- source-byte drift and byte limits;
- protected and symlinked destinations;
- repeated adoption and execution fan-out;
- concurrent destination appearance;
- PREPARED/post-link crash ambiguity;
- no Pixelorama replay;
- no automatic signing;
- no Task Verification or terminal transition;
- unchanged legacy Phase-19 adoption behavior;
- unchanged package entrypoint count.

The cockpit remains read-only.

## Final authority exclusions preserved

Phase 49 adds no:

- Task PASS/FAIL Verification or Task `SUCCEEDED`/`FAILED` transition;
- semantic/aesthetic image acceptance or Visual Critic authority;
- automatic provenance signing or private-key access;
- overwrite, force, replace, edit-in-place, or destination-selection authority;
- automatic adoption from Manager/dispatcher execution;
- production adoption from Task-only, Run-only, path-only, or Artifact-only inference;
- legacy-output backfill without an exact durable DISPEXEC binding;
- Pixelorama replay/re-execution during binding, currentness, adoption, retry, or recovery;
- generic production-output registry/plugin system;
- caller/model-selected Pixelorama executable/profile/runtime/process settings;
- caller/model-selected source Artifact/path/URI or verifier;
- broad global Verification uniqueness redesign;
- code/simulation/Goal-bootstrap authority drift;
- fourth installed package entrypoint;
- mutating cockpit/HTTP route, daemon, watcher, poller, timer, or background adoption queue;
- automatic merge, release, deployment, or mutation of immutable v0.5 release records.

## Packaging and immutable release boundaries preserved

Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The explicit production-adoption operator remains a module command under `origin_forge.pixelorama_admin_cli`; it is not a new package entrypoint.

Phase-45/46 Goal bootstrap remains code-only:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

The immutable v0.5 release remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 49 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Exact-head accepted evidence

- **Phase-49 planning — PR #120:** exact accepted head `e0ffb62a209c2d3e056b4d6438ec71050729a401` / normal run `31960330673` / #1442 passed Python 3.12 and Python 3.13; merged as `c4242506a7372e7afeb3eedf401d3e059c61b2dd`.
- **49A — immutable dispatch-output binding — PR #121:** exact accepted head `1596535cb032d32d95a3ace0cc8adee28ec9a6c7` / normal run `31961083674` / #1444 passed Python 3.12 and Python 3.13; merged as `e84d3978215aa3e7935a65ffb8181fd39df791c8`.
- **49B — invocation/recovery/currentness integration — PR #122:** exact accepted head `5c6915f798cb51b71ba44a163739ece8468cf0de` / normal run `31969954756` / #1453 passed Python 3.12 and Python 3.13; merged as `a5c367f96c8e9f48d9b709faa9354b29b9c1c5a8`.
- **49C — explicit production adoption — PR #123:** exact accepted head `e735c0282241a7c5b973805645566b330a37930a` / normal run `32008755709` / #1458 passed Python 3.12 job `95323661205` and Python 3.13 job `95323661240`; merged as `ea21a1a08a249369d573a5fd8371ecbbcb4e64b3`.
- **49D — operator + adversarial acceptance — PR #124:** exact accepted head `eed300f40374b2b0213caf461d2cdf7ce596d70d` / normal run `32011087914` / #1464 passed Python 3.12 job `95330582421` and Python 3.13 job `95330582363`; merged as `bb77eac4af6ddbc885050b993ffd1af811a70fdc`.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact merged Phase-49D main `bb77eac4af6ddbc885050b993ffd1af811a70fdc`.

The intended final net diff is exactly three documentation files:

```text
docs/phase-49-implementation-closure.md
docs/operator-guide.md
docs/roadmap.md
```

It may not modify production code, tests, schema, config, packaging, workflows, runtime authority, or immutable release records. It must preserve the three packaged scripts, read-only cockpit boundary, code-only Phase-45/46 Goal bootstrap, bounded Manager semantics, no editor replay, no Task outcome authority, no automatic signing, and immutable v0.5 tag.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
