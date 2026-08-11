# Origin Forge Roadmap

Status: **Canonical execution order aligned with merged repository state**

Origin Forge is built in dependency order: durable verified state first, then bounded autonomous execution, then intelligence/discovery, then learning and multi-media production. Models may reason, propose, create, and repair; Origin Forge owns identity, authority, state, history, and truth.

---

## Phase 0 — Specification and Foundations — DONE

Defined the architectural laws, object model, ID strategy, state transitions, authority/security model, company-root provenance concept, repository layout, tool/model contracts, and execution lifecycle.

**Exit condition met:** later runtime code could be implemented without inventing fundamental semantics during execution.

## Phase 1 — Durable Runtime — DONE

Implemented SQLite-backed Goal / Flow / Task / Run state, Decision / Change / Artifact / Verification lineage, schema migrations, optimistic revisions, event journal, restart recovery, and verification-gated completion.

**Exit condition met:** work survives process restart without depending on conversation history.

## Phase 2 — Bounded Local Worker — DONE

Implemented replaceable local model adapters, llama.cpp-compatible local HTTP execution, bounded repository reads, protected project state, content hashes, structured PatchProposal output, proposal-only Worker behavior, and model/context/proposal provenance.

**Exit condition met:** a local model can produce a bounded hash-preconditioned patch proposal without write authority.

## Phase 3 — Isolated Apply and Audit — DONE

Implemented durable Git Workspaces, deterministic patch application, rollback/cleanup, persisted diff evidence, independent content audit, proposal-artifact integrity checks, and Workspace recovery.

**Exit condition met:** model-generated mutations occur only inside disposable isolated Workspaces and are independently audited.

## Phase 4 — Sandboxed Verification Contract — DONE

Implemented `CREATED → APPLIED → AUDITED → VERIFIED`, approved structured commands, backend-neutral sandbox contracts, isolation guarantees, required build/test verification, and blocked-vs-failed infrastructure semantics.

**Exit condition met:** modified code cannot become VERIFIED without acceptable isolated execution evidence.

## Phase 5 — Podman Sandbox Backend — DONE

Implemented local-image-only Podman verification with `--pull=never`, disposable source copies, network-off default, dropped capabilities, no-new-privileges, CPU/RAM/PID bounds, bounded output, timeouts, and cleanup.

**Exit condition met:** approved verification commands execute in a real constrained sandbox without writable access to authoritative project state.

## Phase 6 — Snapshot-First Bounded Orchestration — DONE

Implemented the first complete single-attempt production loop:

```text
READY Task
→ isolated Git Workspace
→ bounded Executor
→ Patch Proposal
→ deterministic apply
→ independent audit
→ sandbox verification
→ Task PASS
```

The Workspace is created before context selection, so the model and applier operate on the same base snapshot.

## Phase 7 — Bounded Retry, Resume, Loop Detection and Model Escalation — DONE

Implemented durable retry accounting, verification-failure budgets, deterministic model escalation, repeated-proposal loop detection, checkpoint resume, quarantine, and bounded infrastructure-failure handling.

**Exit condition met:** retries and recovery are explicit policy rather than an endless agent loop.

## Phase 8 — Deterministic Context Discovery — DONE

Implemented tracked-file discovery inside the Workspace, UTF-8/text/symlink safety, scan/selection budgets, deterministic Task-term ranking, explicit seed files, manual/automatic modes, no arbitrary fallback context, and dirty-live-checkout isolation.

**Exit condition met:** a bounded Executor receives reconstructable task-relevant context without model-controlled filesystem search.

## Phase 9 — Governed Skills — DONE

Implemented instruction-only project Skills with deterministic selection, progressive disclosure, semantic versions, SHA-256 fingerprints, Run/Artifact provenance, hard catalog/read/instruction budgets, fail-closed containment, symlink rejection, and no executable Skill authority.

```text
.origin-forge/skills/<name>/
├── SKILL.md
└── skill.toml
```

**Exit condition met:** relevant procedural knowledge can be disclosed without allowing a Skill to grant new authority.

## Phase 10 — Structural Context Graph — DONE

Implemented bounded Python AST indexing, definitions, imports/reverse-importers, source↔test relationships, Task-symbol evidence, one-hop expansion, shared `WorkspaceContextSelector`, and fresh retry-time reselection.

```text
manual OR lexical auto-context
        ↓
optional structural expansion
        ↓
final bounded context
```

**Exit condition met:** structural relationships improve deterministic Workspace-local context without recursive repository dumping.

## Phase 11 — LSP and General Code Intelligence — DONE

Implemented provider-neutral read-only code intelligence, deterministic Python AST intelligence, semantic context expansion, bounded LSP JSON-RPC, UTF-8/16/32 position conversion, Workspace URI containment, normalized definitions/references/symbols/diagnostics, config-v4 trusted LSP registry, and sandboxed Podman language servers.

Important authority rules:

- the model receives normalized evidence, not unrestricted LSP control
- no native-host LSP backend
- only configured server IDs may be used
- LSP execution accepts only canonical isolated `.origin-forge/workspaces/<WSPACE-ID>` roots
- diagnostics are supplementary evidence, not a correctness oracle

**Exit condition met:** code intelligence extends context and audit evidence without gaining mutation or completion authority.

## Phase 12 — Governed Skill Evaluation and Benchmarks — DONE

Implemented immutable eval cases, fixture/scorer/environment fingerprints, paired with-vs-without Skill trials, stable paired seeds, alternating execution order, regression-dominant verdicts, success/score/duration/model-call/token metrics, exact Skill refs, content-addressed reports, replayability checks, and evidence-only CLI surfaces.

**Exit condition met:** Skill versions can be judged using repeatable outcomes rather than intuition, without automatic promotion authority.

## Phase 13 — Tool Registry and Tool Search — DONE

Implemented governed `ToolDescriptor` catalogs, bounded schemas/metadata, permissions/effects/determinism/reversibility/resource/timeout/verifier metadata, content-addressed catalog snapshots, authority filtering, bounded `search_tools` / `describe_tool`, hydration/response budgets, hidden/unknown denial equivalence, and disclosure-footprint metrics.

Phase 13 deliberately does **not** add generic model-facing `call_tool` authority.

**Exit condition met:** models can progressively discover authorized tool contracts without loading the entire catalog or gaining authority through discovery.

## Phase 14 — Model and Resource Scheduler — DONE

Implemented:

