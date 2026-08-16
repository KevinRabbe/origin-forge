# Phase 48 — Governed Pixelorama Spritesheet Export Production Dispatch — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-48-governed-pixelorama-spritesheet-export-production-dispatch.md`. Phase 48 is post-v0.5 development and promotes only the already-proven Pixelorama v1.2 opaque-project spritesheet-export boundary into the governed production preparation/claim/execution path. It does not rewrite the immutable v0.5 release, promote generic Pixelorama project editing, or turn structural export evidence into Task truth.

## Final production boundary

An already-governed Task whose exact Phase-32 authority is:

```text
media.2d.export
→ originforge.pixelorama.export
→ pixelorama.spritesheet-export@1
```

may now proceed through the existing preparation and Manager path to exactly one reviewed Pixelorama execution owner.

The accepted production sequence is:

```text
QUEUED Pixelorama export Task
→ governed Phase-39 preparation / WorkOrder planning
→ exactly one ARTIFACT / pixelorama_project WorkOrder ref
→ metadata-only Phase-34 Artifact resolution + PASS-audited binding
→ exact Phase-35 claim
→ atomic Phase-36 DISPEXEC STARTED + Task READY→RUNNING
→ post-STARTED local .pxo materialization / containment / hash / size revalidation
→ fresh infrastructure-owned PXOP-* / MEDIA-* identities
→ exactly one durable Pixelorama CLI export service call
→ exactly one proven PixeloramaCliExportAdapter invocation
→ durable PIXELORAMA Run + request/result/export evidence
→ independent source/request/result/PNG/lineage revalidation
→ DISPEXEC RETURNED / claim CONSUMED
→ Task remains RUNNING
```

A normal Pixelorama return is dispatch-completion and structural-export evidence only. It is not aesthetic acceptance, Task PASS/FAIL, canonical asset adoption, provenance signing, merge, release, or deployment authority.

## 48A — exact spritesheet-export WorkOrder contract

Phase 48A added only the reviewed `pixelorama.spritesheet-export@1` dispatch contract.

The accepted contract:

- belongs only to `originforge.pixelorama.export`;
- requires exactly one `ARTIFACT` input ref with role `pixelorama_project`;
- uses canonical payload `{}` and grants no caller/model-selected operation, path, executable, profile, timeout, argv, environment, workspace, PXOP/MEDIA identity, adoption, signing, or Task authority;
- appears only for an explicit Pixelorama-capable Phase-32 catalog;
- preserves existing code-only and simulation-only contract behavior;
- preserves the Phase-45/46 full/global Goal-bootstrap dispatch catalog as code-only;
- keeps mixed non-code reviewed catalogs fail closed rather than selecting by order.

No Phase-34 binding, Artifact byte read, editor process, or execution owner was introduced in 48A.

## 48B — metadata-only Artifact binding/currentness

Phase 48B added one exact Pixelorama binder over the existing `ArtifactInputResolver` metadata projection.

The accepted binder:

- requires the exact one `pixelorama_project` WorkOrder ref;
- requires a project-owned `PIXELORAMA_PROJECT` Artifact in `PRODUCED` state;
- binds the stored Artifact identity, path metadata, and exact content hash without opening source bytes;
- allows the existing resolver's safe metadata superset while consuming only the fields required by the Pixelorama request relation;
- remains inert: no process call, source materialization, profile lookup, workspace allocation, Run, or Task transition occurs.

The generic Artifact resolver and core production-dispatch binding semantics remain unchanged.

## 48C — separate Pixelorama preparation authority

Phase 48C added the code-owned preparation owner:

```text
originforge.preparation.pixelorama-spritesheet-export-planner@1
```

Pixelorama preparation reuses the existing one-shot governed WorkOrder Planner and keeps planner role `CODER_STRONG`. A Pixelorama-only DISPCAT resolves exactly the Pixelorama preparation owner. Code-only and simulation-only catalogs retain their existing owners; any catalog resolving multiple preparation owners fails closed rather than using ordering as fallback authority.

Phase-45/46 Goal bootstrap remains code-only. Preparation still stops before Artifact byte reads, Pixelorama profile/process use, execution ownership, or Task execution.

## 48D — zero-model Pixelorama execution owner and atomic start

Phase 48D added the exact execution owner:

```text
originforge.execution.pixelorama.spritesheet-export@1
```

Its dependency assembly is owner-specific and requires the infrastructure-owned trusted Pixelorama CLI profile, but no:

- model scheduling/runtime/provider allocation;
- resource scheduler lease;
- managed llama.cpp runtime;
- coding sandbox;
- Git Workspace manager;
- bounded coding retry policy.

