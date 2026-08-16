# Phase 48 — Governed Pixelorama Spritesheet Export Production Dispatch — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-48-governed-pixelorama-spritesheet-export-production-dispatch.md`. Phase 48 promotes only the already-proven Pixelorama v1.2 documented headless spritesheet-export boundary into the governed production preparation/claim/execution path while preserving the existing bounded-code and deterministic-simulation owners, code-only Goal bootstrap, bounded Manager stop/no-fallback/no-replay semantics, read-only cockpit, fixed package command count, and separate adoption/signing/Task-outcome authority.

## Final production boundary

An already-governed Task whose exact Phase-32 authority is:

```text
media.2d.export
→ originforge.pixelorama.export
→ pixelorama.spritesheet-export@1
```

may now proceed through the existing preparation and Manager path to exactly one reviewed Pixelorama spritesheet-export execution owner.

The production execution sequence is:

```text
QUEUED media.2d.export Task
→ governed Phase-39 preparation / one-shot WorkOrder planning
→ exact one PIXELORAMA_PROJECT Artifact ref as role pixelorama_project
→ current PASS-audited Phase-34 binding
→ exact Phase-35 claim
→ atomic Phase-36 DISPEXEC STARTED + Task READY→RUNNING
→ post-STARTED source path/bytes materialization + containment/type/hash/size revalidation
→ fresh PXOP/MEDIA identities and fixed infrastructure-owned paths
→ exactly one durable PixeloramaCliExportService execution
→ canonical Pixelorama Run + request/result/spritesheet evidence
→ durable result/lineage revalidation
→ DISPEXEC RETURNED / claim CONSUMED
→ Task remains RUNNING
```

A normal Pixelorama return is dispatch completion evidence, not Task success/failure, Artifact adoption/signing, semantic/aesthetic truth, project mutation authority, merge authority, or release authority.

## 48A — exact spritesheet-export WorkOrder contract

Phase 48A added the strict `pixelorama.spritesheet-export@1` contract for the trusted `originforge.pixelorama.export` adapter.

The accepted contract:

- has a fixed empty payload;
- requires exactly one `ARTIFACT` input ref with role `pixelorama_project`;
- grants no caller/model path, executable, profile, plugin, GDScript, network, process, PXOP/MEDIA identity, adoption, signing, or Task-outcome authority;
- preserves the global Phase-45/46 dispatch catalog as code-only;
- preserves deterministic simulation as a separately reviewed explicit catalog;
- fails closed rather than resolving a mixed non-code catalog by ordering.

## 48B — exact Artifact metadata binding and currentness

Phase 48B added `binder.pixelorama.spritesheet-export@1` and binds exactly one current project-owned `PIXELORAMA_PROJECT` Artifact through the existing metadata-only Artifact resolver.

Binding freezes the exact Artifact identity/hash plus the code-owned `EXPORT_SPRITESHEET`, `inputs/source.pxo`, and `exports/spritesheet.png` request semantics. Phase-34 binding and currentness do not open `.pxo` bytes or treat `path_or_uri` as caller execution authority.

The Phase-48D claim gate exposed one historical persisted-reader assumption that still rejected every nonzero-ref binding. The separate Phase-48B repair narrowed persisted currentness to exactly the reviewed Pixelorama adapter/contract/binder relation, requires one canonical `ARTIFACT` ref with role `pixelorama_project`, re-resolves only safe metadata, and keeps every other nonzero-ref relation fail closed.

## 48C — separate Pixelorama preparation authority

Phase 48C added `originforge.preparation.pixelorama-spritesheet-export-planner@1` as a separate Phase-39 preparation owner while preserving the bounded-code and deterministic-simulation preparation owners.

Pixelorama preparation uses the accepted one-shot governed WorkOrder Planner and `CODER_STRONG` planning role. PREPPOL still requires an exact single owner; mixed reviewed-owner catalogs fail closed. Phase-45/46 Goal bootstrap remains pinned to the original code preparation owner and does not gain `media.2d.export` capability.

Preparation does not open source Artifact bytes, invoke Pixelorama, or allocate execution identities.