- atomic process-local CPU/RAM/GPU leases
- VRAM headroom and GPU compute-slot accounting
- exclusive GPU leases and explicit device pinning
- deterministic multi-GPU best-fit placement
- static incompatibility vs temporary contention
- read-only resource admission inspection
- governed model profiles and semantic roles
- explicit primary + fallback policy chains
- no implicit model downgrade
- model load/use/unload lifecycle
- trusted runtime-loader registry/dispatch
- unchanged `ModelAdapter` / Worker integration
- Run-level model/resource evidence
- read-only model/policy inspection
- config v5 protected `[resources]` / `[models]` sections
- v1–v4 config compatibility
- safe-disabled v5 defaults
- read-only `model_resource_cli status`

Hardware leases are ephemeral; durable Task/Run state remains authoritative across restart. Resource contention creates no hidden retry queue. A fallback model is considered only when explicitly authorized by policy.

**Exit condition met:** Origin Forge can choose between governed local model profiles and safely schedule incompatible CPU/GPU workloads without losing durable Task state or silently changing model quality.

---

## Phase 15 — Offline Dream Cycle / Memory Consolidation — DONE

Implemented a bounded offline consolidation layer that is explicitly separate from production-time execution.

Implemented components:

- frozen content-addressed Dream input manifests over terminal Run/Task/Decision/Verification evidence
- immutable content-addressed `MemoryEntry` objects
- parent-linked immutable `MemoryGeneration` snapshots
- exact evidence hashes/revisions/classes and active-memory revalidation
- deterministic duplicate/staleness/hash-drift/revision-drift and Decision-supersession preprocessing
- deterministic data-quality Analyzer
- optional bounded model-backed cross-run Analyzer using the existing `ModelAdapter` contract
- independent Dream Auditor with structural-vs-semantic authority separation
- proposal-only Dream candidates whose candidate type determines the mandatory downstream gate
- candidate classes for memory, Skills, routing, context strategy, process/architecture, and data quality
- exact `dream-audit` Verification binding before any new memory generation can be constructed
- ancestor audit revalidation so later durable-evidence tampering invalidates derived memory
- protected immutable Dream persistence with symlink/containment/size/count validation
- atomic no-overwrite object publication under competing writers
- bounded model-call/token/evidence/candidate budgets
- model context/response hashes and durable model-Dream observability Verifications
- durable deterministic Dream Cycle Goal/Flow/Task/Run lifecycle with verification-gated completion
- fail-closed Dream lifecycle cleanup on invalid evidence or planning failure
- operator `dream status`, `dream plan`, and deterministic `dream run` surfaces
- read-only manifest/candidate/audit/memory/generation inspection
- no CLI generative-model execution until a trusted runtime loader is explicitly wired
- no automatic memory generation, Skill promotion, routing/context policy mutation, source mutation, or merge authority

Core rule:

```text
Dreaming may discover candidate knowledge.
It may not redefine canonical truth.
```

The Dream process cannot modify source code, canonical Decisions, Design Bible content, Goal/Flow/Task/Verification outcomes from analyzed work, active Skills, routing/context policy, permissions, company identity, model weights, or merge state. Its own durable Dream lifecycle records are governed through the normal verified runtime.

See `docs/phase-15-dream-cycle.md` for the detailed architecture and acceptance tests.

**Exit condition met:** Origin Forge can inspect bounded completed work including failed attempts, discover cross-session and stale-derived-memory patterns, independently audit findings, construct immutable audit-bound memory generations without mutating parents, and emit improvement candidates into existing governance gates without self-modification authority.

## Phase 16 — Isolated Specialist Roles — DONE

Implemented the first isolated specialist role, Reviewer, as an advisory sidecar rather than a new production authority path.

Implemented components:

- separate specialist authority roles from Phase-14 model capability/resource roles
- immutable bounded `SpecialistContract` objects and typed exact evidence references
- exact frozen evidence packages persisted for replay
- fresh one-shot `IsolatedReviewer` using the normal `ModelAdapter` contract
- strict Reviewer JSON output limited to findings, with infrastructure-owned finding/report IDs and computed risk
- independent structural `ReviewerReportAuditor`
- explicit structural-vs-semantic separation: a structurally valid report does not verify its semantic findings
- protected immutable specialist contract/evidence/report/audit persistence
- symlink/root containment, byte/count limits, tamper detection, and atomic no-overwrite publication
- dedicated existing RUNNING `REVIEWER` Run/Task requirement and Run-level model/context/response/report/audit provenance
- read-only specialist and Reviewer-evaluation inspection surfaces
- repeatable paired Reviewer evaluation with exact labeled issue signatures, true/false positives, critical misses, precision/recall/F1, token/time/context/resource metrics, optional downstream repair outcomes, regression-dominant verdicts, and replayability checks
- explicit fresh-context isolation proving Reviewer input contains only the frozen specialist package rather than Executor scratch/session state
- no default production blocking gate, model-execution CLI, repair authority, Task status authority, merge authority, peer-agent messaging, or recursive delegation

Core rule:

```text
specialist insight = evidence
infrastructure verification = authority
```

Researcher, Test Planner, and Visual Critic remain deferred until a measured need and relevant evidence surface exist. Reviewer findings can inform a human/Manager or a later governed repair Task, but they cannot directly change production state.

See `docs/phase-16-specialist-roles.md` for the detailed architecture and acceptance tests.

**Exit condition met:** Origin Forge can invoke a fresh isolated Reviewer over exact bounded evidence, persist and independently structurally audit the report, prove the specialist has no production mutation or verification authority, and measure Reviewer value with a replayable evaluation protocol before any default integration is enabled.

## Phase 17 — Project Intelligence — DONE

Implemented the first durable semantic project layer in the existing protected SQLite truth store.

Implemented components:

- stable infrastructure-owned Entity identity across implementation changes
- software/media-neutral Entity kinds and governed lifecycle status/revisions
- typed directional Entity relations with same-project composite foreign keys
- explicit self-relation rejection and duplicate-active-edge prevention
- Entity bindings to files, symbols, Tasks, Decisions, Artifacts, Verifications, and inert external references
- portable/protected file-binding path validation and optional pinned SHA-256 hashes
- structured Design Bible `DesignRule` records with category, authority, global/scoped applicability, retirement, and append-only supersession
- project-scoped validation for durable binding targets, relation evidence, and Design Rule scopes
- optimistic revisions and state-event history for governed semantic changes
- deterministic bounded impact analysis with inbound/outbound/bidirectional traversal, relation filtering, cycle detection, stable ordering, content hashes, and explicit truncation flags
- active global/scoped Design Rules and implementation bindings included in impact evidence
- read-only stale file-binding inspection reporting CURRENT/STALE/MISSING/UNPINNED/INVALID/TOO_LARGE without rewriting canonical bindings
- read-only Project Intelligence CLI for status/list/show/binding-inspect/impact
- no automatic model-context integration, graph auto-discovery promotion, source mutation, Task verification, or merge authority

Core rule:

```text
semantic project structure = canonical infrastructure state
model inference             = proposal/evidence only
```

