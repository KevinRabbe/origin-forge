# Phase 49 — Governed Pixelorama Production Output Adoption — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-49-governed-pixelorama-production-output-adoption.md`. Phase 49 is separately gated post-v0.5 development. It adopts only the exact durable PNG produced by the accepted Phase-48 Pixelorama spritesheet-export dispatch into one new canonical project path, while preserving create-only publication, exact dispatch provenance, no automatic replay, no Task terminalization, and separate provenance-signing authority.

Phase 49 does not rewrite the immutable v0.5 release and does not turn Pixelorama export structure or adoption integrity into aesthetic acceptance, Task PASS/FAIL, signing, merge, release, or deployment truth.

## Final production boundary

The accepted sequence is:

```text
already-governed media.2d.export Task
→ Phase-48 Pixelorama DISPEXEC STARTED
→ exactly one durable Pixelorama CLI export invocation
→ durable PIXELORAMA Run + request/result/PNG/Verification evidence
→ immutable Phase-49 dispatch-output binding
→ DISPEXEC RETURNED / claim CONSUMED
→ Task remains RUNNING
→ explicit human adoption request by exact DISPEXEC-* + new project-relative PNG path
→ full bound-output/currentness/evidence revalidation
→ durable PREPARED adoption reservation
→ immediate pre-publication currentness recheck
→ existing Phase-19 create-only byte publisher
→ adopted child Artifact + production adoption Verification
→ durable PUBLISHED adoption receipt
→ Task remains RUNNING
```

The production adoption path never invokes Pixelorama. The exact Phase-48 output bytes are the only source, and publication remains one new destination only.

## 49A — immutable dispatch-output binding

Phase 49A added schema v13 evidence binding one exact successful Pixelorama dispatch execution to the exact durable output relation required for later adoption.

The accepted immutable binding freezes:

- exact `DISPEXEC-*` and originating `DISPCLAIM-*` identities;
- exact Task revision/content hash and WorkOrder/binding relation;
- exact Pixelorama execution-owner identity;
- exact PIXELORAMA Run ID;
- exact request, result, and output Artifact IDs;
- exact output and Run Verification IDs;
- exact output SHA-256 digest and byte count;
- one schema-versioned no-overwrite row with uniqueness across execution, claim, Run, Artifacts, and Verifications.

Publication is idempotent only for the same exact immutable relation. A second execution cannot reuse the same Run/output identities, and a changed relation cannot be written under an existing execution ID.

49A adds no adoption, filesystem publication, Pixelorama invocation, Task transition, signing, merge, or release authority.

## 49B — invocation integration, no-replay recovery, and adoption currentness

Phase 49B moves binding publication into the accepted Phase-48 success boundary after durable result validation and before DISPEXEC RETURNED terminalization.

The accepted ordering is:

```text
Pixelorama owner returns
→ durable Phase-48 result validation
→ publish/reuse exact immutable output binding
→ DISPEXEC RETURNED / claim CONSUMED
→ return typed invocation result
```

This ordering preserves durable proof across the crash window where Pixelorama has already produced trustworthy evidence but dispatch terminalization fails. Explicit recovery uses only the exact durable binding/evidence and never invokes Pixelorama again merely to reconstruct a return value.

Adoption eligibility is separately recomputed from current durable truth. Eligibility requires the exact Pixelorama owner, exact immutable binding, exact Run/Artifact/Verification lineage and digest/size evidence, canonical DISPEXEC RETURNED state, consumed originating claim, and the exact RUNNING production Task relation. STARTED/ACTIVE, stale WorkOrder/binding/Task state, missing or tampered evidence, wrong owner, wrong Run, or output drift is non-authorizing.

49B leaves bounded-code and deterministic-simulation invocation semantics unchanged and adds no publication or Task outcome authority.

## 49C — production-aware create-only adoption and provenance evidence

Phase 49C adds schema v14 and one narrow durable `pixelorama_production_adoptions` receipt lifecycle:

```text
PREPARED → PUBLISHED
```

The receipt reserves exactly one execution/output for exactly one destination before the filesystem publication boundary. Uniqueness prevents one execution from fanning out to multiple destinations and prevents competing executions from claiming the same production output or destination.

The production coordinator:

- accepts only one exact `DISPEXEC-*` plus one caller-supplied new project-relative `.png` destination;
- requires Phase-49B adoption currentness before reservation;
- loads only the exact bound Phase-48 output Artifact and hash;
- delegates byte preparation/publication to the existing Phase-19 `GovernedPixeloramaOutputAdopter` internal create-only primitive rather than creating a second generic Artifact writer;
- rechecks currentness immediately before the atomic create-only link boundary;
- records the adopted child Artifact with exact parent/run lineage;
- records `pixelorama-production-adoption-integrity` PASS evidence under verifier `OriginForge.GovernedPixeloramaProductionOutputAdopter`;
- freezes exact execution, claim, Run, source Artifact, source/destination digest, byte count, and destination path evidence;
- explicitly records `production_dispatch_output_bound=true`, `production_task_verified=false`, `semantic_visual_quality_verified=false`, `provenance_signed=false`, and `existing_asset_overwritten=false`;
- finalizes the exact receipt to PUBLISHED only after re-reading and validating the full adopted Artifact/Verification relation.

The Phase-19 legacy `adopt-new` surface and its `pixelorama-output-integrity` verifier gate remain unchanged. Phase-48 production output does not silently become eligible through that legacy path.

A PREPARED receipt with no destination file is retryable against the same exact binding and destination. If the destination exists while the receipt remains PREPARED, recovery is deliberately ambiguous and fails closed: Origin Forge does not delete, replace, or guess ownership of the file.