## 48D — zero-model Pixelorama execution owner and atomic start

Phase 48D added `originforge.execution.pixelorama.spritesheet-export@1` with an infrastructure/operator-owned `PixeloramaCliProfile` and no model/runtime/resource/sandbox/Git-Workspace stack.

For Pixelorama only, Phase 36 atomically commits the exact `DISPEXEC STARTED` receipt and exact Task `READY → RUNNING` transition. Rollback coverage proves neither side can persist alone. Missing or invalid trusted profile state fails before STARTED.

48D deliberately does not read `.pxo` bytes, allocate PXOP/MEDIA identities, create a Pixelorama Run, or launch the editor process.

## 48E — durable direct CLI export service

Phase 48E wrapped the already-proven direct Pixelorama v1.2 CLI spritesheet-export adapter in one durable Run-level production service.

The service:

- persists the exact request/result evidence;
- invokes only the frozen direct `EXPORT_SPRITESHEET` boundary;
- independently rehashes and structurally re-inspects the produced PNG;
- records the canonical Run, request/result Artifacts, `SPRITESHEET_EXPORT` Artifact, and structural Verification evidence;
- leaves the production Task RUNNING;
- grants no Phase-37 owner fanout, adoption, signing, project-editing, Task-outcome, merge, release, package, or CLI authority by itself.

## 48F — exact invocation owner and cross-phase adversarial acceptance

Phase 48F extended the public dispatch coordinator to exactly the reviewed bounded-code, deterministic-simulation, and Pixelorama execution-owner branches.

After durable STARTED ownership, the Pixelorama branch:

- revalidates the exact active claim, audited binding, adapter/contract/binder relation, execution owner, and trusted profile;
- accepts only a canonical portable relative `.pxo` source outside protected roots;
- rejects escape, protected path, symlink, non-regular file, non-`.pxo`, hash drift, and size drift before process launch;
- allocates fresh infrastructure-owned PXOP/MEDIA request identities and fixed paths;
- invokes `PixeloramaCliExportService.execute(...)` at most once;
- independently revalidates the returned Run, request/result/export Artifacts, structural Verification, hashes, and lineage before recording DISPEXEC `RETURNED`;
- records ordinary owner exceptions as `RAISED/CONSUMED` and preserves BaseException uncertainty as `STARTED/ACTIVE/RUNNING` with no automatic replay.

Real Manager-path acceptance exposed two Phase-39 persisted-evidence integration defects rather than a Pixelorama execution-owner defect. The accepted repairs:

- project only frozen `ART-*` PlanningInput evidence into the Pixelorama WorkOrder-planner allow-list while code and deterministic simulation remain zero-ref;
- reconstruct exactly the reviewed one-ref Pixelorama WorkOrder from post-planner evidence/status while non-Pixelorama planner evidence remains zero-ref;
- preserve the one-shot verification law exactly: `audited=false`, `dispatched=false`, `model_calls=1`, and `allowed_input_refs == len(work_order.input_refs)`.

Cross-phase acceptance proves the real bounded Manager can traverse preparation → binding → claim → atomic start → one Pixelorama export → dispatch return, leaves the selected Task RUNNING with no Task-level Verification, does not fall through to a newer Task, preserves no-replay under uncertain STARTED states, bounds concurrent Managers at the claim boundary, and keeps code/simulation invocation authority closed.

## Manager, Goal-bootstrap, packaging, and release boundaries preserved

A Pixelorama `DISPATCH_RETURNED` is terminal for the current bounded Manager invocation. Manager does not automatically dispatch another Task in the same call and does not reinterpret structural spritesheet evidence into Task success/failure or Artifact adoption.

Phase-45/46 Goal bootstrap remains exactly code-only. It does not bootstrap `simulation.run` or `media.2d.export` Tasks and still stops at GOALBOOT READY before the separate explicit Manager authorization.

Production Pixelorama execution therefore requires already-governed media Task/materialization/preparation authority and the existing explicit `origin-forge manager advance` invocation. Phase 48 adds no direct Pixelorama production mutation command.

