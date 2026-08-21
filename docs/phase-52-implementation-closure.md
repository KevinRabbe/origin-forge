# Phase 52 — Governed Blender Production Output Adoption — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-52-governed-blender-production-output-adoption.md`. Phase 52 is post-v0.5 development. It takes exactly one already-durable, already-bound, terminal Phase-51 Blender GLB production output and allows an explicit human operator to publish those exact bytes once at a new canonical project path.

Phase 52 deliberately stops at **canonical byte adoption**. It does not claim semantic geometry correctness or aesthetic acceptance, does not create a Task PASS, does not terminalize the production Task, does not sign provenance, does not merge or release, and does not give Manager, cockpit, browser, or GUI code a new production control plane.

## Final governed Blender adoption boundary

The accepted sequence is:

```text
explicit operator selects one DISPEXEC-* and one new project-relative destination
→ read exact Phase-51 Blender dispatch-output binding
→ require exact current Blender owner / Task / WorkOrder / Run / Artifact / Verification relation
→ require DISPEXEC RETURNED + claim CONSUMED
→ re-read current bound GLB bytes and revalidate exact hash / size / GLB structure / lineage
→ reserve one immutable Blender production-adoption receipt as PREPARED
→ create-only publish the exact current bytes to the requested canonical destination
→ create exact adopted BLENDER_GLB_EXPORT child Artifact
→ record exact blender-production-adoption-integrity PASS evidence
→ finalize immutable receipt PREPARED → PUBLISHED
→ STOP with production Task RUNNING
```

A successful result proves only that the exact terminal governed Blender output bytes were canonically adopted once. It does not prove that the model is semantically correct for the game, visually acceptable, accepted against the Task contract, signed, or releasable.

## 52A — terminal Blender adoption currentness

52A added the read-only adoption-currentness boundary over the existing immutable Phase-51 Blender dispatch-output binding.

Adoption eligibility requires the exact reviewed Blender execution relation to be terminal and current: the dispatch execution is `RETURNED`, its claim is `CONSUMED`, the frozen production Task relation remains exact, the bound successful Blender Run and request/result/output/Verification lineage remain exact, and the durable GLB evidence remains materializable through the existing strict Phase-51 reader.

`STARTED` remains recovery-only. A stranded durable Blender output may help explicit Phase-51 dispatch recovery complete `RETURNED`/`CONSUMED`; it is never treated as adoption authority while the dispatch execution is nonterminal.

52A is read-only. It adds no schema mutation, file publication, Blender invocation, Task transition, signing, Manager, cockpit, or GUI authority.

## 52B — Blender-specific immutable production adoption

52B added schema-v17 `blender_production_adoptions` and the Blender-specific governed adopter.

The receipt is immutable one-shot authority for the exact DISPEXEC / Task / request / binding / source / destination relation. Its lifecycle is only:

```text
PREPARED → PUBLISHED
```

The destination is create-only. Existing files are never overwritten. The same execution/output cannot fan out to a second canonical destination. Exact PREPARED retry is allowed only while the destination remains absent; if a destination exists beside PREPARED state, Origin Forge fails closed and requires explicit operator recovery rather than deleting, replacing, or guessing whether publication completed.

Before reservation or publication, the adopter independently revalidates the exact Phase-51 binding and current GLB bytes. After publication it records:

- one adopted child `BLENDER_GLB_EXPORT` Artifact bound to the exact source output;
- one `blender-production-adoption-integrity` PASS Verification binding the source and destination identity, hash, size, Task, execution, request, and binding relation;
- the final immutable PUBLISHED receipt relation.

The adopter never invokes Blender. Missing, stale, tampered, symlinked, escaped, oversized, ambiguous, or nonterminal evidence fails closed rather than replaying production.

52B adds no semantic geometry acceptance, Task PASS/FAIL, Task terminalization, provenance signing, Manager/cockpit/GUI mutation, merge, or release authority. Pixelorama production adoption remains a separate authority family.

## 52C — explicit module-only operator and adversarial acceptance

52C exposes the already-governed 52B boundary through a module-only human operator command:

```bash
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  adopt-production-new \
  --execution-id DISPEXEC-... \
  --destination assets/models/new_asset.glb
```

The optional `--max-source-bytes` argument retains the hard source-read bound. There is no new installed package entrypoint.

The operator supplies only the canonical `DISPEXEC-*`, a new safe project-relative destination, and optionally the byte limit. It cannot supply a Run ID, source Artifact ID, source path, Task ID, Verification ID, Blender executable/profile/runtime/version, WorkOrder/binding override, PASS status, signing key, overwrite/force flag, semantic verdict, or release decision.

Adversarial acceptance proves the command fails closed for missing/tampered bindings, non-RETURNED execution, non-CONSUMED claim, owner drift, stale Task/Run evidence, output Artifact lineage drift, GLB byte drift, source symlinks, Verification drift, protected/traversal/symlink destinations, existing destinations, byte-limit violations, repeated fan-out, concurrent publication, invalid execution identity, non-PASS adoption integrity, and ambiguous crash windows.

The accepted pre-link crash behavior leaves PREPARED state retryable only while the destination is absent. The accepted post-link ambiguous window leaves PREPARED plus existing destination and refuses automatic retry/overwrite/replay.

The first 52C canonical matrix exposed one test-fixture-only defect: the adversarial non-RETURNED mutation changed a terminal execution to `STARTED` while retaining terminal-state fields. The final repair changed only that fixture to the canonical valid nonterminal shape (`status='STARTED'`, `revision=0`, `terminal_detail_hash=NULL`). Production adopter and CLI code were unchanged by the repair.