AST/LSP intelligence remains a live code-structure signal; Project Intelligence represents stable product meaning. Later controlled context integration can compose the two after separate measurement rather than making the model traverse or rewrite the semantic graph directly.

See `docs/phase-17-project-intelligence.md` for the detailed architecture and acceptance tests.

**Exit condition met:** Origin Forge can represent stable product/project Entities, typed cross-media relationships and implementation bindings, enforce/query structured Design Bible rules, detect stale file bindings, and deterministically identify bounded change impact without relying on a model to rediscover project meaning or granting model-generated graph claims canonical authority.

## Phase 18 — Cryptographic Provenance — DONE

Implemented company-root trust identity, Ed25519 operational certificates/signatures, revocation, signed provenance manifests, protected public provenance persistence, offline trust verification, and currentness/freshness inspection while keeping secret key material outside media/runtime authority.

**Exit condition met:** accepted Artifacts can be cryptographically traced through signed immutable provenance to their causal Task/Run/artifact state and governed tool/model/Skill evidence without making signatures a substitute for current verification.

## Phase 19 — Pixelorama Integration — DONE

Implemented the first bounded deterministic 2D media integration layer:

- canonical bounded sprite/project/layer/frame/animation/palette/pixel contracts
- deterministic standard-library RGBA8 PNG encoding/inspection and structural validators
- protected isolated `MEDIA-*` workspaces and `PXOP-*` operations
- strict bridge protocol and one-shot no-shell bounded process execution
- post-editor symlink/root/path containment revalidation and undeclared-output rejection
- media Run/Artifact/Verification evidence without production Task completion authority
- explicit create-only governed output adoption with no-overwrite/protected-root rules
- read-only Pixelorama status inspection
- Phase-18 provenance integration for explicitly adopted raster output
- direct Pixelorama v1.2 CLI spritesheet export over opaque `.pxo` input
- externally pinned `v1.2-stable` runtime/executable identity and frozen real upstream `.pxo` fixture
- opt-in supply-chain evidence workflow whose authoritative frozen-pin real-editor run completed successfully

The v0 direct CLI adapter deliberately exposes only the smallest proven export surface. Pixelorama project creation/import/save through Extension API 9, generic model-facing media tools, image generation, and aesthetic vision critique remain separately governed future capabilities.

See `docs/phase-19-pixelorama.md` and `docs/pixelorama-real-gate.md` for the implemented boundary and frozen real-editor evidence.

**Exit condition met:** Origin Forge can run a pinned real Pixelorama v1.2 headless spritesheet export over exact frozen input inside an isolated workspace, independently validate containment/hash/raster output, record evidence without transferring Task authority, and explicitly adopt a verified new media output without overwrite or signing authority.

## Phase 20A — Editor-Independent 3D Integration Substrate — DONE

Implemented the deterministic 3D substrate independently of any single editor:

- infrastructure-owned `MODEL3D-*` workspace IDs and `BBOP-*` operation IDs
- bounded immutable project contracts for bones/hierarchy, cuboids, pivots/rotations, UV offsets, exact texture refs, animations, and keyframes
- deterministic ordering/content addressing with missing-reference, duplicate, numeric-bound, and hierarchy-cycle rejection
- strict content-addressed bridge request/result protocols with exact request/version/fingerprint/output binding and no production-authority fields
- protected one-shot no-shell bridge process execution with pinned executable identity, isolated runtime state, hard timeout/log/output bounds, strict result JSON, exact export-set matching, output rehashing, symlink/root containment, and undeclared-entry rejection
- independent standard-library GLB v2/glTF 2.0 structural inspection covering container framing, embedded buffers/images, graph references, hierarchy cycles, skins, and animation sampler/target references
- explicit rejection of external GLB asset URIs in the initial evidence surface
- fake-process adversarial integration coverage proving the Origin Forge side of the isolation/protocol/validation boundary

**Exit condition met:** Origin Forge owns a backend-replaceable, content-addressed 3D contract and independent GLB truth layer without depending on a specific editor runtime.

## Phase 20B — Real Blockbench Automation — DEFERRED

The intended real Blockbench boundary remains a pinned governed JavaScript plugin using Blockbench's supported plugin/API surface. Origin Forge does not synthesize Blockbench's internal `.bbmodel` bytes, execute model-generated JavaScript, manipulate Electron/Chromium private state, or use GUI-coordinate automation.

Blockbench v5.1.4 was inspected and did not expose a supported non-interactive way to load an exact local side-loaded plugin or a documented headless create/edit/export CLI. Side-loaded plugin startup depends on persisted browser state, and manufacturing Chromium/LevelDB state would rely on private implementation details.

See `docs/phase-20-blockbench.md` for the implemented contract and exact future unblock conditions.

**Deferred condition:** revisit when Blockbench exposes a supported non-interactive bootstrap, or when Origin Forge deliberately approves a separately maintained/pinned distribution or fork. Blockbench no longer blocks unrelated roadmap work.

## Phase 20C — Governed Blender Backend — DONE

Implemented Blender as a separately governed replaceable 3D backend behind the Phase-20A contract rather than as unrestricted Python execution:

- infrastructure-owned `BLOP-*` operation identity;
- bounded Blender v1 acceptance over the existing canonical 3D project spec;
- explicit rejection of unsupported hierarchy/texture/animation/rotation/inflation semantics in the first runner revision;
- repository-owned frozen runner with no caller/model Python surface;
- exact Blender 5.2.0 LTS release/build/archive identity;
- symlink-free materialized runtime-tree hashing and frozen runner hashing;
- background/factory-startup/offline execution with automatic script execution disabled;
- isolated `MODEL3D-*` workspace, minimal environment and hardened fixed argv;
- exact request/result/version/hash/export-set binding;
- independent existing GLB validation after Blender exits;
- normal fake-process/adversarial CI plus authoritative real Blender execution on one immutable closure SHA.

Frozen runtime evidence used Blender 5.2.0 LTS source tag `v5.2.0` / commit `fbe6228777e7d9afefcd61a413844e790ae75db7`, archive SHA-256 `96f6c181a30f4950607839dc84d42a354b250d8a0231b098b59b7bc69c351c48`, materialized runtime-tree hash `sha256:96528bd441b3c6d095216be58a5165a5ae4c1b7f0679e63dcbe2bd40ebe11676`, and runner hash `sha256:c2eb8ebc0523bcfe0675bf8ba0a48018ae811a128551e1a935afde8ceb978746`.

Blockbench and Blender remain replaceable backends; neither defines Origin Forge's canonical 3D representation or production truth.

**Exit condition met:** the frozen Blender runtime and frozen infrastructure-owned runner produced a real bounded cuboid → GLB result on exact closure head `7f9140ab87cce7bf961a467f37afb25e55ef7e90`, with Python 3.12/3.13 normal CI and independent GLB validation green before the SHA-guarded merge.

