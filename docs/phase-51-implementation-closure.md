# Phase 51 — Governed Blender 3D Production Dispatch — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-51-governed-blender-3d-production-dispatch.md`. Phase 51 is post-v0.5 development. It promotes exactly the already-proven Phase-20C Blender GLB backend through the governed Phase-33/34/35/36/37/39 production chain by first adding a protected semantic `MODEL3DREQ-*` request boundary and then preserving runtime identity, path, profile, budget, execution, and recovery authority inside infrastructure-owned post-STARTED execution.

Phase 51 does **not** adopt the produced GLB into canonical project state, accept or terminalize the production Task, sign provenance, merge, release, or widen Goal-bootstrap authority. A trustworthy normal return proves only that one exact protected semantic 3D request was executed through the reviewed Blender boundary and produced independently revalidated durable GLB evidence while the production Task remains `RUNNING`.

## Final governed Blender production boundary

The accepted sequence is:

```text
exact protected MODEL3DREQ-* semantic request
→ Phase-39 Blender preparation owner / bounded planner allow-list
→ exact Phase-33 WorkOrder MODEL3D_REQUEST ref
→ exact Phase-34 protected resolver + blender.export-glb@1 binder/audit
→ Phase-35 exclusive ACTIVE dispatch claim
→ Phase-36 Blender owner STARTED + Task READY→RUNNING
→ only now allocate fresh BLOP-* + MODEL3D-* identities
→ infrastructure-owned trusted Blender profile + fixed exports/model.glb + BlenderBudget()
→ existing governed Phase-20C Blender adapter exactly once
→ durable request/result/GLB Artifact + Run/Verification lineage
→ independently re-read/reinspect exact GLB bytes and evidence
→ immutable DISPEXEC→durable-output binding
→ DISPEXEC RETURNED / claim CONSUMED
→ STOP with Task RUNNING
```

If the Blender output becomes durable but dispatch terminalization fails, the immutable output binding is recovery evidence. Explicit recovery revalidates that exact durable relation and may finish RETURNED/CONSUMED without invoking Blender again.

## 51A — protected semantic MODEL3D request substrate

51A added infrastructure-owned `MODEL3DREQ-*` identity and a separate immutable `Model3DProductionRequest` containing only fixed `EXPORT_GLB` semantics plus the canonical Phase-20A `BlockbenchProjectSpec`.

The protected `.origin-forge/model3d-requests/` registry is create-only and content-addressed. Exact non-creating ID/hash reads enforce canonical UTF-8 JSON, duplicate-key rejection, exact request/project hash recomputation, byte/count bounds, no symlink/alias escape, and no-overwrite publication.

The semantic request deliberately excludes all execution-owned state: `BLOP-*`, `MODEL3D-*`, filesystem paths, runtime root/executable, runner fingerprint, runtime hash, Blender version, argv/environment, process/log/output budgets, resource/model/sandbox/Git-Workspace selection, adoption destination, Task outcome, signing, merge, and release authority.

## 51B — exact WorkOrder ref, resolver, Blender contract, and binder

51B added `WorkOrderRefType.MODEL3D_REQUEST`, exact protected `MODEL3DREQ-*` resolution, the inert `blender.export-glb@1` WorkOrder contract, and `binder.blender.export-glb@1`.

The accepted WorkOrder shape is exactly one semantic ref:

```text
ref_type = MODEL3D_REQUEST
role = model3d_request
revision = None
payload = {}
```

The resolver reuses the protected non-creating semantic reader. The binder reconstructs only the fixed export request projection and exact canonical project semantics. `PHASE_SPECIFIC_EVIDENCE` remains non-authorizing; caller/model runtime identity, paths, profile/version, budgets, operation IDs, workspace IDs, and process authority remain absent.

The pure Blender-v1 project compatibility predicate is applied before claim/execution authority. Existing code, deterministic simulation, Pixelorama, and Goal-bootstrap boundaries remain unchanged.

## 51C — Blender preparation authority

51C added the separate code-owned preparation descriptor `originforge.preparation.blender-export-glb@1` without adding Blender runtime or execution authority.

For the exact Blender contract, `planner_allowed_input_refs(...)` projects only already-frozen, revisionless `MODEL3DREQ-*` PlanningInput evidence into the bounded planner allow-list. `work_order_input_refs_within_authority(...)` requires the returned WorkOrder to choose exactly one member of that infrastructure-supplied authority set.

Wrong hash, wrong role, revision injection, phase-specific evidence, unrelated Artifacts, and refs outside the frozen allow-list cannot be promoted by the planner. Mixed-owner catalogs continue to fail closed and Phase-45/46 Goal bootstrap remains code-only.