Packaging remains exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The cockpit remains read-only. The immutable `v0.5.0` tag/release records are unchanged; Phase 48 is post-v0.5 work toward the v1.0 production-integration boundary.

## Authority exclusions preserved

Phase 48 adds no:

- Goal-bootstrap support for `media.2d.export`;
- direct `origin-forge pixelorama ...` production mutation command;
- Pixelorama project create/import/edit/save production dispatch or generic bridge promotion;
- model/caller-selected executable, profile, runtime, process, plugin, GDScript, network, path, PXOP/MEDIA identity, or arbitrary tool authority;
- arbitrary WorkOrder input refs or pre-STARTED Artifact byte reads;
- automatic Artifact adoption/signing or Task SUCCEEDED/FAILED transition from export evidence;
- automatic replay after durable STARTED uncertainty;
- generic owner/plugin/tool dispatch or dynamic executable expression language;
- background loop, queue drain, timer, watcher, poller, daemon, service, or automatic Manager invocation;
- cockpit/HTTP/plugin mutation surface;
- Project Intelligence/Design Bible mutation, Dream promotion, training/model activation, merge, release, deployment, or remote multi-user authority.

## Exact-head accepted evidence

- **Phase-48 planning — PR #108:** exact head `52411df4e876a7bb2c0a2fc6023e15abb6eb87c4`; normal run `31915469094` / #1369 passed Python 3.12 and Python 3.13; merged as `e52a101e578783c7731bdde0d53051a586f5791a`.
- **48A — Pixelorama WorkOrder contract — PR #109:** exact head `c6e328575db4ecaa7b0ca3c191ede56f42857f92`; normal run `31915910291` / #1371 passed Python 3.12 and Python 3.13; merged as `d0097e521b94aa2e576f3f3afb8acb09c8147ecf`.
- **48B — exact Artifact request binding — PR #110:** exact head `78e86b4da53be894be2223ee807ba208d42f618a`; normal run `31922527176` / #1374 passed Python 3.12 and Python 3.13; merged as `dc189925778498ab27bca57b78f97902a6f6d3e2`.
- **48C — Pixelorama preparation authority — PR #111:** exact head `12e10bcbbba5a19d286dbd924ef1270ef929b900`; normal run `31926045992` / #1376 passed Python 3.12 and Python 3.13; merged as `4101b1568f1effdbc8e595afc558bce76cafc942`.
- **48B persisted-currentness repair — PR #113:** exact head `4e3bafee120232f607c6405c1dfee6acb33b8845`; normal run `31929132808` / #1380 passed Python 3.12 and Python 3.13; merged as `b05658dc37bd6bfd42c7c04b29b48821b4d0d128`.
- **48D — zero-model execution owner + atomic start — PR #112:** exact head `66d8c52d4d8f57eed43ddb376a06981ea0bf71e1`; normal run `31929383977` / #1382 passed Python 3.12 and Python 3.13; merged as `4ebaba55efec22382fa0b47b43202aa152ee07f8`.
- **48E — durable Pixelorama CLI export service — PR #114:** exact head `2e1131c85adf3039cd2685c7380300ebfdc6b7ea`; normal run `31930898625` / #1384 passed Python 3.12 and Python 3.13; merged as `c1072a0f8c1526331f9f0797b10168061943206f`.
- **48F — invocation owner + cross-phase acceptance — PR #115:** exact accepted head `68315a50526ac00634ce03d26e669a7053c8ace1`; normal run `31945142450` / #1433 passed Python 3.12 and Python 3.13; SHA-guarded merged as `16eb0cd631ec572d07605209cb8ca29a1c5f3db9`.

## Closure gate

This Phase-48G documentation/operator-guide/roadmap closure branch starts from exact merged Phase-48F main `16eb0cd631ec572d07605209cb8ca29a1c5f3db9`.

The intended final net diff is exactly three documentation files: this implementation-closure record, the living operator guide, and the canonical roadmap. It may not modify production code, tests, schema, config, packaging, workflows in the final tree, immutable v0.5 release records, or runtime authority.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