## Phase 21 — Image and Vision — DONE

Implemented provider-neutral image generation/editing and advisory visual inspection boundaries with isolated `IMAGE-*` workspaces, immutable governed workflows, independent raster validation, durable Run/Artifact/Verification evidence, create-only adoption, and read-only operator surfaces.

Real evidence includes a pinned local llama.cpp + SmolVLM multimodal path with request-bound structured output and a pinned ComfyUI + SD1.5 generation path with frozen source/model/dependency identities. Generated or inspected image evidence never verifies or completes the production Task by itself.

**Exit condition met:** real pinned generation and vision backends execute through governed replaceable adapters, outputs are independently validated, and semantic model findings remain advisory evidence rather than production truth.

## Phase 22 — Audio — DONE

Implemented deterministic/local audio production and evidence:

- exact canonical PCM16 RIFF/WAVE parsing, encoding, inspection and metadata-stripping canonicalization;
- deterministic structured SFX/music synthesis;
- immutable governed audio profiles and typed operation/result contracts;
- bounded FFmpeg and Piper process adapters with no caller-supplied shell/command authority;
- durable audio Run/Artifact/Verification lineage with independent exact-workspace/output revalidation;
- create-only verified audio adoption and read-only operator inspection;
- pinned real FFmpeg 8.1.2 processing evidence;
- pinned real Piper v1.6.0 + reviewed Joe voice TTS evidence;
- Piper-specific exact streaming IEEE-float32 WAV normalization into shared canonical PCM16 without weakening the canonical WAV parser.

See `docs/phase-22-audio.md` for the detailed architecture, pins, authority exclusions and evidence levels.

**Exit condition met:** deterministic audio substrate, real governed processing, and real governed TTS all produce independently validated canonical evidence while neural SFX/music remains optional and replaceable.

## Phase 23 — Runtime Observation — DONE

Implemented a governed runtime-observation substrate that records application behavior without transferring production Task authority:

- infrastructure-owned `OBS-*` observation IDs and `OBSWS-*` workspaces;
- content-addressed backend/target/executable-bound request/result contracts;
- adapter-owned executable and fixed argv with no shell or caller environment injection;
- bounded concurrent stdout/stderr capture with active overflow termination;
- POSIX process-group timeout and descendant cleanup;
- explicit normal exit, nonzero failure, signal and timeout outcomes distinct from observer infrastructure failure;
- duration and best-effort Linux peak-RSS observations;
- cooperative exact-path screenshot capture and timed `VIDEO_FRAME` PNG sequences as the canonical v1 video evidence;
- exact capture-set, symlink/root/path and pre-read byte-bound enforcement;
- independent RGB/RGBA PNG inspection after process exit;
- exact baseline Artifact revalidation and deterministic changed-pixel/channel visual-regression evidence;
- durable request/result/log/capture Artifacts plus Run/Artifact Verifications;
- visual-regression FAIL evidence without automatic Task failure/completion authority;
- read-only `runtime_observation_cli` status/run/artifact inspection;
- real local subprocess regressions covering abnormal exit, timeout, log overflow, oversized sparse capture and direct-child/descendant cleanup;
- no input automation, semantic vision authority, performance-requirement authority, asset adoption, signing, merge, or release surface.

Cooperative exact-path PNG capture is the accepted v1 capture boundary. OS/window/framebuffer capture remains a replaceable backend-specific enhancement and untrusted native binaries require a separately governed sandbox backend.

See `docs/phase-23-runtime-observation.md` for the detailed v1 contract, exclusions, evidence model and acceptance boundary.

**Exit condition met:** one immutable repository head proves on Python 3.12 and 3.13 that Origin Forge can launch an exact trusted target, bind logs/runtime outcomes/performance evidence, capture and independently validate only declared screenshots/timed video frames, emit deterministic baseline-regression evidence, persist/read that evidence, terminate descendant process state, and leave production Task/adoption/signing/merge/release authority unchanged.

## Phase 24 — Automated Playtesting — DONE

Implemented a governed automated-playtesting substrate for suitable games:

- infrastructure-owned `PLAYSCEN-*`, `PLAY-*`, and `PLAYWS-*` identities;
- immutable content-addressed scenarios with exact harness/target identity and executable hash binding;
- semantic whitelisted `SET_AXIS`, `PRESS`, `RELEASE`, and `WAIT` controls rather than generic host input injection;
- a real cooperative no-shell target-specific harness with fixed executable/argv, minimal infrastructure-owned environment, bounded concurrent logs, timeout and POSIX process-group cleanup;
- strict bounded scenario-bound telemetry for deaths, encounters, damage, shortages, soft locks, pathfinding failures, progression and runtime outcome;
- deterministic encounter/progression/gameplay analysis that remains evidence rather than semantic game-quality authority;
- explicit separation between a successful playtest observation and a failed/timed-out game session;
- independently revalidated exact workspace, scenario path/bytes, log paths/hashes/sizes and backend exit/telemetry consistency;
- adversarial rejection of workspace escape, escaped/aliased log paths, symlinked scenario evidence, hash drift and backend process-state disagreement before Artifact persistence;
- durable scenario/telemetry/summary/log Artifacts plus Run-level `playtest-structure` Verification;
- read-only operator inspection;
- no production Task verification/completion, canonical adoption, signing, merge, release, generic keyboard/mouse, model-authored executable code, or autonomous self-improvement authority.

The v1 reward-hacking boundary explicitly keeps the synthetic player, telemetry producer, evaluator and production Task verifier as separate authority surfaces. Metric improvement is evidence, not proof of legitimate gameplay improvement, and any later optimization/refinement loop must operate against frozen capabilities and independent evaluation/acceptance authority.

See `docs/phase-24-automated-playtesting.md` for the detailed contract, threat boundary and acceptance tests.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before SHA-guarded merge.

## Phase 25 — Simulation Layer — DONE

Implemented the first governed cheap pre-implementation simulation substrate:

- infrastructure-format `SIMSPEC-*`, `SIM-*`, and `SIMWS-*` identities;
- immutable content-addressed specifications with exact `origin-forge-deterministic-sim:1` engine binding;
- finite signed-int32 state vectors and bounded declarative transition rules only;
- no Python/JavaScript/shell/arbitrary-expression/callback/process/network execution surface;
- deterministic `(priority, rule_id)` evaluation and SHA-256 probability draws over seed/replicate/step/rule identity rather than hidden runtime RNG state;
- explicit prerequisite, consumption and production semantics with overflow fail-closed behavior;
- implementation-aware 5,000,000-unit work budgeting over rule fields, mutation/bookkeeping and invariants;
- bounded replicates, steps, variables, rules and invariants;
- initial and post-full-step invariant checkpoints with exact violation counts, explicit truncation, at most 1,024 stored details per replicate and 8,192 across one governed result;
- no-progress/stall evidence based on net whole-step state change;
- independently bound result evidence rejecting inconsistent extrema, rule attempt/firing counts, unknown/mismatched invariant evidence, impossible checkpoints and duplicate/noncanonical stored violations;
- deterministic exact aggregate metrics using integer/rational evidence rather than floating-point acceptance semantics;
- protected fresh simulation workspaces and exact canonical `spec.json`, `result.json`, and `summary.json` evidence paths;
- 16 MiB per-file durable simulation evidence limit;
- durable `SIMULATION_SPEC`, `SIMULATION_RESULT`, and `SIMULATION_SUMMARY` Artifacts plus Run-level `simulation-structure` Verification;
- read-only `simulation_cli` inspection;
- explicit separation between negative simulation findings and simulator infrastructure failure;
- no production Task verification/completion, semantic balance authority, automatic tuning, config/asset adoption, signing, merge, release, or live self-improvement authority.

Phase 25 remains a cheap abstract evidence layer. Phase 24 runtime playtesting remains the stronger surface for real application behavior, and later Phase-26 refinement may consume frozen simulation metrics only under independent evaluation/acceptance authority.

See `docs/phase-25-simulation-layer.md` for the detailed v1 transition semantics, deterministic draw schedule, resource/evidence bounds, structural binding rules and exclusions.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before SHA-guarded merge.

## Phase 26 — Skill & Harness Workshop — DONE

Implemented a governed improvement-candidate workshop without live self-modification:

- infrastructure-owned `HIC-*`, `HPLAN-*`, `HREP-*`, `HAUD-*`, and `HDEC-*` identities;
- one bounded immutable target candidate over exact baseline/source-evidence hashes and inert canonical JSON payload data;
- independently frozen evaluation plans whose metrics, thresholds, evaluator protocol/evidence and cost ceilings are not candidate-controlled;
- exact regression-dominant task-metric and model-call/token/wall-time/resource-cost reports;
- infrastructure-owned trusted evaluator registry with exactly one promotion-capable v1 adapter: Phase-12 `paired-skill-ab-v1` Skill evaluation;
- fail-closed unsupported prompt/context/routing/specialist/mini-workflow evaluator families that may retain evidence but cannot create promotion eligibility;
- conservative Phase-12 Skill verdict composition so Phase 26 may become stricter but cannot reinterpret a Phase-12 regression/equivalence as stronger evidence;
- independent structural audits with exact candidate/plan/evaluation binding and explicit structural-vs-semantic separation;
- decision-time revalidation of candidate/plan/audit/evaluator authority, including exact Phase-12 evidence for Skill promotion, so forged `PASS` audit objects cannot amplify authority;
- `APPROVE_FOR_PROMOTION`, `REJECT`, and `DEFER` decisions where approval is only eligibility evidence and never activation authority;
- proposal-only Phase-15 Dream bridge preserving exact Dream ID/hash/type/downstream-gate evidence without satisfying that gate;
- immutable bounded symlink-safe canonical Workshop persistence with no-overwrite publication and load/list revalidation;
- read-only Workshop CLI exposing evidence and trusted-evaluator state;
- no active Skill/prompt/routing/context mutation, candidate activation, Task completion/verification, signing, merge, release, generic executable mini-workflow or model-weight authority.

Core rule:

```text
proposal → independent plan → trusted evidence → audit → promotion eligibility → STOP
```

See `docs/phase-26-skill-harness-workshop.md` for the detailed v1 contracts, trust registry, Dream bridge, persistence rules, decision-time authority checks and exclusions.

**Exit condition met:** Origin Forge can turn exact verified evidence into bounded independently evaluated improvement candidates, preserve stronger upstream Skill evidence, fail closed when no governed evaluator exists, record audited promotion eligibility without activating the candidate, and keep production truth/authority outside the Workshop.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before SHA-guarded merge.

## Phase 27 — Code Mode and Programmatic Context Experiments — DONE

Implemented a governed programmatic-context experiment substrate without introducing arbitrary model-written code execution:

- infrastructure-owned `CTXREQ-*`, `CTXCAT-*`, `CTXPROG-*`, `CTXEXEC-*`, `CTXPKG-*`, and `CTXEXP-*` identities;
- model-proposable inert straight-line programs over exact content-addressed read-only operation catalogs;
- infrastructure-owned request/catalog/identity/budget binding, with a strict proposal parser that rejects candidate-supplied authority metadata, duplicate JSON keys, unknown operations, forward references, rebinding and pathological values;
- no Python/JavaScript/shell/SQL/filesystem/network/process language surface, loops, recursion, dynamic operation names or generic Phase-13 `call_tool`;
- exact adapter fingerprints/schema hashes, call/response limits, READ_ONLY effect enforcement and replay classification;
- pre-dispatch scalar/JSON, per-call input, aggregate input, per-response, aggregate result and final-context bounds that prevent reference amplification and pathological serialization work;
- one real governed `runtime.run_show@1` adapter exposing only task-scoped terminal Run evidence through an explicit stable projection;
- canonical content-addressed per-step traces with exact input/output hashes and reconstructable final context packages;
- deterministic replay verification for `DETERMINISTIC` adapters and explicit refusal of exact-replay claims for `REVISION_BOUND` adapters;
- immutable no-overwrite programmatic-context persistence with symlink/root containment, duplicate-key rejection, byte/count limits and canonical/hash revalidation;
- regression-dominant paired baseline-vs-programmatic experiments over success, quality, model calls, tokens, context bytes, wall time and resource units;
- experiment classification revalidation preventing forged case/report verdicts and preventing two failed variants from winning solely through lower cost;
- read-only status/list/show CLI with all creation/execution/generic-code/tool/filesystem/SQL/network/process/Task/activation/promotion/signing/merge/release flags false;
- no Phase-26 trusted promotion adapter added by Phase 27 and no automatic activation path.

Core rule:

```text
model proposal → frozen read-only catalog → bounded interpreter → context evidence → benchmark
```

The accepted v1 deliberately stops short of a general-purpose code mode. Future operation adapters or richer program control flow require independent evidence that they improve reliability/cost without widening authority. Long-lived work continues to use durable Origin Forge state plus fresh bounded model invocations rather than a persistent autonomous process with private memory.

See `docs/phase-27-code-mode-programmatic-context.md` for the detailed contracts, replay boundary, resource limits, benchmark policy and exclusions.

**Exit condition met:** Origin Forge can execute a model-proposable finite read-only mini-program over an exact infrastructure-owned operation catalog, persist/reconstruct/replay-check the resulting context evidence, compare it against conventional context using regression-dominant metrics, and keep generic code/process/filesystem/Task/activation/promotion/signing/merge/release authority outside the experiment.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before SHA-guarded merge.