For Pixelorama only, Phase 36 atomically commits the exact DISPEXEC `STARTED` receipt together with the exact Task `READY → RUNNING` transition. Rollback tests prove neither side persists alone. Phase 48D deliberately stops before reading `.pxo` bytes or invoking Pixelorama.

A narrow persisted-currentness repair was accepted immediately after 48D because real reconstruction exposed one historical assumption: the Phase-34 read path had treated all production WorkOrders as zero-ref. The repair recognizes only the already-reviewed one `ARTIFACT / pixelorama_project` Pixelorama shape; every unrelated nonzero-ref shape still fails closed.

## 48E — durable direct CLI export service

Phase 48E introduced the durable service wrapper around the already-proven Phase-19 direct CLI export adapter.

The service:

- requires the exact RUNNING production Task;
- creates one dedicated Pixelorama Run;
- durably binds the exact `PixeloramaCliExportRequest`;
- calls the existing `PixeloramaCliExportAdapter.execute(...)` exactly once;
- persists exact typed result evidence and the exported PNG Artifact;
- independently reopens, rehashes, and structurally re-inspects the PNG;
- records a Run-level PASS Verification binding source/request/result/export lineage;
- finishes only the Pixelorama Run;
- leaves the production Task RUNNING;
- exposes no adoption, signing, Task terminalization, merge, release, project-create/import/save, plugin, or arbitrary-script authority.

The direct adapter's existing executable/version, no-shell, containment, source-hash, exact-output-set, PNG, timeout, and output-bound checks remain authoritative rather than being replaced by weaker service checks.

## 48F — post-STARTED invocation and cross-phase adversarial acceptance

Phase 48F completed the production integration and adversarial acceptance on the real Manager/preparation/claim/execution path.

The accepted Pixelorama branch of the single public `dispatch_claim_once(...)` coordinator:

- revalidates the exact owner, active claim, binding audit, binder/request relation, trusted profile, and STARTED/RUNNING execution ownership;
- opens the source only after STARTED, rejecting URI/absolute/escaped/protected/symlink/non-file/non-`.pxo` sources;
- rehashes the local source and requires equality with the frozen Artifact hash while deriving a bounded byte count;
- allocates fresh code-owned `PXOP-*` and `MEDIA-*` identities and fixed `inputs/source.pxo` / `exports/spritesheet.png` paths only after STARTED;
- calls the durable Phase-48E service at most once;
- requires a typed service result and independently revalidates the durable PIXELORAMA Run, request/result evidence, output Artifact, PNG structure, source binding, hashes, and Verification lineage before recording RETURNED;
- records ordinary owner exceptions as RAISED/CONSUMED without Task outcome authority;
- preserves BaseException/crash uncertainty as STARTED/ACTIVE/RUNNING and never automatically replays the editor;
- preserves already-durable output during later dispatch-terminalization uncertainty rather than launching Pixelorama again;
- never falls through to a newer Task after selection or a claim race.

Cross-phase acceptance also exposed two legacy Phase-39 zero-ref assumptions outside the Pixelorama owner itself. Both were repaired narrowly:

1. persisted preparation-status reconstruction now accepts exactly the reviewed one-ref Pixelorama WorkOrder and requires planner `allowed_input_refs == len(work_order.input_refs)`;
2. post-planner evidence recovery/finalization reconstructs that same exact typed one-ref Pixelorama WorkOrder instead of rejecting every nonzero-ref result.

Non-Pixelorama planner evidence remains zero-ref only. Existing bounded-code and deterministic-simulation call sites and no-fallback semantics remain unchanged.

Concurrency acceptance follows the established Phase-47 law: two Managers pinned to the same selected candidate prove the exact claim winner/loser boundary and at-most-once downstream authority. Scheduler timing is not required to make the winner reach the editor process on every interpreter schedule. The newer Task receives no claim, execution, materialization, Run, or editor invocation.

## Manager, Goal-bootstrap, packaging, and release boundaries preserved

Pixelorama production execution is reachable only through already-governed Task/materialization/preparation/claim authority and the existing explicit:

```bash
origin-forge --project-root /path/to/project manager advance
```

There is no direct mutating Pixelorama production command. `manager advance` remains bounded and stops on the first dispatch result; it does not reinterpret Pixelorama output into Task acceptance truth or automatically continue to another Task.

Phase-45/46 Goal bootstrap remains exactly:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

It does not acquire `media.2d.export` authority and still stops at GOALBOOT READY before Manager invocation.

Packaging remains exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The cockpit remains read-only.

The immutable v0.5 release remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 48 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Final closed production owner set