## 49D — explicit operator surface and cross-phase adversarial acceptance

Phase 49D exposes the accepted production adopter through the existing module-only Pixelorama admin surface:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  adopt-production-new \
  <DISPEXEC-ID> \
  <new-project-relative-path.png>
```

The command accepts no Run ID, source Artifact ID/path, Task ID/revision, Pixelorama executable/profile, verifier override, signing material, overwrite flag, destination discovery policy, Manager selector, or replay control. The existing package scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Cross-phase acceptance proves:

- real Phase-48 dispatch output can be adopted through the explicit command without a second Pixelorama invocation;
- exact execution/claim/Task/Run/source Artifact/hash/byte provenance survives into the adopted result;
- the production Task remains RUNNING at the same revision and receives no Task Verification;
- provenance signing state remains untouched;
- missing binding, stale/tampered durable evidence, protected destinations, symlink parent escape, and source-byte-limit failure publish nothing;
- a bound STARTED execution with ACTIVE claim remains non-authorizing and is not replayed;
- two concurrent publishers for the same execution/destination produce at most one successful publication and one durable PUBLISHED receipt;
- a crash after the create-only filesystem link but before lineage/final receipt completion leaves an explicit PREPARED ambiguity that cannot be retried into overwrite or editor replay;
- the production adoption coordinator contains no Pixelorama execution, dispatch terminalization, Task transition, signing, generic merge, or release authority.

## Task, signing, Manager, bootstrap, packaging, and release boundaries preserved

After Phase 49, a trustworthy production adoption still leaves the canonical production Task `RUNNING`. The following remain separate authority questions:

```text
output was produced by the exact Phase-48 dispatch
output bytes were adopted create-only at the requested new path
semantic/aesthetic output quality is acceptable
Task acceptance criteria are satisfied
provenance should be signed
Task should terminalize
asset should merge/release/deploy
```

Phase 49 proves only the first two statements. It does not collapse them into later policy decisions.

Pixelorama execution remains reachable only through the existing governed preparation/claim/dispatch/Manager path. The new module command adopts already-terminal durable output and cannot launch Pixelorama or repair/replay a nonterminal execution.

Phase-45/46 Goal bootstrap remains code-only:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

The cockpit remains read-only. Packaging remains exactly three scripts. No daemon, watcher, poller, automatic adoption loop, queue drain, plugin route, or background scheduler is introduced.

The immutable v0.5 release remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 49 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Authority exclusions preserved

Phase 49 adds no:

- automatic adoption during Pixelorama export or Manager dispatch;
- second generic Artifact/file writer or overwrite/edit/manage-root bypass;
- source/output inference by Task, Run, path scan, newest file, or destination discovery;
- adoption from an unbound, STARTED, RAISED, INTERRUPTED, stale, or otherwise non-current dispatch execution;
- Pixelorama replay/retry while evaluating or performing adoption;
- arbitrary Pixelorama project creation/import/edit/save, extension/plugin/GDScript execution, executable/profile/argv/environment authority, or generic media dispatch;
- automatic visual/aesthetic acceptance, `production_task_verified=true`, Task Verification, Task SUCCEEDED/FAILED transition, Flow/Goal terminalization, or semantic policy decision;
- private-key access, automatic provenance manifest/signature creation, or trust-root mutation;
- fourth packaged command, cockpit mutation, HTTP/plugin mutation route, daemon, timer, watcher, poller, queue drain, or background adoption worker;
- automatic merge, release, deployment, or mutation of immutable v0.5 release records.

## Exact-head accepted evidence

- **Phase-49 planning — PR #120:** exact accepted head `e0ffb62a209c2d3e056b4d6438ec71050729a401` / normal run `31960330673` / #1442 passed Python 3.12 and Python 3.13; merged as `c4242506a7372e7afeb3eedf401d3e059c61b2dd`.
- **49A — immutable dispatch-output binding — PR #121:** exact accepted head `1596535cb032d32d95a3ace0cc8adee28ec9a6c7` / normal run `31961083674` / #1444 passed Python 3.12 and Python 3.13; merged as `e84d3978215aa3e7935a65ffb8181fd39df791c8`.
- **49B — invocation/currentness/recovery integration — PR #122:** exact accepted head `5c6915f798cb51b71ba44a163739ece8468cf0de` / normal run `31964939727` / #1446 passed Python 3.12 and Python 3.13; merged as `a5c367f96c8e9f48d9b709faa9354b29b9c1c5a8`.
- **49C — production-aware create-only adoption — PR #123:** exact accepted head `e735c0282241a7c5b973805645566b330a37930a` / normal run `32008755709` / #1458 passed Python 3.12 (`95323661205`) and Python 3.13 (`95323661240`); merged as `ea21a1a08a249369d573a5fd8371ecbbcb4e64b3`.
- **49D — explicit operator + adversarial acceptance — PR #124:** exact accepted head `eed300f40374b2b0213caf461d2cdf7ce596d70d` / normal run `32011087914` / #1464 passed Python 3.12 (`95330582421`) and Python 3.13 (`95330582363`); merged as `bb77eac4af6ddbc885050b993ffd1af811a70fdc`.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact merged Phase-49D main `bb77eac4af6ddbc885050b993ffd1af811a70fdc`.

The intended closure diff is exactly three documentation files. It may not modify production code, tests, schema, config, packaging, workflows, release metadata, or runtime authority. It must preserve the three packaged scripts, read-only cockpit boundary, code-only Phase-45/46 Goal bootstrap, bounded Manager/Pixelorama execution semantics, immutable v0.5 tag, create-only Phase-19 publisher authority, and separate Task/signing truth.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