## 51D — zero-model Blender execution owner and atomic start

51D added `originforge.execution.blender.export-glb@1` and owner-specific infrastructure dependency assembly.

The owner requires only the infrastructure-owned trusted Blender profile. It does not assemble the coding model/runtime scheduler, resource lease, sandbox, or Git Workspace stack. Profile loading/fingerprinting occurs without Blender process launch, runtime probing, operation allocation, or media-workspace creation.

`begin_dispatch_execution(...)` atomically commits the exact Blender `DISPEXEC STARTED` relation together with the production Task `READY → RUNNING`. No `BLOP-*` operation ID or `MODEL3D-*` workspace ID exists before this durable boundary. Duplicate/restarted starts fail closed, and transaction failure rolls back both execution receipt and Task transition.

## 51E — post-STARTED one-shot Blender export

51E added the durable Blender production service and the narrow Blender branch in the existing single-shot dispatch coordinator.

Only after STARTED does infrastructure create the concrete strict `BlenderJobRequest`, allocating fresh `BLOP-*` / `MODEL3D-*` identities and injecting only:

- the exact frozen semantic project;
- fixed `exports/model.glb` output path;
- trusted profile runtime hash;
- trusted runner fingerprint;
- trusted expected Blender version;
- code-owned `BlenderBudget()`.

The existing governed Blender adapter is called exactly once. The service records one successful MODEL3D Run plus canonical request/result/GLB Artifacts and exact output/Run Verifications. Before normal dispatch terminalization, the invocation layer independently rereads canonical evidence, rehashes and reinspects the current GLB bytes, and verifies exact lineage/profile/request/result relations.

Ordinary owner exceptions become durable RAISED/CONSUMED mechanics. BaseException/crash and uncertain post-call states preserve STARTED/ACTIVE recovery state and are never automatically replayed. A normal trusted return records RETURNED/CONSUMED and deliberately leaves the Task `RUNNING`.

## 51F — adversarial acceptance, no-replay recovery, and real preparation/currentness path

Phase 51F was accepted in three independently gated pieces.

First, a deterministic two-worker race holds the winning worker after durable STARTED at the Blender service boundary while a competing worker attacks the same ACTIVE claim. The losing worker fails closed before the Blender service. The accepted durable state has exactly one Blender service invocation, one dispatch execution, one successful Blender Run, one consumed claim, and one still-RUNNING Task.

Second, Phase 51F added schema v16 immutable `blender_dispatch_output_bindings`. The exact binding freezes one DISPEXEC to the reviewed claim/Task/WorkOrder/dispatch relation plus Run, request/result/output Artifacts, output/Run Verifications, content hash, and byte count. It is published only after the existing strict Blender result/GLB lineage validation and before RETURNED/CONSUMED terminalization.

`recover_blender_dispatch_execution_once(...)` is an explicit no-replay recovery boundary. It reconstructs the typed Blender result from durable evidence only, independently revalidates the protected request, output bytes, GLB inspection, Artifacts, Verifications, Run, Task, claim, and execution relation, and may finish dispatch terminalization without importing or invoking `BlenderExportService.execute`. GLB/evidence drift fails closed and leaves the execution recoverable rather than replaying Blender.

Third, cross-phase acceptance routes the happy path through the actual 51C planner allow-list/proposal boundary before WorkOrder creation and proves that the exact prepared `MODEL3DREQ-*` reaches one governed Blender dispatch. It rejects `PHASE_SPECIFIC_EVIDENCE` substitution, wrong role, and extra refs before claim/execution authority. Deleting the protected semantic request after claim causes dispatch currentness to fail before STARTED, Run creation, runtime workspace allocation, or Blender service invocation.

The repository-wide canonical suite plus focused 51A–51E tests cover the remaining frozen attack surface: malformed/wrong-ID/wrong-hash request evidence, unsupported Blender-v1 semantics before STARTED, runtime/path/profile/budget injection attempts, stale WorkOrder/binding/request currentness, pre-STARTED runtime-ID exclusion, runtime hash/version/runner/executable containment failures, workspace/output/symlink/undeclared-export rejection, GLB byte/hash/inspection/lineage drift, ordinary exception and uncertain-return no-replay behavior, and unchanged code/simulation/Pixelorama/Goal-bootstrap authority.

## Final authority exclusions preserved

Phase 51 adds no:

- Goal/Task metadata reconstruction of 3D semantic intent;
- generic `PHASE_SPECIFIC_EVIDENCE` fallback for Blender;
- caller/model-selected Blender runtime root, executable, version, runner, runtime hash, workspace, output path, argv, environment, or budget;
- `BLOP-*` or `MODEL3D-*` allocation before durable STARTED;
- model/resource/sandbox/Git-Workspace dependency stack for Blender execution;
- unbounded backend execution, automatic retry, replay, daemon, queue, watcher, poller, or background Blender worker;
- automatic GLB adoption into canonical project state;
- Task PASS/FAIL, Task terminalization, semantic/aesthetic acceptance, parent Flow/Goal transition, or production acceptance authority;
- provenance signing/private-key access, merge, release, or deployment authority;
- dynamic execution-owner/plugin marketplace or generic media dispatch expansion;
- mutation of Phase-45/46 code-only Goal-bootstrap authority;
- fourth installed package entrypoint or mutating cockpit/HTTP Blender surface;
- mutation of immutable v0.5 release records.

## Packaging and immutable release boundaries preserved

Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

There is no direct mutating `origin-forge blender ...` production command. Blender production execution is reachable only through already-governed preparation/claim/dispatch authority and the existing explicit Manager path.

Phase-45/46 Goal bootstrap remains exactly code-only:

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

Phase 51 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Exact-head accepted evidence

- **Phase-51 planning — PR #132:** exact accepted head `eb8cf4a60aca63314735fc069f0bf29186b4f092` / canonical run `32263456991` passed the normal matrix; merged as `7d64d8610e209b4071ffcb24d258ed73798bdccf`.
- **51A — protected MODEL3D request substrate — PR #133:** exact accepted head `a2fabcad5456e5c1742df87fa8933d7252d2f9f0` / canonical run `32264666094` passed; merged as `1f535c826aa9af11bd1e72b2b890c26cb7e5dd7d`.
- **51B — governed WorkOrder binding — PR #134:** exact accepted head `410fb4e27934a18e5eb757a5575fbef81ea5f744` / canonical run `32312382896` passed; merged as `713698a40807803b27846f6a8a1e7d7ba523a482`.
- **51C — Blender preparation owner — PR #135:** exact accepted head `ddddef0dc7ff7a28c3d4b03cbb14c9a3b4caae9d` / canonical run `32323663915` passed; merged as `7142bcb572c388adcddf0ce12fb00b61f6283262`.
- **51D — Blender execution owner — PR #136:** exact accepted head `b30ecb9080410661b9e8cb404d3cfc6ef1147b4a` / canonical run `32335031647` passed; merged as `79a45e66d7310fe88fdfb532d7b96ee5be014294`.
- **51E — governed one-shot Blender export — PR #137:** exact accepted head `1f1063686078232f07d39de09985a8e0021f5f17` / canonical run `32336438548` passed; merged as `f647564f0560bd767e2bf33fb28cc1e093dafe05`.
- **51F — two-worker adversarial race — PR #138:** exact accepted head `a5a952d1a4fd1d5b52fa6804f51d2a2b8ab6d6ea` / canonical run `32401063637` passed after the failed 3.13 matrix job was rerun on the exact unchanged SHA; merged as `2a05b753e5c9769a2b9c974129f7ea688fe3326e`.
- **51F — durable-output no-replay recovery — PR #139:** exact accepted head `763d5c1f0478622de12107b8b570fac755a1da6f` / canonical run `32413162858` passed Python 3.12 and Python 3.13; merged as `89d5b9769a89e28f6939e9f4b67a850bc598f955`.
- **51F — preparation/currentness acceptance — PR #140:** exact accepted head `ebca57a14bbd0c490d13c2eb4e6dda3050e82dfd` / canonical run `32414424872` passed Python 3.12 and Python 3.13; merged as `37ccca57316a9e1eb2460f49f4b9edf44aac86fa`.

## Closure gate

This documentation/roadmap/operator-guide closure branch starts from exact accepted Phase-51 implementation `main`:

```text
37ccca57316a9e1eb2460f49f4b9edf44aac86fa
```

The intended final net diff is documentation only:

```text
docs/phase-51-implementation-closure.md
docs/operator-guide.md
docs/roadmap.md
```

The frozen planning document `docs/phase-51-governed-blender-3d-production-dispatch.md` remains unchanged as the historical architecture contract, matching the closure pattern used by prior phases.

The closure may not modify production code, tests, schema, config, packaging, workflows, runtime authority, Goal-bootstrap semantics, Manager semantics, cockpit mutability, immutable v0.5 release records, Blender replay/adoption/acceptance/signing/release authority, or the accepted Task-stays-RUNNING boundary.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.