After Phase 48, the code-owned production execution owner set is exactly:

```text
originforge.execution.bounded-retry@1
originforge.execution.simulation.deterministic@1
originforge.execution.pixelorama.spritesheet-export@1
```

The coordinator remains hard-coded to reviewed owner branches. Phase 48 adds no plugin registry, dynamic import, reflection-based backend selection, arbitrary tool execution, model-selected owner, caller-selected owner, or generic media dispatch.

## Authority exclusions preserved

Phase 48 adds no:

- `CREATE_SPRITE_PROJECT`, `IMPORT_LAYER_PNG`, editing, animation, or `SAVE_PROJECT` production dispatch;
- generic `PixeloramaBridgeAdapter` project-editing promotion;
- arbitrary Extension API/plugin/GDScript execution;
- caller/model-selected source/output host path, Pixelorama executable/profile/version, argv/environment, runtime, model, resource, sandbox, workspace, PXOP, MEDIA, or dispatch owner;
- pre-STARTED `.pxo` byte read or Pixelorama process call;
- automatic editor replay/retry after durable STARTED uncertainty;
- visual/aesthetic acceptance or automatic Task Verification/terminalization;
- automatic canonical asset adoption or destination selection;
- private-key access or automatic provenance signing;
- automatic Goal-bootstrap media authority or bootstrap→Manager chaining;
- fourth package entrypoint, mutating cockpit/HTTP/plugin route, daemon, watcher, poller, timer, background queue drain, or remote editor service;
- automatic merge, release, deployment, or mutation of immutable v0.5 release records.

## Exact-head accepted evidence

- **Phase-48 planning — PR #108:** exact accepted head `52411df4e876a7bb2c0a2fc6023e15abb6eb87c4` / normal run `31915469094` / #1369 passed Python 3.12 and Python 3.13; merged as `e52a101e578783c7731bdde0d53051a586f5791a`.
- **48A — exact WorkOrder contract — PR #109:** exact accepted head `c6e328575db4ecaa7b0ca3c191ede56f42857f92` / normal run `31915910291` / #1371 passed Python 3.12 and Python 3.13; merged as `d0097e521b94aa2e576f3f3afb8acb09c8147ecf`.
- **48B — Artifact metadata binding/currentness — PR #110:** exact accepted head `78e86b4da53be894be2223ee807ba208d42f618a` / normal run `31922527176` / #1374 passed Python 3.12 and Python 3.13; merged as `dc189925778498ab27bca57b78f97902a6f6d3e2`.
- **48C — Pixelorama preparation owner — PR #111:** exact accepted head `12e10bcbbba5a19d286dbd924ef1270ef929b900` / normal run `31926045992` / #1376 passed Python 3.12 and Python 3.13; merged as `4101b1568f1effdbc8e595afc558bce76cafc942`.
- **48D — execution owner + atomic start — PR #112:** exact accepted head `66d8c52d4d8f57eed43ddb376a06981ea0bf71e1` / normal run `31929383977` / #1382 passed Python 3.12 and Python 3.13; merged as `4ebaba55efec22382fa0b47b43202aa152ee07f8`.
- **Phase-34 persisted Pixelorama currentness repair — PR #113:** exact accepted head `4e3bafee120232f607c6405c1dfee6acb33b8845` / normal run `31929132808` / #1380 passed Python 3.12 and Python 3.13; merged as `b05658dc37bd6bfd42c7c04b29b48821b4d0d128`.
- **48E — durable direct CLI export service — PR #114:** exact accepted head `2e1131c85adf3039cd2685c7380300ebfdc6b7ea` / normal run `31930898625` / #1384 passed Python 3.12 and Python 3.13; merged as `c1072a0f8c1526331f9f0797b10168061943206f`.
- **48F — invocation integration + cross-phase adversarial acceptance — PR #115:** exact accepted head `68315a50526ac00634ce03d26e669a7053c8ace1`; normal run `31945142450` / #1433 passed Python 3.12 and Python 3.13; the final net diff contains exactly 15 source/test files and no helper-workflow residue; merged as `16eb0cd631ec572d07605209cb8ca29a1c5f3db9`.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact merged Phase-48F main `16eb0cd631ec572d07605209cb8ca29a1c5f3db9`.

The intended closure diff is exactly three documentation files. It may not modify production code, tests, schema, config, packaging, workflows in the final tree, or runtime authority. It must preserve the three packaged scripts, read-only cockpit boundary, code-only Phase-45/46 Goal bootstrap, bounded Manager semantics, immutable v0.5 tag, and the accepted three-owner production invocation surface.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
