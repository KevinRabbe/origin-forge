# Phase 50 — Governed Pixelorama Production Task Acceptance — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-50-governed-pixelorama-production-task-acceptance.md`. Phase 50 is post-v0.5 development. It adds one narrow explicit human acceptance boundary over the exact already-governed Phase-48/49 Pixelorama production relation, publishes one immutable Task-targeted PASS bound to that exact production result, and then delegates the canonical `RUNNING → SUCCEEDED` transition to the existing runtime/store Task state machine.

Phase 50 does **not** make Pixelorama, vision, specialists, Manager, structural adoption evidence, or an unrelated PASS authoritative for semantic production acceptance. It does not replay the editor, rewrite the adopted asset, sign provenance, authorize release, or transition the parent Flow or Goal.

## Final production-acceptance boundary

The accepted production sequence is:

```text
Phase-48 Pixelorama DISPEXEC RETURNED / claim CONSUMED
→ exact immutable dispatch-output binding
→ Phase-49 PUBLISHED production-adoption receipt
→ exact adopted SPRITESHEET_EXPORT Artifact + adoption-integrity PASS
→ exact current canonical RGBA8 PNG bytes
→ exact still-RUNNING production Task
→ explicit human accept-production-task DISPEXEC-* action
→ one immutable pixelorama_production_task_acceptances row
→ one Task-targeted pixelorama-production-task-acceptance PASS
→ revalidate exact acceptance/currentness
→ existing OriginForgeRuntime.transition_task(...SUCCEEDED...)
→ Task RUNNING → SUCCEEDED
```

The infrastructure derives the Task, Run, output Artifact, adopted Artifact, adoption Verification, destination, hashes, and byte count from the explicit DISPEXEC identity. The operator supplies only the explicit human acceptance action for that one exact durable relation.

## 50A — immutable acceptance authority and atomic Task PASS

Phase 50A added schema version 15 and the narrow immutable `pixelorama_production_task_acceptances` relation.

The accepted relation is one-to-one across:

- dispatch execution;
- production Task;
- adopted Artifact;
- Phase-49 adoption Verification;
- Phase-50 Task Verification.

The publisher receives a prevalidated exact Phase-49 snapshot and atomically commits:

- exactly one fixed `pixelorama-production-task-acceptance` PASS Verification targeting the exact Task;
- the normal `VERIFICATION_RECORDED` event;
- exactly one immutable acceptance row referencing that PASS.

The frozen PASS authority is infrastructure-owned:

```text
verification_type = pixelorama-production-task-acceptance
verifier = OriginForge.GovernedPixeloramaProductionTaskAcceptor
status = PASS
acceptance_authority = HUMAN_OPERATOR
production_task_verified = true
semantic_visual_quality_verified = true
production_dispatch_output_bound = true
canonical_asset_adopted = true
existing_asset_overwritten = false
provenance_signed = false
release_authorized = false
```

The caller cannot override those semantics. Exact replay is idempotent and reuses the same row/PASS. Conflicting execution/Task/adoption/Artifact/Verification/content/revision relations fail closed. Acceptance rows are immutable; there is no update lifecycle or generic Verification-uniqueness redesign.

50A deliberately stops before live filesystem/currentness checks and before Task terminalization.

## 50B — exact live currentness, canonical terminalization, and recovery

Phase 50B added the read-only currentness projection and `GovernedPixeloramaProductionTaskAcceptor`.

Before first acceptance, and again before completing a pending transition, the acceptor reconstructs and revalidates the exact Phase-48/49 durable relation from one explicit DISPEXEC identity, including:

- immutable dispatch-output binding;
- exact Pixelorama execution owner;
- DISPEXEC `RETURNED` and claim `CONSUMED`;
- exact frozen Task relation;
- exact PIXELORAMA Run/request/result/output/Verification lineage;
- exact PUBLISHED Phase-49 adoption receipt;
- exact adopted `SPRITESHEET_EXPORT` Artifact and adoption-integrity PASS;
- exact project-relative canonical destination;
- regular-file/non-symlink containment;
- exact current content hash and byte count;
- accepted RGBA8 PNG structure;
- exact Task lifecycle/revision and existing child-Task success law.

Only after that currentness proof does it reuse the 50A atomic acceptance publisher and request the existing runtime transition to `SUCCEEDED`. There is no direct `tasks.status` update and no second Task state machine.

The expected crash boundary is supported:

```text
Phase-50 PASS + acceptance receipt durable
Task still RUNNING
```

Retry revalidates the same exact durable relation, reuses the existing PASS/receipt, and may finish the canonical Task transition without creating a second acceptance. An exact already-SUCCEEDED replay is idempotent only when the same Phase-50 acceptance remains the historical basis for that state.

Pixelorama is never invoked during acceptance or recovery. The canonical adopted file is never rewritten to make currentness pass. After successful terminalization the acceptance remains historical evidence; later asset drift does not retroactively rewrite the accepted Task history.

## 50C — explicit operator surface