## Phase 28 — Cross-Media Watermarking and Fingerprinting — DONE

Implemented exact cross-media fingerprint and explicitly fragile derivative watermark evidence without weakening Phase-18 provenance:

- infrastructure-owned `MFPR-*`, `FPCMP-*`, `WMPLAN-*`, `WMRES-*`, and `FPLINK-*` identities;
- exact source-text fingerprinting with strict UTF-8 and line-ending-only normalization;
- exact raster fingerprinting over existing validated width/height + canonical RGBA8 pixel evidence;
- exact PCM16 fingerprinting over channels/sample-rate/frame-count + canonical PCM hash, ignoring ancillary WAV chunks;
- exact validated-byte GLB fingerprinting plus structural summary, with no re-export/mesh-reindex invariance claim;
- exact `EXACT_MATCH` / `DIFFERENT` / `INCOMPARABLE` comparison semantics and durable pre-publication classification revalidation;
- derivative-only PNG `ofWM` private ancillary mark classified `FRAGILE_METADATA`, preserving normalized raster pixels;
- separately invoked detector with `DETECTED` / `NOT_DETECTED` / `MISMATCH` evidence and plan/status revalidation;
- exact Phase-18 manifest Artifact ID/content-hash linkage without taking signature-verification authority;
- bounded immutable no-overwrite persistence with symlink/root/canonical/hash/referenced-evidence revalidation;
- strictly read-only CLI inspection;
- no authorship proof, perceptual/robust watermark claim, arbitrary path hashing/external executable/key access, Task verification/completion, adoption/signing, merge/release authority.

See `docs/phase-28-cross-media-watermarking.md` for the detailed v1 algorithms, fragile-mark boundary, provenance linkage, persistence rules and exclusions.

**Exit condition met:** Origin Forge can create, compare, persist and inspect exact fingerprints across source/raster/audio/validated-GLB media, create/detect one explicitly fragile derivative PNG mark, bind fingerprint evidence to Phase-18 Artifact provenance without verifying signatures itself, and keep production authority unchanged.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before SHA-guarded merge.

## Phase 29 — Training / Fine-Tuning Research — DONE

Implemented the governed data/evaluation substrate required before any real training backend can be considered:

- infrastructure-owned `TRAJ-*`, `TRAUD-*`, `TRDATA-*`, `TRPLAN-*`, and `TRREP-*` research identities;
- bounded canonical research trajectories with exact Task/Run/Verification evidence refs, explicit outcome class and no production-training/model-activation/Task authority;
- one trusted `origin-forge-runtime-redacted@1` producer that accepts only a task-scoped `SUCCEEDED` Run, terminal `SUCCEEDED` Task and `PASS` Task Verification bound to that exact Run;
- redacted runtime examples exposing only stable structural/cost metadata while excluding Task objective/acceptance/constraints, Verification evidence/metrics, failure text, repository content and arbitrary Artifact bytes;
- content-addressed producer identity and `verified-runtime-redacted-v1@1` eligibility policy;
- fail-closed producer trust/disclosure auditing: generic/manual trajectories, producer drift, protected evidence, forged eligibility and policy drift cannot enter durable v1 datasets;
- deterministic infrastructure-owned `80-10-10-v1` train/validation/test assignment from a frozen split-salt hash and leakage-group hash, with same-Task grouping and caller-forged split rejection;
- durable dataset publication requiring trusted governed trajectories, governed eligibility audits, exact v1 policy identity and full source/audit/split reconstruction;
- independently frozen experiment plans binding exact dataset, base-model/tokenizer, method family, trainer identity, independent evaluator identity, evaluation suite, resource ceilings and regression thresholds;
- candidate checkpoint reports containing only bounded checkpoint hash/size plus independent evaluation observations rather than executable/loadable weights;
- regression-dominant report classification over success, quality, critical failures, model calls, input/output tokens and wall time, with plan/evaluator/classification/checkpoint-limit revalidation;
- immutable no-overwrite `.origin-forge/training-research/` persistence with protected-root/symlink/alias, strict JSON, byte/count, canonical/hash and relational revalidation;
- strictly read-only research CLI exposing exact trusted producer/policy fingerprints and no dataset-build/training/download/checkpoint-load/model-profile/routing/secret/Task/promotion/signing/merge/release authority;
- no actual trainer, fine-tuning/LoRA/distillation process, trusted failed-attempt export, checkpoint loader, model-profile/routing activation or Phase-26 model-candidate promotion path in v1.

Core rule:

```text
verified history → trusted redacted producer → eligibility audit → leakage-safe dataset
        ↓
frozen experiment plan → candidate checkpoint evidence → independent evaluation → STOP
```

Phase-15 Dream remains symbolic consolidation rather than gradient training. Trainer identity in `TRPLAN-*` is an inert commitment for future research, not an executable training surface. Training loss alone is explicitly not promotion evidence.

See `docs/phase-29-training-finetuning-research.md` for the detailed trusted-producer contract, dataset/split governance, experiment/evaluator boundary, persistence rules and exclusions.

**Exit condition met:** Origin Forge can construct and persist only trusted redacted verified-runtime trajectories into deterministic leakage-safe datasets, freeze independent training/evaluation requirements, represent candidate checkpoint results as non-production evidence, recompute regression-dominant outcomes, inspect the chain read-only, and keep training execution, checkpoint activation, model/routing mutation, Task authority, Phase-26 promotion, signing, merge and release outside the research substrate.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before SHA-guarded merge.

## Phase 30 — Full Production Interface — DONE

Implemented the first bounded local production cockpit over proven Origin Forge infrastructure without creating a second truth or mutation layer:

- content-addressed bounded Goal / Flow / Task / Run / Task-Verification snapshots with explicit counts/truncation;
- dedicated immutable, non-creating core SQLite read guard requiring existing contained config/database, exact current schema, exact repository→project binding, and quiescent journal state;
- fail-closed uninitialized, stale-schema, aliased, symlinked, actively-written, and changing-database inspection paths with no automatic migration/checkpoint/repair;
- SELECT-only Project Intelligence / Design Bible projection through the same immutable DB boundary;
- causal Decision → Change → Artifact metadata → Verification-summary navigation;
- fresh non-loading model/resource configuration/admission monitoring with zero lease/routing mutation authority and no default-config creation;
- non-creating bounded public provenance inspection with canonical/hash validation while withholding secret material, DER/signature bytes, arbitrary Artifact bytes, Skill/tool lists, and fresh trust/currentness claims;
- non-creating bounded Dream/memory inspection with canonical/hash/containment validation while withholding raw evidence refs/finding messages and all promotion/execution authority;
- escaped static HTML under a strict no-script/no-form/no-network CSP;
- fixed loopback-only `127.0.0.1` HTTP routes with no arbitrary static/project file serving, conservative snapshot/response bounds, and controlled fail-closed overflow;
- operator surface limited to `snapshot` and `serve`;
- metadata-only Artifact inspection in v1; arbitrary byte/media previews remain outside the accepted surface;
- Verification evidence/metrics and approved command arrays remain withheld from the cockpit;
- no Task mutation/completion/retry, model/tool execution, Artifact adoption/signing, Dream promotion, merge, release, or remote/multi-user hosting authority.