## Final authority exclusions preserved

Phase 52 adds no:

- Blender replay, retry worker, watcher, poller, daemon, queue, or background adoption;
- caller/model-selected Blender runtime, executable, profile, version, runner, workspace, operation ID, output path, argv, environment, or process budget;
- caller-selected source Artifact/path/URI, binding override, Run override, Verification override, or Task override for adoption;
- overwrite/replace/force authority for canonical project files;
- multi-destination fan-out from one terminal Blender production output;
- semantic geometry, aesthetic, gameplay, or design-quality acceptance claim;
- Task PASS/FAIL Verification, production Task terminalization, parent Flow/Goal transition, or release decision;
- provenance signing, private-key access, certificate authority, merge, deployment, or release authority;
- reuse or widening of Pixelorama production-adoption authority;
- Manager production-adoption action, automatic adoption after dispatch, or Goal-bootstrap widening;
- mutating cockpit/HTTP/browser/GUI Blender adoption surface;
- fourth installed package entrypoint;
- mutation of immutable v0.5 release records.

## Future UI integration requirements — documentation only

Phase 52 does **not** implement UI behavior. A future governed UI may present this already-accepted operator boundary only if it remains a client of the same infrastructure-owned adoption service rather than becoming a second control plane.

A future UI may:

- display exact `DISPEXEC-*` identity and read-only adoption eligibility/currentness;
- let the operator explicitly choose the one execution to adopt;
- collect one new safe project-relative `.glb` destination and, if exposed, the same bounded source-byte limit;
- invoke the same governed Blender production-adoption application boundary;
- display the exact success projection, PUBLISHED receipt identity, adopted Artifact identity, integrity Verification identity, and fail-closed error/recovery-required state.

A future UI must **not**:

- copy, move, rename, delete, or overwrite project files directly;
- reproduce or weaken binding/currentness/hash/size/GLB/lineage validation in presentation code;
- infer a source Artifact/path, substitute another Run/Task/Verification, or choose a destination automatically;
- auto-adopt after Blender dispatch, silently retry PREPARED ambiguity, or poll/replay Blender;
- expose overwrite/force, semantic-accept, Task-success, signing, merge, deploy, or release controls through this boundary;
- present successful byte adoption as proof of semantic geometry correctness, Task acceptance, provenance trust, or release readiness.

The UI should treat `recovery required` as an explicit operator state, not something to repair automatically. Any future browser transport must delegate to a typed application/service boundary with the same authority and idempotency laws; the browser itself must never own filesystem, dispatch, adoption, Task, signing, or release authority.

These are implementation instructions only. This closure slice changes no cockpit, server, browser, conversation, GUI, or HTTP source.

## Packaging, Goal bootstrap, and immutable release boundaries preserved

Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Blender production adoption is module-only; there is no installed `origin-forge-blender` command and no `origin-forge blender adopt` mutation family.

Phase-45/46 Goal bootstrap remains exactly code-only:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

Phase 52 does not bootstrap, dispatch, adopt, or accept Blender work through Goal bootstrap.

The immutable v0.5 release remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 52 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Exact-head accepted evidence

- **Phase-52 planning — PR #143:** exact accepted head `89b2d79656e3e44b3148233a27509d48694a6af2` / canonical run `32440731032` passed the normal matrix; merged as `ddb80161d1736a46a8d359a2997caeeff645a6b5`.
- **52A — terminal Blender adoption currentness — PR #148:** exact accepted head `4c333b8484b96623530eeee5204db971f887c1b6` / canonical run `32442040314`; Python 3.12 job `96654570577` and Python 3.13 job `96654570736` passed; merged as `4794e2fae694b85832d8486dd72f590686ff6ab4`.
- **52B — governed Blender production-output adoption — PR #150:** exact accepted head `1f7f3b356c65792202ffde5382de45f94c6d8a1c` / canonical run `32483360618`; Python 3.12 job `96774434665` and Python 3.13 job `96774434437` passed; merged as `4c9b0ebc089eac1998f86885f05b8c6486b61413`.
- **52C — explicit operator/adversarial acceptance — PR #156:** exact accepted head `a55a185603b3f8088c07f92ae9b0ef71b45e0e1f` / canonical run `32500706983`; Python 3.12 job `96829545483` and Python 3.13 job `96829545341` passed against the current-main merge ref; merged as `b2b402c1b467923458f69d90f6410162285ad9a5`.

The 52C exact merge ref combined the accepted Phase-52 head with then-current `main` `08d9ee3f46d8ac881cf306a73f35dd3c0cc482b3`, which independently contained the separately governed GUI conversation Gate-A substrate/schema v18. Phase 52 did not modify that UI/conversation substrate, and the combined canonical matrix passed before merge.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact accepted Phase-52 implementation `main`:

```text
b2b402c1b467923458f69d90f6410162285ad9a5
```

The intended final net diff is documentation only:

```text
docs/phase-52-implementation-closure.md
docs/operator-guide.md
docs/roadmap.md
```

The frozen planning document `docs/phase-52-governed-blender-production-output-adoption.md` remains unchanged as the historical architecture contract.

The closure may not modify production source, tests, schema, config, packaging, workflows, runtime/Manager/Goal-bootstrap authority, cockpit/server/browser/GUI code, Pixelorama authority, Task acceptance semantics, semantic geometry claims, provenance signing, merge/release authority, or immutable v0.5 release records.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.