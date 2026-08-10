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

**Exit condition met:** one immutable repository head proves on Python 3.12 and 3.13 that Origin Forge can launch an exact trusted target, bound logs/runtime outcomes/performance evidence, capture and independently validate only declared screenshots/timed video frames, emit deterministic baseline-regression evidence, persist/read that evidence, terminate descendant process state, and leave production Task/adoption/signing/merge/release authority unchanged.

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

The v1 reward-hacking boundary explicitly keeps the synthetic player, telemetry producer, evaluator and production Task verifier as separate authority surfaces. Metric improvement is evidence, not proof of legitimate gameplay improvement, and any later optimization/refinement loop must operate against frozen capabilities and independent evaluation.

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

## Phase 26 — Skill & Harness Workshop — PLANNED

Govern operational learning and harness refinement without live self-modification:

```text
verified trajectories / Dream candidates
→ minimal improvement candidate
→ isolated paired evaluation
→ regression suite
→ independent audit
→ approval
→ new immutable governed component version
```

Introduce a first-class Harness Improvement Candidate that can propose exactly one bounded target such as a Skill, prompt, context-selection strategy, routing policy, specialist contract, or sandboxed mini-workflow. Each candidate must bind its source trajectory/evidence hashes, target component/version, hypothesis, smallest relevant diff, expected metric effect, evaluation plan and known risks.

Old-vs-candidate evaluation must measure success/regression together with model calls, tokens, wall time and resource cost. A candidate cannot choose its own acceptance metric, verify itself, activate itself, or silently replace the governing component. Dream Cycle findings may enter this pipeline, but active agents and Dream processes remain proposal-only.

## Phase 27 — Code Mode and Programmatic Context Experiments — PLANNED

Benchmark sandboxed model-written mini-workflows that combine multiple authorized operations without returning to the model between every operation. Enable only where measured reliability or cost improves.

Also evaluate bounded programmatic context access over governed APIs such as artifact/run search, failed-attempt lookup, Entity context, memory search, Skill description and Tool discovery instead of dumping long histories into one model context. Do not expose unrestricted SQL, arbitrary filesystem traversal, hidden persistent scratch state, or generic process authority.

Long-lived work should prefer durable specialist jobs plus fresh isolated model invocations over persistent autonomous model processes with private evolving memory. The durable job/evidence persists; each model invocation receives a reconstructable bounded package. Recursive delegation may never amplify authority beyond the parent contract.

## Phase 28 — Cross-Media Watermarking — PLANNED

Develop source/image/audio/3D watermark and fingerprint adapters. Watermarks complement cryptographic manifests and never become the sole proof of origin.

## Phase 29 — Training / Fine-Tuning Research — PLANNED

Only after a substantial verified trajectory dataset exists, investigate routing models, specialized tool-use models, coding-agent fine-tuning, infrastructure-native agents, and offline distillation from verified trajectories and audited Dream outcomes.

Symbolic Dream consolidation remains separate from neural weight training. Production models do not rewrite their own weights.

## Phase 30 — Full Production Interface — PLANNED

Build the polished visual environment around proven infrastructure: project/entity browser, Goal/Flow/Task graph, Design Bible, Artifact previews, verification evidence, provenance inspector, model/resource monitor, Dream/memory-generation inspector, and causal “why does this exist?” history.

The UI stays late so early architecture is not distorted around a premature frontend.

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