See `docs/phase-30-full-production-interface.md` for the detailed read-side mutation boundary, presentation/network contract, authority exclusions, and closure proof.

**Exit condition met:** exact implementation head `1246fa9f7e9df8aa09c31b5c6e1cf8667f3759fa` passed normal GitHub Actions run `31456921293` on Python 3.12 and Python 3.13 with unrelated heavyweight evidence workflows skipped/disarmed; Origin Forge can inspect the accepted v1 production state through bounded non-creating projections without transferring production authority to the UI.

**Merge gate:** the canonical DONE/documentation head created after that implementation proof must itself pass the normal Python 3.12/3.13 matrix before ready-for-review transition and SHA-guarded merge.

## Phase 31 — Governed Production Planning & Dependency Graph — DONE

Implemented the Manager-side planning substrate needed to turn one durable Goal into a bounded cross-domain dependency graph without giving a Planner model production authority:

- infrastructure-owned `PLINPUT-*`, `PLPROP-*`, `PLAUD-*`, and `PLMAT-*` identities;
- frozen Goal-revision/hash-bound PlanningInput evidence with bounded verified/design-rule refs, Project Intelligence identity, capability catalog, and model/resource policy hashes;
- strict proposal-local PlanStep/PlanProposal contracts with duplicate-key-aware JSON parsing, finite task/edge/depth limits, capability binding, and deterministic DAG/topological evidence;
- independent structural PlanAudit recomputation;
- canonical same-Flow `REQUIRES_SUCCESS` Task dependencies in SQLite with foreign keys, uniqueness, self-edge, same-Flow, and recursive cycle defenses;
- immutable normalized planning input/proposal/audit/materialization evidence;
- explicit one-transaction audited-plan materialization allocating infrastructure-owned Flow/Task IDs and rolling back all partial state on failure;
- deterministic dependency readiness requiring canonical Task `SUCCEEDED` plus Task Verification `PASS`, with explicit waiting/failed/invalid/active/terminal evidence and no Task transition side effect;
- one-shot Task-less `PLANNER` Runs using the existing Phase-14 scheduled model/resource boundary, exact request/response/proposal evidence, and no implicit audit/materialization;
- Phase-30 immutable-SQLite-guard-based read-only planning evidence, graph, and readiness inspection with exact materialized Task/dependency drift detection;
- read-only `origin-forge-plan` module CLI exposing status/show/graph/readiness only;
- no automatic Task execution, recursive replanning, hidden queue, model self-verification, Artifact adoption/signing, Project Intelligence mutation, arbitrary model tool execution, cockpit mutation, merge, or release authority.

See `docs/phase-31-governed-production-planning.md` for the detailed implemented contract, evidence model, readiness semantics, model boundary, inspection surface, and slice-by-slice CI evidence.

**Exit condition met in implementation:** Phase-31 slices 31A–31G independently passed the normal Python 3.12/3.13 matrix through code head `eedd8a8699a57a856b9451c1be273e14edf856e4`; the canonical documentation/roadmap closure head created after those proofs must itself pass the final normal matrix before SHA-guarded merge.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before ready-for-review transition and SHA-guarded merge.

## Phase 32 — Governed Production Capability Catalog & Routing — DONE

Implemented the infrastructure-owned capability/routing layer required between a Phase-31 production plan and any future dependency-aware execution coordinator:

- infrastructure-owned `CAPCAT-*`, `CAPPOL-*`, and `CAPROUTE-*` identities;
- bounded semantic `ProductionCapability` contracts with exact capability IDs and no fuzzy/model-created capability authority;
- inert trusted production-adapter descriptors with exact contract fingerprints, effects/replay classes, and no shell/argv/import/callable/endpoint/secret/executable payload;
- immutable deterministic capability catalogs with duplicate/reference/bounds/hash validation;
- immutable exact-catalog-bound routing policies separated from inventory, preserving explicit ordered adapter allow-lists and no implicit fallback;
- exact canonical Task routing inputs bound to Flow ownership, objective, acceptance criteria, constraints, required capabilities, budgets, priority, revision, and content hash;
- deterministic pure static routing that considers only policy-listed adapters and requires one adapter to cover the complete Task capability set;
- explicit `ROUTABLE`, `UNKNOWN_CAPABILITY`, `CAPABILITY_NOT_ALLOWED`, `NO_ELIGIBLE_ADAPTER`, and `INVALID_TASK_CONTRACT` outcomes with bounded reasons;
- no hidden multi-adapter composition or registry-driven backend fallback;
- immutable no-overwrite `.origin-forge/production-capabilities/` catalog/policy/route evidence with canonical JSON, byte/count, duplicate-key, hash, symlink/alias, and relational validation;
- exact current-Task route revalidation plus frozen route-outcome recomputation that rejects self-consistently rehashed forged selected-adapter evidence;
- governed Phase-31 PlanningInput freeze deriving capability catalog hash and Planner-visible capability IDs from persisted catalog/policy authority rather than caller strings;
- reviewed built-in descriptors for bounded coding/retry, Pixelorama export, Blender 3D, image generation, vision inspection, FFmpeg processing, Piper TTS, runtime observation, cooperative playtesting, and deterministic simulation;
- known `design.specify` capability with no built-in executor, and no Blockbench adapter while Phase 20B remains deferred;
- non-creating read-only capability inspection through Phase-30 immutable SQLite reads and protected immutable evidence reads;
- read-only module CLI limited to `status`, `catalog-show`, `policy-show`, `route-show`, and `task-route`;
- no Task execution/transition, background queue, recursive replanning, model loading, resource lease, generic tool call, plugin install, Artifact adoption/signing, Project Intelligence mutation, cockpit mutation, merge, or release authority.

See `docs/phase-32-governed-production-capability-routing.md` for the detailed implemented contract, reviewed built-in inventory, persistence/read boundary, authority exclusions, and slice-by-slice CI evidence.

**Exit condition met in implementation:** Phase-32 slices 32A–32F independently passed the normal Python 3.12/3.13 matrix through code head `52e74952ef6b7b182893f6b478a9b097f0fc1ebb`; the canonical documentation/roadmap closure head created after those proofs must itself pass the final normal matrix before SHA-guarded merge.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before ready-for-review transition and SHA-guarded merge.