Phase 50C extended only the existing module-operated Pixelorama admin family:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  accept-production-task DISPEXEC-...
```

No fourth installed package script was added.

The operator supplies only the explicit dispatch execution identity. The command delegates once to `GovernedPixeloramaProductionTaskAcceptor`, prints the existing deterministic structured JSON result/error shape, and exposes no Task ID, Run ID, Artifact ID, path, verifier, model, signing/release, force, overwrite, or bypass input.

The command does not invoke Manager, Pixelorama, vision, a specialist, provenance signing, release, or a background worker.

## 50D — cross-phase adversarial acceptance

Phase 50D added a test-only cross-phase adversarial gate over real temporary-project Phase-48 → Phase-49 → Phase-50 durable state. No production file changed in the accepted 50D delta.

The accepted gate covers the missing Phase-50-specific attack surface, including:

- missing dispatch-output binding;
- tampered frozen DispatchExecution Task identity;
- internally valid non-RETURNED execution / non-CONSUMED claim state;
- stale Task revision;
- valid-but-wrong Run binding and wrong output lineage;
- missing or non-PUBLISHED production-adoption receipt;
- wrong adopted Artifact and wrong adoption Verification;
- canonical destination symlink drift;
- immutable acceptance-row rewrite rejection;
- concurrent identical human acceptance converging on one PASS, one receipt, and one Task transition;
- concurrent Task revision change after acceptance publication without force terminalization;
- unrelated Task PASS, favorable vision-style PASS, and specialist-style PASS remaining non-authoritative;
- no Pixelorama replay or asset rewrite during acceptance;
- no automatic signing/release or parent Flow/Goal transition;
- exactly the existing three installed package scripts.

Existing 50B tests remain the authoritative focused coverage for current canonical byte drift, incomplete child Tasks, crash-after-PASS recovery, and exact already-SUCCEEDED idempotence. The repository-wide canonical suite continues to prove unchanged legacy Phase-19 adoption, bounded-code execution, deterministic simulation, Goal bootstrap, Manager, cockpit, provenance, and other established authority boundaries.

The first 50D candidate correctly failed on both interpreters because five adversarial tests attempted impossible database rewrites or overconstrained race/diagnostic behavior. The accepted test-only repair changed no production semantics: it used the database-valid STARTED/ACTIVE durable shape, asserted the existing acceptance immutability trigger instead of bypassing it, and judged concurrent acceptance by the canonical final durable state. The repaired exact head then passed the full Python 3.12/3.13 matrix.

## Final authority exclusions preserved

Phase 50 adds no:

- model-, vision-, specialist-, Pixelorama-, Manager-, or dispatcher-owned semantic Task acceptance;
- automatic negative acceptance, Task failure, repair, redispatch, or replacement policy;
- caller-selected Task, Run, Artifact, Verification, destination, source, verifier, model, editor profile, or acceptance status;
- direct Task-table mutation or second Task terminalization state machine;
- weakening of child-Task completeness or optimistic revision checks;
- Pixelorama replay/re-execution during acceptance, currentness, retry, or recovery;
- canonical asset overwrite, rewrite, delete, replace, force, or republish authority;
- automatic provenance signing, private-key access, release, deployment, or merge authority;
- automatic parent Flow/Goal transition;
- generic production-acceptance owner registry or plugin system;
- code/simulation acceptance authority;
- legacy Phase-19 adoption promotion into production Task acceptance;
- Goal-bootstrap or bounded-Manager authority drift;
- fourth installed package entrypoint;
- mutating cockpit/HTTP route, daemon, watcher, poller, timer, queue, or background acceptance service;
- mutation of immutable v0.5 release records.

## Packaging and immutable release boundaries preserved

Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Both production adoption and production Task acceptance remain explicit module commands under `origin_forge.pixelorama_admin_cli`; neither is a new package entrypoint.

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

Phase 50 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Exact-head accepted evidence

- **Phase-50 planning — PR #126:** exact accepted head `eef3d4c3c8ee57607754dc2b7b7d9aad3f074bc6` / normal run `32033866391` / #1468 passed Python 3.12 and Python 3.13; merged as `4f2a10a0a9eeebc6fd8b8cd3da852ef32769d131`.
- **50A — immutable acceptance authority — PR #127:** exact accepted head `4dd69dac806350ed9512d7b4121faf5f951103e1` / normal run `32086705921` / #1471 passed Python 3.12 and Python 3.13; merged as `3b9fc838867e7cf5b5857f62103d07b5318a06d9`.
- **50B — currentness/terminalization/recovery — PR #128:** exact accepted head `c23fcd1de41c0711e92a86a3d70088f7648ea743` / normal run `32145375055` / #1474 passed Python 3.12 and Python 3.13; merged as `913feb62cb613c18ee09c6ae48870c4c6e49c9df`.
- **50C — explicit acceptance CLI — PR #129:** exact accepted head `06f931622ab01d66051ff69bde3d0aa53f281871` / normal run `32153162973` / #1478 passed Python 3.12 and Python 3.13; merged as `ffa6ea656d91ade752de9d2f8a3e11d9928f5093`.
- **50D — cross-phase adversarial acceptance — PR #130:** exact accepted head `abe96a01a15877a4bca08462dafca222e384f5dd` / normal run `32192102875` / #1481 passed Python 3.12 job `95888443271` and Python 3.13 job `95888443368`; merged as `6375fb7e00de21d402d933370b1a7ee5a024409a`.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact merged Phase-50D main `6375fb7e00de21d402d933370b1a7ee5a024409a`.

The intended final net diff is exactly three documentation files:

```text
docs/phase-50-implementation-closure.md
docs/operator-guide.md
docs/roadmap.md
```

It may not modify production code, tests, schema, config, packaging, workflows, runtime authority, or immutable release records. It must preserve the three packaged scripts, read-only cockpit boundary, code-only Phase-45/46 Goal bootstrap, bounded Manager semantics, no editor replay, explicit human-only acceptance authority, no automatic signing/release, and immutable v0.5 tag.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