## Phase 33 — Governed Production Work Orders & Dispatch Contracts — DONE

Implemented the dispatch-input authority layer required between Phase-31 dependency readiness, Phase-32 routing, and any later production coordinator:

- infrastructure-owned `DISPCAT-*`, `WORKORD-*`, and `WORKAUD-*` identities;
- immutable dispatch-contract catalogs bound to exact Phase-32 capability catalogs and adapter fingerprints;
- code-owned trusted validator registry with inert exact payload schemas and no dynamic import/callable execution surface;
- immutable WorkOrders bound to exact Task revision/content, Flow, current `CAPROUTE-*`, selected adapter, dispatch catalog/contract, bounded evidence refs, and canonical normalized payload;
- independent frozen WorkOrder audits that recompute historical route/catalog/contract/validator/payload relations rather than trusting self-claimed PASS state;
- separate live currentness inspection reusing Phase-31 dependency-readiness semantics and current Phase-32 route derivation;
- one-shot taskless `WORK_ORDER_PLANNER` Runs through the existing scheduled-model boundary with strict duplicate-key/authority-field-aware proposal parsing and exact request/response/proposal/WorkOrder evidence;
- intentionally narrow reviewed built-in dispatch support: `originforge.code.bounded-retry` only; media/runtime adapters remain fail-closed until their phase-specific evidence inputs can be resolved generically without weakening authority;
- protected canonical no-overwrite `.origin-forge/production-work-orders/` persistence with byte/count, hash, symlink/alias, relation, frozen WorkOrder, and audit recomputation checks;
- Phase-30 immutable-SQLite-guard-based non-creating read-only inspection and CLI limited to status/catalog/contract/WorkOrder/audit/currentness views;
- no adapter invocation, Task transition/completion, background queue, generic tool execution, arbitrary shell/argv/import/callable authority, Artifact adoption/signing, Project Intelligence mutation, merge, release, or self-training authority.

See `docs/phase-33-governed-production-work-orders.md` for the finalized implementation contract, reviewed built-in boundary, persistence/currentness model, authority exclusions, and slice-by-slice CI evidence.

**Exit condition met in implementation:** Phase-33 slices 33A–33G independently passed the normal Python 3.12/3.13 matrix through code head `5f124d64466405106390c2f93c97e0068becb89b`; the canonical documentation/roadmap closure head created after those proofs must itself pass the final normal matrix before SHA-guarded merge.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before ready-for-review transition and SHA-guarded merge.

## Phase 34 — Governed Dispatch Input Resolution & Binding — DONE

Implemented the exact evidence-resolution and typed-request binding layer between audited Phase-33 WorkOrders and any later production coordinator while preserving the hard stop before backend execution:

- infrastructure-owned `INRES-*`, `DISPBIND-*`, and `BINDAUD-*` identities;
- deterministic trusted resolver contracts/fingerprints with ambiguous-claim rejection and exact original ref ID/hash/revision/role binding;
- core Artifact, Verification, Project Entity, and Design Rule resolvers plus one protected exact Audio Profile resolver;
- explicit fail-closed review for phase-specific evidence families lacking typed IDs, direct non-creating readers, or unambiguous exact claims;
- one exact typed binder for `originforge.code.bounded-retry` / `code.bounded-retry@1`, reconstructing the inert `BoundedRetryPolicy.drive@1` input projection without importing or calling the policy;
- independent binding audit and separate live currentness for resolver/binder/schema/WorkOrder/source/request drift;
- exact review of all ten Phase-32 built-in adapters, leaving nine media/runtime backends deferred with explicit missing-substrate blockers rather than silently promoting them;
- protected canonical no-overwrite `.origin-forge/production-dispatch-bindings/` persistence for input resolutions, bindings, and PASS audits with restart/tamper/symlink/cross-object revalidation;
- independent non-creating read-only inspection and CLI limited to status/show/currentness operations;
- no adapter/backend invocation, process/model/tool execution, resource lease, Task/Flow/Goal transition/completion, dispatch queue, arbitrary shell/argv/import/callable/endpoint authority, Artifact adoption/signing, Project Intelligence mutation, merge, release, or self-training authority.

See `docs/phase-34-governed-dispatch-input-resolution.md` for the finalized implementation contract, exact resolver/binder inventories, built-in deferral review, persistence/currentness model, authority exclusions, and slice-by-slice CI evidence.

**Exit condition met in implementation:** Phase-34 slices 34A–34F independently passed the normal Python 3.12/3.13 matrix through code head `b4ff1f5eb6c224c965cb7fa35a8ffffcbca72caa`; the canonical documentation/roadmap closure head created after those proofs must itself pass the final normal matrix before SHA-guarded merge.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before ready-for-review transition and SHA-guarded merge.

---

# v0.1 — First Useful Release

Target lifecycle:

```text
Human request
    ↓
Goal / Flow / Task
    ↓
Workspace snapshot
    ↓
Context selection
    ↓
Governed Skills
    ↓
Fresh Executor
    ↓
Patch Proposal
    ↓
Deterministic Apply
    ↓
Independent Audit
    ↓
Sandbox Build / Tests
    ↓
FAIL → bounded repair / escalation
PASS
    ↓
Verified durable state + provenance
    ↓
Human review / eventual merge
```

Success criteria:

- no dependency on long chat history
- process restart does not lose work state
- known-good project state remains isolated
- model cannot self-verify completion
- retries and no-progress loops are bounded
- selected context is reconstructable
- final diff is understandable
- meaningful changes have causal/provenance records

# v0.5 — Integrated Development Infrastructure

Target capabilities:

- durable long-running work
- local coding models
- governed Skills + Skill evaluation
- structural/LSP code intelligence
- progressive tool discovery
- model/resource scheduling
- offline memory consolidation and audited improvement proposals
- specialist review
- project graph + Design Bible
- cryptographic provenance
- basic 2D production

# v1.0 — Integrated Game Production

Representative Goal:

> Create a slow heavily armored enemy that lives in abandoned factories and attacks with a large mechanical hammer.

Origin Forge should eventually coordinate:

- design specification
- gameplay implementation
- behavior
- tests
- 2D/3D assets
- textures
- animation
- sound
- loot/configuration
- integration
- runtime verification
- provenance

while allowing the human creator to inspect, reject, refine, or replace any part.

# Explicit early non-goals

Do not prioritize early:

- polished GUI
- Kubernetes
- microservice decomposition
- giant agent swarms
- giant vector database
- custom foundation-model training
- arbitrary internet plugin marketplace
- fully autonomous one-prompt game creation

Build the smallest reliable production loop first.